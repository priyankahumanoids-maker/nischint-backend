"""NISCH-009.1 — Guardian Impact Service.

`saved_by_network_count(guardian_id)` — count of distinct incidents
where:
  1. The guardian's CURRENT verdict is `mark_safe` (UPSERT keeps the
     final verdict per (incident, guardian)), AND
  2. The incident received an auto-resolve transition driven by
     community feedback (`safety_incident_events` row with
     `actor_type='community_feedback'` and `to_state='resolved'`).

The `incident_feedback` UNIQUE(incident_id, guardian_id) constraint
guarantees the count is naturally deduplicated — at most one
contributing vote per pair.

**Reopen tolerance** (per spec): we count the incident if there is
*any* community_feedback resolved transition tied to the guardian's
mark_safe vote. If the incident later flipped to ARCHIVED, the
"original auto-resolution persisted" — credit stands. (RESOLVED is
the only path to ARCHIVED in our state machine, so a ROLLED-BACK
resolve is impossible by the state contract today.)

**Low-confidence guard**: badge surfaces are hidden when the
*system-wide* count of community_feedback resolutions is < 5.
Caller decides whether to render based on `confidence_low`.

**Caching**: 5-minute TTL Redis cache, namespaced per guardian.
Invalidated by `feedback_aggregator.apply_feedback_decision` for the
guardians who voted `mark_safe` on an incident that just auto-resolved
— so the badge updates near-instantly for the contributing guardians.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


CACHE_TTL_S = 300                        # 5 minutes
CACHE_KEY_FMT = "nischint:guardian_impact:{guardian_id}"
SYSTEM_RESOLUTIONS_KEY = "nischint:guardian_impact:system_resolutions"
LOW_CONFIDENCE_FLOOR = 5                 # < this → confidence_low


_COUNT_SQL = text("""
    SELECT COUNT(DISTINCT inc_fb.incident_id) AS saved_count
    FROM incident_feedback inc_fb
    JOIN safety_incident_events sie
      ON sie.incident_id = inc_fb.incident_id
    WHERE inc_fb.guardian_id  = :guardian_id
      AND inc_fb.verdict      = 'mark_safe'
      AND sie.actor_type      = 'community_feedback'
      AND sie.to_state        = 'resolved'
""")


_SYSTEM_RESOLUTIONS_SQL = text("""
    SELECT COUNT(DISTINCT incident_id) AS total
    FROM safety_incident_events
    WHERE actor_type = 'community_feedback'
      AND to_state   = 'resolved'
""")


async def _get_redis():
    """Lazy import — keep the service usable in tests where Redis
    isn't reachable. Returns None on any failure."""
    try:
        from app.services.redis_service import get_redis
        return await get_redis()
    except Exception:
        return None


async def _read_cache(guardian_id: uuid.UUID) -> Optional[dict]:
    r = await _get_redis()
    if r is None:
        return None
    try:
        raw = await r.get(CACHE_KEY_FMT.format(guardian_id=guardian_id))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode()
        return json.loads(raw)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[IMPACT] cache read failed: {e}")
        return None


async def _write_cache(guardian_id: uuid.UUID, payload: dict) -> None:
    r = await _get_redis()
    if r is None:
        return
    try:
        await r.set(
            CACHE_KEY_FMT.format(guardian_id=guardian_id),
            json.dumps(payload),
            ex=CACHE_TTL_S,
        )
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[IMPACT] cache write failed: {e}")


async def invalidate_guardians(guardian_ids: list[uuid.UUID]) -> None:
    """Drop cached impact rows for these guardians (called after an
    auto-resolve fires so contributors see fresh counts within seconds).
    Best-effort; never raises."""
    if not guardian_ids:
        return
    r = await _get_redis()
    if r is None:
        return
    try:
        for gid in guardian_ids:
            await r.delete(CACHE_KEY_FMT.format(guardian_id=gid))
        # System-wide count also needs invalidation — its denominator
        # changed.
        await r.delete(SYSTEM_RESOLUTIONS_KEY)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[IMPACT] cache invalidate failed: {e}")


async def _read_system_resolutions(session: AsyncSession) -> int:
    """Count of all distinct incidents auto-resolved by community
    feedback. Cached separately because it changes for the whole
    system, not per-guardian."""
    r = await _get_redis()
    if r is not None:
        try:
            raw = await r.get(SYSTEM_RESOLUTIONS_KEY)
            if raw is not None:
                return int(raw)
        except Exception:
            pass
    row = (await session.execute(_SYSTEM_RESOLUTIONS_SQL)).one()
    total = int(row[0] or 0)
    if r is not None:
        try:
            await r.set(SYSTEM_RESOLUTIONS_KEY, str(total), ex=CACHE_TTL_S)
        except Exception:
            pass
    return total


async def get_impact(
    session: AsyncSession, guardian_id: uuid.UUID, *, use_cache: bool = True,
) -> dict:
    """Return the impact envelope for one guardian.

    Shape:
        {
            "guardian_id":            str,
            "saved_by_network_count": int,
            "system_resolutions":     int,
            "confidence_low":         bool,  # hide UI if true
            "from_cache":             bool,
        }
    """
    if use_cache:
        cached = await _read_cache(guardian_id)
        if cached is not None:
            cached["from_cache"] = True
            return cached

    row = (await session.execute(
        _COUNT_SQL, {"guardian_id": str(guardian_id)}
    )).one()
    saved = int(row[0] or 0)
    sysres = await _read_system_resolutions(session)
    confidence_low = sysres < LOW_CONFIDENCE_FLOOR

    payload = {
        "guardian_id":            str(guardian_id),
        "saved_by_network_count": saved,
        "system_resolutions":     sysres,
        "confidence_low":         confidence_low,
        "from_cache":             False,
    }
    await _write_cache(guardian_id, payload)
    return payload


async def get_mark_safe_voters(
    session: AsyncSession, incident_id: uuid.UUID,
) -> list[uuid.UUID]:
    """Helper for the aggregator: return guardian_ids whose CURRENT
    verdict on this incident is `mark_safe`. Used to invalidate
    their badge cache after auto-resolve."""
    rows = (await session.execute(text("""
        SELECT guardian_id FROM incident_feedback
        WHERE incident_id = :iid AND verdict = 'mark_safe'
    """), {"iid": str(incident_id)})).all()
    return [r[0] for r in rows]


__all__ = [
    "CACHE_TTL_S",
    "LOW_CONFIDENCE_FLOOR",
    "get_impact",
    "get_mark_safe_voters",
    "invalidate_guardians",
]
