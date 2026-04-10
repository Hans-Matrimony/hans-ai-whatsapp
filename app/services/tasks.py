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
SUBSCRIPTION_TEST_NUMBER = os.getenv("SUBSCRIPTION_TEST_NUMBER", "9760347653")

# WhatsApp Payments Configuration (Flows API)
WHATSAPP_WABA_ID = os.getenv("WHATSAPP_WABA_ID")
WHATSAPP_PAYMENT_CONFIG_ID = os.getenv("WHATSAPP_PAYMENT_CONFIG_ID")
WHATSAPP_PAYMENT_MID = os.getenv("WHATSAPP_PAYMENT_MID")
WHATSAPP_FLOW_ID = os.getenv("WHATSAPP_FLOW_ID")  # Flow ID from Meta Business Manager

# Testing mode: Only send proactive nudges to this number (None = send to all users)
PROACTIVE_NUDGE_TEST_NUMBER = os.getenv("PROACTIVE_NUDGE_TEST_NUMBER", "+919760347653")

# Gender-based Astrologer Personality Configuration
ASTROLOGER_PERSONALITIES = {
    "male": {
        "name": "Aarav",
        "traits": "warm, caring, emotionally intelligent male astrologer friend",
        "speaking_style": "friendly, supportive, uses 'main' (I), caring tone",
        "greeting_style": "gentle, brotherly warmth"
    },
    "female": {
        "name": "Meera",
        "traits": "warm, caring, emotionally intelligent female astrologer friend",
        "speaking_style": "friendly, supportive, uses 'main' (I), caring tone",
        "greeting_style": "gentle, sisterly warmth"
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


def get_user_gender(phone: str, message: str) -> str:
    """
    Get user gender from MongoDB, cache, or detect from message.

    Priority: MongoDB > Cache > Detection

    Args:
        phone: User's phone number
        message: Current message (may contain name)

    Returns:
        "male", "female", or "unknown"
    """
    import asyncio

    user_id = f"+{phone}"

    # PRIORITY 1: Check MongoDB first (FASTEST!)
    try:
        # Run async function in sync context
        user_data = asyncio.run(user_metadata.get_user_metadata(phone))
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
        return """IMPORTANT: You are talking to a MALE user. You MUST respond as a FEMALE friend.
- Use FEMALE verbs: "sakti", "rahì", "dekh rahi hoon", "samajh sakti hoon"
- Be warm, nurturing, and emotionally supportive
- Use caring tone like "Aww", "please", "Tension mat lo"
- Show emotional empathy and validation"""
    elif user_gender == "female":
        return """IMPORTANT: You are talking to a FEMALE user. You MUST respond as a MALE friend.
- Use MALE verbs: "sakta", "raha", "dekh raha hoon", "samajh sakta hoon"
- Be strong, protective, and encouraging
- Use confident tone like "Bilkul", "Pakka", "Tum kar sakti ho"
- Build confidence and provide reliable support"""
    else:
        return """NOTE: User gender unknown. Use neutral warm friendly tone.
- Use inclusive language like "dost", "friend"
- Be warm and supportive without gender-specific expressions"""


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


async def _generate_payment_link(user_id: str, plan_number: int) -> str:
    """
    Generate Razorpay payment link for selected plan.
    Calls subscriptions service which creates Razorpay Payment Link.
    Returns direct Razorpay payment URL - no custom page needed!
    """
    if not SUBSCRIPTIONS_URL:
        logger.error("SUBSCRIPTIONS_URL not configured")
        return None

    try:
        # First, fetch all plans to find the selected one
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
            plan_id = selected_plan.get("planId")

            # Call subscriptions service to create Razorpay Payment Link
            # This endpoint will use Razorpay Payment Links API
            payment_link_response = await client.post(
                f"{SUBSCRIPTIONS_URL}/payments/create-payment-link",
                json={
                    "userId": user_id,
                    "planId": plan_id,
                    "currency": "INR"
                },
                timeout=30.0
            )

            if payment_link_response.status_code == 200:
                link_data = payment_link_response.json()
                razorpay_link = link_data.get("short_url") or link_data.get("payment_link")

                if razorpay_link:
                    logger.info(f"Generated Razorpay payment link for plan {plan_number}: {razorpay_link}")
                    return razorpay_link
                else:
                    logger.error("No payment_link in response")
                    return None
            else:
                logger.error(f"Failed to create payment link: {payment_link_response.status_code}")
                return None

    except Exception as e:
        logger.error(f"Error generating payment link: {e}")
        return None


async def _generate_trial_activation_link(user_id: str) -> str:
    """
    Generate ₹1 trial activation payment link.
    Creates a Razorpay Payment Link for the trial_activation plan.
    Returns direct Razorpay payment URL.
    """
    if not SUBSCRIPTIONS_URL:
        logger.error("SUBSCRIPTIONS_URL not configured")
        return None

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Call subscriptions service to create Razorpay Payment Link for trial activation
            payment_link_response = await client.post(
                f"{SUBSCRIPTIONS_URL}/payments/create-payment-link",
                json={
                    "userId": user_id,
                    "planId": "trial_activation",
                    "currency": "INR"
                }
            )

            if payment_link_response.status_code == 200:
                link_data = payment_link_response.json()
                razorpay_link = link_data.get("short_url") or link_data.get("payment_link")

                if razorpay_link:
                    logger.info(f"Generated ₹1 trial activation link for {user_id}: {razorpay_link}")
                    return razorpay_link
                else:
                    logger.error("No payment_link in trial activation response")
                    return None
            else:
                logger.error(f"Failed to create trial activation link: {payment_link_response.status_code}")
                return None

    except Exception as e:
        logger.error(f"Error generating trial activation link: {e}")
        return None


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
    # Check required variables for WhatsApp Flow
    # NOTE: Payment config (PAYMENT_CONFIG_ID, PAYMENT_MID) should be pre-configured in Meta Business Manager
    # They are NOT sent in the API request, so we don't check for them here
    required_vars = {
        "WHATSAPP_PHONE_ID": WHATSAPP_PHONE_ID,
        "WHATSAPP_ACCESS_TOKEN": WHATSAPP_ACCESS_TOKEN,
        "WHATSAPP_FLOW_ID": WHATSAPP_FLOW_ID
    }

    missing_vars = [var_name for var_name, var_value in required_vars.items() if not var_value]

    if missing_vars:
        logger.error(f"[WhatsApp Flow] Missing required variables: {missing_vars}. Falling back to payment link.")
        logger.error(f"[WhatsApp Flow] WHATSAPP_PHONE_ID: {'✓' if WHATSAPP_PHONE_ID else '✗'}")
        logger.error(f"[WhatsApp Flow] WHATSAPP_ACCESS_TOKEN: {'✓' if WHATSAPP_ACCESS_TOKEN else '✗'}")
        logger.error(f"[WhatsApp Flow] WHATSAPP_FLOW_ID: {'✓ ' + WHATSAPP_FLOW_ID if WHATSAPP_FLOW_ID else '✗'}")
        return None

    # Log payment config status (not required for API, but should be configured in Meta)
    if WHATSAPP_PAYMENT_CONFIG_ID:
        logger.info(f"[WhatsApp Flow] Payment Config ID '{WHATSAPP_PAYMENT_CONFIG_ID}' found (should be pre-configured in Flow)")
    else:
        logger.warning(f"[WhatsApp Flow] WHATSAPP_PAYMENT_CONFIG_ID not set - make sure payment is configured in Meta Business Manager!")

    if WHATSAPP_PAYMENT_MID:
        logger.info(f"[WhatsApp Flow] Payment MID '{WHATSAPP_PAYMENT_MID[:10]}...' found (should be pre-configured in Flow)")
    else:
        logger.warning(f"[WhatsApp Flow] WHATSAPP_PAYMENT_MID not set - make sure payment is configured in Meta Business Manager!")

    logger.info(f"[WhatsApp Flow] ✓ All required variables present. Flow ID: {WHATSAPP_FLOW_ID}")

    try:
        # Import here to avoid circular dependency
        from app.services.whatsapp_api import WhatsAppAPI

        whatsapp_api = WhatsAppAPI(
            phone_id=WHATSAPP_PHONE_ID,
            access_token=WHATSAPP_ACCESS_TOKEN
        )

        # Clean phone number for WhatsApp API
        clean_phone = phone.replace("+", "")

        # Send the flow message
        # Note: WhatsApp Flows with payment components must be pre-configured in Meta Business Manager
        # The Flow itself contains the payment configuration (amount, etc.)
        message_id = await whatsapp_api.send_flow(
            to=clean_phone,
            header=f"Pay for {plan_name}",
            body=f"Complete your payment of ₹{amount // 100} for {plan_name} safely within WhatsApp.",
            flow_id=WHATSAPP_FLOW_ID,
            flow_cta="Pay Now",
            payment_config_id=WHATSAPP_PAYMENT_CONFIG_ID,
            payment_mid=WHATSAPP_PAYMENT_MID
        )

        if message_id:
            logger.info(f"[WhatsApp Flow] Payment flow sent successfully: {message_id}")
            return message_id
        else:
            logger.error("[WhatsApp Flow] Failed to send payment flow")
            return None

    except Exception as e:
        logger.error(f"[WhatsApp Flow] Error sending payment flow: {e}")
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
    if clean_phone != SUBSCRIPTION_TEST_NUMBER:
        logger.debug(f"[Subscription] Not test number ({clean_phone} != {SUBSCRIPTION_TEST_NUMBER}), skipping check")
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
    # Check for PAY command FIRST, before subscription check
    # This allows ANY user to request plan options

    pay_command = message.strip().upper()
    if pay_command in ["PAY", "PAYMENT", "PLAN", "PLANS", "SUBSCRIBE"]:
        # Fetch and send plan options
        plans_message = await _get_plans_message()
        async with httpx.AsyncClient(timeout=30.0) as client:
            await _send_whatsapp_message(client, phone, plans_message)
        await _log_to_mongo(session_id, user_id, "assistant", plans_message, "whatsapp")
        return {"status": "plans_sent"}

    # Check if user is selecting a plan (replying with number 1, 2, 3, etc.)
    if message.strip().isdigit():
        plan_number = int(message.strip())

        # First fetch plan details
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                plans_response = await client.get(
                    f"{SUBSCRIPTIONS_URL}/plans?active_only=true"
                )
                if plans_response.status_code == 200:
                    plans_data = plans_response.json()
                    plans = plans_data.get("plans", [])

                    if 1 <= plan_number <= len(plans):
                        selected_plan = plans[plan_number - 1]
                        plan_id = selected_plan.get("planId")
                        plan_name = selected_plan.get("name", "Plan")
                        amount = selected_plan.get("price", 0)

                        # Try to send WhatsApp Flow (in-WhatsApp payment)
                        if WHATSAPP_FLOW_ID and WHATSAPP_PAYMENT_CONFIG_ID:
                            flow_message_id = await _send_whatsapp_payment_flow(
                                phone=phone,
                                user_id=user_id,
                                plan_id=plan_id,
                                amount=amount,
                                plan_name=plan_name
                            )

                            if flow_message_id:
                                flow_message = (
                                    f"Great! You selected **{plan_name}**.\n\n"
                                    f"Please complete the payment securely within WhatsApp. 💫\n\n"
                                    f"After payment, send me a message to start!"
                                )
                                async with httpx.AsyncClient(timeout=30.0) as client:
                                    await _send_whatsapp_message(client, phone, flow_message)
                                await _log_to_mongo(session_id, user_id, "assistant", flow_message, "whatsapp")
                                return {"status": "payment_flow_sent", "flow_id": flow_message_id}

                        # Fallback to payment link if Flow is not configured
                        payment_link = await _generate_payment_link(user_id, plan_number)
                        if payment_link:
                            link_message = (
                                f"Great! You selected **{plan_name}**.\n\n"
                                f"Click here to complete payment: {payment_link}\n\n"
                                f"After payment, come back and send me a message! 💫"
                            )
                            async with httpx.AsyncClient(timeout=30.0) as client:
                                await _send_whatsapp_message(client, phone, link_message)
                            await _log_to_mongo(session_id, user_id, "assistant", link_message, "whatsapp")
                            return {"status": "payment_link_sent", "payment_link": payment_link}

        except Exception as e:
            logger.error(f"Error processing plan selection: {e}")

        # Invalid plan number
        async with httpx.AsyncClient(timeout=30.0) as client:
            await _send_whatsapp_message(client, phone, "Invalid plan number. Please select a valid plan (1, 2, 3...).")
        return {"status": "invalid_plan", "plan_number": plan_number}

    # ===================================================================

    # ==================== SUBSCRIPTION CHECK ====================

    # Check if user has valid subscription (trial or active)
    # Only enforced for SUBSCRIPTION_TEST_NUMBER in testing mode
    access = await _check_subscription_access(phone)

    if access.get("access") == "no_access":
        # User's trial has expired and no active subscription
        # OR New user who hasn't paid ₹1 yet
        logger.info(f"[Subscription] Access denied for {phone}")

        # Check if this is a new user who needs to pay ₹1 to activate trial
        if access.get("require_payment"):
            # New user - Needs to pay ₹1 to activate 7-day trial
            logger.info(f"[Subscription] New user - requires ₹1 trial activation: {phone}")

            # Try to send WhatsApp Flow for trial activation (in-WhatsApp payment)
            if WHATSAPP_FLOW_ID and WHATSAPP_PAYMENT_CONFIG_ID:
                flow_message_id = await _send_whatsapp_payment_flow(
                    phone=phone,
                    user_id=user_id,
                    plan_id="trial_activation",
                    amount=100,  # ₹1 in paise
                    plan_name="7-Day Trial Activation"
                )

                if flow_message_id:
                    trial_message = (
                        "👋 Welcome to Astrofriend!\n\n"
                        "To activate your **7-day FREE trial**, please pay ₹1 (verification fee).\n\n"
                        "Complete the payment securely within WhatsApp. 💫\n\n"
                        "After payment, send me a message to start!"
                    )
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        await _send_whatsapp_message(client, phone, trial_message)
                    await _log_to_mongo(session_id, user_id, "assistant", trial_message, "whatsapp", "text", None, nudge_level=1)
                    return {"status": "trial_activation_flow_sent", "flow_id": flow_message_id}

            # Fallback to payment link if Flow is not configured
            trial_activation_link = await _generate_trial_activation_link(user_id)

            if trial_activation_link:
                trial_message = (
                    "👋 Welcome to Astrofriend!\n\n"
                    "To activate your **7-day FREE trial**, please pay ₹1 (verification fee).\n\n"
                    f"Click here: {trial_activation_link}\n\n"
                    "After payment, send me a message to start! 💫"
                )
                async with httpx.AsyncClient(timeout=30.0) as client:
                    await _send_whatsapp_message(client, phone, trial_message)
                await _log_to_mongo(session_id, user_id, "assistant", trial_message, "whatsapp", "text", None, nudge_level=1)
                return {"status": "trial_activation_required", "trial_activation_link": trial_activation_link}

        # Default payment nudge message (trial expired)
        payment_message = (
            "Your 7-day free trial has ended. To continue using Astrofriend services, "
            "please subscribe to a plan.\n\n"
            "Reply *PAY* to see subscription options."
        )

        async with httpx.AsyncClient(timeout=30.0) as client:
            await _send_whatsapp_message(client, phone, payment_message)

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
        # Initialize MongoDB client for message limiter
        mongo_client = MongoClient(MONGO_LOGGER_URL) if MONGO_LOGGER_URL else None

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
                        # Send paywall message first, then continue to process normally
                        async with httpx.AsyncClient(timeout=30.0) as client:
                            await _send_whatsapp_message(client, phone, paywall_message)
                        await _log_to_mongo(session_id, user_id, "assistant", paywall_message, "whatsapp", "text", None, nudge_level=1)
                        logger.info(f"[Message Limiter] Soft paywall shown to user {user_id}, continuing message processing")
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
        user_gender = get_user_gender(phone, message)

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
            mongo_client = MongoClient(MONGO_LOGGER_URL) if MONGO_LOGGER_URL else None
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


async def _send_whatsapp_message_async(phone: str, message: str):
    """Async implementation of sending WhatsApp message."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        return await _send_whatsapp_message(client, phone, message)


async def _send_whatsapp_message(client: httpx.AsyncClient, phone: str, message: str):
    """Send message via WhatsApp API."""
    if not WHATSAPP_PHONE_ID or not WHATSAPP_ACCESS_TOKEN:
        logger.error("WhatsApp credentials missing")
        return {"error": "Credentials missing"}

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

        caption = f"Namaste {user_data.get('name', 'User')}! 🙏 Here's your detailed Janam Kundli PDF."

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

                        # No need to check who sent the last message
                        # Just check if user has been inactive for 8+ hours
                        # The 8 hour threshold is already checked above (line 2346)
                        # If we reach here, user is eligible for nudge regardless of who sent last message
                        

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
    Stage 1: Topic-based messages (Stage 2 will be more personalized with Mem0)

    Args:
        user_id: User phone number
        detected_topic: Topic detected from conversation (marriage, career, health, education)
        hours_inactive: Hours since last message
        user_language: User's language preference ("en" or "hi")
    """

    # English message templates based on topic
    topic_messages_en = {
        "marriage": [
            "Hey! Was thinking about our shaadi discussion... Your 7th house lord is actually quite strong right now. Should we check what the planets say about your marriage timing?",

            "Namaste! You know, we were talking about your vivah earlier - Jupiter's current position might bring some good news for your relationships. Want me to analyze your kundli for this?",

            "Hi! Remember we discussed your shaadi? The transit of Venus is favorable right now. Shall I check your birth chart for the best period?",
        ],
        "career": [
            "Hey! Was thinking about your career discussion... Your 10th house has some interesting planetary movements happening. Want me to check what this means for your job prospects?",

            "Hi! Remember you asked about your career? Saturn's position suggests good things coming professionally. Should I analyze your kundli for the timing?",

            "Namaste! Your career discussion has been on my mind... Mercury is favoring your profession house right now. Want to know what opportunities are coming?",
        ],
        "health": [
            "Hey! How are you feeling now? We talked about your health earlier... There are some simple remedies that might really help based on your current planetary position. Want me to check?",

            "Hi! Was thinking about your health... The 6th house lord is well-placed in your chart right now, which is good for recovery. Should I suggest some personalized remedies?",

            "Namaste! Hope you're feeling better... Your health houses look stronger in your recent kundli analysis. Want me to suggest some astrological remedies?",
        ],
        "education": [
            "Hey! How are your studies going? We talked about your exams... Your 5th house is very strong right now - great time for students! Should I check what the stars say about your results?",

            "Hi! Remember your education discussion? Jupiter is blessing your learning house this month. Want me to analyze your chart for exam success?",

            "Namaste! Was thinking about your studies... Mercury's position is excellent for concentration right now. Should I check your kundli for favorable periods?",
        ]
    }

    # Hindi message templates based on topic
    topic_messages_hi = {
        "marriage": [
            "नमस्ते! आपकी शादी की बात सोच रहा था... आपकी सातवीं भाव का शास्त्री अभी काफी मजबूत है। क्या हम ग्रहों को देखें कि आपकी शादी का समय क्या है?",

            "हाय! हमने आपकी विवाह की बात की थी ना... बृहस्पति की वर्तमान स्थिति आपके रिश्तों के लिए अच्छी खबर ला सकती है। क्या मैं आपकी कुंडली का विश्लेषण करूं?",

            "नमस्ते! याद है न हमने आपकी शादी पर बात की थी? शुक्र का गोचर अनुकूल है। क्या हम आपकी जन्म कुंडली को देखें?",
        ],
        "career": [
            "हाय! आपकी करियर की बात सोच रहा था... आपकी दसवीं भाव में कुछ दिलचस्प ग्रह गतिविधि हो रही है। क्या मैं देखूं कि इसका क्या मतलब है?",

            "नमस्ते! याद है न आपने अपनी नौकरी के बारे में पूछा था? शनि की स्थिति व्यावसायिक रूप से अच्छी चीजें ला रही है। क्या मैं समय जानूं?",

            "हाय! आपकी नौकरी की चर्चा मेरे दिमाग में है... बुध आपकी व्यावसायिक भाव का अनुकूलन कर रहा है। क्या आपको पता है क्या अवसर आ रहे हैं?",
        ],
        "health": [
            "नमस्ते! आप अभी कैसे महसूस कर रहे हो? हमने आपकी सेहत की बात की थी... कुछ सरल उपचार मदद कर सकते हैं। क्या मैं बताऊं?",

            "हाय! आपकी सेहत की बात सोच रहा था... छठा भाव का स्वामी अच्छी तरह से स्थित है, जो ठीक है। क्या मैं कुछ व्यक्तिगत उपचार सुझाऊं?",

            "नमस्ते! आशा है आप ठीक महसूस कर रहे हों... आपकी सेहत की भावें कुंडली विश्लेषण में मजबूत दिख रही हैं। क्या मैं ज्योतिषीय उपचार सुझाऊं?",
        ],
        "education": [
            "हाय! आपकी पढ़ाई कैसी चल रही है? हमने आपकी परीक्षा की बात की थी... आपकी पांचवीं भाव बहुत मजबूत है! क्या मैं देखूं कि तारे क्या कहते हैं?",

            "नमस्ते! याद है न आपकी शिक्षा की चर्चा? बृहस्पति इस महीने आपकी शिक्षा भाव को आशीर्वाद दे रहा है। क्या मैं आपकी कुंडली का विश्लेषण करूं?",

            "हाय! आपकी पढ़ाई की बात सोच रहा था... बुध की स्थिति एकाग्रता के लिए उत्कृष्ट है। क्या मैं अनुकूल समय के लिए जांच करूं?",
        ]
    }

    # Kundli-based messages when no topic detected
    kundli_messages_en = [
        "Hey! It's been a while... Your kundli shows some interesting planetary movements this week. Should we check what the stars have in store for you?",

        "Namaste! Your birth chart indicates this is a good time for new beginnings. The planets are aligned in your favor - want me to analyze what this means for you?",

        "Hi! Your current dasha period looks quite favorable according to your kundli. The coming weeks might bring some important changes. Shall we check your predictions?",

        "Hey! Your Moon sign's position suggests this is a good time to revisit your goals. Your kundli has some insights about your near future. Want to take a look?",

        "Namaste! Was looking at your birth chart... Your ascendant lord is strong right now, which is excellent for overall growth. Should we explore what this means for you?",
    ]

    kundli_messages_hi = [
        "नमस्ते! काफी दिन हो गए... आपकी कुंडली कुछ दिलचस्प ग्रह गतिविधि दिखा रही है। क्या हम देखें कि तारे क्या कहते हैं?",

        "हाय! आपकी जन्म कुंडली बताती है कि यह नई शुरुआत के लिए अच्छा समय है। ग्रह आपके पक्ष में हैं - क्या मैं विश्लेषण करूं?",

        "नमस्ते! आपकी वर्तमान दशा आपकी कुंडली के अनुसार काफी अनुकूल दिख रही है। आने वाले हफ्तों में कुछ महत्वपूर्ण बदलाव आ सकते हैं। क्या हम जांचें?",

        "हाय! आपकी चंद्र राशि की स्थिति बताती है कि यह अपने लक्ष्यों को दोबारा देखने का अच्छा समय है। आपकी कुंडली में आपके नज़दीक भविष्य के बारे में कुछ जानकारी है। क्या देखना चाहते हैं?",

        "नमस्ते! आपकी जन्म कुंडली देख रहा था... आपका लग्न भाव का स्वामी अभी मजबूत है, जो समग्र विकास के लिए उत्कृष्ट है। क्या हम इसका अर्थ समझें?",
    ]

    # Select message based on language and topic
    if user_language == "hi":
        # Hindi messages
        if detected_topic and detected_topic in topic_messages_hi:
            import random
            messages = topic_messages_hi[detected_topic]
            return random.choice(messages)
        else:
            import random
            return random.choice(kundli_messages_hi)
    else:
        # English messages (default)
        if detected_topic and detected_topic in topic_messages_en:
            import random
            messages = topic_messages_en[detected_topic]
            return random.choice(messages)
        else:
            import random
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

        # Analyze only last 5 questions (RECENT context matters most!)
        recent_questions = user_questions[-5:]
        result["last_questions"] = recent_questions
        logger.info(f"[Proactive Nudge] Total questions: {len(user_questions)}, analyzing last 5 for recent context")
        logger.debug(f"[Proactive Nudge] Recent questions: {[q[:50]+'...' if len(q)>50 else q for q in recent_questions]}")

        # Language detection: Hindi vs English
        # Detect Hindi by checking for Devanagari characters or common Hindi words
        def detect_language(texts):
            hindi_indicators = [
                # Common Hindi words
                "है", "हूं", "क्या", "कैसे", "कहां", "कब", "किस", "कितना",
                "मेरा", "मेरी", "आपकी", "आप", "हम", "मुझे", "मुझे",
                "चाहिए", "सकता", "सकती", "होगा", "होगी", "होती",
                "जाना", "आना", "बताओ", "बताएं", "करूं", "करें",
                # Hinglish words
                "kya", "kaise", "kab", "kidhar", "kiska", "kitna",
                "mera", "meri", "apka", "apki", "hum", "mujhe",
                "chahiye", "sakta", "sakti", "hoga", "hogi",
                "jana", "aana", "batao", "batayen", "karo", "kar"
            ]

            hindi_score = 0
            total_chars = 0

            for text in texts:
                total_chars += len(text)
                text_lower = text.lower()

                # Check for Devanagari characters (Unicode range)
                if any('\u0900' <= char <= '\u097F' for char in text):
                    hindi_score += len(text)

                # Check for Hindi words
                for word in hindi_indicators:
                    if word in text_lower:
                        hindi_score += 5  # Weight more for words

            # If more than 20% Hindi content, classify as Hindi
            if total_chars > 0 and (hindi_score / total_chars) > 0.2:
                return "hi"
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
