"""
Audio Processor Module for WhatsApp Bot
Handles transcription (audio → text) and TTS (text → audio)
Edge TTS version - 100% FREE, enabled only for test number
"""

from .transcribe import transcribe_audio, is_audio_message
from .text_to_speech_edge import (
    text_to_speech_edge,
    text_to_speech_edge_async,
    save_audio_to_file,
    detect_language,
    is_test_number
)

__all__ = [
    "transcribe_audio",
    "is_audio_message",
    "text_to_speech_edge",
    "text_to_speech_edge_async",
    "save_audio_to_file",
    "detect_language",
    "is_test_number"
]
