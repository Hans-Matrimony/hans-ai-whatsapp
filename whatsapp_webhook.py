#!/usr/bin/env python3
"""
WhatsApp Webhook Handler for Hans AI Dashboard
Production Ready Version with Celery Task Queue
"""

import os
import logging
from typing import Optional
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel
from dotenv import load_dotenv
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import Query

from app.services.tasks import process_message_task

# =============================================================================
# Load Environment
# =============================================================================

load_dotenv()

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger("whatsapp-webhook")

# =============================================================================
# Environment Variables
# =============================================================================

WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
OPENCLAW_URL = os.getenv("OPENCLAW_URL")
OPENCLAW_GATEWAY_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN")
MONGO_LOGGER_URL = os.getenv("MONGO_LOGGER_URL")

PORT = int(os.getenv("PORT", "8003"))

FB_API_URL = "https://graph.facebook.com/v18.0"

# =============================================================================
# Rate Limiter
# =============================================================================

limiter = Limiter(key_func=get_remote_address)

# =============================================================================
# Lifespan
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Starting WhatsApp Webhook Server...")

    # Validate required env vars
    required = [
        "WHATSAPP_VERIFY_TOKEN",
        "WHATSAPP_PHONE_ID",
        "WHATSAPP_ACCESS_TOKEN"
    ]

    missing = [v for v in required if not os.getenv(v)]
    if missing:
        logger.warning(f"⚠ Missing ENV variables: {missing}")

    logger.info("✅ Server Ready")

    yield

    logger.info("🛑 Shutting down server...")


# =============================================================================
# FastAPI App
# =============================================================================

app = FastAPI(
    title="WhatsApp Webhook",
    version="1.0.0",
    lifespan=lifespan
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# Models
# =============================================================================

class SendMessageRequest(BaseModel):
    to: str
    message: str


class MessageResponse(BaseModel):
    success: bool
    message_id: Optional[str] = None
    error: Optional[str] = None


# =============================================================================
# Health Endpoint (NO RATE LIMIT)
# =============================================================================

@app.get("/health")
async def health():
    """Health check endpoint."""
    from app.services.celery_app import celery_app

    # Check if Celery workers are available
    celery_status = "unknown"
    try:
        inspector = celery_app.control.inspect()
        active = inspector.active()
        celery_status = "connected" if active else "no_workers"
    except Exception:
        celery_status = "disconnected"

    return {
        "status": "healthy",
        "service": "whatsapp-webhook",
        "whatsapp_configured": bool(WHATSAPP_PHONE_ID),
        "openclaw_configured": bool(OPENCLAW_URL),
        "mongo_logger_configured": bool(MONGO_LOGGER_URL),
        "celery_status": celery_status
    }


# =============================================================================
# Webhook Verification
# =============================================================================

@app.get("/webhook/whatsapp")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge")
):
    logger.info(f"Verification attempt: mode={hub_mode}, token={hub_verify_token}")

    if hub_mode == "subscribe" and hub_verify_token == WHATSAPP_VERIFY_TOKEN:
        logger.info("Webhook verified successfully")
        return Response(content=hub_challenge, status_code=200)

    logger.warning("Webhook verification failed")
    raise HTTPException(status_code=403, detail="Verification failed")


# =============================================================================
# Incoming Webhook
# =============================================================================

@app.post("/webhook/whatsapp")
@limiter.limit("100/minute")
async def receive_webhook(request: Request):
    """Receive WhatsApp webhook and queue message processing via Celery."""
    try:
        data = await request.json()

        if data.get("object") != "whatsapp_business_account":
            return {"status": "ignored"}

        entry = data.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})

        if "messages" in value:
            for msg in value["messages"]:
                phone = msg.get("from")
                message_id = msg.get("id")

                # Extract message type and content
                message_type = msg.get("type", "text")
                text_content = ""
                media_info = None

                if message_type == "text":
                    text_content = msg.get("text", {}).get("body", "")
                elif message_type == "image":
                    media_id = msg.get("image", {}).get("id")
                    caption = msg.get("image", {}).get("caption", "")
                    text_content = f"[Image: {caption}]" if caption else "[Image]"
                    media_info = {"type": "image", "id": media_id, "caption": caption}
                elif message_type == "audio":
                    media_id = msg.get("audio", {}).get("id")
                    text_content = "[Audio message]"
                    media_info = {"type": "audio", "id": media_id}
                elif message_type == "video":
                    media_id = msg.get("video", {}).get("id")
                    caption = msg.get("video", {}).get("caption", "")
                    text_content = f"[Video: {caption}]" if caption else "[Video]"
                    media_info = {"type": "video", "id": media_id, "caption": caption}
                elif message_type == "document":
                    media_id = msg.get("document", {}).get("id")
                    filename = msg.get("document", {}).get("filename", "")
                    text_content = f"[Document: {filename}]" if filename else "[Document]"
                    media_info = {"type": "document", "id": media_id, "filename": filename}
                elif message_type == "sticker":
                    media_id = msg.get("sticker", {}).get("id")
                    text_content = "[Sticker]"
                    media_info = {"type": "sticker", "id": media_id}
                else:
                    # Unknown type - log but still process
                    text_content = f"[{message_type}]"
                    logger.info(f"Unknown message type: {message_type}")

                # Queue task to Celery for async processing
                process_message_task.delay(
                    phone=phone,
                    message=text_content,
                    message_id=message_id,
                    message_type=message_type,
                    media_info=media_info
                )
                logger.info(f"Queued {message_type} from {phone} for processing")

        return {"status": "ok"}

    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        return {"status": "error"}


# =============================================================================
# Send Message API
# =============================================================================

@app.post("/send", response_model=MessageResponse)
@limiter.limit("60/minute")
async def send_message(request: Request, body: SendMessageRequest):
    try:
        message_id = await send_whatsapp_message(body.to, body.message)
        if message_id:
            return MessageResponse(success=True, message_id=message_id)
        return MessageResponse(success=False, error="Failed to send")
    except Exception as e:
        return MessageResponse(success=False, error=str(e))


async def send_whatsapp_message(phone: str, message: str):
    """Send message via WhatsApp API (for /send endpoint)."""
    if not WHATSAPP_PHONE_ID or not WHATSAPP_ACCESS_TOKEN:
        logger.error("WhatsApp credentials missing")
        return None

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

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, headers=headers, json=payload)

        if response.status_code in [200, 201]:
            return response.json().get("messages", [{}])[0].get("id")

        logger.error(f"WhatsApp send failed: {response.text}")
        return None


# =============================================================================
# Root
# =============================================================================

@app.get("/")
async def root():
    return {"service": "WhatsApp Webhook", "status": "running"}


# =============================================================================
# Run
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("whatsapp_webhook:app", host="0.0.0.0", port=PORT)