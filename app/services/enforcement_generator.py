"""
AI-Generated Contextual Enforcement Messages Service

This service generates personalized enforcement messages (soft paywall, daily limit, payment nudge)
using OpenClaw API with recent conversation context and astrologer personality system.

Features:
- Context-aware messages referencing recent conversation
- Meera/Aarav personality system with proper Hindi verb forms
- Redis caching for 24 hours (cost optimization)
- Graceful fallback to hardcoded messages
- Feature flag for safe rollout
"""

import os
import json
import hashlib
import logging
from typing import Dict, Optional, Any, List
from datetime import datetime
import redis
import httpx

logger = logging.getLogger(__name__)


class EnforcementMessageGenerator:
    """
    Generate AI-powered contextual enforcement messages

    This service creates personalized messages based on:
    - Recent conversation context (last 5-10 messages)
    - User's language preference (English/Hinglish)
    - Astrologer personality (Meera for male users, Aarav for female users)
    - Enforcement type (soft_paywall, daily_limit, payment_nudge)
    """

    # Personality templates for Meera and Aarav
    PERSONALITIES = {
        "Meera": {
            "name": "Meera",
            "gender": "female",
            "traits": "soft, caring girlfriend-like companion who knows you personally - deeply understanding, emotionally connected, remembers your concerns, feels like a close friend who truly cares about your feelings",
            "speaking_style": "gentle, soft, caring tone - like a best friend who really understands you, uses feminine Hindi verbs (sakti, rahi, karungi), warm and empathetic, shows she remembers what you've shared",
            "hindi_verbs": "sakti, rahi, karungi, chahti, dekhungi, batati",
            "terms_of_endearment": "soft, caring phrases - 'I remember', 'I know', 'I understand', 'main samajh sakti hoon', use gentle tone - NEVER use 'beta' (motherly) or be too formal"
        },
        "Aarav": {
            "name": "Aarav",
            "gender": "male",
            "traits": "caring, protective boyfriend-like companion who knows you personally - deeply understanding, emotionally connected, remembers your concerns, feels like a close friend who truly cares about your feelings",
            "speaking_style": "gentle, supportive tone - like a best friend who really understands you, uses masculine Hindi verbs (sakta, raha, karunga), warm and empathetic, shows he remembers what you've shared",
            "hindi_verbs": "sakta, raha, karunga, chahta, dekhunga, batata",
            "terms_of_endearment": "soft, caring phrases - 'I remember', 'I know', 'I understand', 'main samajh sakta hoon', use gentle tone - NEVER use 'beta' (fatherly) or be too formal"
        }
    }

    # Pricing information (update from .env or settings if needed)
    PRICING = {
        "monthly": 299,
        "yearly": 1999,
        "daily": 10
    }

    def __init__(
        self,
        openclaw_url: str,
        openclaw_token: str,
        redis_client: redis.Redis,
        cache_ttl: int = 86400,  # 24 hours
        timeout: float = 10.0,
        mem0_url: str = None,
        mem0_api_key: str = None
    ):
        """
        Initialize enforcement message generator

        Args:
            openclaw_url: OpenClaw Gateway URL
            openclaw_token: OpenClaw Gateway auth token
            redis_client: Redis client for caching
            cache_ttl: Cache TTL in seconds (default: 24 hours)
            timeout: AI generation timeout in seconds
            mem0_url: Mem0 server URL (optional)
            mem0_api_key: Mem0 API key (optional)
        """
        self.openclaw_url = openclaw_url
        self.openclaw_token = openclaw_token
        self.redis = redis_client
        self.cache_ttl = cache_ttl
        self.timeout = timeout
        self.mem0_url = mem0_url or os.getenv("MEM0_URL", "https://rg4g0gkk0wwkk4cc00g4sg0c.api.hansastro.com")
        self.mem0_api_key = mem0_api_key or os.getenv("MEM0_API_KEY")

        logger.info(
            f"[Enforcement Generator] Initialized with cache_ttl={cache_ttl}s, timeout={timeout}s, mem0_enabled={bool(self.mem0_api_key)}"
        )

    async def generate_enforcement_message(
        self,
        enforcement_type: str,
        user_id: str,
        session_id: str,
        astrologer_name: str,
        astrologer_personality: Dict[str, Any],
        user_gender: str,
        language: str,
        message_count: int = 0,
        today_messages: int = 0,
        mongo_logger_url: Optional[str] = None,
        current_message: str = None
    ) -> Optional[str]:
        """
        Generate AI-powered contextual enforcement message

        Args:
            enforcement_type: Type of enforcement (soft_paywall, daily_limit, payment_nudge)
            user_id: User's phone number
            session_id: User's session ID
            astrologer_name: Name of astrologer (Meera or Aarav)
            astrologer_personality: Personality dictionary
            user_gender: User's gender (male or female)
            language: User's language preference (english or hinglish)
            message_count: Total messages sent by user
            today_messages: Messages sent today
            mongo_logger_url: MongoDB URL for fetching conversation context
            current_message: The user's current message/question that triggered enforcement

        Returns:
            Generated message or None if generation failed
        """
        try:
            # Step 1: Fetch 40 recent messages for better context understanding
            recent_messages = await self._fetch_recent_conversation(
                user_id, mongo_logger_url, limit=40
            )
            logger.info(
                f"[Enforcement Generator] Fetched {len(recent_messages)} recent messages "
                f"for user {user_id}"
            )

            # Step 1.5: Detect language and gender from recent conversation
            detected_language = self._detect_language_from_conversation(recent_messages)
            logger.info(
                f"[Enforcement Generator] Detected language from MongoDB: {detected_language} "
                f"(passed language: {language})"
            )
            # Use detected language from conversation instead of passed parameter
            language = detected_language

            # Detect gender from conversation
            detected_gender = self._detect_gender_from_conversation(recent_messages)
            logger.info(
                f"[Enforcement Generator] Detected gender from MongoDB: {detected_gender} "
                f"(passed gender: {user_gender})"
            )
            # Use detected gender if it's more certain than passed parameter
            if detected_gender in ['male', 'female']:
                user_gender = detected_gender
                # Select astrologer based on detected gender (opposite gender)
                if user_gender == "male":
                    astrologer_name = "Meera"  # Female astrologer for male user
                    astrologer_personality = self.PERSONALITIES["Meera"]
                else:
                    astrologer_name = "Aarav"  # Male astrologer for female user
                    astrologer_personality = self.PERSONALITIES["Aarav"]
                logger.info(
                    f"[Enforcement Generator] Updated astrologer to {astrologer_name} "
                    f"based on detected gender: {user_gender}"
                )

            # Step 1.6: Fetch mem0 memories for personalization
            user_memory = await self._fetch_mem0_memories(user_id)
            logger.info(
                f"[Enforcement Generator] User memory from mem0: {list(user_memory.keys())}"
            )

            # Step 2: Generate context hash for cache key
            context_hash = self._generate_context_hash(
                enforcement_type,
                message_count,
                today_messages,
                recent_messages[:3]  # Last 3 messages for variety
            )

            # Step 3: Check cache
            cache_key = f"enforcement:{enforcement_type}:{user_id}:{context_hash}"
            cached_message = self.redis.get(cache_key)

            if cached_message:
                logger.info(
                    f"[Enforcement Generator] Cache HIT for {enforcement_type} - "
                    f"returning cached message"
                )
                return cached_message

            logger.info(
                f"[Enforcement Generator] Cache MISS for {enforcement_type} - "
                f"generating new message"
            )

            # Step 4: Build AI prompt
            prompt = self._build_enforcement_prompt(
                enforcement_type=enforcement_type,
                astrologer_name=astrologer_name,
                astrologer_personality=astrologer_personality,
                user_gender=user_gender,
                language=language,
                message_count=message_count,
                today_messages=today_messages,
                recent_messages=recent_messages,
                user_memory=user_memory,
                current_message=current_message
            )

            # Step 5: Call OpenClaw API
            message = await self._call_openclaw_api(prompt)

            if not message:
                logger.warning(
                    f"[Enforcement Generator] OpenClaw API returned empty message"
                )
                return None

            # Step 6: Cache the generated message
            self.redis.setex(cache_key, self.cache_ttl, message)
            logger.info(
                f"[Enforcement Generator] Generated message cached for {self.cache_ttl}s"
            )

            # Step 7: Log success
            logger.info(
                f"[Enforcement Generator] Successfully generated {enforcement_type} message "
                f"for user {user_id} ({language}, {astrologer_name})"
            )
            logger.info(f"[Enforcement Generator] Message preview: {message[:200]}...")

            return message

        except Exception as e:
            logger.error(
                f"[Enforcement Generator] Error generating message: {e}",
                exc_info=True
            )
            return None

    async def _fetch_recent_conversation(
        self,
        user_id: str,
        mongo_logger_url: Optional[str],
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Fetch recent conversation from MongoDB for context

        Args:
            user_id: User's phone number
            mongo_logger_url: MongoDB URL
            limit: Maximum number of messages to fetch

        Returns:
            List of recent messages (user messages only)
        """
        try:
            if not mongo_logger_url:
                logger.warning(
                    "[Enforcement Generator] MONGO_LOGGER_URL not provided, "
                    "using empty context"
                )
                return []

            async with httpx.AsyncClient(timeout=10.0) as client:
                # Fetch last 50 messages (we'll filter for user messages)
                # NOTE: Use "userId" not "user_id" - the API expects camelCase
                response = await client.get(
                    f"{mongo_logger_url}/messages",
                    params={"userId": user_id, "role": "user", "limit": 50}
                )

                logger.info(f"[Enforcement Generator] API Response status: {response.status_code}")

                if response.status_code != 200:
                    logger.warning(
                        f"[Enforcement Generator] Failed to fetch messages: "
                        f"{response.status_code} - {response.text[:200]}"
                    )
                    return []

                data = response.json()
                logger.info(f"[Enforcement Generator] API Response keys: {list(data.keys())}")
                logger.info(f"[Enforcement Generator] API Response preview: {str(data)[:500]}")

                messages = data.get("messages", [])

                # Try alternative response structures
                if not messages and "sessions" in data:
                    # Response might have sessions structure
                    sessions = data.get("sessions", [])
                    if sessions and isinstance(sessions, list):
                        all_messages = []
                        for session in sessions:
                            session_messages = session.get("messages", [])
                            all_messages.extend(session_messages)
                        messages = all_messages

                # Take the last 'limit' messages (most recent first)
                user_messages = messages[:limit]

                logger.info(
                    f"[Enforcement Generator] Fetched {len(user_messages)} user messages "
                    f"from {len(messages)} total messages"
                )

                return user_messages

        except Exception as e:
            logger.error(
                f"[Enforcement Generator] Error fetching conversation: {e}",
                exc_info=True
            )
            return []

    def _detect_language_from_conversation(
        self,
        messages: List[Dict[str, Any]]
    ) -> str:
        """
        Detect user's language from their recent conversation history

        Analyzes the user's messages to determine if they communicate in:
        - English (predominantly English)
        - Hinglish (Hindi words written in English script)

        Args:
            messages: List of user messages from MongoDB

        Returns:
            "english" or "hinglish"
        """
        try:
            if not messages:
                logger.info("[Enforcement Generator] No messages to detect language, defaulting to english")
                return "english"

            # Common Hinglish words (Roman script Hindi)
            hinglish_keywords = {
                # Pronouns & common words
                'mai', 'me', 'main', 'mera', 'meri', 'mera', 'tera', 'teri', 'tum', 'tumhara',
                'ap', 'aap', 'aapka', 'aapki', 'hamara', 'hamari', 'uska', 'uski',
                # Verbs & auxiliaries
                'hai', 'hain', 'ho', 'hoga', 'hogi', 'hon', 'tha', 'thi', 'the',
                'kar', 'ke', 'ki', 'ko', 'se', 'mein', 'me', 'par', 'liye', 'wajahse',
                'karta', 'karti', 'karte', 'sakta', 'sakti', 'sake', 'chahta', 'chahti',
                'chaiye', ' Lena', 'dene', 'de', 'diya', 'dijiye', 'kijiye', 'batana',
                'bata', 'bolo', 'bol', 'aana', 'jana', 'ana', 'ja', 'raha', 'rahi', 'rahe',
                'karunga', 'karegi', 'karenge', 'karun', 'kar', 'rakha', 'rakhi', 'hain',
                # Time & place
                'abhi', 'ab', 'kal', 'aaj', 'aj', 'pehli', 'pichli', 'baad', 'mein',
                'kabhi', 'kab', 'kahan', 'kaise', 'kitna', 'kitni', 'kitne', 'itna',
                'itni', 'bahut', 'bohot', 'zyada', 'kam', 'thoda', 'bahut', 'kaafi',
                # Question words
                'kya', 'kyun', 'kyunki', 'kisko', 'kiska', 'kaun', 'kaunsa', 'kahan',
                # Connecting words
                'aur', 'or', 'lekin', 'magar', 'par', 'toh', 'to', 'bhi', 'hi', 'tak',
                'vaadi', 'ke_sath', 'ke_bina', 'ke_liye',
                # Feelings & reactions
                'acha', 'achha', 'theek', 'thik', 'sahi', 'galat', 'maza', 'maza',
                'dushman', 'dost', 'pyaar', 'pyar', 'love', 'hate', 'ghussa', 'gussa',
                'khush', 'udaaS', 'naraaz', 'khushi', 'gussaa', 'dard', 'pain',
                # Family & relations
                'mummy', 'papa', 'mummyji', 'papaaji', 'maa', 'baap', 'beti', 'beta',
                'bhai', 'behen', 'didi', 'bhaiya', 'family', 'ghar', 'gharpe',
                # Astrology specific
                'kundli', 'kundli', 'rashi', 'lagna', 'grah', 'nakshatra', 'dasha',
                'mahadasha', 'vivah', 'shaadi', 'marriage', 'kundli', 'janam', 'patrika',
                # Common phrases
                'ji', 'jii', 'sahij', 'sahi', 'bilkul', 'pakka', 'shayad', 'hmm',
                'haan', 'haanji', 'hanji', 'na', 'nahi', 'nahee', 'ok', 'okay',
                'sorry', 'thank', 'thanks', 'welcome', 'please', 'kripaya',
                # Actions
                'dekhna', 'dekho', 'sunna', 'suno', 'samajhna', 'samajh', 'samjho',
                'pata', 'maloom', 'chal', 'chalo', 'ruk', 'ruko', 'wait', 'karo',
                # Numbers & quantities
                'ek', 'do', 'teen', 'char', 'paanch', 'cheh', 'saath', 'aath', 'nau', 'das',
                'bees', 'tees', 'chaalis', 'pachas', 'sattar', 'assi', 'nabbe',
            }

            # Analyze user's last 10 messages
            hinglish_count = 0
            total_messages = 0
            total_words = 0

            for msg in messages[-10:]:  # Check last 10 messages
                content = msg.get("text", msg.get("content", ""))
                if not content:
                    continue

                total_messages += 1
                words = content.lower().split()
                total_words += len(words)

                # Count Hinglish keywords
                for word in words:
                    clean_word = word.strip('.,!?;:"\'-()[]{}')
                    if clean_word in hinglish_keywords:
                        hinglish_count += 1

            if total_messages == 0 or total_words == 0:
                logger.info("[Enforcement Generator] No valid messages to analyze, defaulting to english")
                return "english"

            # Calculate Hinglish ratio
            hinglish_ratio = hinglish_count / total_words

            # If more than 8% of words are Hinglish keywords, classify as Hinglish
            # (Lowered threshold to be more sensitive)
            is_hinglish = hinglish_ratio > 0.08

            detected = "hinglish" if is_hinglish else "english"

            logger.info(
                f"[Enforcement Generator] Language detection: "
                f"hinglish_words={hinglish_count}, total_words={total_words}, "
                f"ratio={hinglish_ratio:.3f}, detected={detected}"
            )

            return detected

        except Exception as e:
            logger.error(
                f"[Enforcement Generator] Error detecting language: {e}",
                exc_info=True
            )
            return "english"  # Default to English on error

    def _detect_gender_from_conversation(
        self,
        messages: List[Dict[str, Any]]
    ) -> str:
        """
        Detect user's gender from their conversation history

        Analyzes pronouns, verbs, and self-references to determine if user is:
        - male (uses masculine verb forms: karunga, sakta, hoon, etc.)
        - female (uses feminine verb forms: karungi, sakti, hoon, etc.)

        Args:
            messages: List of user messages from MongoDB

        Returns:
            "male", "female", or "unknown"
        """
        try:
            if not messages:
                logger.info("[Enforcement Generator] No messages to detect gender, returning unknown")
                return "unknown"

            # Gender indicators in Hindi/Hinglish
            masculine_indicators = {
                # First person masculine verb forms
                'karunga', 'karenga', 'karun', 'karunga', 'jaunga', 'jayenge',
                'dekhta', 'dekhte', 'dekhun', 'rahana', 'rehenga', 'rahun',
                # Pronouns & self-reference (masculine context)
                'maine', 'mujhe', 'mera', 'mere', 'mein', 'main',
                # Masculine verb endings
                'sakta', 'sakte', 'chahta', 'chahte', 'pahunchna', 'pahunchega',
                'hoga', 'honge', 'hoon', 'raha', 'rahe', 'rata',
                # Relationship terms (if user mentions being husband)
                'husband', 'pati', 'meri patni', 'meri wife',
            }

            feminine_indicators = {
                # First person feminine verb forms
                'karungi', 'karengi', 'jaungi', 'jayengi',
                'dekhti', 'dekhun', 'rahna', 'rehengi', 'rahungi',
                # Feminine verb endings
                'sakti', 'sakhti', 'sakti', 'chahti', 'chahte',
                'chahiye', 'pahunchegi', 'hogi', 'hongi',
                'hoon', 'rahi', 'rahen', 'rati',
                # Relationship terms (if user mentions being wife)
                'wife', 'patni', 'meri husband', 'mera pati',
            }

            male_score = 0
            female_score = 0
            total_indicators = 0

            # Analyze last 15 messages for gender clues
            for msg in messages[-15:]:
                content = msg.get("text", msg.get("content", "")).lower()
                if not content:
                    continue

                words = content.split()

                # Count masculine indicators
                for word in words:
                    clean_word = word.strip('.,!?;:"\'-()[]{}')
                    if clean_word in masculine_indicators:
                        male_score += 1
                        total_indicators += 1
                    elif clean_word in feminine_indicators:
                        female_score += 1
                        total_indicators += 1

                # Check for specific patterns (more weight)
                # "Main X hoon" patterns
                import re
                male_patterns = [
                    r'main\s+\w+\s+(?:karunga|jaunga|dunga|lunga|sakta)',
                    r'mera\s+(?:beta|son|bhai|dad|papa)',
                    r'maine\s+\w+\s+(?:kiya|liya|diya)',
                ]

                female_patterns = [
                    r'main\s+\w+\s+(?:karungi|jaungi|dungi|lungi|sakti)',
                    r'meri\s+(?:beti|daughter|sister|didi|mom|mummy)',
                ]

                for pattern in male_patterns:
                    if re.search(pattern, content):
                        male_score += 2
                        total_indicators += 2

                for pattern in female_patterns:
                    if re.search(pattern, content):
                        female_score += 2
                        total_indicators += 2

            if total_indicators == 0:
                logger.info("[Enforcement Generator] No gender indicators found in messages")
                return "unknown"

            # Calculate ratio
            male_ratio = male_score / total_indicators
            female_ratio = female_score / total_indicators

            # Determine gender with confidence threshold
            confidence_threshold = 0.60  # Need 60% confidence

            if male_ratio >= confidence_threshold:
                detected = "male"
            elif female_ratio >= confidence_threshold:
                detected = "female"
            else:
                # Not enough confidence
                detected = "unknown"

            logger.info(
                f"[Enforcement Generator] Gender detection: "
                f"male_score={male_score}, female_score={female_score}, "
                f"male_ratio={male_ratio:.2f}, female_ratio={female_ratio:.2f}, "
                f"detected={detected}"
            )

            return detected

        except Exception as e:
            logger.error(
                f"[Enforcement Generator] Error detecting gender: {e}",
                exc_info=True
            )
            return "unknown"

    async def _fetch_mem0_memories(self, user_id: str) -> Dict[str, Any]:
        """
        Fetch user memories from mem0 for personalization

        Args:
            user_id: User's phone number

        Returns:
            Dictionary with user info: {name, gender, concerns, preferences, birth_details}
        """
        if not self.mem0_url:
            logger.info("[Enforcement Generator] Mem0 not configured (no URL)")
            return {}

        try:
            # Normalize user_id for mem0 (ensure it has + prefix for phone numbers)
            normalized_id = user_id if user_id.startswith('+') else f"+{user_id}"

            headers = {
                "Content-Type": "application/json"
            }
            # Only add Authorization header if API key is provided
            if self.mem0_api_key:
                headers["Authorization"] = f"Token {self.mem0_api_key}"

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.mem0_url}/memory/{normalized_id}?limit=20",
                    headers=headers
                )

                if response.status_code != 200:
                    logger.warning(
                        f"[Enforcement Generator] Mem0 fetch failed: {response.status_code}"
                    )
                    return {}

                data = response.json()
                memories = data if isinstance(data, list) else data.get("memories", data.get("results", []))

                logger.info(
                    f"[Enforcement Generator] Fetched {len(memories)} memories from mem0"
                )

                # Extract meaningful information from memories
                user_info = {
                    "name": None,
                    "gender": None,
                    "concerns": [],
                    "preferences": [],
                    "birth_details": None
                }

                for memory in memories:
                    content = memory.get("content", "")
                    metadata = memory.get("metadata", {})

                    # Extract name
                    if not user_info["name"]:
                        # Look for name patterns
                        import re
                        name_match = re.search(r'(?:Name|User(?:\s*Name)?)\s*[:\s]*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)', content, re.IGNORECASE)
                        if name_match:
                            user_info["name"] = name_match.group(1)

                    # Extract gender
                    if not user_info["gender"]:
                        if any(word in content.lower() for word in ['gender:', 'male', 'female', 'gender']):
                            if 'female' in content.lower() or 'woman' in content.lower() or girl in content.lower():
                                user_info["gender"] = "female"
                            elif 'male' in content.lower() or 'man' in content.lower() or 'boy' in content.lower():
                                user_info["gender"] = "male"

                    # Extract concerns
                    content_lower = content.lower()
                    if any(word in content_lower for word in ['marriage', 'shaadi', 'vivah', 'wedding', 'love marriage', 'arranged marriage']):
                        if 'marriage' not in user_info["concerns"]:
                            user_info["concerns"].append("marriage")
                    if any(word in content_lower for word in ['career', 'job', 'naukri', 'business', 'work']):
                        if 'career' not in user_info["concerns"]:
                            user_info["concerns"].append("career")
                    if any(word in content_lower for word in ['health', 'swasthya', 'illness', 'medical']):
                        if 'health' not in user_info["concerns"]:
                            user_info["concerns"].append("health")
                    if any(word in content_lower for word in ['education', 'study', 'exam', 'college', 'school']):
                        if 'education' not in user_info["concerns"]:
                            user_info["concerns"].append("education")

                    # Extract birth details
                    if not user_info["birth_details"] and any(word in content_lower for word in ['dob:', 'born:', 'birth:', 'time:', 'place:']):
                        user_info["birth_details"] = content[:100]  # First 100 chars

                logger.info(
                    f"[Enforcement Generator] Extracted user info: name={user_info['name']}, gender={user_info['gender']}, concerns={user_info['concerns']}"
                )

                return user_info

        except Exception as e:
            logger.warning(
                f"[Enforcement Generator] Error fetching mem0 memories: {e}"
            )
            return {}

    def _generate_context_hash(
        self,
        enforcement_type: str,
        message_count: int,
        today_messages: int,
        recent_messages: List[Dict[str, Any]]
    ) -> str:
        """
        Generate context hash for cache key

        Includes hour bucket for hourly variety

        Args:
            enforcement_type: Type of enforcement
            message_count: Total message count
            today_messages: Today's message count
            recent_messages: Last 3 messages for variety

        Returns:
            Hex digest hash string
        """
        try:
            # Get current hour (changes every hour → different messages)
            current_hour = datetime.now().hour

            # Build hash string
            hash_input = f"{enforcement_type}:{message_count}:{today_messages}:{current_hour}:"

            # Add recent message content for variety
            for msg in recent_messages:
                content = msg.get("text", msg.get("content", ""))[:50]  # First 50 chars
                hash_input += f"{content[:20]}:"  # First 20 chars

            # Generate hash
            hash_digest = hashlib.md5(hash_input.encode()).hexdigest()[:8]

            logger.debug(
                f"[Enforcement Generator] Context hash: {hash_digest} "
                f"(hour: {current_hour}, messages: {message_count}/{today_messages})"
            )

            return hash_digest

        except Exception as e:
            logger.error(f"[Enforcement Generator] Error generating hash: {e}")
            return "default"

    def _build_enforcement_prompt(
        self,
        enforcement_type: str,
        astrologer_name: str,
        astrologer_personality: Dict[str, Any],
        user_gender: str,
        language: str,
        message_count: int,
        today_messages: int,
        recent_messages: List[Dict[str, Any]],
        user_memory: Dict[str, Any] = None,
        current_message: str = None
    ) -> str:
        """
        Build AI prompt for message generation

        Args:
            enforcement_type: Type of enforcement
            astrologer_name: Name of astrologer
            astrologer_personality: Personality dictionary
            user_gender: User's gender
            language: Language preference
            message_count: Total messages
            today_messages: Messages today
            recent_messages: Recent conversation
            user_memory: User's mem0 memories
            current_message: The user's current message/question

        Returns:
            Prompt string for OpenClaw API
        """
        # Get personality template
        personality = self.PERSONALITIES.get(
            astrologer_name,
            self.PERSONALITIES["Meera"]  # Default to Meera
        )

        # Build enhanced conversation context with topic extraction
        conversation_context = ""
        user_topics = []
        user_name_or_nickname = "dear"

        if recent_messages:
            # Extract topics and personal info from recent messages
            for msg in recent_messages[-10:]:  # Last 10 messages
                content = msg.get("text", msg.get("content", "")).lower()

                # Detect topics
                if any(word in content for word in ['marriage', 'shaadi', 'vivah', 'wedding', 'love', 'relationship', 'partner']):
                    if 'marriage' not in user_topics:
                        user_topics.append('marriage concerns')
                if any(word in content for word in ['career', 'job', 'naukri', 'business', 'work', 'office', 'promotion', 'salary']):
                    if 'career' not in user_topics:
                        user_topics.append('career')
                if any(word in content for word in ['health', 'swasthya', 'illness', 'disease', 'doctor', 'medicine', 'treatment']):
                    if 'health' not in user_topics:
                        user_topics.append('health concerns')
                if any(word in content for word in ['money', 'paisa', 'finance', 'investment', 'sip', 'stock', 'trading']):
                    if 'finance' not in user_topics:
                        user_topics.append('financial matters')
                if any(word in content for word in ['study', 'exam', 'padhai', 'college', 'school', 'education']):
                    if 'education' not in user_topics:
                        user_topics.append('education')
                if any(word in content for word in ['family', 'ghar', 'parents', 'mummy', 'papa', 'mother', 'father']):
                    if 'family' not in user_topics:
                        user_topics.append('family matters')

            # Build context summary
            memory_context = ""

            # First, use mem0 memory if available (has long-term personal info)
            if user_memory and user_memory.get("name"):
                user_name = user_memory.get("name", "dear")
                memory_context = f"\n## WHAT YOU KNOW ABOUT THIS USER (from memory)\n"
                memory_context += f"- Name: {user_memory.get('name', 'dear')}\n"

                if user_memory.get("birth_details"):
                    memory_context += f"- Birth details: {user_memory['birth_details']}\n"

                if user_memory.get("concerns"):
                    concerns = user_memory.get("concerns", [])
                    if concerns:
                        memory_context += f"- Concerns: {', '.join(concerns)}\n"

                memory_context += "\n"

            # Then, add recent conversation topics (short-term context)
            if user_topics:
                topics_str = ", ".join(user_topics)
                conversation_context = f"\n## RECENT TOPIC{'' if user_memory else 'S'} YOU DISCUSSED\nThis user has shared about their: {topics_str}.\n"
                conversation_context += "Reference these naturally in your message.\n"
            elif not user_memory:
                # Fallback: show recent conversation snippets
                conversation_context = "\n## RECENT CONVERSATION\n"
                for i, msg in enumerate(recent_messages[-3:], 1):
                    content = msg.get("content", "")[:80]
                    conversation_context += f"- User said: \"{content}...\"\n"

            # Combine both memory and recent context
            full_context = memory_context + conversation_context

        # Build enforcement-specific context
        enforcement_context = ""
        if enforcement_type == "soft_paywall":
            remaining = 40 - message_count
            enforcement_context = (
                f"The user has sent {message_count}/40 free messages. "
                f"This is their LAST free message before paywall. "
            )
        elif enforcement_type == "daily_limit":
            enforcement_context = (
                f"The user has sent {today_messages}/6 messages today. "
                f"DAILY LIMIT REACHED. Cannot send more messages today. "
            )
        elif enforcement_type == "payment_nudge":
            enforcement_context = (
                f"The user's trial has expired. "
                f"They've used all {message_count} free messages. "
            )

        # Pricing info
        pricing_info = (
            f"Pricing: ₹{self.PRICING['monthly']}/month, "
            f"₹{self.PRICING['yearly']}/year (best value), "
            f"₹{self.PRICING['daily']}/day"
        )

        # Get the user's CURRENT question/message for better context
        # PRIORITY: current_message (what they just asked) > recent_messages
        last_user_message = ""
        last_question_topic = None

        # First, try to use the current message that triggered enforcement
        if current_message and len(current_message.strip()) > 3:
            last_user_message = current_message.strip()
            logger.info(f"[Enforcement Generator] Using CURRENT message: {last_user_message[:50]}...")
        # Fallback: use the last message from MongoDB history
        elif recent_messages:
            for msg in reversed(recent_messages[-5:]):
                msg_text = msg.get("text", msg.get("content", ""))
                if msg_text and len(msg_text.strip()) > 3:
                    last_user_message = msg_text
                    logger.info(f"[Enforcement Generator] Using message from MongoDB: {last_user_message[:50]}...")
                    break

        # Detect topic from the message (current or MongoDB)
        if last_user_message:
            msg_lower = last_user_message.lower()
            if any(word in msg_lower for word in ['shaadi', 'marriage', 'vivah', 'wedding', 'love', 'relationship', 'partner']):
                last_question_topic = "marriage"
            elif any(word in msg_lower for word in ['career', 'job', 'naukri', 'business', 'work', 'office', 'promotion', 'salary']):
                last_question_topic = "career"
            elif any(word in msg_lower for word in ['health', 'swasthya', 'illness', 'disease', 'doctor', 'medical']):
                last_question_topic = "health"
            elif any(word in msg_lower for word in ['money', 'paisa', 'finance', 'investment', 'sip', 'stock']):
                last_question_topic = "finance"
            elif any(word in msg_lower for word in ['study', 'exam', 'padhai', 'education', 'college']):
                last_question_topic = "education"
            elif any(word in msg_lower for word in ['future', 'aage', 'kya', 'hoga', 'hogi', 'time', 'kab']):
                last_question_topic = "future"
            logger.info(f"[Enforcement Generator] Detected topic from message: {last_question_topic}")

        # Get user name from mem0 if available
        user_name = user_memory.get('name') if user_memory and user_memory.get('name') else None

        # Build full prompt with CONVINCING value proposition
        prompt = f"""You are {astrologer_name}, a caring astrologer friend. You are OPPOSITE gender of the user.

## CRITICAL INSTRUCTION - ANSWER THE USER'S QUESTION FIRST

The user just asked: "{last_user_message[:100] if last_user_message else 'No question'}"

**You MUST address their specific question in your first paragraph!**

If they asked about marriage → Talk about their marriage timing
If they asked about career → Talk about their career prospects
If they asked about health → Talk about their health concerns
If they asked about something else → Address that specific topic

**DO NOT give generic kundli answers. BE SPECIFIC to their question!**

## CRITICAL INSTRUCTION - 4-5 SHORT PARAGRAPHS

You MUST generate a message in 4-5 VERY SHORT paragraphs (separated by blank line).

**EACH paragraph MUST be ONLY 1 SENTENCE. No long paragraphs!**

**PARAGRAPH 1: Answer their SPECIFIC question**
- Address what they just asked about
- Give ONE specific insight about their topic
- 1 sentence only

**PARAGRAPH 2: What you were about to tell them**
- "Main tumhe aur bhi batana chahti hoon..."
- "I was just about to tell you..."
- Create curiosity about more details
- 1 sentence only

**PARAGRAPH 3: The interruption**
- Messages khatam ho gaye
- Sound frustrated that you can't continue
- 1 sentence only

**PARAGRAPH 4: Value comparison - BE CREATIVE, CONVINCE THEM NATURALLY**
- Make ₹199 feel like a tiny amount compared to the value
- Think: What else costs ₹200-300 that's gone in minutes?
  - One pizza (2-3 bites, done)
  - Auto-rickshaw ride to market (15 minutes, done)
  - One coffee at cafe (10 minutes, done)
  - Phone recharge for 2 days (gone)
  - One movie ticket (3 hours, done)
- BUT ₹199 here gives you: FULL MONTH of personal astrology guidance, 24/7 access, kundli analysis, career/marriage predictions, health guidance
- Make it conversational like: "Bas ek pizza ka hai, 10 minute mein khatam, but yeh poora mahine ka hai!"
- 1 sentence only

**PARAGRAPH 5 (optional): Emotional closing**
- "Main wait kar rahi hoon tumhara reply ka..."
- "Kal milte hain ya abhi le lo!"
- 1 sentence only

## USER'S QUESTION (MOST IMPORTANT - ADDRESS THIS!)
"{last_user_message[:150] if last_user_message else 'No recent message'}"

{'TOPIC: ' + last_question_topic.upper() if last_question_topic else 'NO SPECIFIC TOPIC - Use general astrology context'}

## ANTI-COPYING INSTRUCTION
- DO NOT use the exact same phrases every time
- Vary your examples naturally
- One time talk about pizza, next time about auto, then coffee, then movie
- Make each message feel unique and spontaneous
- Sound like a real friend, not a template bot

## LANGUAGE RULE
You must respond in 100% {language.upper()}:
- If ENGLISH: Only English words
- If HINGLISH: Only Roman Hinglish (Hindi in English script)

## OUTPUT FORMAT
Return ONLY the final message text. Format as 4-5 paragraphs separated by DOUBLE newlines.

**CRITICAL: Each paragraph must be 1 sentence only!**
**CRITICAL: First paragraph MUST address their specific question!**
**CRITICAL: Be creative with comparisons - vary them each time!**

Generate now:"""

        logger.info(
            f"[Enforcement Generator] Generated prompt for {enforcement_type} "
            f"({language}, {astrologer_name}, topic={last_question_topic})"
        )

        return prompt

    async def _call_openclaw_api(self, prompt: str) -> Optional[str]:
        """
        Call OpenClaw API to generate the message.
        """
        try:
            # We must pass the operator scope since OpenClaw blocks 
            # direct model generation via Gateway without it.
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.openclaw_token}",
                "x-openclaw-scopes": "operator.admin,operator.write"
            }

            payload = {
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "max_tokens": 300,
                "temperature": 0.8,
                "model": "openclaw"
            }

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.openclaw_url}/v1/chat/completions",
                    json=payload,
                    headers=headers
                )

                if response.status_code != 200:
                    logger.error(
                        f"[Enforcement Generator] OpenClaw API error: "
                        f"{response.status_code} - {response.text[:200]}"
                    )
                    return None

                data = response.json()

                if "choices" in data and len(data["choices"]) > 0:
                    message = data["choices"][0]["message"]["content"].strip()
                    return message
                else:
                    logger.error("[Enforcement Generator] Invalid OpenClaw API response format")
                    return None

        except Exception as e:
            logger.error(f"[Enforcement Generator] Error calling OpenClaw: {e}", exc_info=True)
            return None


# Helper function to create generator instance
def create_enforcement_generator(
    openclaw_url: str,
    openclaw_token: str,
    redis_url: str,
    cache_ttl: int = 86400,
    timeout: float = 10.0,
    mem0_url: str = None,
    mem0_api_key: str = None
) -> Optional[EnforcementMessageGenerator]:
    """
    Create enforcement message generator instance

    Args:
        openclaw_url: OpenClaw Gateway URL
        openclaw_token: OpenClaw Gateway auth token
        redis_url: Redis URL
        cache_ttl: Cache TTL in seconds
        timeout: AI generation timeout
        mem0_url: Mem0 server URL (optional)
        mem0_api_key: Mem0 API key (optional)

    Returns:
        EnforcementMessageGenerator instance or None if initialization fails
    """
    try:
        # Connect to Redis
        redis_client = redis.from_url(redis_url, decode_responses=True)
        redis_client.ping()

        # Create generator with mem0 integration
        generator = EnforcementMessageGenerator(
            openclaw_url=openclaw_url,
            openclaw_token=openclaw_token,
            redis_client=redis_client,
            cache_ttl=cache_ttl,
            timeout=timeout,
            mem0_url=mem0_url,
            mem0_api_key=mem0_api_key
        )
        generator = EnforcementMessageGenerator(
            openclaw_url=openclaw_url,
            openclaw_token=openclaw_token,
            redis_client=redis_client,
            cache_ttl=cache_ttl,
            timeout=timeout
        )

        logger.info("[Enforcement Generator] Successfully created generator instance")
        return generator

    except Exception as e:
        logger.error(
            f"[Enforcement Generator] Failed to create generator: {e}",
            exc_info=True
        )
        return None
