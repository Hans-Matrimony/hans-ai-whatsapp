"""
WhatsApp Cloud API client
"""
import logging
from typing import Optional, Dict, Any, List
import httpx

logger = logging.getLogger(__name__)


class WhatsAppAPI:
    """WhatsApp Cloud API client"""

    def __init__(
        self,
        phone_id: str,
        access_token: str,
        api_version: str = "v18.0"
    ):
        self.phone_id = phone_id
        self.access_token = access_token
        self.base_url = f"https://graph.facebook.com/{api_version}"
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

    async def send_text(
        self,
        to: str,
        message: str,
        preview_url: bool = False
    ) -> Optional[str]:
        """Send text message"""
        url = f"{self.base_url}/{self.phone_id}/messages"

        payload = {
            "messaging_product": "whatsapp",
            "to": to.lstrip("+"),
            "type": "text",
            "text": {
                "body": message,
                "preview_url": preview_url
            }
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=self.headers, json=payload)

                if response.status_code in [200, 201]:
                    data = response.json()
                    return data.get("contacts", [{}])[0].get("input")
                else:
                    logger.error(f"Send failed: {response.status_code} - {response.text}")
                    return None

        except Exception as e:
            logger.error(f"Error sending text: {e}")
            return None

    async def send_template(
        self,
        to: str,
        template_name: str,
        components: Optional[List[Dict]] = None,
        language_code: str = "en"
    ) -> Optional[str]:
        """Send template message"""
        url = f"{self.base_url}/{self.phone_id}/messages"

        payload = {
            "messaging_product": "whatsapp",
            "to": to.lstrip("+"),
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code}
            }
        }

        if components:
            payload["template"]["components"] = components

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=self.headers, json=payload)

                if response.status_code in [200, 201]:
                    data = response.json()
                    return data.get("contacts", [{}])[0].get("input")
                else:
                    logger.error(f"Template send failed: {response.status_code}")
                    return None

        except Exception as e:
            logger.error(f"Error sending template: {e}")
            return None

    async def send_interactive_buttons(
        self,
        to: str,
        text: str,
        buttons: List[Dict[str, str]]
    ) -> Optional[str]:
        """Send interactive message with buttons"""
        url = f"{self.base_url}/{self.phone_id}/messages"

        button_objs = []
        for i, btn in enumerate(buttons[:3]):
            button_objs.append({
                "type": "reply",
                "reply": {
                    "id": btn.get("id", f"btn_{i}"),
                    "title": btn.get("title", f"Button {i+1}")
                }
            })

        payload = {
            "messaging_product": "whatsapp",
            "to": to.lstrip("+"),
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": text},
                "action": {"buttons": button_objs}
            }
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=self.headers, json=payload)

                if response.status_code in [200, 201]:
                    data = response.json()
                    return data.get("contacts", [{}])[0].get("input")
                else:
                    logger.error(f"Interactive send failed: {response.status_code}")
                    return None

        except Exception as e:
            logger.error(f"Error sending interactive: {e}")
            return None

    async def mark_as_read(self, message_id: str) -> bool:
        """Mark message as read"""
        url = f"{self.base_url}/{self.phone_id}/messages"

        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=self.headers, json=payload)
                return response.status_code in [200, 201]

        except Exception as e:
            logger.error(f"Error marking as read: {e}")
            return False

    async def get_business_profile(self) -> Optional[Dict]:
        """Get business profile"""
        url = f"{self.base_url}/{self.phone_id}/whatsapp_business_profile"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=self.headers)

                if response.status_code == 200:
                    data = response.json()
                    return data.get("data", [{}])[0]
                else:
                    return None

        except Exception as e:
            logger.error(f"Error getting business profile: {e}")
            return None
