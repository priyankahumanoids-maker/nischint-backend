# Whisper Transcription Service — Lightweight audio-to-text
#
# Uses OpenAI Whisper via Emergent LLM Key
# Designed for short clips (2-3 seconds) from voice distress detection

import base64
import io
import logging
import os
import tempfile

logger = logging.getLogger(__name__)


async def transcribe_audio_base64(audio_base64: str) -> dict:
    """
    Transcribe a base64-encoded audio clip using OpenAI Whisper.

    Returns: {"text": "...", "language": "en", "success": True}
    or {"text": "", "success": False, "error": "..."}
    """
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        logger.error("[WHISPER] EMERGENT_LLM_KEY not set")
        return {"text": "", "success": False, "error": "API key not configured"}

    try:
        audio_bytes = base64.b64decode(audio_base64)
    except Exception as e:
        logger.warning(f"[WHISPER] Invalid base64: {e}")
        return {"text": "", "success": False, "error": "Invalid base64 audio"}

    if len(audio_bytes) < 100:
        return {"text": "", "success": False, "error": "Audio too short"}

    if len(audio_bytes) > 25 * 1024 * 1024:
        return {"text": "", "success": False, "error": "Audio exceeds 25MB limit"}

    try:
        from emergentintegrations.llm.openai import OpenAISpeechToText

        stt = OpenAISpeechToText(api_key=api_key)

        # Write to temp file (Whisper API requires a file-like object with name)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        try:
            with open(tmp_path, "rb") as audio_file:
                response = await stt.transcribe(
                    file=audio_file,
                    model="whisper-1",
                    response_format="json",
                    temperature=0.0,
                )

            transcript = response.text.strip() if response and response.text else ""
            logger.info(f"[WHISPER] Transcribed: '{transcript[:100]}' ({len(audio_bytes)} bytes)")

            return {
                "text": transcript,
                "success": True,
                "audio_size_bytes": len(audio_bytes),
            }
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    except Exception as e:
        logger.error(f"[WHISPER] Transcription failed: {e}")
        return {"text": "", "success": False, "error": str(e)}
