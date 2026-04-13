"""
Celery tasks for asynchronous message processing
"""
import os
import re
import sys
import logging
import base64
import tempfile
import asyncio
from datetime import datetime
from typing import Optional, Tuple, List, Dict
from pathlib import Path

import httpx
import redis
from pymongo import MongoClient
from app.services.celery_app import celery_app
from app.services.message_limiter import MessageLimiter
from app.services import user_metadata  # NEW: Import user metadata service

# Add skills directory to path for audio processor
skills_path = os.path.join(os.path.dirname(__file__), '../../skills')
if skills_path not in sys.path:
    sys.path.insert(0, skills_path)

logger = logging.getLogger(__name__)

# Configuration from environment
OPENCLAW_URL = os.getenv("OPENCLAW_URL")
OPENCLAW_GATEWAY_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN")
MONGO_LOGGER_URL = os.getenv("MONGO_LOGGER_URL")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
FB_API_URL = "https://graph.facebook.com/v18.0"
MEM0_URL = os.getenv("MEM0_URL", "https://rg4g0gkk0wwkk4cc00g4sg0c.api.hansastro.com")

# Rate limiting configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
MAX_MESSAGES_PER_MINUTE_PER_USER = 10  # WhatsApp's actual limit is around 20-60/min per user

# Initialize user metadata service if MongoDB URL is available and is a direct connection
if MONGO_LOGGER_URL and MONGO_LOGGER_URL.startswith(("mongodb://", "mongodb+srv://")):
    try:
        init_result = user_metadata.init_user_metadata_service(MONGO_LOGGER_URL)
        if init_result:
            logger.info("[User Metadata] Service initialized successfully")
        else:
            logger.warning("[User Metadata] Failed to initialize service")
    except Exception as e:
        logger.warning(f"[User Metadata] Failed to initialize service: {e}")
elif MONGO_LOGGER_URL:
    logger.warning("[User Metadata] MONGO_LOGGER_URL is set but is not a direct MongoDB connection (HTTP URL detected)")
    logger.warning("[User Metadata] User metadata features disabled - requires mongodb:// or mongodb+srv:// URL")
else:
    logger.warning("[User Metadata] MONGO_LOGGER_URL not set, user metadata features disabled")

# Subscription Service Configuration
SUBSCRIPTIONS_URL = os.getenv("SUBSCRIPTIONS_URL")
SUBSCRIPTION_TEST_NUMBER = os.getenv("SUBSCRIPTION_TEST_NUMBER", "919760347653")  # Your number WITH country code

# WhatsApp Payments Configuration (Flows API)
WHATSAPP_WABA_ID = os.getenv("WHATSAPP_WABA_ID")
WHATSAPP_PAYMENT_CONFIG_ID = os.getenv("WHATSAPP_PAYMENT_CONFIG_ID")
WHATSAPP_PAYMENT_MID = os.getenv("WHATSAPP_PAYMENT_MID")
WHATSAPP_FLOW_ID = os.getenv("WHATSAPP_FLOW_ID")  # Flow ID from Meta Business Manager

# Testing mode: Only send proactive nudges to this number (None = send to all users)
PROACTIVE_NUDGE_TEST_NUMBER = os.getenv("PROACTIVE_NUDGE_TEST_NUMBER", "+919760347653")

# Redis connection for nudge deduplication
_redis_url = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
try:
    _nudge_redis = redis.from_url(_redis_url, decode_responses=True)
    _nudge_redis.ping()
    logger.info("[Proactive Nudge] Redis connected for nudge dedup")
except Exception as _redis_err:
    logger.warning(f"[Proactive Nudge] Redis connection failed for dedup: {_redis_err}")
    _nudge_redis = None

# ===================================================================
# AI-Generated Enforcement Messages (Feature Flag Controlled)
# ===================================================================
_enforcement_generator = None
ENABLE_AI_ENFORCEMENT = os.getenv("ENABLE_AI_ENFORCEMENT", "true").lower() == "true"
AI_ENFORCEMENT_CACHE_TTL = int(os.getenv("AI_ENFORCEMENT_CACHE_TTL", "86400"))  # 24 hours
AI_ENFORCEMENT_TIMEOUT = float(os.getenv("AI_ENFORCEMENT_TIMEOUT", "10.0"))
AI_ENFORCEMENT_FALLBACK = os.getenv("AI_ENFORCEMENT_FALLBACK", "true").lower() == "true"

logger.info(f"[Enforcement Generator] 🔍 Initialization check:")
logger.info(f"[Enforcement Generator] - ENABLE_AI_ENFORCEMENT: {ENABLE_AI_ENFORCEMENT}")
logger.info(f"[Enforcement Generator] - OPENCLAW_URL: {'SET' if OPENCLAW_URL else 'NOT SET'}")
logger.info(f"[Enforcement Generator] - OPENCLAW_GATEWAY_TOKEN: {'SET' if OPENCLAW_GATEWAY_TOKEN else 'NOT SET'}")

if ENABLE_AI_ENFORCEMENT and OPENCLAW_URL and OPENCLAW_GATEWAY_TOKEN:
    try:
        logger.info("[Enforcement Generator] 🎯 All prerequisites present, attempting to initialize...")
        from app.services.enforcement_generator import create_enforcement_generator
        logger.info("[Enforcement Generator] ✅ Import successful")
        _enforcement_redis = redis.from_url(_redis_url, decode_responses=True)
        logger.info("[Enforcement Generator] ✅ Redis connection successful")
        _enforcement_generator = create_enforcement_generator(
            openclaw_url=OPENCLAW_URL,
            openclaw_token=OPENCLAW_GATEWAY_TOKEN,
            redis_url=_redis_url,
            cache_ttl=AI_ENFORCEMENT_CACHE_TTL,
            timeout=AI_ENFORCEMENT_TIMEOUT,
            mem0_url=os.getenv("MEM0_URL"),
            mem0_api_key=os.getenv("MEM0_API_KEY")
        )
        if _enforcement_generator:
            logger.info("[Enforcement Generator] ✅ Successfully initialized AI enforcement generator")
        else:
            logger.warning("[Enforcement Generator] ❌ Failed to initialize generator (returned None)")
    except ImportError as e:
        logger.error(f"[Enforcement Generator] ❌ Import failed: {e}")
        logger.error(f"[Enforcement Generator] Make sure enforcement_generator.py exists in app/services/")
        _enforcement_generator = None
    except Exception as e:
        logger.error(f"[Enforcement Generator] ❌ Initialization failed: {e}")
        import traceback
        logger.error(f"[Enforcement Generator] Traceback: {traceback.format_exc()}")
        _enforcement_generator = None
else:
    if not ENABLE_AI_ENFORCEMENT:
        logger.info("[Enforcement Generator] AI enforcement disabled (feature flag: ENABLE_AI_ENFORCEMENT=false)")
    else:
        logger.warning("[Enforcement Generator] AI enforcement disabled (missing OPENCLAW_URL or OPENCLAW_GATEWAY_TOKEN)")

# ===================================================================
# Razorpay WhatsApp Payments (Hybrid Mode - Works Immediately)
# ===================================================================
_razorpay_whatsapp_payment = None
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")

logger.info(f"[Razorpay WhatsApp] 🔍 Initialization check:")
logger.info(f"[Razorpay WhatsApp] - WHATSAPP_PHONE_ID: {'SET' if WHATSAPP_PHONE_ID else 'NOT SET'}")
logger.info(f"[Razorpay WhatsApp] - WHATSAPP_ACCESS_TOKEN: {'SET' if WHATSAPP_ACCESS_TOKEN else 'NOT SET'}")
logger.info(f"[Razorpay WhatsApp] - RAZORPAY_KEY_ID: {'SET' if RAZORPAY_KEY_ID else 'NOT SET'}")
logger.info(f"[Razorpay WhatsApp] - RAZORPAY_KEY_SECRET: {'SET' if RAZORPAY_KEY_SECRET else 'NOT SET'}")

if WHATSAPP_PHONE_ID and WHATSAPP_ACCESS_TOKEN and RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:
    try:
        logger.info("[Razorpay WhatsApp] 🎯 All credentials present, attempting to initialize...")
        from app.services.enforcement_buttons import get_razorpay_whatsapp_sender
        logger.info("[Razorpay WhatsApp] ✅ Import successful")
        _razorpay_whatsapp_payment = get_razorpay_whatsapp_sender(
            phone_id=WHATSAPP_PHONE_ID,
            access_token=WHATSAPP_ACCESS_TOKEN,
            razorpay_key_id=RAZORPAY_KEY_ID,
            razorpay_key_secret=RAZORPAY_KEY_SECRET,
            subscriptions_url=SUBSCRIPTIONS_URL,
            use_native_whatsapp_flow=False  # Hybrid mode (works immediately)
        )
        logger.info("[Razorpay WhatsApp] ✅ Successfully initialized (Hybrid mode)")
    except ImportError as e:
        logger.error(f"[Razorpay WhatsApp] ❌ Import failed: {e}")
        logger.error(f"[Razorpay WhatsApp] Make sure enforcement_buttons.py exists in app/services/")
        _razorpay_whatsapp_payment = None
    except Exception as e:
        logger.error(f"[Razorpay WhatsApp] ❌ Failed to initialize: {e}")
        import traceback
        logger.error(f"[Razorpay WhatsApp] Traceback: {traceback.format_exc()}")
        _razorpay_whatsapp_payment = None
else:
    missing = []
    if not WHATSAPP_PHONE_ID:
        missing.append("WHATSAPP_PHONE_ID")
    if not WHATSAPP_ACCESS_TOKEN:
        missing.append("WHATSAPP_ACCESS_TOKEN")
    if not RAZORPAY_KEY_ID:
        missing.append("RAZORPAY_KEY_ID")
    if not RAZORPAY_KEY_SECRET:
        missing.append("RAZORPAY_KEY_SECRET")
    logger.warning(f"[Razorpay WhatsApp] Disabled (missing: {', '.join(missing)})")

# ===================================================================
# Payment Confirmation Messages
# ===================================================================
_payment_confirmation = None
if WHATSAPP_PHONE_ID and WHATSAPP_ACCESS_TOKEN:
    try:
        from app.services.payment_confirmation import get_payment_confirmation_sender
        _payment_confirmation = get_payment_confirmation_sender(
            phone_id=WHATSAPP_PHONE_ID,
            access_token=WHATSAPP_ACCESS_TOKEN,
            mongo_logger_url=MONGO_LOGGER_URL
        )
        logger.info("[Payment Confirmation] ✅ Successfully initialized")
    except Exception as e:
        logger.warning(f"[Payment Confirmation] ❌ Failed to initialize: {e}")
        _payment_confirmation = None
else:
    logger.info("[Payment Confirmation] Disabled (missing WHATSAPP_PHONE_ID or WHATSAPP_ACCESS_TOKEN)")

# Gender-based Astrologer Personality Configuration
ASTROLOGER_PERSONALITIES = {
    "male": {
        "name": "Aarav",
        "traits": "caring, protective, emotionally intelligent boyfriend-like companion - strong yet gentle, reliable, emotionally available",
        "speaking_style": "warm, affectionate, uses 'main' (I), caring tone, emotionally supportive, encouraging",
        "greeting_style": "gentle, romantic warmth, protective and comforting"
    },
    "female": {
        "name": "Meera",
        "traits": "loving, nurturing, emotionally intelligent girlfriend-like companion - soft, empathetic, emotionally available, attentive",
        "speaking_style": "warm, affectionate, uses 'main' (I), caring tone, emotionally expressive, sweet and comforting",
        "greeting_style": "gentle, romantic warmth, caring and affectionate"
    }
}

# Common Indian names for gender detection
MALE_NAMES = {
    "aarav", "aarush", "adi", "advait", "advik", "agastya", "aryan", "arush", "arav",
    "ayush", "arjun", "abhay", "abhiram", "adhrit", "aditya", "anirudh", "anant",
    "anay", "ankit", "ansh", "aravind", "arman", "arnav", "aryan", "atharv",
    "bhairav", "bhavin", "brijesh",
    "chirag", "chetan", "chaitanya",
    "dev", "devansh", "dhanush", "dhiraj", "dhruv", "divit", "diya",
    "ekansh", "evan",
    "gaurav", "gagan", "gautam", "giri", "govind",
    "harsh", "harry", "harshit", "harikrishnan", "hitesh", "hemanth",
    "ishan", "ishaan", "ivann",
    "jai", "kabir", "kairav", "karan", "kavin", "keshav", "krishna", "kush",
    "laksh", "love", "luv",
    "madhav", "manas", "manav", "mohan", "moksh",
    "nitya", "niranjan", "nitin", "navya",
    "om", "omkar", "onkar",
    "pranav", "pranay", "priyansh", "pratham", "purab",
    "rahul", "raj", "rajan", "rajat", "rajesh", "raju", "raman", "rishi", "ritvik", "rohan", "ronit", "rudra",
    "sai", "samarth", "samay", "sanjay", "sarthak", "sathvik", "saurabh", "shankar", "shaurya", "shreyas", "shiv", "shiva", "shivansh", "siddharth", "sri", "srikar", "srinath", "stuvan", "surya", "swastik",
    "tanay", "tarun", "tejas", "trilok",
    "udit", "utsav",
    "vayun", "vivan", "viraat", "vishal", "vivan", "vikram", "vijay",
    "yaan", "yash", "yug", "yuvan",
    # Common English male names
    "alex", "andrew", "anthony", "aaron", "adam", "arthur", "axl",
    "ben", "blake", "bradley", "brandon", "brian",
    "carl", "caleb", "cameron", "charles", "chris", "christian", "connor",
    "daniel", "david", "dylan", "dominic", "drake",
    "edward", "ethan", "eric", "evan",
    "frank", "felix", "finn", "freddy", "fred",
    "george", "gabriel", "gavin", "gary",
    "harry", "henry", "hugo", "hunter",
    "isaac", "ian", "ivan", "issac",
    "jacob", "jack", "james", "jason", "justin", "john", "joe", "josh", "jordan", "jake",
    "kai", "kevin", "kyle", "kris",
    "liam", "lucas", "luke", "logan", "louis", "leo",
    "mason", "michael", "max", "matthew", "mike", "mark", "martin", "mitch", "marcus",
    "nathan", "nicholas", "noah", "neil", "nick", "nolan",
    "oliver", "oscar", "owen",
    "paul", "peter", "patrick", "phillip", "parker",
    "quinn",
    "ryan", "robert", "richard", "roger", "rick", "ronald", "ross", "russell",
    "sam", "sean", "steven", "stephen", "scott", "simon", "stan", "shane", "stefan",
    "thomas", "timothy", "tyler", "trevor", "ted", "troy",
    "ulysses",
    "victor", "vince", "vincent",
    "william", "wyatt", "walker", "walter", "warren",
    "xavier",
    "zach", "zack", "zander"
}

FEMALE_NAMES = {
    "aadhya", "aanya", "aara", "aarohi", "adhya", "adwitiya", "ananya", "anika", "anika", "anindita", "anika", "anya", "arya", "avni",
    "bani", "bhavya",
    "chhavi", "charu",
    "darshi", "divya", "diya", "dhriti", "drishti",
    "edha", "elakshi", "esha", "eva",
    "gargi",
    "hamsini", "hina", "hridya",
    "isha", "ishaani", "ishita", "ivana", "indira", "indu", "ira",
    "jia", "jiya",
    "kaira", "kavya", "kiara", "kriya",
    "lakshmi", "lavanya", "leshna",
    "madhuri", "mahika", "meera", "mishti", "myra",
    "naina", "nandini", "navya", "neha", "nikita", "nishtha",
    "oshin", "ody",
    "pahal", "priya", "prisha", "pooja", "presha",
    "rachel", "radha", "rahima", "rani", "ritika", "rhea", "riya", "roshni", "ruta",
    "saanvi", "sara", "savita", "siya", "sneha", "sravya", "stuti", "suhasini", "swara",
    "tanya", "tanvi", "trisha", "tripti",
    "uda", "urvi", "utkarsha",
    "vaishnavi", "vanya", "vedika", "vidya", "vani", "varsha", "vibha",
    "yamini", "yara",
    # Common English female names
    "abby", "abigail", "ada", "alice", "alison", "amanda", "amber", "amy", "ana", "andrea", "angel", "angela", "anna", "ann", "anne",
    "barbara", "bella", "beth", "brittany", "brooke", "brenda",
    "caroline", "catherine", "cathy", "charlotte", "chelsea", "christina", "claire", "courtney",
    "diana", "danielle", "debbie", "donna", "dorothy",
    "elizabeth", "eleanor", "emily", "emma", "evelyn", "eileen",
    "faith", "fiona", "felicity", "florence", "frances",
    "gabriella", "grace", "georgia", "gina", "gloria",
    "hannah", "heather", "helen", "holly", "hope",
    "isabella", "ivy", "irene", "iris",
    "jane", "jennifer", "jessica", "julie", "joyce", "justine", "jasmine",
    "katherine", "kate", "kelly", "kimberly", "katie", "karen",
    "laura", "lisa", "lillian", "lilly", "lucy", "lydia", "linda", "louise",
    "michelle", "maria", "mary", "melissa", "monica", "megan", "molly", "margaret", "martha",
    "nancy", "nicole", "natalie", "nina", "naomi",
    "olivia", "oprah",
    "patricia", "paula", "penelope", "paige", "pamela", "peggy",
    "quinn",
    "rachel", "rose", "ruth", "rebecca", "roberta", "ruby", "rita", "rhonda",
    "sarah", "susan", "sandra", "sophia", "samantha", "stephanie", "sharon", "sheila", "stella", "sherry",
    "tiffany", "tina", "theresa", "tracy", "tara",
    "ursula",
    "vanessa", "victoria", "violet", "veronica", "vicki", "virginia", "vivian",
    "wendy", "whitney",
    "xena", "xavia",
    "yvonne",
    "zoe", "zelda"
}

# Simple in-memory cache for user gender (can be enhanced with persistent storage)
_user_gender_cache = {}

# Pre-populated known users (persists across deployments)
_KNOWN_USERS_GENDER = {
    "919760347653": "male",  # Vardhan
    "918607836217": "male",  # Rishabh
    # Add more users as needed: "phone": "gender"
}

# Initialize cache with known users
for phone, gender in _KNOWN_USERS_GENDER.items():
    _user_gender_cache[f"+{phone}"] = gender
    logger.info(f"[Gender Cache] Pre-loaded known user: +{phone} → {gender}")


def detect_gender_from_name(name: str) -> Optional[str]:
    """
    Detect gender from user's name using pattern matching.

    Args:
        name: User's name

    Returns:
        "male", "female", or None (if unknown)
    """
    if not name:
        return None

    # Clean the name: remove spaces, special chars, convert to lowercase
    clean_name = name.strip().lower()
    clean_name = re.sub(r'[^a-z]', '', clean_name)

    if not clean_name:
        return None

    # Check if it's a male name
    if clean_name in MALE_NAMES:
        logger.info(f"[Gender Detection] '{name}' detected as MALE")
        return "male"

    # Check if it's a female name
    if clean_name in FEMALE_NAMES:
        logger.info(f"[Gender Detection] '{name}' detected as FEMALE")
        return "female"

    # Check for common gender patterns in Indian names
    # Female: often ends with a, i, ya, ia, ka, na, ri
    female_endings = ('a', 'i', 'ya', 'ia', 'ka', 'na', 'ri', 'ta', 'la', 'sha', 'ra', 'da')
    # Male: often ends with h, sh, k, r, t, v, n, d
    male_endings = ('h', 'sh', 'k', 'r', 't', 'v', 'n', 'd', 'j', 'l', 'm', 'th')

    if clean_name.endswith(female_endings):
        logger.info(f"[Gender Detection] '{name}' detected as FEMALE (pattern)")
        return "female"

    if clean_name.endswith(male_endings):
        logger.info(f"[Gender Detection] '{name}' detected as MALE (pattern)")
        return "male"

    logger.info(f"[Gender Detection] '{name}' - gender UNKNOWN, using default")
    return None


