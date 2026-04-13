"""
Horoscope Service
Integrates with the horoscope skill for 100% accurate Vedic astrology predictions
"""
import os
import subprocess
import json
import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)


class HoroscopeService:
    """Service for generating personalized daily horoscopes using Swiss Ephemeris"""

    def __init__(self, skill_path: str = None):
        # Default path to horoscope skill
        if skill_path:
            self.skill_path = skill_path
        else:
            # Try to find the horoscope skill
            # The script is in: D:/HansMatrimonyOrg/openclawforaiastro/skills/horoscope/calculate.py
            # We're in: D:/HansMatrimonyOrg/hans-ai-whatsapp/app/services/
            # So we need to go: ../../openclawforaiastro/skills/horoscope
            possible_paths = [
                "../../../openclawforaiastro/skills/horoscope",  # Correct: from services/ go up 3 levels
                "../../openclawforaiastro/skills/horoscope",
                "/d/HansMatrimonyOrg/openclawforaiastro/skills/horoscope",
            ]
            # Find first path that exists
            for path in possible_paths:
                if os.path.exists(path):
                    self.skill_path = path
                    break
            else:
                self.skill_path = possible_paths[0]  # Fallback

        self.calculate_script = os.path.join(self.skill_path, "calculate.py")

    def is_horoscope_request(self, message: str) -> bool:
        """
        Detect if user is asking for horoscope.
        Returns True if horoscope-related keywords are found.
        More specific keywords to avoid false positives with Kundli or general queries.
        """
        message_lower = message.lower()

        # Strong horoscope indicators (high confidence)
        strong_keywords = [
            "horoscope", "daily horoscope", "today's horoscope",
            "mera horoscope", "horoscope batao", "horoscope batana"
        ]

        # Medium confidence horoscope keywords (need additional context)
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
        Get user birth data from MongoDB (same approach as Kundli system).
        Returns dict with dob, tob, place if found, None otherwise.

        Uses: user_metadata.get_user_metadata() - same as Kundli
        """
        try:
            from app.services import user_metadata

            logger.info(f"[Horoscope] Fetching birth data from MongoDB for {phone}")

            # Use the same function as Kundli system (user_metadata.get_user_metadata)
            user_data = await user_metadata.get_user_metadata(phone)

            if user_data:
                # Extract birth details from user metadata
                dob = user_data.get("dob")
                tob = user_data.get("tob")
                place = user_data.get("place")

                if dob and tob and place:
                    logger.info(f"[Horoscope] ✅ Found birth data in MongoDB for {phone}")
                    return {
                        "dob": dob,
                        "tob": tob,
                        "place": place
                    }
                else:
                    logger.info(f"[Horoscope] ⚠️  User found but incomplete birth data: dob={dob}, tob={tob}, place={place}")
                    return None
            else:
                logger.info(f"[Horoscope] ❌ No user found in MongoDB for {phone}")
                return None

        except Exception as e:
            logger.error(f"[Horoscope] Error fetching birth data from MongoDB: {e}")
            return None

    def _parse_birth_details_from_memory(self, memory_text: str) -> Optional[Dict]:
        """
        Parse birth details from Mem0 memory text.
        Handles various formats of stored birth data.
        """
        import re

        try:
            # Pattern to match various formats
            # Format 1: "User birth details: DOB=1990-05-15, TOB=10:30 AM, Place=Mumbai"
            # Format 2: "DOB: 1990-05-15, Time: 10:30 AM, Place: Mumbai"
            # Format 3: "Date of Birth: 15 May 1990, Time: 10:30, Place: Mumbai"

            dob_pattern = r'(?:DOB|Date of Birth|Birth Date|dob)[:\s=]+([0-9]{1,4}[-/][0-9]{1,2}[-/][0-9]{1,4})'
            time_pattern = r'(?:TOB|Time|Birth Time|tob|time)[:\s=]+([0-9]{1,2}:[0-9]{2}(?:\s*[AP]M)?)'
            place_pattern = r'(?:Place|Birth Place|City|place|sthaan)[:\s=]+([A-Za-z\s]+?)(?:,|\.|\n|$)'

            dob_match = re.search(dob_pattern, memory_text, re.IGNORECASE)
            time_match = re.search(time_pattern, memory_text, re.IGNORECASE)
            place_match = re.search(place_pattern, memory_text, re.IGNORECASE)

            if dob_match and time_match and place_match:
                return {
                    "dob": dob_match.group(1).strip(),
                    "tob": time_match.group(1).strip(),
                    "place": place_match.group(1).strip()
                }
            else:
                logger.debug(f"[Horoscope] Could not parse all birth details from memory")
                return None

        except Exception as e:
            logger.error(f"[Horoscope] Error parsing birth details from memory: {e}")
            return None

    async def generate_horoscope(
        self,
        dob: str,
        tob: str,
        place: str,
        language: str = "auto",
        user_message: str = ""
    ) -> Optional[Dict]:
        """Generate personalized horoscope using the horoscope skill"""

        cmd = [
            "python3",
            self.calculate_script,
            "--dob", dob,
            "--tob", tob,
            "--place", place,
            "--language", language
        ]

        if language == "auto" and user_message:
            cmd.extend(["--user-input", user_message])

        try:
            logger.info(f"[Horoscope] Generating horoscope for DOB={dob}, Place={place}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=os.path.dirname(self.calculate_script)
            )

            if result.returncode == 0:
                horoscope_data = json.loads(result.stdout)
                logger.info(f"[Horoscope] Successfully generated horoscope")
                return horoscope_data
            else:
                logger.error(f"[Horoscope] Script error: {result.stderr}")
                return None

        except subprocess.TimeoutExpired:
            logger.error(f"[Horoscope] Generation timed out")
            return None
        except Exception as e:
            logger.error(f"[Horoscope] Generation failed: {e}")
            return None

    def detect_language(self, message: str) -> str:
        """Detect if user prefers English or Hinglish"""
        message_lower = message.lower()

        # Common Hindi/Hinglish words
        hindi_words = [
            'hai', 'hain', 'ho', 'kaise', 'kya', 'karo', 'karein', 'bhai', 'dost',
            'acha', 'accha', 'theek', 'aaj', 'hoga', 'hogi', 'rahega', 'rahenga',
            'shaadi', 'kare', 'karte', 'karne', 'ka', 'ki', 'ke', 'mein', 'main',
            'tum', 'aap', 'hum', 'mera', 'teri', 'uski', 'hamari', 'kisi', 'kuch',
            'batao', 'batana', 'suno', 'sunna', 'dekhna', 'dekho', 'jana', 'jao',
            'ana', 'aao', 'rakhna', 'rakho', 'lena', 'lelo', 'dena', 'do',
            'paisa', 'rupaye', 'kaam', 'ghar', 'bata', 'kya', 'kaisa'
        ]

        hindi_count = sum(1 for word in hindi_words if word in message_lower)

        # If more than 2 Hindi words detected, it's Hinglish
        if hindi_count >= 2:
            return 'hinglish'
        return 'english'

    def format_horoscope_message(self, horoscope: Dict) -> str:
        """Format horoscope data into beautiful WhatsApp message"""

        greeting = "Namaste! 🔮"

        message = f"""{greeting}

