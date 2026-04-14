"""
Kundli Calculator Wrapper - OpenClaw API Version
Makes API calls to OpenClaw service for kundli calculation
"""

import os
import logging
import httpx
import asyncio
from typing import Dict, Any

logger = logging.getLogger(__name__)

OPENCLAW_URL = os.getenv("OPENCLAW_URL")
OPENCLAW_GATEWAY_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN")


class KundliCalculatorWrapper:
    """Wrapper for kundli calculation via OpenClaw API with retry logic"""

    def __init__(self):
        if not OPENCLAW_URL:
            logger.warning("OPENCLAW_URL not configured")
            self.available = False
        else:
            self.available = True

    async def _call_openclaw_with_retry(
        self,
        prompt: str,
        max_tokens: int = 2000,
        temperature: float = 0.3,
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """
        Call OpenClaw API with retry logic for kundli calculation.

        Args:
            prompt: The prompt to send
            max_tokens: Maximum tokens in response
            temperature: Temperature for generation
            max_retries: Number of retry attempts

        Returns:
            Dict with success status and data/error
        """
        base_delay = 1.0  # seconds

        for attempt in range(max_retries):
            try:
                headers = {
                    "Content-Type": "application/json",
                    "x-openclaw-scopes": "operator.admin,operator.write"
                }

                if OPENCLAW_GATEWAY_TOKEN:
                    headers["Authorization"] = f"Bearer {OPENCLAW_GATEWAY_TOKEN}"

                payload = {
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "model": "google/gemini-3.1-flash"
                }

                # Increase timeout for retries (kundli calculation can be slow)
                timeout = 60.0 * (1 + attempt * 0.5)

                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(
                        f"{OPENCLAW_URL}/v1/chat/completions",
                        json=payload,
                        headers=headers
                    )

                    if response.status_code != 200:
                        logger.warning(
                            f"[Kundli Calculator] OpenClaw API error (attempt {attempt + 1}/{max_retries}): "
                            f"{response.status_code} - {response.text[:200]}"
                        )

                        # Don't retry on client errors (4xx)
                        if 400 <= response.status_code < 500:
                            return {
                                "success": False,
                                "error": f"Client error: {response.status_code}"
                            }

                        # Retry on server errors
                        if attempt < max_retries - 1:
                            await asyncio.sleep(base_delay * (2 ** attempt))
                            continue
                        return {
                            "success": False,
                            "error": f"API error after {max_retries} attempts: {response.status_code}"
                        }

                    data = response.json()

                    if "choices" in data and len(data["choices"]) > 0:
                        content = data["choices"][0]["message"]["content"]

                        # Check for error responses
                        error_indicators = [
                            "no response from openclaw",
                            "error from openclaw",
                            "failed to generate",
                            "unable to respond",
                            "timeout",
                            "rate limit"
                        ]

                        content_lower = content.lower()
                        if any(error in content_lower for error in error_indicators):
                            logger.warning(
                                f"[Kundli Calculator] Error response (attempt {attempt + 1}/{max_retries}): {content[:100]}"
                            )

                            if attempt < max_retries - 1:
                                await asyncio.sleep(base_delay * (2 ** attempt))
                                continue
                            return {
                                "success": False,
                                "error": "Received error response from API"
                            }

                        # Success!
                        logger.info(
                            f"[Kundli Calculator] ✅ Success on attempt {attempt + 1}/{max_retries}"
                        )
                        return {
                            "success": True,
                            "content": content
                        }
                    else:
                        logger.error(
                            f"[Kundli Calculator] Invalid response format (attempt {attempt + 1}/{max_retries})"
                        )

                        if attempt < max_retries - 1:
                            await asyncio.sleep(base_delay * (2 ** attempt))
                            continue
                        return {
                            "success": False,
                            "error": "Invalid response format"
                        }

            except asyncio.TimeoutError as e:
                logger.warning(
                    f"[Kundli Calculator] Timeout on attempt {attempt + 1}/{max_retries}: {e}"
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(base_delay * (2 ** attempt))
                    continue
                return {
                    "success": False,
                    "error": f"Timeout after {max_retries} attempts"
                }

            except httpx.TimeoutException as e:
                logger.warning(
                    f"[Kundli Calculator] HTTP timeout on attempt {attempt + 1}/{max_retries}: {e}"
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(base_delay * (2 ** attempt))
                    continue
                return {
                    "success": False,
                    "error": f"HTTP timeout after {max_retries} attempts"
                }

            except Exception as e:
                logger.error(
                    f"[Kundli Calculator] Error on attempt {attempt + 1}/{max_retries}: {e}",
                    exc_info=True
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(base_delay * (2 ** attempt))
                    continue
                return {
                    "success": False,
                    "error": str(e)
                }

        return {
            "success": False,
            "error": f"Failed after {max_retries} attempts"
        }

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
            prompt = f"""Calculate kundli for:
DOB: {dob}
TOB: {tob}
Place: {place}

Return the complete kundli data in JSON format with:
- lagna (ascendant)
- moon_sign (rashi)
- nakshatra
- planet_positions (all 9 planets with house positions)
- dasha (current mahadasha and antardasha)
- nakshatra_pada

Return ONLY valid JSON, no other text.
"""

            result = asyncio.run(self._call_openclaw_with_retry(
                prompt=prompt,
                max_tokens=2000,
                temperature=0.3,
                max_retries=3
            ))

            if not result.get("success"):
                return {
                    "success": False,
                    "error": result.get("error", "Unknown error")
                }

            content = result.get("content", "")

            # Try to parse JSON from the response
            try:
                import json
                kundli_data = json.loads(content)
                return {
                    "success": True,
                    "data": kundli_data
                }
            except json.JSONDecodeError:
                # Try to extract JSON from markdown code blocks
                import re
                json_match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
                if json_match:
                    try:
                        kundli_data = json.loads(json_match.group(1))
                        return {
                            "success": True,
                            "data": kundli_data
                        }
                    except json.JSONDecodeError:
                        pass

                logger.warning(f"[Kundli Calculator] Could not parse JSON from response: {content[:200]}")
                return {
                    "success": False,
                    "error": "Could not parse kundli data from response"
                }

        except Exception as e:
            logger.error(f"[Kundli Calculator] Failed to calculate kundli: {e}", exc_info=True)
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
