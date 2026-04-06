"""
Simplified Kundli Calculator for PDF Generation
Uses jyotishganit library for Vedic astrology calculations
"""

import os
import json
from datetime import datetime
from typing import Dict, Any, List

# Try to import jyotishganit
try:
    import jyotishganit
    JYOTISH_AVAILABLE = True
except ImportError:
    JYOTISH_AVAILABLE = False
    print("Warning: jyotishganit not available. Install with: pip install jyotishganit")

# Sign names and mappings
SIGNS = ['Aries', 'Taurus', 'Gemini', 'Cancer', 'Leo', 'Virgo',
         'Libra', 'Scorpio', 'Sagittarius', 'Capricorn', 'Aquarius', 'Pisces']

HINDI_RASHI = {
    "Aries": "Mesh", "Taurus": "Vrishabh", "Gemini": "Mithun", "Cancer": "Kark",
    "Leo": "Singh", "Virgo": "Kanya", "Libra": "Tula", "Scorpio": "Vrishchik",
    "Sagittarius": "Dhanu", "Capricorn": "Makar", "Aquarius": "Kumbh", "Pisces": "Meen"
}

# Hindi characters for planets
HINDI_MAP = {
    'Sun': 'सु', 'Moon': 'च', 'Mars': 'कु', 'Mercury': 'बु',
    'Jupiter': 'गु', 'Venus': 'शु', 'Saturn': 'श',
    'Rahu': 'रा', 'Ketu': 'के', 'Lagna': 'ल'
}

# Nakshatra ranges
NAKSHATRA_RANGES = [
    ("Ashwini", 0, 13.333),
    ("Bharani", 13.333, 26.666),
    ("Krittika", 26.666, 40),
    ("Rohini", 40, 53.333),
    ("Mrigashira", 53.333, 66.666),
    ("Ardra", 66.666, 80),
    ("Punarvasu", 80, 93.333),
    ("Pushya", 93.333, 106.666),
    ("Ashlesha", 106.666, 120),
    ("Magha", 120, 133.333),
    ("Purva Phalguni", 133.333, 146.666),
    ("Uttara Phalguni", 146.666, 160),
    ("Hasta", 160, 173.333),
    ("Chitra", 173.333, 186.666),
    ("Swati", 186.666, 200),
    ("Vishakha", 200, 213.333),
    ("Anuradha", 213.333, 226.666),
    ("Jyeshtha", 226.666, 240),
    ("Mula", 240, 253.333),
    ("Purva Ashadha", 253.333, 266.666),
    ("Uttara Ashadha", 266.666, 280),
    ("Shravana", 280, 293.333),
    ("Dhanishta", 293.333, 306.666),
    ("Shatabhisha", 306.666, 320),
    ("Purva Bhadrapada", 320, 333.333),
    ("Uttara Bhadrapada", 333.333, 346.666),
    ("Revati", 346.666, 360),
]


def get_coordinates(place: str) -> tuple:
    """Get latitude and longitude for a place"""
    # Try local cities file
    cities_file = os.path.join(os.path.dirname(__file__), 'cities_india.json')

    if os.path.exists(cities_file):
        try:
            with open(cities_file, 'r') as f:
                cities = json.load(f)
                place_lower = place.strip().lower()
                for city_name, coords in cities.items():
                    if city_name.lower() == place_lower:
                        return coords[0], coords[1]
        except Exception as e:
            print(f"Error loading cities file: {e}")

    # Fallback coordinates for major Indian cities
    major_cities = {
        "meerut": (28.9844, 77.7064),
        "delhi": (28.6139, 77.2090),
        "mumbai": (19.0760, 72.8777),
        "bangalore": (12.9716, 77.5946),
        "chennai": (13.0827, 80.2707),
        "kolkata": (22.5726, 88.3639),
        "hyderabad": (17.3850, 78.4867),
        "pune": (18.5204, 73.8567),
        "jaipur": (26.9124, 75.7873),
        "lucknow": (26.8467, 80.9462),
    }

    place_key = place.strip().lower()
    if place_key in major_cities:
        return major_cities[place_key]

    # Default to Delhi if not found
    return 28.6139, 77.2090


