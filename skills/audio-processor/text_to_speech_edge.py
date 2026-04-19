#!/usr/bin/env python3
"""
Text-to-Speech using Edge TTS (100% FREE)
Converts text response to audio using Microsoft Edge TTS
Only enabled for test number: 8534823036
"""
import os
import logging
import tempfile
import hashlib
from datetime import datetime
import asyncio

import edge_tts

logger = logging.getLogger(__name__)

# Test number filter - ONLY works for this number
TEST_NUMBER = "8534823036"

# Voice settings (Edge TTS voices)
VOICES = {
    "hi": "hi-IN-SwaraNeural",  # Hindi female voice
    "en": "en-IN-NeerajNeural"   # Indian English male voice
}


def is_test_number(phone: str) -> bool:
    """
    Check if phone number is the test number.

    Args:
        phone: Phone number (with or without +)

    Returns:
        True if test number, False otherwise
    """
    # Normalize phone number (remove +, spaces, dashes)
    normalized = phone.replace("+", "").replace(" ", "").replace("-", "")
    return normalized == TEST_NUMBER


async def text_to_speech_edge(text: str, language: str = "hi") -> bytes | None:
    """
    Convert text to speech using Edge TTS (100% FREE).

    Args:
        text: Text to convert to speech
        language: "hi" for Hindi, "en" for English

    Returns:
        Audio bytes (MP3 format) or None if failed
    """
    try:
        # Select voice
        voice_id = VOICES.get(language, VOICES["hi"])

        logger.info(f"[Edge TTS] Converting text to speech ({language}, voice: {voice_id})")
        logger.info(f"[Edge TTS] Text preview: {text[:100]}...")

        # Create Edge TTS communicate object
        communicate = edge_tts.Communicate(text, voice_id)

        # Generate audio to bytes
        audio_bytes = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_bytes += chunk["data"]

        if audio_bytes:
            logger.info(f"[Edge TTS] Audio generated: {len(audio_bytes)} bytes")
            return audio_bytes
        else:
            logger.error("[Edge TTS] No audio content generated")
            return None

    except Exception as e:
        logger.error(f"[Edge TTS] Error converting text to speech: {e}")
        return None


async def save_audio_to_file(audio_bytes: bytes, user_id: str) -> str | None:
    """
    Save audio bytes to a temporary file and return the path.

    Args:
        audio_bytes: Audio file bytes
        user_id: User's WhatsApp number (for filename)

    Returns:
        File path or None if failed
    """
    try:
        # Create unique filename
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        hash_id = hashlib.md5(f"{user_id}_{timestamp}".encode()).hexdigest()[:8]
        # Remove + from user_id for filename
        clean_user_id = user_id.replace("+", "")
        filename = f"audio_{clean_user_id}_{hash_id}_{timestamp}.mp3"

        # Save to temp directory
        temp_dir = tempfile.gettempdir()
        file_path = os.path.join(temp_dir, filename)

        # Write in thread to avoid blocking
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: open(file_path, "wb").write(audio_bytes))

        logger.info(f"[Edge TTS] Audio saved to: {file_path}")
        return file_path

    except Exception as e:
        logger.error(f"[Edge TTS] Error saving audio: {e}")
        return None


async def text_to_speech_edge_async(text: str, language: str = "hi", user_id: str = "user") -> tuple[bytes, str] | None:
    """
    Async wrapper for text_to_speech_edge. Returns (audio_bytes, file_path).

    Args:
        text: Text to convert
        language: Language code
        user_id: User ID for filename

    Returns:
        Tuple of (audio_bytes, file_path) or None
    """
    audio_bytes = await text_to_speech_edge(text, language)

    if audio_bytes:
        # Save to file
        file_path = await save_audio_to_file(audio_bytes, user_id)
        return (audio_bytes, file_path)

    return None


def detect_language(text: str) -> str:
    """
    Detect if text is Hindi or English.
    Simple heuristic: checks for Devanagari script.

    Args:
        text: Text to analyze

    Returns:
        "hi" for Hindi, "en" for English
    """
    # Check for Devanagari script (Hindi)
    if any(char for char in text if '\u0900' <= char <= '\u097F'):
        return "hi"
    return "en"
