# Fall Detection API — Sensor-based fall detection endpoints
#
# POST /api/sensors/fall          — Report fall from mobile (5-stage signals)
# POST /api/sensors/fall/{id}/resolve  — User confirms safe
# POST /api/sensors/fall/{id}/auto-sos — Trigger auto SOS (unresponsive user)
# POST /api/sensors/fall/{id}/cancel   — Cancel due to movement recovery
# GET  /api/sensors/fall/events   — Recent fall events
# POST /api/sensors/voice-distress/verify — Upload audio for Whisper verification
# GET  /api/sensors/voice-distress/{id}  — Get verification status

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session
from app.models import User

router = APIRouter(prefix="/sensors", tags=["sensors"])


class FallReportRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    # 5-stage signal scores (0.0 to 1.0 each)
    impact_score: float = Field(0.0, ge=0, le=1)
    freefall_score: float = Field(0.0, ge=0, le=1)
    orientation_score: float = Field(0.0, ge=0, le=1)
    post_impact_score: float = Field(0.0, ge=0, le=1)
    immobility_score: float = Field(0.0, ge=0, le=1)
    # Optional raw sensor data for ML training
    sensor_data: Optional[dict] = None


class ResolveRequest(BaseModel):
    resolved_by: str = Field("user_confirmed_safe", description="user_confirmed_safe|user_called_help|operator_resolved")


