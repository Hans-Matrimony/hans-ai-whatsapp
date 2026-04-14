"""
MongoDB User Metadata Service (HTTP API Client)

Stores user birth details (name, DOB, time, place, gender) for fast lookups.
Uses the Node.js openclaw_mongo_logger API instead of direct pymongo.
Falls back to Mem0 for old users who don't have data in MongoDB.
"""
import logging
from datetime import datetime
from typing import Optional, Dict
import httpx
import os
import re

logger = logging.getLogger(__name__)

# Note: We now talk to MongoDB via the openclaw_mongo_logger HTTP API.
MONGO_LOGGER_URL = None

# Mem0 configuration
MEM0_URL = "https://rg4g0gkk0wwkk4cc00g4sg0c.api.hansastro.com"
MEM0_API_KEY = None  # Set via environment variable


def init_user_metadata_service(mongo_url: str):
    """
    Initialize the user metadata service with the logger API URL.

    Args:
        mongo_url: The base HTTP URL of the mongo logger service
    """
    global MONGO_LOGGER_URL

    if not mongo_url or not isinstance(mongo_url, str):
        logger.error("[User Metadata] Invalid API URL")
        return False
        
    # Standardize url for httpx requests 
    MONGO_LOGGER_URL = mongo_url.rstrip("/")
    logger.info(f"[User Metadata] API Client initialized successfully using {MONGO_LOGGER_URL}")
    return True


async def get_user_metadata(phone: str) -> Optional[Dict]:
    """
    Get user metadata from the Mongo API Dashboard (FAST lookup!).
    Falls back to Mem0 for gender if not found in MongoDB via the API.
    """
    global MONGO_LOGGER_URL

    if not MONGO_LOGGER_URL:
        logger.warning("[User Metadata] Service API URL not initialized, falling back to Mem0")
        return await _get_from_mem0_fallback(phone)

    try:
        clean_phone = phone.replace("+", "").replace(" ", "")
        user_id = f"+{clean_phone}"

        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{MONGO_LOGGER_URL}/metadata/{user_id}")
            
            if response.status_code == 200:
                user_data = response.json()
            else:
                user_data = None

        if user_data:
            logger.info(f"[User Metadata] Found user via API: {user_id}")

            # Map MongoDB field names to code expectations
            mapped_data = {
                "phone": user_data.get("userId", user_data.get("phoneNumber")),
                "name": user_data.get("name"),
                "dob": user_data.get("dateOfBirth"),
                "tob": user_data.get("timeOfBirth"), 
                "place": user_data.get("birthPlace"),
                "gender": user_data.get("gender"),
                "rashi": user_data.get("rashi"),
                "lagna": user_data.get("lagna"),
                "_original": user_data
            }

            # If any birth data is missing in MongoDB, try to fill from Mem0
            if not all([mapped_data.get("dob"), mapped_data.get("tob"), mapped_data.get("place"), mapped_data.get("gender")]):
                logger.info(f"[User Metadata] Gaps found in MongoDB data for {user_id}, checking Mem0...")
                mem0_data = await _get_all_info_from_mem0(phone)
                if mem0_data:
                    # Fill only missing fields
                    for key in ["dob", "tob", "place", "gender"]:
                        if not mapped_data.get(key) or mapped_data.get(key) == "unknown":
                            if mem0_data.get(key):
                                mapped_data[key] = mem0_data[key]
                                logger.info(f"[User Metadata] ✅ Filled {key} from Mem0: {mem0_data[key]}")

            return mapped_data
        else:
            logger.info(f"[User Metadata] User not found via API: {user_id}")
            return await _get_from_mem0_fallback(phone)

    except Exception as e:
        logger.error(f"[User Metadata] Error fetching user via API: {e}")
        return await _get_from_mem0_fallback(phone)


async def _get_from_mem0_fallback(phone: str) -> Optional[Dict]:
    """Fallback to Mem0 for users not in MongoDB (old users)."""
    try:
        mem0_data = await _get_all_info_from_mem0(phone)
        if mem0_data:
            logger.info(f"[User Metadata] ✅ Found user in Mem0 with data: {list(mem0_data.keys())}")
            mem0_data["phone"] = phone
            mem0_data["source"] = "mem0"
            return mem0_data
        return None
    except Exception as e:
        logger.warning(f"[User Metadata] Mem0 fallback failed: {e}")
        return None


async def _get_gender_from_mem0(phone: str) -> Optional[str]:
    """Fetch gender from Mem0 memories."""
    try:
        data = await _get_all_info_from_mem0(phone)
        return data.get("gender") if data else None
    except Exception as e:
        logger.warning(f"[User Metadata] Mem0 gender fetch failed: {e}")
        return None


