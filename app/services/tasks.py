"""
Celery tasks for asynchronous message processing
"""
import os
import re
import sys
import logging
import base64
import tempfile
from datetime import datetime
from typing import Optional, Tuple, List
from pathlib import Path

import httpx
from app.services.celery_app import celery_app

# Add skills directory to path for audio processor
skills_path = os.path.join(os.path.dirname(__file__), '../../skills')
if skills_path not in sys.path:
    sys.path.insert(0, skills_path)

logger = logging.getLogger(__name__)

# Configuration from environment
OPENCLAW_URL = os.getenv("OPENCLAW_URL")
OPENCLAW_GATEWAY_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN")
MONGO_LOGGER_URL = os.getenv("MONGO_LOGGER_URL")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
FB_API_URL = "https://graph.facebook.com/v18.0"
MEM0_URL = os.getenv("MEM0_URL", "https://rg4g0gkk0wwkk4cc00g4sg0c.api.hansastro.com")

# Subscription Service Configuration
SUBSCRIPTIONS_URL = os.getenv("SUBSCRIPTIONS_URL")
SUBSCRIPTION_TEST_NUMBER = os.getenv("SUBSCRIPTION_TEST_NUMBER", "9760347653")

# Testing mode: Only send proactive nudges to this number (None = send to all users)
PROACTIVE_NUDGE_TEST_NUMBER = os.getenv("PROACTIVE_NUDGE_TEST_NUMBER", "+919760347653")


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_message_task(self, phone: str, message: str, message_id: str, message_type: str = "text", media_info: dict = None):
    """
    Process incoming WhatsApp message asynchronously.
    Retries up to 3 times with 60 second delay on failure.
    """
    try:
        logger.info(f"[Celery] Processing {message_type} from {phone}: {message[:50]}...")

        # Run async code in sync context
        import asyncio
        result = asyncio.run(_process_message_async(phone, message, message_id, message_type, media_info))
        return result

    except Exception as e:
        logger.error(f"[Celery] Task failed: {e}")
        # Retry with exponential backoff
        raise self.retry(exc=e, countdown=2 ** self.request.retries)


async def _download_whatsapp_media(media_id: str) -> dict:
    """Download media file from WhatsApp servers.
    Returns dict with url and mime_type, or None if failed.
    """
    if not WHATSAPP_ACCESS_TOKEN:
        logger.warning("Cannot download media: no access token")
        return None

    url = f"{FB_API_URL}/{media_id}"

    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # First get media info (which contains the download URL)
            response = await client.get(url, headers=headers)

            if response.status_code != 200:
                logger.error(f"Failed to get media info: {response.text}")
                return None

            media_data = response.json()
            return {
                "url": media_data.get("url"),
                "mime_type": media_data.get("mime_type"),
                "file_size": media_data.get("file_size"),
                "media_type": media_data.get("media_type")  # image, audio, video, document
            }

    except Exception as e:
        logger.error(f"Error downloading media: {e}")
        return None


async def _get_plans_message() -> str:
    """
    Fetch active plans from subscriptions service and format for WhatsApp.
    Returns formatted message with plan options.
    """
    if not SUBSCRIPTIONS_URL:
        return "Subscription service not configured. Please contact support."

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{SUBSCRIPTIONS_URL}/plans?active_only=true"
            )
            if response.status_code == 200:
                data = response.json()
                plans = data.get("plans", [])

                if not plans:
                    return "No plans available. Please contact support."

                # Format plans for WhatsApp
                message = "*💫 Choose Your Subscription Plan:*\n\n"

                for idx, plan in enumerate(plans, 1):
                    price_rupees = plan.get("price", 0) / 100  # Convert paise to rupees
                    duration = plan.get("durationDays", 30)

                    message += f"*{idx}. {plan.get('name', 'Plan')}*\n"
                    message += f"💰 ₹{price_rupees}/{duration} days\n"

                    # Add features if available
                    features = plan.get("features", [])
                    if features and isinstance(features, list):
                        for feature in features[:3]:  # Max 3 features
                            message += f"   ✓ {feature}\n"
                    message += "\n"

                message += "Reply with plan number (1, 2, 3...) to get payment link."
                return message
            else:
                logger.error(f"Failed to fetch plans: {response.status_code}")
                return "Unable to fetch plans. Please try again later."
    except Exception as e:
        logger.error(f"Error fetching plans: {e}")
        return "Unable to fetch plans. Please contact support."


async def _generate_payment_link(user_id: str, plan_number: int) -> str:
    """
    Generate Razorpay payment link for selected plan.
    Calls subscriptions service which creates Razorpay Payment Link.
    Returns direct Razorpay payment URL - no custom page needed!
    """
    if not SUBSCRIPTIONS_URL:
        logger.error("SUBSCRIPTIONS_URL not configured")
        return None

    try:
        # First, fetch all plans to find the selected one
        async with httpx.AsyncClient(timeout=10.0) as client:
            plans_response = await client.get(
                f"{SUBSCRIPTIONS_URL}/plans?active_only=true"
            )
            if plans_response.status_code != 200:
                return None

            plans_data = plans_response.json()
            plans = plans_data.get("plans", [])

            # Validate plan number
            if plan_number < 1 or plan_number > len(plans):
                return None

            selected_plan = plans[plan_number - 1]
            plan_id = selected_plan.get("planId")

            # Call subscriptions service to create Razorpay Payment Link
            # This endpoint will use Razorpay Payment Links API
            payment_link_response = await client.post(
                f"{SUBSCRIPTIONS_URL}/payments/create-payment-link",
                json={
                    "userId": user_id,
                    "planId": plan_id,
                    "currency": "INR"
                },
                timeout=30.0
            )

            if payment_link_response.status_code == 200:
                link_data = payment_link_response.json()
                razorpay_link = link_data.get("short_url") or link_data.get("payment_link")

                if razorpay_link:
                    logger.info(f"Generated Razorpay payment link for plan {plan_number}: {razorpay_link}")
                    return razorpay_link
                else:
                    logger.error("No payment_link in response")
                    return None
            else:
                logger.error(f"Failed to create payment link: {payment_link_response.status_code}")
                return None

    except Exception as e:
        logger.error(f"Error generating payment link: {e}")
        return None


async def _generate_trial_activation_link(user_id: str) -> str:
    """
    Generate ₹1 trial activation payment link.
    Creates a Razorpay Payment Link for the trial_activation plan.
    Returns direct Razorpay payment URL.
    """
    if not SUBSCRIPTIONS_URL:
        logger.error("SUBSCRIPTIONS_URL not configured")
        return None

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Call subscriptions service to create Razorpay Payment Link for trial activation
            payment_link_response = await client.post(
                f"{SUBSCRIPTIONS_URL}/payments/create-payment-link",
                json={
                    "userId": user_id,
                    "planId": "trial_activation",
                    "currency": "INR"
                }
            )

            if payment_link_response.status_code == 200:
                link_data = payment_link_response.json()
                razorpay_link = link_data.get("short_url") or link_data.get("payment_link")

                if razorpay_link:
                    logger.info(f"Generated ₹1 trial activation link for {user_id}: {razorpay_link}")
                    return razorpay_link
                else:
                    logger.error("No payment_link in trial activation response")
                    return None
            else:
                logger.error(f"Failed to create trial activation link: {payment_link_response.status_code}")
                return None

    except Exception as e:
        logger.error(f"Error generating trial activation link: {e}")
        return None


async def _check_subscription_access(phone: str) -> dict:
    """
    Check if user has valid subscription (trial or active).
    Returns: dict with 'access' field (trial, active, trial_ending_soon, no_access)
    Only enforces subscription for SUBSCRIPTION_TEST_NUMBER (testing mode).
    """
    # Skip subscription check if not configured
    if not SUBSCRIPTIONS_URL:
        logger.debug("[Subscription] SUBSCRIPTIONS_URL not configured, skipping check")
        return {"access": "trial", "skip_reason": "no_url"}

    # Skip subscription check if not the test number (testing mode)
    clean_phone = phone.replace("+", "").replace(" ", "")
    if clean_phone != SUBSCRIPTION_TEST_NUMBER:
        logger.debug(f"[Subscription] Not test number ({clean_phone} != {SUBSCRIPTION_TEST_NUMBER}), skipping check")
        return {"access": "trial", "skip_reason": "not_test_number"}

    # Check subscription status
    user_id = f"+{clean_phone}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{SUBSCRIPTIONS_URL}/users/{user_id}/access-check"
            )
            if response.status_code == 200:
                access_data = response.json()
                logger.info(f"[Subscription] Access check for {user_id}: {access_data.get('access')}")
                return access_data
            else:
                logger.warning(f"[Subscription] Access check failed: {response.status_code}")
                # On API failure, allow access (fail-open)
                return {"access": "trial", "skip_reason": "api_error"}
    except Exception as e:
        logger.error(f"[Subscription] Error checking access: {e}")
        # On exception, allow access (fail-open)
        return {"access": "trial", "skip_reason": "exception"}


