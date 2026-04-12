"""
Razorpay Native WhatsApp Payments - Two Implementation Options

Option 1: Hybrid (Works Immediately)
- Creates Razorpay payment link
- Sends via WhatsApp button
- Opens in browser when clicked
- Works NOW without special setup

Option 2: True Native (Requires Meta + Razorpay Partnership)
- Uses WhatsApp Flows
- Razorpay opens directly in WhatsApp
- 100% seamless experience
- Requires 2-4 week approval process
"""

import logging
import httpx
from typing import Dict, Any, List, Optional
import os
import json
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class RazorpayWhatsAppPaymentSender:
    """
    Send enforcement messages with Razorpay payment buttons

    Supports two modes:
    1. Hybrid mode (default): Button opens Razorpay payment in browser
    2. Native mode: Button opens Razorpay payment directly in WhatsApp (requires partnership)
    """

    def __init__(
        self,
        phone_id: str,
        access_token: str,
        razorpay_key_id: str,
        razorpay_key_secret: str,
        subscriptions_url: str = None,
        use_native_whatsapp_flow: bool = False,
        whatsapp_flow_id: str = None
    ):
        """
        Initialize Razorpay WhatsApp payment sender

        Args:
            phone_id: WhatsApp Phone ID
            access_token: WhatsApp Access Token
            razorpay_key_id: Razorpay Key ID
            razorpay_key_secret: Razorpay Key Secret
            subscriptions_url: Subscriptions service URL
            use_native_whatsapp_flow: Set True if you have Meta + Razorpay partnership
            whatsapp_flow_id: Flow ID from Meta Business Suite (for native mode)
        """
        self.phone_id = phone_id
        self.access_token = access_token
        self.razorpay_key_id = razorpay_key_id
        self.razorpay_key_secret = razorpay_key_secret
        self.subscriptions_url = subscriptions_url
        self.use_native_whatsapp_flow = use_native_whatsapp_flow
        self.whatsapp_flow_id = whatsapp_flow_id
        self.api_url = "https://graph.facebook.com/v18.0"
        self.razorpay_api_url = "https://api.razorpay.com/v1"

        if use_native_whatsapp_flow and not whatsapp_flow_id:
            logger.warning("[Razorpay WhatsApp] Native mode requested but no flow_id provided, falling back to hybrid mode")
            self.use_native_whatsapp_flow = False

        logger.info(f"[Razorpay WhatsApp] Initialized in {'Native' if use_native_whatsapp_flow else 'Hybrid'} mode")

    async def send_enforcement_with_razorpay_buttons(
        self,
        phone: str,
        user_id: str,
        astrologer_name: str,
        language: str,
        enforcement_type: str = "soft_paywall",
        mongo_logger_url: str = None
    ) -> bool:
        """
        Send enforcement message with Razorpay payment buttons

        Args:
            phone: User's phone number
            user_id: User's phone number
            astrologer_name: Meera or Aarav
            language: english or hinglish
            enforcement_type: soft_paywall, daily_limit, payment_nudge
            mongo_logger_url: MongoDB URL for context

        Returns:
            True if successful, False otherwise
        """
        try:
            # Fetch plans from subscriptions service
            plans = await self._fetch_plans()
            if not plans:
                logger.warning("[Razorpay WhatsApp] No plans available")
                return False

            # Build personalized message based on language
            message = await self._build_message(
                astrologer_name=astrologer_name,
                language=language,
                enforcement_type=enforcement_type,
                phone=phone,
                mongo_logger_url=mongo_logger_url
            )

            # Send main message
            await self._send_text_message(phone, message)

            # Send each plan with Razorpay payment button
            for idx, plan in enumerate(plans, 1):
                await self._send_plan_with_razorpay_button(
                    phone=phone,
                    user_id=user_id,
                    plan=plan,
                    plan_number=idx,
                    language=language
                )

            # Send footer message
            footer = await self._build_footer(language)
            await self._send_text_message(phone, footer)

            logger.info(
                f"[Razorpay WhatsApp] Sent {enforcement_type} with {len(plans)} Razorpay buttons to {phone}"
            )
            return True

        except Exception as e:
            logger.error(f"[Razorpay WhatsApp] Error: {e}", exc_info=True)
            return False

    async def _fetch_plans(self) -> List[Dict[str, Any]]:
        """Fetch active plans from subscriptions service"""
        try:
            if not self.subscriptions_url:
                return self._get_default_plans()

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.subscriptions_url}/plans",
                    params={"active": "true"}
                )

                if response.status_code == 200:
                    data = response.json()
                    return data.get("plans", [])
                else:
                    logger.warning(f"[Razorpay WhatsApp] Failed to fetch plans: {response.status_code}")
                    return self._get_default_plans()

        except Exception as e:
            logger.warning(f"[Razorpay WhatsApp] Error fetching plans: {e}")
            return self._get_default_plans()

    def _get_default_plans(self) -> List[Dict[str, Any]]:
        """Default plan if API fails - YOUR ₹199/month plan"""
        return [
            {
                "planId": "monthly_199",
                "name": "Monthly",
                "price": 19900,  # ₹199 in paise
                "durationDays": 30,
                "features": ["Unlimited messages", "Full astrology access", "Priority support"]
            }
        ]

    async def _build_message(
        self,
        astrologer_name: str,
        language: str,
        enforcement_type: str,
        phone: str,
        mongo_logger_url: str = None
    ) -> str:
        """Build personalized message based on language"""
        context = await self._get_user_context(phone, mongo_logger_url)

        if language == "english":
            return self._build_english_message(astrologer_name, enforcement_type, context)
        else:
            return self._build_hinglish_message(astrologer_name, enforcement_type, context)

    def _build_english_message(
        self,
        astrologer_name: str,
        enforcement_type: str,
        context: str
    ) -> str:
        """Build English message"""
        if astrologer_name == "Meera":
            message = f"💫 *I'd love to continue our conversation, {context}!*\n\n"
        else:
            message = f"💫 *I'd love to continue our conversation, {context}!*\n\n"

        if enforcement_type == "soft_paywall":
            message += "I know, you've reached your free message limit (40/40) 😔\n\n"
        elif enforcement_type == "daily_limit":
            message += "I know, you've reached your daily limit (5/5 today) 😔\n\n"
        elif enforcement_type == "payment_nudge":
            message += "I know, your trial has expired 😔\n\n"

        message += "Choose a plan below to continue instantly:\n\n"
        return message

    def _build_hinglish_message(
        self,
        astrologer_name: str,
        enforcement_type: str,
        context: str
    ) -> str:
        """Build Hinglish message"""
        if astrologer_name == "Meera":
            message = f"💫 *Main tumhari baat continue karna chahti hoon, {context}!*\n\n"
        else:
            message = f"💫 *Main tumhari baat continue karna chahta hoon, {context}!*\n\n"

        if enforcement_type == "soft_paywall":
            message += "I know, tumhari free messages khatam ho gayi hain (40/40) 😔\n\n"
        elif enforcement_type == "daily_limit":
            message += "I know, aaj ki messages khatam ho gayi hain (5/5) 😔\n\n"
        elif enforcement_type == "payment_nudge":
            message += "I know, tumhari trial expire ho gayi hai 😔\n\n"

        message += "Niche plan select karo:\n\n"
        return message

    async def _get_user_context(self, phone: str, mongo_logger_url: str = None) -> str:
        """Get user context from recent messages"""
        try:
            if not mongo_logger_url:
                return "and there's so much I want to share with you"

            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"{mongo_logger_url}/messages",
                    params={"user_id": phone, "limit": 5}
                )

                if response.status_code == 200:
                    data = response.json()
                    messages = data.get("messages", [])

                    for msg in reversed(messages):
                        if msg.get("role") == "user":
                            content = msg.get("content", "").lower()
                            if "marriage" in content or "shaadi" in content or "vivah" in content:
                                return "and I remember you were worried about your marriage timing"
                            elif "career" in content or "job" in content or "naukri" in content:
                                return "and I know you've been stressed about your career"
                            elif "health" in content or "swasthya" in content or "roga" in content:
                                return "and I understand your health concerns"

            return "and there's so much I want to share with you"

        except Exception as e:
            logger.warning(f"[Razorpay WhatsApp] Error getting context: {e}")
            return "and there's so much I want to share with you"

    async def _send_plan_with_razorpay_button(
        self,
        phone: str,
        user_id: str,
        plan: Dict[str, Any],
        plan_number: int,
        language: str
    ) -> None:
        """
        Send plan with Razorpay payment button

        Uses Hybrid mode (default) or Native mode (if partnership approved)
        """
        try:
            price_rupees = plan.get("price", 0) / 100
            duration = plan.get("durationDays", 30)
            plan_id = plan.get("planId", "")
            features = plan.get("features", [])

            # Build plan message
            if language == "english":
                if duration == 1:
                    duration_text = "1 Day"
                elif duration == 30:
                    duration_text = "Monthly"
                elif duration == 365:
                    duration_text = "Yearly (Best Value! 🌟)"
                else:
                    duration_text = f"{duration} Days"

                message = f"*{duration_text} - ₹{price_rupees}*\n"
                for feature in features[:3]:
                    message += f"✓ {feature}\n"

                button_text = f"Buy Now - ₹{price_rupees}"

            else:  # Hinglish
                if duration == 1:
                    duration_text = "1 Day"
                elif duration == 30:
                    duration_text = "Monthly"
                elif duration == 365:
                    duration_text = "Yearly (Best Value! 🌟)"
                else:
                    duration_text = f"{duration} Days"

                message = f"*{duration_text} - ₹{price_rupees}*\n"
                for feature in features[:3]:
                    message += f"✓ {feature}\n"

                button_text = f"Buy Now - ₹{price_rupees}"

            # Create Razorpay payment link
            razorpay_payment_link = await self._create_razorpay_payment_link(
                user_id=user_id,
                plan_id=plan_id,
                amount=int(plan.get("price", 0)),
                phone=phone
            )

            if not razorpay_payment_link:
                logger.error(f"[Razorpay WhatsApp] Failed to create payment link")
                return

            # Send button based on mode
            if self.use_native_whatsapp_flow:
                # Native mode: WhatsApp Flow (requires partnership)
                await self._send_whatsapp_flow_button(
                    phone=phone,
                    text=message,
                    razorpay_link=razorpay_payment_link
                )
            else:
                # Hybrid mode: CTA URL button (works immediately)
                await self._send_cta_url_button(
                    phone=phone,
                    text=message,
                    razorpay_link=razorpay_payment_link
                )

            logger.debug(
                f"[Razorpay WhatsApp] Sent {'Native' if self.use_native_whatsapp_flow else 'Hybrid'} button: {button_text} to {phone}"
            )

        except Exception as e:
            logger.error(f"[Razorpay WhatsApp] Error sending plan button: {e}", exc_info=True)

    async def _create_razorpay_payment_link(
        self,
        user_id: str,
        plan_id: str,
        amount: int,
        phone: str
    ) -> Optional[str]:
        """
        Create Razorpay payment link

        Args:
            user_id: User's phone number
            plan_id: Plan ID
            amount: Amount in paise (₹199 = 19900)
            phone: User's phone number

        Returns:
            Razorpay payment short URL
        """
        try:
            # Razorpay payment link payload (simplified - only supported fields)
            payload = {
                "amount": amount,
                "currency": "INR",
                "accept_partial": False,
                "description": f"Astrology subscription - {plan_id}",
                "customer": {
                    "name": f"User {user_id}",
                    "email": f"user_{user_id}@example.com",
                    "contact": f"+{user_id.lstrip('+')}"
                },
                "notes": {
                    "plan_id": plan_id,
                    "user_id": user_id,
                    "phone": phone
                },
                "notify": {
                    "sms": False,
                    "email": False
                }
            }

            # Call Razorpay API
            auth = (self.razorpay_key_id, self.razorpay_key_secret)

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.razorpay_api_url}/payment_links",
                    auth=auth,
                    json=payload
                )

                if response.status_code not in [200, 201]:
                    logger.error(f"[Razorpay WhatsApp] Payment link creation failed: {response.status_code} - {response.text}")
                    return None

                payment_data = response.json()

                # Get short URL from response
                short_url = payment_data.get("short_url", "")

                if short_url:
                    logger.info(f"[Razorpay WhatsApp] Payment link created: {payment_data.get('id')}")
                    return short_url
                else:
                    logger.error("[Razorpay WhatsApp] No short URL in response")
                    return None

        except Exception as e:
            logger.error(f"[Razorpay WhatsApp] Error creating payment link: {e}", exc_info=True)
            return None

    async def _send_cta_url_button(
        self,
        phone: str,
        text: str,
        razorpay_link: str
    ) -> None:
        """
        Send WhatsApp CTA URL button (Hybrid mode)

        When user taps button, opens Razorpay payment in browser

        Args:
            phone: User's phone number
            text: Message text
            razorpay_link: Razorpay payment link
        """
        url = f"{self.api_url}/{self.phone_id}/messages"

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

        # WhatsApp CTA URL button payload
        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "interactive",
            "interactive": {
                "type": "cta_url",
                "body": {
                    "text": text
                },
                "action": {
                    "name": "cta_url",
                    "parameters": {
                        "url": razorpay_link
                    }
                }
            }
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()

            logger.info(
                f"[Razorpay WhatsApp] Sent CTA URL button to {phone}"
            )

    async def _send_whatsapp_flow_button(
        self,
        phone: str,
        text: str,
        razorpay_link: str
    ) -> None:
        """
        Send WhatsApp Flow button (Native mode - REQUIRES PARTNERSHIP)

        When user taps button, Razorpay payment opens directly in WhatsApp

        Args:
            phone: User's phone number
            text: Message text
            razorpay_link: Razorpay payment link
        """
        if not self.whatsapp_flow_id:
            logger.error("[Razorpay WhatsApp] Native mode requires flow_id")
            # Fallback to hybrid mode
            await self._send_cta_url_button(phone, text, razorpay_link)
            return

        url = f"{self.api_url}/{self.phone_id}/messages"

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

        # WhatsApp Flow button payload (Native mode)
        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "interactive",
            "interactive": {
                "type": "flow",
                "header": {
                    "type": "text",
                    "text": "Complete Your Payment"
                },
                "body": {
                    "text": text
                },
                "footer": {
                    "text": "Tap the button below to pay securely via Razorpay"
                },
                "action": {
                    "name": "flow",
                    "parameters": {
                        "flow_id": self.whatsapp_flow_id,
                        "flow_token": f"temp_token_{int(datetime.now().timestamp())}",
                        "flow_cta": "Pay Now",
                        "flow_action": "open",
                        "flow_action_payload": {
                            "razorpay_link": razorpay_link,
                            "amount": text
                        }
                    }
                }
            }
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()

            logger.info(
                f"[Razorpay WhatsApp] Sent WhatsApp Flow button (Native) to {phone}"
            )

    async def _build_footer(self, language: str) -> str:
        """Build footer message based on language"""
        if language == "english":
            if self.use_native_whatsapp_flow:
                return "✨ Tap the button above to pay securely via Razorpay (without leaving WhatsApp)!"
            else:
                return "✨ Tap the button above to pay securely via Razorpay!"
        else:
            if self.use_native_whatsapp_flow:
                return "✨ Upar diye gaye button tap karke WhatsApp ke andar hi securely Razorpay se pay kar sakte ho!"
            else:
                return "✨ Upar diye gaye button tap karke securely Razorpay se pay kar sakte ho!"

    async def _send_text_message(self, phone: str, message: str) -> None:
        """Send text message via WhatsApp API"""
        url = f"{self.api_url}/{self.phone_id}/messages"

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "text",
            "text": {
                "body": message
            }
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()


