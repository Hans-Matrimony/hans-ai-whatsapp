"""
Audio Processor Module for WhatsApp Bot
Handles transcription (audio → text) and TTS (text → audio)
"""

from .transcribe import transcribe_audio, is_audio_message
from .text_to_speech import text_to_speech, text_to_speech_async, save_audio_to_file, detect_language

__all__ = [
    "transcribe_audio",
    "is_audio_message",
    "text_to_speech",
    "text_to_speech_async",
    "save_audio_to_file",
    "detect_language"
]
