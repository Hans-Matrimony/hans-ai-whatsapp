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
MEM0_URL = os.getenv("MEM0_URL", "https://rg4g0gkk0wwkk4cc00g4sg0c.api.hansastro.com")

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


@celery_app.task
def proactive_nudge_task():
    """
    Send proactive nudges to inactive WhatsApp users.
    Runs every 5 minutes to check for users inactive for 5+ minutes.
    """
    import asyncio
    from datetime import timedelta

    try:
        logger.info("[Proactive Nudge] ===== TASK STARTED =====")
        logger.info("[Proactive Nudge] PRODUCTION MODE: Sending to all eligible users")

        # Check if within active hours (10 AM - 9 PM IST)
        from datetime import datetime
        import pytz
        ist = pytz.timezone('Asia/Kolkata')
        now_ist = datetime.now(ist)
        current_hour = now_ist.hour

        logger.info(f"[Proactive Nudge] Current time: {now_ist.strftime('%Y-%m-%d %H:%M:%S')} IST")

        if not (10 <= current_hour < 21):
            logger.info(f"[Proactive Nudge] Outside active hours ({current_hour}:00 IST), skipping")
            return {"status": "outside_active_hours", "current_hour": current_hour}

        # Query MongoDB Logger for inactive users
        logger.info(f"[Proactive Nudge] MONGO_LOGGER_URL: {MONGO_LOGGER_URL}")
        result = asyncio.run(_check_inactive_users())

        logger.info(f"[Proactive Nudge] ===== TASK COMPLETED =====")
        logger.info(f"[Proactive Nudge] Result: {result}")
        return result

    except Exception as e:
        logger.error(f"[Proactive Nudge] ===== TASK FAILED =====", exc_info=True)
        logger.error(f"[Proactive Nudge] Error: {e}")
        return {"error": str(e)}


