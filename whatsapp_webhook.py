#!/usr/bin/env python3
"""
WhatsApp Webhook Handler for Hans AI Dashboard
Production Ready Version
"""

import os
import logging
import json
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, BackgroundTasks, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

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

PORT = int(os.getenv("PORT", "8003"))

FB_API_URL = "https://graph.facebook.com/v18.0"

# =============================================================================
# Rate Limiter
# =============================================================================

limiter = Limiter(key_func=get_remote_address)

# =============================================================================
# HTTP Client
# =============================================================================

http_client: Optional[httpx.AsyncClient] = None


async def init_http_client():
    global http_client
    http_client = httpx.AsyncClient(timeout=60.0)
    logger.info("HTTP client initialized")


async def close_http_client():
    global http_client
    if http_client:
        await http_client.aclose()
        logger.info("HTTP client closed")


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

    await init_http_client()
    logger.info("✅ Server Ready")

    yield

    logger.info("🛑 Shutting down server...")
    await close_http_client()


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
    return {
        "status": "healthy",
        "service": "whatsapp-webhook",
        "whatsapp_configured": bool(WHATSAPP_PHONE_ID),
        "openclaw_configured": bool(OPENCLAW_URL)
    }


# =============================================================================
# Webhook Verification
# =============================================================================

@app.get("/webhook/whatsapp")
async def verify_webhook(
    hub_mode: str = None,
    hub_verify_token: str = None,
    hub_challenge: str = None
):
    if hub_mode == "subscribe" and hub_verify_token == WHATSAPP_VERIFY_TOKEN:
        logger.info("Webhook verified successfully")
        return Response(content=hub_challenge, status_code=200)

    raise HTTPException(status_code=403, detail="Verification failed")


# =============================================================================
# Incoming Webhook
# =============================================================================

@app.post("/webhook/whatsapp")
@limiter.limit("100/minute")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks):
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
                text = msg.get("text", {}).get("body", "")

                if text:
                    background_tasks.add_task(
                        process_message,
                        phone,
                        text,
                        message_id
                    )

        return {"status": "ok"}

    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        return {"status": "error"}


# =============================================================================
# Message Processing
# =============================================================================

async def process_message(phone: str, message: str, message_id: str):
    logger.info(f"Incoming from {phone}: {message}")

    if not OPENCLAW_URL:
        logger.warning("OPENCLAW_URL not set")
        return

    try:
        headers = {
            "Content-Type": "application/json"
        }
        if OPENCLAW_GATEWAY_TOKEN:
            headers["Authorization"] = f"Bearer {OPENCLAW_GATEWAY_TOKEN}"

        # Use OpenAI Chat Completions format
        payload = {
            "model": "openai/gpt-4o",  # Ensure this matches a valid model in OpenClaw
            "messages": [
                {"role": "user", "content": message}
            ],
            "user": phone  # Pass phone number as user ID for context
        }

        response = await http_client.post(
            f"{OPENCLAW_URL}/v1/chat/completions",
            json=payload,
            headers=headers
        )

        if response.status_code == 200:
            data = response.json()
            # Parse OpenAI response format
            if "choices" in data and len(data["choices"]) > 0:
                reply = data["choices"][0]["message"]["content"]
                if reply:
                    await send_whatsapp_message(phone, reply)
            else:
                 logger.warning(f"Unexpected response format: {data}")
        else:
             logger.error(f"OpenClaw error {response.status_code}: {response.text}")

    except Exception as e:
        logger.error(f"Processing error: {e}", exc_info=True)


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

    response = await http_client.post(url, headers=headers, json=payload)

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