async def _download_whatsapp_media_file(media_id: str) -> dict:
    """Download the actual media file content from WhatsApp servers.
    Returns dict with base64 data, mime_type, and file extension.
    This is needed because WhatsApp media URLs require authentication.
    """
    if not WHATSAPP_ACCESS_TOKEN:
        logger.warning("Cannot download media file: no access token")
        return None

    # First get media info to get the download URL
    info_url = f"{FB_API_URL}/{media_id}"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Get media info
            info_response = await client.get(info_url, headers=headers)
            if info_response.status_code != 200:
                logger.error(f"Failed to get media info: {info_response.text}")
                return None

            media_data = info_response.json()
            download_url = media_data.get("url")
            mime_type = media_data.get("mime_type", "")

            if not download_url:
                logger.error("No download URL in media response")
                return None

            # Download the actual file using the URL (still needs auth)
            file_response = await client.get(download_url, headers=headers)
            if file_response.status_code != 200:
                logger.error(f"Failed to download media file: {file_response.status_code}")
                return None

            # Convert to base64
            file_content = file_response.content
            base64_data = base64.b64encode(file_content).decode('utf-8')

            # Determine file extension from mime type
            extension_map = {
                "image/jpeg": ".jpg",
                "image/png": ".png",
                "image/webp": ".webp",
                "image/gif": ".gif",
                "audio/mpeg": ".mp3",
                "audio/mp4": ".m4a",
                "audio/amr": ".amr",
                "audio/ogg": ".ogg",
                "video/mp4": ".mp4",
                "video/3gpp": ".3gp",
                "application/pdf": ".pdf",
                "text/plain": ".txt",
                "application/msword": ".doc",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
            }
            extension = extension_map.get(mime_type, ".bin")

            return {
                "base64": base64_data,
                "mime_type": mime_type,
                "extension": extension,
                "size_bytes": len(file_content),
                "media_type": media_data.get("media_type", "unknown")
            }

    except Exception as e:
        logger.error(f"Error downloading media file: {e}", exc_info=True)
        return None


def _extract_media_from_reply(text: str) -> Tuple[str, List[dict]]:
    """Parse MEDIA: tokens and MEDIA_BASE64: tokens from agent response text.
    Returns (clean_text, list_of_media_items).
    Each media item is: {"type": "url"|"base64", "value": ..., "mime_type": ...}
    """
    media_items = []
    clean_lines = []

    logger.info(f"[DEBUG] _extract_media_from_reply: Processing {len(text)} chars, {len(text.split(chr(10)))} lines")
    logger.info(f"[DEBUG] First 300 chars: {repr(text[:300])}")

    # FIRST: Check for data URLs in the full text BEFORE splitting into lines
    # This handles cases where base64 spans multiple lines
    data_url_match = re.search(r'\!\[([^\]]+)\]\((data:image/[^;]+;base64,[^\)]+)\)', text, re.DOTALL)
    if data_url_match:
        data_url = data_url_match.group(2)
        # Extract mime type and base64 data
        if 'base64,' in data_url:
            mime_part, b64_part = data_url.split('base64,', 1)
            mime_type = mime_part.replace('data:image/', '').replace(';', '')
            b64_data = b64_part.rstrip(')')
            media_items.append({"type": "base64", "value": b64_data, "mime_type": f"image/{mime_type}"})
            logger.info(f"Found data URL in markdown: image/{mime_type}, size={len(b64_data)} chars")
            # Remove the entire image markdown from text
            text = text.replace(data_url_match.group(0), '')

    for line in text.split("\n"):
        stripped = line.strip()

        # Log lines that might contain media
        if 'MEDIA' in stripped.upper() or 'oaidalleapiprodscus' in stripped or 'blob.core.windows.net' in stripped:
            logger.info(f"[DEBUG] Checking potential media line: {repr(stripped[:100])}")

        # Check for MEDIA_BASE64: <mime_type> <base64_data>
        b64_match = re.match(r'^MEDIA_BASE64:\s*(\S+)\s+(\S+)$', stripped)
        if b64_match:
            mime_type = b64_match.group(1)
            b64_data = b64_match.group(2)
            media_items.append({"type": "base64", "value": b64_data, "mime_type": mime_type})
            logger.info(f"Found MEDIA_BASE64 in response: mime={mime_type}, len={len(b64_data)}")
            continue

        # Check for KUNDLI_IMAGE: <mime_type> <base64_data> (custom format to avoid OpenClaw plugin)
        kundli_match = re.match(r'^KUNDLI_IMAGE:\s*(\S+)\s+(\S+)$', stripped)
        if kundli_match:
            mime_type = kundli_match.group(1)
            b64_data = kundli_match.group(2)
            media_items.append({"type": "base64", "value": b64_data, "mime_type": mime_type})
            logger.info(f"Found KUNDLI_IMAGE in response: mime={mime_type}, len={len(b64_data)}")
            continue

        # Check for data:media_base64:mime_type,base64_data (OpenClaw WhatsApp plugin format)
        openclaw_media_match = re.match(r'^data:media_base64:([^,]+),(.+)$', stripped)
        if openclaw_media_match:
            mime_type = openclaw_media_match.group(1)
            b64_data = openclaw_media_match.group(2)
            media_items.append({"type": "base64", "value": b64_data, "mime_type": mime_type})
            logger.info(f"Found OpenClaw media_base64 in response: mime={mime_type}, len={len(b64_data)}")
            continue

        # Check for IMAGE_URL: or IMAGE: https://... (Kundli image uploaded to dashboard)
        # Now robustly handles LLM hallucinated markdown: IMAGE_URL: [text](https://...)
        image_url_match = re.search(r'^(?:IMAGE_URL|IMAGE):\s*(?:\[[^\]]*\]\()?(https?://[^\)\s]+)\)?', stripped)
        if image_url_match:
            image_url = image_url_match.group(1)
            media_items.append({"type": "url", "value": image_url})
            logger.info(f"Found IMAGE_URL in response: {image_url}")
            # If it was a markdown link, we should clean it from the output so it doesn't show
            line = line.replace(image_url_match.group(0), "")
            continue

        # Check for MEDIA: <path_or_url>
        media_match = re.match(r'^MEDIA:\s*(.+)$', stripped)
        if media_match:
            media_path = media_match.group(1).strip().strip('"').strip("'")
            logger.info(f"[DEBUG] MEDIA: regex matched, path: {repr(media_path[:100])}")

            # Direct URL
            if media_path.startswith('http://') or media_path.startswith('https://'):
                # [URL_V2.1] Log the URL AS RECEIVED from OpenClaw, before any processing
                logger.info(f"[URL_V2.1] URL_AS_RECEIVED from OpenClaw: {media_path[:200]}...")
                # Extract and log signature if present
                if 'sig=' in media_path:
                    sig_start = media_path.find('sig=') + 4
                    sig_end = media_path.find('&', sig_start)
                    if sig_end == -1:
                        sig_end = len(media_path)
                    signature = media_path[sig_start:sig_end]
                    logger.info(f"[URL_V2.1] Signature AS_RECEIVED: {signature}")

                media_items.append({"type": "url", "value": media_path})
                logger.info(f"[URL_V2.1] Added URL to media_items: {media_path[:80]}...")
                continue  # Skip adding this line to clean text

            # Check for Markdown link syntax: [text](url) or ![text](url)
            md_match = re.search(r'!?\[([^\]]*)\]\((https?://[^)]+)\)', media_path)
            if md_match:
                url = md_match.group(2)
                media_items.append({"type": "url", "value": url})
                logger.info(f"Found MEDIA URL in markdown link: {url[:80]}...")
                continue

            # Check for DALL-E URL embedded in malformed text
            dalle_in_media = re.search(r'https://oaidalleapiprodscus\.[^\"\)\s]+', media_path)
            if dalle_in_media:
                dalle_url = dalle_in_media.group(0)
                media_items.append({"type": "url", "value": dalle_url})
                logger.info(f"Found DALL-E URL in MEDIA line: {dalle_url[:80]}...")
                continue

            # Local file path — can't access across containers,
            # log warning but keep line so user sees context
            logger.warning(f"Found MEDIA local path in response (not accessible across containers): {media_path}")
            # Don't add to media_items, can't use it
            continue

        # FALLBACK: Check for DALL-E URLs (oaidalleapiprodscus) even in malformed lines
        # Agent sometimes outputs: "MEDIA:Kundli Chart](https://oaidalleapiprodscus...)"
        # or "[MEDIA: Kundli Chart](url)" - try to extract the URL anyway
        dalle_match = re.search(r'https://oaidalleapiprodscus\.[^\"\)\s]+', line)
        if dalle_match:
            dalle_url = dalle_match.group(0)
            media_items.append({"type": "url", "value": dalle_url})
            logger.info(f"Found DALL-E URL in malformed line: {dalle_url[:80]}...")
            # Remove the entire line from output (it contains broken markdown)
            continue

        # Check for other image URLs in markdown link format [text](url)
        url_match = re.search(r'\[([^\]]+)\]\((https?://[^\)]+)\)', line)
        if url_match:
            url = url_match.group(2)
            # Only extract if it looks like an image URL (common image hosts)
            if any(host in url for host in ['oaidalleapiprodscus', 'blob.core.windows.net', 'images.unsplash', 'imgur', 'i.ibb.co', 'ibb.co', 'hansastro.com', 'localhost']):
                media_items.append({"type": "url", "value": url})
                logger.info(f"Found image URL in markdown link: {url[:80]}...")
                line = line.replace(url_match.group(0), "")
                continue

        # Check for data URL in markdown format ![alt](data:image/...)
        # Try multiline match first (DOTALL flag makes . match newlines)
        data_url_match = re.search(r'\[([^\]]+)\]\((data:image/([^;]+);base64,.+?)\)', line, re.DOTALL)
        if not data_url_match:
            # Try single-line match
            data_url_match = re.search(r'\[([^\]]+)\]\((data:image/([^;]+);base64,[^\)]+)\)', line)
        if data_url_match:
            mime_type = f"image/{data_url_match.group(3)}"
            b64_data = data_url_match.group(4)
            # Remove 'data:image/png;base64,' prefix if present
            if b64_data.startswith('data:'):
                # Extract just the base64 part
                b64_data = b64_data.split('base64,')[1]
            media_items.append({"type": "base64", "value": b64_data, "mime_type": mime_type})
            logger.info(f"Found data URL in markdown link: {mime_type}, size={len(b64_data)} chars")
            # Remove the entire line from output (the base64 string is too long)
            continue

        clean_lines.append(line)

    clean_text = "\n".join(clean_lines).strip()
    return clean_text, media_items


