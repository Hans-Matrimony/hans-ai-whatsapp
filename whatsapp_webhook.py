#!/usr/bin/env python3
"""
WhatsApp Webhook Handler for Hans AI Dashboard

Integrates Meta WhatsApp Cloud API with OpenClaw Gateway
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

# Load environment variables
load_dotenv()

# Configure logging
log_level = os.getenv("LOG_LEVEL", "info").upper()
logging.basicConfig(
    level=getattr(logging, log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Rate limiter
limiter = Limiter(key_func=get_remote_address)

# Configuration
WHATSAPP_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_BUSINESS_ID = os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID", "")
OPENCLAW_URL = os.getenv("OPENCLAW_URL", "")
OPENCLAW_TIMEOUT = int(os.getenv("OPENCLAW_TIMEOUT", "60"))
MESSAGE_TIMEOUT = int(os.getenv("MESSAGE_TIMEOUT", "30"))
MAX_MESSAGE_LENGTH = int(os.getenv("MAX_MESSAGE_LENGTH", "4096"))
ENABLE_QUEUE = os.getenv("ENABLE_MESSAGE_QUEUE", "true").lower() == "true"

# Facebook API URL
FB_API_URL = "https://graph.facebook.com/v18.0"

# HTTP Client (will be initialized at startup)
http_client: Optional[httpx.AsyncClient] = None


# =============================================================================
# Pydantic Models
# =============================================================================

class SendMessageRequest(BaseModel):
    """Request model for sending messages"""
    to: str = Field(..., description="Phone number (E.164 format, without +)")
    message: str = Field(..., min_length=1, max_length=MAX_MESSAGE_LENGTH)
    type: str = Field(default="text", description="Message type: text, template")
    components: Optional[list] = None


class InteractiveMessageRequest(BaseModel):
    """Request model for interactive messages"""
    to: str = Field(..., description="Phone number")
    text: str = Field(..., description="Message text")
    buttons: list = Field(..., description="Button options")


class MessageResponse(BaseModel):
    """Response model for message operations"""
    success: bool
    message_id: Optional[str] = None
    error: Optional[str] = None


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    service: str
    version: str
    connections: Dict[str, Any]


# =============================================================================
# HTTP Client Management
# =============================================================================

async def init_http_client():
    """Initialize HTTP client"""
    global http_client
    timeout = httpx.Timeout(OPENCLAW_TIMEOUT, connect=10.0)
    http_client = httpx.AsyncClient(timeout=timeout)
    logger.info("HTTP client initialized")


async def close_http_client():
    """Close HTTP client"""
    global http_client
    if http_client:
        await http_client.aclose()
        logger.info("HTTP client closed")


# =============================================================================
# Message Processing
# =============================================================================

async def process_whatsapp_message(
    phone: str,
    message: str,
    message_id: str,
    metadata: Optional[Dict[str, Any]] = None
):
    """Process incoming WhatsApp message via OpenClaw"""
    try:
        logger.info(f"Processing message from {phone}: {message[:50]}...")

        payload = {
            "channel": "whatsapp",
            "from": phone,
            "message": message,
            "message_id": message_id,
            "metadata": metadata or {}
        }

        if not OPENCLAW_URL:
            logger.warning("OPENCLAW_URL not set, skipping processing")
            return

        response = await http_client.post(
            f"{OPENCLAW_URL}/webhook/whatsapp",
            json=payload,
            timeout=MESSAGE_TIMEOUT
        )

        if response.status_code == 200:
            data = response.json()

            # Send response back to WhatsApp
            if data.get("response"):
                await send_whatsapp_message(
                    phone=phone,
                    message=data["response"]
                )
                logger.info(f"Response sent to {phone}")
            elif data.get("messages"):
                for msg in data["messages"]:
                    await send_whatsapp_message(
                        phone=phone,
                        message=msg
                    )
        else:
            logger.error(f"OpenClaw returned {response.status_code}: {response.text}")

    except httpx.TimeoutException:
        logger.error(f"Timeout processing message from {phone}")
    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)


async def send_whatsapp_message(phone: str, message: str) -> Optional[str]:
    """Send message via WhatsApp API"""
    try:
        # Ensure phone has + prefix
        if not phone.startswith("+"):
            phone = f"+{phone}"

        url = f"{FB_API_URL}/{WHATSAPP_PHONE_ID}/messages"
        headers = {
            "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }

        payload = {
            "messaging_product": "whatsapp",
            "to": phone.lstrip("+"),  # API wants number without +
            "type": "text",
            "text": {"body": message}
        }

        response = await http_client.post(
            url,
            headers=headers,
            json=payload
        )

        if response.status_code in [200, 201]:
            data = response.json()
            message_id = data.get("contacts", [{}])[0].get("input", "")
            logger.info(f"Message sent to {phone}, ID: {message_id}")
            return message_id
        else:
            logger.error(f"Failed to send message: {response.status_code} - {response.text}")
            return None

    except Exception as e:
        logger.error(f"Error sending WhatsApp message: {e}", exc_info=True)
        return None


async def mark_message_read(message_id: str):
    """Mark a message as read"""
    try:
        url = f"{FB_API_URL}/{WHATSAPP_PHONE_ID}/messages"
        headers = {
            "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }

        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id
        }

        await http_client.post(url, headers=headers, json=payload)
        logger.debug(f"Message {message_id} marked as read")

    except Exception as e:
        logger.error(f"Error marking message as read: {e}")


# =============================================================================
# Lifespan Context Manager
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan"""
    # Startup
    logger.info("🚀 Starting WhatsApp Webhook Handler...")
    await init_http_client()
    logger.info("✅ WhatsApp Webhook Handler ready!")

    yield

    # Shutdown
    logger.info("🛑 Shutting down WhatsApp Webhook Handler...")
    await close_http_client()
    logger.info("👋 WhatsApp Webhook Handler stopped")


