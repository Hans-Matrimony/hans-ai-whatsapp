"""
MongoDB User Metadata Service

Stores user birth details (name, DOB, time, place, gender) for fast lookups.
This complements Mem0 which stores conversation insights and preferences.
"""
import logging
from datetime import datetime
from typing import Optional, Dict
from pymongo import MongoClient, UpdateOne
from pymongo.errors import DuplicateKeyError

logger = logging.getLogger(__name__)

# MongoDB connection
MONGO_LOGGER_URL = None
_db = None
_users_collection = None


def init_user_metadata_service(mongo_url: str):
    """
    Initialize the user metadata service with MongoDB connection.

    Args:
        mongo_url: MongoDB connection string (must start with mongodb:// or mongodb+srv://)
    """
    global MONGO_LOGGER_URL, _db, _users_collection

    # Validate URL format
    if not mongo_url or not isinstance(mongo_url, str):
        logger.error("[User Metadata] Invalid MongoDB URL: URL is empty or not a string")
        return False

    if not mongo_url.startswith(("mongodb://", "mongodb+srv://")):
        logger.error(f"[User Metadata] Invalid MongoDB URL format: '{mongo_url}'")
        logger.error("[User Metadata] URL must start with 'mongodb://' or 'mongodb+srv://'")
        logger.error("[User Metadata] User metadata service will be disabled")
        return False

    MONGO_LOGGER_URL = mongo_url

    try:
        client = MongoClient(mongo_url)
        _db = client.hans_ai_whatsapp
        _users_collection = _db.users

        # Create indexes for faster queries
        _users_collection.create_index("phone", unique=True)
        _users_collection.create_index("created_at")
        _users_collection.create_index("gender")

        logger.info("[User Metadata] Service initialized successfully")
        logger.info(f"[User Metadata] Database: {_db.name}")
        logger.info(f"[User Metadata] Collection: {_users_collection.name}")
        return True

    except Exception as e:
        logger.error(f"[User Metadata] Failed to initialize: {e}")
        logger.error("[User Metadata] User metadata service will be disabled")
        return False


async def get_user_metadata(phone: str) -> Optional[Dict]:
    """
    Get user metadata from MongoDB (FAST lookup!).

    Args:
        phone: User's phone number (with or without +)

    Returns:
        User metadata dict or None if not found
    """
    global _users_collection, MONGO_LOGGER_URL, _db

    if not _users_collection:
        # Lazy initialization - try to initialize if not already done
        import os
        # mongo_url = os.getenv("MONGO_LOGGER_URL")
        mongo_url = "mongodb://root:w4YfCoo56EcEf1t1LVsBHxDMI6Jxm1QGCZwDHFy1Z2dp6CDirphc1WfXl782FlWt@46.225.78.212:5001/?directConnection=true"
        if mongo_url and mongo_url.startswith(("mongodb://", "mongodb+srv://")):
            logger.info("[User Metadata] Lazy initialization triggered...")
            try:
                from pymongo import MongoClient
                client = MongoClient(mongo_url)
                _db = client.hans_ai_whatsapp
                _users_collection = _db.users
                MONGO_LOGGER_URL = mongo_url
                logger.info("[User Metadata] Lazy initialization successful")
            except Exception as e:
                logger.warning(f"[User Metadata] Lazy initialization failed: {e}")
                return None
        else:
            logger.warning("[User Metadata] Service not initialized, skipping MongoDB lookup")
            return None

    try:
        # Clean phone number
        clean_phone = phone.replace("+", "").replace(" ", "")
        user_id = f"+{clean_phone}"

        # Fast lookup by phone number
        user_data = _users_collection.find_one({"phone": user_id})

        if user_data:
            logger.info(f"[User Metadata] Found user in MongoDB: {user_id}")
            # Convert ObjectId to string for JSON serialization
            if "_id" in user_data:
                user_data["_id"] = str(user_data["_id"])
            return user_data
        else:
            logger.info(f"[User Metadata] User not found in MongoDB: {user_id}")
            return None

    except Exception as e:
        logger.error(f"[User Metadata] Error fetching user: {e}")
        return None


async def save_user_metadata(
    phone: str,
    name: Optional[str] = None,
    dob: Optional[str] = None,
    tob: Optional[str] = None,
    place: Optional[str] = None,
    gender: Optional[str] = None,
    rashi: Optional[str] = None,
    lagna: Optional[str] = None
) -> bool:
    """
    Save or update user metadata in MongoDB.

    Args:
        phone: User's phone number
        name: User's name
        dob: Date of birth (YYYY-MM-DD)
        tob: Time of birth (HH:MM)
        place: Birth place
        gender: User's gender (male/female/unknown)
        rashi: Calculated Rashi (optional)
        lagna: Calculated Lagna (optional)

    Returns:
        True if successful, False otherwise
    """
    global _users_collection

    if not _users_collection:
        logger.warning("[User Metadata] Service not initialized, skipping save")
        return False

    try:
        # Clean phone number
        clean_phone = phone.replace("+", "").replace(" ", "")
        user_id = f"+{clean_phone}"

        # Build document
        user_doc = {
            "phone": user_id,
            "updated_at": datetime.utcnow(),
            "last_seen": datetime.utcnow()
        }

        # Add optional fields
        if name:
            user_doc["name"] = name
        if dob:
            user_doc["dob"] = dob
        if tob:
            user_doc["tob"] = tob
        if place:
            user_doc["place"] = place
        if gender:
            user_doc["gender"] = gender
        if rashi:
            user_doc["rashi"] = rashi
        if lagna:
            user_doc["lagna"] = lagna

        # Upsert (insert if not exists, update if exists)
        result = _users_collection.update_one(
            {"phone": user_id},
            {"$set": user_doc, "$setOnInsert": {"created_at": datetime.utcnow()}},
            upsert=True
        )

        if result.upserted_count:
            logger.info(f"[User Metadata] Created new user: {user_id}")
        else:
            logger.info(f"[User Metadata] Updated user: {user_id}")

        return True

    except Exception as e:
        logger.error(f"[User Metadata] Error saving user: {e}")
        return False


