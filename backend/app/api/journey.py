"""Journey API — thin wrappers over the existing `guardian_sessions`
lifecycle. There is intentionally NO `/journey/location` endpoint:
client GPS goes through the existing /api/guardian/update-location
path so it inherits all safety guarantees (shadow tracking, 24h cap,
GPS resurrection, alert generation, idle detection).

See /app/memory/SYSTEM_INVARIANTS.md — Invariant #1.
"""
from __future__ import annotations
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.models.guardian import GuardianSession, JourneyPoint
from app.models.user import User

router = APIRouter(prefix="/journey", tags=["journey"])


@router.get("/{session_id}/polyline")
async def get_polyline(
    session_id: uuid.UUID,
    since_seq: int = Query(0, ge=0,
                           description="Return only points with seq > since_seq (incremental)"),
    limit: int = Query(2000, ge=1, le=10000),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Return the GPS trail for a session, ordered by seq ascending.
    Caller must own the session OR be an operator/admin.

    Each point includes `quality` (good | unstable | offline) so the
    client can split the polyline into solid / dashed-amber / dashed-
    gray segments without re-computing on the device.
    """
    gs = (await session.execute(
        select(GuardianSession).where(GuardianSession.id == session_id)
    )).scalar_one_or_none()
    if gs is None:
        raise HTTPException(404, "session not found")
    if gs.user_id != current_user.id and current_user.role not in ("admin", "operator"):
        # Guardians of this user MAY view too — but that requires a
        # guardians-table join. Keeping strict-owner-or-admin here for
        # the first cut; widen in a follow-up.
        raise HTTPException(403, "not authorized")

    rows = (await session.execute(
        select(JourneyPoint)
        .where(JourneyPoint.session_id == session_id,
               JourneyPoint.seq > since_seq)
        .order_by(JourneyPoint.seq.asc())
        .limit(limit)
    )).scalars().all()

    return {
        "session_id":   str(session_id),
        "is_offline":   bool(gs.is_offline),
        "total_points": int(gs.total_points or 0),
        "offline_gaps": int(gs.offline_gaps or 0),
        "max_gap_seconds": int(gs.max_gap_seconds or 0),
        "since_seq":    since_seq,
        "count":        len(rows),
        "points": [
            {
                "seq":       p.seq,
                "lat":       p.lat,
                "lng":       p.lng,
                "accuracy":  p.accuracy,
                "speed_mps": p.speed_mps,
                "quality":   p.quality,
                "gap_before_s": p.gap_before_s,
                "gps_recorded_at":   p.gps_recorded_at.isoformat() if p.gps_recorded_at else None,
                "server_received_at": p.server_received_at.isoformat(),
            } for p in rows
        ],
    }
