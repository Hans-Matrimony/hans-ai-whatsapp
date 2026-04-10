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

    async def send_document(
        self,
        to: str,
        document_url: str = None,
        media_id: str = None,
        filename: str = None,
        caption: str = None
    ) -> Optional[str]:
        """
        Send document (PDF) via WhatsApp Cloud API

        Args:
            to: Phone number (without +)
            document_url: URL to document (external URL)
            media_id: WhatsApp Media ID (from upload)
            filename: Document filename
            caption: Optional caption text

        Returns:
            Message ID if successful, None otherwise
        """
        url = f"{self.base_url}/{self.phone_id}/messages"

        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "document",
            "document": {}
        }

        # Use media_id if provided (for uploaded files), else use document_url (for external URLs)
        if media_id:
            payload["document"]["id"] = media_id
            if filename:
                payload["document"]["filename"] = filename
        elif document_url:
            payload["document"]["link"] = document_url
            if filename:
                payload["document"]["filename"] = filename
        else:
            logger.error("Either media_id or document_url must be provided")
            return None

        if caption:
            payload["document"]["caption"] = caption

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, headers=self.headers, json=payload)

                if response.status_code in [200, 201]:
                    return response.json().get("messages", [{}])[0].get("id")

                logger.error(f"WhatsApp document send failed: {response.text}")
                return None

        except Exception as e:
            logger.error(f"Error sending document: {e}")
            return None

    async def send_flow(
        self,
        to: str,
        header: str,
        body: str,
        flow_id: str,
        flow_cta: str = "Pay Now",
        payment_config_id: str = None,
        payment_mid: str = None
    ) -> Optional[str]:
        """
        Send WhatsApp Flow message for in-WhatsApp payments.

        Args:
            to: Phone number (with or without +)
            header: Header text for the message
            body: Body text for the message
            flow_id: Flow ID from Meta (created in Business Manager)
            flow_cta: Button text (default "Pay Now")
            payment_config_id: Payment configuration ID (kept for compatibility, not used in API)
            payment_mid: Payment Gateway MID (kept for compatibility, not used in API)

        Returns:
            Message ID if successful, None otherwise

        Note:
            WhatsApp Flows with payment components must be pre-configured in Meta Business Manager.
            The Flow itself contains the payment configuration (amount, etc.).
            Payment config is NOT sent in the API - it's configured in the Flow in Meta Business Manager.
        """
        # Validate flow_id
        if not flow_id:
            logger.error("[WhatsApp Flow] flow_id is None or empty. Cannot send Flow message.")
            logger.error(f"[WhatsApp Flow] WHATSAPP_FLOW_ID environment variable may not be set.")
            return None

        url = f"{self.base_url}/{self.phone_id}/messages"

        # Build the interactive message with Flow component
        # NOTE: Payment configuration is pre-configured in the Flow in Meta Business Manager
        # We do NOT send payment_config_id or payment_mid in the API request
        payload = {
            "messaging_product": "whatsapp",
            "to": to.lstrip("+"),
            "type": "interactive",
            "interactive": {
                "type": "flow",
                "header": {
                    "type": "text",
                    "text": header
                },
                "body": {
                    "text": body
                },
                "action": {
                    "name": "flow",
                    "parameters": {
                        "flow_message_version": "3",
                        "flow_id": flow_id,
                        "flow_cta": flow_cta,
                        "flow_token": flow_id  # Use flow_id as flow_token for payment flows
                    }
                },
                "footer": {
                    "text": "Powered by Razorpay"
                }
            }
        }

        # Log that payment config is pre-configured (not sent in API)
        if payment_config_id:
            logger.info(f"[WhatsApp Flow] Payment config '{payment_config_id}' is pre-configured in Meta Business Manager (not sent in API)")
        if payment_mid:
            logger.info(f"[WhatsApp Flow] Payment MID '{payment_mid[:10]}...' is pre-configured in Meta Business Manager (not sent in API)")

        try:
            # DEBUG: Log the exact payload being sent
            logger.info(f"[DEBUG] Sending WhatsApp Flow with flow_id: {flow_id}")
            logger.info(f"[DEBUG] Full payload: {payload}")
            logger.info(f"[DEBUG] Phone ID: {self.phone_id}")

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, headers=self.headers, json=payload)

                if response.status_code in [200, 201]:
                    data = response.json()
                    logger.info(f"WhatsApp Flow sent successfully: {data}")
                    return data.get("messages", [{}])[0].get("id")
                else:
                    logger.error(f"WhatsApp Flow send failed: {response.status_code} - {response.text}")
                    logger.error(f"[DEBUG] Response body: {response.text}")
                    return None

        except Exception as e:
            logger.error(f"Error sending WhatsApp Flow: {e}")
            return None

    async def send_interactive_list(
        self,
        to: str,
        header: str,
        body: str,
        footer: str,
        button_text: str,
        sections: List[Dict]
    ) -> Optional[str]:
        """
        Send interactive list message (for plan selection).

        Args:
            to: Phone number (with or without +)
            header: Header text
            body: Body text
            footer: Footer text
            button_text: Button text (e.g., "Select Plan")
            sections: List of section objects with rows

        Returns:
            Message ID if successful, None otherwise
        """
        url = f"{self.base_url}/{self.phone_id}/messages"

        payload = {
            "messaging_product": "whatsapp",
            "to": to.lstrip("+"),
            "type": "interactive",
            "interactive": {
                "type": "list",
                "header": {
                    "type": "text",
                    "text": header
                },
                "body": {
                    "text": body
                },
                "footer": {
                    "text": footer
                },
                "action": {
                    "button": button_text,
                    "sections": sections
                }
            }
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, headers=self.headers, json=payload)

                if response.status_code in [200, 201]:
                    data = response.json()
                    return data.get("messages", [{}])[0].get("id")
                else:
                    logger.error(f"List message send failed: {response.status_code} - {response.text}")
                    return None

        except Exception as e:
            logger.error(f"Error sending list message: {e}")
            return None

    async def send_native_payment(
        self,
        to: str,
        header: str,
        body: str,
        plan_name: str,
        amount_paise: int,
        reference_id: str,
        payment_config_id: str
    ) -> Optional[str]:
        """
        Send WhatsApp Indian Native Payment (order_details) checkout via Razorpay.
        Uses v21.0 API which fully supports order_details for India payments.
        """
        # Use v21.0 specifically for payments - v18.0 may not support order_details
        url = f"https://graph.facebook.com/v21.0/{self.phone_id}/messages"

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to.lstrip("+"),
            "type": "interactive",
            "interactive": {
                "type": "order_details",
                "header": {
                    "type": "text",
                    "text": header
                },
                "body": {
                    "text": body
                },
                "footer": {
                    "text": "Powered by Razorpay"
                },
                "action": {
                    "name": "review_and_pay",
                    "parameters": {
                        "reference_id": reference_id,
                        "type": "digital-goods",
                        "payment_configuration": payment_config_id,
                        "currency": "INR",
                        "total_amount": {
                            "value": amount_paise,
                            "offset": 100
                        },
                        "order": {
                            "status": "pending",
                            "subtotal": {
                                "value": amount_paise,
                                "offset": 100
                            },
                            "items": [{
                                "retailer_id": reference_id,
                                "name": plan_name,
                                "amount": {
                                    "value": amount_paise,
                                    "offset": 100
                                },
                                "sale_amount": {
                                    "value": amount_paise,
                                    "offset": 100
                                },
                                "quantity": 1
                            }]
                        }
                    }
                }
            }
        }

        try:
            import json
            logger.info(f"[NativePayment] Full payload: {json.dumps(payload, indent=2)}")
            logger.info(f"[NativePayment] URL: {url}")

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, headers=self.headers, json=payload)

                if response.status_code in [200, 201]:
                    data = response.json()
                    logger.info(f"WhatsApp Native Payment Checkout sent successfully: {data}")
                    return data.get("messages", [{}])[0].get("id")
                else:
                    logger.error(f"WhatsApp Native Payment send failed: {response.status_code} - {response.text}")
                    return None

        except Exception as e:
            logger.error(f"Error sending WhatsApp Native Payment: {e}")
            return None
