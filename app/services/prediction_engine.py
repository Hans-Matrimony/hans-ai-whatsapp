"""
Prediction Engine
Generates life predictions and astrological remedies based on planetary positions
"""

import logging


logger = logging.getLogger(__name__)


class PredictionEngine:
    """Generate life predictions based on planetary positions"""

    # Planet names in English and Hindi
    PLANET_NAMES = {
        "sun": "Surya (Sun)",
        "moon": "Chandra (Moon)",
        "mars": "Mangal (Mars)",
        "mercury": "Budh (Mercury)",
        "jupiter": "Guru (Jupiter)",
        "venus": "Shukra (Venus)",
        "saturn": "Shani (Saturn)",
        "rahu": "Rahu (North Node)",
        "ketu": "Ketu (South Node)"
    }

    # Sign rulerships (Natural rulerships of signs)
    SIGN_RULERS = {
        "Aries": "Mars",
        "Taurus": "Venus",
        "Gemini": "Mercury",
        "Cancer": "Moon",
        "Leo": "Sun",
        "Virgo": "Mercury",
        "Libra": "Venus",
        "Scorpio": "Mars",
        "Sagittarius": "Jupiter",
        "Capricorn": "Saturn",
        "Aquarius": "Saturn",
        "Pisces": "Jupiter"
    }

    # Signs in order
    SIGNS = [
        'Aries', 'Taurus', 'Gemini', 'Cancer', 'Leo', 'Virgo',
        'Libra', 'Scorpio', 'Sagittarius', 'Capricorn', 'Aquarius', 'Pisces'
    ]

    def _get_house_ruler(self, house_number: int, lagna: str) -> str:
        """
        Calculate the ruler of a house based on Lagna sign

        Uses Whole Sign House system - each house is one complete sign
        """
        try:
            lagna_idx = self.SIGNS.index(lagna)
            house_idx = (lagna_idx + house_number - 1) % 12
            house_sign = self.SIGNS[house_idx]
            ruler = self.SIGN_RULERS.get(house_sign, "Unknown")
            return ruler
        except ValueError:
            # If lagna not found, default to Mars
            return "Mars"

    def _get_functional_benefics(self, lagna: str) -> list:
        """
        Get functional benefic planets based on Lagna

        Functional benefics vary by Lagna. This is a simplified version.
        """
        # Trikone lords (1, 5, 9) are always benefic
        # For simplicity, using basic rules
        benefic_map = {
            "Aries": ["Sun", "Jupiter", "Mars"],  # 5th (Sun), 9th (Jupiter), Lagna lord (Mars)
            "Taurus": ["Saturn", "Mercury", "Venus"],
            "Gemini": ["Venus", "Saturn", "Mercury"],
            "Cancer": ["Mars", "Jupiter", "Moon"],
            "Leo": ["Jupiter", "Mars", "Sun"],
            "Virgo": ["Saturn", "Mercury", "Venus"],
            "Libra": ["Saturn", "Venus", "Mercury"],  # Saturn is Yogakaraka for Libra!
            "Scorpio": ["Moon", "Jupiter", "Mars"],
            "Sagittarius": ["Mars", "Sun", "Jupiter"],
            "Capricorn": ["Venus", "Mercury", "Saturn"],
            "Aquarius": ["Venus", "Saturn", "Mercury"],
            "Pisces": ["Jupiter", "Mars", "Moon"]
        }
        return benefic_map.get(lagna, ["Jupiter", "Venus", "Mercury"])

    def _get_functional_malefics(self, lagna: str) -> list:
        """
        Get functional malefic planets based on Lagna

        Functional malefics are lords of dusthana houses (6, 8, 12)
        """
        malefic_map = {
            "Aries": ["Mercury"],  # 6th and 8th lord
            "Taurus": ["Mars", "Jupiter"],
            "Gemini": ["Jupiter"],
            "Cancer": ["Venus", "Saturn"],
            "Leo": ["Mercury", "Venus"],
            "Virgo": ["Mars", "Jupiter"],
            "Libra": ["Sun", "Jupiter"],  # Sun rules 11th, Jupiter rules 6th
            "Scorpio": ["Mercury", "Venus"],
            "Sagittarius": ["Mercury", "Venus"],
            "Capricorn": ["Moon", "Jupiter"],
            "Aquarius": ["Moon", "Mars"],
            "Pisces": ["Saturn", "Venus"]
        }
        return malefic_map.get(lagna, ["Saturn", "Rahu", "Ketu"])

    def generate_all_predictions(self, kundli_data: dict) -> dict:
        """
        Generate predictions for all life areas

        Args:
            kundli_data: Calculated kundli data with planet_positions

        Returns:
            Dict with predictions for career, marriage, health, wealth
        """
        planet_positions = kundli_data.get("planet_positions", {})
        lagna = kundli_data.get("lagna", "Unknown")
        moon_sign = kundli_data.get("moon_sign", "Unknown")

        logger.info(f"[Predictions] Generating for Lagna: {lagna}, Moon: {moon_sign}")

        return {
            "career": self._predict_career(planet_positions, lagna),
            "marriage": self._predict_marriage(planet_positions, moon_sign),
            "health": self._predict_health(planet_positions),
            "wealth": self._predict_wealth(planet_positions, lagna)
        }

    def _predict_career(self, planets: dict, lagna: str) -> str:
        """Generate career predictions based on 10th house and Saturn"""

        predictions = []

        # Get 10th house ruler dynamically based on Lagna
        tenth_ruler = self._get_house_ruler(10, lagna)
        career_field = self._get_career_field(tenth_ruler)
        predictions.append(f"Your 10th house is ruled by {tenth_ruler}, indicating strong potential in {career_field}.")

        # Check Saturn's position (career karma)
        saturn_data = planets.get("saturn", {})
        saturn_house = saturn_data.get("house")
        saturn_sign = saturn_data.get("sign", "")

        if saturn_house == 10:
            predictions.append("Saturn in the 10th house indicates hard work will bring success. You may face delays but will achieve stability through persistence. Focus on long-term goals rather than quick results.")

        if saturn_house == 6:
            predictions.append("Saturn in the 6th house suggests you excel in service-oriented careers. You are hardworking and dedicated, which will lead to professional growth.")

        if saturn_house == 11:
            predictions.append("Saturn in the 11th house indicates gains through hard work and perseverance. Your professional network will be crucial for success.")

        # Check Sun's position (authority and government)
        sun_data = planets.get("sun", {})
        sun_house = sun_data.get("house")

        if sun_house == 10:
            predictions.append("Sun in the 10th house suggests leadership roles, government service, or authoritative positions suit you well. You have natural leadership abilities.")

        if sun_house == 1:
            predictions.append("Sun in the 1st house gives you a strong personality and self-confidence. You are meant to be in positions of authority.")

        # Check Mercury's position (business and communication)
        mercury_data = planets.get("mercury", {})
        mercury_house = mercury_data.get("house")

        if mercury_house == 10:
            predictions.append("Mercury in the 10th house indicates success in communication-related fields - teaching, writing, business, or media.")

        return " ".join(predictions) if predictions else "Your career looks stable and promising. Focus on your skills and keep working hard towards your goals. Success will come through dedication."

    def _predict_marriage(self, planets: dict, moon_sign: str) -> str:
        """Generate marriage predictions based on 7th house and Venus"""

        predictions = []

        # Get 7th house ruler dynamically based on Lagna
        seventh_ruler = self._get_house_ruler(7, lagna)
        marriage_style = self._get_marriage_style(seventh_ruler)
        predictions.append(f"Your 7th house is ruled by {seventh_ruler}, suggesting {marriage_style}.")

        # Check Venus's position (planet of love and marriage)
        venus_data = planets.get("venus", {})
        venus_house = venus_data.get("house")
        venus_sign = venus_data.get("sign", "")

        if venus_house == 7:
            predictions.append("Venus in the 7th house is highly auspicious for marriage. It indicates a loving and harmonious married life. You are likely to attract a beautiful and caring partner.")

        if venus_house == 5:
            predictions.append("Venus in the 5th house indicates love marriage. You will likely marry someone you love, and your married life will be filled with romance and creativity.")

        if venus_house == 1:
            predictions.append("Venus in the 1st house gives you a charming personality. You are likely to have an attractive spouse who brings good fortune.")

        # Check Jupiter's position (benefic for marriage)
        jupiter_data = planets.get("jupiter", {})
        jupiter_house = jupiter_data.get("house")

        if jupiter_house == 7:
            predictions.append("Jupiter in the 7th house blesses your marriage with wisdom and stability. Your spouse will be supportive, fortunate, and of good character.")

        # Check Moon's position (emotional needs in marriage)
        moon_data = planets.get("moon", {})
        moon_house = moon_data.get("house")

        if moon_house == 7:
            predictions.append("Moon in the 7th house indicates emotional sensitivity in marriage. You need an emotionally supportive partner.")

        return " ".join(predictions) if predictions else "Your marriage will be harmonious and blessed. Trust in divine timing and maintain faith in your future partner."

    def _predict_health(self, planets: dict) -> str:
        """Generate health predictions based on 6th house and Saturn"""

        predictions = []

        # Get 6th house ruler dynamically based on Lagna
        sixth_ruler = self._get_house_ruler(6, lagna)

        if sixth_ruler == "Mars":
            predictions.append("Mars ruling your 6th house indicates you need to be careful about injuries, inflammation, and accidents. Avoid rash actions and drive safely.")

        if sixth_ruler == "Saturn":
            predictions.append("Saturn ruling your 6th house suggests chronic health issues may trouble you. Regular health checkups and a disciplined lifestyle are essential.")

        if sixth_ruler == "Mercury":
            predictions.append("Mercury ruling your 6th house indicates nervous system sensitivity. Practice stress management and maintain good sleep hygiene.")

        # Check Saturn's position (planet of disease and suffering)
        saturn_data = planets.get("saturn", {})
        saturn_house = saturn_data.get("house")

        if saturn_house == 6:
            predictions.append("Saturn in the 6th house may cause chronic health issues. Focus on preventive care and don't ignore minor ailments.")

        if saturn_house == 1:
            predictions.append("Saturn in the 1st house can affect overall vitality. Regular exercise and balanced diet are crucial for you.")

        if saturn_house == 8:
            predictions.append("Saturn in the 8th house indicates longevity but may cause chronic issues in later life. Invest in your health now.")

        # Check Sun's position (vitality)
        sun_data = planets.get("sun", {})
        sun_house = sun_data.get("house")

        if sun_house == 6:
            predictions.append("Sun in the 6th house may cause eye or heart issues. Protect yourself from excessive sun exposure and maintain cardiovascular health.")

        return " ".join(predictions) if predictions else "Your health is generally good. Maintain a balanced lifestyle with proper diet, exercise, and sleep. Prevention is better than cure."

    def _predict_wealth(self, planets: dict, lagna: str) -> str:
        """Generate wealth predictions based on 2nd and 11th houses"""

        predictions = []

        # Get 2nd house ruler (accumulated wealth) - dynamically based on Lagna
        second_ruler = self._get_house_ruler(2, lagna)
        wealth_source = self._get_wealth_source(second_ruler)
        predictions.append(f"Your 2nd house is ruled by {second_ruler}, indicating wealth from {wealth_source}.")

        # Get 11th house ruler (gains and income) - dynamically based on Lagna
        eleventh_ruler = self._get_house_ruler(11, lagna)
        gain_source = self._get_gain_source(eleventh_ruler)
        predictions.append(f"Your 11th house is ruled by {eleventh_ruler}, suggesting gains from {gain_source}.")

        # Check Jupiter's position (planet of wealth)
        jupiter_data = planets.get("jupiter", {})
        jupiter_house = jupiter_data.get("house")

        if jupiter_house == 2:
            predictions.append("Jupiter in the 2nd house is highly auspicious for wealth. You will accumulate money through righteous means and enjoy financial stability throughout life.")

        if jupiter_house == 11:
            predictions.append("Jupiter in the 11th house blesses you with abundant gains and multiple sources of income. Your financial future is secure.")

        if jupiter_house == 5:
            predictions.append("Jupiter in the 5th house indicates gains through investments, speculation, or creative pursuits. You have good financial intuition.")

        # Check Venus's position (luxury and comforts)
        venus_data = planets.get("venus", {})
        venus_house = venus_data.get("house")

        if venus_house == 2:
            predictions.append("Venus in the 2nd house indicates love for luxury and comforts. You will earn well and enjoy material prosperity.")

        if venus_house == 11:
            predictions.append("Venus in the 11th house brings gains through women, arts, entertainment, or luxury goods.")

        # Check Mercury's position (business and intelligence)
        mercury_data = planets.get("mercury", {})
        mercury_house = mercury_data.get("house")

        if mercury_house == 2:
            predictions.append("Mercury in the 2nd house indicates wealth through business, trading, or intellectual pursuits. You are skilled at making money.")

        if mercury_house == 11:
            predictions.append("Mercury in the 11th house suggests multiple sources of income through your communication skills and intelligence.")

        return " ".join(predictions) if predictions else "Financial stability and prosperity are indicated in your chart. Hard work combined with smart investments will bring wealth. Avoid risky ventures and seek expert advice for major decisions."

    def generate_remedies(self, kundli_data: dict) -> dict:
        """
        Generate astrological remedies based on functional nature of planets

        Args:
            kundli_data: Calculated kundli data

        Returns:
            Dict with gemstones, mantras, and general remedies
        """
        planets = kundli_data.get("planet_positions", {})
        lagna = kundli_data.get("lagna", "Unknown")

        # Determine functional nature of planets based on Lagna
        # For each Lagna, certain planets are benefic or malefic
        functional_benefics = self._get_functional_benefics(lagna)
        functional_malefics = self._get_functional_malefics(lagna)

        # Check for malefic planets in dusthana houses (6, 8, 12)
        malefic_planets = []
        for planet_name, planet_data in planets.items():
            house = planet_data.get("house")
            planet_ruler = planet_data.get("planet")

            # Check if planet is functionally malefic or in dusthana
            if house in [6, 8, 12] or planet_ruler in functional_malefics:
                malefic_planets.append(planet_name)

        remedies = {
            "gemstones": "",
            "mantras": "",
            "general": ""
        }

        # Saturn remedies
        if "saturn" in malefic_planets:
            remedies["gemstones"] += "Blue Sapphire (Neelam) can help strengthen Saturn. "
            remedies["mantras"] += "Chant 'Om Sham Shanicharaya Namah' on Saturdays (108 times). "
            remedies["general"] += "• Donate black sesame seeds, iron, or black clothes on Saturdays\n"
            remedies["general"] += "• Feed stray dogs and birds\n"
            remedies["general"] += "• Light mustard oil lamp under Peepal tree on Saturdays\n"

        # Rahu remedies
        if "rahu" in malefic_planets:
            remedies["gemstones"] += "Hessonite (Gomed) can help balance Rahu. "
            remedies["mantras"] += "Chant 'Om Raam Rahave Namah' during Rahu Kaal (90 minutes before sunset). "
            remedies["general"] += "• Donate coconut, mustard oil, or black gram on Wednesdays\n"
            remedies["general"] += "• Avoid wearing grey or blue clothes\n"
            remedies["general"] += "• Feed stray dogs\n"

        # Ketu remedies
        if "ketu" in malefic_planets:
            remedies["gemstones"] += "Cat's Eye (Lehsunia) can help pacify Ketu. "
            remedies["mantras"] += "Chant 'Om Kem Ketave Namah' regularly (108 times). "
            remedies["general"] += "• Donate brown colored items, dog food, or blankets to the needy\n"
            remedies["general"] += "• Keep a dog as a pet\n"
            remedies["general"] += "• Visit religious places regularly\n"

        # Mars remedies
        if "mars" in malefic_planets:
            remedies["gemstones"] += "Red Coral (Moonga) can help strengthen Mars. "
            remedies["mantras"] += "Chant 'Om Ang Angarkaya Namah' on Tuesdays. "
            remedies["general"] += "• Donate red items, wheat, or jaggery on Tuesdays\n"
            remedies["general"] += "• Feed stray cows\n"
            remedies["general"] += "• Avoid getting angry unnecessarily\n"

        # General remedies (always good)
        if not remedies["general"]:
            remedies["general"] += "• Practice meditation regularly\n"
            remedies["general"] += "• Respect your parents and elders\n"
            remedies["general"] += "• Help the needy through donations\n"
            remedies["general"] += "• Chant Gayatri Mantra daily\n"

        return remedies

    def _get_career_field(self, ruler: str) -> str:
        """Get career field based on house ruler"""
        career_fields = {
            "Mars": "military, police, engineering, sports, or technical fields",
            "Mercury": "communication, writing, teaching, business, or IT",
            "Jupiter": "teaching, priesthood, law, consulting, or advisory roles",
            "Venus": "arts, entertainment, beauty, fashion, hospitality, or luxury industries",
            "Saturn": "government service, administration, mining, agriculture, or real estate",
            "Sun": "leadership, politics, government, or authoritative positions",
            "Moon": "hospitality, nursing, healthcare, public relations, or marine-related fields",
            "Rahu": "technology, innovation, research, or foreign lands",
            "Ketu": "spirituality, healing, astrology, or alternative medicine"
        }
        return career_fields.get(ruler, "entrepreneurship or professional roles")

    def _get_marriage_style(self, ruler: str) -> str:
        """Get marriage style based on 7th house ruler"""
        marriage_styles = {
            "Mars": "a passionate and energetic partner who may be strong-willed",
            "Mercury": "an intelligent and communicative partner who enjoys conversation",
            "Jupiter": "a wise, learned, and spiritual partner with good character",
            "Venus": "a loving, romantic, and beautiful partner with strong values",
            "Saturn": "a mature, stable, and responsible partner who is older or more serious",
            "Sun": "a confident, proud, and influential partner with leadership qualities",
            "Moon": "an emotional, caring, and nurturing partner with strong family values",
            "Rahu": "an unconventional or unique partner from a different background",
            "Ketu": "a spiritual or detached partner inclined towards liberation"
        }
        return marriage_styles.get(ruler, "a harmonious and balanced partnership")

    def _get_wealth_source(self, ruler: str) -> str:
        """Get wealth source based on 2nd house ruler"""
        wealth_sources = {
            "Mars": "property, real estate, manufacturing, engineering, or technical work",
            "Mercury": "business, trading, commerce, writing, or intellectual work",
            "Jupiter": "teaching, consulting, religious activities, or advisory services",
            "Venus": "arts, entertainment, fashion, beauty, luxury goods, or creative work",
            "Saturn": "government service, administration, agriculture, mining, or manual work",
            "Sun": "government, authority, father, or leadership positions",
            "Moon": "mother, emotional support, public service, or hospitality",
            "Rahu": "foreign sources, technology, innovation, or unconventional means",
            "Ketu": "spiritual work, healing, astrology, or charitable activities"
        }
        return wealth_sources.get(ruler, "multiple sources through your efforts")

    def _get_gain_source(self, ruler: str) -> str:
        """Get gain source based on 11th house ruler"""
        gain_sources = {
            "Sun": "government, authority, father, or leadership positions",
            "Moon": "mother, emotional support, public life, or water-related work",
            "Mars": "brothers, courage, physical efforts, or sports",
            "Mercury": "friends, intelligence, communication, or business networks",
            "Jupiter": "teachers, elders, blessings, or wisdom-based activities",
            "Venus": "spouse, women, luxury, or entertainment industry",
            "Saturn": "hard work, patience, service, or older people",
            "Rahu": "foreign sources, technology, or unexpected gains",
            "Ketu": "spiritual sources, charity, or detachment"
        }
        return gain_sources.get(ruler, "your network and social connections")