async def _upload_base64_to_whatsapp_media(client: httpx.AsyncClient, b64_data: str, mime_type: str) -> Optional[str]:
    """Upload base64-encoded image to WhatsApp Media API.
    Returns media_id on success, None on failure.
    """
    if not WHATSAPP_PHONE_ID or not WHATSAPP_ACCESS_TOKEN:
        logger.error("WhatsApp credentials missing for media upload")
        return None

    url = f"{FB_API_URL}/{WHATSAPP_PHONE_ID}/media"

    try:
        # Decode base64 to binary
        file_bytes = base64.b64decode(b64_data)

        # Determine file extension from mime type
        ext_map = {
            "image/png": "chart.png",
            "image/jpeg": "chart.jpg",
            "image/webp": "chart.webp",
        }
        filename = ext_map.get(mime_type, "chart.png")

        # Upload as multipart form data
        files = {
            "file": (filename, file_bytes, mime_type),
        }
        data = {
            "messaging_product": "whatsapp",
            "type": mime_type,
        }
        headers = {
            "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        }

        response = await client.post(url, headers=headers, data=data, files=files)

        if response.status_code in [200, 201]:
            media_id = response.json().get("id")
            logger.info(f"Uploaded media to WhatsApp: media_id={media_id}")
            return media_id

        logger.error(f"WhatsApp media upload failed: {response.status_code} {response.text}")
        return None

    except Exception as e:
        logger.error(f"Error uploading media to WhatsApp: {e}", exc_info=True)
        return None


async def _upload_pdf_to_whatsapp_media(client: httpx.AsyncClient, pdf_bytes: bytes, filename: str) -> Optional[str]:
    """
    Upload PDF to WhatsApp Media API

    Args:
        client: HTTP client
        pdf_bytes: PDF file bytes
        filename: Document filename

    Returns:
        Media ID if successful, None otherwise
    """
    if not WHATSAPP_ACCESS_TOKEN:
        logger.error("WhatsApp access token missing")
        return None

    url = f"{FB_API_URL}/{WHATSAPP_PHONE_ID}/media"

    try:
        # Upload as multipart form data
        files = {
            "file": (filename, pdf_bytes, "application/pdf"),
        }
        data = {
            "messaging_product": "whatsapp",
            "type": "application/pdf",
        }
        headers = {
            "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        }

        response = await client.post(url, headers=headers, data=data, files=files)

        if response.status_code in [200, 201]:
            media_id = response.json().get("id")
            logger.info(f"[PDF] Uploaded to WhatsApp Media: {media_id}")
            return media_id

        logger.error(f"[PDF] Upload failed: {response.status_code} {response.text}")
        return None

    except Exception as e:
        logger.error(f"[PDF] Error uploading PDF: {e}", exc_info=True)
        return None


async def _send_whatsapp_image(client: httpx.AsyncClient, phone: str, media_id: str = None, image_url: str = None, caption: str = None) -> dict:
    """Send image message via WhatsApp API using media_id or URL."""
    if not WHATSAPP_PHONE_ID or not WHATSAPP_ACCESS_TOKEN:
        logger.error("WhatsApp credentials missing")
        return {"error": "Credentials missing"}

    url = f"{FB_API_URL}/{WHATSAPP_PHONE_ID}/messages"

    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    # Build image payload — prefer media_id (uploaded), fallback to URL
    image_obj = {}
    if media_id:
        image_obj["id"] = media_id
    elif image_url:
        image_obj["link"] = image_url
    else:
        logger.error("No media_id or image_url provided for image send")
        return {"error": "No image source"}

    if caption:
        image_obj["caption"] = caption[:1024]  # WhatsApp caption limit

    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "image",
        "image": image_obj
    }

    response = await client.post(url, headers=headers, json=payload)

    if response.status_code in [200, 201]:
        msg_id = response.json().get("messages", [{}])[0].get("id")
        logger.info(f"Sent image to {phone}, msg_id={msg_id}")
        return {"success": True, "message_id": msg_id}

    logger.error(f"WhatsApp image send failed: {response.status_code} {response.text}")
    return {"error": response.text}


async def _process_message_async(phone: str, message: str, message_id: str, message_type: str = "text", media_info: dict = None):
    """Async implementation of message processing."""
    session_id = f"whatsapp:+{phone}"
    user_id = f"+{phone}"

    # Download media file if present (image, audio, video, document)
    # This downloads the actual file content and converts to base64
    # because WhatsApp media URLs require authentication
    media_file_data = None
    if media_info and media_info.get("id"):
        media_file_data = await _download_whatsapp_media_file(media_info["id"])
        if media_file_data:
            logger.info(f"Downloaded media file: {message_type}, size: {media_file_data['size_bytes']} bytes, base64_len: {len(media_file_data['base64'])}")
            media_info["base64_data"] = media_file_data["base64"]
            media_info["mime_type"] = media_file_data["mime_type"]
            media_info["extension"] = media_file_data["extension"]
        else:
            logger.warning(f"Failed to download media file: {media_info.get('id')}")

    # Log user message to MongoDB (exclude large base64 data from log)
    log_media_info = None
    if media_info:
        log_media_info = {k: v for k, v in media_info.items() if k != "base64_data"}
    await _log_to_mongo(session_id, user_id, "user", message, "whatsapp", message_type, log_media_info)

    # ==================== AUDIO MESSAGE PROCESSING ====================

    # Check if this is an audio message
    if message_type in ["audio", "voice"]:
        logger.info(f"[Audio] Received audio message from {phone}")

        try:
            # Import audio processor
            from skills.audio_processor.transcribe import transcribe_audio

            # Transcribe audio to text using Groq (FREE)
            if media_info and media_info.get("base64_data"):
                transcribed_text = await transcribe_audio(
                    media_info["base64_data"],
                    media_info.get("mime_type", "audio/ogg")
                )

                if transcribed_text:
                    logger.info(f"[Audio] Transcription successful: {transcribed_text[:100]}...")
                    # Replace the message with transcription
                    message = transcribed_text
                    # Keep message_type as audio for logging, but treat as text
                    logger.info("[Audio] Proceeding with transcribed text")
                else:
                    logger.warning("[Audio] Transcription failed, sending empty message")
                    message = ""  # Send empty message
            else:
                logger.warning("[Audio] No audio data found")
                message = ""

        except Exception as e:
            logger.error(f"[Audio] Error processing audio: {e}")
            # Fallback: send empty message
            message = ""

    # ===================================================================

    # ==================== SUBSCRIPTION CHECK ====================

    # Check if user has valid subscription (trial or active)
    # Only enforced for SUBSCRIPTION_TEST_NUMBER in testing mode
    access = await _check_subscription_access(phone)

    if access.get("access") == "no_access":
        # User's trial has expired and no active subscription
        # OR New user who hasn't paid ₹1 yet
        logger.info(f"[Subscription] Access denied for {phone}")

        # Check if this is a new user who needs to pay ₹1 to activate trial
        if access.get("require_payment"):
            # New user - Needs to pay ₹1 to activate 7-day trial
            logger.info(f"[Subscription] New user - requires ₹1 trial activation: {phone}")

            # Generate ₹1 trial activation payment link
            trial_activation_link = await _generate_trial_activation_link(user_id)

            if trial_activation_link:
                trial_message = (
                    "👋 Welcome to Astrofriend!\n\n"
                    "To activate your **7-day FREE trial**, please pay ₹1 (verification fee).\n\n"
                    f"Click here: {trial_activation_link}\n\n"
                    "After payment, send me a message to start! 💫"
                )
                async with httpx.AsyncClient(timeout=30.0) as client:
                    await _send_whatsapp_message(client, phone, trial_message)
                await _log_to_mongo(session_id, user_id, "assistant", trial_message, "whatsapp", "text", None, nudge_level=1)
                return {"status": "trial_activation_required", "trial_activation_link": trial_activation_link}

        # User is requesting to see plans
        if message.strip().upper() in ["PAY", "PAYMENT", "PLAN", "PLANS", "SUBSCRIBE"]:
            # Fetch and send plan options
            plans_message = await _get_plans_message()
            async with httpx.AsyncClient(timeout=30.0) as client:
                await _send_whatsapp_message(client, phone, plans_message)
            await _log_to_mongo(session_id, user_id, "assistant", plans_message, "whatsapp")
            return {"status": "plans_sent", "access": access}

        # Check if user is selecting a plan (replying with number 1, 2, 3, etc.)
        if message.strip().isdigit():
            plan_number = int(message.strip())
            payment_link = await _generate_payment_link(user_id, plan_number)
            if payment_link:
                link_message = (
                    f"Great! You selected Plan {plan_number}.\n\n"
                    f"Click here to complete payment: {payment_link}\n\n"
                    f"After payment, come back and send me a message! 💫"
                )
                async with httpx.AsyncClient(timeout=30.0) as client:
                    await _send_whatsapp_message(client, phone, link_message)
                await _log_to_mongo(session_id, user_id, "assistant", link_message, "whatsapp")
                return {"status": "payment_link_sent", "payment_link": payment_link}

        # Default payment nudge message (trial expired)
        payment_message = (
            "Your 7-day free trial has ended. To continue using Astrofriend services, "
            "please subscribe to a plan.\n\n"
            "Reply *PAY* to see subscription options."
        )

        async with httpx.AsyncClient(timeout=30.0) as client:
            await _send_whatsapp_message(client, phone, payment_message)

        # Log the payment nudge to MongoDB
        await _log_to_mongo(
            session_id,
            user_id,
            "assistant",
            payment_message,
            "whatsapp",
            "text",
            None,
            nudge_level=1  # Track as payment nudge
        )

        return {"status": "payment_required", "access": access}

    # Log subscription status for monitoring
    access_type = access.get("access", "unknown")
    if access_type != "trial" or access.get("skip_reason"):
        logger.info(f"[Subscription] {phone} has access: {access_type} (reason: {access.get('skip_reason', 'valid_access')})")

    if not OPENCLAW_URL:
        logger.warning("OPENCLAW_URL not set")
        return {"error": "OpenClaw URL not configured"}

    async with httpx.AsyncClient(timeout=300.0) as client:
        # Send typing indicator
        await _send_typing_indicator(client, message_id)

        headers = {
            "Content-Type": "application/json",
            "x-openclaw-session-key": f"agent:astrologer:whatsapp:direct:+{phone}",
            "x-openclaw-scopes": "operator.admin",
        }

        if OPENCLAW_GATEWAY_TOKEN:
            headers["Authorization"] = f"Bearer {OPENCLAW_GATEWAY_TOKEN}"

        # Create envelope with media context
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        envelope = f"[From: WhatsApp User (+{phone}) at {timestamp}]"

        # Build context text (no image data in text — that goes via input_image)
        if message_type != "text" and media_info:
            media_context = f" [Media Type: {message_type}"
            if message_type == "image" and media_info.get("caption"):
                media_context += f", Caption: {media_info['caption']}"
            elif message_type == "document" and media_info.get("filename"):
                media_context += f", Filename: {media_info['filename']}"
            media_context += "]"
            text_content = f"{envelope}{media_context}\n{message}"
        else:
            text_content = f"{envelope}\n{message}"

        # Build input: use structured content parts when image is present
        has_image_data = (
            media_info
            and media_info.get("base64_data")
            and message_type in ["image", "photo", "sticker"]
        )

        if has_image_data:
            # Use OpenClaw's input_image format — sends full base64 image
            mime = media_info.get("mime_type", "image/jpeg")
            
            # Ensure mime is one of the allowed types by the schema
            allowed_mimes = ["image/jpeg", "image/png", "image/gif", "image/webp"]
            if mime not in allowed_mimes:
                # Default to jpeg if an unsupported mime type is used
                mime = "image/jpeg"
                
            content_parts = [
                {"type": "input_text", "text": text_content},
                {
                    "type": "input_image",
                    "source": {
                        "type": "base64",
                        "media_type": mime,
                        "data": media_info["base64_data"],  # FULL base64, not truncated
                    },
                },
            ]
            payload_input = [
                {
                    "type": "message",
                    "role": "user",
                    "content": content_parts,
                }
            ]
            logger.info(f"Sending image to OpenClaw via input_image: mime={mime}, b64_len={len(media_info['base64_data'])}")
        else:
            # Plain text input
            payload_input = text_content

        payload = {
            "model": "agent:astrologer",
            "input": payload_input,
            "user": f"+{phone}",
        }

        # Add lightweight metadata (no base64 in metadata — it goes in input_image)
        if media_info:
            payload["metadata"] = {
                "message_type": message_type,
                "media_type": media_info.get("type", message_type),
                "media_id": media_info.get("id", ""),
            }
            if "caption" in media_info:
                payload["metadata"]["media_caption"] = media_info["caption"]
            if "filename" in media_info:
                payload["metadata"]["media_filename"] = media_info["filename"]

        response = await client.post(
            f"{OPENCLAW_URL}/v1/responses",
            json=payload,
            headers=headers,
        )

        if response.status_code != 200:
            logger.error(f"OpenClaw error {response.status_code}: {response.text}")
            return {"error": f"OpenClaw returned {response.status_code}"}

        data = response.json()

        # [DEBUG] Log the entire response structure
        logger.info(f"[RESPONSE_DEBUG] Response keys: {list(data.keys())}")
        if "output" in data:
            logger.info(f"[RESPONSE_DEBUG] Number of output items: {len(data['output'])}")
            for idx, item in enumerate(data["output"]):
                logger.info(f"[RESPONSE_DEBUG] Output item {idx}: type={item.get('type')}, keys={list(item.keys())}")
                if "content" in item:
                    logger.info(f"[RESPONSE_DEBUG] Item {idx} has {len(item['content'])} content entries")
                    for cidx, content in enumerate(item["content"]):
                        logger.info(f"[RESPONSE_DEBUG] Content {cidx}: type={content.get('type')}, has_text={'text' in content}")
                        if "text" in content:
                            text_preview = content["text"][:200] if content["text"] else ""
                            logger.info(f"[RESPONSE_DEBUG] Content {cidx} text preview: {repr(text_preview)}")

        # Extract reply text from response
        # CONCATENATE all text content entries (don't just take the first one)
        reply_parts = []
        tool_outputs = []

        if "output" in data:
            for item in data["output"]:
                # Process agent messages (type: message)
                if item.get("type") == "message" and item.get("content"):
                    for content in item["content"]:
                        if content.get("text"):
                            reply_parts.append(content["text"])

                # Process tool execution outputs (type: tool, execution, etc.)
                # Tool outputs contain MEDIA_BASE64 tokens from script execution
                if item.get("type") in ["tool", "execution", "function"] and item.get("content"):
                    for content in item["content"]:
                        # Extract text from tool outputs (contains MEDIA_BASE64)
                        if content.get("text"):
                            tool_outputs.append(content["text"])
                            logger.info(f"[TOOL_OUTPUT] Found tool output: {content['text'][:100]}...")

        if not reply_parts and not tool_outputs:
            logger.error(f"[RESPONSE_ERROR] No content found in response")
            return {"status": "no_reply"}

        # Combine agent messages and tool outputs
        # Tool outputs go FIRST so MEDIA_BASE64 is extracted before agent text
        all_parts = tool_outputs + reply_parts
        reply = "\n\n".join(all_parts)
        logger.info(f"[RESPONSE_DEBUG] Concatenated {len(reply_parts)} text parts + {len(tool_outputs)} tool outputs, total length: {len(reply)}")

        # Parse MEDIA: / MEDIA_BASE64: tokens from response
        logger.info(f"[DEBUG] Raw reply from agent (first 500 chars): {reply[:500]}...")
        clean_reply, media_items = _extract_media_from_reply(reply)
        logger.info(f"[DEBUG] Extracted {len(media_items)} media items, clean_reply length: {len(clean_reply)}")

        # ===================================================================
        # DETECT PDF REQUESTS FROM AI AGENT RESPONSE
        # ===================================================================

        # Check if AI agent's response contains a PDF request
        # Agent should include: "PDF_REQUEST: dob=YYYY-MM-DD, tob=HH:MM, place=CITY, name=NAME"
        if "PDF_REQUEST:" in clean_reply:
            logger.info(f"[PDF] Agent triggered PDF generation for {user_id}")

            try:
                # Parse the PDF request parameters from AI's response
                import re
                params = {}
                for param in ["dob", "tob", "place", "name"]:
                    match = re.search(rf"{param}=([^,\n]+)", clean_reply)
                    if match:
                        params[param] = match.group(1).strip()

                # Set default name if not provided
                if "name" not in params:
                    params["name"] = "User"

                # Validate required parameters
                if not all(k in params for k in ["dob", "tob", "place"]):
                    logger.error(f"[PDF] Missing required parameters: {params}")
                else:
                    logger.info(f"[PDF] Triggering PDF generation with params: {params}")

                    # Trigger PDF generation in background
                    generate_kundli_pdf_task.delay(phone, user_id, params["dob"], params["tob"], params["place"], params["name"])

                    logger.info(f"[PDF] PDF generation task triggered successfully")

            except Exception as e:
                logger.error(f"[PDF] Error processing PDF request: {e}", exc_info=True)

        # Send text reply (split on double-newline for separate bubbles)
        if clean_reply:
            bubbles = [b.strip() for b in clean_reply.split("\n\n") if b.strip()]
            for bubble in bubbles:
                await _send_whatsapp_message(client, phone, bubble)

        # Send any media items as images
        for media_item in media_items:
            if media_item["type"] == "base64":
                # Upload base64 image to WhatsApp Media API, then send
                media_id = await _upload_base64_to_whatsapp_media(
                    client,
                    media_item["value"],
                    media_item.get("mime_type", "image/png"),
                )
                if media_id:
                    await _send_whatsapp_image(client, phone, media_id=media_id, caption="Kundli Chart")
                else:
                    logger.error("Failed to upload media to WhatsApp")
            elif media_item["type"] == "url":
                # DALL-E URLs are temporary SAS tokens - need to download first
                # WhatsApp cannot access these directly
                logger.info(f"Processing DALL-E URL: {media_item['value'][:100]}...")

                # Download the image from DALL-E URL
                try:
                    async with httpx.AsyncClient(timeout=30.0) as dl_client:
                        from urllib.parse import unquote_plus
                        url_to_fetch = media_item["value"]

                        # [VERSION_MARKER] v2.1 - Smart signature-only decoding
                        logger.info(f"[URL_V2.1] ORIGINAL URL (first 150 chars): {url_to_fetch[:150]}")

                        # Extract and log signature specifically to verify encoding
                        if 'sig=' not in url_to_fetch:
                            logger.warning(f"[URL_V2.1] No signature found in URL, using as-is")
                        else:
                            sig_start = url_to_fetch.find('sig=') + 4
                            sig_end = url_to_fetch.find('&', sig_start)
                            if sig_end == -1:
                                sig_end = len(url_to_fetch)
                            original_signature = url_to_fetch[sig_start:sig_end]
                            logger.info(f"[URL_V2.1] Original signature: {original_signature}")

                            # Smart decode: Only decode the signature parameter, not the entire URL
                            # This preserves legitimate URL encoding in path/query while fixing over-encoded signatures
                            from urllib.parse import urlparse, urlunparse, urlencode, parse_qsl

                            parsed = urlparse(url_to_fetch)
                            query_params = dict(parse_qsl(parsed.query))

                            if 'sig' in query_params:
                                sig_value = query_params['sig']
                                logger.info(f"[URL_V2.1] Signature from query params: {sig_value[:100]}...")

                                # Repeatedly decode ONLY the signature until stable
                                prev_sig = sig_value
                                max_iterations = 5
                                iteration = 0

                                while '%' in sig_value and iteration < max_iterations:
                                    prev_sig = sig_value
                                    sig_value = unquote_plus(sig_value)
                                    iteration += 1
                                    logger.info(f"[URL_V2.1] Sig decode iteration {iteration}: {len(prev_sig)} -> {len(sig_value)} chars")
                                    logger.info(f"[URL_V2.1] Signature after iteration {iteration}: {sig_value[:100]}...")

                                    if len(sig_value) == len(prev_sig):
                                        # Check if no actual changes occurred (stable)
                                        if sig_value == prev_sig:
                                            break

                                # Update query params with decoded signature
                                query_params['sig'] = sig_value
                                logger.info(f"[URL_V2.1] Final decoded signature: {sig_value[:100]}...")

                                # Validate decoded signature format
                                # Azure SAS signatures should be base64-like: alphanumeric, +, /, =
                                # Should NOT contain % characters (those should have been decoded)
                                if '%' in sig_value:
                                    logger.error(f"[URL_V2.1] WARNING: Signature STILL contains % after decoding: {sig_value[:100]}...")
                                else:
                                    logger.info(f"[URL_V2.1] ✓ Signature looks clean (no % chars)")

                                # Reconstruct URL with decoded signature
                                new_query = urlencode(query_params, doseq=True)
                                url_to_fetch = urlunparse((
                                    parsed.scheme,
                                    parsed.netloc,
                                    parsed.path,
                                    parsed.params,
                                    new_query,
                                    parsed.fragment
                                ))

                                logger.info(f"[URL_V2.1] Reconstructed URL with decoded signature")
                            else:
                                logger.warning(f"[URL_V2.1] sig parameter not found in query params")

                        # Now download with the decoded signature URL
                        logger.info(f"[URL_V2.1] Starting download with decoded signature...")
                        logger.info(f"[URL_V2.1] Download URL (first 150 chars): {url_to_fetch[:150]}")
                        dl_response = await dl_client.get(url_to_fetch)

                        logger.info(f"[URL_V2.1] Response status: {dl_response.status_code}")
                        logger.info(f"[URL_V2.1] Response headers: {dict(dl_response.headers)}")

                        if dl_response.status_code != 200:
                            logger.error(f"[URL_V2.1] ERROR: Failed to download DALL-E image: {dl_response.status_code}")
                            logger.error(f"[URL_V2.1] URL used (first 200 chars): {url_to_fetch[:200]}")
                            logger.error(f"[URL_V2.1] Response body (first 500 chars): {dl_response.text[:500]}")

                            # Check signature state in failed URL
                            if 'sig=' in url_to_fetch:
                                sig_start = url_to_fetch.find('sig=') + 4
                                sig_end = url_to_fetch.find('&', sig_start)
                                if sig_end == -1:
                                    sig_end = len(url_to_fetch)
                                signature = url_to_fetch[sig_start:sig_end]
                                if '%' in signature:
                                    logger.error(f"[URL_V2.1] ERROR: Signature STILL contains % chars: {signature[:100]}...")
                                    logger.error(f"[URL_V2.1] This means signature is still over-encoded despite our fix!")
                                else:
                                    logger.error(f"[URL_V2.1] ERROR: Signature looks clean but download still failed: {signature[:100]}...")
                                    logger.error(f"[URL_V2.1] This might be a different issue (expiration, permissions, etc.)")

                            continue

                        # Get content type
                        content_type = dl_response.headers.get("content-type", "image/png")
                        if content_type.startswith("image/"):
                            mime_type = content_type.split(";")[0]
                        else:
                            mime_type = "image/png"

                        # Convert to base64
                        image_bytes = dl_response.content
                        base64_data = base64.b64encode(image_bytes).decode('utf-8')

                        # Upload to WhatsApp Media API
                        logger.info(f"Uploading DALL-E image to WhatsApp Media API (size: {len(image_bytes)} bytes)")
                        media_id = await _upload_base64_to_whatsapp_media(
                            client,
                            base64_data,
                            mime_type,
                        )

                        if media_id:
                            logger.info(f"DALL-E image uploaded successfully: media_id={media_id}")
                            await _send_whatsapp_image(client, phone, media_id=media_id, caption="Kundli Chart")
                        else:
                            logger.error("Failed to upload DALL-E image to WhatsApp Media API")

                except Exception as e:
                    logger.error(f"Error processing DALL-E URL: {e}", exc_info=True)

        await _log_to_mongo(session_id, user_id, "assistant", clean_reply or reply, "whatsapp")
        return {"status": "sent", "message_id": message_id}


async def _send_media_message(client: httpx.AsyncClient, phone: str, media_url: str, media_type: str = "image", caption: str = None) -> dict:
    """Send media message via WhatsApp API."""
    if not WHATSAPP_PHONE_ID or not WHATSAPP_ACCESS_TOKEN:
        logger.error("WhatsApp credentials missing")
        return {"error": "Credentials missing"}

    url = f"{FB_API_URL}/{WHATSAPP_PHONE_ID}/messages"

    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    # Build media payload
    media_key = media_type  # image, audio, video, document
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": media_type,
        media_key: {
            "link": media_url
        }
    }

    # Add caption for images/videos
    if caption and media_type in ["image", "video"]:
        payload[media_key]["caption"] = caption

    # Add filename for documents
    if media_type == "document" and caption:
        payload[media_key]["filename"] = caption

    response = await client.post(url, headers=headers, json=payload)

    if response.status_code in [200, 201]:
        msg_id = response.json().get("messages", [{}])[0].get("id")
        logger.info(f"Sent {media_type} to {phone}")
        return {"success": True, "message_id": msg_id}

    logger.error(f"WhatsApp send failed: {response.text}")
    return {"error": response.text}


