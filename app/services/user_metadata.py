"""
MongoDB User Metadata Service

Stores user birth details (name, DOB, time, place, gender) for fast lookups.
Uses existing AstrologyBotDB.user_profiles collection.
Falls back to Mem0 for old users who don't have data in MongoDB.

Collection: AstrologyBotDB.user_profiles
Field Mapping:
- userId (MongoDB) ← → phone (code)
- dateOfBirth (MongoDB) ← → dob (code)
- birthPlace (MongoDB) ← → place (code)
- gender (MongoDB) ← → gender (code)
- name (MongoDB) ← → name (code)
"""
import logging
from datetime import datetime
from typing import Optional, Dict
from pymongo import MongoClient, UpdateOne
from pymongo.errors import DuplicateKeyError
import httpx

logger = logging.getLogger(__name__)

# MongoDB connection
MONGO_LOGGER_URL = None
_db = None
_users_collection = None

# Mem0 configuration
MEM0_URL = "https://rg4g0gkk0wwkk4cc00g4sg0c.api.hansastro.com"
MEM0_API_KEY = None  # Set via environment variable


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
        _db = client.AstrologyBotDB  # Use existing database
        _users_collection = _db.user_profiles  # Use existing collection

        # Create indexes for faster queries
        try:
            _users_collection.create_index("userId", unique=True)
            _users_collection.create_index("createdAt")
            _users_collection.create_index("gender")
            logger.info("[User Metadata] Indexes created/verified")
        except Exception as e:
            logger.warning(f"[User Metadata] Index creation warning: {e}")

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
    Falls back to Mem0 for gender if not found in MongoDB.

    Args:
        phone: User's phone number (with or without +)

    Returns:
        User metadata dict with standardized field names, or None if not found
    """
    global _users_collection, _db

    if _users_collection is None:
        # Lazy initialization - try to initialize if not already done
        import os
        # mongo_url = os.getenv("MONGO_LOGGER_URL") or os.getenv("MONGO_METADATA_URL")
        mongo_url = "mongodb://root:w4YfCoo56EcEf1t1LVsBHxDMI6Jxm1QGCZwDHFy1Z2dp6CDirphc1WfXl782FlWt@46.225.78.212:5001/?directConnection=true"
        if mongo_url and mongo_url.startswith(("mongodb://", "mongodb+srv://")):
            logger.info("[User Metadata] Lazy initialization triggered...")
            try:
                client = MongoClient(mongo_url)
                _db = client.AstrologyBotDB
                _users_collection = _db.user_profiles
                logger.info("[User Metadata] Lazy initialization successful")
            except Exception as e:
                logger.warning(f"[User Metadata] Lazy initialization failed: {e}")
        else:
            logger.warning("[User Metadata] Service not initialized, skipping MongoDB lookup")
            return await _get_from_mem0_fallback(phone)

    try:
        # Clean phone number - normalize to match MongoDB format
        clean_phone = phone.replace("+", "").replace(" ", "")

        # Try both formats: with and without + prefix
        user_data = _users_collection.find_one({"userId": f"+{clean_phone}"})
        if not user_data:
            user_data = _users_collection.find_one({"userId": clean_phone})
        if not user_data:
            user_data = _users_collection.find_one({"phoneNumber": clean_phone})

        if user_data:
            logger.info(f"[User Metadata] Found user in MongoDB: {clean_phone}")

            # Convert ObjectId to string for JSON serialization
            if "_id" in user_data:
                user_data["_id"] = str(user_data["_id"])

            # Map MongoDB field names to code expectations
            mapped_data = {
                "phone": user_data.get("userId", user_data.get("phoneNumber")),
                "name": user_data.get("name"),
                "dob": user_data.get("dateOfBirth"),
                "tob": user_data.get("timeOfBirth"),  # Field may not exist yet
                "place": user_data.get("birthPlace"),
                "gender": user_data.get("gender"),
                "rashi": user_data.get("rashi"),
                "lagna": user_data.get("lagna"),
                # Also include original fields for reference
                "_original": user_data
            }

            # If gender is missing in MongoDB, try to get from Mem0
            if not mapped_data.get("gender") or mapped_data.get("gender") == "unknown":
                mem0_gender = await _get_gender_from_mem0(phone)
                if mem0_gender:
                    mapped_data["gender"] = mem0_gender
                    logger.info(f"[User Metadata] ✅ Got gender from Mem0: {mem0_gender}")

            return mapped_data
        else:
            logger.info(f"[User Metadata] User not found in MongoDB: {clean_phone}")
            # Try Mem0 fallback for old users
            return await _get_from_mem0_fallback(phone)

    except Exception as e:
        logger.error(f"[User Metadata] Error fetching user: {e}")
        # Try Mem0 as fallback
        return await _get_from_mem0_fallback(phone)


async def _get_from_mem0_fallback(phone: str) -> Optional[Dict]:
    """
    Fallback to Mem0 for users not in MongoDB (old users).

    Args:
        phone: User's phone number

    Returns:
        Partial user data with gender from Mem0, or None
    """
    try:
        gender = await _get_gender_from_mem0(phone)
        if gender:
            logger.info(f"[User Metadata] ✅ Found user in Mem0 with gender: {gender}")
            return {
                "phone": phone,
                "gender": gender,
                "source": "mem0"
            }
        return None
    except Exception as e:
        logger.warning(f"[User Metadata] Mem0 fallback failed: {e}")
        return None


async def _get_gender_from_mem0(phone: str) -> Optional[str]:
    """
    Fetch gender from Mem0 memories.

    Args:
        phone: User's phone number

    Returns:
        "male", "female", or None
    """
    try:
        import os
        mem0_url = os.getenv("MEM0_URL", MEM0_URL)
        mem0_api_key = os.getenv("MEM0_API_KEY")

        if not mem0_url:
            return None

        # Normalize user_id
        clean_phone = phone.replace("+", "").replace(" ", "")
        user_id = f"+{clean_phone}"

        headers = {"Content-Type": "application/json"}
        if mem0_api_key:
            headers["Authorization"] = f"Token {mem0_api_key}"

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{mem0_url}/memory/{user_id}",
                headers=headers
            )

            if response.status_code != 200:
                return None

            data = response.json()
            if not data:
                return None

            # Handle Mem0 response format: {success: true, memories: [...], count: N}
            memories = []
            if isinstance(data, list):
                memories = data
            elif isinstance(data, dict):
                # Use sequential get with OR to avoid None.get() error
                memories = data.get("memories") or data.get("results") or data.get("data", [])
                # Ensure memories is a list, not None
                if memories is None:
                    memories = []
            else:
                return None

            if not memories:
                return None

            # Search memories for gender
            import re
            for memory in memories:
                # Mem0 uses "memory" field, not "content"
                content = memory.get("memory", memory.get("content", "")).lower()
                metadata = memory.get("metadata", {})

                # Check metadata first (most reliable)
                if metadata.get("gender"):
                    gender = metadata["gender"].lower()
                    if gender in ["male", "female"]:
                        logger.info(f"[User Metadata] Gender from Mem0 metadata: {gender}")
                        return gender

                # Check content for "Gender is Male/Female" pattern
                gender_match = re.search(r'gender\s+is\s+(male|female)', content)
                if gender_match:
                    logger.info(f"[User Metadata] Gender from Mem0 content: {gender_match.group(1)}")
                    return gender_match.group(1)

                # Keyword search (fallback)
                if "gender is female" in content or "user is female" in content:
                    return "female"
                elif "gender is male" in content or "user is male" in content:
                    return "male"

            return None

    except Exception as e:
        logger.warning(f"[User Metadata] Mem0 gender fetch failed: {e}")
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

    if _users_collection is None:
        logger.warning("[User Metadata] Service not initialized, skipping save")
        return False

    try:
        # Clean phone number
        clean_phone = phone.replace("+", "").replace(" ", "")
        user_id = f"+{clean_phone}"

        # Build document with MongoDB field names
        user_doc = {
            "updatedAt": datetime.utcnow()
        }

        # Map code field names to MongoDB field names
        if name:
            user_doc["name"] = name
        if dob:
            user_doc["dateOfBirth"] = dob
        if tob:
            user_doc["timeOfBirth"] = tob  # New field, may not exist in old records
        if place:
            user_doc["birthPlace"] = place
        if gender:
            user_doc["gender"] = gender
        if rashi:
            user_doc["rashi"] = rashi
        if lagna:
            user_doc["lagna"] = lagna

        # Upsert (insert if not exists, update if exists)
        result = _users_collection.update_one(
            {"userId": user_id},
            {"$set": user_doc, "$setOnInsert": {
                "userId": user_id,
                "phoneNumber": clean_phone,
                "createdAt": datetime.utcnow(),
                "onboardingStage": 1,
                "totalMessagesSent": 0,
                "freemiumMessagesUsed": 0,
                "hasReachedPaywall": False,
                "dailyFreeMessagesRemaining": 5
            }},
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

    if _users_collection is None:
        logger.warning("[User Metadata] Service not initialized, skipping update")
        return False

    try:
        # Clean phone number
        clean_phone = phone.replace("+", "").replace(" ", "")
        user_id = f"+{clean_phone}"

        # Map code field names to MongoDB field names
        mongo_updates = {}
        field_mapping = {
            "dob": "dateOfBirth",
            "tob": "timeOfBirth",
            "place": "birthPlace"
        }

        for key, value in updates.items():
            mongo_key = field_mapping.get(key, key)
            mongo_updates[mongo_key] = value

        # Add timestamp
        mongo_updates["updatedAt"] = datetime.utcnow()

        # Update only specified fields
        result = _users_collection.update_one(
            {"userId": user_id},
            {"$set": mongo_updates}
        )

        if result.modified_count:
            logger.info(f"[User Metadata] Updated user {user_id}: {list(mongo_updates.keys())}")
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

    if _users_collection is None:
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

    if _users_collection is None:
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

    if _users_collection is None:
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

    if _users_collection is None:
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