async def _get_recent_conversation_from_mongo(user_id: str, session_data: dict = None) -> dict:
    """Extract recent conversation from MongoDB session data and detect topics from USER questions."""
    result = {
        "detected_topic": None,
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
        logger.debug(f"[Proactive Nudge] Recent questions: {[q[:50]+'...' for q in recent_questions]}")

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

        # Score each RECENT question against topics (prioritize recent context)
        # Most recent question gets 2x weight, second most gets 1.5x, etc.
        for idx, question in enumerate(recent_questions):
            question_lower = question.lower()

            # Calculate weight: most recent = 2x, second = 1.5x, third = 1.2x, etc.
            weight = 2.0 - (idx * 0.2)  # [2.0, 1.8, 1.6, 1.4, 1.2]

            logger.debug(f"[Proactive Nudge] Analyzing recent question (weight={weight:.1f}): {question_lower[:60]}...")

            for topic, keywords in topic_keywords.items():
                for kw in keywords:
                    if kw in question_lower:
                        topic_scores[topic] += weight
                        logger.debug(f"[Proactive Nudge] ✓ Topic '{topic}' +{weight:.1f} matched on '{kw}'")

        # Find highest scoring topic
        max_topic_score = 0
        for topic, score in topic_scores.items():
            if score > max_topic_score:
                max_topic_score = score
                result["detected_topic"] = topic

        logger.info(f"[Proactive Nudge] Weighted topic scores (last 5 questions, recent=2x weight): {topic_scores}")
        logger.info(f"[Proactive Nudge] ✓ Detected topic: {result['detected_topic']}")

    except Exception as e:
        logger.warning(f"[Proactive Nudge] Failed to fetch conversation from MongoDB: {e}", exc_info=True)

    return result


async def _check_inactive_users():
    """Check for inactive users and send nudges."""
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

        from datetime import timezone
        now = datetime.now(timezone.utc)
        nudges_sent = 0
        users_checked = 0

        for user in users:
            user_id = user.get("userId", "")
            if not user_id or not user_id.startswith("+"):
                continue

            # TESTING MODE: Only send to test number (DISABLED for production)
            # if PROACTIVE_NUDGE_TEST_NUMBER and user_id != PROACTIVE_NUDGE_TEST_NUMBER:
            #     logger.debug(f"[Proactive Nudge] TESTING MODE: Skipping {user_id} (not test number)")
            #     continue

            # logger.info(f"[Proactive Nudge] ✓ Processing {user_id} (matches test number)")

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

                    logger.debug(f"[Proactive Nudge] {user_id}: inactive for {inactive_minutes:.0f} mins")

                    # Skip if:
                    # - Inactive for less than 480 minutes (8 hours - production ready)
                    # - Inactive for more than 24 hours (WhatsApp window)
                    if not (480 <= inactive_minutes <= 1440):
                        logger.debug(f"[Proactive Nudge] {user_id}: inactive for {inactive_minutes:.0f} mins (skipping - too recent)")
                        continue

                    users_checked += 1
                    logger.info(f"[Proactive Nudge] ELIGIBLE: {user_id} inactive for {inactive_minutes:.0f} mins")

                    # Get recent conversation from MongoDB session data (for topic detection)
                    recent_conversation = await _get_recent_conversation_from_mongo(user_id, session)
                    logger.info(f"[Proactive Nudge] Recent conversation topic: {recent_conversation.get('detected_topic')}")

                    # Get user context from Mem0 (for name and language)
                    user_context = await _get_user_context(user_id)

                    # Override topic with MongoDB-based detection (more accurate)
                    if recent_conversation.get("detected_topic"):
                        user_context["last_topic"] = recent_conversation["detected_topic"]
                        user_context["last_questions"] = recent_conversation.get("last_questions", [])

                    logger.info(f"[Proactive Nudge] User context: {user_context}")

                    # Generate nudge message bubbles
                    nudge_messages = _generate_nudge_message(user_id, user_context, inactive_minutes)
                    logger.info(f"[Proactive Nudge] Generated {len(nudge_messages)} message bubbles")

                    if nudge_messages:
                        # Send each message bubble separately
                        phone = user_id.lstrip("+")
                        all_sent_successfully = True

                        for idx, msg in enumerate(nudge_messages):
                            # Add small delay between messages to mimic natural conversation
                            if idx > 0:
                                import asyncio
                                await asyncio.sleep(1.5)  # 1.5 second delay between bubbles

                            send_result = await _send_whatsapp_message(client, phone, msg)

                            if "error" in send_result:
                                logger.error(f"[Proactive Nudge] ✗ Failed to send bubble {idx+1} to {user_id}: {send_result}")
                                all_sent_successfully = False
                                break
                            else:
                                logger.info(f"[Proactive Nudge] ✓ Sent bubble {idx+1}/{len(nudge_messages)} to {user_id}")

                                # Log each bubble to MongoDB
                                session_id = f"whatsapp:{user_id}"
                                await _log_to_mongo(session_id, user_id, "assistant", msg, "whatsapp")

                        if all_sent_successfully:
                            nudges_sent += 1
                            logger.info(f"[Proactive Nudge] ✓ Successfully sent all {len(nudge_messages)} bubbles to {user_id} (inactive: {inactive_minutes:.0f} mins)")
                        else:
                            logger.error(f"[Proactive Nudge] ✗ Failed to send complete nudge to {user_id}")

                except Exception as e:
                    logger.error(f"[Proactive Nudge] Error processing {user_id}: {e}", exc_info=True)
                    continue

        return {
            "status": "completed",
            "users_checked": users_checked,
            "nudges_sent": nudges_sent,
            "timestamp": now.isoformat()
        }


async def _get_user_context(user_id: str) -> dict:
    """Get user context from Mem0 (name, language, last topic) using HTTP API."""
    context = {
        "name": None,
        "language": "Hinglish",  # Default for Indian users
        "last_topic": None
    }

    try:
        logger.info(f"[Proactive Nudge] Fetching context from Mem0 API for {user_id}")

        # Call Mem0 HTTP API
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{MEM0_URL}/memory/{user_id}",
                params={"limit": 100}
            )

            if response.status_code != 200:
                logger.warning(f"[Proactive Nudge] Mem0 API returned {response.status_code}: {response.text[:200]}")
                return context

            data = response.json()

            if not data.get("success"):
                logger.warning(f"[Proactive Nudge] Mem0 API returned success=False for {user_id}")
                return context

            memories = data.get("memories", [])
            logger.info(f"[Proactive Nudge] Found {len(memories)} memories for {user_id}")

            # Separate metadata memories from conversation memories
            conversation_memories = []
            metadata_memories = []

            metadata_indicators = ["name is", "date of birth is", "time of birth is", "place of birth is",
                                   "gender is", "janam tithi", "samay", "janam sthaan", "user"]

            for memory in memories:
                # Handle both dict and object formats
                if isinstance(memory, dict):
                    mem_text = memory.get("memory", "")
                else:
                    mem_text = getattr(memory, "memory", "")

                mem_lower = mem_text.lower()

                # Check if this is metadata (looks like "User Name is X")
                if any(indicator in mem_lower for indicator in metadata_indicators):
                    metadata_memories.append(mem_text)
                else:
                    conversation_memories.append(mem_text)

            logger.info(f"[Proactive Nudge] {len(metadata_memories)} metadata, {len(conversation_memories)} conversation memories")

            # Extract name from metadata first
            for mem_text in metadata_memories:
                mem_lower = mem_text.lower()
                if not context["name"]:
                    # Try "Name is X" pattern
                    if "name is" in mem_lower:
                        name_part = mem_text.split("name is")[-1].split(".")[0].strip()
                        # Get first meaningful word
                        words = name_part.replace(".", " ").split()
                        for word in words:
                            if word and word[0].isupper() and len(word) > 2 and word.lower() not in ["user", "name"]:
                                context["name"] = word
                                logger.info(f"[Proactive Nudge] ✓ Extracted name: {context['name']}")
                                break

                    # Try Hindi "Naam" pattern
                    if not context["name"] and "naam" in mem_lower:
                        # Find word after "naam"
                        for word in mem_text.split():
                            if word[0].isupper() and len(word) > 2 and word.lower() not in ["naam", "user", "kya", "hai"]:
                                context["name"] = word
                                logger.info(f"[Proactive Nudge] ✓ Extracted name from 'naam': {context['name']}")
                                break

            # Detect language and topic from conversation memories
            topic_scores = {"marriage": 0, "career": 0, "health": 0, "education": 0}
            hinglish_score = 0
            english_score = 0

            for mem_text in conversation_memories:
                mem_lower = mem_text.lower()

                # Language detection - expanded keywords
                hinglish_keywords = ["shaadi", "vivah", "kundli", "upay", "kundali", "mangal",
                                    "tabiyat", "bimari", "swasthya", "rog", "padhai", "naukri",
                                    "kam", "rishta", "kaise", "kya", "hai", "lijiye", "jiye"]
                english_keywords = ["marriage", "career", "job", "remedy", "health", "business",
                                   "illness", "education", "study", "exam", "government", "plan"]

                for kw in hinglish_keywords:
                    if kw in mem_lower:
                        hinglish_score += 1
                for kw in english_keywords:
                    if kw in mem_lower:
                        english_score += 1

                # Topic detection with comprehensive keywords
                topic_keywords = {
                    "marriage": ["shaadi", "marriage", "vivah", "rishta", "life partner", "spouse",
                                "milna", "shadi", "lagna", "partner"],
                    "career": ["job", "career", "business", "kam", "naukri", "government", "govt",
                              "service", "employment", "work", "office", "company", "interview",
                              "promotion", "salary", "earning"],
                    "health": ["health", "swasthya", "illness", "bemari", "rog", "tabiyat", "bimari",
                              "disease", "sick", "problem", "pain", "upay", "remedy", "medicine",
                              "theek", "recovery", "treatment"],
                    "education": ["study", "padhai", "education", "exam", "test", "school", "college",
                                 "university", "degree", "course", "result", "marks", "grade"]
                }

                for topic, keywords in topic_keywords.items():
                    for kw in keywords:
                        if kw in mem_lower:
                            topic_scores[topic] += 1

            # Determine language from scores
            if hinglish_score > english_score:
                context["language"] = "Hinglish"
            elif english_score > hinglish_score:
                context["language"] = "English"
            logger.info(f"[Proactive Nudge] Language scores - Hinglish: {hinglish_score}, English: {english_score}. Selected: {context['language']}")

            # Determine topic from highest score
            max_topic_score = 0
            for topic, score in topic_scores.items():
                if score > max_topic_score:
                    max_topic_score = score
                    context["last_topic"] = topic

            logger.info(f"[Proactive Nudge] Topic scores: {topic_scores}. Selected: {context['last_topic']}")
            logger.info(f"[Proactive Nudge] ✓ Final context for {user_id}: name={context['name']}, language={context['language']}, topic={context['last_topic']}")

    except httpx.TimeoutException:
        logger.warning(f"[Proactive Nudge] Mem0 API timed out for {user_id}")
    except Exception as e:
        logger.warning(f"[Proactive Nudge] Failed to get Mem0 context for {user_id}: {e}", exc_info=True)

    return context


