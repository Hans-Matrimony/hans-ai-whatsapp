"""
Database Migration Script for Message-Based Paywall

This script:
1. Creates the message_limits collection with indexes
2. Adds new fields to existing users (doesn't overwrite if they exist)
3. Ensures existing users have isPaywallEnabled = false (they keep unlimited access)
4. Creates necessary indexes for performance

Run this script BEFORE deploying the paywall feature:
    python scripts/migrate_message_paywall.py
"""

import os
import sys
import logging
from datetime import datetime
from pymongo import MongoClient, ASCENDING, IndexModel

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.message_limiter import MessageLimiter

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def migrate_database():
    """
    Run database migration for message-based paywall feature
    """

    # Get MongoDB URI from environment
    mongo_uri = os.getenv('MONGO_LOGGER_URL', 'mongodb://localhost:27017')

    logger.info("🚀 Starting message-based paywall migration...")
    logger.info(f"📍 MongoDB: {mongo_uri}")

    try:
        # Connect to MongoDB
        client = MongoClient(mongo_uri)
        db = client["hans-ai-subscriptions"]

        logger.info("✅ Connected to MongoDB")

        # ============================================================
        # STEP 1: Create message_limits collection with indexes
        # ============================================================
        logger.info("\n📋 Step 1: Creating message_limits collection...")

        message_limits = db["message_limits"]

        # Create indexes for message_limits
        indexes = [
            IndexModel([("userId", ASCENDING), ("date", ASCENDING)], unique=True),
            IndexModel([("date", ASCENDING)]),
            IndexModel([("userId", ASCENDING)])
        ]

        existing_indexes = message_limits.list_indexes()
        existing_index_names = [idx.get('name') for idx in existing_indexes]

        for idx in indexes:
            idx_name = idx.document.get('name')
            if idx_name not in existing_index_names:
                message_limits.create_indexes([idx])
                logger.info(f"  ✅ Created index: {idx_name}")
            else:
                logger.info(f"  ⏭️  Index already exists: {idx_name}")

        logger.info("✅ message_limits collection ready")

        # ============================================================
        # STEP 2: Update users collection schema
        # ============================================================
        logger.info("\n📋 Step 2: Updating users collection schema...")

        users = db["users"]

        # Count total users
        total_users = users.count_documents({})
        logger.info(f"  📊 Total users in database: {total_users}")

        # Add new fields to existing users (only if they don't exist)
        # This is safe to run multiple times

        new_fields = {
            "messageCount": 0,
            "dailyFreeMessagesUsed": 0,
            "lastFreeMessageDate": None,
            "paywallShown": False,
            "paywallShownAt": None,
            "tier": "free"
        }

        # For existing users, set isPaywallEnabled = false by default
        # This means existing users keep unlimited access until we enable it
        existing_user_fields = {
            "isPaywallEnabled": False,
            "paywallEnabledDate": None
        }

        logger.info("  🔄 Updating existing user documents...")

        # Count users that need updates
        users_needing_message_count = users.count_documents({"messageCount": {"$exists": False}})
        users_needing_paywall_disabled = users.count_documents({"isPaywallEnabled": {"$exists": False}})

        logger.info(f"    - Users needing messageCount field: {users_needing_message_count}")
        logger.info(f"    - Users needing isPaywallEnabled field: {users_needing_paywall_disabled}")

        if users_needing_message_count > 0:
            result = users.update_many(
                {"messageCount": {"$exists": False}},
                {
                    "$set": new_fields
                }
            )
            logger.info(f"    ✅ Updated {result.modified_count} users with new fields")

        if users_needing_paywall_disabled > 0:
            result = users.update_many(
                {"isPaywallEnabled": {"$exists": False}},
                {
                    "$set": existing_user_fields
                }
            )
            logger.info(f"    ✅ Set isPaywallEnabled=false for {result.modified_count} existing users")

        logger.info("✅ users collection schema updated")

        # ============================================================
        # STEP 3: Create indexes for users collection
        # ============================================================
        logger.info("\n📋 Step 3: Creating indexes for users collection...")

        user_indexes = [
            IndexModel([("isPaywallEnabled", ASCENDING)]),
            IndexModel([("tier", ASCENDING)]),
            IndexModel([("messageCount", ASCENDING)]),
            IndexModel([("userId", ASCENDING)], unique=True)
        ]

        existing_user_indexes = users.list_indexes()
        existing_user_index_names = [idx.get('name') for idx in existing_user_indexes]

        for idx in user_indexes:
            idx_name = idx.document.get('name')
            if idx_name not in existing_user_index_names:
                users.create_indexes([idx])
                logger.info(f"  ✅ Created index: {idx_name}")
            else:
                logger.info(f"  ⏭️  Index already exists: {idx_name}")

        logger.info("✅ users collection indexes ready")

        # ============================================================
        # STEP 4: Verify migration
        # ============================================================
        logger.info("\n📋 Step 4: Verifying migration...")

        # Count users by paywall status
        paywall_disabled_count = users.count_documents({"isPaywallEnabled": False})
        paywall_enabled_count = users.count_documents({"isPaywallEnabled": True})

        logger.info(f"  📊 Migration summary:")
        logger.info(f"    - Total users: {total_users}")
        logger.info(f"    - Users with paywall DISABLED (existing): {paywall_disabled_count}")
        logger.info(f"    - Users with paywall ENABLED (new): {paywall_enabled_count}")

        # Check message_limits collection
        message_limits_count = message_limits.count_documents({})
        logger.info(f"    - Records in message_limits: {message_limits_count}")

        # ============================================================
        # STEP 5: Test MessageLimiter
        # ============================================================
        logger.info("\n📋 Step 5: Testing MessageLimiter...")

        try:
            message_limiter = MessageLimiter(client)
            test_user_id = "+919999999999"  # Test user ID

            logger.info(f"  🧪 Testing with user: {test_user_id}")
            limit_check = message_limiter.check_message_limit(test_user_id)

            logger.info(f"    ✅ MessageLimiter working!")
            logger.info(f"    - Allowed: {limit_check.get('allowed')}")
            logger.info(f"    - Messages Remaining: {limit_check.get('messagesRemaining')}")
            logger.info(f"    - Phase: {limit_check.get('phase')}")

        except Exception as e:
            logger.warning(f"  ⚠️  MessageLimiter test failed: {e}")
            logger.warning(f"     This is OK if the service hasn't been deployed yet")

        # ============================================================
        # MIGRATION COMPLETE
        # ============================================================
        logger.info("\n" + "="*60)
        logger.info("✅ MIGRATION COMPLETE!")
        logger.info("="*60)
        logger.info("\n📋 Next Steps:")
        logger.info("  1. Deploy the updated code to production")
        logger.info("  2. Test with a NEW phone number (should have paywall enabled)")
        logger.info("  3. Verify existing users still work (paywall disabled)")
        logger.info("  4. Monitor logs for [Message Limiter] tags")
        logger.info("\n📊 Existing Users:")
        logger.info("  - isPaywallEnabled = false (unlimited access)")
        logger.info("  - No changes to their experience")
        logger.info("\n🆕 New Users (from now):")
        logger.info("  - isPaywallEnabled = true (paywall active)")
        logger.info("  - 40 free messages, then 3-5/day")
        logger.info("\n⚠️  To enable paywall for existing users later:")
        logger.info("  from app.services.message_limiter import MessageLimiter")
        logger.info("  limiter = MessageLimiter(mongo_client)")
        logger.info("  limiter.enable_paywall_for_all_existing_users()")
        logger.info("\n")

        # Close connection
        client.close()

        return True

    except Exception as e:
        logger.error(f"❌ Migration failed: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    print("""
╔════════════════════════════════════════════════════════════╗
║   Message-Based Paywall Database Migration                  ║
║                                                            ║
║   This will:                                               ║
║   1. Create message_limits collection                     ║
║   2. Update users collection schema                        ║
║   3. Set isPaywallEnabled=false for existing users        ║
║   4. Create indexes for performance                       ║
║                                                            ║
║   Existing users will keep unlimited access!              ║
║   New users will get 40 free messages, then paywall.      ║
╚════════════════════════════════════════════════════════════╝
    """)

    response = input("\n⚠️  This will modify your database. Continue? (yes/no): ")

    if response.lower() in ["yes", "y"]:
        success = migrate_database()
        if success:
            print("\n✅ Migration completed successfully!")
            sys.exit(0)
        else:
            print("\n❌ Migration failed. Check logs above.")
            sys.exit(1)
    else:
        print("\n❌ Migration cancelled.")
        sys.exit(0)
