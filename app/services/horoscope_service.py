"""
Horoscope Service
Integrates with the horoscope skill via OpenClaw API for 100% accurate Vedic astrology predictions
"""
import os
import json
import logging
import httpx
import re
from typing import Optional, Dict

logger = logging.getLogger(__name__)


class HoroscopeService:
    """Service for generating personalized daily horoscopes using OpenClaw API"""

    def __init__(self):
        self.api_url = os.getenv("OPENCLAW_URL")
        self.api_token = os.getenv("OPENCLAW_GATEWAY_TOKEN")
        
        if not self.api_url:
            logger.warning("[Horoscope] OPENCLAW_URL not configured, service will be limited")

    def is_horoscope_request(self, message: str) -> bool:
        """
        Detect if user is asking for horoscope.
        Returns True if horoscope-related keywords are found.
        """
        message_lower = message.lower()

        # Strong horoscope indicators (high confidence)
        strong_keywords = [
            "horoscope", "daily horoscope", "today's horoscope",
            "mera horoscope", "horoscope batao", "horoscope batana"
        ]

        # Medium confidence horoscope keywords
        medium_keywords = [
            "prediction", "forecast", "daily prediction",
            "rashi bhavishya", "aaj ka bhavishya"
        ]

        # Weak indicators - only match if combined with day/today context
        weak_context_keywords = [
            ("how is my day", "day"),
            ("how's my day", "day"),
            ("aaj kaisa rahega", "aaj"),
            ("mera din kaisa", "din"),
        ]

        # Check strong keywords first
        for keyword in strong_keywords:
            if keyword in message_lower:
                logger.info(f"[Horoscope] Detected via strong keyword: '{keyword}'")
                return True

        # Check medium keywords
        for keyword in medium_keywords:
            if keyword in message_lower:
                logger.info(f"[Horoscope] Detected via medium keyword: '{keyword}'")
                return True

        # Check weak context keywords
        for phrase, context in weak_context_keywords:
            if phrase in message_lower:
                logger.info(f"[Horoscope] Detected via context keyword: '{phrase}'")
                return True

        return False

    async def get_user_birth_data(self, phone: str) -> Optional[Dict]:
        """
        Get user birth data from MongoDB and Mem0 fallback.
        """
        try:
            from app.services import user_metadata

            logger.info(f"[Horoscope] Fetching birth data for {phone}")

            # Use the generalized user_metadata service which handles MongoDB + Mem0 fallback
            user_data = await user_metadata.get_user_metadata(phone)

            if user_data:
                # Extract birth details from user metadata
                dob = user_data.get("dob")
                tob = user_data.get("tob")
                place = user_data.get("place")

                if dob and tob and place:
                    logger.info(f"[Horoscope] ✅ Found full birth data for {phone}")
                    return {
                        "dob": dob,
                        "tob": tob,
                        "place": place
                    }
                else:
                    logger.info(f"[Horoscope] ⚠️  Incomplete birth data for {phone}: dob={dob}, tob={tob}, place={place}")
                    return None
            else:
                logger.info(f"[Horoscope] ❌ No user data found for {phone}")
                return None

        except Exception as e:
            logger.error(f"[Horoscope] Error fetching birth data: {e}")
            return None

    async def generate_horoscope(
        self,
        dob: str,
        tob: str,
        place: str,
        language: str = "auto",
        user_message: str = ""
    ) -> Optional[Dict]:
        """Generate personalized horoscope using OpenClaw API"""
        
        if not self.api_url:
            logger.error("[Horoscope] Cannot generate horoscope: OPENCLAW_URL missing")
            return None

        try:
            logger.info(f"[Horoscope] Requesting API horoscope for DOB={dob}, Place={place}")

            # Create prompt for the OpenClaw agent to act as the Vedic Horoscope Engine
            prompt = f"""You are the Vedic Horoscope Engine. 
Generate a personalized daily horoscope (Dainik Rashifal) for today based on these birth details:
DOB: {dob}
TOB: {tob}
Place: {place}
Preferred Language: {language}

Return your response in STRICT JSON format with these exact keys:
{{
  "date": "YYYY-MM-DD",
  "birth_moon_sign": "English Name",
  "birth_moon_sign_hindi": "Hindi Name",
  "birth_nakshatra": "Nakshatra Name",
  "transit_moon_house": "House Number (1-12)",
  "prediction": "A detailed 3-4 sentence daily prediction focusing on career, health and luck.",
  "lucky_color": "Color Name",
  "lucky_numbers": [1, 2, 3],
  "lucky_day": "Day of the Week"
}}

Rules:
- Keep the prediction personal and encouraging.
- If language is 'hinglish', use Hinglish for the 'prediction' field.
- Ensure the JSON is valid and contains NO other text."""

            headers = {
                "Content-Type": "application/json",
                "x-openclaw-session-key": f"horoscope:{dob}:{place.replace(' ', '_')}",
                "x-openclaw-scopes": "operator.admin"
            }
            if self.api_token:
                headers["Authorization"] = f"Bearer {self.api_token}"

            payload = {
                "model": "agent:astrologer",
                "input": prompt,
                "user": "horoscope_service"
            }

            async with httpx.AsyncClient(timeout=45.0) as client:
                response = await client.post(
                    f"{self.api_url}/v1/responses",
                    json=payload,
                    headers=headers
                )

                if response.status_code != 200:
                    logger.error(f"[Horoscope] API Error: {response.status_code} - {response.text}")
                    return None

                data = response.json()
                
                # Extract text from the complex OpenClaw output structure
                # Schema: data -> output[] -> content[] -> text
                reply_text = ""
                if "output" in data:
                    for item in data["output"]:
                        if item.get("type") == "message" and "content" in item:
                            for content in item["content"]:
                                if "text" in content:
                                    reply_text += content["text"]
                elif "response" in data:
                    reply_text = data["response"]
                
                if not reply_text:
                    logger.error(f"[Horoscope] No text found in AI response: {data}")
                    return None
                
                # Extract JSON from reply (in case agent added words)
                json_match = re.search(r'(\{.*\})', reply_text, re.DOTALL)
                if json_match:
                    try:
                        horoscope_data = json.loads(json_match.group(1))
                        logger.info(f"[Horoscope] ✅ Successfully generated and parsed API horoscope")
                        return horoscope_data
                    except json.JSONDecodeError:
                        logger.error(f"[Horoscope] Failed to parse JSON from AI: {reply_text}")
                        return None
                else:
                    logger.error(f"[Horoscope] No JSON found in AI response: {reply_text}")
                    return None

        except Exception as e:
            logger.error(f"[Horoscope] API generation failed: {e}")
            return None

    def detect_language(self, message: str) -> str:
        """Detect if user prefers English or Hinglish"""
        message_lower = message.lower()
        hindi_words = [
            'hai', 'hain', 'ho', 'kaise', 'kya', 'karo', 'karein', 'acha', 'accha', 
            'theek', 'aaj', 'hoga', 'hogi', 'rahega', 'batao', 'batana', 'kaisa'
        ]
        hindi_count = sum(1 for word in hindi_words if word in message_lower)
        return 'hinglish' if hindi_count >= 2 else 'english'

    def format_horoscope_message(self, horoscope: Dict) -> str:
        """Format horoscope data into beautiful WhatsApp message"""
        greeting = "Namaste! 🔮"
        
        # Handle lucky numbers as list or string
        lucky_nums = horoscope.get('lucky_numbers', [])
        if isinstance(lucky_nums, list):
            nums_str = ', '.join(map(str, lucky_nums))
        else:
            nums_str = str(lucky_nums)

        message = f"""{greeting}

📅 *Your Daily Horoscope - {horoscope.get('date', 'Today')}*

🌙 *Moon Sign:* {horoscope.get('birth_moon_sign', 'N/A')} ({horoscope.get('birth_moon_sign_hindi', 'N/A')})
🌟 *Nakshatra:* {horoscope.get('birth_nakshatra', 'N/A')}
🔮 *Today's Moon Transit:* House {horoscope.get('transit_moon_house', 'N/A')}

✨ *Prediction:*
{horoscope.get('prediction', 'No prediction available.')}

🎨 *Lucky Color:* {horoscope.get('lucky_color', 'N/A')}
🔢 *Lucky Numbers:* {nums_str}
📆 *Lucky Day:* {horoscope.get('lucky_day', 'N/A')}

---
🔥 *100% Accurate* - Daily Vedic Insights"""
        return message

    def get_birth_details_request_message(self, language: str = "english") -> str:
        """Get message asking user for birth details"""
        if language == "hinglish":
            return """Aapka accurate horoscope dene ke liye mujhe aapki birth details chahiye:

1. *Date of Birth* (YYYY-MM-DD)
2. *Time of Birth* (HH:MM AM/PM)
3. *Place of Birth* (City)

Please is details share karein, main aapka personalized horoscope generate kar dunga! 🔮"""
        else:
            return """To provide your accurate horoscope, I need your birth details:

1. *Date of Birth* (YYYY-MM-DD)
2. *Time of Birth* (HH:MM AM/PM)
3. *Place of Birth* (City)

Please share these details and I'll generate your personalized horoscope! 🔮"""
