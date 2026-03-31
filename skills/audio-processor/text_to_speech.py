#!/usr/bin/env python3
"""
Text-to-Speech using Google Cloud TTS (FREE tier)
Converts text response to audio using Google Cloud Text-to-Speech API
"""
import os
import logging
import tempfile
import hashlib
from datetime import datetime

from google.cloud import texttospeech
from google.oauth2 import service_account

logger = logging.getLogger(__name__)

# Google Cloud configuration
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

# Voice settings
HINDI_VOICE = "hi-IN-Wavenet-A"  # Natural female Hindi voice
ENGLISH_VOICE = "en-IN-Wavenet-A"  # Indian English female voice


def text_to_speech(text: str, language: str = "hi") -> bytes | None:
    """
    Convert text to speech using Google Cloud TTS.

    Args:
        text: Text to convert to speech
        language: "hi" for Hindi, "en" for English

    Returns:
        Audio bytes (MP3 format) or None if failed
    """
    if not GOOGLE_APPLICATION_CREDENTIALS:
        logger.error("GOOGLE_APPLICATION_CREDENTIALS not set")
        return None

    try:
        # Initialize TTS client
        client = texttospeech.TextToSpeechClient.from_service_account_json(
            GOOGLE_APPLICATION_CREDENTIALS
        )

        # Select voice based on language
        if language == "hi":
            voice_name = HINDI_VOICE
        else:
            voice_name = ENGLISH_VOICE

        # Set text input
        synthesis_input = texttospeech.SynthesisInput(text=text)

        # Configure voice
        voice = texttospeech.VoiceSelectionParams(
            language_code=language,
            name=voice_name,
            ssml_gender=texttospeech.SsmlVoiceGender.FEMALE
        )

        # Configure audio output
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=0.9,  # Slightly slower for clarity
            pitch=0.0
        )

        logger.info(f"[TTS] Converting text to speech ({language}, voice: {voice_name})")

        # Generate speech
        response = client.synthesize_voice(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config
        )

        if response.audio_content:
            logger.info(f"[TTS] Audio generated: {len(response.audio_content)} bytes")
            return response.audio_content
        else:
            logger.error("[TTS] No audio content returned")
            return None

    except Exception as e:
        logger.error(f"[TTS] Error converting text to speech: {e}")
        return None


def save_audio_to_file(audio_bytes: bytes, user_id: str) -> str | None:
    """
    Save audio bytes to a temporary file and return the path.
    For production, you'd upload to S3/Cloud Storage and return public URL.

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
        filename = f"audio_{user_id.replace('+', '')}_{hash_id}_{timestamp}.mp3"

        # Save to temp directory
        temp_dir = tempfile.gettempdir()
        file_path = os.path.join(temp_dir, filename)

        with open(file_path, "wb") as f:
            f.write(audio_bytes)

        logger.info(f"[TTS] Audio saved to: {file_path}")
        return file_path

    except Exception as e:
        logger.error(f"[TTS] Error saving audio: {e}")
        return None


async def text_to_speech_async(text: str, language: str = "hi") -> tuple[bytes, str] | None:
    """
    Async wrapper for text_to_speech. Returns (audio_bytes, file_path).

    Args:
        text: Text to convert
        language: Language code

    Returns:
        Tuple of (audio_bytes, file_path) or None
    """
    audio_bytes = text_to_speech(text, language)

    if audio_bytes:
        # Save to file
        import asyncio
        file_path = await asyncio.to_thread(
            lambda: save_audio_to_file(audio_bytes, "user")
        )
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
