"""
Update Subscription Plans in Database

This script will:
1. Deactivate all existing plans
2. Create new plans with updated pricing:
   - Monthly: ₹299/month
   - Yearly: ₹199/year (BEST VALUE!)

Usage:
    python scripts/update_plans.py
"""

import os
import sys
import logging
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from pymongo import MongoClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def update_plans():
    """
    Update subscription plans in database
    """

    # Get MongoDB URI from environment
    mongo_uri = os.getenv('MONGO_LOGGER_URL', 'mongodb://localhost:27017')

    logger.info("🚀 Starting plan update...")
    logger.info(f"📍 MongoDB: {mongo_uri}")

    try:
        # Connect to MongoDB
        client = MongoClient(mongo_uri)
        db = client["hans-ai-subscriptions"]
        plans_collection = db["plans"]

        logger.info("✅ Connected to MongoDB")

        # ============================================================
        # STEP 1: Deactivate all existing plans
        # ============================================================
        logger.info("\n📋 Step 1: Deactivating existing plans...")

        existing_plans = list(plans_collection.find({"isActive": True}))
        logger.info(f"  📊 Found {len(existing_plans)} active plans")

        if existing_plans:
            result = plans_collection.update_many(
                {"isActive": True},
                {"$set": {"isActive": False}}
            )
            logger.info(f"  ✅ Deactivated {result.modified_count} plans")

            # Show what was deactivated
            for plan in existing_plans:
                price_rupees = plan.get("price", 0) / 100
                logger.info(f"     - {plan.get('name')}: ₹{price_rupees:.2f}/{plan.get('durationDays')} days")
        else:
            logger.info(f"  ℹ️  No existing plans to deactivate")

        # ============================================================
        # STEP 2: Create new plans
        # ============================================================
        logger.info("\n📋 Step 2: Creating new plans...")

        # Monthly Plan: ₹299/month
        monthly_plan = {
            "planId": "monthly_299",
            "name": "Monthly Basic",
            "description": "Unlimited messages for 1 month",
            "price": 29900,  # ₹299 in paise
            "currency": "INR",
            "durationDays": 30,
            "features": [
                "Unlimited messages",
                "Detailed kundli",
                "Personalized predictions",
                "Career guidance",
                "Relationship advice"
            ],
            "isActive": True,
            "createdAt": datetime.utcnow()
        }

        # Yearly Plan: ₹199/year
        yearly_plan = {
            "planId": "yearly_199",
            "name": "Yearly Premium",
            "description": "Unlimited messages for 1 year - BEST VALUE!",
            "price": 19900,  # ₹199 for the YEAR (not per month!)
            "currency": "INR",
            "durationDays": 365,
            "features": [
                "Unlimited messages",
                "Detailed kundli",
                "Personalized predictions",
                "Career guidance",
                "Relationship advice",
                "Priority support",
                "Vastu consultation"
            ],
            "isActive": True,
            "createdAt": datetime.utcnow()
        }

        # Insert plans (check if they already exist first)
        existing_monthly = plans_collection.find_one({"planId": "monthly_299"})
        if existing_monthly:
            logger.info(f"  ⏭️  Monthly plan already exists, updating...")
            plans_collection.update_one(
                {"planId": "monthly_299"},
                {"$set": monthly_plan}
            )
        else:
            logger.info(f"  ➕ Creating monthly plan: ₹299/month")
            plans_collection.insert_one(monthly_plan)

        existing_yearly = plans_collection.find_one({"planId": "yearly_199"})
        if existing_yearly:
            logger.info(f"  ⏭️  Yearly plan already exists, updating...")
            plans_collection.update_one(
                {"planId": "yearly_199"},
                {"$set": yearly_plan}
            )
        else:
            logger.info(f"  ➕ Creating yearly plan: ₹199/year")
            plans_collection.insert_one(yearly_plan)

        logger.info("✅ New plans created/updated")

        # ============================================================
        # STEP 3: Verify the changes
        # ============================================================
        logger.info("\n📋 Step 3: Verifying changes...")

        active_plans = list(plans_collection.find({"isActive": True}))
        logger.info(f"  📊 Active plans: {len(active_plans)}")

        for plan in active_plans:
            price_rupees = plan.get("price", 0) / 100
            duration = plan.get("durationDays", 0)

            if duration == 365:
                price_display = f"₹{price_rupees:.2f}/year"
            else:
                price_display = f"₹{price_rupees:.2f}/month"

            logger.info(f"\n  ✅ {plan.get('planId')}:")
            logger.info(f"     Name: {plan.get('name')}")
            logger.info(f"     Price: {price_display}")
            logger.info(f"     Duration: {duration} days")
            logger.info(f"     Features: {', '.join(plan.get('features', [])[:3])}")

        # ============================================================
        # DONE
        # ============================================================
        logger.info("\n" + "="*60)
        logger.info("✅ PLAN UPDATE COMPLETE!")
        logger.info("="*60)
        logger.info("\n📋 New Pricing:")
        logger.info("  • Monthly:  ₹299/month")
        logger.info("  • Yearly:   ₹199/year (BEST VALUE!)")
        logger.info("\n💰 Savings with yearly plan:")
        logger.info("  • Monthly: ₹299 × 12 = ₹3,588/year")
        logger.info("  • Yearly:  ₹199 (you save ₹3,389!)")
        logger.info("\n🎯 Next Steps:")
        logger.info("  1. Test payment flow with new plans")
        logger.info("  2. Verify WhatsApp shows correct pricing")
        logger.info("  3. Deploy message paywall changes")
        logger.info("\n")

        # Close connection
        client.close()

        return True

    except Exception as e:
        logger.error(f"❌ Plan update failed: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    print("""
╔════════════════════════════════════════════════════════════╗
║   Update Subscription Plans                                 ║
║                                                            ║
║   This will:                                               ║
║   1. Deactivate all existing plans                         ║
║   2. Create new plans:                                     ║
║      • Monthly: ₹299/month                                  ║
║      • Yearly: ₹199/year (BEST VALUE!)                      ║
║                                                            ║
║   Old plans will be preserved but deactivated.             ║
╚════════════════════════════════════════════════════════════╝
    """)

    response = input("\n⚠️  This will modify your subscription plans. Continue? (yes/no): ")

    if response.lower() in ["yes", "y"]:
        success = update_plans()
        if success:
            print("\n✅ Plan update completed successfully!")
            sys.exit(0)
        else:
            print("\n❌ Plan update failed. Check logs above.")
            sys.exit(1)
    else:
        print("\n❌ Plan update cancelled.")
        sys.exit(0)
