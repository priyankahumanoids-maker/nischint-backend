# Voice Trigger API — Voice command management and recognition
import logging
import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.core.rbac import require_role
from app.models.user import User
from app.services import voice_trigger_service as svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voice-trigger", tags=["voice-trigger"])

_escape_role = require_role(["guardian", "operator", "admin"])

UPLOAD_DIR = Path("/tmp/nischint_voice_trigger")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MAX_AUDIO_BYTES = 5 * 1024 * 1024  # 5 MB


class CommandCreate(BaseModel):
    phrase: str = Field(..., max_length=200)
    linked_action: str = Field(..., pattern="^(sos|fake_call|fake_notification)$")
    action_config: Optional[dict] = None
    confidence_threshold: float = Field(0.7, ge=0.3, le=1.0)


class RecognizeRequest(BaseModel):
    transcribed_text: str = Field(..., max_length=1000)


@router.get("/commands")
async def list_commands(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_escape_role),
):
    await svc.ensure_defaults(session, user.id)
    await session.commit()
    commands = await svc.list_commands(session, user.id)
    return {"commands": commands}


@router.post("/commands", status_code=status.HTTP_201_CREATED)
async def create_command(
    body: CommandCreate,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_escape_role),
):
    return await svc.create_command(session, user.id, body.model_dump())


@router.delete("/commands/{cmd_id}")
async def delete_command(
    cmd_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_escape_role),
):
    ok = await svc.delete_command(session, user.id, uuid.UUID(cmd_id))
    if not ok:
        raise HTTPException(status_code=404, detail="Command not found or is default")
    return {"deleted": True}


@router.post("/recognize")
async def recognize_voice(
    body: RecognizeRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_escape_role),
):
    return await svc.recognize_and_trigger(session, user.id, body.transcribed_text)


@router.post("/recognize-audio")
async def recognize_audio(
    audio: UploadFile = File(...),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_escape_role),
):
    """
    Accept audio file, transcribe via OpenAI Whisper, then match against
    configured voice commands. Returns transcription + trigger result.
    """
    # Validate file size
    contents = await audio.read()
    if len(contents) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio file too large (max 5MB)")

    # Save to temp
    ext = Path(audio.filename or "audio.webm").suffix or ".webm"
    file_id = uuid.uuid4().hex[:12]
    audio_path = UPLOAD_DIR / f"{file_id}{ext}"
    audio_path.write_bytes(contents)

    try:
        # Transcribe via Whisper
        from app.services.whisper_verification_service import transcribe_audio
        whisper_result = await transcribe_audio(str(audio_path))
        transcribed_text = whisper_result.get("text", "").strip()

        if not transcribed_text:
            return {
                "transcribed_text": "",
                "triggered": False,
                "matched_phrase": None,
                "confidence": 0.0,
                "linked_action": None,
                "action_result": None,
                "whisper_language": whisper_result.get("language"),
                "whisper_duration": whisper_result.get("duration"),
            }

        # Match against commands
        result = await svc.recognize_and_trigger(session, user.id, transcribed_text)
        result["whisper_language"] = whisper_result.get("language")
        result["whisper_duration"] = whisper_result.get("duration")
        return result

    finally:
        # Delete audio file (privacy)
        try:
            audio_path.unlink(missing_ok=True)
        except Exception:
            pass


@router.get("/history")
async def trigger_history(
    limit: int = 20,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_escape_role),
):
    logs = await svc.get_history(session, user.id, limit)
    return {"history": logs, "count": len(logs)}