# Singleton instance
_razorpay_whatsapp_sender = None


def get_razorpay_whatsapp_sender(
    phone_id: str = None,
    access_token: str = None,
    razorpay_key_id: str = None,
    razorpay_key_secret: str = None,
    subscriptions_url: str = None,
    use_native_whatsapp_flow: bool = False,
    whatsapp_flow_id: str = None
) -> RazorpayWhatsAppPaymentSender:
    """
    Get or create Razorpay WhatsApp payment sender instance

    Args:
        phone_id: WhatsApp Phone ID
        access_token: WhatsApp Access Token
        razorpay_key_id: Razorpay Key ID
        razorpay_key_secret: Razorpay Key Secret
        subscriptions_url: Subscriptions service URL
        use_native_whatsapp_flow: Set True if you have Meta + Razorpay partnership
        whatsapp_flow_id: Flow ID from Meta Business Suite (for native mode)

    Returns:
        RazorpayWhatsAppPaymentSender instance
    """
    global _razorpay_whatsapp_sender

    if _razorpay_whatsapp_sender is None:
        if not phone_id or not access_token:
            raise ValueError("phone_id and access_token required")
        if not razorpay_key_id or not razorpay_key_secret:
            raise ValueError("Razorpay credentials required")

        _razorpay_whatsapp_sender = RazorpayWhatsAppPaymentSender(
            phone_id=phone_id,
            access_token=access_token,
            razorpay_key_id=razorpay_key_id,
            razorpay_key_secret=razorpay_key_secret,
            subscriptions_url=subscriptions_url,
            use_native_whatsapp_flow=use_native_whatsapp_flow,
            whatsapp_flow_id=whatsapp_flow_id
        )
        logger.info("[Razorpay WhatsApp] Razorpay WhatsApp payment sender initialized")

    return _razorpay_whatsapp_sender
