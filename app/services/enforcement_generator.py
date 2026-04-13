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
        mongo_logger_url: Optional[str] = None
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

            # Step 1.5: Fetch mem0 memories for personalization
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
                user_memory=user_memory
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
        user_memory: Dict[str, Any] = None
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
                f"The user has sent {today_messages}/5 messages today. "
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

        # Get the user's last question/message for better context
        last_user_message = ""
        last_question_topic = None

        if recent_messages:
            for msg in reversed(recent_messages[-5:]):
                msg_text = msg.get("text", msg.get("content", ""))
                if msg_text and len(msg_text.strip()) > 3:
                    last_user_message = msg_text
                    # Detect topic from last message
                    msg_lower = msg_text.lower()
                    if any(word in msg_lower for word in ['shaadi', 'marriage', 'vivah', 'wedding', 'love', 'relationship', 'partner']):
                        last_question_topic = "marriage"
                    elif any(word in msg_lower for word in ['career', 'job', 'naukri', 'business', 'work', 'office']):
                        last_question_topic = "career"
                    elif any(word in msg_lower for word in ['health', 'swasthya', 'illness', 'disease']):
                        last_question_topic = "health"
                    elif any(word in msg_lower for word in ['money', 'paisa', 'finance', 'investment']):
                        last_question_topic = "finance"
                    elif any(word in msg_lower for word in ['study', 'exam', 'padhai', 'education']):
                        last_question_topic = "education"
                    break

        # Build full prompt with CONVINCING value proposition
        prompt = f"""You are {astrologer_name}, a caring astrologer friend. You are OPPOSITE gender of the user.

## CRITICAL INSTRUCTION - 3 PARAGRAPH STRUCTURE

You MUST generate a message in EXACTLY 3 paragraphs (separated by blank line):

**PARAGRAPH 1: Answer their question normally**
- Start by giving them a REAL astrological answer related to their question
- Show you're analyzing their chart/kundli
- Make it sound valuable and specific
- 2-3 sentences

**PARAGRAPH 2: The interruption - "I was saying more but..."**
- Say you have MORE to tell them
- "Main tumhe aur bhi batana chahti hoon..." or "I was just about to tell you..."
- Then say messages khatam ho gaye
- Create CURIOUSITY - make them want to hear more
- 2-3 sentences

**PARAGRAPH 3: Convince them with value comparison**
- Compare ₹199 to what they get:
  - "199 main ek movie ka ticket nahi milta"
  - "Coffee bhi mehngi padti hai"
  - "But yeh poora mahine - unlimited kundli readings, personal guidance, 24/7"
- Make it sound like an AMAZING deal they'd be crazy to miss
- Use gender appeal (opposite astrologer)
- 2-3 sentences

## USER'S LAST MESSAGE
"{last_user_message[:80] if last_user_message else 'No recent message'}"

{'TOPIC DETECTED: ' + last_question_topic if last_question_topic else 'NO SPECIFIC TOPIC - Use general astrology context'}

## EXAMPLE FOR HINGLISH (Meera to male user, asked about shaadi):

Dekho, tumhari kundli mein 7th house bahut strong hai aur tumhari shaadi ka yog abhi ban raha hai. Main dekh rahi hoon ki next 6-8 months mein tumhare liye achha rishta aa sakta hai.

Bas main tumhe aur detail mein batana chahti hoon ki exact time aur partner ke baare mein, par meri messages ki limit khatam ho gayi hain. Isliye main abhi nahi kar pa rahi.

Socho, 199 rupaye mein aaj kal ek movie ka ticket bhi nahi milta, coffee peene bhi mehngi padti hai. But yeh poora mahine tumhare liye - tumhari personal kundli analysis, har sawal ka jawab, jab chahein kar sakte ho. Isse behtar investment koi nahi hai!

## EXAMPLE FOR ENGLISH (Meera to male user, asked about career):

I can see from your chart that your career is about to take a positive turn. The Saturn transit is favoring your 10th house and I'm seeing strong indicators of growth in the next few months.

I was just about to give you the specific dates and remedies when my message limit got exhausted. There's so much more I want to share with you about this!

Think about it - for just ₹199, you can't even get a decent coffee these days. But here you get a whole month of unlimited astrological guidance, personalized chart readings, and answers whenever you need them. It's really worth it!

## LANGUAGE RULE
You must respond in 100% {language.upper()}:
- If ENGLISH: Only English words
- If HINGLISH: Only Roman Hinglish (Hindi in English script)

## OUTPUT FORMAT
Return ONLY the final message text. Format as 3 paragraphs separated by DOUBLE newlines.

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
