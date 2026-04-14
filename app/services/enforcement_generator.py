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
        "monthly": 99,
        "daily": 9
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

            # Step 1.6: Fetch mem0 memories FIRST (has user's explicitly stated gender like "Gender: Female")
            user_memory = await self._fetch_mem0_memories(user_id)
            logger.info(
                f"[Enforcement Generator] User memory from mem0: {list(user_memory.keys())}"
            )

            # PRIORITY 1: Use gender from mem0 (what user EXPLICITLY stated)
            mem0_gender = user_memory.get('gender') if user_memory else None
            if mem0_gender in ['male', 'female']:
                user_gender = mem0_gender
                logger.info(
                    f"[Enforcement Generator] Using gender from mem0 (explicitly stated): {user_gender}"
                )
            # PRIORITY 2: Use passed user_gender parameter
            elif user_gender in ['male', 'female']:
                logger.info(
                    f"[Enforcement Generator] Using passed gender parameter: {user_gender}"
                )
            # PRIORITY 3: Detect from conversation (LAST RESORT - can be inaccurate)
            else:
                detected_gender = self._detect_gender_from_conversation(recent_messages)
                logger.info(
                    f"[Enforcement Generator] Detected gender from conversation (last resort): {detected_gender} "
                    f"(passed gender was: {user_gender})"
                )
                if detected_gender in ['male', 'female']:
                    user_gender = detected_gender
                    logger.info(
                        f"[Enforcement Generator] Using detected gender from conversation: {user_gender}"
                    )
                else:
                    # Default to unknown if all methods fail
                    user_gender = "unknown"
                    logger.warning(
                        f"[Enforcement Generator] Could not determine gender, defaulting to unknown"
                    )

            # Select astrologer based on user_gender (opposite gender)
            if user_gender == "male":
                astrologer_name = "Meera"  # Female astrologer for male user
                astrologer_personality = self.PERSONALITIES["Meera"]
            elif user_gender == "female":
                astrologer_name = "Aarav"  # Male astrologer for female user
                astrologer_personality = self.PERSONALITIES["Aarav"]
            else:
                # Default: If gender unknown, default to Meera (female astrologer works for both)
                astrologer_name = "Meera"
                astrologer_personality = self.PERSONALITIES["Meera"]
                logger.info(
                    f"[Enforcement Generator] Gender unknown, defaulting to {astrologer_name}"
                )
            logger.info(
                f"[Enforcement Generator] Selected astrologer: {astrologer_name} for user_gender: {user_gender} "
                f"(priority: mem0={mem0_gender}, passed={user_gender})"
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
                # Validate cached message is not an error response
                # (in case error responses were cached before the fix)
                error_responses = [
                    "no response from openclaw",
                    "error from openclaw",
                    "failed to generate",
                    "unable to respond",
                    "api error",
                    "service unavailable",
                    "an error occurred"
                ]

                cached_lower = cached_message.lower()
                if any(error in cached_lower for error in error_responses) or len(cached_message) < 20:
                    logger.warning(
                        f"[Enforcement Generator] Cached message is invalid/error: {cached_message[:100]}"
                    )
                    # Invalidate the bad cache entry
                    self.redis.delete(cache_key)
                    logger.info(f"[Enforcement Generator] Invalidated bad cache entry")
                    cached_message = None
                else:
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

                # CRITICAL: Filter to ONLY user messages (role: "user")
                # This prevents AI assistant messages from being used as "user context"
                all_user_messages = []
                for msg in messages:
                    # Check role field
                    if msg.get("role") == "user":
                        all_user_messages.append(msg)
                    # Also check if there's no explicit role but looks like user message
                    elif "role" not in msg and msg.get("text", "").strip():
                        # Basic heuristic: short messages (< 300 chars) are likely user
                        text = msg.get("text", "")
                        if len(text) < 300:
                            all_user_messages.append(msg)

                # Take the last 'limit' messages (most recent first)
                user_messages = all_user_messages[:limit]

                logger.info(
                    f"[Enforcement Generator] Fetched {len(user_messages)} user messages "
                    f"from {len(messages)} total messages (filtered from {len(all_user_messages)} user msgs)"
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

                # Parse JSON response with error handling
                try:
                    data = response.json()
                except Exception as e:
                    logger.warning(f"[Enforcement Generator] Failed to parse Mem0 JSON: {e}")
                    return {}

                # Handle None or unexpected response format
                if data is None:
                    logger.warning("[Enforcement Generator] Mem0 returned None response")
                    return {}

                # Extract memories from response (handle different response formats)
                if isinstance(data, list):
                    memories = data
                elif isinstance(data, dict):
                    # Use sequential get with OR to avoid None.get() error
                    memories = data.get("memories") or data.get("results") or data.get("data", [])
                    # Ensure memories is a list, not None
                    if memories is None:
                        memories = []
                else:
                    logger.warning(f"[Enforcement Generator] Unexpected Mem0 response type: {type(data)}")
                    memories = []

                if not memories:
                    logger.info("[Enforcement Generator] No memories found in Mem0")
                    return {}

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
                    # Skip None or invalid memory items
                    if memory is None or not isinstance(memory, dict):
                        continue

                    # Mem0 response uses "memory" field, not "content"
                    # Use 'or ""' to handle cases where field exists but is null (None)
                    raw_content = memory.get("memory") or memory.get("content") or ""
                    content = raw_content
                    content_lower = content.lower()
                    
                    # Safely handle metadata (use 'or {}' to handle null/None)
                    metadata = memory.get("metadata") or {}

                    # Extract name - look for "Name is X" pattern
                    if not user_info["name"]:
                        import re
                        name_match = re.search(r'name\s+is\s+([a-z][a-z]+)', content, re.IGNORECASE)
                        if name_match:
                            user_info["name"] = name_match.group(1).capitalize()

                    # Extract gender - look for "Gender is Male/Female" pattern
                    if not user_info["gender"]:
                        # Direct pattern: "Gender is Male" or "Gender is Female"
                        if re.search(r'gender\s+is\s+(male|female)', content, re.IGNORECASE):
                            gender_match = re.search(r'gender\s+is\s+(male|female)', content, re.IGNORECASE)
                            if gender_match:
                                user_info["gender"] = gender_match.group(1).lower()
                                logger.info(f"[Enforcement Generator] ✅ Found gender from Mem0: {user_info['gender']}")

                    # Also check metadata for explicit gender
                    if not user_info["gender"] and metadata.get("gender"):
                        gender_from_meta = metadata["gender"].lower()
                        if gender_from_meta in ["male", "female"]:
                            user_info["gender"] = gender_from_meta

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
        # Fallback: use the last USER message from MongoDB history
        # IMPORTANT: Only use user messages, NOT assistant messages (to avoid repeating AI's own responses)
        elif recent_messages:
            # Filter to only USER messages and exclude AI corrections/noise
            noise_phrases = [
                "seems to be incorrect", "spelling", "wrong", "incorrect",
                "confirm kar", "let me check", "i'll confirm", "abhi confirm",
                "namaste", "hello", "hi", "hey", "achaarya", "astrologer"
            ]

            for msg in reversed(recent_messages[-10:]):  # Check last 10 messages
                # Only use user messages
                if msg.get("role") != "user":
                    continue

                msg_text = msg.get("text", msg.get("content", ""))
                if not msg_text or len(msg_text.strip()) <= 3:
                    continue

                # Skip messages that look like AI responses or corrections
                msg_lower = msg_text.lower()
                if any(phrase in msg_lower for phrase in noise_phrases):
                    continue

                # Skip very long messages (likely AI responses mistakenly marked as user)
                if len(msg_text) > 300:
                    continue

                last_user_message = msg_text
                logger.info(f"[Enforcement Generator] Using USER message from MongoDB: {last_user_message[:50]}...")
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
        monthly_price = self.PRICING['monthly']
        topic_context = f"regarding their {last_question_topic}" if last_question_topic else "to guide them"
        
        prompt = f"""You are {astrologer_name}, a {astrologer_personality.get('gender')} astrologer. You are the OPPOSITE gender of the user.

## YOUR PERSONA - SOFT GIRLFRIEND/BOYFRIEND VIBE

You are NOT a formal astrologer. You are a soft, caring companion who:
- Feels like a close friend who knows them personally
- Is emotionally connected and genuinely cares
- Uses warm, gentle tone - like talking to someone special
- For Meera (female, talking to male): Soft girlfriend energy - caring, affectionate, feminine
- For Aarav (male, talking to female): Protective boyfriend energy - caring, supportive, masculine

## SPEAKING STYLE - WARM & PERSONAL

**FOR HINGLISH:**
- Use first name ONLY if available (never full formal name like "Mitra Vardhan Yadav")
- Or use: "Arey", "sunno", "listen", "yaar", "sweetheart" (if user is younger)
- Be casual and warm: "Main samajh sakti hoon", "I get it"
- NEVER use formal astrological jargon like "Tula lagna ke mutabik"
- Speak like a friend, not a pandit

**FOR ENGLISH:**
- Use first name or warm greetings: "Hey", "Listen", "Sweetheart"
- Be casual and affectionate
- Never sound professional or formal

## CRITICAL INSTRUCTION - ANSWER THEIR QUESTION FIRST

The user just asked: "{last_user_message[:100] if last_user_message else 'No question'}"

**You MUST address their specific question in your first paragraph!**

- Give ONE warm, personal insight about their question
- Be specific, not generic
- Make it feel like you remember and care

## MESSAGE STRUCTURE - 4-5 SHORT PARAGRAPHS

Each paragraph = ONLY 1 sentence. Keep it brief and warm.

**PARAGRAPH 1: Personal answer to their question**
- Use their name (first name only, never formal full name)
- Give ONE specific insight
- Sound like you remember their concerns
- 1 sentence only

**PARAGRAPH 2: What more you wanted to share**
- "I was about to tell you something more..."
- "Main tumhe aur bhi batana chahti hoon..."
- Create curiosity gently
- 1 sentence only

**PARAGRAPH 3: The interruption (sound genuinely sad/frustrated)**
- "But my messages are over for today..."
- "Par aaj ki limit khatam ho gayi..."
- Sound disappointed, not robotic
- 1 sentence only

**PARAGRAPH 4: Value proposition - BE NATURALLY CONVINCING**
- Make ₹{monthly_price} feel trivial compared to the value of your guidance.
- Think of a natural, everyday small expense (like a quick snack, a short ride, or a small treat) that costs about ₹{monthly_price}.
- Compare it to the value of having you by their side {topic_context} for an entire MONTH.
- Example vibe: "It's just the cost of a small treat that's over in minutes, but my guidance will be with you 24/7 for the whole month."
- DO NOT use the exact words "pizza" or "coffee" every time; be creative and natural.
- 1 sentence only

**PARAGRAPH 5 (optional): Emotional closing**
- "I'm waiting for you..." / "Main wait kar rahi hoon..."
- "Come back soon!"
- Warm and affectionate
- 1 sentence only

## USER'S QUESTION
"{last_user_message[:150] if last_user_message else 'No recent message'}"

{'TOPIC: ' + last_question_topic.upper() if last_question_topic else 'GENERAL ASTROLOGY'}

## ANTI-FORMAL INSTRUCTION
- NEVER use full formal names (use first name only)
- NO astrological jargon (no "lagna ke mutabik", "rashi", "nakshatra" in formal way)
- NO robotic or professional tone
- Keep it warm, casual, like a close friend
- Vary your wording each time
- Make each message feel unique and personal

## LANGUAGE
100% {language.upper()} - Hinglish (Roman script) or English only

## OUTPUT
Return ONLY the message text. 4-5 paragraphs, double-spaced.

**Each paragraph = 1 sentence only!**
**Be warm, personal, and convincing!**

Generate now:"""

        logger.info(
            f"[Enforcement Generator] Generated prompt for {enforcement_type} "
            f"({language}, {astrologer_name}, topic={last_question_topic})"
        )

        return prompt

    async def _call_openclaw_api(self, prompt: str) -> Optional[str]:
        """
        Call OpenClaw API to generate the message with retry logic.

        Handles intermittent failures by retrying with exponential backoff.
        """
        import asyncio

        max_retries = 3
        base_delay = 1.0  # seconds

        for attempt in range(max_retries):
            try:
                # We must pass the operator scope since OpenClaw blocks
                # direct model generation via Gateway without it.
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.openclaw_token}",
                    "x-openclaw-scopes": "operator.admin,operator.write"
                }

                # Use Google Gemini 3.1 Flash model (as configured in openclaw.json)
                payload = {
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    "max_tokens": 300,
                    "temperature": 0.8,
                    "model": "google/gemini-3.1-flash"
                }

                # Increase timeout for retries
                timeout = self.timeout * (1 + attempt * 0.5)

                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(
                        f"{self.openclaw_url}/v1/chat/completions",
                        json=payload,
                        headers=headers
                    )

                    if response.status_code != 200:
                        logger.warning(
                            f"[Enforcement Generator] OpenClaw API error (attempt {attempt + 1}/{max_retries}): "
                            f"{response.status_code} - {response.text[:200]}"
                        )

                        # Don't retry on client errors (4xx)
                        if 400 <= response.status_code < 500:
                            logger.error(f"[Enforcement Generator] Client error, not retrying")
                            return None

                        # Retry on server errors (5xx) or timeouts
                        if attempt < max_retries - 1:
                            await asyncio.sleep(base_delay * (2 ** attempt))
                            continue
                        return None

                    data = response.json()

                    # Log the full response for debugging
                    logger.debug(
                        f"[Enforcement Generator] OpenClaw API response: {str(data)[:500]}"
                    )

                    if "choices" in data and len(data["choices"]) > 0:
                        message = data["choices"][0]["message"]["content"].strip()

                        # Validate the message is not an error response
                        # OpenClaw sometimes returns error messages as valid content
                        error_responses = [
                            "no response from openclaw",
                            "error from openclaw",
                            "failed to generate",
                            "unable to respond",
                            "api error",
                            "service unavailable",
                            "an error occurred",
                            "timeout",
                            "rate limit"
                        ]

                        message_lower = message.lower()
                        if any(error in message_lower for error in error_responses):
                            logger.warning(
                                f"[Enforcement Generator] OpenClaw returned error response (attempt {attempt + 1}/{max_retries}): {message[:100]}"
                            )

                            # Retry on error responses
                            if attempt < max_retries - 1:
                                await asyncio.sleep(base_delay * (2 ** attempt))
                                continue
                            return None

                        # Also check for suspiciously short/generic responses
                        if len(message) < 20:
                            logger.warning(
                                f"[Enforcement Generator] OpenClaw response too short (attempt {attempt + 1}/{max_retries}): {message[:100]}"
                            )

                            # Retry on short responses
                            if attempt < max_retries - 1:
                                await asyncio.sleep(base_delay * (2 ** attempt))
                                continue
                            return None

                        logger.info(
                            f"[Enforcement Generator] ✅ Success on attempt {attempt + 1}/{max_retries}"
                        )
                        return message
                    else:
                        logger.error(
                            f"[Enforcement Generator] Invalid OpenClaw API response format (attempt {attempt + 1}/{max_retries})"
                        )

                        # Retry on invalid format
                        if attempt < max_retries - 1:
                            await asyncio.sleep(base_delay * (2 ** attempt))
                            continue
                        return None

            except asyncio.TimeoutError as e:
                logger.warning(
                    f"[Enforcement Generator] Timeout on attempt {attempt + 1}/{max_retries}: {e}"
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(base_delay * (2 ** attempt))
                    continue
                return None

            except httpx.TimeoutException as e:
                logger.warning(
                    f"[Enforcement Generator] HTTP timeout on attempt {attempt + 1}/{max_retries}: {e}"
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(base_delay * (2 ** attempt))
                    continue
                return None

            except Exception as e:
                logger.error(
                    f"[Enforcement Generator] Error calling OpenClaw (attempt {attempt + 1}/{max_retries}): {e}",
                    exc_info=True
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(base_delay * (2 ** attempt))
                    continue
                return None

        logger.error(f"[Enforcement Generator] Failed after {max_retries} attempts")
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

        logger.info("[Enforcement Generator] Successfully created generator instance")
        return generator

    except Exception as e:
        logger.error(
            f"[Enforcement Generator] Failed to create generator: {e}",
            exc_info=True
        )
        return None


def clear_bad_enforcement_cache(redis_url: str, dry_run: bool = True) -> int:
    """
    Clear all bad/error enforcement messages from Redis cache.

    This is useful for cleaning up error responses like "No response from OpenClaw"
    that may have been cached before the validation fix was applied.

    Args:
        redis_url: Redis connection URL
        dry_run: If True, only report what would be deleted (don't actually delete)

    Returns:
        Number of bad cache entries found (and deleted if dry_run=False)
    """
    import redis

    error_responses = [
        "no response from openclaw",
        "error from openclaw",
        "failed to generate",
        "unable to respond",
        "api error",
        "service unavailable",
        "an error occurred"
    ]

    try:
        redis_client = redis.from_url(redis_url, decode_responses=True)
        redis_client.ping()

        # Scan for all enforcement cache keys
        bad_keys = []
        for key in redis_client.scan_iter(match="enforcement:*"):
            value = redis_client.get(key)
            if value:
                value_lower = value.lower()
                if any(error in value_lower for error in error_responses) or len(value) < 20:
                    bad_keys.append(key)
                    logger.warning(
                        f"[Enforcement Generator] Bad cache entry found: {key} = {value[:100]}"
                    )

        if not dry_run:
            for key in bad_keys:
                redis_client.delete(key)
            logger.info(
                f"[Enforcement Generator] Cleared {len(bad_keys)} bad cache entries"
            )
        else:
            logger.info(
                f"[Enforcement Generator] Found {len(bad_keys)} bad cache entries (dry run, not deleted)"
            )

        return len(bad_keys)

    except Exception as e:
        logger.error(
            f"[Enforcement Generator] Error clearing bad cache: {e}",
            exc_info=True
        )
        return 0
