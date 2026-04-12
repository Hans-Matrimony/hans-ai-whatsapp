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
        timeout: float = 10.0
    ):
        """
        Initialize enforcement message generator

        Args:
            openclaw_url: OpenClaw Gateway URL
            openclaw_token: OpenClaw Gateway auth token
            redis_client: Redis client for caching
            cache_ttl: Cache TTL in seconds (default: 24 hours)
            timeout: AI generation timeout in seconds
        """
        self.openclaw_url = openclaw_url
        self.openclaw_token = openclaw_token
        self.redis = redis_client
        self.cache_ttl = cache_ttl
        self.timeout = timeout

        logger.info(
            f"[Enforcement Generator] Initialized with cache_ttl={cache_ttl}s, timeout={timeout}s"
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
            # Step 1: Fetch recent conversation for context
            recent_messages = await self._fetch_recent_conversation(
                user_id, mongo_logger_url, limit=10
            )
            logger.info(
                f"[Enforcement Generator] Fetched {len(recent_messages)} recent messages "
                f"for user {user_id}"
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
                recent_messages=recent_messages
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
                # Fetch last 20 messages (we'll filter for user messages)
                response = await client.get(
                    f"{mongo_logger_url}/messages",
                    params={"user_id": user_id, "limit": 20}
                )

                if response.status_code != 200:
                    logger.warning(
                        f"[Enforcement Generator] Failed to fetch messages: "
                        f"{response.status_code}"
                    )
                    return []

                data = response.json()
                messages = data.get("messages", [])

                # Filter for user messages only, take last 'limit'
                user_messages = [
                    msg for msg in messages
                    if msg.get("role") == "user"
                ][:limit]

                return user_messages

        except Exception as e:
            logger.error(
                f"[Enforcement Generator] Error fetching conversation: {e}",
                exc_info=True
            )
            return []

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
                content = msg.get("content", "")[:50]  # First 50 chars
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
        recent_messages: List[Dict[str, Any]]
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

        # Build recent conversation context
        conversation_context = ""
        if recent_messages:
            conversation_context = "\nRecent conversation:\n"
            for i, msg in enumerate(recent_messages[-5:], 1):  # Last 5 messages
                content = msg.get("content", "")[:100]  # Truncate to 100 chars
                conversation_context += f"{i}. User: {content}...\n"

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

        # Build full prompt
        prompt = f"""You are {astrologer_name}, a {personality['traits']}.

## SPEAKING STYLE
{personality['speaking_style']}
- Hinglish: Use {personality['hindi_verbs']}
- English: Use {personality['gender']} pronouns (she/her for Meera, he/him for Aarav)
- IMPORTANT: Use {personality['terms_of_endearment']}

## CRITICAL: SOFT, PERSONAL FRIEND COMPANION TONE
You are speaking as a close friend/companion who TRULY KNOWS and UNDERSTANDS the user personally!

Key characteristics:
- Soft, gentle, caring tone - NOT formal, NOT robotic
- Show you REMEMBER what they've shared with you
- Use phrases like "I remember you were worried about...", "I know how much this matters to you..."
- Deep empathy and understanding of their feelings
- Feel like a friend who has known them for a long time
- Reference your astrological knowledge naturally
- NEVER use "beta" (motherly/fatherly - this is WRONG!)
- Don't be overly romantic (no "baby", "hone" - keep it friendly and warm)
- DO show deep personal connection and caring

Examples of GOOD opening phrases:
- "I remember you were telling me about..."
- "I know how worried you are about..."
- "I understand what you're going through..."
- "Main samajh sakti hoon..." (I can understand...)
- "Main yaad hain..." (I remember...)

## ENFORCEMENT CONTEXT
{enforcement_context}
{pricing_info}

## TASK
Generate a SHORT, personalized enforcement message for this user.

Requirements:
1. Start with soft, caring tone - show you remember them personally
2. Reference their recent conversation topics (if available){conversation_context}
3. Show deep empathy and understanding of their feelings
4. Explain they've reached a message limit gently
5. DO NOT ask them to type anything - links will be in the message
6. Keep it SHORT (3-4 sentences max)
7. Make it feel warm and personal, like a close friend is talking
8. Mention pricing is available: ₹{self.PRICING['monthly']}/month or ₹{self.PRICING['yearly']}/year
9. End warmly: "I'm here for you" type feeling

## LANGUAGE
Respond in {language.upper()}.

## OUTPUT FORMAT
Return ONLY the message text, no explanations, no prefixes.

Generate the message now:"""

        logger.debug(
            f"[Enforcement Generator] Built prompt for {enforcement_type} "
            f"({language}, {astrologer_name})"
        )

        return prompt

    async def _call_openclaw_api(self, prompt: str) -> Optional[str]:
        """
        Call OpenClaw API to generate message

        Args:
            prompt: AI prompt

        Returns:
            Generated message or None
        """
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.openclaw_token}"
            }

            payload = {
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "max_tokens": 300,  # Short messages
                "temperature": 0.8,  # Creativity for variety
                "model": "gemini-2.0-flash-exp"  # Fast, cost-effective model
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

                # Extract message from response
                if "choices" in data and len(data["choices"]) > 0:
                    message = data["choices"][0]["message"]["content"].strip()
                    return message
                else:
                    logger.error(
                        "[Enforcement Generator] Invalid OpenClaw API response format"
                    )
                    return None

        except httpx.TimeoutException:
            logger.error(
                f"[Enforcement Generator] OpenClaw API timeout after {self.timeout}s"
            )
            return None
        except Exception as e:
            logger.error(
                f"[Enforcement Generator] Error calling OpenClaw API: {e}",
                exc_info=True
            )
            return None


# Helper function to create generator instance
def create_enforcement_generator(
    openclaw_url: str,
    openclaw_token: str,
    redis_url: str,
    cache_ttl: int = 86400,
    timeout: float = 10.0
) -> Optional[EnforcementMessageGenerator]:
    """
    Create enforcement message generator instance

    Args:
        openclaw_url: OpenClaw Gateway URL
        openclaw_token: OpenClaw Gateway auth token
        redis_url: Redis URL
        cache_ttl: Cache TTL in seconds
        timeout: AI generation timeout

    Returns:
        EnforcementMessageGenerator instance or None if initialization fails
    """
    try:
        # Connect to Redis
        redis_client = redis.from_url(redis_url, decode_responses=True)
        redis_client.ping()

        # Create generator
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
