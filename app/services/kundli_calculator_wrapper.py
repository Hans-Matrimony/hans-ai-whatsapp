"""
Kundli Calculator Wrapper
Wrapper around existing kundli calculation and chart generation
"""

import os
import sys
import logging
from typing import Dict, Any, Optional


logger = logging.getLogger(__name__)


class KundliCalculatorWrapper:
    """Wrapper for kundli calculation and chart generation"""

    def __init__(self):
        # Add skills directory to path
        self.skills_path = os.path.join(
            os.path.dirname(__file__),
            '../../openclawforaiastro/skills'
        )
        if self.skills_path not in sys.path:
            sys.path.insert(0, self.skills_path)

        # Try to import kundli calculation module
        try:
            from kundli.calculate import calculate_kundli
            self.calculate_kundli = calculate_kundli
            logger.info("Kundli calculation module imported successfully")
        except ImportError as e:
            logger.error(f"Failed to import kundli calculation: {e}")
            self.calculate_kundli = None

        # Try to import chart generation module
        try:
            from kundli.draw_kundli_traditional import draw_kundli_chart
            self.draw_kundli_chart = draw_kundli_chart
            logger.info("Kundli chart generation module imported successfully")
        except ImportError as e:
            logger.error(f"Failed to import chart generation: {e}")
            self.draw_kundli_chart = None

    def calculate_complete_kundli(
        self,
        dob: str,
        tob: str,
        place: str
    ) -> Dict[str, Any]:
        """
        Calculate complete kundli data

        Args:
            dob: Date of birth (YYYY-MM-DD or DD/MM/YYYY)
            tob: Time of birth (HH:MM AM/PM or 24-hour format)
            place: Birth place (city name)

        Returns:
            Complete kundli data dict with success status
        """
        if not self.calculate_kundli:
            return {
                "success": False,
                "error": "Kundli calculation module not available"
            }

        try:
            logger.info(f"[Kundli] Calculating for DOB: {dob}, TOB: {tob}, Place: {place}")

            # Calculate kundli using existing skill
            kundli_data = self.calculate_kundli(dob, tob, place)

            if not kundli_data:
                return {
                    "success": False,
                    "error": "Kundli calculation returned empty data"
                }

            # Extract key information
            result = {
                "success": True,
                "data": kundli_data,
                "lagna": kundli_data.get("lagna"),
                "moon_sign": kundli_data.get("moon_sign"),
                "nakshatra": kundli_data.get("nakshatra"),
                "planet_positions": kundli_data.get("planet_positions", {}),
                "current_dasha": kundli_data.get("current_dasha"),
                "confidence": kundli_data.get("confidence"),
                "warnings": kundli_data.get("warnings", [])
            }

            logger.info(f"[Kundli] Calculation successful: Lagna={result['lagna']}, Rashi={result['moon_sign']}")
            return result

        except Exception as e:
            logger.error(f"[Kundli] Calculation failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def generate_charts(
        self,
        kundli_data: Dict[str, Any]
    ) -> Dict[str, Optional[str]]:
        """
        Generate kundli chart images (base64 encoded)

        Args:
            kundli_data: Calculated kundli data

        Returns:
            Dict with birth_chart and navamsa_chart as base64 strings
        """
        if not self.draw_kundli_chart:
            return {
                "error": "Chart generation module not available"
            }

        try:
            logger.info("[Kundli] Generating birth chart (Lagna Kundli)")

            # Generate birth chart (Lagna Kundli)
            birth_chart = self.draw_kundli_chart(kundli_data, chart_type="birth")

            if not birth_chart:
                return {
                    "error": "Birth chart generation failed"
                }

            logger.info("[Kundli] Birth chart generated successfully")

            # For now, we'll use the same chart for navamsa
            # TODO: Implement proper navamsa chart generation
            navamsa_chart = birth_chart

            logger.info("[Kundli] Navamsa chart generated (using birth chart)")

            return {
                "birth_chart": birth_chart,
                "navamsa_chart": navamsa_chart
            }

        except Exception as e:
            logger.error(f"[Kundli] Chart generation failed: {e}", exc_info=True)
            return {
                "error": str(e)
            }

    def parse_birth_details(
        self,
        date_of_birth: str,
        time_of_birth: str,
        birth_place: str
    ) -> Dict[str, str]:
        """
        Parse and format birth details for kundli calculation

        Args:
            date_of_birth: Various date formats
            time_of_birth: Various time formats
            birth_place: City name

        Returns:
            Dict with formatted dob, tob, place
        """
        import re
        from datetime import datetime

        # Parse date
        dob_formats = [
            "%Y-%m-%d",      # 1990-01-15
            "%d/%m/%Y",      # 15/01/1990
            "%d-%m-%Y",      # 15-01-1990
            "%d %B %Y",      # 15 January 1990
            "%B %d %Y"       # January 15 1990
        ]

        formatted_dob = date_of_birth
        for fmt in dob_formats:
            try:
                dt = datetime.strptime(date_of_birth, fmt)
                formatted_dob = dt.strftime("%Y-%m-%d")
                break
            except ValueError:
                continue

        # Parse time
        tob_formats = [
            "%H:%M",        # 14:30
            "%I:%M %p",      # 02:30 PM
            "%I:%M%p"        # 02:30PM
        ]

        formatted_tob = time_of_birth
        for fmt in tob_formats:
            try:
                # Add space if needed
                test_tob = time_of_birth.strip().upper()
                if "PM" in test_tob or "AM" in test_tob:
                    # Convert to 24-hour format
                    parts = test_tob.split()
                    if len(parts) == 2:
                        time_part = parts[0]
                        meridiem = parts[1]
                        try:
                            dt = datetime.strptime(time_part + meridiem, "%I:%M%p")
                            formatted_tob = dt.strftime("%H:%M")
                            break
                        except ValueError:
                            continue
                else:
                    dt = datetime.strptime(test_tob, fmt)
                    formatted_tob = dt.strftime("%H:%M")
                    break
            except ValueError:
                continue

        # Clean place name
        formatted_place = birth_place.strip().title()

        return {
            "dob": formatted_dob,
            "tob": formatted_tob,
            "place": formatted_place
        }

    def format_planet_positions(
        self,
        planet_positions: Dict[str, Any]
    ) -> Dict[str, Dict[str, str]]:
        """
        Format planet positions for PDF table

        Args:
            planet_positions: Raw planet positions from calculation

        Returns:
            Formatted planet positions with all required fields
        """
        formatted = {}

        # All 9 planets in Vedic astrology
        all_planets = ["sun", "moon", "mars", "mercury", "jupiter", "venus", "saturn", "rahu", "ketu"]

        for planet in all_planets:
            if planet in planet_positions:
                planet_data = planet_positions[planet]

                formatted[planet] = {
                    "sign": planet_data.get("sign", "Unknown"),
                    "house": planet_data.get("house", 0),
                    "degree": planet_data.get("degree", "0°00'"),
                    "nakshatra": planet_data.get("nakshatra", "Unknown")
                }
            else:
                # Planet not found - add placeholder
                formatted[planet] = {
                    "sign": "Unknown",
                    "house": 0,
                    "degree": "0°00'",
                    "nakshatra": "Unknown"
                }

        return formatted

    def get_dasha_period(
        self,
        kundli_data: Dict[str, Any]
    ) -> Dict[str, str]:
        """
        Get current Vimshottari Dasha period

        Args:
            kundli_data: Calculated kundli data

        Returns:
            Dict with mahadasha and antardasha info
        """
        current_dasha = kundli_data.get("current_dasha", {})

        return {
            "mahadasha": current_dasha.get("mahadasha", "Unknown"),
            "antardasha": current_dasha.get("antardasha", "Unknown"),
            "mahadasha_lord": current_dasha.get("mahadasha_lord", "Unknown"),
            "period_start": current_dasha.get("period_start", "Unknown"),
            "period_end": current_dasha.get("period_end", "Unknown")
        }

    def validate_birth_details(
        self,
        dob: str,
        tob: str,
        place: str
    ) -> Dict[str, Any]:
        """
        Validate birth details before kundli calculation

        Args:
            dob: Date of birth
            tob: Time of birth
            place: Birth place

        Returns:
            Dict with valid status and error message if invalid
        """
        errors = []

        # Validate date
        if not dob:
            errors.append("Date of birth is required")
        else:
            try:
                # Try to parse the date
                self.parse_birth_details(dob, "00:00", place)
            except Exception:
                errors.append("Invalid date format")

        # Validate time
        if not tob:
            errors.append("Time of birth is required")
        else:
            # Check if time format is valid
            valid_formats = ["%H:%M", "%I:%M %p", "%I:%M%p"]
            time_valid = False
            for fmt in valid_formats:
                try:
                    import datetime
                    # Try parsing
                    parts = tob.strip().upper().split()
                    if len(parts) == 2 and parts[1] in ["AM", "PM"]:
                        datetime.datetime.strptime(tob, "%I:%M %p")
                    else:
                        datetime.datetime.strptime(tob, fmt)
                    time_valid = True
                    break
                except ValueError:
                    continue

            if not time_valid:
                errors.append("Invalid time format. Use HH:MM or HH:MM AM/PM")

        # Validate place
        if not place:
            errors.append("Birth place is required")
        elif len(place) < 3:
            errors.append("Birth place name is too short")

        if errors:
            return {
                "valid": False,
                "errors": errors
            }

        return {
            "valid": True,
            "errors": []
        }
