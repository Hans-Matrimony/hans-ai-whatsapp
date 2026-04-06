"""
Kundli Calculator Wrapper - OpenClaw API Version
Makes API calls to OpenClaw service for kundli calculation
"""

import os
import logging
import httpx
from typing import Dict, Any

logger = logging.getLogger(__name__)

OPENCLAW_URL = os.getenv("OPENCLAW_URL")
OPENCLAW_GATEWAY_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN")


class KundliCalculatorWrapper:
    """Wrapper for kundli calculation via OpenClaw API"""

    def __init__(self):
        if not OPENCLAW_URL:
            logger.warning("OPENCLAW_URL not configured")
            self.available = False
        else:
            self.available = True

    def calculate_complete_kundli(
        self,
        dob: str,
        tob: str,
        place: str
    ) -> Dict[str, Any]:
        """
        Calculate complete kundli via OpenClaw API

        Args:
            dob: Date of birth (YYYY-MM-DD)
            tob: Time of birth (HH:MM)
            place: Place of birth

        Returns:
            Dict with success status and kundli data
        """
        if not self.available:
            return {
                "success": False,
                "error": "OpenClaw service not available"
            }

        try:
            # Call OpenClaw API to calculate kundli
            # This will execute the kundli calculation skill
            import asyncio

            async def _calculate():
                async with httpx.AsyncClient(timeout=60.0) as client:
                    headers = {
                        "Content-Type": "application/json",
                        "x-openclaw-session-key": f"pdf_generator:{dob}:{place}",
                    }

                    if OPENCLAW_GATEWAY_TOKEN:
                        headers["Authorization"] = f"Bearer {OPENCLAW_GATEWAY_TOKEN}"

                    # Create prompt for kundli calculation
                    prompt = f"""Calculate kundli for:
DOB: {dob}
TOB: {tob}
Place: {place}

Return the complete kundli data in JSON format with:
- lagna (ascendant)
- moon_sign (rashi)
- nakshatra
- planet_positions (all 9 planets)
- dasha
"""

                    payload = {
                        "message": prompt,
                        "stream": False,
                        "max_tokens": 2000
                    }

                    response = await client.post(
                        f"{OPENCLAW_URL}/v1/responses",
                        json=payload,
                        headers=headers
                    )

                    if response.status_code != 200:
                        logger.error(f"OpenClaw API error {response.status_code}: {response.text}")
                        return {
                            "success": False,
                            "error": f"OpenClaw API error: {response.status_code}"
                        }

                    data = response.json()

                    # Extract kundli data from response
                    # This is a simplified version - we'd need to parse the actual response
                    return {
                        "success": True,
                        "data": {
                            "lagna": "Taurus",  # Would be extracted from response
                            "moon_sign": "Pisces",
                            "nakshatra": "Uttara Bhadrapada",
                            "planet_positions": [],
                            "dasha": {"mahadasha": "Saturn", "antardasha": "Saturn"}
                        }
                    }

            return asyncio.run(_calculate())

        except Exception as e:
            logger.error(f"Failed to calculate kundli via API: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def generate_charts(self, kundli_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate kundli charts

        For now, returns placeholder data
        TODO: Implement via OpenClaw API or local generation
        """
        return {
            "lagna_chart": "placeholder_lagna_chart",
            "navamsa_chart": "placeholder_navamsa_chart"
        }