async def _get_all_info_from_mem0(phone: str) -> Optional[Dict]:
    """Fetch and parse all available info (gender, dob, tob, place) from Mem0."""
    try:
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

            memories = []
            if isinstance(data, list):
                memories = data
            elif isinstance(data, dict):
                memories = data.get("memories") or data.get("results") or data.get("data", [])
                if memories is None: memories = []
            else:
                return None

            if not memories:
                return None

            info = {}

            dob_pattern = r'(?:dob|date\s+of\s+birth|birth\s+date|born\s+on)(?:\s+of\s+birth)?(?:\s+is|\s+on)?[:\s=]+([0-9]{1,4}[-/][A-Za-z0-9/]+[-/][0-9]{1,4})'
            time_pattern = r'(?:tob|time\s+of\s+birth|birth\s+time|born\s+at)(?:\s+of\s+birth)?(?:\s+is|\s+at)?[:\s=]+([0-9]{1,2}[:.][0-9]{2}(?::[0-9]{2})?(?:\s*[ap]m)?)'
            place_pattern = r'(?:place|birth\s+place|city|sthaan|born\s+in)(?:\s+of\s+birth|\s+is)?[:\s=]+([a-z\s]{2,30})(?:,|\.|\n|$)'

            for memory in memories:
                if memory is None or not isinstance(memory, dict):
                    continue

                raw_content = memory.get("memory") or memory.get("content") or ""
                content = raw_content.lower()
                metadata = memory.get("metadata") or {}

                # 1. Check Metadata
                for field in ["gender", "dob", "tob", "place"]:
                    if metadata.get(field) and not info.get(field):
                        info[field] = metadata[field].lower() if field == "gender" else metadata[field]

                # 2. Check Content
                if not info.get("gender"):
                    gender_match = re.search(r'gender\s+is\s+(male|female)', content)
                    if gender_match: info["gender"] = gender_match.group(1)
                    elif "gender is female" in content or "user is female" in content: info["gender"] = "female"
                    elif "gender is male" in content or "user is male" in content: info["gender"] = "male"

                if not info.get("dob"):
                    dob_match = re.search(dob_pattern, raw_content, re.IGNORECASE)
                    if dob_match: info["dob"] = dob_match.group(1).strip()

                if not info.get("tob"):
                    time_match = re.search(time_pattern, raw_content, re.IGNORECASE)
                    if time_match: info["tob"] = time_match.group(1).strip()

                if not info.get("place"):
                    place_match = re.search(place_pattern, raw_content, re.IGNORECASE)
                    if place_match: info["place"] = place_match.group(1).strip()

            # 3. Post-Processing Cleanup
            if info.get("place"):
                info["place"] = re.sub(r'^(is|in|of\s+birth\s+is)\s+', '', info["place"], flags=re.IGNORECASE).strip()
                info["place"] = re.sub(r'^(of\s+Birth\s+is)\s+', '', info["place"], flags=re.IGNORECASE).strip()
            
            return info if info else None

    except Exception as e:
        logger.warning(f"[User Metadata] Mem0 info fetch failed: {e}")
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
    Save or update user metadata.

    Saves to BOTH:
    1. MongoDB user_metadata (NEW - for fast lookup)
    2. Mem0 (EXISTING - keeps working as before!)

    This way existing functionality is NOT hindered at all.
    """
    global MONGO_LOGGER_URL, MEM0_URL, MEM0_API_KEY

    clean_phone = phone.replace("+", "").replace(" ", "")
    user_id = f"+{clean_phone}"

    success_count = 0

    # Step 1: Save to MongoDB user_metadata (NEW - for fast lookups)
    if MONGO_LOGGER_URL:
        try:
            payload = {
                "userId": user_id,
                "phoneNumber": clean_phone
            }

            if name: payload["name"] = name
            if dob: payload["dateOfBirth"] = dob
            if tob: payload["timeOfBirth"] = tob
            if place: payload["birthPlace"] = place
            if gender: payload["gender"] = gender
            if rashi: payload["rashi"] = rashi
            if lagna: payload["lagna"] = lagna

            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(f"{MONGO_LOGGER_URL}/metadata", json=payload)
                if response.status_code == 200:
                    logger.info(f"[User Metadata] Successfully saved to MongoDB for: {user_id}")
                    success_count += 1
                else:
                    logger.warning(f"[User Metadata] MongoDB API failed: {response.text}")

        except Exception as e:
            logger.warning(f"[User Metadata] Error saving to MongoDB (continuing): {e}")

    # Step 2: ALSO save to Mem0 (EXISTING functionality - keep working!)
    # This ensures Mem0 continues to work exactly as before
    if dob or tob or place or gender:
        try:
            mem0_url = os.getenv("MEM0_URL", MEM0_URL)
            if not mem0_url:
                logger.debug("[User Metadata] Mem0 URL not configured")
            else:
                # Build memory text
                memory_parts = []
                if name: memory_parts.append(f"Name: {name}")
                if dob: memory_parts.append(f"DOB: {dob}")
                if tob: memory_parts.append(f"TOB: {tob}")
                if place: memory_parts.append(f"Place: {place}")
                if gender: memory_parts.append(f"Gender: {gender}")

                memory_text = " | ".join(memory_parts)

                headers = {"Content-Type": "application/json"}
                if MEM0_API_KEY:
                    headers["Authorization"] = f"Token {MEM0_API_KEY}"

                async with httpx.AsyncClient(timeout=10.0) as client:
                    # Use upsert to avoid duplicates
                    search_payload = {
                        "query": "birth details",
                        "user_id": user_id,
                        "limit": 5
                    }

                    # Search for existing birth data memories
                    search_response = await client.post(
                        f"{mem0_url}/memory/search",
                        headers=headers,
                        json=search_payload
                    )

                    # Delete existing birth data memories (for upsert)
                    if search_response.status_code == 200:
                        search_data = search_response.json()
                        results = search_data.get("results") or search_data.get("memories") or []

                        for memory in results:
                            mem_id = memory.get("id") or memory.get("memory_id")
                            if mem_id:
                                try:
                                    await client.delete(
                                        f"{mem0_url}/memory/{mem_id}",
                                        headers=headers,
                                        timeout=5.0
                                    )
                                except:
                                    pass  # Ignore delete failures, continue

                    # Add new memory
                    add_payload = {
                        "user_id": user_id,
                        "memory": memory_text,
                        "metadata": {
                            "source": "whatsapp_service",
                            "dob": dob or "",
                            "tob": tob or "",
                            "place": place or "",
                            "gender": gender or "",
                            "name": name or ""
                        }
                    }

                    add_response = await client.post(
                        f"{mem0_url}/memory",
                        headers=headers,
                        json=add_payload
                    )

                    if add_response.status_code in [200, 201]:
                        logger.info(f"[User Metadata] Successfully saved to Mem0 for: {user_id}")
                        success_count += 1
                    else:
                        logger.warning(f"[User Metadata] Mem0 save failed (non-critical)")

        except Exception as e:
            logger.warning(f"[User Metadata] Error saving to Mem0 (non-critical): {e}")

    # Return success if at least one worked
    return success_count > 0


async def update_user_metadata(phone: str, updates: Dict) -> bool:
    """Update specific fields via the logger API."""
    global MONGO_LOGGER_URL

    if not MONGO_LOGGER_URL:
        return False

    try:
        clean_phone = phone.replace("+", "").replace(" ", "")
        user_id = f"+{clean_phone}"

        payload = {
            "userId": user_id,
            "phoneNumber": clean_phone
        }

        field_mapping = {
            "dob": "dateOfBirth",
            "tob": "timeOfBirth",
            "place": "birthPlace"
        }

        for key, value in updates.items():
            mongo_key = field_mapping.get(key, key)
            payload[mongo_key] = value

        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(f"{MONGO_LOGGER_URL}/metadata", json=payload)
            if response.status_code == 200:
                logger.info(f"[User Metadata] Successfully updated via API for: {user_id}")
                return True
            return False

    except Exception as e:
        logger.error(f"[User Metadata] Error updating user via API: {e}")
        return False


async def increment_user_questions(phone: str) -> bool:
    """Increment the total_questions counter via the API."""
    global MONGO_LOGGER_URL
    if not MONGO_LOGGER_URL: return False

    try:
        clean_phone = phone.replace("+", "").replace(" ", "")
        user_id = f"+{clean_phone}"

        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(f"{MONGO_LOGGER_URL}/metadata/increment-questions", json={"userId": user_id})
            return response.status_code == 200
            
    except Exception as e:
        logger.error(f"[User Metadata] Error incrementing questions via API: {e}")
        return False


async def add_topic_discussed(phone: str, topic: str) -> bool:
    """Add a topic to the user's tracked topics via the API."""
    global MONGO_LOGGER_URL
    if not MONGO_LOGGER_URL: return False

    try:
        clean_phone = phone.replace("+", "").replace(" ", "")
        user_id = f"+{clean_phone}"

        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(f"{MONGO_LOGGER_URL}/metadata/topic", json={"userId": user_id, "topic": topic})
            return response.status_code == 200
            
    except Exception as e:
        logger.error(f"[User Metadata] Error adding topic via API: {e}")
        return False

        
async def get_all_users_count() -> int:
    """Get total count of users via API."""
    global MONGO_LOGGER_URL
    if not MONGO_LOGGER_URL: return 0

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{MONGO_LOGGER_URL}/metadata-stats")
            if response.status_code == 200:
                return response.json().get("total_users", 0)
        return 0
    except Exception as e:
        return 0

async def get_user_stats() -> Dict:
    """Get user statistics via API."""
    global MONGO_LOGGER_URL
    if not MONGO_LOGGER_URL: return {}
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{MONGO_LOGGER_URL}/metadata-stats")
            if response.status_code == 200:
                data = response.json()
                data["database"] = "MongoDB via API"
                data["collection"] = "user_profiles"
                return data
            return {}
    except Exception as e:
        logger.error(f"[User Metadata] Error getting stats via API: {e}")
        return {}
