"""
Message Limiter Service
Handles message counting, paywall checks, and daily limits for Hans AI Astrology
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Optional
from pymongo import MongoClient, ASCENDING
import os

logger = logging.getLogger(__name__)


class MessageLimiter:
    """
    Manages message limits and paywall logic for users

    Flow:
    - Messages 1-3: Onboarding phase
    - Messages 4-40: Full free experience
    - Message 40: Soft paywall (tease + pricing)
    - After 40: 3-5 free messages/day for non-paying users
    - Premium users: Unlimited
    """

    # Constants
    FREE_MESSAGE_LIMIT = 40           # Total free messages before paywall
    DAILY_FREE_MESSAGES = 3           # Daily free messages after paywall
    SOFT_PAYWALL_MESSAGE = 40         # When to show soft paywall

    def __init__(self, mongo_client: Optional[MongoClient] = None):
        """
        Initialize MessageLimiter

        Args:
            mongo_client: MongoDB client instance (optional, will create if not provided)
        """
        if mongo_client is None:
            # Create MongoDB connection
            mongo_uri = os.getenv('MONGODB_URI', 'mongodb://localhost:27017')
            self.mongo_client = MongoClient(mongo_uri)
        else:
            self.mongo_client = mongo_client

        # Database and collections
        self.db = self.mongo_client["hans-ai-subscriptions"]
        self.users_collection = self.db["users"]
        self.message_limits_collection = self.db["message_limits"]

        # Ensure indexes exist
        self._ensure_indexes()

    def _ensure_indexes(self):
        """Create necessary indexes for performance"""
        try:
            # Index on userId and date for message_limits collection
            self.message_limits_collection.create_index(
                [("userId", ASCENDING), ("date", ASCENDING)],
                unique=True,
                background=True
            )

            # Index on isPaywallEnabled for users collection
            self.users_collection.create_index(
                [("isPaywallEnabled", ASCENDING)],
                background=True
            )

            logger.info("Message limiter indexes ensured")
        except Exception as e:
            logger.error(f"Error creating indexes: {e}")

    def check_message_limit(self, user_id: str) -> Dict:
        """
        Check if user can send message

        Args:
            user_id: User's phone number with + prefix (e.g., "+919876543210")

        Returns:
            Dict with keys:
                - allowed (bool): Can user send message?
                - messagesRemaining (int): Messages remaining
                - showPaywall (bool): Should show paywall message?
                - paywallType (str): "soft" or "hard" or None
                - message (str): Paywall message (if applicable)
                - phase (str): Current phase (onboarding, free_tier, etc.)
        """
        try:
            user = self.users_collection.find_one({"userId": user_id})

            # User doesn't exist - new user
            if not user:
                logger.info(f"New user {user_id}, allowing first message")
                return {
                    "allowed": True,
                    "messagesRemaining": self.FREE_MESSAGE_LIMIT - 1,
                    "showPaywall": False,
                    "phase": "new_user",
                    "isNewUser": True
                }

            # CRITICAL: Check if paywall is enabled for this user
            is_paywall_enabled = user.get("isPaywallEnabled", False)

            if not is_paywall_enabled:
                # Paywall not enabled - allow unlimited (existing users)
                logger.info(f"Paywall not enabled for user {user_id}, allowing unlimited")
                return {
                    "allowed": True,
                    "messagesRemaining": -1,  # unlimited
                    "showPaywall": False,
                    "phase": "unlimited",
                    "paywallDisabled": True
                }

            # Get message count
            message_count = user.get("messageCount", 0)

            # Message 1-3: Onboarding phase
            if message_count < 3:
                remaining = 3 - message_count
                logger.info(f"User {user_id} in onboarding phase, messages remaining: {remaining}")
                return {
                    "allowed": True,
                    "messagesRemaining": remaining,
                    "phase": "onboarding",
                    "showPaywall": False
                }

            # Message 4-40: Full free experience
            if message_count < self.SOFT_PAYWALL_MESSAGE:
                remaining = self.SOFT_PAYWALL_MESSAGE - message_count

                # Check if we should show soft paywall for the first time
                if message_count == self.SOFT_PAYWALL_MESSAGE - 1 and not user.get("paywallShown"):
                    logger.info(f"Showing soft paywall to user {user_id}")
                    return {
                        "allowed": True,
                        "messagesRemaining": 1,
                        "showPaywall": True,
                        "paywallType": "soft",
                        "phase": "soft_paywall_approaching",
                        "message": self._get_basic_soft_paywall_message()
                    }

                logger.info(f"User {user_id} in free tier, messages remaining: {remaining}")
                return {
                    "allowed": True,
                    "messagesRemaining": remaining,
                    "phase": "free_tier",
                    "showPaywall": False
                }

            # Message 40+: Check if paying user
            tier = user.get("tier", "free")
            if tier == "premium":
                # Paying user - unlimited
                logger.info(f"User {user_id} is premium, unlimited access")
                return {
                    "allowed": True,
                    "messagesRemaining": -1,
                    "phase": "premium",
                    "showPaywall": False
                }

            # Free user after paywall - check daily limit
            logger.info(f"User {user_id} checking daily limit")
            return self._check_daily_limit(user_id, user)

        except Exception as e:
            logger.error(f"Error checking message limit for {user_id}: {e}")
            # On error, allow message (fail open)
            return {
                "allowed": True,
                "messagesRemaining": -1,
                "showPaywall": False,
                "error": str(e)
            }

    def _check_daily_limit(self, user_id: str, user: dict) -> Dict:
        """
        Check daily message limit for free users after paywall

        Args:
            user_id: User's phone number
            user: User document from database

        Returns:
            Dict with limit check result
        """
        # Get current date in IST
        ist_timezone = timezone(datetime.now().astimezone().utcoffset().total_seconds() / 3600)
        today = datetime.now(ist_timezone).strftime("%Y-%m-%d")

        # Get or create today's message limit record
        try:
            limit_record = self.message_limits_collection.find_one({
                "userId": user_id,
                "date": today
            })

            if not limit_record:
                # First message of the day - create record
                self.message_limits_collection.insert_one({
                    "userId": user_id,
                    "date": today,
                    "messagesSent": 0,
                    "limit": self.DAILY_FREE_MESSAGES,
                    "tier": user.get("tier", "free"),
                    "createdAt": datetime.now(ist_timezone)
                })
                messages_sent_today = 0
                logger.info(f"Created daily limit record for user {user_id}")
            else:
                messages_sent_today = limit_record.get("messagesSent", 0)

            if messages_sent_today < self.DAILY_FREE_MESSAGES:
                # User hasn't hit daily limit yet
                remaining = self.DAILY_FREE_MESSAGES - messages_sent_today
                logger.info(f"User {user_id} has {remaining} daily messages remaining")
                return {
                    "allowed": True,
                    "messagesRemaining": remaining,
                    "phase": "daily_limit",
                    "showPaywall": False
                }
            else:
                # Daily limit reached
                logger.warning(f"User {user_id} has hit daily limit")
                return {
                    "allowed": False,
                    "messagesRemaining": 0,
                    "showPaywall": True,
                    "paywallType": "hard",
                    "phase": "daily_limit_reached",
                    "message": self._get_basic_hard_paywall_message()
                }

        except Exception as e:
            logger.error(f"Error checking daily limit for {user_id}: {e}")
            # On error, allow message (fail open)
            return {
                "allowed": True,
                "messagesRemaining": 1,
                "showPaywall": False,
                "error": str(e)
            }

    def increment_message_count(self, user_id: str) -> Dict:
        """
        Increment message count after sending message

        Args:
            user_id: User's phone number with + prefix

        Returns:
            Dict with updated user info:
                - messageCount (int): New total message count
                - tier (str): User's tier
        """
        try:
            user = self.users_collection.find_one({"userId": user_id})

            if not user:
                # New user - create document
                ist_timezone = timezone(datetime.now().astimezone().utcoffset().total_seconds() / 3600)
                new_user = {
                    "userId": user_id,
                    "messageCount": 1,
                    "tier": "free",
                    "isPaywallEnabled": True,  # NEW USERS get paywall enabled
                    "createdAt": datetime.now(ist_timezone),
                    "dailyFreeMessagesUsed": 0
                }
                self.users_collection.insert_one(new_user)
                logger.info(f"Created new user {user_id} with paywall enabled")
                return {"messageCount": 1, "tier": "free"}

            # Increment message count
            new_count = user.get("messageCount", 0) + 1

            # Update daily limit if paywall is enabled
            if user.get("isPaywallEnabled", False):
                ist_timezone = timezone(datetime.now().astimezone().utcoffset().total_seconds() / 3600)
                today = datetime.now(ist_timezone).strftime("%Y-%m-%d")

                self.message_limits_collection.update_one(
                    {"userId": user_id, "date": today},
                    {
                        "$inc": {"messagesSent": 1},
                        "$set": {"updatedAt": datetime.now(ist_timezone)}
                    },
                    upsert=True
                )

            # Update user
            ist_timezone = timezone(datetime.now().astimezone().utcoffset().total_seconds() / 3600)
            self.users_collection.update_one(
                {"userId": user_id},
                {
                    "$set": {
                        "messageCount": new_count,
                        "lastFreeMessageDate": datetime.now(ist_timezone).strftime("%Y-%m-%d"),
                        "updatedAt": datetime.now(ist_timezone)
                    },
                    "$setOnInsert": {
                        "tier": "free",
                        "isPaywallEnabled": True
                    }
                }
            )

            logger.info(f"Incremented message count for {user_id} to {new_count}")
            return {"messageCount": new_count, "tier": user.get("tier", "free")}

        except Exception as e:
            logger.error(f"Error incrementing message count for {user_id}: {e}")
            return {"error": str(e)}

    def mark_paywall_shown(self, user_id: str):
        """
        Mark that soft paywall has been shown to user

        Args:
            user_id: User's phone number with + prefix
        """
        try:
            ist_timezone = timezone(datetime.now().astimezone().utcoffset().total_seconds() / 3600)
            self.users_collection.update_one(
                {"userId": user_id},
                {
                    "$set": {
                        "paywallShown": True,
                        "paywallShownAt": datetime.now(ist_timezone)
                    }
                }
            )
            logger.info(f"Paywall marked as shown for user {user_id}")
        except Exception as e:
            logger.error(f"Error marking paywall shown for {user_id}: {e}")

    def enable_paywall_for_user(self, user_id: str) -> bool:
        """
        Enable paywall for a specific user

        Use this for existing users when you're ready to enable paywall for them

        Args:
            user_id: User's phone number with + prefix

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            ist_timezone = timezone(datetime.now().astimezone().utcoffset().total_seconds() / 3600)
            result = self.users_collection.update_one(
                {"userId": user_id},
                {
                    "$set": {
                        "isPaywallEnabled": True,
                        "paywallEnabledDate": datetime.now(ist_timezone)
                    }
                }
            )

            if result.modified_count > 0:
                logger.info(f"Paywall enabled for user {user_id}")
                return True
            else:
                logger.warning(f"User {user_id} not found, paywall not enabled")
                return False

        except Exception as e:
            logger.error(f"Error enabling paywall for user {user_id}: {e}")
            return False

    def enable_paywall_for_all_existing_users(self) -> int:
        """
        Enable paywall for ALL existing users who don't have it enabled yet

        Use this when ready to roll out paywall to existing users

        Returns:
            int: Number of users updated
        """
        try:
            ist_timezone = timezone(datetime.now().astimezone().utcoffset().total_seconds() / 3600)
            result = self.users_collection.update_many(
                {
                    "isPaywallEnabled": {"$exists": False},
                    "tier": {"$ne": "premium"}
                },
                {
                    "$set": {
                        "isPaywallEnabled": True,
                        "paywallEnabledDate": datetime.now(ist_timezone)
                    }
                }
            )

            count = result.modified_count
            logger.info(f"Paywall enabled for {count} existing users")
            return count

        except Exception as e:
            logger.error(f"Error enabling paywall for existing users: {e}")
            return 0

    def get_user_stats(self, user_id: str) -> Dict:
        """
        Get user's message statistics

        Args:
            user_id: User's phone number with + prefix

        Returns:
            Dict with user stats
        """
        try:
            user = self.users_collection.find_one({"userId": user_id})

            if not user:
                return {"error": "User not found"}

            ist_timezone = timezone(datetime.now().astimezone().utcoffset().total_seconds() / 3600)
            today = datetime.now(ist_timezone).strftime("%Y-%m-%d")

            limit_record = self.message_limits_collection.find_one({
                "userId": user_id,
                "date": today
            })

            return {
                "userId": user_id,
                "messageCount": user.get("messageCount", 0),
                "tier": user.get("tier", "free"),
                "isPaywallEnabled": user.get("isPaywallEnabled", False),
                "paywallShown": user.get("paywallShown", False),
                "dailyMessagesUsedToday": limit_record.get("messagesSent", 0) if limit_record else 0,
                "dailyMessagesRemaining": max(0, self.DAILY_FREE_MESSAGES - (limit_record.get("messagesSent", 0) if limit_record else 0)),
                "phase": self._get_user_phase(user)
            }

        except Exception as e:
            logger.error(f"Error getting stats for user {user_id}: {e}")
            return {"error": str(e)}

    def _get_user_phase(self, user: dict) -> str:
        """Get user's current phase"""
        if not user.get("isPaywallEnabled", False):
            return "unlimited"

        message_count = user.get("messageCount", 0)

        if message_count < 3:
            return "onboarding"
        elif message_count < self.SOFT_PAYWALL_MESSAGE:
            return "free_tier"
        elif user.get("tier") == "premium":
            return "premium"
        else:
            return "post_paywall"


    def _get_basic_soft_paywall_message(self) -> str:
        """Get basic soft paywall message (fallback if AI fails)"""
        return "Aapke free messages khatam ho gaye hain. Niche Pay Now button par click karke ₹9 mein recharge karein."

    def _get_basic_hard_paywall_message(self) -> str:
        """Get basic hard paywall message (fallback if AI fails)"""
        return "Aapki aaj ki daily limit khatam ho gayi hai. Niche Pay Now button par click karke ₹9 mein 1 day pass lein."