def get_house_from_sign(planet_sign: str, lagna_sign: str) -> int:
    """Calculate house number using Vedic Whole Sign system"""
    sign_to_index = {
        "Aries": 0, "Taurus": 1, "Gemini": 2, "Cancer": 3, "Leo": 4, "Virgo": 5,
        "Libra": 6, "Scorpio": 7, "Sagittarius": 8, "Capricorn": 9, "Aquarius": 10, "Pisces": 11
    }

    p_idx = sign_to_index.get(planet_sign, 0)
    l_idx = sign_to_index.get(lagna_sign, 0)

    house = ((p_idx - l_idx) % 12) + 1
    return house


def get_nakshatra_from_degree(degree: float) -> tuple:
    """Calculate nakshatra from zodiac degree (0-360)"""
    for nakshatra, start, end in NAKSHATRA_RANGES:
        if start <= degree < end:
            return nakshatra, start
    return "Unknown", 0


def parse_date(dob_str: str) -> datetime:
    """Parse date string in various formats"""
    dob_str = dob_str.strip()

    formats = [
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%d %B %Y",
        "%d %b %Y",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(dob_str, fmt)
        except ValueError:
            continue

    raise ValueError(f"Unable to parse date '{dob_str}'")


def parse_time(tob_str: str) -> datetime.time:
    """Parse time string in various formats"""
    tob_str = tob_str.strip()

    # Try 12-hour format
    for fmt in ["%I:%M %p", "%I:%M%p", "%I %p", "%I%p"]:
        try:
            return datetime.strptime(tob_str, fmt).time()
        except ValueError:
            continue

    # Try 24-hour format
    for fmt in ["%H:%M", "%H:%M:%S", "%H"]:
        try:
            return datetime.strptime(tob_str, fmt).time()
        except ValueError:
            continue

    # Default to midnight if parsing fails
    return datetime.time(0, 0)


def calculate_kundli(dob: str, tob: str, place: str) -> Dict[str, Any]:
    """
    Calculate Kundli using jyotishganit

    Returns simplified kundli data for PDF generation
    """
    if not JYOTISH_AVAILABLE:
        # Return fallback data if jyotishganit not available
        return {
            "error": "jyotishganit not available",
            "fallback_data": _get_fallback_kundli_data()
        }

    try:
        # Parse date and time
        birth_date = parse_date(dob)
        birth_time = parse_time(tob)
        birth_dt = datetime.combine(birth_date, birth_time)

        # Get coordinates
        lat, lon = get_coordinates(place)

        # Calculate chart using jyotishganit
        chart = jyotishganit.calculate_birth_chart(
            birth_date=birth_dt,
            latitude=lat,
            longitude=lon,
            timezone_offset=5.5,  # IST
            name="User"
        )

        chart_data = chart.to_dict()

        # Extract Lagna
        if hasattr(chart, 'ascendant') and chart.ascendant:
            lagna = chart.ascendant.sign if hasattr(chart.ascendant, 'sign') else chart.ascendant.to_dict().get('sign')
        else:
            lagna_house = next((h for h in chart.d1_chart.houses if h.to_dict().get('number') == 1), None)
            lagna = lagna_house.to_dict().get('sign') if lagna_house else "Unknown"

        # Extract Moon data
        moon_planet = next(
            (p for p in chart.d1_chart.planets if p.celestial_body.lower() == 'moon'),
            None
        )

        if moon_planet:
            moon_data = moon_planet.to_dict()
            moon_sign = moon_data.get('sign', 'Unknown')
            moon_degree = moon_data.get('signDegrees', moon_data.get('degree', 0))
            moon_nakshatra = moon_data.get('nakshatra', 'Unknown')
        else:
            moon_sign = "Unknown"
            moon_degree = 0
            moon_nakshatra = "Unknown"

        # Extract planet positions
        planet_positions = {}
        d1 = chart_data.get('d1Chart', {})

        for p in d1.get('planets', []):
            p_name = p.get('celestialBody')
            p_sign = p.get('sign')

            # Calculate house using Whole Sign system
            h_num = get_house_from_sign(p_sign, lagna)

            planet_positions[p_name.lower()] = {
                "planet": p_name,
                "sign": p_sign,
                "house": h_num,
                "degree": p.get('signDegrees', p.get('degree', 0))
            }

        # Get dasha info
        dashas = chart_data.get('dashas', {})
        current_dasha = dashas.get('current', {})
        mahadashas = current_dasha.get('mahadashas', {})

        if mahadashas:
            md_planet = list(mahadashas.keys())[0]
            md_data = mahadashas[md_planet]
            antardashas = md_data.get('antardashas', {})
            ad_planet = list(antardashas.keys())[0] if antardashas else md_planet

            dasha_info = {
                "mahadasha": md_planet,
                "antardasha": ad_planet
            }
        else:
            dasha_info = {"mahadasha": "Unknown", "antardasha": "Unknown"}

        return {
            "lagna": lagna,
            "moon_sign": moon_sign,
            "nakshatra": moon_nakshatra,
            "planet_positions": planet_positions,
            "dasha": dasha_info,
            "summary": {
                "lagna": lagna,
                "moon_sign": moon_sign,
                "nakshatra": moon_nakshatra,
                "current_dasha": f"Current Mahadasha: {dasha_info['mahadasha']}, Antardasha: {dasha_info['antardasha']}"
            },
            "ai_summary": {
                "planet_positions": [
                    f"{p_data['planet']} is in House {p_data['house']} ({p_data['sign']})"
                    for p_data in planet_positions.values()
                ]
            }
        }

    except Exception as e:
        print(f"Error calculating kundli: {e}")
        return {
            "error": str(e),
            "fallback_data": _get_fallback_kundli_data()
        }


def _get_fallback_kundli_data() -> Dict[str, Any]:
    """Provide fallback kundli data when calculation fails"""
    return {
        "lagna": "Taurus",
        "moon_sign": "Pisces",
        "nakshatra": "Uttara Bhadrapada",
        "planet_positions": {
            "sun": {"planet": "Sun", "sign": "Aquarius", "house": 11, "degree": 28.0},
            "moon": {"planet": "Moon", "sign": "Pisces", "house": 12, "degree": 5.0},
            "mars": {"planet": "Mars", "sign": "Sagittarius", "house": 9, "degree": 15.0},
            "mercury": {"planet": "Mercury", "sign": "Aquarius", "house": 11, "degree": 22.0},
            "jupiter": {"planet": "Jupiter", "sign": "Gemini", "house": 3, "degree": 10.0},
            "venus": {"planet": "Venus", "sign": "Pisces", "house": 12, "degree": 18.0},
            "saturn": {"planet": "Saturn", "sign": "Gemini", "house": 3, "degree": 5.0},
            "rahu": {"planet": "Rahu", "sign": "Taurus", "house": 2, "degree": 12.0},
            "ketu": {"planet": "Ketu", "sign": "Scorpio", "house": 8, "degree": 12.0}
        },
        "dasha": {"mahadasha": "Saturn", "antardasha": "Saturn"},
        "summary": {
            "lagna": "Taurus",
            "moon_sign": "Pisces",
            "nakshatra": "Uttara Bhadrapada"
        },
        "ai_summary": {
            "planet_positions": [
                "Sun is in House 11 (Aquarius)",
                "Moon is in House 12 (Pisces)",
                "Mars is in House 9 (Sagittarius)",
                "Mercury is in House 11 (Aquarius)",
                "Jupiter is in House 3 (Gemini)",
                "Venus is in House 12 (Pisces)",
                "Saturn is in House 3 (Gemini)",
                "Rahu is in House 2 (Taurus)",
                "Ketu is in House 8 (Scorpio)"
            ]
        }
    }