@celery_app.task
def send_message_task(phone: str, message: str) -> dict:
    """
    Send a WhatsApp message asynchronously.
    Returns the message ID on success.
    """
    try:
        import asyncio
        result = asyncio.run(_send_whatsapp_message_async(phone, message))
        return result
    except Exception as e:
        logger.error(f"[Celery] Send task failed: {e}")
        return {"error": str(e)}


async def _send_whatsapp_message_async(phone: str, message: str):
    """Async implementation of sending WhatsApp message."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        return await _send_whatsapp_message(client, phone, message)


async def _send_whatsapp_message(client: httpx.AsyncClient, phone: str, message: str):
    """Send message via WhatsApp API."""
    if not WHATSAPP_PHONE_ID or not WHATSAPP_ACCESS_TOKEN:
        logger.error("WhatsApp credentials missing")
        return {"error": "Credentials missing"}

    url = f"{FB_API_URL}/{WHATSAPP_PHONE_ID}/messages"

    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": message}
    }

    response = await client.post(url, headers=headers, json=payload)

    if response.status_code in [200, 201]:
        msg_id = response.json().get("messages", [{}])[0].get("id")
        return {"success": True, "message_id": msg_id}

    logger.error(f"WhatsApp send failed: {response.text}")
    return {"error": response.text}


async def _send_typing_indicator(client: httpx.AsyncClient, message_id: str):
    """Send typing indicator via WhatsApp API."""
    if not WHATSAPP_PHONE_ID or not WHATSAPP_ACCESS_TOKEN:
        return

    url = f"{FB_API_URL}/{WHATSAPP_PHONE_ID}/messages"

    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
        "typing_indicator": {"type": "text"}
    }

    try:
        await client.post(url, headers=headers, json=payload)
    except Exception as e:
        logger.warning(f"Failed to send typing indicator: {e}")


async def _log_to_mongo(session_id: str, user_id: str, role: str, text: str, channel: str, message_type: str = "text", media_info: dict = None, nudge_level: int = None):
    """Log chat message to MongoDB."""
    if not MONGO_LOGGER_URL:
        return

    payload = {
        "sessionId": session_id,
        "userId": user_id,
        "role": role,
        "text": text,
        "channel": channel,
        "messageType": message_type
    }
    
    if nudge_level:
        payload["nudgeLevel"] = nudge_level

    # Add media info if present
    if media_info:
        payload["mediaInfo"] = media_info

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{MONGO_LOGGER_URL}/webhook",
                json=payload
            )
            if response.status_code == 200:
                logger.debug(f"Logged {role} message to MongoDB")
    except Exception as e:
        logger.warning(f"Failed to log to MongoDB: {e}")


@celery_app.task
def health_check_task():
    """Periodic health check task."""
    logger.info("[Celery] Health check - worker is running")
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@celery_app.task(bind=True, max_retries=2, default_retry_delay=60)
def generate_kundli_pdf_task(self, phone: str, user_id: str, dob: str, tob: str, place: str, name: str = "User"):
    """
    Generate and send Kundli PDF to user

    Args:
        phone: User's phone number (without +)
        user_id: User's ID (with +)
        dob: Date of birth
        tob: Time of birth
        place: Place of birth
        name: User's name
    """
    try:
        logger.info(f"[PDF Task] Starting for {user_id}: DOB={dob}, TOB={tob}, Place={place}")

        # Run async code in sync context
        import asyncio
        result = asyncio.run(_generate_kundli_pdf_async(phone, user_id, dob, tob, place, name))

        logger.info(f"[PDF Task] Completed for {user_id}: {result}")
        return result

    except Exception as e:
        logger.error(f"[PDF Task] Failed for {user_id}: {e}")
        # Retry with exponential backoff
        raise self.retry(exc=e, countdown=2 ** self.request.retries)


async def _generate_kundli_pdf_async(phone: str, user_id: str, dob: str, tob: str, place: str, name: str) -> dict:
    """Async implementation of PDF generation"""
    from app.services.kundli_pdf_generator import KundliPDFGenerator
    from app.services.whatsapp_api import WhatsAppAPI

    session_id = f"whatsapp:+{phone}"

    # Prepare user data
    user_data = {
        "name": name,
        "dateOfBirth": dob,
        "timeOfBirth": tob,
        "birthPlace": place
    }

    # Use placeholder kundli data for now (simplified version)
    # TODO: Integrate with actual kundli calculation service
    kundli_data = {
        "lagna": "Taurus",
        "moon_sign": "Pisces",
        "nakshatra": "Uttara Bhadrapada",
        "planet_positions": {
            "sun": {"planet": "Sun", "sign": "Leo", "house": 5, "degree": 15.5},
            "moon": {"planet": "Moon", "sign": "Cancer", "house": 4, "degree": 10.2},
            "mars": {"planet": "Mars", "sign": "Aries", "house": 1, "degree": 5.0},
            "mercury": {"planet": "Mercury", "sign": "Gemini", "house": 3, "degree": 20.1},
            "jupiter": {"planet": "Jupiter", "sign": "Sagittarius", "house": 8, "degree": 18.3},
            "venus": {"planet": "Venus", "sign": "Taurus", "house": 2, "degree": 12.7},
            "saturn": {"planet": "Saturn", "sign": "Aquarius", "house": 10, "degree": 8.9},
            "rahu": {"planet": "Rahu", "sign": "Gemini", "house": 3, "degree": 15.0},
            "ketu": {"planet": "Ketu", "sign": "Sagittarius", "house": 9, "degree": 15.0}
        },
        "dasha": {"mahadasha": "Saturn", "antardasha": "Saturn"}
    }

    logger.info(f"[PDF] Using placeholder kundli data: Lagna={kundli_data.get('lagna')}, Rashi={kundli_data.get('moon_sign')}")

    # Placeholder charts
    charts = {
        "lagna_chart": "placeholder",
        "navamsa_chart": "placeholder"
    }

    # Generate PDF
    try:
        pdf_generator = KundliPDFGenerator()
        pdf_bytes = pdf_generator.generate_pdf(user_data, kundli_data, charts)

        logger.info(f"[PDF] PDF generated: {len(pdf_bytes)} bytes")

    except Exception as e:
        logger.error(f"[PDF] PDF generation failed: {e}", exc_info=True)
        return {"error": f"PDF generation failed: {str(e)}"}

    # Upload PDF to WhatsApp Media
    filename = f"Kundli_{user_id.replace('+', '')}.pdf"

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Upload PDF
        media_id = await _upload_pdf_to_whatsapp_media(client, pdf_bytes, filename)

        if not media_id:
            logger.error("[PDF] PDF upload to WhatsApp failed")
            return {"error": "PDF upload failed"}

        logger.info(f"[PDF] PDF uploaded to WhatsApp: {media_id}")

        # Get direct URL from media ID
        document_url = f"{FB_API_URL}/{media_id}"

        # Send PDF via WhatsApp
        whatsapp_api = WhatsAppAPI(
            phone_id=WHATSAPP_PHONE_ID,
            access_token=WHATSAPP_ACCESS_TOKEN
        )

        caption = f"Namaste {user_data.get('name', 'User')}! 🙏 Here's your detailed Janam Kundli PDF."

        message_id = await whatsapp_api.send_document(
            to=phone,
            document_url=document_url,
            filename=filename,
            caption=caption
        )

        if message_id:
            logger.info(f"[PDF] Sent Kundli PDF to {user_id}, message_id={message_id}")

            # Log to MongoDB
            await _log_to_mongo(
                session_id,
                user_id,
                "assistant",
                f"Kundli PDF sent: {filename}",
                "whatsapp",
                "document",
                {"filename": filename, "size": len(pdf_bytes)}
            )

            return {"success": True, "message_id": message_id}
        else:
            logger.error("[PDF] Failed to send PDF via WhatsApp")
            return {"error": "Failed to send PDF"}


@celery_app.task
def proactive_nudge_task():
    """
    Send proactive nudges to inactive WhatsApp users.
    Runs every 5 minutes to check for users inactive for 8+ hours.
    Only sends messages between 9 AM - 10 PM IST.
    """
    import asyncio
    from datetime import timedelta, timezone

    try:
        logger.info("[Proactive Nudge] ===== TASK STARTED =====")

        # Check if within active hours (9 AM - 10 PM IST)
        from datetime import datetime
        import pytz
        ist = pytz.timezone('Asia/Kolkata')
        now_ist = datetime.now(ist)
        current_hour = now_ist.hour

        logger.info(f"[Proactive Nudge] Current time: {now_ist.strftime('%Y-%m-%d %H:%M:%S')} IST")

        if not (9 <= current_hour < 22):
            logger.info(f"[Proactive Nudge] Outside active hours ({current_hour}:00 IST), skipping")
            return {"status": "outside_active_hours", "current_hour": current_hour}

        # Query MongoDB Logger for inactive users
        logger.info(f"[Proactive Nudge] Checking for inactive users...")
        result = asyncio.run(_check_inactive_users())

        logger.info(f"[Proactive Nudge] ===== TASK COMPLETED =====")
        logger.info(f"[Proactive Nudge] Result: {result}")
        return result

    except Exception as e:
        logger.error(f"[Proactive Nudge] ===== TASK FAILED =====", exc_info=True)
        logger.error(f"[Proactive Nudge] Error: {e}")
        return {"error": str(e)}


async def _check_inactive_users():
    """
    Check for inactive users and send nudges.
    Only processes users inactive for 8-24 hours.
    """
    if not MONGO_LOGGER_URL:
        logger.error("[Proactive Nudge] MONGO_LOGGER_URL not configured!")
        return {"error": "MongoDB URL not configured"}

    logger.info(f"[Proactive Nudge] Fetching users from {MONGO_LOGGER_URL}/messages")

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Get all users from MongoDB Logger
        try:
            response = await client.get(f"{MONGO_LOGGER_URL}/messages")
            logger.info(f"[Proactive Nudge] MongoDB response status: {response.status_code}")

            if response.status_code != 200:
                logger.error(f"[Proactive Nudge] Failed to fetch users: {response.status_code} - {response.text}")
                return {"error": f"Failed to fetch users: {response.status_code}"}

            data = response.json()
            users = data.get("users", [])
            logger.info(f"[Proactive Nudge] Total users found: {len(users)}")

        except Exception as e:
            logger.error(f"[Proactive Nudge] Exception fetching users: {e}", exc_info=True)
            return {"error": f"Exception fetching users: {e}"}

        # Process users in a try-except block
        try:
            from datetime import timezone
            now = datetime.now(timezone.utc)
            nudges_sent = 0
            users_checked = 0

            for user in users:
                user_id = user.get("userId", "")
                if not user_id or not user_id.startswith("+"):
                    continue

                # TESTING MODE: Only send to test number if configured
                if PROACTIVE_NUDGE_TEST_NUMBER:
                    if user_id != PROACTIVE_NUDGE_TEST_NUMBER:
                        logger.debug(f"[Proactive Nudge] TESTING MODE: Skipping {user_id} (not test number)")
                        continue
                    logger.info(f"[Proactive Nudge] ✓ Processing {user_id} (matches test number)")

                for session in user.get("sessions", []):
                    channel = session.get("channel", "").lower()
                    if "whatsapp" not in channel:
                        continue

                    # Get last message time
                    last_msg_str = session.get("lastMessageTime", "")
                    if not last_msg_str:
                        continue

                    try:
                        # Parse timestamp
                        if last_msg_str.endswith('Z'):
                            last_msg_time = datetime.fromisoformat(last_msg_str.replace('Z', '+00:00'))
                        else:
                            last_msg_time = datetime.fromisoformat(last_msg_str)

                        # Calculate inactive minutes
                        inactive_minutes = (now - last_msg_time).total_seconds() / 60

                        # Send nudge if inactive for at least 8 hours (480 minutes)
                        # Only sent between 9 AM - 10 PM IST
                        if inactive_minutes < 480:
                            logger.debug(f"[Proactive Nudge] {user_id}: inactive for {inactive_minutes:.0f} mins (skipping - waiting for 8 hour threshold)")
                            continue

                        users_checked += 1
                        hours_inactive = inactive_minutes / 60
                        logger.info(f"[Proactive Nudge] ELIGIBLE: {user_id} inactive for {hours_inactive:.1f} hours")

                        # DUPLICATE PREVENTION: Check if last message was from bot (proactive nudge)
                        messages = session.get("messages", [])
                        if messages:
                            last_message = messages[-1]
                            last_message_role = last_message.get("role", "")
                            if last_message_role == "assistant":
                                logger.info(f"[Proactive Nudge] {user_id}: Last message was from bot (skipping - user hasn't replied)")
                                continue
                        

                        # Get recent conversation for topic and language detection
                        recent_conversation = await _get_recent_conversation_from_mongo(user_id, session)
                        detected_topic = recent_conversation.get("detected_topic")
                        detected_language = recent_conversation.get("detected_language", "en")

                        logger.info(f"[Proactive Nudge] {user_id}: topic={detected_topic}, language={detected_language}")

                        # Generate and send nudge message based on topic and language
                        nudge_message = _generate_nudge_message(user_id, detected_topic, hours_inactive, detected_language)

                        # Send nudge via WhatsApp
                        phone = user_id.replace("+", "")
                        await _send_whatsapp_message(client, phone, nudge_message)
                        nudges_sent += 1


                        logger.info(f"[Proactive Nudge] ✓ Nudge sent to {user_id} (topic: {detected_topic}, language: {detected_language})")

                        # Small delay to avoid rate limiting
                        await asyncio.sleep(2)

                    except Exception as e:
                        logger.error(f"[Proactive Nudge] Error processing {user_id}: {e}")
                        continue

            logger.info(f"[Proactive Nudge] Summary: Checked {users_checked} users, sent {nudges_sent} nudges")
            return {
                "status": "completed",
                "users_checked": users_checked,
                "nudges_sent": nudges_sent
            }

        except Exception as e:
            logger.error(f"[Proactive Nudge] Exception in _check_inactive_users: {e}", exc_info=True)
            return {"error": str(e)}


def _generate_nudge_message(user_id: str, detected_topic: str, hours_inactive: float, user_language: str = "en") -> str:
    """
    Generate personalized nudge message based on detected topic and user language.
    Stage 1: Topic-based messages (Stage 2 will be more personalized with Mem0)

    Args:
        user_id: User phone number
        detected_topic: Topic detected from conversation (marriage, career, health, education)
        hours_inactive: Hours since last message
        user_language: User's language preference ("en" or "hi")
    """

    # English message templates based on topic
    topic_messages_en = {
        "marriage": [
            "Hey! Was thinking about our shaadi discussion... Your 7th house lord is actually quite strong right now. Should we check what the planets say about your marriage timing?",

            "Namaste! You know, we were talking about your vivah earlier - Jupiter's current position might bring some good news for your relationships. Want me to analyze your kundli for this?",

            "Hi! Remember we discussed your shaadi? The transit of Venus is favorable right now. Shall I check your birth chart for the best period?",
        ],
        "career": [
            "Hey! Was thinking about your career discussion... Your 10th house has some interesting planetary movements happening. Want me to check what this means for your job prospects?",

            "Hi! Remember you asked about your career? Saturn's position suggests good things coming professionally. Should I analyze your kundli for the timing?",

            "Namaste! Your career discussion has been on my mind... Mercury is favoring your profession house right now. Want to know what opportunities are coming?",
        ],
        "health": [
            "Hey! How are you feeling now? We talked about your health earlier... There are some simple remedies that might really help based on your current planetary position. Want me to check?",

            "Hi! Was thinking about your health... The 6th house lord is well-placed in your chart right now, which is good for recovery. Should I suggest some personalized remedies?",

            "Namaste! Hope you're feeling better... Your health houses look stronger in your recent kundli analysis. Want me to suggest some astrological remedies?",
        ],
        "education": [
            "Hey! How are your studies going? We talked about your exams... Your 5th house is very strong right now - great time for students! Should I check what the stars say about your results?",

            "Hi! Remember your education discussion? Jupiter is blessing your learning house this month. Want me to analyze your chart for exam success?",

            "Namaste! Was thinking about your studies... Mercury's position is excellent for concentration right now. Should I check your kundli for favorable periods?",
        ]
    }

    # Hindi message templates based on topic
    topic_messages_hi = {
        "marriage": [
            "नमस्ते! आपकी शादी की बात सोच रहा था... आपकी सातवीं भाव का शास्त्री अभी काफी मजबूत है। क्या हम ग्रहों को देखें कि आपकी शादी का समय क्या है?",

            "हाय! हमने आपकी विवाह की बात की थी ना... बृहस्पति की वर्तमान स्थिति आपके रिश्तों के लिए अच्छी खबर ला सकती है। क्या मैं आपकी कुंडली का विश्लेषण करूं?",

            "नमस्ते! याद है न हमने आपकी शादी पर बात की थी? शुक्र का गोचर अनुकूल है। क्या हम आपकी जन्म कुंडली को देखें?",
        ],
        "career": [
            "हाय! आपकी करियर की बात सोच रहा था... आपकी दसवीं भाव में कुछ दिलचस्प ग्रह गतिविधि हो रही है। क्या मैं देखूं कि इसका क्या मतलब है?",

            "नमस्ते! याद है न आपने अपनी नौकरी के बारे में पूछा था? शनि की स्थिति व्यावसायिक रूप से अच्छी चीजें ला रही है। क्या मैं समय जानूं?",

            "हाय! आपकी नौकरी की चर्चा मेरे दिमाग में है... बुध आपकी व्यावसायिक भाव का अनुकूलन कर रहा है। क्या आपको पता है क्या अवसर आ रहे हैं?",
        ],
        "health": [
            "नमस्ते! आप अभी कैसे महसूस कर रहे हो? हमने आपकी सेहत की बात की थी... कुछ सरल उपचार मदद कर सकते हैं। क्या मैं बताऊं?",

            "हाय! आपकी सेहत की बात सोच रहा था... छठा भाव का स्वामी अच्छी तरह से स्थित है, जो ठीक है। क्या मैं कुछ व्यक्तिगत उपचार सुझाऊं?",

            "नमस्ते! आशा है आप ठीक महसूस कर रहे हों... आपकी सेहत की भावें कुंडली विश्लेषण में मजबूत दिख रही हैं। क्या मैं ज्योतिषीय उपचार सुझाऊं?",
        ],
        "education": [
            "हाय! आपकी पढ़ाई कैसी चल रही है? हमने आपकी परीक्षा की बात की थी... आपकी पांचवीं भाव बहुत मजबूत है! क्या मैं देखूं कि तारे क्या कहते हैं?",

            "नमस्ते! याद है न आपकी शिक्षा की चर्चा? बृहस्पति इस महीने आपकी शिक्षा भाव को आशीर्वाद दे रहा है। क्या मैं आपकी कुंडली का विश्लेषण करूं?",

            "हाय! आपकी पढ़ाई की बात सोच रहा था... बुध की स्थिति एकाग्रता के लिए उत्कृष्ट है। क्या मैं अनुकूल समय के लिए जांच करूं?",
        ]
    }

    # Kundli-based messages when no topic detected
    kundli_messages_en = [
        "Hey! It's been a while... Your kundli shows some interesting planetary movements this week. Should we check what the stars have in store for you?",

        "Namaste! Your birth chart indicates this is a good time for new beginnings. The planets are aligned in your favor - want me to analyze what this means for you?",

        "Hi! Your current dasha period looks quite favorable according to your kundli. The coming weeks might bring some important changes. Shall we check your predictions?",

        "Hey! Your Moon sign's position suggests this is a good time to revisit your goals. Your kundli has some insights about your near future. Want to take a look?",

        "Namaste! Was looking at your birth chart... Your ascendant lord is strong right now, which is excellent for overall growth. Should we explore what this means for you?",
    ]

    kundli_messages_hi = [
        "नमस्ते! काफी दिन हो गए... आपकी कुंडली कुछ दिलचस्प ग्रह गतिविधि दिखा रही है। क्या हम देखें कि तारे क्या कहते हैं?",

        "हाय! आपकी जन्म कुंडली बताती है कि यह नई शुरुआत के लिए अच्छा समय है। ग्रह आपके पक्ष में हैं - क्या मैं विश्लेषण करूं?",

        "नमस्ते! आपकी वर्तमान दशा आपकी कुंडली के अनुसार काफी अनुकूल दिख रही है। आने वाले हफ्तों में कुछ महत्वपूर्ण बदलाव आ सकते हैं। क्या हम जांचें?",

        "हाय! आपकी चंद्र राशि की स्थिति बताती है कि यह अपने लक्ष्यों को दोबारा देखने का अच्छा समय है। आपकी कुंडली में आपके नज़दीक भविष्य के बारे में कुछ जानकारी है। क्या देखना चाहते हैं?",

        "नमस्ते! आपकी जन्म कुंडली देख रहा था... आपका लग्न भाव का स्वामी अभी मजबूत है, जो समग्र विकास के लिए उत्कृष्ट है। क्या हम इसका अर्थ समझें?",
    ]

    # Select message based on language and topic
    if user_language == "hi":
        # Hindi messages
        if detected_topic and detected_topic in topic_messages_hi:
            import random
            messages = topic_messages_hi[detected_topic]
            return random.choice(messages)
        else:
            import random
            return random.choice(kundli_messages_hi)
    else:
        # English messages (default)
        if detected_topic and detected_topic in topic_messages_en:
            import random
            messages = topic_messages_en[detected_topic]
            return random.choice(messages)
        else:
            import random
            return random.choice(kundli_messages_en)


async def _get_recent_conversation_from_mongo(user_id: str, session_data: dict = None) -> dict:
    """
    Extract recent conversation from MongoDB session data and detect topics from USER questions.
    Stage 1: Topic-based message generation (Stage 2 will add Mem0 personalization)
    """
    result = {
        "detected_topic": None,
        "detected_language": "en",  # Default to English
        "last_questions": []
    }

    try:
        logger.info(f"[Proactive Nudge] Extracting conversation from session data for {user_id}")

        # Extract messages from session_data if provided
        if not session_data:
            logger.warning(f"[Proactive Nudge] No session data provided for {user_id}")
            return result

        # Debug: Log what keys are available in session_data
        logger.debug(f"[Proactive Nudge] Session data keys: {list(session_data.keys())}")

        messages = session_data.get("messages", [])
        if not messages:
            logger.warning(f"[Proactive Nudge] No 'messages' key in session data for {user_id}")
            logger.debug(f"[Proactive Nudge] Session data sample: {str(session_data)[:500]}")
            return result

        # Extract user questions only
        user_questions = []
        for msg in messages:
            if msg.get("role") == "user":
                text = msg.get("text", "")
                if text:
                    user_questions.append(text)

        if not user_questions:
            logger.info(f"[Proactive Nudge] No user questions found for {user_id}")
            return result

        # Analyze only last 5 questions (RECENT context matters most!)
        recent_questions = user_questions[-5:]
        result["last_questions"] = recent_questions
        logger.info(f"[Proactive Nudge] Total questions: {len(user_questions)}, analyzing last 5 for recent context")
        logger.debug(f"[Proactive Nudge] Recent questions: {[q[:50]+'...' if len(q)>50 else q for q in recent_questions]}")

        # Language detection: Hindi vs English
        # Detect Hindi by checking for Devanagari characters or common Hindi words
        def detect_language(texts):
            hindi_indicators = [
                # Common Hindi words
                "है", "हूं", "क्या", "कैसे", "कहां", "कब", "किस", "कितना",
                "मेरा", "मेरी", "आपकी", "आप", "हम", "मुझे", "मुझे",
                "चाहिए", "सकता", "सकती", "होगा", "होगी", "होती",
                "जाना", "आना", "बताओ", "बताएं", "करूं", "करें",
                # Hinglish words
                "kya", "kaise", "kab", "kidhar", "kiska", "kitna",
                "mera", "meri", "apka", "apki", "hum", "mujhe",
                "chahiye", "sakta", "sakti", "hoga", "hogi",
                "jana", "aana", "batao", "batayen", "karo", "kar"
            ]

            hindi_score = 0
            total_chars = 0

            for text in texts:
                total_chars += len(text)
                text_lower = text.lower()

                # Check for Devanagari characters (Unicode range)
                if any('\u0900' <= char <= '\u097F' for char in text):
                    hindi_score += len(text)

                # Check for Hindi words
                for word in hindi_indicators:
                    if word in text_lower:
                        hindi_score += 5  # Weight more for words

            # If more than 20% Hindi content, classify as Hindi
            if total_chars > 0 and (hindi_score / total_chars) > 0.2:
                return "hi"
            return "en"

        detected_language = detect_language(recent_questions)
        result["detected_language"] = detected_language
        logger.info(f"[Proactive Nudge] Language detected: {detected_language}")

        # Topic detection from user questions
        topic_keywords = {
            "marriage": ["shaadi", "marriage", "vivah", "rishta", "life partner", "spouse",
                        "milna", "shadi", "lagna", "partner", "engagement", "sagai",
                        "marry", "wedding", "shaadi kab", "engagement kab", "meri shaadi",
                        "meri engagement", "vivah", "rishta", "divorce"],
            "career": ["job", "career", "business", "kam", "naukri", "government", "govt",
                      "service", "employment", "work", "office", "company", "interview",
                      "promotion", "salary", "earning", "new macbook", "purchase", "buy",
                      "macbook", "laptop"],
            "health": ["health", "swasthya", "illness", "bemari", "rog", "tabiyat", "bimari",
                      "disease", "sick", "problem", "pain", "upay", "remedy", "medicine",
                      "theek", "recovery", "treatment", "kaise feel", "health issue",
                      "kharab", "thek", "swasthya", "major health"],
            "education": ["study", "padhai", "education", "exam", "test", "school", "college",
                         "university", "degree", "course", "result", "marks", "grade"]
        }

        topic_scores = {"marriage": 0, "career": 0, "health": 0, "education": 0}

        # Score each topic based on keyword matches
        for question in recent_questions:
            question_lower = question.lower()
            for topic, keywords in topic_keywords.items():
                for keyword in keywords:
                    if keyword in question_lower:
                        topic_scores[topic] += 1

        # Find topic with highest score
        max_score = max(topic_scores.values())
        if max_score > 0:
            # Get topic with highest score
            detected_topic = max(topic_scores, key=topic_scores.get)
            result["detected_topic"] = detected_topic
            logger.info(f"[Proactive Nudge] Topic detected: {detected_topic} (score: {max_score})")
        else:
            logger.info(f"[Proactive Nudge] No specific topic detected (scores: {topic_scores})")

        return result

    except Exception as e:
        logger.error(f"[Proactive Nudge] Error extracting conversation: {e}", exc_info=True)
        return result