def _generate_nudge_message(user_id: str, context: dict, inactive_minutes: float) -> list:
    """Generate personalized nudge messages as separate bubbles based on user context."""
    name = context.get("name")
    language = context.get("language", "Hinglish")
    last_topic = context.get("last_topic")

    # Ensure natural naming (avoid forced "ji" in every single template)
    n_only = name if name else "dost"

    inactive_hours = inactive_minutes / 60
    inactive_days = inactive_hours / 24

    # Topic-based personalized messages (each message bubble will be sent separately)
    topic_messages = {
        "marriage": {
            "hinglish": [
                [
                    f"Hello {n_only}! Kaise hain aajkal?",
                    "Pichli baar humne aapki shaadi ke baare mein baat ki thi. Koi progress?",
                    "Sitare abhi aapke haq mein hain, tension mat lijiye."
                ],
                [
                    f"Hi {n_only}! Sab theek chal raha hai na?",
                    "Shaadi ki planning kahan tak pohochi?",
                    "Kuch bhi zarurat ho toh batana, main yahan hoon."
                ]
            ],
            "english": [
                [
                    f"Hello {n_only}! How have you been?",
                    "We discussed your marriage plans last time. Any exciting updates?",
                    "The stars are looking favorable for you!"
                ],
                [
                    f"Hi {n_only}! Hope you're doing well.",
                    "Just checking in on the marriage plans we discussed earlier.",
                    "Let me know if you need any guidance."
                ]
            ]
        },
        "career": {
            "hinglish": [
                [
                    f"Hello {n_only}! Kaise hain aap?",
                    "Aapke job aur career ki baat hui thi, koi naya update aaya usme?",
                    "Naye opportunities aspas hi hain, lage rahiye."
                ],
                [
                    f"Hi {n_only}! Kya haal hain aajkal?",
                    "Career ki planning kaisi chal rahi hai?",
                    "Sahi time hai abhi opportunities ke liye."
                ]
            ],
            "english": [
                [
                    f"Hello {n_only}! How's everything going?",
                    "Just following up on our career discussion. Are there any new updates on the job front?",
                    "Good opportunities might be coming your way!"
                ],
                [
                    f"Hi {n_only}! Hope you're having a good week.",
                    "How is your job search going? Any developments?",
                    "Just checking in!"
                ]
            ]
        },
        "health": {
            "hinglish": [
                [
                    f"Hello {n_only}! Kaise hain aaj?",
                    "Aapki health ki baat hui thi, ab aap kaisa feel kar rahe hain?",
                    "Dhyan rakhiyega apna."
                ],
                [
                    f"Hi {n_only}! Sab theek hai na?",
                    "Aapke health ki chinta thi, ummid hai ab thik hoga sab.",
                    "Koi bhi tension ho toh bata dijiyega."
                ]
            ],
            "english": [
                [
                    f"Hello {n_only}! How are you doing today?",
                    "Following up on our previous health discussion. How are you feeling now?",
                    "I hope the remedies are helping!"
                ],
                [
                    f"Hi {n_only}! Just checking in.",
                    "How is your health now? Are you seeing any improvements?",
                    "Please take care of yourself."
                ]
            ]
        },
        "education": {
            "hinglish": [
                [
                    f"Hello {n_only}! Padhai kaisi chal rahi hai?",
                    "Studies ki baat hui thi pichli baar, kaisa progress hai?",
                    "Best of luck aapki taiyari ke liye!"
                ],
                [
                    f"Hi {n_only}! Exams ki taiyari kaisi ho rahi hai?",
                    "Padhai mein koi help chahiye toh zarur batana."
                ]
            ],
            "english": [
                [
                    f"Hello {n_only}! How are your studies going?",
                    "We talked about your education earlier, are you making good progress?",
                    "Hope everything's going well!"
                ],
                [
                    f"Hi {n_only}! Hope your studies are going well.",
                    "Any updates on your exams or education plans?",
                    "Just wanted to check in!"
                ]
            ]
        }
    }

    # Get messages for the last topic, or use general messages
    if last_topic and last_topic in topic_messages:
        messages = topic_messages[last_topic]
    else:
        # General messages when no specific topic detected
        if name:
            # Personalized messages when we know the name
            messages = {
                "hinglish": [
                    [
                        f"Hello {name}! Kaise hain aap aajkal?",
                        "Pichli baar aapse baat hui thi, kuch nayi baat karni hai kya?",
                        "Main yahan hoon aapki madad ke liye."
                    ],
                    [
                        f"Hi {name}! Kafi din ho gaye baat kiye.",
                        "Kuch bhi janna chahte ho toh puch sakte ho!",
                        "Kaisa bhi sawaal ho, zaroor batana."
                    ]
                ],
                "english": [
                    [
                        f"Hello {name}! How have you been lately?",
                        "Hope you're doing well! Any specific questions you want to discuss?",
                        "I'm here to help!"
                    ],
                    [
                        f"Hi {name}! Long time no see.",
                        "How are things with you? Do you have any questions right now?",
                        "Just wanted to check in!"
                    ]
                ]
            }
        else:
            # Generic messages when we don't know the name
            messages = {
                "hinglish": [
                    [
                        "Hello dost! Kaise hain aap aajkal?",
                        "Koi sawaal ho toh zarur puchiyega.",
                        "Main yahan hoon aapki madad ke liye."
                    ],
                    [
                        "Hi dost! Kafi din ho gaye baat kiye.",
                        "Koi bhi problem ho, toh share kar lijiye.",
                        "Kaisa bhi sawaal ho, zaroor batana."
                    ]
                ],
                "english": [
                    [
                        "Hello! How have you been lately?",
                        "Feel free to ask whenever you're ready!",
                        "I'm here to help!"
                    ],
                    [
                        "Hi there! Long time no see.",
                        "Let me know if there's anything I can help with!",
                        "Just wanted to check in!"
                    ]
                ]
            }

    # Select appropriate language messages
    if language == "Hinglish":
        template_list = messages["hinglish"]
    else:
        template_list = messages["english"]

    # Return first template (list of separate message bubbles)
    return template_list[0]
