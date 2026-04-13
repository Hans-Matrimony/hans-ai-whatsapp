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
                "../../openclawforaiastro/skills/horoscope",
                "../openclawforaiastro/skills/horoscope",
                "/d/HansMatrimonyOrg/openclawforaiastro/skills/horoscope",
            ]
            self.skill_path = possible_paths[0]  # Use first path as default

        self.calculate_script = os.path.join(self.skill_path, "calculate.py")

    def is_horoscope_request(self, message: str) -> bool:
        """
        Detect if user is asking for horoscope.
        Returns True if horoscope-related keywords are found.
        """
        message_lower = message.lower()

        # English horoscope keywords
        english_keywords = [
            "horoscope", "prediction", "forecast", "today's prediction",
            "daily prediction", "stars", "zodiac", "astrology prediction",
            "tell me about", "how is my day", "my horoscope today"
        ]

        # Hindi/Hinglish horoscope keywords
        hindi_keywords = [
            "horoscope", "rashi", "bhavishya", "kundli", "nakshatra",
            "aaj ka din", "mera horoscope", "horoscope batao",
            "aaj kaisa rahega", "bhavishya batana"
        ]

        # Check if any keyword matches
        for keyword in english_keywords + hindi_keywords:
            if keyword in message_lower:
                logger.info(f"[Horoscope] Detected horoscope request via keyword: '{keyword}'")
                return True

        return False

    async def get_user_birth_data(self, phone: str) -> Optional[Dict]:
        """
        Get user birth data from MongoDB.
        Returns dict with dob, tob, place if found, None otherwise.
        """
        try:
            from pymongo import MongoClient
            from app.services.user_metadata import init_user_metadata_service

            # Get MongoDB URL from environment
            mongo_url = os.getenv("MONGO_LOGGER_URL")

            if not mongo_url or not mongo_url.startswith(("mongodb://", "mongodb+srv://")):
                logger.warning(f"[Horoscope] Invalid MongoDB URL")
                return None

            # Connect to MongoDB
            client = MongoClient(mongo_url)
            db = client.astrology
            users_collection = db.user_birth_details

            # Find user by phone number
            user_data = users_collection.find_one({"phone": phone})

            if user_data:
                logger.info(f"[Horoscope] Found birth data for {phone}")
                return {
                    "dob": user_data.get("dob"),
                    "tob": user_data.get("tob"),
                    "place": user_data.get("place")
                }
            else:
                logger.info(f"[Horoscope] No birth data found for {phone}")
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