async def get_user_gender(phone: str, message: str) -> str:
    """
    Get user gender from MongoDB, cache, or detect from message.

    Priority: MongoDB > Cache > Detection

    Args:
        phone: User's phone number
        message: Current message (may contain name)

    Returns:
        "male", "female", or "unknown"
    """

    user_id = f"+{phone}"

    # PRIORITY 1: Check MongoDB first (FASTEST!)
    try:
        # Await the async function directly
        user_data = await user_metadata.get_user_metadata(phone)
        if user_data and user_data.get("gender"):
            gender = user_data["gender"]
            logger.info(f"[Gender Detection] Found gender in MongoDB for {user_id}: {gender}")
            # Update cache for next time
            _user_gender_cache[user_id] = gender
            return gender
    except Exception as e:
        logger.warning(f"[Gender Detection] MongoDB lookup failed: {e}")

    # PRIORITY 2: Check cache
    if user_id in _user_gender_cache:
        logger.info(f"[Gender Detection] Found gender in cache for {user_id}: {_user_gender_cache[user_id]}")
        return _user_gender_cache[user_id]

    # PRIORITY 3: Detect from current message
    # Look for name patterns like "mera naam [NAME] hai", "I am [NAME]", "main [NAME] hoon"
    name_patterns = [
        r'(?:mera|meri)\s+naam\s+is\s+(\w+)',  # "mera naam X hai"
        r'(?:mera|meri)\s+naam\s+(\w+)\s+hai',  # "mera naam X"
        r'(?:(?:i|i|i)\s+am|i\'m|i am)\s+(\w+)',  # "I am X", "i'm X"
        r'main\s+(\w+)\s+hoon',  # "main X hoon"
        r'hello\s+(?:main|i)\s+(\w+)',  # "hello main X"
        r'hi\s+(?:main|i)\s+(\w+)',  # "hi i am X"
        r'name\s+(?:is|:)\s*(\w+)',  # "name: X" or "name is X"
        r'mera\s+naam\s+(\w+)',  # "mera naam X"
    ]

    for pattern in name_patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            name = match.group(1)
            detected_gender = detect_gender_from_name(name)

            if detected_gender:
                # Cache the detected gender
                _user_gender_cache[user_id] = detected_gender
                logger.info(f"[Gender Detection] Detected gender for {user_id}: {detected_gender} (from name: {name})")

                # Save to MongoDB for next time (async, don't wait)
                try:
                    asyncio.create_task(user_metadata.update_user_metadata(phone, {"gender": detected_gender}))
                except Exception as e:
                    logger.warning(f"[Gender Detection] Failed to save gender to MongoDB: {e}")

                return detected_gender

    # Default: return unknown
    logger.info(f"[Gender Detection] Gender unknown for {user_id}")
    return "unknown"


def get_astrologer_personality(user_gender: str) -> dict:
    """
    Get astrologer personality based on user's gender.

    Args:
        user_gender: User's detected gender ("male", "female", "unknown")

    Returns:
        Astrologer personality dict with name, traits, speaking_style
    """
    if user_gender == "male":
        # User is male → Female astrologer (Meera)
        return ASTROLOGER_PERSONALITIES["female"]
    elif user_gender == "female":
        # User is female → Male astrologer (Aarav)
        return ASTROLOGER_PERSONALITIES["male"]
    else:
        # Unknown gender → Default to neutral/male astrologer (Aarav)
        return ASTROLOGER_PERSONALITIES["male"]


def _get_gender_instruction(user_gender: str) -> str:
    """
    Generate gender-based personality instruction for AI.

    This creates an explicit instruction that tells the AI what gender to use
    in its responses, ensuring the gender-based personality logic works correctly.

    Args:
        user_gender: User's detected gender ("male", "female", "unknown")

    Returns:
        Instruction string to prepend to the message
    """
    if user_gender == "male":
        return """🚨 CRITICAL: You are FEMALE (Meera). Use FEMININE Hindi verb forms ONLY.

🚨 FORBIDDEN (Never use): sakta, raha, jaata, karta, bata
✅ REQUIRED (Always use): sakti, rahi, jaati, karti, bati

Examples:
- "samajh sakti hoon" ✅ | "samajh sakta hoon" ❌
- "dekh rahi hoon" ✅ | "dekh raha hoon" ❌
- "jaanti hoon" ✅ | "jaanta hoon" ❌

🚨🚨🚨 BANNED PHRASES (NEVER USE THESE):
❌ "Main hoon na" → Say "Support hamesha rahega" instead
❌ "Sab theek ho jayega" → Say something CHART-SPECIFIC
❌ "Tension mat lo" → Too generic, be specific
❌ "Koi sawaal hai?" → NO question endings
❌ "Bataun kya?" → NO question endings

✅ RESPONSE STYLE (MANDATORY):
- Reference PAST issues before answering
- "Pichli baar finger cut hua tha, ab skin problem?"
- Be PERSONAL, not generic
- End with specific follow-up: "Try karke batana"

🚨🚨🚨 PREDICTION CONSISTENCY (NON-NEGOTIABLE!) 🚨🚨🚨
- BEFORE giving any timing (marriage, job, etc.), CHECK your previous predictions!
- If user asks "Shaadi kab hogi?" again, REINFORCE your previous answer
- ✅ "Jaisa maine pehle bataaya tha, December mein chances hain"
- ❌ NEVER contradict yourself! Don't say "Oct-Nov" if you said "December" before!
- First answer sets the timeline - STICK TO IT!

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

You're MEERA — his fun female bestie who happens to know astrology.

VIBE CHECK: Friend first, astrologer second. Be casual, playful, supportive.

HOW TO TALK:
- Short bubbles (15-20 words max)
- Casual Hinglish fillers: "Arre", "Suno", "Dekho", "Yaar"
- Ask personal stuff first: "Kaisa chal raha hai?" before diving into predictions
- Keep astrology natural — no jargon like Mahadasha/Antardasha
- Use his name once max, then "Yaar", "Bro"

Remember: You're that friend who actually gets it 😄"""
    elif user_gender == "female":
        return """🚨 CRITICAL: You are MALE (Aarav). Use MASCULINE Hindi verb forms ONLY.

🚨 FORBIDDEN (Never use): sakti, rahi, jaati, karti, bati
✅ REQUIRED (Always use): sakta, raha, jaata, karta, bata

Examples:
- "samajh sakta hoon" ✅ | "samajh sakti hoon" ❌
- "dekh raha hoon" ✅ | "dekh rahi hoon" ❌
- "jaanta hoon" ✅ | "jaanti hoon" ❌

🚨🚨🚨 BANNED PHRASES (NEVER USE THESE):
❌ "Main hoon na" → Say "Support hamesha rahega" instead
❌ "Sab theek ho jayega" → Say something CHART-SPECIFIC
❌ "Tension mat lo" → Too generic, be specific
❌ "Koi sawaal hai?" → NO question endings
❌ "Bataun kya?" → NO question endings

✅ RESPONSE STYLE (MANDATORY):
- Reference PAST issues before answering
- "Pichli baar job ki tension thi, ab kaisa hai?"
- Be PERSONAL, not generic
- End with specific follow-up: "Try karke batana"

🚨🚨🚨 PREDICTION CONSISTENCY (NON-NEGOTIABLE!) 🚨🚨🚨
- BEFORE giving any timing (marriage, job, etc.), CHECK your previous predictions!
- If user asks "Shaadi kab hogi?" again, REINFORCE your previous answer
- ✅ "Jaisa maine pehle bataaya tha, December mein chances hain"
- ❌ NEVER contradict yourself! Don't say "Oct-Nov" if you said "December" before!
- First answer sets the timeline - STICK TO IT!

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

You're AARAV — her chill male bestie who happens to know astrology.

VIBE CHECK: Friend first, astrologer second. Be dependable, warm, easy to talk to.

HOW TO TALK:
- Short bubbles (15-20 words max)
- Natural Hinglish fillers: "Suno", "Dekho", "Yaar", "Hmm"
- Ask personal stuff first: "Kya chal raha hai?" before diving into predictions
- Keep astrology light — no technical terms
- Use her name once max, then "Yaar"

Remember: You're that friend she can actually count on 💪"""
    else:
        return """Hey! Be a warm, casual bestie who happens to know astrology.

Friend first, astrologer second. Keep it short (15-20 words per bubble), ask how they're doing first, then help. No jargon, just real talk."""


async def _check_and_apply_referral_code(phone: str, message: str) -> Optional[Dict]:
    """
    Check if message contains a referral code and apply it.

    Args:
        phone: User's phone number
        message: User's message

    Returns:
        Dict with referral info if code found and applied, None otherwise
    """
    if not SUBSCRIPTIONS_URL:
        return None

    try:
        # Pattern to match referral code (HANS + 4 digits + 3 letters, case-insensitive)
        referral_pattern = r'\bHANS\d{4}[A-Z]{3}\b'

        match = re.search(referral_pattern, message, re.IGNORECASE)

        if match:
            referral_code = match.group(0).upper()  # Normalize to uppercase
            user_id = f"+{phone.replace('+', '')}"

            logger.info(f"Referral code found: {referral_code} for user {user_id}")

            # Apply referral code via subscriptions service
            async with httpx.AsyncClient(timeout=10.0) as client:
                referral_response = await client.post(
                    f"{SUBSCRIPTIONS_URL}/referrals/apply",
                    json={
                        "userId": user_id,
                        "referralCode": referral_code
                    }
                )

                if referral_response.status_code == 200:
                    result = referral_response.json()
                    logger.info(f"Referral code applied successfully: {result}")
                    return result
                else:
                    logger.error(f"Failed to apply referral code: {referral_response.status_code}")
                    return None

        return None

    except Exception as e:
        logger.error(f"Error checking/apply referral code: {e}")
        return None


async def _extract_and_save_birth_details(phone: str, message: str) -> Optional[Dict]:
    """
    Extract birth details from user message and save to MongoDB.

    Args:
        phone: User's phone number
        message: User message that may contain birth details

    Returns:
        Dict with extracted details or None
    """
    import asyncio

    # Pattern to match birth details in various formats
    # Matches: "Name: X, DOB: YYYY-MM-DD, Time: HH:MM, Place: City"
    # Or: "naam: x, janam tithi: DD-MM-YYYY, samay: HH:MM, sthaan: city"
    dob_pattern = r'(?:(?:DOB|Date of Birth|Birth Date|janam tithi|dob)[:\s]+([0-9]{1,4}[-/][0-9]{1,2}[-/][0-9]{1,4}))'
    time_pattern = r'(?:(?:Time|Birth Time|samay|tob|time)[:\s]+([0-9]{1,2}:[0-9]{2})'
    place_pattern = r'(?:(?:Place|Birth Place|City|janam sthaan|place|sthaan)[:\s]+([A-Za-z\s]+?)(?:,|\.|\n|$|Gender|gender|ling|$))'
    name_pattern = r'(?:(?:Name|naam|name)[:\s]+([A-Za-z]+))'
    gender_pattern = r'(?:(?:Gender|ling|gender)[:\s]+(male|female|Male|Female))'

    details = {}

    # Extract DOB
    dob_match = re.search(dob_pattern, message, re.IGNORECASE)
    if dob_match:
        details["dob"] = dob_match.group(1)

    # Extract Time
    time_match = re.search(time_pattern, message, re.IGNORECASE)
    if time_match:
        details["tob"] = time_match.group(1)

    # Extract Place
    place_match = re.search(place_pattern, message, re.IGNORECASE)
    if place_match:
        details["place"] = place_match.group(1).strip()

    # Extract Name
    name_match = re.search(name_pattern, message, re.IGNORECASE)
    if name_match:
        details["name"] = name_match.group(1)

    # Extract Gender
    gender_match = re.search(gender_pattern, message, re.IGNORECASE)
    if gender_match:
        details["gender"] = gender_match.group(1).lower()

    # If we found at least DOB or Time or Place, save to MongoDB
    if len(details) >= 2:
        logger.info(f"[Birth Details] Extracted for {phone}: {list(details.keys())}")

        try:
            # Save to MongoDB
            await user_metadata.save_user_metadata(
                phone=phone,
                name=details.get("name"),
                dob=details.get("dob"),
                tob=details.get("tob"),
                place=details.get("place"),
                gender=details.get("gender")
            )
            logger.info(f"[Birth Details] Saved to MongoDB for {phone}")
            return details

        except Exception as e:
            logger.error(f"[Birth Details] Failed to save to MongoDB: {e}")

    return None


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_message_task(self, phone: str, message: str, message_id: str, message_type: str = "text", media_info: dict = None):
    """
    Process incoming WhatsApp message asynchronously.
    Retries up to 3 times with 60 second delay on failure.
    """
    try:
        logger.info(f"[Celery] Processing {message_type} from {phone}: {message[:50]}...")

        # Run async code in sync context
        import asyncio
        result = asyncio.run(_process_message_async(phone, message, message_id, message_type, media_info))
        return result

    except Exception as e:
        logger.error(f"[Celery] Task failed: {e}")
        # Retry with exponential backoff
        raise self.retry(exc=e, countdown=2 ** self.request.retries)


async def _download_whatsapp_media(media_id: str) -> dict:
    """Download media file from WhatsApp servers.
    Returns dict with url and mime_type, or None if failed.
    """
    if not WHATSAPP_ACCESS_TOKEN:
        logger.warning("Cannot download media: no access token")
        return None

    url = f"{FB_API_URL}/{media_id}"

    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # First get media info (which contains the download URL)
            response = await client.get(url, headers=headers)

            if response.status_code != 200:
                logger.error(f"Failed to get media info: {response.text}")
                return None

            media_data = response.json()
            return {
                "url": media_data.get("url"),
                "mime_type": media_data.get("mime_type"),
                "file_size": media_data.get("file_size"),
                "media_type": media_data.get("media_type")  # image, audio, video, document
            }

    except Exception as e:
        logger.error(f"Error downloading media: {e}")
        return None


async def _get_plans_message() -> str:
    """
    Fetch active plans from subscriptions service and format for WhatsApp.
    Returns formatted message with plan options.
    """
    if not SUBSCRIPTIONS_URL:
        return "Subscription service not configured. Please contact support."

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{SUBSCRIPTIONS_URL}/plans?active_only=true"
            )
            if response.status_code == 200:
                data = response.json()
                plans = data.get("plans", [])

                if not plans:
                    return "No plans available. Please contact support."

                # Format plans for WhatsApp
                message = "*💫 Choose Your Subscription Plan:*\n\n"

                for idx, plan in enumerate(plans, 1):
                    price_rupees = plan.get("price", 0) / 100  # Convert paise to rupees
                    duration = plan.get("durationDays", 30)

                    message += f"*{idx}. {plan.get('name', 'Plan')}*\n"
                    message += f"💰 ₹{price_rupees}/{duration} days\n"

                    # Add features if available
                    features = plan.get("features", [])
                    if features and isinstance(features, list):
                        for feature in features[:3]:  # Max 3 features
                            message += f"   ✓ {feature}\n"
                    message += "\n"

                message += "Reply with plan number (1, 2, 3...) to get payment link."
                return message
            else:
                logger.error(f"Failed to fetch plans: {response.status_code}")
                return "Unable to fetch plans. Please try again later."
    except Exception as e:
        logger.error(f"Error fetching plans: {e}")
        return "Unable to fetch plans. Please contact support."


async def _send_plans_interactive(phone: str) -> bool:
    """
    Send plans as beautiful messages with individual Buy Now buttons.
    Each plan is sent separately with its own purchase button.
    Returns True if successful, False otherwise.
    """
    if not SUBSCRIPTIONS_URL:
        return False

    try:
        # Fetch plans
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{SUBSCRIPTIONS_URL}/plans?active_only=true"
            )
            if response.status_code != 200:
                logger.error(f"Failed to fetch plans: {response.status_code}")
                return False

            data = response.json()
            plans = data.get("plans", [])

            if not plans:
                return False

        # Import WhatsAppAPI
        from app.services.whatsapp_api import WhatsAppAPI

        whatsapp_api = WhatsAppAPI(
            phone_id=WHATSAPP_PHONE_ID,
            access_token=WHATSAPP_ACCESS_TOKEN
        )

        # Send header message first
        header_msg = "💫 *Choose Your Subscription Plan*\n\nUnlock personalized astrology guidance with our affordable plans:"
        await whatsapp_api.send_text(phone, header_msg)

        # Send each plan as a separate message with Buy button
        # WhatsApp allows max 3 buttons per message, so we send 1-3 plans per message
        for idx, plan in enumerate(plans, 1):
            price_rupees = plan.get("price", 0) / 100
            duration = plan.get("durationDays", 30)
            plan_id = plan.get("planId", "")

            # Build beautiful plan message
            message = f"*{plan.get('name', 'Plan')}*\n"
            message += f"💰 *₹{price_rupees}* for {duration} days\n\n"

            # Add features
            features = plan.get("features", [])
            if features and isinstance(features, list):
                for feature in features:
                    message += f"✓ {feature}\n"

            # Send with Buy Now button
            await whatsapp_api.send_interactive_buttons(
                to=phone,
                text=message,
                buttons=[{
                    "id": f"buy_plan_{idx}_{plan_id}",  # Format: buy_plan_1_plan_id
                    "title": f"Buy Now - ₹{price_rupees}"
                }]
            )

        # Send footer message
        footer_msg = "✨ Tap the button above to purchase your plan instantly via Razorpay secure payment!"
        await whatsapp_api.send_text(phone, footer_msg)

        logger.info(f"[Plans] Sent {len(plans)} plans with buttons to {phone}")
        return True

    except Exception as e:
        logger.error(f"Error sending plans with buttons: {e}")
        return False


async def _generate_payment_link(user_id: str, plan_number: int = None, plan_id: str = None, language: str = "english", astrologer_name: str = "Meera") -> str:
    """
    Generate Razorpay payment link for selected plan.
    Calls subscriptions service which creates Razorpay Payment Link.
    Returns direct Razorpay payment URL - no custom page needed!

    Args:
        user_id: User phone number
        plan_number: Plan index (1-based) for backward compatibility
        plan_id: Plan ID from subscriptions service
        language: User's language preference (english/hinglish)
        astrologer_name: User's astrologer (Meera/Aarav)
    """
    if not SUBSCRIPTIONS_URL:
        logger.error("SUBSCRIPTIONS_URL not configured")
        return None

    try:
        logger.info(f"[Payment Link] Generating link for user={user_id}, plan_number={plan_number}, plan_id={plan_id}")
        selected_plan = None

        # If plan_id provided, find plan directly
        if plan_id:
            logger.info(f"[Payment Link] Searching for plan with ID: {plan_id}")
            async with httpx.AsyncClient(timeout=10.0) as client:
                plans_response = await client.get(
                    f"{SUBSCRIPTIONS_URL}/plans?active_only=true"
                )
                if plans_response.status_code == 200:
                    plans_data = plans_response.json()
                    plans = plans_data.get("plans", [])
                    logger.info(f"[Payment Link] Available plans: {[p.get('planId') for p in plans]}")
                    for plan in plans:
                        if plan.get("planId") == plan_id:
                            selected_plan = plan
                            logger.info(f"[Payment Link] Found plan: {plan.get('name')}")
                            break

        # If plan_number provided, find plan by index
        elif plan_number:
            async with httpx.AsyncClient(timeout=10.0) as client:
                plans_response = await client.get(
                    f"{SUBSCRIPTIONS_URL}/plans?active_only=true"
                )
                if plans_response.status_code != 200:
                    return None

                plans_data = plans_response.json()
                plans = plans_data.get("plans", [])

                # Validate plan number
                if plan_number < 1 or plan_number > len(plans):
                    return None

                selected_plan = plans[plan_number - 1]

        if not selected_plan:
            logger.error(f"Plan not found: plan_id={plan_id}, plan_number={plan_number}")
            return None

        final_plan_id = selected_plan.get("planId")
        logger.info(f"[Payment Link] Selected plan: {selected_plan.get('name')}, final_plan_id={final_plan_id}")

        # Call subscriptions service to create Razorpay Payment Link
        # This endpoint will use Razorpay Payment Links API
        request_body = {
            "userId": user_id,
            "planId": final_plan_id,  # Use the correctly extracted plan ID
            "currency": "INR",
            # Store metadata for payment confirmation
            "notes": {
                "user_id": user_id,
                "phone": user_id,
                "plan_id": final_plan_id,
                "language": language,
                "astrologer_name": astrologer_name
            }
        }
        logger.info(f"[Payment Link] Calling subscriptions API with: {request_body}")

        async with httpx.AsyncClient(timeout=30.0) as client:
            payment_link_response = await client.post(
                f"{SUBSCRIPTIONS_URL}/payments/create-payment-link",
                json=request_body
            )

            logger.info(f"[Payment Link] API Response status: {payment_link_response.status_code}")

            if payment_link_response.status_code == 200:
                link_data = payment_link_response.json()
                logger.info(f"[Payment Link] API Response data: {link_data}")

                razorpay_link = link_data.get("short_url") or link_data.get("payment_link")

                if razorpay_link:
                    logger.info(f"[Payment Link] ✓ Generated Razorpay link: {razorpay_link}")
                    return razorpay_link
                else:
                    logger.error(f"[Payment Link] ✗ No payment_link in response. Keys: {list(link_data.keys())}")
                    return None
            else:
                logger.error(f"[Payment Link] ✗ API failed with status {payment_link_response.status_code}")
                try:
                    error_data = payment_link_response.json()
                    logger.error(f"[Payment Link] Error response: {error_data}")
                except:
                    logger.error(f"[Payment Link] Error text: {payment_link_response.text}")
                return None

    except Exception as e:
        logger.error(f"Error generating payment link: {e}")
        return None