@router.post("/fall")
async def report_fall(
    req: FallReportRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Report a fall event from mobile sensors. Computes confidence and broadcasts SSE."""
    from app.services.fall_detection_service import report_fall

    signals = {
        "impact_score": req.impact_score,
        "freefall_score": req.freefall_score,
        "orientation_score": req.orientation_score,
        "post_impact_score": req.post_impact_score,
        "immobility_score": req.immobility_score,
    }

    result = await report_fall(
        session=session,
        user_id=str(user.id),
        lat=req.lat,
        lng=req.lng,
        signals=signals,
        sensor_data=req.sensor_data,
    )

    if result.get("status") == "cooldown":
        raise HTTPException(429, result["message"])
    return result


@router.post("/fall/{event_id}/resolve")
async def resolve_fall(
    event_id: str,
    req: ResolveRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """User confirms they are safe (resolves fall event)."""
    from app.services.fall_detection_service import resolve_fall

    result = await resolve_fall(session, event_id, req.resolved_by, str(user.id))
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.post("/fall/{event_id}/auto-sos")
async def auto_sos(
    event_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Trigger auto-SOS for unresolved fall (user didn't respond in time)."""
    from app.services.fall_detection_service import trigger_auto_sos

    result = await trigger_auto_sos(session, event_id)
    return result


@router.post("/fall/{event_id}/cancel")
async def cancel_fall(
    event_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Cancel fall event — user started moving again (movement recovery)."""
    from app.services.fall_detection_service import cancel_fall_by_movement

    result = await cancel_fall_by_movement(session, event_id, str(user.id))
    return result


@router.get("/fall/events")
async def get_fall_events(
    limit: int = 20,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Get recent fall events. Operators see all, guardians see their own."""
    from app.services.fall_detection_service import get_recent_fall_events

    user_id = None if user.role in ("operator", "admin") else str(user.id)
    events = await get_recent_fall_events(session, user_id=user_id, limit=limit)
    return {"events": events, "count": len(events)}


# ── Wandering Detection Endpoints ──

class WanderingCheckRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    speed: float = Field(0, ge=0)
    heading: float = Field(0, ge=0, le=360)


class WanderingResolveRequest(BaseModel):
    event_id: str


@router.post("/wandering/check")
async def check_wandering(
    req: WanderingCheckRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Check user location against safe zones. Detect wandering."""
    from app.services.wandering_detection_service import check_wandering

    result = await check_wandering(session, str(user.id), req.lat, req.lng, req.speed, req.heading)
    return result


@router.post("/wandering/resolve")
async def resolve_wandering(
    req: WanderingResolveRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Resolve a wandering event."""
    from app.services.wandering_detection_service import resolve_wandering

    result = await resolve_wandering(session, req.event_id, str(user.id))
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.get("/wandering/events")
async def get_wandering_events(
    limit: int = 20,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Get recent wandering events."""
    from app.services.wandering_detection_service import get_wandering_events

    user_id = None if user.role in ("operator", "admin") else str(user.id)
    events = await get_wandering_events(session, user_id=user_id, limit=limit)
    return {"events": events, "count": len(events)}


# ── Voice Distress Detection Endpoints ──

class VoiceDistressRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    keywords: Optional[list[str]] = None
    scream_detected: bool = False
    repeated: bool = False
    audio_features: Optional[dict] = None
    audio_base64: Optional[str] = Field(None, description="Base64-encoded audio clip for Whisper transcription")
    confidence: Optional[float] = Field(None, ge=0, le=1, description="Client-side confidence score")
    trigger_type: Optional[str] = Field(None, description="Trigger type: immediate-scream, decay-scream, whisper-mode")


class VoiceResolveRequest(BaseModel):
    resolved_by: str = Field("user_safe", description="user_safe|false_positive|operator_resolved")


@router.post("/voice-distress")
async def report_voice_distress(
    req: VoiceDistressRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Report voice distress from mobile (keywords + scream + audio features)."""
    import logging as _logging
    _logger = _logging.getLogger(__name__)
    _logger.info(
        f"[VOICE_DISTRESS_RECEIVED] user={user.id} scream={req.scream_detected} "
        f"trigger={req.trigger_type} confidence={req.confidence} "
        f"has_audio={'yes' if req.audio_base64 else 'no'}"
    )

    from app.services.voice_distress_service import report_voice_distress

    result = await report_voice_distress(
        session, str(user.id), req.lat, req.lng,
        req.keywords, req.scream_detected, req.repeated, req.audio_features,
        audio_base64=req.audio_base64,
        client_confidence=req.confidence,
        trigger_type=req.trigger_type,
    )
    if result.get("status") == "cooldown":
        raise HTTPException(429, result["message"])
    return result


@router.post("/voice-distress/{event_id}/resolve")
async def resolve_voice_distress(
    event_id: str,
    req: VoiceResolveRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Resolve a voice distress event."""
    from app.services.voice_distress_service import resolve_voice_distress

    result = await resolve_voice_distress(session, event_id, str(user.id), req.resolved_by)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.get("/voice-distress/events")
async def get_voice_events(
    limit: int = 20,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Get recent voice distress events."""
    from app.services.voice_distress_service import get_voice_distress_events

    user_id = None if user.role in ("operator", "admin") else str(user.id)
    events = await get_voice_distress_events(session, user_id=user_id, limit=limit)
    return {"events": events, "count": len(events)}


# ── Whisper Voice Verification Endpoints ──

@router.post("/voice-distress/verify")
async def verify_voice_distress(
    audio: UploadFile = File(..., description="Audio file (WAV/MP3/WebM, max 5MB, 15s)"),
    lat: float = Form(...),
    lng: float = Form(...),
    trigger_type: str = Form("on_device"),
    keywords: Optional[str] = Form(None, description="Comma-separated keywords detected on-device"),
    scream_detected: bool = Form(False),
    repeated: bool = Form(False),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """
    Upload audio for Whisper voice verification.

    1. Creates a voice distress event with 'queued' verification status
    2. Saves audio temporarily
    3. Queues async Whisper transcription + distress analysis
    4. Returns event_id immediately (non-blocking)
    """
    import os
    from pathlib import Path
    from app.services.whisper_verification_service import queue_whisper_verification, UPLOAD_DIR, MAX_AUDIO_BYTES

    # Validate audio format
    allowed = {"audio/wav", "audio/mpeg", "audio/mp3", "audio/webm", "audio/mp4", "audio/x-wav",
               "audio/ogg", "application/octet-stream"}
    if audio.content_type and audio.content_type not in allowed:
        ext = Path(audio.filename or "").suffix.lower()
        if ext not in {".wav", ".mp3", ".webm", ".mp4", ".m4a", ".ogg", ".mpeg"}:
            raise HTTPException(400, f"Unsupported audio format: {audio.content_type}")

    # Read and validate size
    content = await audio.read()
    if len(content) > MAX_AUDIO_BYTES:
        raise HTTPException(413, f"Audio too large ({len(content)} bytes). Max: {MAX_AUDIO_BYTES}")

    # Parse keywords
    kw_list = [k.strip() for k in keywords.split(",")] if keywords else None

    # Import required modules
    from app.models.voice_distress_event import VoiceDistressEvent
    from app.services.voice_distress_service import compute_distress_score
    import uuid as _uuid

    # Compute on-device distress score
    score = compute_distress_score(kw_list, scream_detected, repeated, None)

    # Always create event for Whisper verification (bypass cooldown)
    event = VoiceDistressEvent(
        user_id=_uuid.UUID(str(user.id)),
        lat=lat, lng=lng,
        keywords=kw_list,
        scream_detected=scream_detected,
        repeated_detection=repeated,
        distress_score=score,
        status="pending_verification",
        verification_status="queued",
        trigger_type=trigger_type,
    )
    session.add(event)
    await session.flush()
    event_id = str(event.id)
    await session.commit()

    # Save audio temporarily
    ext = Path(audio.filename or "audio.wav").suffix or ".wav"
    audio_path = str(UPLOAD_DIR / f"{event_id}{ext}")
    with open(audio_path, "wb") as f:
        f.write(content)

    # Queue async Whisper verification
    await queue_whisper_verification(session, event_id, audio_path)

    return {
        "event_id": event_id,
        "processing_status": "queued",
        "message": "Audio received. Whisper verification in progress.",
    }


@router.get("/voice-distress/{event_id}")
async def get_voice_verification(
    event_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Get verification status and result for a voice distress event."""
    from app.services.whisper_verification_service import get_verification_status

    result = await get_verification_status(session, event_id)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.post("/voice-distress/{event_id}/re-verify")
async def re_verify_voice_event(
    event_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Guardian requests re-verification of a past voice event."""
    from app.services.whisper_verification_service import verify_voice_event

    result = await verify_voice_event(session, event_id, audio_path=None)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result
