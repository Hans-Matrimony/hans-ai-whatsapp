#!/usr/bin/env python3
"""
Audio Transcription using Groq (FREE & Fast)
Transcribes audio to text using Groq's Whisper API
"""
import os
import logging
import tempfile
import httpx

logger = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Supported audio formats by WhatsApp
SUPPORTED_FORMATS = [
    "audio/ogg",
    "audio/amr",
    "audio/mpeg",
    "audio/mp4",
    "audio/wav",
    "audio/aac"
]


async def transcribe_audio(audio_bytes: bytes, mime_type: str = "audio/ogg") -> str | None:
    """
    Transcribe audio bytes to text using Groq Whisper API.

    Args:
        audio_bytes: Audio file bytes
        mime_type: MIME type of the audio file

    Returns:
        Transcribed text or None if failed
    """
    if not GROQ_API_KEY:
        logger.error("GROQ_API_KEY not set")
        return None

    try:
        # Determine file extension from mime type
        ext_map = {
            "audio/ogg": ".ogg",
            "audio/amr": ".amr",
            "audio/mpeg": ".mp3",
            "audio/mp4": ".mp4",
            "audio/wav": ".wav",
            "audio/aac": ".aac"
        }
        ext = ext_map.get(mime_type, ".ogg")

        # Create temporary file
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as temp_file:
            temp_file.write(audio_bytes)
            temp_file_path = temp_file.name

        try:
            # Upload and transcribe using Groq
            async with httpx.AsyncClient(timeout=60.0) as client:
                # Open file for upload
                with open(temp_file_path, "rb") as f:
                    files = {
                        "file": (f"audio{ext}", f, f"audio/*")
                    }

                    data = {
                        "model": "whisper-large-v3",
                        "response_format": "text",
                        "temperature": 0.0
                    }

                    headers = {
                        "Authorization": f"Bearer {GROQ_API_KEY}"
                    }

                    logger.info(f"[Audio] Transcribing audio with Groq Whisper (size: {len(audio_bytes)} bytes)")

                    response = await client.post(
                        "https://api.groq.com/openai/v1/audio/transcriptions",
                        headers=headers,
                        data=data,
                        files=files,
                        timeout=60.0
                    )

                    if response.status_code == 200:
                        # Handle both JSON and text responses from Groq
                        content_type = response.headers.get("content-type", "")
                        if "application/json" in content_type:
                            result = response.json()
                            transcribed_text = result.get("text", "").strip()
                        else:
                            # Plain text response
                            transcribed_text = response.text.strip()

                        if transcribed_text:
                            logger.info(f"[Audio] Transcription successful: {transcribed_text[:50]}...")
                            return transcribed_text
                        else:
                            logger.warning("[Audio] Empty transcription")
                            return None
                    else:
                        logger.error(f"[Audio] Groq API error {response.status_code}: {response.text}")
                        return None

        finally:
            # Clean up temporary file
            import os
            try:
                os.unlink(temp_file_path)
            except:
                pass

    except Exception as e:
        logger.error(f"[Audio] Transcription error: {e}")
        return None


def transcribe_audio_sync(audio_bytes: bytes, mime_type: str = "audio/ogg") -> str | None:
    """
    Synchronous wrapper for transcription (for non-async contexts).
    """
    import asyncio
    return asyncio.run(transcribe_audio(audio_bytes, mime_type))


def is_audio_message(message_type: str) -> bool:
    """Check if message is an audio message."""
    return message_type in ["audio", "voice", "audio_message"]