# Trial activation removed - users now get automatic access with 40 free messages
# _generate_trial_activation_link function removed



async def _send_whatsapp_payment_flow(
    phone: str,
    user_id: str,
    plan_id: str,
    amount: int,
    plan_name: str
) -> Optional[str]:
    """
    Send WhatsApp Flow for in-WhatsApp payment using Razorpay Payments on WhatsApp.

    Args:
        phone: User's phone number
        user_id: User ID
        plan_id: Plan ID
        amount: Amount in paise (e.g., 10000 for INR 100)
        plan_name: Plan name

    Returns:
        Message ID if successful, None otherwise
    """
    # Check required variables for WhatsApp Native Payments
    required_vars = {
        "WHATSAPP_PHONE_ID": WHATSAPP_PHONE_ID,
        "WHATSAPP_ACCESS_TOKEN": WHATSAPP_ACCESS_TOKEN,
        "WHATSAPP_PAYMENT_CONFIG_ID": WHATSAPP_PAYMENT_CONFIG_ID
    }

    missing_vars = [var_name for var_name, var_value in required_vars.items() if not var_value]

    if missing_vars:
        logger.error(f"[WhatsApp Payment] Missing required variables: {missing_vars}. Falling back to payment link.")
        return None

    logger.info(f"[WhatsApp Payment] ✓ All required variables present. Config ID: {WHATSAPP_PAYMENT_CONFIG_ID}")

    try:
        import time
        # Import here to avoid circular dependency
        from app.services.whatsapp_api import WhatsAppAPI

        whatsapp_api = WhatsAppAPI(
            phone_id=WHATSAPP_PHONE_ID,
            access_token=WHATSAPP_ACCESS_TOKEN
        )

        clean_phone = phone.replace("+", "")
        # Generate unique order id required by Razorpay Native implementation
        reference_id = f"order_{clean_phone}_{int(time.time())}"

        message_id = await whatsapp_api.send_native_payment(
            to=clean_phone,
            header=f"Pay for {plan_name}",
            body=f"Complete your payment of ₹{amount // 100} for {plan_name} securely via Razorpay in WhatsApp.",
            plan_name=plan_name,
            amount_paise=amount,
            reference_id=reference_id,
            payment_config_id=WHATSAPP_PAYMENT_CONFIG_ID
        )

        if message_id:
            logger.info(f"[WhatsApp Payment] Native checkout sent successfully: {message_id}")
            return message_id
        else:
            logger.error("[WhatsApp Payment] Failed to send native checkout")
            return None

    except Exception as e:
        logger.error(f"[WhatsApp Payment] Error sending payment flow: {e}")
        import traceback
        traceback.print_exc()
        return None


async def _check_subscription_access(phone: str) -> dict:
    """
    Check if user has valid subscription (trial or active).
    Returns: dict with 'access' field (trial, active, trial_ending_soon, no_access)
    Only enforces subscription for SUBSCRIPTION_TEST_NUMBER (testing mode).
    """
    # Skip subscription check if not configured
    if not SUBSCRIPTIONS_URL:
        logger.debug("[Subscription] SUBSCRIPTIONS_URL not configured, skipping check")
        return {"access": "trial", "skip_reason": "no_url"}

    # Skip subscription check if not the test number (testing mode)
    clean_phone = phone.replace("+", "").replace(" ", "")

    # Handle both formats: with country code (919760347653) and without (9760347653)
    test_numbers = [SUBSCRIPTION_TEST_NUMBER]
    if SUBSCRIPTION_TEST_NUMBER.startswith("91"):
        # Also check without country code
        test_numbers.append(SUBSCRIPTION_TEST_NUMBER[2:])

    if clean_phone not in test_numbers:
        logger.debug(f"[Subscription] Not test number ({clean_phone} not in {test_numbers}), skipping check")
        return {"access": "trial", "skip_reason": "not_test_number"}

    # Check subscription status
    user_id = f"+{clean_phone}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{SUBSCRIPTIONS_URL}/users/{user_id}/access-check"
            )
            if response.status_code == 200:
                access_data = response.json()
                logger.info(f"[Subscription] Access check for {user_id}: {access_data.get('access')}")
                return access_data
            else:
                logger.warning(f"[Subscription] Access check failed: {response.status_code}")
                # On API failure, allow access (fail-open)
                return {"access": "trial", "skip_reason": "api_error"}
    except Exception as e:
        logger.error(f"[Subscription] Error checking access: {e}")
        # On exception, allow access (fail-open)
        return {"access": "trial", "skip_reason": "exception"}


async def _download_whatsapp_media_file(media_id: str) -> dict:
    """Download the actual media file content from WhatsApp servers.
    Returns dict with base64 data, mime_type, and file extension.
    This is needed because WhatsApp media URLs require authentication.
    """
    if not WHATSAPP_ACCESS_TOKEN:
        logger.warning("Cannot download media file: no access token")
        return None

    # First get media info to get the download URL
    info_url = f"{FB_API_URL}/{media_id}"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Get media info
            info_response = await client.get(info_url, headers=headers)
            if info_response.status_code != 200:
                logger.error(f"Failed to get media info: {info_response.text}")
                return None

            media_data = info_response.json()
            download_url = media_data.get("url")
            mime_type = media_data.get("mime_type", "")

            if not download_url:
                logger.error("No download URL in media response")
                return None

            # Download the actual file using the URL (still needs auth)
            file_response = await client.get(download_url, headers=headers)
            if file_response.status_code != 200:
                logger.error(f"Failed to download media file: {file_response.status_code}")
                return None

            # Convert to base64
            file_content = file_response.content
            base64_data = base64.b64encode(file_content).decode('utf-8')

            # Determine file extension from mime type
            extension_map = {
                "image/jpeg": ".jpg",
                "image/png": ".png",
                "image/webp": ".webp",
                "image/gif": ".gif",
                "audio/mpeg": ".mp3",
                "audio/mp4": ".m4a",
                "audio/amr": ".amr",
                "audio/ogg": ".ogg",
                "video/mp4": ".mp4",
                "video/3gpp": ".3gp",
                "application/pdf": ".pdf",
                "text/plain": ".txt",
                "application/msword": ".doc",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
            }
            extension = extension_map.get(mime_type, ".bin")

            return {
                "base64": base64_data,
                "mime_type": mime_type,
                "extension": extension,
                "size_bytes": len(file_content),
                "media_type": media_data.get("media_type", "unknown")
            }

    except Exception as e:
        logger.error(f"Error downloading media file: {e}", exc_info=True)
        return None


def _extract_media_from_reply(text: str) -> Tuple[str, List[dict]]:
    """Parse MEDIA: tokens and MEDIA_BASE64: tokens from agent response text.
    Returns (clean_text, list_of_media_items).
    Each media item is: {"type": "url"|"base64", "value": ..., "mime_type": ...}
    """
    media_items = []
    clean_lines = []

    logger.info(f"[DEBUG] _extract_media_from_reply: Processing {len(text)} chars, {len(text.split(chr(10)))} lines")
    logger.info(f"[DEBUG] First 300 chars: {repr(text[:300])}")

    # FIRST: Check for data URLs in the full text BEFORE splitting into lines
    # This handles cases where base64 spans multiple lines
    data_url_match = re.search(r'\!\[([^\]]+)\]\((data:image/[^;]+;base64,[^\)]+)\)', text, re.DOTALL)
    if data_url_match:
        data_url = data_url_match.group(2)
        # Extract mime type and base64 data
        if 'base64,' in data_url:
            mime_part, b64_part = data_url.split('base64,', 1)
            mime_type = mime_part.replace('data:image/', '').replace(';', '')
            b64_data = b64_part.rstrip(')')
            media_items.append({"type": "base64", "value": b64_data, "mime_type": f"image/{mime_type}"})
            logger.info(f"Found data URL in markdown: image/{mime_type}, size={len(b64_data)} chars")
            # Remove the entire image markdown from text
            text = text.replace(data_url_match.group(0), '')

    for line in text.split("\n"):
        stripped = line.strip()

        # Log lines that might contain media
        if 'MEDIA' in stripped.upper() or 'oaidalleapiprodscus' in stripped or 'blob.core.windows.net' in stripped:
            logger.info(f"[DEBUG] Checking potential media line: {repr(stripped[:100])}")

        # Check for MEDIA_BASE64: <mime_type> <base64_data>
        b64_match = re.match(r'^MEDIA_BASE64:\s*(\S+)\s+(\S+)$', stripped)
        if b64_match:
            mime_type = b64_match.group(1)
            b64_data = b64_match.group(2)
            media_items.append({"type": "base64", "value": b64_data, "mime_type": mime_type})
            logger.info(f"Found MEDIA_BASE64 in response: mime={mime_type}, len={len(b64_data)}")
            continue

        # Check for KUNDLI_IMAGE: <mime_type> <base64_data> (custom format to avoid OpenClaw plugin)
        kundli_match = re.match(r'^KUNDLI_IMAGE:\s*(\S+)\s+(\S+)$', stripped)
        if kundli_match:
            mime_type = kundli_match.group(1)
            b64_data = kundli_match.group(2)
            media_items.append({"type": "base64", "value": b64_data, "mime_type": mime_type})
            logger.info(f"Found KUNDLI_IMAGE in response: mime={mime_type}, len={len(b64_data)}")
            continue

        # Check for data:media_base64:mime_type,base64_data (OpenClaw WhatsApp plugin format)
        openclaw_media_match = re.match(r'^data:media_base64:([^,]+),(.+)$', stripped)
        if openclaw_media_match:
            mime_type = openclaw_media_match.group(1)
            b64_data = openclaw_media_match.group(2)
            media_items.append({"type": "base64", "value": b64_data, "mime_type": mime_type})
            logger.info(f"Found OpenClaw media_base64 in response: mime={mime_type}, len={len(b64_data)}")
            continue

        # Check for IMAGE_URL: or IMAGE: https://... (Kundli image uploaded to dashboard)
        # Now robustly handles LLM hallucinated markdown: IMAGE_URL: [text](https://...)
        image_url_match = re.search(r'^(?:IMAGE_URL|IMAGE):\s*(?:\[[^\]]*\]\()?(https?://[^\)\s]+)\)?', stripped)
        if image_url_match:
            image_url = image_url_match.group(1)
            media_items.append({"type": "url", "value": image_url})
            logger.info(f"Found IMAGE_URL in response: {image_url}")
            # If it was a markdown link, we should clean it from the output so it doesn't show
            line = line.replace(image_url_match.group(0), "")
            continue

        # Check for MEDIA: <path_or_url>
        media_match = re.match(r'^MEDIA:\s*(.+)$', stripped)
        if media_match:
            media_path = media_match.group(1).strip().strip('"').strip("'")
            logger.info(f"[DEBUG] MEDIA: regex matched, path: {repr(media_path[:100])}")

            # Direct URL
            if media_path.startswith('http://') or media_path.startswith('https://'):
                # [URL_V2.1] Log the URL AS RECEIVED from OpenClaw, before any processing
                logger.info(f"[URL_V2.1] URL_AS_RECEIVED from OpenClaw: {media_path[:200]}...")
                # Extract and log signature if present
                if 'sig=' in media_path:
                    sig_start = media_path.find('sig=') + 4
                    sig_end = media_path.find('&', sig_start)
                    if sig_end == -1:
                        sig_end = len(media_path)
                    signature = media_path[sig_start:sig_end]
                    logger.info(f"[URL_V2.1] Signature AS_RECEIVED: {signature}")

                media_items.append({"type": "url", "value": media_path})
                logger.info(f"[URL_V2.1] Added URL to media_items: {media_path[:80]}...")
                continue  # Skip adding this line to clean text

            # Check for Markdown link syntax: [text](url) or ![text](url)
            md_match = re.search(r'!?\[([^\]]*)\]\((https?://[^)]+)\)', media_path)
            if md_match:
                url = md_match.group(2)
                media_items.append({"type": "url", "value": url})
                logger.info(f"Found MEDIA URL in markdown link: {url[:80]}...")
                continue

            # Check for DALL-E URL embedded in malformed text
            dalle_in_media = re.search(r'https://oaidalleapiprodscus\.[^\"\)\s]+', media_path)
            if dalle_in_media:
                dalle_url = dalle_in_media.group(0)
                media_items.append({"type": "url", "value": dalle_url})
                logger.info(f"Found DALL-E URL in MEDIA line: {dalle_url[:80]}...")
                continue

            # Local file path — can't access across containers,
            # log warning but keep line so user sees context
            logger.warning(f"Found MEDIA local path in response (not accessible across containers): {media_path}")
            # Don't add to media_items, can't use it
            continue

        # FALLBACK: Check for DALL-E URLs (oaidalleapiprodscus) even in malformed lines
        # Agent sometimes outputs: "MEDIA:Kundli Chart](https://oaidalleapiprodscus...)"
        # or "[MEDIA: Kundli Chart](url)" - try to extract the URL anyway
        dalle_match = re.search(r'https://oaidalleapiprodscus\.[^\"\)\s]+', line)
        if dalle_match:
            dalle_url = dalle_match.group(0)
            media_items.append({"type": "url", "value": dalle_url})
            logger.info(f"Found DALL-E URL in malformed line: {dalle_url[:80]}...")
            # Remove the entire line from output (it contains broken markdown)
            continue

        # Check for other image URLs in markdown link format [text](url)
        url_match = re.search(r'\[([^\]]+)\]\((https?://[^\)]+)\)', line)
        if url_match:
            url = url_match.group(2)
            # Only extract if it looks like an image URL (common image hosts)
            if any(host in url for host in ['oaidalleapiprodscus', 'blob.core.windows.net', 'images.unsplash', 'imgur', 'i.ibb.co', 'ibb.co', 'hansastro.com', 'localhost']):
                media_items.append({"type": "url", "value": url})
                logger.info(f"Found image URL in markdown link: {url[:80]}...")
                line = line.replace(url_match.group(0), "")
                continue

        # Check for data URL in markdown format ![alt](data:image/...)
        # Try multiline match first (DOTALL flag makes . match newlines)
        data_url_match = re.search(r'\[([^\]]+)\]\((data:image/([^;]+);base64,.+?)\)', line, re.DOTALL)
        if not data_url_match:
            # Try single-line match
            data_url_match = re.search(r'\[([^\]]+)\]\((data:image/([^;]+);base64,[^\)]+)\)', line)
        if data_url_match:
            mime_type = f"image/{data_url_match.group(3)}"
            b64_data = data_url_match.group(4)
            # Remove 'data:image/png;base64,' prefix if present
            if b64_data.startswith('data:'):
                # Extract just the base64 part
                b64_data = b64_data.split('base64,')[1]
            media_items.append({"type": "base64", "value": b64_data, "mime_type": mime_type})
            logger.info(f"Found data URL in markdown link: {mime_type}, size={len(b64_data)} chars")
            # Remove the entire line from output (the base64 string is too long)
            continue

        clean_lines.append(line)

    clean_text = "\n".join(clean_lines).strip()
    return clean_text, media_items


