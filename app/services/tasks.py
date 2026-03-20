"""
Celery tasks for asynchronous message processing
"""
import os
import re
import logging
import base64
import tempfile
from datetime import datetime
from typing import Optional, Tuple, List
from pathlib import Path

import httpx
from app.services.celery_app import celery_app

logger = logging.getLogger(__name__)

# Configuration from environment
OPENCLAW_URL = os.getenv("OPENCLAW_URL")
OPENCLAW_GATEWAY_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN")
MONGO_LOGGER_URL = os.getenv("MONGO_LOGGER_URL")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
FB_API_URL = "https://graph.facebook.com/v18.0"


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

    for line in text.split("\n"):
        stripped = line.strip()

        # Check for MEDIA_BASE64: <mime_type> <base64_data>
        b64_match = re.match(r'^MEDIA_BASE64:\s*(\S+)\s+(\S+)$', stripped)
        if b64_match:
            mime_type = b64_match.group(1)
            b64_data = b64_match.group(2)
            media_items.append({"type": "base64", "value": b64_data, "mime_type": mime_type})
            logger.info(f"Found MEDIA_BASE64 in response: mime={mime_type}, len={len(b64_data)}")
            continue

        # Check for MEDIA: <path_or_url>
        media_match = re.match(r'^MEDIA:\s*(.+)$', stripped)
        if media_match:
            media_path = media_match.group(1).strip().strip('"').strip("'")

            # Direct URL
            if media_path.startswith('http://') or media_path.startswith('https://'):
                media_items.append({"type": "url", "value": media_path})
                logger.info(f"Found MEDIA URL in response: {media_path}")
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
            if any(host in url for host in ['oaidalleapiprodscus', 'blob.core.windows.net', 'images.unsplash', 'imgur']):
                media_items.append({"type": "url", "value": url})
                logger.info(f"Found image URL in markdown link: {url[:80]}...")
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

    if not OPENCLAW_URL:
        logger.warning("OPENCLAW_URL not set")
        return {"error": "OpenClaw URL not configured"}

    async with httpx.AsyncClient(timeout=120.0) as client:
        # Send typing indicator
        await _send_typing_indicator(client, message_id)

        headers = {
            "Content-Type": "application/json",
            "x-openclaw-session-key": f"agent:astrologer:whatsapp:direct:+{phone}",
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

        # Extract reply text from response
        reply = None
        if "output" in data:
            for item in data["output"]:
                if item.get("content"):
                    for content in item["content"]:
                        if content.get("text"):
                            reply = content["text"]
                            break

        if not reply:
            return {"status": "no_reply"}

        # Parse MEDIA: / MEDIA_BASE64: tokens from response
        clean_reply, media_items = _extract_media_from_reply(reply)

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
                        dl_response = await dl_client.get(media_item["value"])
                        if dl_response.status_code != 200:
                            logger.error(f"Failed to download DALL-E image: {dl_response.status_code}")
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


async def _log_to_mongo(session_id: str, user_id: str, role: str, text: str, channel: str, message_type: str = "text", media_info: dict = None):
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
