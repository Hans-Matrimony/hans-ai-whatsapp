#!/usr/bin/env python3
"""
Audio Message Handler for WhatsApp Bot
Orchestrates the complete audio-to-audio flow:
Audio → Transcription → AI Processing → TTS → Send Audio
"""
import os
import logging

from .transcribe import transcribe_audio, is_audio_message
from .text_to_speech import text_to_speech_async, detect_language

logger = logging.getLogger(__name__)


async def process_audio_message(
    phone: str,
    audio_bytes: bytes,
    mime_type: str,
    openclaw_response_text: str
) -> dict:
    """
    Process audio message completely:
    1. Transcribe audio to text
    2. Process text (already done by caller)
    3. Convert response to audio
    4. Return audio file path

    Args:
        phone: User's WhatsApp number
        audio_bytes: Audio data bytes
        mime_type: MIME type of audio
        openclaw_response_text: AI text response

    Returns:
        Dict with status and audio file path
    """
    try:
        logger.info(f"[Audio Handler] Processing audio message from {phone}")

        # Step 1: Transcribe audio
        logger.info("[Audio Handler] Step 1: Transcribing audio...")
        transcribed_text = await transcribe_audio(audio_bytes, mime_type)

        if not transcribed_text:
            return {
                "success": False,
                "error": "Transcription failed",
                "audio_file": None
            }

        logger.info(f"[Audio Handler] Transcribed: {transcribed_text[:100]}...")

        # Note: The text processing is already done by the caller
        # They pass the AI response as openclaw_response_text

        # Step 2: Detect language
        logger.info("[Audio Handler] Step 2: Detecting language...")
        language = detect_language(openclaw_response_text)
        logger.info(f"[Audio Handler] Language detected: {language}")

        # Step 3: Convert response to speech
        logger.info("[Audio Handler] Step 3: Converting response to audio...")
        result = await text_to_speech_async(openclaw_response_text, language)

        if result:
            audio_bytes, audio_file_path = result
            logger.info(f"[Audio Handler] Audio generated: {len(audio_bytes)} bytes")
            logger.info(f"[Audio Handler] Audio saved to: {audio_file_path}")

            return {
                "success": True,
                "transcribed_text": transcribed_text,
                "audio_bytes": audio_bytes,
                "audio_file": audio_file_path,
                "language": language
            }
        else:
            return {
                "success": False,
                "error": "TTS conversion failed",
                "audio_file": None
            }

    except Exception as e:
        logger.error(f"[Audio Handler] Error: {e}")
        return {
            "success": False,
            "error": str(e),
            "audio_file": None
        }


def get_transcription_only(audio_bytes: bytes, mime_type: str) -> str | None:
    """
    Get only transcription (for when you want text response, not audio).

    Args:
        audio_bytes: Audio data
        mime_type: MIME type

    Returns:
        Transcribed text or None
    """
    import asyncio
    return asyncio.run(transcribe_audio(audio_bytes, mime_type))