async def _upload_base64_to_whatsapp_media(client: httpx.AsyncClient, b64_data: str, mime_type: str) -> Optional[str]:
    """Upload base64-encoded image to WhatsApp Media API.
    Returns media_id on success, None on failure.
    """
    if not WHATSAPP_PHONE_ID or not WHATSAPP_ACCESS_TOKEN:
        logger.error("WhatsApp credentials missing for media upload")
        return None

    url = f"{FB_API_URL}/{WHATSAPP_PHONE_ID}/media"

    try:
        # Decode base64 to binary
        file_bytes = base64.b64decode(b64_data)

        # Determine file extension from mime type
        ext_map = {
            "image/png": "chart.png",
            "image/jpeg": "chart.jpg",
            "image/webp": "chart.webp",
        }
        filename = ext_map.get(mime_type, "chart.png")

        # Upload as multipart form data
        files = {
            "file": (filename, file_bytes, mime_type),
        }
        data = {
            "messaging_product": "whatsapp",
            "type": mime_type,
        }
        headers = {
            "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        }

        response = await client.post(url, headers=headers, data=data, files=files)

        if response.status_code in [200, 201]:
            media_id = response.json().get("id")
            logger.info(f"Uploaded media to WhatsApp: media_id={media_id}")
            return media_id

        logger.error(f"WhatsApp media upload failed: {response.status_code} {response.text}")
        return None

    except Exception as e:
        logger.error(f"Error uploading media to WhatsApp: {e}", exc_info=True)
        return None


async def _upload_pdf_to_whatsapp_media(client: httpx.AsyncClient, pdf_bytes: bytes, filename: str) -> Optional[str]:
    """
    Upload PDF to WhatsApp Media API

    Args:
        client: HTTP client
        pdf_bytes: PDF file bytes
        filename: Document filename

    Returns:
        Media ID if successful, None otherwise
    """
    if not WHATSAPP_ACCESS_TOKEN:
        logger.error("WhatsApp access token missing")
        return None

    url = f"{FB_API_URL}/{WHATSAPP_PHONE_ID}/media"

    try:
        # Upload as multipart form data
        files = {
            "file": (filename, pdf_bytes, "application/pdf"),
        }
        data = {
            "messaging_product": "whatsapp",
            "type": "application/pdf",
        }
        headers = {
            "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        }

        response = await client.post(url, headers=headers, data=data, files=files)

        if response.status_code in [200, 201]:
            media_id = response.json().get("id")
            logger.info(f"[PDF] Uploaded to WhatsApp Media: {media_id}")
            return media_id

        logger.error(f"[PDF] Upload failed: {response.status_code} {response.text}")
        return None

    except Exception as e:
        logger.error(f"[PDF] Error uploading PDF: {e}", exc_info=True)
        return None


async def _send_whatsapp_image(client: httpx.AsyncClient, phone: str, media_id: str = None, image_url: str = None, caption: str = None) -> dict:
    """Send image message via WhatsApp API using media_id or URL."""
    if not WHATSAPP_PHONE_ID or not WHATSAPP_ACCESS_TOKEN:
        logger.error("WhatsApp credentials missing")
        return {"error": "Credentials missing"}

    url = f"{FB_API_URL}/{WHATSAPP_PHONE_ID}/messages"

    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    # Build image payload — prefer media_id (uploaded), fallback to URL
    image_obj = {}
    if media_id:
        image_obj["id"] = media_id
    elif image_url:
        image_obj["link"] = image_url
    else:
        logger.error("No media_id or image_url provided for image send")
        return {"error": "No image source"}

    if caption:
        image_obj["caption"] = caption[:1024]  # WhatsApp caption limit

    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "image",
        "image": image_obj
    }

    response = await client.post(url, headers=headers, json=payload)

    if response.status_code in [200, 201]:
        msg_id = response.json().get("messages", [{}])[0].get("id")
        logger.info(f"Sent image to {phone}, msg_id={msg_id}")
        return {"success": True, "message_id": msg_id}

    logger.error(f"WhatsApp image send failed: {response.status_code} {response.text}")
    return {"error": response.text}


async def _process_message_async(phone: str, message: str, message_id: str, message_type: str = "text", media_info: dict = None):
    """Async implementation of message processing."""
    session_id = f"whatsapp:+{phone}"
    user_id = f"+{phone}"

    # SPAM DETECTION: Check for repetitive spam messages
    # If message is > 1000 chars and contains highly repetitive content, truncate it
    if len(message) > 1000:
        # Check if message is highly repetitive (same phrase repeated > 50 times)
        words = message.split()
        unique_words = set(words)
        if len(words) > 100 and len(unique_words) < 20:
            logger.warning(f"[SPAM] Detected repetitive spam message, truncating. Original length: {len(message)}")
            # Keep first 200 chars only
            message = message[:200]
            message = message + "... (message truncated due to spam detection)"

    # Download media file if present (image, audio, video, document)
    # This downloads the actual file content and converts to base64
    # because WhatsApp media URLs require authentication
    media_file_data = None
    if media_info and media_info.get("id"):
        media_file_data = await _download_whatsapp_media_file(media_info["id"])
        if media_file_data:
            logger.info(f"Downloaded media file: {message_type}, size: {media_file_data['size_bytes']} bytes, base64_len: {len(media_file_data['base64'])}")
            media_info["base64_data"] = media_file_data["base64"]
            media_info["mime_type"] = media_file_data["mime_type"]
            media_info["extension"] = media_file_data["extension"]
        else:
            logger.warning(f"Failed to download media file: {media_info.get('id')}")

    # Log user message to MongoDB (exclude large base64 data from log)
    log_media_info = None
    if media_info:
        log_media_info = {k: v for k, v in media_info.items() if k != "base64_data"}
    await _log_to_mongo(session_id, user_id, "user", message, "whatsapp", message_type, log_media_info)

    # ==================== BIRTH DETAILS EXTRACTION (MongoDB) ====================
    # Extract and save birth details to MongoDB if present in message
    # This runs in background and doesn't block message processing
    try:
        extracted_details = await _extract_and_save_birth_details(phone, message)
        if extracted_details:
            logger.info(f"[Birth Details] Successfully extracted and saved details for {phone}")
    except Exception as e:
        logger.warning(f"[Birth Details] Extraction failed: {e}")

    # Check for and apply referral code in message
    # This runs in background and doesn't block message processing
    try:
        referral_result = await _check_and_apply_referral_code(phone, message)
        if referral_result and referral_result.get("success"):
            logger.info(f"[Referral] Referral code applied for {phone}: {referral_result}")
            # Send confirmation message to user
            referral_confirm_msg = referral_result.get("message", "Referral code applied! You'll get 1 month FREE premium when you subscribe.")
            async with httpx.AsyncClient(timeout=30.0) as client:
                await _send_whatsapp_message(client, phone, referral_confirm_msg)
    except Exception as e:
        logger.warning(f"[Referral] Referral code check failed: {e}")

    # Update user stats in MongoDB (increment question count, update last_seen)
    # This runs in background and doesn't block message processing
    try:
        await user_metadata.increment_user_questions(phone)
    except Exception as e:
        logger.warning(f"[User Metadata] Failed to increment question count: {e}")

    # ===================================================================

    # ==================== AUDIO MESSAGE PROCESSING ====================

    # Check if this is an audio message
    if message_type in ["audio", "voice"]:
        logger.info(f"[Audio] Received audio message from {phone}")

        try:
            # Import audio processor
            from skills.audio_processor.transcribe import transcribe_audio

            # Transcribe audio to text using Groq (FREE)
            if media_info and media_info.get("base64_data"):
                transcribed_text = await transcribe_audio(
                    media_info["base64_data"],
                    media_info.get("mime_type", "audio/ogg")
                )

                if transcribed_text:
                    logger.info(f"[Audio] Transcription successful: {transcribed_text[:100]}...")
                    # Replace the message with transcription
                    message = transcribed_text
                    # Keep message_type as audio for logging, but treat as text
                    logger.info("[Audio] Proceeding with transcribed text")
                else:
                    logger.warning("[Audio] Transcription failed, sending empty message")
                    message = ""  # Send empty message
            else:
                logger.warning("[Audio] No audio data found")
                message = ""

        except Exception as e:
            logger.error(f"[Audio] Error processing audio: {e}")
            # Fallback: send empty message
            message = ""

    # ===================================================================

    # ==================== PAY COMMAND CHECK (GLOBAL) ====================
    # PAY command returns generic "didn't understand" message
    # Payment is handled via Razorpay WhatsApp payment buttons only
    pay_command = message.strip().upper()
    if pay_command in ["PAY", "PAYMENT", "PLAN", "PLANS", "SUBSCRIBE"]:
        logger.info(f"[PAY Command] User typed '{pay_command}' - returning generic response")
        generic_message = "I didn't get that. Please ask me about astrology, kundli, marriage, career, or any life guidance! 💫"
        async with httpx.AsyncClient(timeout=30.0) as client:
            await _send_whatsapp_message(client, phone, generic_message)
        await _log_to_mongo(session_id, user_id, "assistant", generic_message, "whatsapp")
        return {"status": "generic_response"}

    # ==================== REFERRAL COMMAND (GLOBAL) ====================
    # Check for REFER command - share with friends
    referral_command = message.strip().upper()
    if referral_command in ["REFER", "REFERRAL", "REFERRALS", "SHARE", "INVITE"]:
        # Get referral link for user
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                referral_response = await client.get(
                    f"{SUBSCRIPTIONS_URL}/referrals/my-link/{user_id}"
                )

                if referral_response.status_code == 200:
                    referral_data = referral_response.json()

                    # Format beautiful referral message
                    referral_msg = f"""🎁 *Share your Astrofriend!*

Your referral code: *{referral_data.get('referralCode', 'N/A')}*

Share this with friends who need guidance. When they subscribe:
✓ You get 1 month FREE premium
✓ They also get 1 month FREE premium

📊 *Your Stats:*
Total referrals: {referral_data.get('totalReferrals', 0)}
Free months earned: {referral_data.get('freeMonthsEarned', 0)}

*Share link:*
{referral_data.get('referralLink', 'N/A')}

Copy your code and share! 💫"""

                    async with httpx.AsyncClient(timeout=30.0) as client2:
                        await _send_whatsapp_message(client2, phone, referral_msg)
                    await _log_to_mongo(session_id, user_id, "assistant", referral_msg, "whatsapp")
                    return {"status": "referral_sent"}
                else:
                    error_msg = "Unable to generate referral link. Please try again later."
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        await _send_whatsapp_message(client, phone, error_msg)
                    await _log_to_mongo(session_id, user_id, "assistant", error_msg, "whatsapp")
                    return {"status": "referral_error"}

        except Exception as e:
            logger.error(f"Error generating referral link: {e}")
            error_msg = "Sorry, something went wrong. Please try again later."
            async with httpx.AsyncClient(timeout=30.0) as client:
                await _send_whatsapp_message(client, phone, error_msg)
            await _log_to_mongo(session_id, user_id, "assistant", error_msg, "whatsapp")
            return {"status": "referral_error"}

    # Check if user is selecting a plan via button click (buy_plan_1_planid), digit (1, 2, 3), or plan name
    plan_number = None
    plan_id_from_button = None
    plan_id_from_name = None

    if message.strip().startswith("buy_plan_"):
        # Parse button click: buy_plan_1_monthly_299 (plan_id can contain underscores)
        parts = message.strip().split("_")
        logger.info(f"[Button Parse] Button message parts: {parts}")
        if len(parts) >= 3:
            try:
                plan_number = int(parts[2])  # Extract plan number
                # Join all parts after index 2 to get the full plan_id (may contain underscores)
                plan_id_from_button = "_".join(parts[3:]) if len(parts) > 3 else None
                logger.info(f"[Button Parse] Parsed plan_number={plan_number}, plan_id={plan_id_from_button}")
            except ValueError:
                logger.error(f"[Button Parse] Failed to parse plan number from: {parts[2]}")
                pass
    elif message.strip().isdigit():
        plan_number = int(message.strip())
    else:
        # Try to match plan name from user message
        # Fetch plans to match against
        try:
            async with httpx.AsyncClient(timeout=10.0) as fetch_client:
                plans_response = await fetch_client.get(
                    f"{SUBSCRIPTIONS_URL}/plans?active_only=true"
                )
                if plans_response.status_code == 200:
                    plans_data = plans_response.json()
                    plans = plans_data.get("plans", [])

                    # Normalize user message for matching
                    user_message_lower = message.strip().lower()

                    # Try to match plan name (case-insensitive, partial match)
                    for idx, plan in enumerate(plans):
                        plan_name = plan.get("name", "").lower()
                        plan_id = plan.get("planId", "").lower()

                        # Check if user message contains plan name or plan ID
                        if (user_message_lower in plan_name or
                            plan_name in user_message_lower or
                            user_message_lower in plan_id or
                            plan_id in user_message_lower):
                            plan_number = idx + 1  # Convert to 1-based index
                            plan_id_from_name = plan.get("planId")
                            logger.info(f"Matched plan by name: {plan.get('name')} (plan_number={plan_number})")
                            break
        except Exception as e:
            logger.error(f"Error matching plan by name: {e}")
            # Continue to plan_number check below

    if plan_number is not None:

        # First fetch plan details
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                plans_response = await client.get(
                    f"{SUBSCRIPTIONS_URL}/plans?active_only=true"
                )
                if plans_response.status_code == 200:
                    plans_data = plans_response.json()
                    plans = plans_data.get("plans", [])
                    logger.info(f"[Plan Selection] Total plans available: {len(plans)}")
                    logger.info(f"[Plan Selection] Looking for: plan_number={plan_number}, plan_id_from_button={plan_id_from_button}, plan_id_from_name={plan_id_from_name}")

                    # Find the selected plan
                    selected_plan = None
                    if plan_id_from_name:
                        # Find plan by ID from name match
                        logger.info(f"[Plan Selection] Searching by plan_id_from_name: {plan_id_from_name}")
                        for plan in plans:
                            if plan.get("planId") == plan_id_from_name:
                                selected_plan = plan
                                logger.info(f"[Plan Selection] Found plan by name match: {plan.get('name')}")
                                break
                    elif plan_id_from_button:
                        # Find plan by ID from button click
                        logger.info(f"[Plan Selection] Searching by plan_id_from_button: {plan_id_from_button}")
                        for plan in plans:
                            if plan.get("planId") == plan_id_from_button:
                                selected_plan = plan
                                logger.info(f"[Plan Selection] Found plan by button ID: {plan.get('name')}")
                                break
                    elif 1 <= plan_number <= len(plans):
                        # Find plan by number (backward compatibility)
                        logger.info(f"[Plan Selection] Searching by plan_number: {plan_number}")
                        selected_plan = plans[plan_number - 1]
                        logger.info(f"[Plan Selection] Found plan by number: {selected_plan.get('name')}")

                    if not selected_plan:
                        logger.error(f"[Plan Selection] No plan found! Available plans: {[p.get('planId') for p in plans]}")

                    if selected_plan:
                        plan_id = selected_plan.get("planId")
                        plan_name = selected_plan.get("name", "Plan")
                        amount = selected_plan.get("price", 0)

                        # DISABLED: WhatsApp Flow (in-WhatsApp payment)
                        # Direct payment link is used instead for better reliability
                        # if WHATSAPP_FLOW_ID and WHATSAPP_PAYMENT_CONFIG_ID:
                        #     flow_message_id = await _send_whatsapp_payment_flow(
                        #         phone=phone,
                        #         user_id=user_id,
                        #         plan_id=plan_id,
                        #         amount=amount,
                        #         plan_name=plan_name
                        #     )
                        #
                        #     if flow_message_id:
                        #         flow_message = (
                        #             f"Great! You selected **{plan_name}**.\n\n"
                        #             f"Please complete the payment securely within WhatsApp. 💫\n\n"
                        #             f"After payment, send me a message to start!"
                        #         )
                        #         async with httpx.AsyncClient(timeout=30.0) as client:
                        #             await _send_whatsapp_message(client, phone, flow_message)
                        #         await _log_to_mongo(session_id, user_id, "assistant", flow_message, "whatsapp")
                        #         return {"status": "payment_flow_sent", "flow_id": flow_message_id}

                        # DISABLED: Direct payment link sending
                        # Payment is now handled via Razorpay WhatsApp payment buttons only
                        # The payment buttons are shown automatically with enforcement messages
                        logger.info(f"[Plan Selection] Plan {plan_name} selected - directing user to payment button")
                        info_message = (
                            f"Great! You selected **{plan_name}**. 💫\n\n"
                            f"Please complete the payment using the payment button shown in my previous message.\n\n"
                            f"If you don't see the payment button, just send me a message and I'll show it again!"
                        )
                        async with httpx.AsyncClient(timeout=30.0) as client:
                            await _send_whatsapp_message(client, phone, info_message)
                        await _log_to_mongo(session_id, user_id, "assistant", info_message, "whatsapp")
                        return {"status": "plan_selected", "plan_name": plan_name}

        except Exception as e:
            logger.error(f"Error processing plan selection: {e}", exc_info=True)
            import traceback
            traceback.print_exc()

        # Invalid plan number
        async with httpx.AsyncClient(timeout=30.0) as client:
            await _send_whatsapp_message(client, phone, "Invalid plan number. Please select a valid plan (1, 2, 3...).")
        return {"status": "invalid_plan", "plan_number": plan_number}

    # ===================================================================

    # ==================== HELPER FUNCTIONS ====================

    def _detect_language(text: str) -> str:
        """Detect if text is English, Hindi, or Hinglish (Roman script with Hindi words)."""
        if not text:
            return "english"

        # Common Hinglish words (Roman script Hindi)
        hinglish_words = {
            # Common words
            'namaste', 'kaise', 'ho', 'kya', 'hai', 'hain', 'nahi', 'ji', 'acha',
            'theek', 'hai', 'hain', 'kar', 'ke', 'ka', 'ki', 'ko', 'se', 'mein', 'mera',
            'tera', 'apna', 'karna', 'sakta', 'sakti', 'sakta', 'hai', 'hoga', 'hogi',
            'please', 'thank', 'you', 'sorry', 'maf', 'kijiye', 'ga', 'bhai', 'behen',
            'yeh', 'voh', 'yah', 'yahin', 'wahan', 'kya', 'kisko', 'kiske', 'kab',
            'kabhi', 'kahan', 'kaise', 'kitna', 'kitni', 'kitne', 'sab', 'sabse',
            'ek', 'do', 'teen', 'char', 'paanch', 'cheh', 'saath', 'aath', 'nau', 'das',
            'bohot', 'bahut', 'zyada', 'kam', 'accha', 'achha', 'bilkul', 'pakka',
            'shayad', 'haan', 'haanji', 'ji', 'nahi', 'na', 'toh', 'to', 'aur', 'or',
            'lekin', 'magar', 'par', 'kyunki', 'kyun', 'kyun', 'isliye', 'liye',
            'wajah', 'wajahse', 'batao', 'batana', 'bata', 'suno', 'sunna', 'samjha',
            'samjhi', 'samajh', 'samjh', 'pata', 'maloom', 'chal', 'chalo', 'ruko',
            'rukho', 'aa', 'aao', 'jao', 'jayiye', 'jiyega', 'jiyegi', 'hoga', 'hogi',
            # Time/relations
            'abhi', 'ab', 'kal', 'aaj', 'aj', 'parson', 'neste', 'subah', 'shaam',
            'dophar', 'raat', 'morning', 'evening', 'night', 'dinner', 'lunch',
            'mom', 'dad', 'papa', 'mummy', 'maa', 'baap', 'beti', 'beta', 'bhai',
            'behen', 'didi', 'bhaiya', 'family', 'ghar', 'gharpe', 'office',
            # Astrology specific
            'kundli', 'horoscope', 'rashi', 'lagna', 'planets', 'grah', 'nakshatra',
            'dasha', 'mahadasha', 'antardasha', 'vivah', 'shaadi', 'marriage', 'career',
            'naukri', 'job', 'business', 'paisa', 'paisaye', 'rupaye', 'investment',
            # Feelings
            'pyaar', 'love', 'dil', 'dilse', 'mann', 'mannki', 'feel', 'feeling',
            'khush', 'gussa', 'naraaz', 'udaas', 'happy', 'sad', 'excited', 'tension',
            'problem', 'solution', 'mamla', 'baat', 'baaten', 'chinta', 'worry',
            # Common connectors
            'hmm', 'haan', 'ok', 'okay', 'thik', 'theek', 'sahi', 'galat', 'wrong',
            'right', 'correct', 'sach', 'truth', 'jhooth', 'lie', 'batao', 'bolo'
        }

        # Convert to lowercase for checking
        text_lower = text.lower()

        # Count Hinglish words in the text
        hinglish_count = 0
        words = text_lower.split()
        for word in words:
            # Remove punctuation for matching
            clean_word = word.strip('.,!?;:"\'-')
            if clean_word in hinglish_words:
                hinglish_count += 1

        # Count Devanagari characters (Hindi script)
        hindi_chars = set('अआइईउऊऋएऐओऔकखगघङचछजझञटडणतथदधनपफबभमयरलवशषसह')
        hindi_char_count = sum(1 for char in text if char in hindi_chars)

        # Decision logic:
        # 1. If has Devanagari characters → Hindi
        if hindi_char_count > 0:
            return "hindi"

        # 2. If more than 15% Hinglish words → Hinglish
        if hinglish_count > 0 and hinglish_count > len(words) * 0.15:
            return "hinglish"

        # 3. Otherwise → English
        return "english"

    def _get_today_start_ist() -> str:
        """Get today's start date in IST (Indian Standard Time = UTC+5:30)."""
        from datetime import timedelta, timezone

        # Get current time in UTC
        utc_now = datetime.now(timezone.utc)
        # Convert to IST (UTC+5:30)
        ist_offset = timedelta(hours=5, minutes=30)
        ist_now = utc_now + ist_offset
        # Return just the date part (YYYY-MM-DD)
        return ist_now.strftime("%Y-%m-%d")

    def _convert_utc_to_ist_date(utc_timestamp: str) -> str:
        """Convert UTC timestamp to IST date string (YYYY-MM-DD)."""
        from datetime import timedelta, timezone

        try:
            # Parse UTC timestamp (formats: 2026-04-12T19:01:42.856Z or 2026-04-12T19:01:42Z)
            ts = utc_timestamp.replace('Z', '')
            if '.' in ts:
                # Remove microseconds for parsing
                ts = ts.split('.')[0]

            utc_time = datetime.fromisoformat(ts)
            utc_time = utc_time.replace(tzinfo=timezone.utc)

            # Convert to IST (UTC+5:30)
            ist_offset = timedelta(hours=5, minutes=30)
            ist_time = utc_time + ist_offset

            return ist_time.strftime("%Y-%m-%d")
        except Exception as e:
            logger.warning(f"[Enforcement] Failed to convert {utc_timestamp} to IST: {e}")
            return ""

    # ===================================================================

    # ==================== MESSAGE LIMIT ENFORCEMENT (PRODUCTION) ====================

    # Message limits for all users
    FREE_MESSAGE_LIMIT = 25
    DAILY_MESSAGE_LIMIT = 5

    logger.info(f"[Enforcement] Checking message limits for {phone}")

    try:
        # Try to count total user messages from MongoDB logger
        # NOTE: /messages/aggregation endpoint may not exist, so we'll use /messages with filtering
        total_messages = 0
        today_messages = 0

        if MONGO_LOGGER_URL:
            try:
                async with httpx.AsyncClient(timeout=10.0) as count_client:
                    # Use regular /messages endpoint with limit
                    count_response = await count_client.get(
                        f"{MONGO_LOGGER_URL}/messages",
                        params={"userId": user_id, "role": "user", "limit": 1000}
                    )

                    if count_response.status_code == 200:
                        count_data = count_response.json()
                        logger.info(f"[Enforcement] MongoDB Logger Raw Response keys: {list(count_data.keys())}")

                        # When userId is provided, API returns user doc directly
                        # When no userId, API returns {count, users: [...]}
                        if "sessions" in count_data:
                            # Single user document returned
                            sessions = count_data.get("sessions", [])
                            logger.info(f"[Enforcement] Single user doc with {len(sessions)} sessions")
                        elif "users" in count_data:
                            # Multiple users returned
                            users_list = count_data.get("users", [])
                            if users_list and users_list[0].get("sessions"):
                                sessions = users_list[0]["sessions"]
                                logger.info(f"[Enforcement] Multiple users, first has {len(sessions)} sessions")
                            else:
                                sessions = []
                                logger.info(f"[Enforcement] Multiple users but no sessions found")
                        else:
                            sessions = []
                            logger.info(f"[Enforcement] No sessions or users key in response")

                        logger.info(f"[Enforcement] Total sessions to process: {len(sessions)}")

                        # Count messages from all sessions
                        for session in sessions:
                            messages = session.get("messages", [])
                            for msg in messages:
                                if msg.get("role") == "user":
                                    total_messages += 1
                                    # Check if message is from today (MongoDB logger uses 'timestamp')
                                    msg_time = msg.get("timestamp", "")
                                    today_ist = _get_today_start_ist()  # Get today's date in IST

                                    # Convert message UTC timestamp to IST date
                                    msg_ist_date = _convert_utc_to_ist_date(msg_time)

                                    logger.info(f"[Enforcement] Checking msg: {msg_time} (UTC) → {msg_ist_date} (IST), today: {today_ist}")

                                    if msg_ist_date and msg_ist_date == today_ist:
                                        logger.info(f"[Enforcement] ✓ Message counted (today in IST)")
                                        today_messages += 1
                                    else:
                                        logger.info(f"[Enforcement] ✗ Message NOT from today (IST date: {msg_ist_date})")

                        logger.info(f"[Enforcement] Total messages for {user_id}: {total_messages}, Today: {today_messages}")
                    else:
                        logger.warning(f"[Enforcement] Failed to count messages: {count_response.status_code}")
            except Exception as e:
                logger.warning(f"[Enforcement] Error counting messages: {e}")
                # Default to allowing the message if counting fails
                total_messages = 0
            else:
                logger.warning("[Enforcement] MONGO_LOGGER_URL not configured, cannot count messages")

            # Check if user has active subscription (OUTSIDE if/else blocks)
            logger.info(f"[Enforcement] About to check subscription access...")
            access = await _check_subscription_access(phone)
            logger.info(f"[Enforcement] Subscription check completed: {access}")

            logger.info(f"[Enforcement] DEBUG: access={access.get('access')}, total_messages={total_messages}, FREE_MESSAGE_LIMIT={FREE_MESSAGE_LIMIT}")

            # Check if user has active subscription (full_access or active skips enforcement)
            if access.get("access") in ["full_access", "active"]:
                logger.info(f"[Enforcement] User has active subscription ({access.get('access')}) - skipping enforcement")
            # User has trial, trial_ending_soon, or no subscription - enforce limits
            elif total_messages >= FREE_MESSAGE_LIMIT:
                logger.info(f"[Enforcement] User exhausted {FREE_MESSAGE_LIMIT} free messages (total: {total_messages}, access: {access.get('access')})")

                # Check if daily limit reached
                if today_messages >= DAILY_MESSAGE_LIMIT:
                    logger.warning(f"[Enforcement] Daily limit reached ({today_messages}/{DAILY_MESSAGE_LIMIT}) - SENDING SOFT PAYWALL")

                    # Detect language of user's message
                    user_language = _detect_language(message)
                    logger.info(f"[Enforcement] User language detected: {user_language}")

                    # Get user's gender for personalized astrologer response
                    user_gender = await get_user_gender(phone, message)
                    logger.info(f"[Enforcement] User gender: {user_gender}")

                    astrologer = get_astrologer_personality(user_gender)
                    astrologer_name = astrologer["name"]
                    logger.info(f"[Enforcement] Selected astrologer: {astrologer_name} (opposite gender)")

                    # ===================================================================
                    # STEP 1: Try AI-generated contextual message FIRST
                    # ===================================================================
                    limit_message = None
                    if _enforcement_generator and ENABLE_AI_ENFORCEMENT:
                        try:
                            logger.info(f"[Enforcement] 🎯 Trying AI-generated enforcement message...")
                            limit_message = await _enforcement_generator.generate_enforcement_message(
                                enforcement_type="daily_limit",
                                user_id=user_id,
                                session_id=session_id,
                                astrologer_name=astrologer_name,
                                astrologer_personality=astrologer,
                                user_gender=user_gender,
                                language=user_language,
                                message_count=total_messages,
                                today_messages=today_messages,
                                mongo_logger_url=MONGO_LOGGER_URL
                            )
                            if limit_message:
                                logger.info(f"[Enforcement] ✅ Successfully generated AI message for daily limit")
                        except Exception as e:
                            logger.warning(f"[Enforcement] ⚠️ AI generation failed: {e}")

                    # Fallback to hardcoded messages if AI failed
                    if not limit_message and AI_ENFORCEMENT_FALLBACK:
                        logger.info(f"[Enforcement] Using hardcoded enforcement message")
                        # Generate personalized message from astrologer
                        if user_language == "english":
                            # English - personalized by astrologer
                            if astrologer_name == "Meera":
                                # Female astrologer (Meera) talking to male user
                                limit_message = (
                                    f"I'm really sorry, but your free messages and daily limit are done for today 😔\n\n"
                                    f"I feel bad that I can't help you right now. It's a system limitation, and I feel terrible about it.\n\n"
                                    f"Please use the payment button below to continue unlimited guidance. "
                                    f"Or you can wait until tomorrow - you'll get 5 free messages tomorrow.\n\n"
                                    f"Really sorry about this 🙏"
                                )
                            else:
                                # Male astrologer (Aarav) talking to female user
                                limit_message = (
                                    f"Main bilkul maafi chahta hoon ki aaj aur aapke free messages khatam ho gaye 😔\n\n"
                                    f"Mujhe bohot bura lag raha hai ki main aapki abhi madad nahi kar pa raha. "
                                    f"System ki limitation hai yeh, main kar bhi kya sakta hoon?\n\n"
                                    f"Agar aapko raasta chahiye toh payment button use karke subscription le sakti ho. "
                                    f"Ya fir kal ka wait kar sakte ho - kal aapko 5 free messages mil jayengi.\n\n"
                                    f"Maf kijiye ga 🙏"
                                )
                        else:
                            # Hinglish (DEFAULT) - personalized by astrologer
                            if astrologer_name == "Meera":
                                # Female astrologer (Meera) talking to male user
                                limit_message = (
                                    f"I'm really sorry, but your free messages and daily limit are done for today 😔\n\n"
                                    f"I feel bad that I can't help you right now. It's a system limitation, and I feel terrible about it.\n\n"
                                    f"Please use the payment button below to continue unlimited guidance. "
                                    f"Or you can wait until tomorrow - you'll get 5 free messages tomorrow.\n\n"
                                    f"Really sorry about this 🙏"
                                )

                    # Fallback to hardcoded messages
                    if not limit_message and AI_ENFORCEMENT_FALLBACK:
                        logger.info(f"[Enforcement] Using hardcoded enforcement message")
                        # Generate personalized message from astrologer
                        if user_language == "english":
                            # English - personalized by astrologer
                            if astrologer_name == "Meera":
                                # Female astrologer (Meera) talking to male user
                                limit_message = (
                                    f"I'm really sorry, but your free messages and daily limit are done for today 😔\n\n"
                                    f"I feel bad that I can't help you right now. It's a system limitation, and I feel terrible about it.\n\n"
                                    f"Please use the payment button below to continue unlimited guidance. "
                                    f"Or you can wait until tomorrow - you'll get 5 free messages tomorrow.\n\n"
                                    f"Really sorry about this 🙏"
                                )
                            else:
                                # Male astrologer (Aarav) talking to female user
                                limit_message = (
                                    f"Main bilkul maafi chahta hoon ki aaj aur aapke free messages khatam ho gaye 😔\n\n"
                                    f"Mujhe bohot bura lag raha hai ki main aapki abhi madad nahi kar pa raha. "
                                    f"System ki limitation hai yeh, main kar bhi kya sakta hoon?\n\n"
                                    f"Agar aapko raasta chahiye toh payment button use karke subscription le sakti ho. "
                                    f"Ya fir kal ka wait kar sakte ho - kal aapko 5 free messages mil jayengi.\n\n"
                                    f"Maf kijiye ga 🙏"
                                )
                        else:
                            # Hinglish (DEFAULT) - personalized by astrologer
                            if astrologer_name == "Meera":
                                # Female astrologer (Meera) talking to male user
                                limit_message = (
                                    f"I'm really sorry, but your free messages and daily limit are done for today 😔\n\n"
                                    f"I feel bad that I can't help you right now. It's a system limitation, and I feel terrible about it.\n\n"
                                    f"Please use the payment button below to continue unlimited guidance. "
                                    f"Or you can wait until tomorrow - you'll get 5 free messages tomorrow.\n\n"
                                    f"Really sorry about this 🙏"
                                )
                            else:
                                # Male astrologer (Aarav) talking to female user
                                limit_message = (
                                    f"I'm really sorry, but your free messages and daily limit are done for today 😔\n\n"
                                    f"I feel bad that I can't help you right now. It's a system limitation, and I feel terrible about it.\n\n"
                                    f"Please use the payment button below to continue unlimited guidance. "
                                    f"Or you can wait until tomorrow - you'll get 5 free messages tomorrow.\n\n"
                                    f"Really sorry about this 🙏"
                                )

                    if not limit_message:
                        logger.error("[Enforcement] Failed to generate enforcement message")
                        return {"status": "error", "error": "Failed to generate enforcement message"}

                    logger.info(f"[Enforcement] Generated enforcement message from {astrologer_name}:")
                    logger.info(f"[Enforcement] Message preview: {limit_message[:200]}...")

                    # STEP 2: Send the AI/hardcoded contextual message (split into multiple bubbles)
                    # Split message by double newlines to create multiple bubbles
                    message_parts = [part.strip() for part in limit_message.split('\n\n') if part.strip()]

                    async with httpx.AsyncClient(timeout=30.0) as client:
                        for idx, part in enumerate(message_parts, 1):
                            await _send_whatsapp_message(client, phone, part)
                            logger.info(f"[Enforcement] ✅ Sent message bubble {idx}/{len(message_parts)} to {phone}")

                    # Log the full message to MongoDB
                    await _log_to_mongo(
                        session_id, user_id, "assistant", limit_message, "whatsapp", "text", None,
                        nudge_level=1
                    )

                    # ===================================================================
                    # STEP 3: Send Razorpay payment button/link
                    # ===================================================================
                    if _razorpay_whatsapp_payment:
                        try:
                            logger.info(f"[Enforcement] 🎯 Sending Razorpay payment button...")
                            success = await _razorpay_whatsapp_payment.send_enforcement_with_razorpay_buttons(
                                phone=phone,
                                user_id=user_id,
                                astrologer_name=astrologer_name,
                                language=user_language,
                                enforcement_type="daily_limit",
                                mongo_logger_url=MONGO_LOGGER_URL,
                                send_intro_message=False  # Only send plan/button, no extra messages
                            )
                            if success:
                                logger.info(f"[Enforcement] ✅ Sent Razorpay payment button")
                            else:
                                logger.warning(f"[Enforcement] ⚠️ Razorpay payment button failed to send")
                        except Exception as e:
                            logger.warning(f"[Enforcement] ⚠️ Razorpay payment button error: {e}")

                    return {"status": "daily_limit_reached", "total_messages": total_messages, "today_messages": today_messages}
                else:
                    remaining = DAILY_MESSAGE_LIMIT - today_messages
                    logger.info(f"[Enforcement] Daily limit not reached ({today_messages}/{DAILY_MESSAGE_LIMIT}), {remaining} remaining")
                    # Continue processing message

            else:
                remaining_free = FREE_MESSAGE_LIMIT - total_messages
                logger.info(f"[Enforcement] User has {remaining_free} free messages remaining")

    except Exception as e:
        logger.error(f"[Enforcement] Error checking message limits: {e}", exc_info=True)
        # On error, allow message to avoid blocking users

    # ===================================================================

    # ==================== SUBSCRIPTION CHECK ====================

    # Check if user has valid subscription (trial or active)
    # Only enforced for SUBSCRIPTION_TEST_NUMBER in testing mode
    access = await _check_subscription_access(phone)

    if access.get("access") == "no_access":
        # User's trial has expired and no active subscription
        # OR New user who hasn't paid ₹1 yet
        logger.info(f"[Subscription] Access denied for {phone}")

        # Trial activation removed - users now get automatic access with 25 free messages
        # Send payment nudge to subscribe - personalized by astrologer
        user_gender = await get_user_gender(phone, message)
        logger.info(f"[Subscription] User gender: {user_gender}")

        astrologer = get_astrologer_personality(user_gender)
        astrologer_name = astrologer["name"]
        logger.info(f"[Subscription] Selected astrologer: {astrologer_name} for payment nudge")

        # DEBUG: Check if services are initialized
        logger.info(f"[Subscription] DEBUG: _razorpay_whatsapp_payment={'INITIALIZED' if _razorpay_whatsapp_payment else 'NOT INITIALIZED'}")
        logger.info(f"[Subscription] DEBUG: _enforcement_generator={'INITIALIZED' if _enforcement_generator else 'NOT INITIALIZED'}")
        logger.info(f"[Subscription] DEBUG: ENABLE_AI_ENFORCEMENT={ENABLE_AI_ENFORCEMENT}")

        # LAYER 1: Try WhatsApp payment buttons first (NEW)
        if _razorpay_whatsapp_payment:
            logger.info(f"[Subscription] 🎯 Trying WhatsApp payment buttons...")
        else:
            logger.warning(f"[Subscription] ⚠️ WhatsApp payment buttons NOT initialized, skipping to Layer 2")

        if _razorpay_whatsapp_payment:
            try:
                user_language = _detect_language(message)
                user_gender = await get_user_gender(phone, message)

                success = await _razorpay_whatsapp_payment.send_enforcement_with_razorpay_buttons(
                    phone=phone,
                    user_id=user_id,
                    astrologer_name=astrologer_name,
                    language=user_language,
                    enforcement_type="payment_nudge",
                    mongo_logger_url=MONGO_LOGGER_URL,
                    send_intro_message=False  # Only send plan/button, no extra messages
                )

                if success:
                    logger.info(f"[Subscription] ✅ Sent WhatsApp payment buttons for payment nudge")
                    return {"status": "payment_required", "method": "whatsapp_button"}
                else:
                    logger.warning(f"[Subscription] ⚠️ WhatsApp buttons returned False, trying fallback")

            except Exception as e:
                logger.warning(f"[Subscription] ⚠️ WhatsApp payment buttons failed: {e}")
                # Continue to fallback...

        # LAYER 2: Try AI-generated message
        payment_message = None
        if _enforcement_generator and ENABLE_AI_ENFORCEMENT:
            logger.info(f"[Subscription] 🎯 Trying AI-generated message...")
        else:
            if not _enforcement_generator:
                logger.warning(f"[Subscription] ⚠️ AI enforcement generator NOT initialized")
            if not ENABLE_AI_ENFORCEMENT:
                logger.warning(f"[Subscription] ⚠️ ENABLE_AI_ENFORCEMENT={ENABLE_AI_ENFORCEMENT} (AI disabled)")

        if _enforcement_generator and ENABLE_AI_ENFORCEMENT:
            try:
                user_language = _detect_language(message)
                payment_message = await _enforcement_generator.generate_enforcement_message(
                    enforcement_type="payment_nudge",
                    user_id=user_id,
                    session_id=session_id,
                    astrologer_name=astrologer_name,
                    astrologer_personality=astrologer,
                    user_gender=user_gender,
                    language=user_language,
                    message_count=total_messages,
                    today_messages=today_messages,
                    mongo_logger_url=MONGO_LOGGER_URL
                )
                if payment_message:
                    logger.info(f"[Subscription] Successfully generated AI message for payment nudge")
            except Exception as e:
                logger.warning(f"[Subscription] AI generation failed: {e}")

        # LAYER 3: Fallback to hardcoded messages
        if not payment_message and AI_ENFORCEMENT_FALLBACK:
            logger.info(f"[Subscription] Using hardcoded payment nudge message")
            if astrologer_name == "Meera":
                # Female astrologer (Meera) talking to male user
                payment_message = (
                    f"Hi! Aapke free messages khatam ho gaye hain 😔\n\n"
                    f"Main continue kar na chahti hoon lekin system ne limit laga di hai. "
                    f"Agar aapko chahiye toh 'PAY' type karke subscription le lo."
                )
            else:
                # Male astrologer (Aarav) talking to female user
                payment_message = (
                    f"Hi! Aapke free messages khatam ho gaye hain 😔\n\n"
                    f"Main continue kar na chahta hoon lekin system ne limit laga di hai. "
                    f"Agar aapko chahiye toh 'PAY' type karke subscription le lo."
                )

        if not payment_message:
            logger.error("[Subscription] Failed to generate payment nudge message")
            return {"status": "error", "error": "Failed to generate payment nudge"}

        logger.info(f"[Subscription] Payment message from {astrologer_name}: {payment_message[:150]}...")

        async with httpx.AsyncClient(timeout=30.0) as client:
            await _send_whatsapp_message(client, phone, payment_message)
            logger.info(f"[Subscription] Payment nudge sent to {phone}")

        # Log the payment nudge to MongoDB
        await _log_to_mongo(
            session_id,
            user_id,
            "assistant",
            payment_message,
            "whatsapp",
            "text",
            None,
            nudge_level=1  # Track as payment nudge
        )

        return {"status": "payment_required", "access": access}

    # Log subscription status for monitoring
    access_type = access.get("access", "unknown")
    if access_type != "trial" or access.get("skip_reason"):
        logger.info(f"[Subscription] {phone} has access: {access_type} (reason: {access.get('skip_reason', 'valid_access')})")

    # ==================== MESSAGE LIMIT CHECK ====================
    # Check message limit BEFORE processing with OpenClaw
    # Only applies if subscription check passed (user has access)

    try:
        # Initialize MongoDB client for message limiter (only if MONGO_LOGGER_URL is a direct MongoDB connection)
        mongo_client = None
        if MONGO_LOGGER_URL and MONGO_LOGGER_URL.startswith(("mongodb://", "mongodb+srv://")):
            mongo_client = MongoClient(MONGO_LOGGER_URL)

        if mongo_client:
            message_limiter = MessageLimiter(mongo_client)
            limit_check = message_limiter.check_message_limit(user_id)

            # Log limit check
            logger.info(f"[Message Limiter] User: {user_id}, Allowed: {limit_check.get('allowed')}, Phase: {limit_check.get('phase')}, Messages Remaining: {limit_check.get('messagesRemaining')}")

            # If paywall not enabled for this user, skip check (existing users)
            if not limit_check.get("paywallDisabled"):
                # Check if user has hit limit
                if not limit_check.get("allowed"):
                    # User has hit limit - send paywall message and block
                    paywall_message = limit_check.get("message")
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        await _send_whatsapp_message(client, phone, paywall_message)
                    await _log_to_mongo(session_id, user_id, "assistant", paywall_message, "whatsapp", "text", None, nudge_level=1)
                    logger.warning(f"[Message Limiter] User {user_id} hit message limit, blocking message")
                    return {"status": "blocked", "reason": "message_limit", "limit_check": limit_check}

                # Check if we should show paywall message (soft paywall at message 40)
                elif limit_check.get("showPaywall"):
                    paywall_type = limit_check.get("paywallType")
                    if paywall_type == "soft":
                        # Show soft paywall but still allow message
                        paywall_message = limit_check.get("message")
                        message_limiter.mark_paywall_shown(user_id)

                        # LAYER 1: Try WhatsApp payment buttons first (NEW)
                        buttons_sent = False
                        if _razorpay_whatsapp_payment:
                            try:
                                user_gender = await get_user_gender(phone, message)
                                user_language = _detect_language(message)
                                astrologer = get_astrologer_personality(user_gender)
                                astrologer_name = astrologer["name"]

                                # Create httpx client for button sending
                                async with httpx.AsyncClient(timeout=30.0) as button_client:
                                    success = await _razorpay_whatsapp_payment.send_enforcement_with_razorpay_buttons(
                                        phone=phone,
                                        user_id=user_id,
                                        astrologer_name=astrologer_name,
                                        language=user_language,
                                        enforcement_type="soft_paywall",
                                        mongo_logger_url=MONGO_LOGGER_URL,
                                        send_intro_message=False  # Only send plan/button, no extra messages
                                    )

                                    if success:
                                        logger.info(f"[Message Limiter] ✅ Sent WhatsApp buttons for soft paywall")
                                        buttons_sent = True
                                        paywall_message = None  # Don't send additional message
                                    else:
                                        logger.warning(f"[Message Limiter] ⚠️ WhatsApp buttons returned False")

                            except Exception as e:
                                logger.warning(f"[Message Limiter] ⚠️ WhatsApp buttons failed: {e}")

                        # LAYER 2: Try to generate AI-powered soft paywall message (if buttons not sent)
                        if not buttons_sent and _enforcement_generator and ENABLE_AI_ENFORCEMENT:
                            try:
                                user_gender = await get_user_gender(phone, message)
                                user_language = _detect_language(message)
                                astrologer = get_astrologer_personality(user_gender)
                                astrologer_name = astrologer["name"]

                                ai_message = await _enforcement_generator.generate_enforcement_message(
                                    enforcement_type="soft_paywall",
                                    user_id=user_id,
                                    session_id=session_id,
                                    astrologer_name=astrologer_name,
                                    astrologer_personality=astrologer,
                                    user_gender=user_gender,
                                    language=user_language,
                                    message_count=limit_check.get("messageCount", 40),
                                    today_messages=0,
                                    mongo_logger_url=MONGO_LOGGER_URL
                                )

                                if ai_message:
                                    paywall_message = ai_message
                                    logger.info(f"[Message Limiter] Using AI-generated soft paywall message")
                                else:
                                    logger.info(f"[Message Limiter] AI generation failed, using default message")
                            except Exception as e:
                                logger.warning(f"[Message Limiter] AI soft paywall generation failed: {e}")

                        # Send paywall message first (if buttons weren't sent), then continue to process normally
                        if paywall_message:
                            async with httpx.AsyncClient(timeout=30.0) as client:
                                await _send_whatsapp_message(client, phone, paywall_message)
                            await _log_to_mongo(session_id, user_id, "assistant", paywall_message, "whatsapp", "text", None, nudge_level=1)
                            logger.info(f"[Message Limiter] Soft paywall shown to user {user_id}, continuing message processing")
                        elif not buttons_sent:
                            logger.info(f"[Message Limiter] No paywall message sent, continuing message processing")

                        # Continue to process the actual message below...

    except Exception as e:
        logger.error(f"[Message Limiter] Error checking message limit: {e}")
        # On error, continue with message processing (fail open)

    # ============================================================

    if not OPENCLAW_URL:
        logger.warning("OPENCLAW_URL not set")
        return {"error": "OpenClaw URL not configured"}

    async with httpx.AsyncClient(timeout=300.0) as client:
        # Send typing indicator
        await _send_typing_indicator(client, message_id)

        headers = {
            "Content-Type": "application/json",
            "x-openclaw-session-key": f"agent:astrologer:whatsapp:direct:+{phone}",
            "x-openclaw-scopes": "operator.admin",
        }

        if OPENCLAW_GATEWAY_TOKEN:
            headers["Authorization"] = f"Bearer {OPENCLAW_GATEWAY_TOKEN}"

        # Detect user gender for personality adaptation
        user_gender = await get_user_gender(phone, message)

        # DEBUG: Log gender detection
        logger.info(f"[GENDER DEBUG] User: +{phone}, Message: {message[:50]}, Detected Gender: {user_gender}")

        # Create envelope with gender context for AI personality
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        # IMPORTANT: Inject gender into the envelope so AI can see it
        # This is required because OpenCLAW doesn't automatically inject metadata into system prompt
        gender_context = f" [Gender: {user_gender}]" if user_gender != "unknown" else ""
        envelope = f"[From: WhatsApp User (+{phone}){gender_context} at {timestamp}]"

        # Build context text (no image data in text — that goes via input_image)
        if message_type != "text" and media_info:
            media_context = f" [Media Type: {message_type}"
            if message_type == "image" and media_info.get("caption"):
                media_context += f", Caption: {media_info['caption']}"
            elif message_type == "document" and media_info.get("filename"):
                media_context += f", Filename: {media_info['filename']}"
            media_context += "]"
            text_content = f"{envelope}{media_context}\n{message}"
        else:
            text_content = f"{envelope}\n{message}"

        # Build input: use structured content parts when image is present
        has_image_data = (
            media_info
            and media_info.get("base64_data")
            and message_type in ["image", "photo", "sticker"]
        )

        if has_image_data:
            # Use OpenClaw's input_image format — sends full base64 image
            mime = media_info.get("mime_type", "image/jpeg")

            # Ensure mime is one of the allowed types by the schema
            allowed_mimes = ["image/jpeg", "image/png", "image/gif", "image/webp"]
            if mime not in allowed_mimes:
                # Default to jpeg if an unsupported mime type is used
                mime = "image/jpeg"

            # Add system message to explicitly tell AI about user's gender
            gender_instruction = _get_gender_instruction(user_gender)

            content_parts = [
                {"type": "input_text", "text": f"{gender_instruction}\n\n{text_content}"},
                {
                    "type": "input_image",
                    "source": {
                        "type": "base64",
                        "media_type": mime,
                        "data": media_info["base64_data"],  # FULL base64, not truncated
                    },
                },
            ]
            payload_input = [
                {
                    "type": "message",
                    "role": "user",
                    "content": content_parts,
                }
            ]
            logger.info(f"Sending image to OpenClaw via input_image: mime={mime}, b64_len={len(media_info['base64_data'])}")
        else:
            # Add system message to explicitly tell AI about user's gender
            gender_instruction = _get_gender_instruction(user_gender)
            # Plain text input with gender instruction
            payload_input = f"{gender_instruction}\n\n{text_content}"

        payload = {
            "model": "agent:astrologer",
            "input": payload_input,
            "user": f"+{phone}",
            "metadata": {
                "user_gender": user_gender,
            }
        }

        # DEBUG: Log metadata being sent
        logger.info(f"[GENDER DEBUG] Sending to OpenClaw - User: +{phone}, Metadata: {payload['metadata']}")

        # Add lightweight metadata (no base64 in metadata — it goes in input_image)
        if media_info:
            payload["metadata"]["message_type"] = message_type
            payload["metadata"]["media_type"] = media_info.get("type", message_type)
            payload["metadata"]["media_id"] = media_info.get("id", "")
            if "caption" in media_info:
                payload["metadata"]["media_caption"] = media_info["caption"]
            if "filename" in media_info:
                payload["metadata"]["media_filename"] = media_info["filename"]

        response = await client.post(
            f"{OPENCLAW_URL}/v1/responses",
            json=payload,
            headers=headers,
        )

        if response.status_code != 200:
            logger.error(f"OpenClaw error {response.status_code}: {response.text}")
            return {"error": f"OpenClaw returned {response.status_code}"}

        data = response.json()

        # [DEBUG] Log the entire response structure
        logger.info(f"[RESPONSE_DEBUG] Response keys: {list(data.keys())}")
        if "output" in data:
            logger.info(f"[RESPONSE_DEBUG] Number of output items: {len(data['output'])}")
            for idx, item in enumerate(data["output"]):
                logger.info(f"[RESPONSE_DEBUG] Output item {idx}: type={item.get('type')}, keys={list(item.keys())}")
                if "content" in item:
                    logger.info(f"[RESPONSE_DEBUG] Item {idx} has {len(item['content'])} content entries")
                    for cidx, content in enumerate(item["content"]):
                        logger.info(f"[RESPONSE_DEBUG] Content {cidx}: type={content.get('type')}, has_text={'text' in content}")
                        if "text" in content:
                            text_preview = content["text"][:200] if content["text"] else ""
                            logger.info(f"[RESPONSE_DEBUG] Content {cidx} text preview: {repr(text_preview)}")

        # Extract reply text from response
        # CONCATENATE all text content entries (don't just take the first one)
        reply_parts = []
        tool_outputs = []

        if "output" in data:
            for item in data["output"]:
                # Process agent messages (type: message)
                if item.get("type") == "message" and item.get("content"):
                    for content in item["content"]:
                        if content.get("text"):
                            reply_parts.append(content["text"])

                # Process tool execution outputs (type: tool, execution, etc.)
                # Tool outputs contain MEDIA_BASE64 tokens from script execution
                if item.get("type") in ["tool", "execution", "function"] and item.get("content"):
                    for content in item["content"]:
                        # Extract text from tool outputs (contains MEDIA_BASE64)
                        if content.get("text"):
                            tool_outputs.append(content["text"])
                            logger.info(f"[TOOL_OUTPUT] Found tool output: {content['text'][:100]}...")

        if not reply_parts and not tool_outputs:
            logger.error(f"[RESPONSE_ERROR] No content found in response")
            return {"status": "no_reply"}

        # Combine agent messages and tool outputs
        # Tool outputs go FIRST so MEDIA_BASE64 is extracted before agent text
        all_parts = tool_outputs + reply_parts
        reply = "\n\n".join(all_parts)
        logger.info(f"[RESPONSE_DEBUG] Concatenated {len(reply_parts)} text parts + {len(tool_outputs)} tool outputs, total length: {len(reply)}")

        # Parse MEDIA: / MEDIA_BASE64: tokens from response
        logger.info(f"[DEBUG] Raw reply from agent (first 500 chars): {reply[:500]}...")
        clean_reply, media_items = _extract_media_from_reply(reply)
        logger.info(f"[DEBUG] Extracted {len(media_items)} media items, clean_reply length: {len(clean_reply)}")

        # ===================================================================
        # DETECT PDF REQUESTS FROM AI AGENT RESPONSE
        # ===================================================================

        # Check if AI agent's response contains a PDF request
        # Agent should include: "PDF_REQUEST: dob=YYYY-MM-DD, tob=HH:MM, place=CITY, name=NAME"
        if "PDF_REQUEST:" in clean_reply:
            logger.info(f"[PDF] Agent triggered PDF generation for {user_id}")

            try:
                # Parse the PDF request parameters from AI's response
                import re
                params = {}
                for param in ["dob", "tob", "place", "name"]:
                    match = re.search(rf"{param}=([^,\n]+)", clean_reply)
                    if match:
                        params[param] = match.group(1).strip()

                # Set default name if not provided
                if "name" not in params:
                    params["name"] = "User"

                # Validate required parameters
                if not all(k in params for k in ["dob", "tob", "place"]):
                    logger.error(f"[PDF] Missing required parameters: {params}")
                else:
                    logger.info(f"[PDF] Triggering PDF generation with params: {params}")

                    # Trigger PDF generation in background
                    generate_kundli_pdf_task.delay(phone, user_id, params["dob"], params["tob"], params["place"], params["name"])

                    logger.info(f"[PDF] PDF generation task triggered successfully")

            except Exception as e:
                logger.error(f"[PDF] Error processing PDF request: {e}", exc_info=True)

        # Send text reply (split on double-newline for separate bubbles)
        if clean_reply:
            bubbles = [b.strip() for b in clean_reply.split("\n\n") if b.strip()]
            for bubble in bubbles:
                await _send_whatsapp_message(client, phone, bubble)

        # Send any media items as images
        for media_item in media_items:
            if media_item["type"] == "base64":
                # Upload base64 image to WhatsApp Media API, then send
                media_id = await _upload_base64_to_whatsapp_media(
                    client,
                    media_item["value"],
                    media_item.get("mime_type", "image/png"),
                )
                if media_id:
                    await _send_whatsapp_image(client, phone, media_id=media_id, caption="Kundli Chart")
                else:
                    logger.error("Failed to upload media to WhatsApp")
            elif media_item["type"] == "url":
                # DALL-E URLs are temporary SAS tokens - need to download first
                # WhatsApp cannot access these directly
                logger.info(f"Processing DALL-E URL: {media_item['value'][:100]}...")

                # Download the image from DALL-E URL
                try:
                    async with httpx.AsyncClient(timeout=30.0) as dl_client:
                        from urllib.parse import unquote_plus
                        url_to_fetch = media_item["value"]

                        # [VERSION_MARKER] v2.1 - Smart signature-only decoding
                        logger.info(f"[URL_V2.1] ORIGINAL URL (first 150 chars): {url_to_fetch[:150]}")

                        # Extract and log signature specifically to verify encoding
                        if 'sig=' not in url_to_fetch:
                            logger.warning(f"[URL_V2.1] No signature found in URL, using as-is")
                        else:
                            sig_start = url_to_fetch.find('sig=') + 4
                            sig_end = url_to_fetch.find('&', sig_start)
                            if sig_end == -1:
                                sig_end = len(url_to_fetch)
                            original_signature = url_to_fetch[sig_start:sig_end]
                            logger.info(f"[URL_V2.1] Original signature: {original_signature}")

                            # Smart decode: Only decode the signature parameter, not the entire URL
                            # This preserves legitimate URL encoding in path/query while fixing over-encoded signatures
                            from urllib.parse import urlparse, urlunparse, urlencode, parse_qsl

                            parsed = urlparse(url_to_fetch)
                            query_params = dict(parse_qsl(parsed.query))

                            if 'sig' in query_params:
                                sig_value = query_params['sig']
                                logger.info(f"[URL_V2.1] Signature from query params: {sig_value[:100]}...")

                                # Repeatedly decode ONLY the signature until stable
                                prev_sig = sig_value
                                max_iterations = 5
                                iteration = 0

                                while '%' in sig_value and iteration < max_iterations:
                                    prev_sig = sig_value
                                    sig_value = unquote_plus(sig_value)
                                    iteration += 1
                                    logger.info(f"[URL_V2.1] Sig decode iteration {iteration}: {len(prev_sig)} -> {len(sig_value)} chars")
                                    logger.info(f"[URL_V2.1] Signature after iteration {iteration}: {sig_value[:100]}...")

                                    if len(sig_value) == len(prev_sig):
                                        # Check if no actual changes occurred (stable)
                                        if sig_value == prev_sig:
                                            break

                                # Update query params with decoded signature
                                query_params['sig'] = sig_value
                                logger.info(f"[URL_V2.1] Final decoded signature: {sig_value[:100]}...")

                                # Validate decoded signature format
                                # Azure SAS signatures should be base64-like: alphanumeric, +, /, =
                                # Should NOT contain % characters (those should have been decoded)
                                if '%' in sig_value:
                                    logger.error(f"[URL_V2.1] WARNING: Signature STILL contains % after decoding: {sig_value[:100]}...")
                                else:
                                    logger.info(f"[URL_V2.1] ✓ Signature looks clean (no % chars)")

                                # Reconstruct URL with decoded signature
                                new_query = urlencode(query_params, doseq=True)
                                url_to_fetch = urlunparse((
                                    parsed.scheme,
                                    parsed.netloc,
                                    parsed.path,
                                    parsed.params,
                                    new_query,
                                    parsed.fragment
                                ))

                                logger.info(f"[URL_V2.1] Reconstructed URL with decoded signature")
                            else:
                                logger.warning(f"[URL_V2.1] sig parameter not found in query params")

                        # Now download with the decoded signature URL
                        logger.info(f"[URL_V2.1] Starting download with decoded signature...")
                        logger.info(f"[URL_V2.1] Download URL (first 150 chars): {url_to_fetch[:150]}")
                        dl_response = await dl_client.get(url_to_fetch)

                        logger.info(f"[URL_V2.1] Response status: {dl_response.status_code}")
                        logger.info(f"[URL_V2.1] Response headers: {dict(dl_response.headers)}")

                        if dl_response.status_code != 200:
                            logger.error(f"[URL_V2.1] ERROR: Failed to download DALL-E image: {dl_response.status_code}")
                            logger.error(f"[URL_V2.1] URL used (first 200 chars): {url_to_fetch[:200]}")
                            logger.error(f"[URL_V2.1] Response body (first 500 chars): {dl_response.text[:500]}")

                            # Check signature state in failed URL
                            if 'sig=' in url_to_fetch:
                                sig_start = url_to_fetch.find('sig=') + 4
                                sig_end = url_to_fetch.find('&', sig_start)
                                if sig_end == -1:
                                    sig_end = len(url_to_fetch)
                                signature = url_to_fetch[sig_start:sig_end]
                                if '%' in signature:
                                    logger.error(f"[URL_V2.1] ERROR: Signature STILL contains % chars: {signature[:100]}...")
                                    logger.error(f"[URL_V2.1] This means signature is still over-encoded despite our fix!")
                                else:
                                    logger.error(f"[URL_V2.1] ERROR: Signature looks clean but download still failed: {signature[:100]}...")
                                    logger.error(f"[URL_V2.1] This might be a different issue (expiration, permissions, etc.)")

                            continue

                        # Get content type
                        content_type = dl_response.headers.get("content-type", "image/png")
                        if content_type.startswith("image/"):
                            mime_type = content_type.split(";")[0]
                        else:
                            mime_type = "image/png"

                        # Convert to base64
                        image_bytes = dl_response.content
                        base64_data = base64.b64encode(image_bytes).decode('utf-8')

                        # Upload to WhatsApp Media API
                        logger.info(f"Uploading DALL-E image to WhatsApp Media API (size: {len(image_bytes)} bytes)")
                        media_id = await _upload_base64_to_whatsapp_media(
                            client,
                            base64_data,
                            mime_type,
                        )

                        if media_id:
                            logger.info(f"DALL-E image uploaded successfully: media_id={media_id}")
                            await _send_whatsapp_image(client, phone, media_id=media_id, caption="Kundli Chart")
                        else:
                            logger.error("Failed to upload DALL-E image to WhatsApp Media API")

                except Exception as e:
                    logger.error(f"Error processing DALL-E URL: {e}", exc_info=True)

        await _log_to_mongo(session_id, user_id, "assistant", clean_reply or reply, "whatsapp")

        # ==================== INCREMENT MESSAGE COUNT ====================
        # Increment message count AFTER successful message processing
        try:
            mongo_client = None
            if MONGO_LOGGER_URL and MONGO_LOGGER_URL.startswith(("mongodb://", "mongodb+srv://")):
                mongo_client = MongoClient(MONGO_LOGGER_URL)
            if mongo_client:
                message_limiter = MessageLimiter(mongo_client)
                result = message_limiter.increment_message_count(user_id)
                logger.info(f"[Message Limiter] Incremented count for {user_id}: {result.get('messageCount', 0)} total messages")
        except Exception as e:
            logger.error(f"[Message Limiter] Error incrementing message count: {e}")
            # Don't fail the message if count increment fails
        # ===============================================================

        return {"status": "sent", "message_id": message_id}


async def _send_media_message(client: httpx.AsyncClient, phone: str, media_url: str, media_type: str = "image", caption: str = None) -> dict:
    """Send media message via WhatsApp API."""
    if not WHATSAPP_PHONE_ID or not WHATSAPP_ACCESS_TOKEN:
        logger.error("WhatsApp credentials missing")
        return {"error": "Credentials missing"}

    url = f"{FB_API_URL}/{WHATSAPP_PHONE_ID}/messages"

    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    # Build media payload
    media_key = media_type  # image, audio, video, document
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": media_type,
        media_key: {
            "link": media_url
        }
    }

    # Add caption for images/videos
    if caption and media_type in ["image", "video"]:
        payload[media_key]["caption"] = caption

    # Add filename for documents
    if media_type == "document" and caption:
        payload[media_key]["filename"] = caption

    response = await client.post(url, headers=headers, json=payload)

    if response.status_code in [200, 201]:
        msg_id = response.json().get("messages", [{}])[0].get("id")
        logger.info(f"Sent {media_type} to {phone}")
        return {"success": True, "message_id": msg_id}

    logger.error(f"WhatsApp send failed: {response.text}")
    return {"error": response.text}