📅 *Your Daily Horoscope - {horoscope['date']}*

🌙 *Moon Sign:* {horoscope['birth_moon_sign']} ({horoscope['birth_moon_sign_hindi']})
🌟 *Nakshatra:* {horoscope['birth_nakshatra']}
🔮 *Today's Moon Transit:* House {horoscope['transit_moon_house']}

✨ *Prediction:*
{horoscope['prediction']}

🎨 *Lucky Color:* {horoscope['lucky_color']}
🔢 *Lucky Numbers:* {', '.join(map(str, horoscope['lucky_numbers']))}
📆 *Lucky Day:* {horoscope['lucky_day']}

---
🔥 *100% Accurate* - Calculated using Swiss Ephemeris"""

        return message

    def get_birth_details_request_message(self, language: str = "english") -> str:
        """Get message asking user for birth details"""

        if language == "hinglish":
            return """Aapka accurate horoscope dene ke liye mujhe aapki birth details chahiye:

1. *Date of Birth* (YYYY-MM-DD)
   Example: 1990-05-15

2. *Time of Birth* (HH:MM AM/PM)
   Example: 10:30 AM

3. *Place of Birth* (City)
   Example: Mumbai

Please is details share karein, main aapka personalized horoscope generate kar dunga! 🔮"""
        else:
            return """To provide your accurate horoscope, I need your birth details:

1. *Date of Birth* (YYYY-MM-DD)
   Example: 1990-05-15

2. *Time of Birth* (HH:MM AM/PM)
   Example: 10:30 AM

3. *Place of Birth* (City)
   Example: Mumbai

Please share these details and I'll generate your personalized horoscope! 🔮"""
