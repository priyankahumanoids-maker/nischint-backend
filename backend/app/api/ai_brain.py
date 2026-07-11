"""
AI Brain API — Unified autonomous decision endpoint.

Routes (mounted under /api):
    POST /ai/decide       — run AI brain on a multi-signal frame
    POST /ai/feedback     — record outcome for a past decision
    GET  /ai/decisions    — recent decision log (diagnostic)
    GET  /ai/stats        — aggregate stats
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services import ai_brain_service as _brain

router = APIRouter(prefix="/ai-brain", tags=["AI Brain"])


# ── Pydantic models ──────────────────────────────────────────────────

class VoiceSignal(BaseModel):
    amplitude: Optional[float] = Field(default=None, ge=0, le=1)
    pitch: Optional[float] = None
    stress_score: Optional[float] = Field(default=None, ge=0, le=1)
    keyword_flag: Optional[bool] = False


class GpsSignal(BaseModel):
    lat: Optional[float] = None
    lng: Optional[float] = None
    speed: Optional[float] = None
    route_deviation: Optional[float] = Field(default=None, ge=0, le=1)


class MotionSignal(BaseModel):
    activity: Optional[Literal["walk", "run", "still", "fall"]] = None
    acceleration: Optional[float] = None
    idle_sec: Optional[float] = None  # elderly inactivity penalty input


class DeviceSignal(BaseModel):
    battery: Optional[float] = Field(default=None, ge=0, le=1)
    network: Optional[bool] = True
    screen_on: Optional[bool] = True


class TimeSignal(BaseModel):
    hour: Optional[int] = Field(default=None, ge=0, le=23)
    is_night: Optional[bool] = None


class Signals(BaseModel):
    voice: Optional[VoiceSignal] = None
    gps: Optional[GpsSignal] = None
    motion: Optional[MotionSignal] = None
    device: Optional[DeviceSignal] = None
    time: Optional[TimeSignal] = None


class DecideRequest(BaseModel):
    user_id: str
    user_type: Literal["child", "woman", "adult", "elderly"] = "adult"
    signals: Signals
    event_id: Optional[str] = None
    skip_behavior: bool = False      # set True for fastest path
    auto_execute: bool = True        # set False to preview only


class FeedbackRequest(BaseModel):
    event_id: str
    outcome: Literal["true_positive", "false_alarm", "missed", "resolved"]
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    note: Optional[str] = None


# ── Endpoints ────────────────────────────────────────────────────────

@router.post("/decide")
async def ai_decide(payload: DecideRequest, session: AsyncSession = Depends(get_db)):
    """Run the AI brain pipeline on a single signal frame."""
    try:
        decision = await _brain.decide(
            session=session,
            user_id=payload.user_id,
            user_type=payload.user_type,
            signals=payload.signals.dict(exclude_none=True),
            event_id=payload.event_id,
            skip_behavior=payload.skip_behavior,
            auto_execute=payload.auto_execute,
        )
        return decision
    except HTTPException:
        raise
    except Exception as e:
        # Production-safe: never leak stack, but always respond
        raise HTTPException(status_code=500, detail=f"ai_brain_error: {e}")


@router.post("/feedback")
def ai_feedback(payload: FeedbackRequest):
    """Record the outcome for a past decision (enables learning loop)."""
    result = _brain.record_feedback(
        event_id=payload.event_id,
        outcome=payload.outcome,
        rating=payload.rating,
        note=payload.note,
    )
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="event_id not found in recent log")
    return result


@router.get("/decisions")
def ai_recent_decisions(limit: int = 50, user_id: Optional[str] = None, full: bool = False):
    """
    Return recent brain decisions (for dashboards / debugging).
    Prefers Mongo-backed audit log (90d TTL) and falls back to in-memory ring.
    Optional `user_id` filter scopes results to one user.
    Default response is a compact summary — set `full=true` for every field.

    Limit is HARD-CAPPED at 100 server-side regardless of caller value.
    """
    safe_limit = max(1, min(100, int(limit)))
    decisions = _brain.recent_decisions(
        safe_limit,
        user_id=user_id,
        summary=not full,
    )
    return {"decisions": decisions, "count": len(decisions), "limit": safe_limit}


@router.get("/stats")
def ai_stats():
    """Aggregate stats across recent brain decisions."""
    return _brain.stats()


@router.get("/user-adjustment/{user_id}")
def ai_user_adjustment(user_id: str):
    """Per-user adaptive threshold diagnostic — shows learned offset + feedback rates."""
    return _brain.get_user_adjustment(user_id)
