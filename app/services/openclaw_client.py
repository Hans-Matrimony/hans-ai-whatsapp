"""
OpenClaw Gateway client
"""
import logging
from typing import Optional, Dict, Any
import httpx

logger = logging.getLogger(__name__)


class OpenClawClient:
    """Client for OpenClaw Gateway API"""

    def __init__(
        self,
        base_url: str,
        api_key: Optional[str] = None,
        timeout: int = 60
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _get_headers(self) -> Dict[str, str]:
        """Get request headers"""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def send_message(
        self,
        channel: str,
        from_number: str,
        message: str,
        message_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict]:
        """Send message to OpenClaw for processing"""
        url = f"{self.base_url}/webhook/whatsapp"

        payload = {
            "channel": channel,
            "from": from_number,
            "message": message,
            "metadata": metadata or {}
        }

        if message_id:
            payload["message_id"] = message_id

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url,
                    headers=self._get_headers(),
                    json=payload
                )

                if response.status_code == 200:
                    return response.json()
                else:
                    logger.error(f"OpenClaw error: {response.status_code} - {response.text}")
                    return None

        except httpx.TimeoutException:
            logger.error("OpenClaw request timed out")
            return None
        except Exception as e:
            logger.error(f"Error sending to OpenClaw: {e}")
            return None

    async def get_agent_response(
        self,
        agent_id: str,
        message: str,
        user_id: str,
        thinking: str = "medium"
    ) -> Optional[str]:
        """Get response from specific agent"""
        url = f"{self.base_url}/agent"

        payload = {
            "agent": agent_id,
            "message": message,
            "user_id": user_id,
            "thinking": thinking
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url,
                    headers=self._get_headers(),
                    json=payload
                )

                if response.status_code == 200:
                    data = response.json()
                    return data.get("response")
                else:
                    return None

        except Exception as e:
            logger.error(f"Error getting agent response: {e}")
            return None

    async def health_check(self) -> bool:
        """Check if OpenClaw is healthy"""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"{self.base_url}/health")
                return response.status_code == 200
        except Exception:
            return False