@celery_app.task
def send_message_task(phone: str, message: str) -> dict:
    """
    Send a WhatsApp message asynchronously.
    Returns the message ID on success.
    """
    try:
        import asyncio
        result = asyncio.run(_send_whatsapp_message_async(phone, message))
        return result
    except Exception as e:
        logger.error(f"[Celery] Send task failed: {e}")
        return {"error": str(e)}


# Simple rate limiter to prevent hitting WhatsApp's rate limits
_user_message_counts = {}  # In-memory tracking (will reset on restart)

def _check_rate_limit(phone: str) -> bool:
    """
    Check if we're sending too many messages to a user.
    Returns True if rate limit is OK, False if we should wait.
    """
    import time
    current_time = int(time.time())
    minute_key = current_time // 60  # Current minute bucket

    if phone not in _user_message_counts:
        _user_message_counts[phone] = {}

    # Clean old entries (older than 1 minute)
    _user_message_counts[phone] = {
        k: v for k, v in _user_message_counts[phone].items()
        if current_time - k < 60
    }

    # Count messages in current minute
    count = sum(1 for t in _user_message_counts[phone].keys() if t // 60 == minute_key)

    if count >= MAX_MESSAGES_PER_MINUTE_PER_USER:
        logger.warning(f"[Rate Limit] {phone} has sent {count} messages in current minute, limiting")
        return False

    # Record this message
    _user_message_counts[phone][current_time] = True
    return True


async def _send_whatsapp_message_async(phone: str, message: str):
    """Async implementation of sending WhatsApp message."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        return await _send_whatsapp_message(client, phone, message)


async def _send_whatsapp_message(client: httpx.AsyncClient, phone: str, message: str):
    """Send message via WhatsApp API."""
    if not WHATSAPP_PHONE_ID or not WHATSAPP_ACCESS_TOKEN:
        logger.error("WhatsApp credentials missing")
        return {"error": "Credentials missing"}

    # Check rate limit before sending
    if not _check_rate_limit(phone):
        logger.warning(f"[Rate Limit] Skipping message to {phone} due to rate limit")
        return {"error": "rate_limited", "message": "Too many messages to this user"}

    url = f"{FB_API_URL}/{WHATSAPP_PHONE_ID}/messages"

    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": message}
    }

    response = await client.post(url, headers=headers, json=payload)

    if response.status_code in [200, 201]:
        msg_id = response.json().get("messages", [{}])[0].get("id")
        return {"success": True, "message_id": msg_id}

    logger.error(f"WhatsApp send failed: {response.text}")
    return {"error": response.text}


async def _send_typing_indicator(client: httpx.AsyncClient, message_id: str):
    """Send typing indicator via WhatsApp API."""
    if not WHATSAPP_PHONE_ID or not WHATSAPP_ACCESS_TOKEN:
        return

    url = f"{FB_API_URL}/{WHATSAPP_PHONE_ID}/messages"

    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
        "typing_indicator": {"type": "text"}
    }

    try:
        await client.post(url, headers=headers, json=payload)
    except Exception as e:
        logger.warning(f"Failed to send typing indicator: {e}")


async def _log_to_mongo(session_id: str, user_id: str, role: str, text: str, channel: str, message_type: str = "text", media_info: dict = None, nudge_level: int = None):
    """Log chat message to MongoDB."""
    if not MONGO_LOGGER_URL:
        return

    payload = {
        "sessionId": session_id,
        "userId": user_id,
        "role": role,
        "text": text,
        "channel": channel,
        "messageType": message_type
    }
    
    if nudge_level:
        payload["nudgeLevel"] = nudge_level

    # Add media info if present
    if media_info:
        payload["mediaInfo"] = media_info

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{MONGO_LOGGER_URL}/webhook",
                json=payload
            )
            if response.status_code == 200:
                logger.debug(f"Logged {role} message to MongoDB")
    except Exception as e:
        logger.warning(f"Failed to log to MongoDB: {e}")


@celery_app.task
def health_check_task():
    """Periodic health check task."""
    logger.info("[Celery] Health check - worker is running")
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@celery_app.task(bind=True, max_retries=2, default_retry_delay=60)
def generate_kundli_pdf_task(self, phone: str, user_id: str, dob: str, tob: str, place: str, name: str = "User"):
    """
    Generate and send Kundli PDF to user

    Args:
        phone: User's phone number (without +)
        user_id: User's ID (with +)
        dob: Date of birth
        tob: Time of birth
        place: Place of birth
        name: User's name
    """
    try:
        logger.info(f"[PDF Task] Starting for {user_id}: DOB={dob}, TOB={tob}, Place={place}")

        # Run async code in sync context
        import asyncio
        result = asyncio.run(_generate_kundli_pdf_async(phone, user_id, dob, tob, place, name))

        logger.info(f"[PDF Task] Completed for {user_id}: {result}")
        return result

    except Exception as e:
        logger.error(f"[PDF Task] Failed for {user_id}: {e}")
        # Retry with exponential backoff
        raise self.retry(exc=e, countdown=2 ** self.request.retries)


async def _calculate_kundli_swiss_ephemeris(dob: str, tob: str, place: str) -> dict:
    """
    Calculate kundli using local calculator (jyotishganit)
    """
    try:
        from app.services.kundli.calculator import calculate_kundli

        logger.info(f"[PDF] Calculating kundli with local calculator for {dob} {tob} {place}")

        # Call the calculator
        kundli_data = calculate_kundli(dob, tob, place)

        if "error" in kundli_data and "fallback_data" in kundli_data:
            logger.warning(f"[PDF] Using fallback data: {kundli_data['error']}")
            return kundli_data["fallback_data"]

        if "error" in kundli_data:
            logger.error(f"[PDF] Kundli calculation failed: {kundli_data['error']}")
            return {"error": kundli_data['error']}

        logger.info(f"[PDF] Kundli calculated successfully: Lagna={kundli_data.get('lagna')}, Rashi={kundli_data.get('moon_sign')}")
        return kundli_data

    except ImportError as ie:
        logger.error(f"[PDF] Failed to import kundli calculator: {ie}")
        return {"error": "Kundli calculator not available"}
    except Exception as e:
        logger.error(f"[PDF] Kundli calculation error: {e}", exc_info=True)
        return {"error": str(e)}


def _format_planet_positions_for_pdf(kundli_calculated: dict) -> dict:
    """
    Format planet positions from calculator output to PDF format
    """
    try:
        # The calculator already provides planet_positions in the correct format
        planet_positions = kundli_calculated.get("planet_positions", {})

        logger.info(f"[PDF] Formatted {len(planet_positions)} planet positions")
        return planet_positions

    except Exception as e:
        logger.error(f"[PDF] Error formatting planet positions: {e}")
        return {}


def _extract_dasha_info(kundli_calculated: dict) -> dict:
    """
    Extract dasha information from calculator output
    """
    try:
        # The calculator already provides dasha in the correct format
        dasha = kundli_calculated.get("dasha", {})

        return {
            "mahadasha": dasha.get("mahadasha", "Unknown"),
            "antardasha": dasha.get("antardasha", "Unknown")
        }

    except Exception as e:
        logger.error(f"[PDF] Error extracting dasha: {e}")
        return {"mahadasha": "Unknown", "antardasha": "Unknown"}


async def _generate_chart_images(kundli_data: dict) -> dict:
    """
    Generate Kundli chart images as base64

    Creates traditional North Indian Kundli charts with Hindi characters
    """
    from io import BytesIO
    from PIL import Image, ImageDraw, ImageFont
    import base64
    import os
    import urllib.request

    charts = {}

    # Colors matching the traditional Kundli style
    BG_COLOR = '#2A1A08'  # Dark brown background
    LINE_COLOR = '#8C7861'  # Brownish lines
    TEXT_COLOR = '#D1B054'  # Gold text

    # Hindi character mapping for planets
    HINDI_MAP = {
        'Sun': 'सु', 'Moon': 'च', 'Mars': 'कु', 'Mercury': 'बु',
        'Jupiter': 'गु', 'Venus': 'शु', 'Saturn': 'श',
        'Rahu': 'रा', 'Ketu': 'के', 'Lagna': 'ल'
    }

    SIGN_NAMES = [
        'Aries', 'Taurus', 'Gemini', 'Cancer', 'Leo', 'Virgo',
        'Libra', 'Scorpio', 'Sagittarius', 'Capricorn', 'Aquarius', 'Pisces'
    ]

    SIGN_ABBR = ["Ari", "Tau", "Gem", "Can", "Leo", "Vir", "Lib", "Sco", "Sag", "Cap", "Aqu", "Pis"]

    def get_devanagari_font():
        """Get Devanagari font for Hindi characters"""
        local_font = "NotoSansDevanagari-Regular.ttf"
        if os.path.exists(local_font):
            return local_font

        # Try Windows fonts
        win_fonts = ["C:\\Windows\\Fonts\\nirmala.ttf", "C:\\Windows\\Fonts\\mangal.ttf"]
        for wf in win_fonts:
            if os.path.exists(wf):
                return wf

        # Try Linux fonts
        linux_fonts = ["/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf"]
        for lf in linux_fonts:
            if os.path.exists(lf):
                return lf

        # Download from GitHub
        try:
            url = "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSansDevanagari/NotoSansDevanagari-Regular.ttf"
            urllib.request.urlretrieve(url, local_font)
            return local_font
        except:
            return None

    def get_house_from_sign(planet_sign, lagna_sign):
        """Calculate house number from sign using Vedic Whole Sign system"""
        sign_to_index = {
            "Aries": 0, "Taurus": 1, "Gemini": 2, "Cancer": 3, "Leo": 4, "Virgo": 5,
            "Libra": 6, "Scorpio": 7, "Sagittarius": 8, "Capricorn": 9, "Aquarius": 10, "Pisces": 11
        }

        p_idx = sign_to_index.get(planet_sign, 0)
        l_idx = sign_to_index.get(lagna_sign, 0)

        house = ((p_idx - l_idx) % 12) + 1
        return house

    def create_traditional_kundli(chart_type: str = "lagna") -> str:
        """Create traditional North Indian Kundli chart"""
        img_size = 400
        PAD = 20

        img = Image.new('RGB', (img_size, img_size), BG_COLOR)
        draw = ImageDraw.Draw(img)

        # Get fonts
        font_path_hindi = get_devanagari_font()

        if font_path_hindi:
            try:
                font_p = ImageFont.truetype(font_path_hindi, 16)
            except:
                font_p = ImageFont.load_default()
        else:
            font_p = ImageFont.load_default()

        try:
            font_s = ImageFont.truetype("arial.ttf", 11)
        except:
            try:
                font_s = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
            except:
                font_s = ImageFont.load_default()

        # Draw grid (North Indian style)
        L, T, R, B = PAD, PAD, img_size - PAD, img_size - PAD
        MX, MY = img_size // 2, img_size // 2

        draw.rectangle([L, T, R, B], outline=LINE_COLOR)
        draw.line([L, T, R, B], fill=LINE_COLOR)
        draw.line([R, T, L, B], fill=LINE_COLOR)
        draw.line([MX, T, R, MY], fill=LINE_COLOR)
        draw.line([R, MY, MX, B], fill=LINE_COLOR)
        draw.line([MX, B, L, MY], fill=LINE_COLOR)
        draw.line([L, MY, MX, T], fill=LINE_COLOR)

        # Get kundli details
        lagna = kundli_data.get("lagna", "Aries")
        moon_sign = kundli_data.get("moon_sign", "Pisces")
        nakshatra = kundli_data.get("nakshatra", "Unknown")

        lagna_idx = SIGN_NAMES.index(lagna) if lagna in SIGN_NAMES else 0

        # Parse planet positions
        planet_positions = kundli_data.get("planet_positions", {})
        house_planets = {}

        for planet_key, planet_data in planet_positions.items():
            if isinstance(planet_data, dict):
                house = planet_data.get("house", 1)
                planet_name = planet_data.get("planet", planet_key)
                hindi_char = HINDI_MAP.get(planet_name, planet_name[:2])

                if 1 <= house <= 12:
                    house_planets.setdefault(house, []).append(hindi_char)

        # Ensure Lagna is in House 1
        house_planets.setdefault(1, [])
        if 'ल' not in house_planets[1]:
            house_planets[1].insert(0, 'ल')

        # House positions (matching traditional layout)
        HOUSE_POS = {
            1: (200, 110), 2: (110, 65),  3: (65, 110),  4: (110, 200),
            5: (65, 290),  6: (110, 335), 7: (200, 290), 8: (290, 335),
            9: (335, 290), 10: (290, 200), 11: (335, 110), 12: (290, 65),
        }

        # Draw houses
        for i in range(12):
            h = i + 1
            s_idx = (lagna_idx + i) % 12
            s_text = f"{s_idx + 1} {SIGN_ABBR[s_idx]}"

            cx, cy = HOUSE_POS[h]

            # Draw sign text
            draw.text(
                (cx, cy - 18),
                s_text,
                fill=LINE_COLOR,
                font=font_s,
                anchor='mm'
            )

            # Draw planets
            planets = house_planets.get(h, [])
            if planets:
                planet_text = " ".join(planets)
                offset = 14 if len(planets) <= 2 else 18

                draw.text(
                    (cx, cy + offset),
                    planet_text,
                    fill=TEXT_COLOR,
                    font=font_p,
                    anchor='mm'
                )

        # Draw bottom info
        draw.text(
            (MX, img_size - 10),
            f"{nakshatra} | Moon: {moon_sign}",
            fill=TEXT_COLOR,
            font=font_s,
            anchor='mm'
        )

        # Convert to base64
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        img_str = base64.b64encode(buffer.getvalue()).decode()
        return f"data:image/png;base64,{img_str}"

    # Generate Lagna Kundli (Birth Chart)
    charts["birth_chart"] = create_traditional_kundli("lagna")

    # Generate Navamsa Chart (D9)
    # For navamsa, we'll use the same layout (can be enhanced later)
    charts["navamsa_chart"] = create_traditional_kundli("navamsa")

    logger.info(f"[PDF] Generated {len(charts)} traditional Kundli chart images")

    return charts


async def _generate_kundli_pdf_async(phone: str, user_id: str, dob: str, tob: str, place: str, name: str) -> dict:
    """Async implementation of PDF generation"""
    from app.services.kundli_pdf_generator import KundliPDFGenerator
    from app.services.whatsapp_api import WhatsAppAPI

    session_id = f"whatsapp:+{phone}"

    # Prepare user data
    user_data = {
        "name": name,
        "dateOfBirth": dob,
        "timeOfBirth": tob,
        "birthPlace": place
    }

    # Calculate kundli using Swiss Ephemeris (same as kundli chart feature)
    logger.info(f"[PDF] Calculating kundli with Swiss Ephemeris for {dob} {tob} {place}")

    kundli_calculated = await _calculate_kundli_swiss_ephemeris(dob, tob, place)

    if not kundli_calculated or "error" in kundli_calculated:
        logger.error(f"[PDF] Kundli calculation failed: {kundli_calculated}")
        return {"error": "Kundli calculation failed"}

    # Extract and format kundli data for PDF
    summary = kundli_calculated.get("summary", {})
    ai_summary = kundli_calculated.get("ai_summary", {})

    kundli_data = {
        "lagna": summary.get("lagna", "Unknown"),
        "moon_sign": summary.get("moon_sign", "Unknown"),
        "nakshatra": summary.get("nakshatra", "Unknown"),
        "planet_positions": _format_planet_positions_for_pdf(kundli_calculated),
        "dasha": _extract_dasha_info(kundli_calculated)
    }

    logger.info(f"[PDF] Calculated kundli: Lagna={kundli_data.get('lagna')}, Rashi={kundli_data.get('moon_sign')}, Nakshatra={kundli_data.get('nakshatra')}")

    # Generate chart images
    charts = await _generate_chart_images(kundli_data)

    # Generate PDF
    try:
        pdf_generator = KundliPDFGenerator()
        pdf_bytes = pdf_generator.generate_pdf(
            user_data,
            kundli_data,
            charts,
            openclaw_url=OPENCLAW_URL,
            openclaw_token=OPENCLAW_GATEWAY_TOKEN
        )

        logger.info(f"[PDF] PDF generated: {len(pdf_bytes)} bytes")

    except Exception as e:
        logger.error(f"[PDF] PDF generation failed: {e}", exc_info=True)
        return {"error": f"PDF generation failed: {str(e)}"}

    # Upload PDF to WhatsApp Media
    filename = f"Kundli_{user_id.replace('+', '')}.pdf"

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Upload PDF
        media_id = await _upload_pdf_to_whatsapp_media(client, pdf_bytes, filename)

        if not media_id:
            logger.error("[PDF] PDF upload to WhatsApp failed")
            return {"error": "PDF upload failed"}

        logger.info(f"[PDF] PDF uploaded to WhatsApp: {media_id}")

        # Send PDF via WhatsApp using media_id (not URL)
        whatsapp_api = WhatsAppAPI(
            phone_id=WHATSAPP_PHONE_ID,
            access_token=WHATSAPP_ACCESS_TOKEN
        )

        caption = "Yeh rahi aapki Kundli PDF! 📄✨"

        message_id = await whatsapp_api.send_document(
            to=phone,
            media_id=media_id,
            filename=filename,
            caption=caption
        )

        if message_id:
            logger.info(f"[PDF] Sent Kundli PDF to {user_id}, message_id={message_id}")

            # Log to MongoDB
            await _log_to_mongo(
                session_id,
                user_id,
                "assistant",
                f"Kundli PDF sent: {filename}",
                "whatsapp",
                "document",
                {"filename": filename, "size": len(pdf_bytes)}
            )

            return {"success": True, "message_id": message_id}
        else:
            logger.error("[PDF] Failed to send PDF via WhatsApp")
            return {"error": "Failed to send PDF"}


@celery_app.task
def proactive_nudge_task():
    """
    Send proactive nudges to inactive WhatsApp users.
    Runs every 5 minutes to check for users inactive for 8+ hours.
    Only sends messages between 9 AM - 10 PM IST.
    """
    import asyncio
    from datetime import timedelta, timezone

    try:
        logger.info("[Proactive Nudge] ===== TASK STARTED =====")

        # Check if within active hours (9 AM - 10 PM IST)
        from datetime import datetime
        import pytz
        ist = pytz.timezone('Asia/Kolkata')
        now_ist = datetime.now(ist)
        current_hour = now_ist.hour

        logger.info(f"[Proactive Nudge] Current time: {now_ist.strftime('%Y-%m-%d %H:%M:%S')} IST")

        if not (9 <= current_hour < 22):
            logger.info(f"[Proactive Nudge] Outside active hours ({current_hour}:00 IST), skipping")
            return {"status": "outside_active_hours", "current_hour": current_hour}

        # Query MongoDB Logger for inactive users
        logger.info(f"[Proactive Nudge] Checking for inactive users...")
        result = asyncio.run(_check_inactive_users())

        logger.info(f"[Proactive Nudge] ===== TASK COMPLETED =====")
        logger.info(f"[Proactive Nudge] Result: {result}")
        return result

    except Exception as e:
        logger.error(f"[Proactive Nudge] ===== TASK FAILED =====", exc_info=True)
        logger.error(f"[Proactive Nudge] Error: {e}")
        return {"error": str(e)}


async def _check_inactive_users():
    """
    Check for inactive users and send nudges.
    Only processes users inactive for 8-24 hours.
    """
    if not MONGO_LOGGER_URL:
        logger.error("[Proactive Nudge] MONGO_LOGGER_URL not configured!")
        return {"error": "MongoDB URL not configured"}

    logger.info(f"[Proactive Nudge] Fetching users from {MONGO_LOGGER_URL}/messages")

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Get all users from MongoDB Logger
        try:
            response = await client.get(f"{MONGO_LOGGER_URL}/messages")
            logger.info(f"[Proactive Nudge] MongoDB response status: {response.status_code}")

            if response.status_code != 200:
                logger.error(f"[Proactive Nudge] Failed to fetch users: {response.status_code} - {response.text}")
                return {"error": f"Failed to fetch users: {response.status_code}"}

            data = response.json()
            users = data.get("users", [])
            logger.info(f"[Proactive Nudge] Total users found: {len(users)}")

        except Exception as e:
            logger.error(f"[Proactive Nudge] Exception fetching users: {e}", exc_info=True)
            return {"error": f"Exception fetching users: {e}"}

        # Process users in a try-except block
        try:
            from datetime import timezone
            now = datetime.now(timezone.utc)
            nudges_sent = 0
            users_checked = 0

            for user in users:
                user_id = user.get("userId", "")
                if not user_id or not user_id.startswith("+"):
                    continue

                # TESTING MODE: Only send to test number if configured
                if PROACTIVE_NUDGE_TEST_NUMBER:
                    if user_id != PROACTIVE_NUDGE_TEST_NUMBER:
                        logger.debug(f"[Proactive Nudge] TESTING MODE: Skipping {user_id} (not test number)")
                        continue
                    logger.info(f"[Proactive Nudge] ✓ Processing {user_id} (matches test number)")

                for session in user.get("sessions", []):
                    channel = session.get("channel", "").lower()
                    if "whatsapp" not in channel:
                        continue

                    # Get last message time
                    last_msg_str = session.get("lastMessageTime", "")
                    if not last_msg_str:
                        continue

                    try:
                        # Parse timestamp
                        if last_msg_str.endswith('Z'):
                            last_msg_time = datetime.fromisoformat(last_msg_str.replace('Z', '+00:00'))
                        else:
                            last_msg_time = datetime.fromisoformat(last_msg_str)

                        # Calculate inactive minutes
                        inactive_minutes = (now - last_msg_time).total_seconds() / 60

                        # Send nudge if inactive for at least 8 hours (480 minutes)
                        # Only sent between 9 AM - 10 PM IST
                        if inactive_minutes < 480:
                            logger.debug(f"[Proactive Nudge] {user_id}: inactive for {inactive_minutes:.0f} mins (skipping - waiting for 8 hour threshold)")
                            continue

                        users_checked += 1
                        hours_inactive = inactive_minutes / 60
                        logger.info(f"[Proactive Nudge] ELIGIBLE: {user_id} inactive for {hours_inactive:.1f} hours")

                        # DEDUP CHECK: Skip if nudge was already sent within the last 8 hours
                        nudge_redis_key = f"proactive_nudge_sent:{user_id}"
                        if _nudge_redis:
                            try:
                                if _nudge_redis.exists(nudge_redis_key):
                                    logger.debug(f"[Proactive Nudge] {user_id}: already nudged recently, skipping")
                                    continue
                            except Exception as redis_err:
                                logger.warning(f"[Proactive Nudge] Redis check failed for {user_id}: {redis_err}")

                        # Get recent conversation for topic and language detection
                        recent_conversation = await _get_recent_conversation_from_mongo(user_id, session)
                        detected_topic = recent_conversation.get("detected_topic")
                        detected_language = recent_conversation.get("detected_language", "en")

                        logger.info(f"[Proactive Nudge] {user_id}: topic={detected_topic}, language={detected_language}")

                        # Generate and send nudge message based on topic and language
                        nudge_message = _generate_nudge_message(user_id, detected_topic, hours_inactive, detected_language)

                        # Send nudge via WhatsApp
                        phone = user_id.replace("+", "")
                        await _send_whatsapp_message(client, phone, nudge_message)
                        nudges_sent += 1

                        # DEDUP SET: Mark this user as nudged with 8-hour expiry
                        if _nudge_redis:
                            try:
                                _nudge_redis.setex(nudge_redis_key, 8 * 3600, "1")  # 8 hours TTL
                                logger.info(f"[Proactive Nudge] Set dedup key for {user_id} (expires in 8h)")
                            except Exception as redis_err:
                                logger.warning(f"[Proactive Nudge] Redis set failed for {user_id}: {redis_err}")


                        logger.info(f"[Proactive Nudge] ✓ Nudge sent to {user_id} (topic: {detected_topic}, language: {detected_language})")

                        # Small delay to avoid rate limiting
                        await asyncio.sleep(2)

                    except Exception as e:
                        logger.error(f"[Proactive Nudge] Error processing {user_id}: {e}")
                        continue

            logger.info(f"[Proactive Nudge] Summary: Checked {users_checked} users, sent {nudges_sent} nudges")
            return {
                "status": "completed",
                "users_checked": users_checked,
                "nudges_sent": nudges_sent
            }

        except Exception as e:
            logger.error(f"[Proactive Nudge] Exception in _check_inactive_users: {e}", exc_info=True)
            return {"error": str(e)}


def _generate_nudge_message(user_id: str, detected_topic: str, hours_inactive: float, user_language: str = "en") -> str:
    """
    Generate personalized nudge message based on detected topic and user language.
    
    Args:
        user_id: User phone number
        detected_topic: Topic detected from conversation (marriage, career, health, education)
        hours_inactive: Hours since last message
        user_language: User's language ("en", "hi", or "hinglish")
    """
    import random

    # Hinglish message templates (casual Roman-script Hindi — DEFAULT for Indian users)
    topic_messages_hinglish = {
        "marriage": [
            "Suno, pichli baar shaadi ki baat hui thi na... chart mein kuch interesting dikh raha hai abhi. Dekhein kya?",
            "Arre, yaad hai shaadi ki baat? Abhi stars kaafi positive dikh rahe hain. Batau kya chal raha hai?",
            "Hey! Shaadi wali baat yaad hai? Chart mein timing ke baare mein kuch naya dikh raha hai. Check karein?",
        ],
        "career": [
            "Suno, career ki baat soch rahi thi... abhi chart mein kuch accha dikh raha hai professionally. Batau?",
            "Arre yaar, job ki baat yaad hai? Stars kuch positive dikha rahe hain. Dekhein kya opportunities aa rahi hain?",
            "Hey! Career ke baare mein kuch interesting dikh raha hai chart mein. Time achha chal raha hai. Batau?",
        ],
        "health": [
            "Suno, pichli baar health ki baat hui thi... kaisa feel ho raha hai ab? Chart mein kuch remedies hain jo help kar sakte hain.",
            "Arre, health ke baare mein soch rahi thi. Ab kaisa hai? Kuch simple upay hain jo fayda karenge.",
            "Hey! Tabiyat kaisi hai ab? Chart mein kuch acchi energy dikh rahi hai recovery ke liye.",
        ],
        "education": [
            "Suno, padhai ka kya scene hai? Chart mein abhi learning ke liye bohot accha time chal raha hai!",
            "Arre yaar, exams ki tayyari kaisi chal rahi hai? Stars kuch positive dikha rahe hain. Batau?",
            "Hey! Padhai ko lekar chart mein kuch interesting dikh raha hai. Check karein?",
        ]
    }

    kundli_messages_hinglish = [
        "Suno, kaafi din ho gaye baat kiye... chart mein kuch interesting chal raha hai abhi. Dekhein kya?",
        "Arre yaar, kaise ho? Stars mein kuch naya dikh raha hai tumhare liye. Batau?",
        "Hey! Bohot din ho gaye. Chart mein abhi accha time chal raha hai tumhara. Baat karein?",
        "Suno, tumhare chart mein aage ke liye kuch changes dikh rahe hain. Dekhna chahoge?",
        "Arre, yaad aa gaye tum! Chart mein kuch positive energy dikh rahi hai. Batau kya hai?",
    ]

    # English message templates
    topic_messages_en = {
        "marriage": [
            "Hey! Was thinking about our marriage discussion... Your chart shows some really positive energy right now. Should we check the timing?",
            "Hi! Remember we talked about marriage? The stars are looking favorable. Want me to take a look?",
            "Hey! Your chart has something interesting about relationships right now. Want to check?",
        ],
        "career": [
            "Hey! Was thinking about your career... Your chart shows some interesting movements professionally. Want me to check?",
            "Hi! Remember your career question? The timing looks good for progress. Should I analyze?",
            "Hey! Some positive career energy showing up in your chart right now. Want to take a look?",
        ],
        "health": [
            "Hey! How are you feeling now? Was thinking about your health... There are some simple remedies that might help. Want me to check?",
            "Hi! Hope you're feeling better. Your chart shows good recovery energy. Should I suggest some remedies?",
            "Hey! Your health sector looks stronger now. Want me to share some helpful insights?",
        ],
        "education": [
            "Hey! How are your studies going? Your chart shows this is a great time for learning! Want me to check?",
            "Hi! Remember your education discussion? The stars are favoring students right now. Should I analyze?",
            "Hey! Your chart shows excellent learning potential right now. Want to take a look?",
        ]
    }

    kundli_messages_en = [
        "Hey! It's been a while... Your chart shows some interesting movements this week. Should we check?",
        "Hi! Your chart indicates this is a good time for new beginnings. Want me to analyze?",
        "Hey! Some positive shifts happening in your chart right now. Want to take a look?",
        "Hi! Was looking at your chart... Some changes coming up ahead. Want to check?",
        "Hey! Your chart has some insights about your near future. Want to take a look?",
    ]

    # Pure Hindi (Devanagari) message templates
    topic_messages_hi = {
        "marriage": [
            "नमस्ते! शादी की बात याद है? चार्ट में कुछ positive दिख रहा है अभी। देखें क्या?",
            "सुनो, शादी के बारे में सोच रही थी... stars काफी अच्छे दिख रहे हैं। बताऊं?",
        ],
        "career": [
            "नमस्ते! करियर के बारे में सोच रही थी... चार्ट में कुछ अच्छा दिख रहा है। देखें?",
            "सुनो, नौकरी वाली बात याद है? अभी timing अच्छी दिख रही है। बताऊं?",
        ],
        "health": [
            "नमस्ते! तबियत कैसी है अब? कुछ उपाय हैं जो मदद कर सकते हैं।",
            "सुनो, सेहत के बारे में सोच रही थी। कैसा feel हो रहा है?",
        ],
        "education": [
            "नमस्ते! पढ़ाई कैसी चल रही है? चार्ट में अभी बहुत अच्छा time है!",
            "सुनो, exams की तैयारी कैसी है? Stars positive दिख रहे हैं।",
        ]
    }

    kundli_messages_hi = [
        "नमस्ते! कैसे हो? चार्ट में कुछ interesting दिख रहा है। बात करें?",
        "सुनो, काफी दिन हो गए... stars में कुछ नया है तुम्हारे लिए। बताऊं?",
        "नमस्ते! चार्ट में अभी अच्छा time चल रहा है। देखना चाहोगे?",
    ]

    # Select message based on language and topic
    if user_language == "hinglish":
        if detected_topic and detected_topic in topic_messages_hinglish:
            return random.choice(topic_messages_hinglish[detected_topic])
        else:
            return random.choice(kundli_messages_hinglish)
    elif user_language == "hi":
        if detected_topic and detected_topic in topic_messages_hi:
            return random.choice(topic_messages_hi[detected_topic])
        else:
            return random.choice(kundli_messages_hi)
    else:
        # English messages (default)
        if detected_topic and detected_topic in topic_messages_en:
            return random.choice(topic_messages_en[detected_topic])
        else:
            return random.choice(kundli_messages_en)


async def _get_recent_conversation_from_mongo(user_id: str, session_data: dict = None) -> dict:
    """
    Extract recent conversation from MongoDB session data and detect topics from USER questions.
    Stage 1: Topic-based message generation (Stage 2 will add Mem0 personalization)
    """
    result = {
        "detected_topic": None,
        "detected_language": "en",  # Default to English
        "last_questions": []
    }

    try:
        logger.info(f"[Proactive Nudge] Extracting conversation from session data for {user_id}")

        # Extract messages from session_data if provided
        if not session_data:
            logger.warning(f"[Proactive Nudge] No session data provided for {user_id}")
            return result

        # Debug: Log what keys are available in session_data
        logger.debug(f"[Proactive Nudge] Session data keys: {list(session_data.keys())}")

        messages = session_data.get("messages", [])
        if not messages:
            logger.warning(f"[Proactive Nudge] No 'messages' key in session data for {user_id}")
            logger.debug(f"[Proactive Nudge] Session data sample: {str(session_data)[:500]}")
            return result

        # Extract user questions only
        user_questions = []
        for msg in messages:
            if msg.get("role") == "user":
                text = msg.get("text", "")
                if text:
                    user_questions.append(text)

        if not user_questions:
            logger.info(f"[Proactive Nudge] No user questions found for {user_id}")
            return result

        # Analyze last 50 questions for better topic and language detection
        recent_questions = user_questions[-50:] if len(user_questions) >= 50 else user_questions
        result["last_questions"] = recent_questions
        logger.info(f"[Proactive Nudge] Total questions: {len(user_questions)}, analyzing last {len(recent_questions)} for context")
        logger.debug(f"[Proactive Nudge] Recent questions: {[q[:50]+'...' if len(q)>50 else q for q in recent_questions[:5]]}")

        # Language detection: Prioritize LAST message for current language preference
        def detect_language(texts):
            """Detect language from user messages. Prioritizes the LAST message.
            Returns: 'hi' (Devanagari Hindi), 'hinglish' (Roman-script Hindi), or 'en' (English)
            """
            # Expanded Hinglish word list (Roman-script Hindi/Hinglish)
            hinglish_words = [
                # Common conversational words
                "kya", "kaise", "kab", "kahan", "kidhar", "kiska", "kitna", "kaisa",
                "mera", "meri", "apka", "apki", "hum", "mujhe", "tumhe", "tumhare",
                "chahiye", "sakta", "sakti", "hoga", "hogi", "hota", "hoti",
                "batao", "batayen", "batana", "karo", "karna", "kar", "dekho", "dekh",
                "acha", "achha", "theek", "thik", "nahi", "nhi", "haan", "ji",
                "shaadi", "shadi", "kundli", "kundali", "dasha", "upay",
                "suno", "arre", "yaar", "bhai", "dost", "log",
                "hai", "hain", "tha", "thi", "raha", "rahi", "wala", "wali",
                "abhi", "aaj", "kal", "parso", "pehle", "baad",
                "bohot", "bahut", "bohut", "zyada", "kam", "thoda", "thodi",
                "kuch", "sab", "bilkul", "pakka", "zarur", "zaroor",
                "aana", "jana", "lena", "dena", "milna", "bolna", "sunna",
                "matlab", "isliye", "kyunki", "lekin", "par", "magar",
                "karunga", "karungi", "karenge", "rahega", "rahegi",
                "tension", "problem", "pareshani", "dikkat",
                "pata", "samajh", "jaanta", "jaanti",
                "ghar", "office", "kaam", "naukri", "padhai",
                "namaste", "namaskar",
                # Question forms
                "hogi", "hoga", "milega", "milegi", "lagega", "lagegi",
                "chahiye", "chahte", "chahti",
                # Greetings & fillers
                "hello", "hey", "hi",  # These alone don't count - need Hindi context
            ]

            # Check the LAST message first (most recent language preference)
            last_text = texts[-1] if texts else ""
            last_text_lower = last_text.lower()

            # Check for Devanagari in last message → Pure Hindi
            if any('\u0900' <= char <= '\u097F' for char in last_text):
                return "hi"

            # Count Hinglish words in the LAST message
            last_msg_words = set(re.split(r'\s+', last_text_lower))
            hinglish_matches = last_msg_words.intersection(set(hinglish_words))

            # If last message has 2+ Hinglish words or is short with 1+ Hinglish word → Hinglish
            if len(hinglish_matches) >= 2 or (len(last_msg_words) <= 5 and len(hinglish_matches) >= 1):
                return "hinglish"

            # Fallback: check across all recent messages
            all_text = " ".join(texts).lower()

            # Check for Devanagari across all messages
            if any('\u0900' <= char <= '\u097F' for char in all_text):
                return "hi"

            # Check Hinglish word density across all messages
            all_words = set(re.split(r'\s+', all_text))
            all_hinglish_matches = all_words.intersection(set(hinglish_words))

            if len(all_hinglish_matches) >= 3:
                return "hinglish"

            return "en"

        detected_language = detect_language(recent_questions)
        result["detected_language"] = detected_language
        logger.info(f"[Proactive Nudge] Language detected: {detected_language}")

        # Topic detection from user questions
        topic_keywords = {
            "marriage": ["shaadi", "marriage", "vivah", "rishta", "life partner", "spouse",
                        "milna", "shadi", "lagna", "partner", "engagement", "sagai",
                        "marry", "wedding", "shaadi kab", "engagement kab", "meri shaadi",
                        "meri engagement", "vivah", "rishta", "divorce"],
            "career": ["job", "career", "business", "kam", "naukri", "government", "govt",
                      "service", "employment", "work", "office", "company", "interview",
                      "promotion", "salary", "earning", "new macbook", "purchase", "buy",
                      "macbook", "laptop"],
            "health": ["health", "swasthya", "illness", "bemari", "rog", "tabiyat", "bimari",
                      "disease", "sick", "problem", "pain", "upay", "remedy", "medicine",
                      "theek", "recovery", "treatment", "kaise feel", "health issue",
                      "kharab", "thek", "swasthya", "major health"],
            "education": ["study", "padhai", "education", "exam", "test", "school", "college",
                         "university", "degree", "course", "result", "marks", "grade"]
        }

        topic_scores = {"marriage": 0, "career": 0, "health": 0, "education": 0}

        # Score each topic based on keyword matches
        for question in recent_questions:
            question_lower = question.lower()
            for topic, keywords in topic_keywords.items():
                for keyword in keywords:
                    if keyword in question_lower:
                        topic_scores[topic] += 1

        # Find topic with highest score
        max_score = max(topic_scores.values())
        if max_score > 0:
            # Get topic with highest score
            detected_topic = max(topic_scores, key=topic_scores.get)
            result["detected_topic"] = detected_topic
            logger.info(f"[Proactive Nudge] Topic detected: {detected_topic} (score: {max_score})")
        else:
            logger.info(f"[Proactive Nudge] No specific topic detected (scores: {topic_scores})")

        return result

    except Exception as e:
        logger.error(f"[Proactive Nudge] Error extracting conversation: {e}", exc_info=True)
        return result
