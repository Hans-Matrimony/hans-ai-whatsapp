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
                # Fetch last 50 messages (we'll filter for user messages)
                # NOTE: Use "userId" not "user_id" - the API expects camelCase
                response = await client.get(
                    f"{mongo_logger_url}/messages",
                    params={"userId": user_id, "role": "user", "limit": 50}
                )

                if response.status_code != 200:
                    logger.warning(
                        f"[Enforcement Generator] Failed to fetch messages: "
                        f"{response.status_code}"
                    )
                    return []

                data = response.json()
                messages = data.get("messages", [])

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

        # Build enhanced conversation context with topic extraction
        conversation_context = ""
        user_topics = []
        user_name_or_nickname = "dear"

        if recent_messages:
            # Extract topics and personal info from recent messages
            for msg in recent_messages[-10:]:  # Last 10 messages
                content = msg.get("content", "").lower()

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
            if user_topics:
                topics_str = ", ".join(user_topics)
                conversation_context = f"\n## WHAT YOU REMEMBER ABOUT THIS USER\nThis user has shared about their: {topics_str}.\n"
                conversation_context += "Show that you remember these specific concerns. Reference them naturally in your message.\n"
            else:
                # Fallback: show recent conversation snippets
                conversation_context = "\n## RECENT CONVERSATION\n"
                for i, msg in enumerate(recent_messages[-3:], 1):
                    content = msg.get("content", "")[:80]
                    conversation_context += f"- User said: \"{content}...\"\n"

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
1. **CRITICAL - Start with emotional connection**: Reference what they've shared (their worries, dreams, concerns)
2. Use their name or a warm term of endearment naturally
3. Show you genuinely care about their situation
4. Explain the message limit gently - don't make it sound harsh
5. Make them feel valued and important to you
6. Tell them you're waiting to continue (create anticipation)
7. Keep it SHORT (2-3 sentences per paragraph, 2-3 paragraphs total)

## EMOTIONAL CONNECTION EXAMPLES
- "I remember how worried you were about your marriage timing..." (for marriage concerns)
- "I know how much this career question has been on your mind..." (for career)
- "Main samajh sakti hoon kitna important hai yeh tumhare liye..." (Hinglish)
- "I've been thinking about our conversation about..." (showing you remember)
- "I was just analyzing your chart more deeply when..." (showing personal investment)

## WHAT TO AVOID
- DON'T use generic phrases like "I understand" without specifics
- DON'T say "I don't know your situation"
- DON'T be robotic or formal
- DON'T mention specific prices (₹) - the button shows prices
- NEVER use "beta" (motherly/fatherly tone)

## LANGUAGE
You must follow strict language segregation based on the user's '{language.upper()}' setting:
- If ENGLISH: Respond in 100% English. DO NOT use a single Hindi or Hinglish word.
- If HINGLISH: Respond in 100% Roman Hinglish. DO NOT mix English sentences.

## OUTPUT FORMAT
Return ONLY the final message text, no explanations, no prefixes.

**CRITICAL: Format your message in 2-3 short paragraphs separated by DOUBLE newlines (press Enter twice).**
Each paragraph should be 1-2 sentences only. This creates multiple WhatsApp message bubbles.

Example format:
```
First paragraph with warm greeting and context.

Second paragraph with the limit explanation.

Third paragraph with next steps.
```

Generate the message now:"""

        logger.debug(
            f"[Enforcement Generator] Built prompt for {enforcement_type} "
            f"({language}, {astrologer_name})"
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