# =============================================================================
# FastAPI Application
# =============================================================================

cors_origins = os.getenv("CORS_ORIGINS", "*").split(",")

app = FastAPI(
    title="WhatsApp Webhook Handler",
    description="Meta WhatsApp Cloud API integration for Hans AI Dashboard",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# =============================================================================
# Exception Handlers
# =============================================================================

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Handle uncaught exceptions"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "Internal server error",
            "detail": str(exc) if os.getenv("DEBUG") == "true" else None
        }
    )


# =============================================================================
# Health Endpoints
# =============================================================================

@app.get("/health", response_model=HealthResponse, tags=["Health"])
@limiter.limit("60/minute")
async def health_check() -> HealthResponse:
    """
    Health check endpoint

    Returns the current status of the webhook handler and its connections.
    """
    return HealthResponse(
        status="healthy",
        service="whatsapp-webhook",
        version="1.0.0",
        connections={
            "openclaw": {
                "url": OPENCLAW_URL,
                "status": "configured" if OPENCLAW_URL else "not_configured"
            },
            "whatsapp": {
                "phone_id": WHATSAPP_PHONE_ID,
                "business_id": WHATSAPP_BUSINESS_ID
            }
        }
    )


@app.get("/", tags=["Root"])
async def root() -> Dict[str, Any]:
    """Root endpoint with API information"""
    return {
        "name": "WhatsApp Webhook Handler",
        "version": "1.0.0",
        "description": "Meta WhatsApp Cloud API integration for Hans AI Dashboard",
        "endpoints": {
            "health": "/health",
            "docs": "/docs",
            "webhook_verify": "/webhook/whatsapp (GET)",
            "webhook_receive": "/webhook/whatsapp (POST)",
            "send_message": "/send"
        }
    }


# =============================================================================
# Webhook Endpoints
# =============================================================================

