"""
PDF and Audio Analysis Functions for WhatsApp Webhook Service
These functions are completely isolated from existing functionality and are gated by feature flags.
"""

import os
import json
import tempfile
import base64
import subprocess
import logging
from typing import Dict, Optional, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class PDFAnalyzer:
    """
    PDF Analysis Handler - Isolated from existing functionality
    Only active if enable_pdf_analysis feature flag is True
    """

    @staticmethod
    def check_feature_flag() -> bool:
        """Check if PDF analysis feature is enabled"""
        try:
            from app.config.settings import settings
            return settings.enable_pdf_analysis
        except Exception as e:
            logger.error(f"[PDF Analysis] Error checking feature flag: {e}")
            return False

    @staticmethod
    async def process_pdf_document(
        media_id: str,
        user_id: str,
        message_context: Dict[str, Any],
        download_func,
        store_func
    ) -> Dict[str, Any]:
        """
        Process PDF document uploaded by user.

        This function is COMPLETELY ISOLATED from existing functionality.
        It only runs if the enable_pdf_analysis feature flag is True.

        Args:
            media_id: WhatsApp media ID
            user_id: User's phone number
            message_context: Message context (language mode, etc.)
            download_func: Function to download media from WhatsApp
            store_func: Function to store data in mem0

        Returns:
            Dict with analysis results or error
        """
        try:
            # Check feature flag first
            if not PDFAnalyzer.check_feature_flag():
                logger.info("[PDF Analysis] Feature disabled, skipping PDF processing")
                return {"feature_disabled": True, "message": "PDF analysis feature is not enabled"}

            logger.info(f"[PDF Analysis] Processing PDF for user {user_id}, media_id: {media_id}")

            # Step 1: Download PDF from WhatsApp
            logger.info("[PDF Analysis] Step 1: Downloading PDF from WhatsApp")
            pdf_data = await download_func(media_id)

            if not pdf_data:
                logger.error("[PDF Analysis] Failed to download PDF from WhatsApp")
                return {"error": "Failed to download PDF"}

            # Step 2: Save to temporary file
            logger.info("[PDF Analysis] Step 2: Saving PDF to temporary file")
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                tmp_file.write(base64.b64decode(pdf_data))
                pdf_path = tmp_file.name

            try:
                # Step 3: Analyze PDF using skill
                logger.info(f"[PDF Analysis] Step 3: Analyzing PDF at {pdf_path}")
                result = subprocess.run(
                    [
                        "python3",
                        os.path.expanduser("~/.openclaw/skills/pdf_analyzer/pdf_client.py"),
                        "analyze",
                        "--pdf-path",
                        pdf_path
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60  # 60 second timeout for PDF processing
                )

                if result.returncode != 0:
                    logger.error(f"[PDF Analysis] Analysis failed: {result.stderr}")
                    return {"error": "PDF analysis failed", "details": result.stderr}

                # Parse analysis result
                analysis = json.loads(result.stdout)
                logger.info(f"[PDF Analysis] Analysis complete: {analysis['metadata'].get('pages', 0)} pages")

                # Step 4: Store analysis in mem0
                logger.info("[PDF Analysis] Step 4: Storing analysis in mem0")
                await PDFAnalyzer._store_pdf_analysis(
                    user_id,
                    analysis,
                    store_func
                )

                # Step 5: Generate summary
                summary = PDFAnalyzer._generate_pdf_summary(analysis, message_context)

                logger.info("[PDF Analysis] PDF processing completed successfully")
                return {
                    "success": True,
                    "analysis": analysis,
                    "summary": summary,
                    "feature_enabled": True
                }

            finally:
                # Clean up temporary file
                try:
                    os.unlink(pdf_path)
                    logger.info("[PDF Analysis] Cleaned up temporary PDF file")
                except Exception as e:
                    logger.warning(f"[PDF Analysis] Failed to cleanup temp file: {e}")

        except subprocess.TimeoutExpired:
            logger.error("[PDF Analysis] PDF processing timed out after 60 seconds")
            return {"error": "PDF processing timed out"}
        except Exception as e:
            logger.error(f"[PDF Analysis] Error processing PDF: {str(e)}", exc_info=True)
            return {"error": str(e)}

    @staticmethod
    async def _store_pdf_analysis(
        user_id: str,
        analysis: Dict[str, Any],
        store_func
    ) -> None:
        """
        Store PDF analysis in mem0 for context.

        Args:
            user_id: User's phone number
            analysis: PDF analysis result
            store_func: Function to store data in mem0
        """
        try:
            metadata = analysis.get("metadata", {})
            text_preview = analysis.get("text", "")[:200]

            summary = (
                f"User uploaded PDF document. "
                f"Pages: {metadata.get('pages', 'Unknown')}, "
                f"Title: {metadata.get('title', 'Unknown')}, "
                f"Content preview: {text_preview}..."
            )

            logger.info(f"[PDF Analysis] Storing PDF summary in mem0 for user {user_id}")

            # Store using the provided store function (or subprocess if not available)
            if store_func:
                await store_func(user_id, summary)
            else:
                # Fallback to direct subprocess call
                subprocess.run([
                    "python3",
                    os.path.expanduser("~/.openclaw/skills/mem0/mem0_client.py"),
                    "add",
                    f"PDF Document: {summary}",
                    "--user-id",
                    user_id
                ], capture_output=True, timeout=10)

            logger.info("[PDF Analysis] PDF summary stored successfully in mem0")

        except Exception as e:
            logger.error(f"[PDF Analysis] Failed to store PDF analysis: {str(e)}")

    @staticmethod
    def _generate_pdf_summary(analysis: Dict[str, Any], context: Dict[str, Any]) -> str:
        """
        Generate human-readable summary of PDF analysis.

        Args:
            analysis: PDF analysis result
            context: Message context (language mode, etc.)

        Returns:
            Summary message in user's language
        """
        try:
            user_language = context.get("language", "hinglish")
            metadata = analysis.get("metadata", {})
            pages = metadata.get("pages", 0)

            if user_language == "english":
                return (
                    f"I've analyzed your PDF document. It has {pages} pages. "
                    f"Would you like me to explain what's in it or answer any specific questions?"
                )
            else:
                return (
                    f"Maine aapka PDF document analyze kar liya hai. Isme {pages} pages hain. "
                    f"Kya aapko batana hai ki isme kya hai ya koi specific question hai?"
                )
        except Exception as e:
            logger.error(f"[PDF Analysis] Error generating summary: {str(e)}")
            return "I've received your PDF document. How can I help you with it?"


class AudioAnalyzer:
    """
    Advanced Audio Analysis Handler - Isolated from existing functionality
    Only active if enable_audio_emotion_detection feature flag is True
    """

    @staticmethod
    def check_feature_flag() -> bool:
        """Check if audio emotion detection feature is enabled"""
        try:
            from app.config.settings import settings
            return settings.enable_audio_emotion_detection
        except Exception as e:
            logger.error(f"[Audio Analysis] Error checking feature flag: {e}")
            return False

    @staticmethod
    async def analyze_audio_advanced(
        transcript_text: str,
        user_id: str,
        message_context: Dict[str, Any],
        store_func
    ) -> Dict[str, Any]:
        """
        Perform advanced audio analysis including emotion detection and question extraction.

        This function is COMPLETELY ISOLATED from existing functionality.
        It only runs if the enable_audio_emotion_detection feature flag is True.

        Args:
            transcript_text: Transcribed audio text
            user_id: User's phone number
            message_context: Message context
            store_func: Function to store data in mem0

        Returns:
            Dict with analysis results
        """
        try:
            # Check feature flag first
            if not AudioAnalyzer.check_feature_flag():
                logger.info("[Audio Analysis] Feature disabled, skipping advanced analysis")
                return {"feature_disabled": True, "transcript": transcript_text}

            logger.info(f"[Audio Analysis] Performing advanced analysis for user {user_id}")

            # Analyze transcript using audio analyzer skill
            result = subprocess.run(
                [
                    "python3",
                    os.path.expanduser("~/.openclaw/skills/audio_analyzer/audio_client.py"),
                    "analyze",
                    transcript_text
                ],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode != 0:
                logger.error(f"[Audio Analysis] Analysis failed: {result.stderr}")
                return {"error": "Audio analysis failed", "transcript": transcript_text}

            # Parse analysis result
            analysis = json.loads(result.stdout)
            emotion = analysis.get("emotion", "neutral")
            is_astro = analysis.get("is_astrology_question", False)
            language = analysis.get("language", "english")

            logger.info(
                f"[Audio Analysis] Analysis complete - "
                f"Emotion: {emotion}, Astro Question: {is_astro}, Language: {language}"
            )

            # Store analysis in mem0
            await AudioAnalyzer._store_audio_analysis(
                user_id,
                emotion,
                is_astro,
                transcript_text,
                store_func
            )

            # Suggest remedy if needed
            suggested_remedy = analysis.get("suggested_remedy")
            if suggested_remedy:
                logger.info(f"[Audio Analysis] Suggested remedy: {suggested_remedy}")

            return {
                "success": True,
                "transcript": transcript_text,
                "emotion": emotion,
                "is_astrology_question": is_astro,
                "language": language,
                "suggested_remedy": suggested_remedy,
                "feature_enabled": True
            }

        except subprocess.TimeoutExpired:
            logger.error("[Audio Analysis] Analysis timed out")
            return {"error": "Audio analysis timed out", "transcript": transcript_text}
        except Exception as e:
            logger.error(f"[Audio Analysis] Error: {str(e)}", exc_info=True)
            return {"error": str(e), "transcript": transcript_text}

    @staticmethod
    async def _store_audio_analysis(
        user_id: str,
        emotion: str,
        is_astro: bool,
        transcript: str,
        store_func
    ) -> None:
        """
        Store audio analysis in mem0.

        Args:
            user_id: User's phone number
            emotion: Detected emotion
            is_astro: Whether astrology question was detected
            transcript: Transcribed text
            store_func: Function to store data in mem0
        """
        try:
            transcript_preview = transcript[:150]
            summary = (
                f"Audio message: {emotion} tone, "
                f"Astrology question: {'Yes' if is_astro else 'No'}, "
                f"Transcript: {transcript_preview}..."
            )

            logger.info(f"[Audio Analysis] Storing audio analysis in mem0 for user {user_id}")

            if store_func:
                await store_func(user_id, summary)
            else:
                # Fallback to direct subprocess call
                subprocess.run([
                    "python3",
                    os.path.expanduser("~/.openclaw/skills/mem0/mem0_client.py"),
                    "add",
                    f"Audio: {summary}",
                    "--user-id",
                    user_id
                ], capture_output=True, timeout=10)

            logger.info("[Audio Analysis] Audio analysis stored successfully in mem0")

        except Exception as e:
            logger.error(f"[Audio Analysis] Failed to store audio analysis: {str(e)}")

    @staticmethod
    def get_audio_remedy(category: str, language: str = "english") -> Dict[str, Any]:
        """
        Get audio remedy (mantra/prayer) for given category.

        Args:
            category: Remedy category
            language: Response language (english or hinglish)

        Returns:
            Remedy details
        """
        try:
            result = subprocess.run(
                [
                    "python3",
                    os.path.expanduser("~/.openclaw/skills/audio_analyzer/audio_client.py"),
                    "remedy",
                    category,
                    "--language",
                    language
                ],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                return json.loads(result.stdout)
            else:
                logger.error(f"[Audio Analysis] Failed to get remedy: {result.stderr}")
                return {"error": "Failed to get remedy"}

        except Exception as e:
            logger.error(f"[Audio Analysis] Error getting remedy: {str(e)}")
            return {"error": str(e)}


# Export classes
__all__ = ['PDFAnalyzer', 'AudioAnalyzer']
