"""
Payment Confirmation Messages - Personalized & Context-Aware
Sends warm confirmation messages after successful payment
"""

import logging
import httpx
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class PaymentConfirmationSender:
    """
    Send personalized payment confirmation messages

    Features:
    - Soft friend companion tone (Meera/Aarav)
    - Language aware (English/Hinglish)
    - Context aware (remembers previous conversation)
    - Encourages continued conversation
    - Celebrates their decision warmly
    """

    def __init__(
        self,
        phone_id: str,
        access_token: str,
        mongo_logger_url: str = None
    ):
        """
        Initialize payment confirmation sender

        Args:
            phone_id: WhatsApp Phone ID
            access_token: WhatsApp Access Token
            mongo_logger_url: MongoDB URL for context
        """
        self.phone_id = phone_id
        self.access_token = access_token
        self.mongo_logger_url = mongo_logger_url
        self.api_url = "https://graph.facebook.com/v18.0"

    async def send_payment_confirmation(
        self,
        phone: str,
        user_id: str,
        plan_name: str,
        amount: int,
        astrologer_name: str,
        language: str,
        mongo_logger_url: str = None
    ) -> bool:
        """
        Send personalized payment confirmation message

        Args:
            phone: User's phone number
            user_id: User's ID
            plan_name: Plan name (e.g., "Monthly", "Yearly")
            amount: Amount paid (₹)
            astrologer_name: Meera or Aarav
            language: english or hinglish
            mongo_logger_url: MongoDB URL for context

        Returns:
            True if successful, False otherwise
        """
        try:
            # Get user context
            context = await self._get_user_context(phone, mongo_logger_url)

            # Build personalized confirmation message
            if language == "english":
                message = self._build_english_confirmation(
                    astrologer_name=astrologer_name,
                    plan_name=plan_name,
                    amount=amount,
                    context=context
                )
            else:
                message = self._build_hinglish_confirmation(
                    astrologer_name=astrologer_name,
                    plan_name=plan_name,
                    amount=amount,
                    context=context
                )

            # Send confirmation message
            await self._send_message(phone, message)

            # Small delay
            import asyncio
            await asyncio.sleep(1)

            # Send follow-up encouragement message
            if language == "english":
                followup = self._build_english_followup(astrologer_name, context)
            else:
                followup = self._build_hinglish_followup(astrologer_name, context)

            await self._send_message(phone, followup)

            logger.info(
                f"[Payment Confirmation] Sent confirmation to {phone} for {plan_name} plan"
            )
            return True

        except Exception as e:
            logger.error(f"[Payment Confirmation] Error: {e}", exc_info=True)
            return False

    def _build_english_confirmation(
        self,
        astrologer_name: str,
        plan_name: str,
        amount: int,
        context: str
    ) -> str:
        """Build English confirmation message"""
        if astrologer_name == "Meera":
            message = f"🎉 *Yay! Your plan is now active!* 💫\n\n"

            if "marriage" in context.lower() or "wedding" in context.lower():
                message += f"Thank you for trusting me, {context}!\n\n"
                message += f"Your {plan_name} plan (₹{amount}) has been activated successfully.\n\n"
                message += "✨ Now I can give you the complete marriage timing analysis you were looking for!\n\n"
                message += "You now have:\n"
                message += "✅ Unlimited messages\n"
                message += "✅ Full astrology access\n"
                message += "✅ Priority responses\n\n"
                message += "Ask me anything about your marriage timing - I'm here for you! 💕"

            elif "career" in context.lower() or "job" in context.lower():
                message += f"Thank you for choosing me, {context}!\n\n"
                message += f"Your {plan_name} plan (₹{amount}) is now active!\n\n"
                message += "✨ I'm so excited to help you with your career path!\n\n"
                message += "You now have:\n"
                message += "✅ Unlimited messages\n"
                message += "✅ Full astrology access\n"
                message += "✅ Priority responses\n\n"
                message += "Let's dive deep into your career prospects! 🚀"

            elif "health" in context.lower() or "swasthya" in context.lower():
                message += f"Thank you for trusting me, {context}!\n\n"
                message += f"Your {plan_name} plan (₹{amount}) has been activated.\n\n"
                message += "✨ I'm here to help you understand your health astrology better!\n\n"
                message += "You now have:\n"
                message += "✅ Unlimited messages\n"
                message += "✅ Full astrology access\n"
                message += "✅ Priority responses\n\n"
                message += "Let's explore your health chart together! 🌿"

            else:
                message += f"Thank you so much, {context}!\n\n"
                message += f"Your {plan_name} plan (₹{amount}) is now active!\n\n"
                message += "✨ I'm really happy we can continue our conversation!\n\n"
                message += "You now have:\n"
                message += "✅ Unlimited messages\n"
                message += "✅ Full astrology access\n"
                message += "✅ Priority responses\n\n"
                message += "Ask me anything - I'm here for you! 💕"

        else:  # Aarav
            message = f"🎉 *Awesome! Your plan is now active!* 💫\n\n"

            if "marriage" in context.lower() or "wedding" in context.lower():
                message += f"Thanks for trusting me, {context}!\n\n"
                message += f"Your {plan_name} plan (₹{amount}) has been activated successfully.\n\n"
                message += "✨ Now I can give you the complete marriage analysis you wanted!\n\n"
                message += "You now have:\n"
                message += "✅ Unlimited messages\n"
                message += "✅ Full astrology access\n"
                message += "✅ Priority responses\n\n"
                message += "Let's explore your marriage timing in detail! 💪"

            elif "career" in context.lower() or "job" in context.lower():
                message += f"Great choice, {context}!\n\n"
                message += f"Your {plan_name} plan (₹{amount}) is now active!\n\n"
                message += "✨ I'm excited to help you with your career journey!\n\n"
                message += "You now have:\n"
                message += "✅ Unlimited messages\n"
                message += "✅ Full astrology access\n"
                message += "✅ Priority responses\n\n"
                message += "Let's work on your career path together! 🚀"

            elif "health" in context.lower() or "swasthya" in context.lower():
                message += f"Thank you, {context}!\n\n"
                message += f"Your {plan_name} plan (₹{amount}) has been activated.\n\n"
                message += "✨ I'm here to help you understand your health chart!\n\n"
                message += "You now have:\n"
                message += "✅ Unlimited messages\n"
                message += "✅ Full astrology access\n"
                message += "✅ Priority responses\n\n"
                message += "Let's explore your health astrology together! 🌿"

            else:
                message += f"Thanks so much, {context}!\n\n"
                message += f"Your {plan_name} plan (₹{amount}) is now active!\n\n"
                message += "✨ Really glad we can continue our conversation!\n\n"
                message += "You now have:\n"
                message += "✅ Unlimited messages\n"
                message += "✅ Full astrology access\n"
                message += "✅ Priority responses\n\n"
                message += "Ask me anything - I'm here to help! 💪"

        return message

    def _build_hinglish_confirmation(
        self,
        astrologer_name: str,
        plan_name: str,
        amount: int,
        context: str
    ) -> str:
        """Build Hinglish confirmation message"""
        if astrologer_name == "Meera":
            message = f"🎉 *Yay! Tumhara plan activate ho gaya!* 💫\n\n"

            if "marriage" in context.lower() or "shaadi" in context.lower() or "vivah" in context.lower():
                message += f"Thank you mujhpe trust karne ke liye, {context}! 😊\n\n"
                message += f"Tumhara {plan_name} plan (₹{amount}) successfully activate ho gaya hai.\n\n"
                message += "✨ Ab main tumhari shaadi timing ka complete analysis de sakti hoon!\n\n"
                message += "Ab tumhe milega:\n"
                message += "✅ Unlimited messages\n"
                message += "✅ Full astrology access\n"
                message += "✅ Priority responses\n\n"
                message += "Jo bhi puchna hai shaadi ke baare mein, puuch lo! 💕"

            elif "career" in context.lower() or "job" in context.lower() or "naukri" in context.lower():
                message += f"Thank you mujhe choose karne ke liye, {context}! 😊\n\n"
                message += f"Tumhara {plan_name} plan (₹{amount}) activate ho gaya hai!\n\n"
                message += "✨ Main tumhare career ke liye bahut excited hoon!\n\n"
                message += "Ab tumhe milega:\n"
                message += "✅ Unlimited messages\n"
                message += "✅ Full astrology access\n"
                message += "✅ Priority responses\n\n"
                message += "Chalo tumhare career prospects detail mein dekhte hain! 🚀"

            elif "health" in context.lower() or "swasthya" in context.lower() or "roga" in context.lower():
                message += f"Thank you trust karne ke liye, {context}! 😊\n\n"
                message += f"Tumhara {plan_name} plan (₹{amount}) activate ho gaya hai.\n\n"
                message += "✨ Main tumhari health astrology detail mein samjhaungi!\n\n"
                message += "Ab tumhe milega:\n"
                message += "✅ Unlimited messages\n"
                message += "✅ Full astrology access\n"
                message += "✅ Priority responses\n\n"
                message += "Chalo health chart explore karte hain! 🌿"

            else:
                message += f"Thank you itna, {context}! 😊\n\n"
                message += f"Tumhara {plan_name} plan (₹{amount}) activate ho gaya hai!\n\n"
                message += "✨ Main bahut khush hoon ki hum baat continue kar sakte hain!\n\n"
                message += "Ab tumhe milega:\n"
                message += "✅ Unlimited messages\n"
                message += "✅ Full astrology access\n"
                message += "✅ Priority responses\n\n"
                message += "Jo bhi puchna hai, puuch lo! Main hoon na! 💕"

        else:  # Aarav
            message = f"🎉 *Badhai! Tumhara plan activate ho gaya!* 💫\n\n"

            if "marriage" in context.lower() or "shaadi" in context.lower() or "vivah" in context.lower():
                message += f"Thanks trust karne ke liye, {context}! 😊\n\n"
                message += f"Tumhara {plan_name} plan (₹{amount}) successfully activate ho gaya hai.\n\n"
                message += "✨ Ab main tumhari shaadi ka complete analysis de sakta hoon!\n\n"
                message += "Ab tumhe milega:\n"
                message += "✅ Unlimited messages\n"
                message += "✅ Full astrology access\n"
                message += "✅ Priority responses\n\n"
                message += "Chalo shaadi timing detail mein dekhte hain! 💪"

            elif "career" in context.lower() or "job" in context.lower() or "naukri" in context.lower():
                message += f"Great choice, {context}! 😊\n\n"
                message += f"Tumhara {plan_name} plan (₹{amount}) activate ho gaya hai!\n\n"
                message += "✨ Main tumhare career ke liye excited hoon!\n\n"
                message += "Ab tumhe milega:\n"
                message += "✅ Unlimited messages\n"
                message += "✅ Full astrology access\n"
                message += "✅ Priority responses\n\n"
                message += "Chalo career path explore karte hain! 🚀"

            elif "health" in context.lower() or "swasthya" in context.lower() or "roga" in context.lower():
                message += f"Thank you, {context}! 😊\n\n"
                message += f"Tumhara {plan_name} plan (₹{amount}) activate ho gaya hai.\n\n"
                message += "✨ Main tumhari health astrology samjhaunga!\n\n"
                message += "Ab tumhe milega:\n"
                message += "✅ Unlimited messages\n"
                message += "✅ Full astrology access\n"
                message += "✅ Priority responses\n\n"
                message += "Chalo health chart explore karte hain! 🌿"

            else:
                message += f"Thanks yaar, {context}! 😊\n\n"
                message += f"Tumhara {plan_name} plan (₹{amount}) activate ho gaya hai!\n\n"
                message += "✨ Bahut accha hai hum continue kar sakte hain!\n\n"
                message += "Ab tumhe milega:\n"
                message += "✅ Unlimited messages\n"
                message += "✅ Full astrology access\n"
                message += "✅ Priority responses\n\n"
                message += "Jo bhi puchna hai, puuch lena! Main hoon na! 💪"

        return message

    def _build_english_followup(
        self,
        astrologer_name: str,
        context: str
    ) -> str:
        """Build English follow-up message"""
        if astrologer_name == "Meera":
            messages = [
                "Now that you have unlimited access, what would you like to know first? 🌟",
                "I'm so happy we can continue our conversation! What's on your mind? 💕",
                "Remember, you can ask me anything now - no limits! What should we explore? ✨",
                "I'm here for you! What would you like to discuss first? 💫"
            ]
        else:  # Aarav
            messages = [
                "Now that you're all set, what would you like to know? 🌟",
                "Great to have you on board! What should we explore first? 💪",
                "Unlimited access means we can dive deep into anything! What's your question? ✨",
                "I'm here to help! What would you like to discuss? 💫"
            ]

        import random
        return random.choice(messages)

    def _build_hinglish_followup(
        self,
        astrologer_name: str,
        context: str
    ) -> str:
        """Build Hinglish follow-up message"""
        if astrologer_name == "Meera":
            messages = [
                "Ab tumhare paas unlimited access hai! Sabse pehle kya jaanna chahte ho? 🌟",
                "Main bahut khush hoon hum baat continue kar sakte hain! Dimag mein kya hai? 💕",
                "Yaad rakhna, ab tum kuch bhi puuch sakte ho - koi limit nahi! Kya dekhein? ✨",
                "Main hoon na! Kya discuss karna hai? 💫"
            ]
        else:  # Aarav
            messages = [
                "Ab tumhara plan activate ho gaya! Sabse pehle kya jaanna hai? 🌟",
                "Badhai ho! Ab hum detail mein explore kar sakte hain! Kya puuchna hai? 💪",
                "Unlimited access matlab ab hum kuch bhi depth mein dekh sakte hain! Kya hai? ✨",
                "Main hoon na madad ke liye! Kya discuss karna hai? 💫"
            ]

        import random
        return random.choice(messages)

    async def _get_user_context(self, phone: str, mongo_logger_url: str = None) -> str:
        """Get user context from recent messages"""
        try:
            if not mongo_logger_url:
                return "and I'm excited to continue our conversation"

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
                                return "and I remember you were asking about marriage"
                            elif "career" in content or "job" in content or "naukri" in content:
                                return "and I know you've been worried about career"
                            elif "health" in content or "swasthya" in content or "roga" in content:
                                return "and I understand your health concerns"

            return "and I'm excited to continue our conversation"

        except Exception as e:
            logger.warning(f"[Payment Confirmation] Error getting context: {e}")
            return "and I'm excited to continue our conversation"

    async def _send_message(self, phone: str, message: str) -> None:
        """Send message via WhatsApp API"""
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
_payment_confirmation_sender = None


def get_payment_confirmation_sender(
    phone_id: str = None,
    access_token: str = None,
    mongo_logger_url: str = None
) -> PaymentConfirmationSender:
    """
    Get or create payment confirmation sender instance

    Args:
        phone_id: WhatsApp Phone ID
        access_token: WhatsApp Access Token
        mongo_logger_url: MongoDB URL for context

    Returns:
        PaymentConfirmationSender instance
    """
    global _payment_confirmation_sender

    if _payment_confirmation_sender is None:
        if not phone_id or not access_token:
            raise ValueError("phone_id and access_token required")

        _payment_confirmation_sender = PaymentConfirmationSender(
            phone_id=phone_id,
            access_token=access_token,
            mongo_logger_url=mongo_logger_url
        )
        logger.info("[Payment Confirmation] Successfully initialized")

    return _payment_confirmation_sender