@app.get("/webhook/whatsapp", tags=["Webhook"])
async def verify_webhook(
    mode: str = None,
    token: str = None,
    challenge: str = None
):
    """
    Verify webhook with Meta

    Meta calls this endpoint when setting up the webhook.
    """
    if mode == "subscribe" and token == WHATSAPP_TOKEN:
        logger.info("Webhook verified successfully")
        return Response(content=challenge, status_code=200)

    logger.warning(f"Webhook verification failed: mode={mode}, token={token[:10] if token else None}")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Verification failed"
    )


@app.post("/webhook/whatsapp", tags=["Webhook"])
async def webhook_message(
    request: Request,
    background_tasks: BackgroundTasks
):
    """
    Receive incoming WhatsApp messages from Meta

    This endpoint receives all webhook events from Meta WhatsApp Cloud API.
    """
    try:
        data = await request.json()
        logger.debug(f"Received webhook: {json.dumps(data, indent=2)}")

        # Handle webhook notification
        if data.get("object") == "whatsapp_business_account":
            entry = data.get("entry", [{}])[0]
            changes = entry.get("changes", [{}])[0]
            value = changes.get("value", {})

            # Process messages
            if "messages" in value:
                messages = value["messages"]

                for msg in messages:
                    # Get message details
                    phone = msg.get("from")
                    message_id = msg.get("id")
                    timestamp = msg.get("timestamp")

                    # Get message content based on type
                    msg_type = msg.get("type")

                    if msg_type == "text":
                        text = msg.get("text", {}).get("body", "")

                        # Process in background
                        background_tasks.add_task(
                            process_whatsapp_message,
                            phone=phone,
                            message=text,
                            message_id=message_id,
                            metadata={"type": "text", "timestamp": timestamp}
                        )

                    elif msg_type == "audio":
                        # Handle audio messages
                        audio_id = msg.get("audio", {}).get("id")
                        logger.info(f"Received audio from {phone}: {audio_id}")
                        # TODO: Process audio with Whisper

                    elif msg_type == "image":
                        # Handle image messages
                        image_id = msg.get("image", {}).get("id")
                        caption = msg.get("image", {}).get("caption", "")
                        logger.info(f"Received image from {phone}: {image_id}")
                        background_tasks.add_task(
                            process_whatsapp_message,
                            phone=phone,
                            message=f"[Image] {caption}" if caption else "[Image]",
                            message_id=message_id,
                            metadata={"type": "image", "media_id": image_id}
                        )

                    elif msg_type == "video":
                        # Handle video messages
                        video_id = msg.get("video", {}).get("id")
                        caption = msg.get("video", {}).get("caption", "")
                        logger.info(f"Received video from {phone}: {video_id}")
                        background_tasks.add_task(
                            process_whatsapp_message,
                            phone=phone,
                            message=f"[Video] {caption}" if caption else "[Video]",
                            message_id=message_id,
                            metadata={"type": "video", "media_id": video_id}
                        )

                    elif msg_type == "document":
                        # Handle document messages
                        document_id = msg.get("document", {}).get("id")
                        filename = msg.get("document", {}).get("filename", "")
                        logger.info(f"Received document from {phone}: {document_id}")
                        background_tasks.add_task(
                            process_whatsapp_message,
                            phone=phone,
                            message=f"[Document] {filename}",
                            message_id=message_id,
                            metadata={"type": "document", "media_id": document_id, "filename": filename}
                        )

                    elif msg_type == "interactive":
                        # Handle interactive button responses
                        interactive_response = msg.get("interactive", {})
                        interactive_type = interactive_response.get("type")

                        if interactive_type == "button_reply":
                            button_id = interactive_response.get("button_reply", {}).get("id")
                            button_title = interactive_response.get("button_reply", {}).get("title")
                            background_tasks.add_task(
                                process_whatsapp_message,
                                phone=phone,
                                message=f"[Button] {button_title}",
                                message_id=message_id,
                                metadata={"type": "button", "button_id": button_id}
                            )

                        elif interactive_type == "list_reply":
                            list_id = interactive_response.get("list_reply", {}).get("id")
                            list_title = interactive_response.get("list_reply", {}).get("title")
                            background_tasks.add_task(
                                process_whatsapp_message,
                                phone=phone,
                                message=f"[List Selection] {list_title}",
                                message_id=message_id,
                                metadata={"type": "list", "list_id": list_id}
                            )

            # Handle message status updates
            elif "statuses" in value:
                statuses = value["statuses"]
                for status in statuses:
                    # Could log delivery/read receipts here
                    logger.debug(f"Message status: {status.get('status')} for {status.get('recipient_id')}")

        return {"status": "ok"}

    except json.JSONDecodeError:
        logger.error("Invalid JSON in webhook payload")
        raise HTTPException(status_code=400, detail="Invalid JSON")
    except Exception as e:
        logger.error(f"Error processing webhook: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


# =============================================================================
# Message Sending Endpoints
# =============================================================================

@app.post("/send", response_model=MessageResponse, tags=["Messages"])
@limiter.limit("60/minute")
async def send_message(request: SendMessageRequest) -> MessageResponse:
    """
    Send a text message via WhatsApp

    - **to**: Phone number (E.164 format, without +)
    - **message**: Message text
    - **type**: Message type (default: text)
    """
    try:
        message_id = await send_whatsapp_message(
            phone=request.to,
            message=request.message
        )

        if message_id:
            return MessageResponse(success=True, message_id=message_id)
        else:
            return MessageResponse(
                success=False,
                error="Failed to send message"
            )

    except Exception as e:
        logger.error(f"Error in send_message: {e}", exc_info=True)
        return MessageResponse(
            success=False,
            error=str(e)
        )


@app.post("/send/interactive", tags=["Messages"])
@limiter.limit("30/minute")
async def send_interactive(request: InteractiveMessageRequest):
    """
    Send an interactive message with buttons

    - **to**: Phone number
    - **text**: Message text
    - **buttons**: List of button objects {"id": "...", "title": "..."}
    """
    try:
        # Ensure phone has + prefix
        phone = request.to
        if not phone.startswith("+"):
            phone = f"+{phone}"

        url = f"{FB_API_URL}/{WHATSAPP_PHONE_ID}/messages"
        headers = {
            "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }

        # Build interactive message
        buttons = []
        for i, btn in enumerate(request.buttons[:3]):  # Max 3 buttons
            buttons.append({
                "type": "reply",
                "reply": {
                    "id": btn.get("id", f"btn_{i}"),
                    "title": btn.get("title", f"Button {i+1}")
                }
            })

        payload = {
            "messaging_product": "whatsapp",
            "to": phone.lstrip("+"),
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": request.text},
                "action": {"buttons": buttons}
            }
        }

        response = await http_client.post(url, headers=headers, json=payload)

        if response.status_code in [200, 201]:
            data = response.json()
            message_id = data.get("contacts", [{}])[0].get("input", "")
            return MessageResponse(success=True, message_id=message_id)
        else:
            return MessageResponse(
                success=False,
                error=f"Failed: {response.text}"
            )

    except Exception as e:
        logger.error(f"Error sending interactive message: {e}", exc_info=True)
        return MessageResponse(success=False, error=str(e))


# =============================================================================
# Utility Endpoints
# =============================================================================

@app.post("/mark-read", tags=["Utility"])
async def mark_read(message_id: str):
    """Mark a message as read"""
    await mark_message_read(message_id)
    return {"success": True}


@app.get("/status", tags=["Utility"])
async def get_status():
    """Get service status"""
    return {
        "status": "running",
        "webhook_configured": bool(WHATSAPP_TOKEN and WHATSAPP_PHONE_ID),
        "openclaw_configured": bool(OPENCLAW_URL),
        "version": "1.0.0"
    }


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8003"))
    host = os.getenv("HOST", "0.0.0.0")

    uvicorn.run(
        "whatsapp_webhook:app",
        host=host,
        port=port,
        reload=os.getenv("DEBUG") == "true",
        log_level=log_level.lower()
    )