async def update_user_metadata(phone: str, updates: Dict) -> bool:
    """
    Update specific fields in user metadata.

    Args:
        phone: User's phone number
        updates: Dict of fields to update (e.g., {"gender": "male"})

    Returns:
        True if successful, False otherwise
    """
    global _users_collection

    if not _users_collection:
        logger.warning("[User Metadata] Service not initialized, skipping update")
        return False

    try:
        # Clean phone number
        clean_phone = phone.replace("+", "").replace(" ", "")
        user_id = f"+{clean_phone}"

        # Add updated_at timestamp
        updates["updated_at"] = datetime.utcnow()
        updates["last_seen"] = datetime.utcnow()

        # Update only specified fields
        result = _users_collection.update_one(
            {"phone": user_id},
            {"$set": updates}
        )

        if result.modified_count:
            logger.info(f"[User Metadata] Updated user {user_id}: {list(updates.keys())}")
            return True
        else:
            logger.warning(f"[User Metadata] User not found for update: {user_id}")
            return False

    except Exception as e:
        logger.error(f"[User Metadata] Error updating user: {e}")
        return False


async def increment_user_questions(phone: str) -> bool:
    """
    Increment the total_questions counter for a user.

    Args:
        phone: User's phone number

    Returns:
        True if successful, False otherwise
    """
    global _users_collection

    if not _users_collection:
        return False

    try:
        # Clean phone number
        clean_phone = phone.replace("+", "").replace(" ", "")
        user_id = f"+{clean_phone}"

        # Increment counter and update last_seen
        result = _users_collection.update_one(
            {"phone": user_id},
            {
                "$inc": {"total_questions": 1},
                "$set": {"last_seen": datetime.utcnow()}
            }
        )

        return result.modified_count > 0 or result.matched_count > 0

    except Exception as e:
        logger.error(f"[User Metadata] Error incrementing questions: {e}")
        return False


async def add_topic_discussed(phone: str, topic: str) -> bool:
    """
    Add a topic to the user's topics_discussed array.

    Args:
        phone: User's phone number
        topic: Topic to add (e.g., "marriage", "career")

    Returns:
        True if successful, False otherwise
    """
    global _users_collection

    if not _users_collection:
        return False

    try:
        # Clean phone number
        clean_phone = phone.replace("+", "").replace(" ", "")
        user_id = f"+{clean_phone}"

        # Add topic to array (avoid duplicates)
        result = _users_collection.update_one(
            {"phone": user_id},
            {
                "$addToSet": {"topics_discussed": topic},
                "$set": {"last_seen": datetime.utcnow()}
            }
        )

        return result.modified_count > 0 or result.matched_count > 0

    except Exception as e:
        logger.error(f"[User Metadata] Error adding topic: {e}")
        return False


async def get_all_users_count() -> int:
    """
    Get total count of users in MongoDB.

    Returns:
        Number of users
    """
    global _users_collection

    if not _users_collection:
        return 0

    try:
        return _users_collection.count_documents({})
    except Exception as e:
        logger.error(f"[User Metadata] Error counting users: {e}")
        return 0


async def get_user_stats() -> Dict:
    """
    Get user statistics from MongoDB.

    Returns:
        Dict with stats like total_users, gender_distribution, etc.
    """
    global _users_collection

    if not _users_collection:
        return {}

    try:
        total_users = _users_collection.count_documents({})

        # Gender distribution
        male_count = _users_collection.count_documents({"gender": "male"})
        female_count = _users_collection.count_documents({"gender": "female"})
        unknown_gender = total_users - male_count - female_count

        # New users in last 7 days
        from datetime import timedelta
        week_ago = datetime.utcnow() - timedelta(days=7)
        new_users_week = _users_collection.count_documents({
            "created_at": {"$gte": week_ago}
        })

        return {
            "total_users": total_users,
            "male_users": male_count,
            "female_users": female_count,
            "unknown_gender": unknown_gender,
            "new_users_last_7_days": new_users_week,
            "database": "MongoDB",
            "collection": "users"
        }

    except Exception as e:
        logger.error(f"[User Metadata] Error getting stats: {e}")
        return {}
