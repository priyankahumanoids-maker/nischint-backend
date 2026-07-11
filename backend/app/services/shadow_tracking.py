"""Shadow location-ping failsafe.

If a GPS ping can't be honored by the session layer (no session row,
terminal state, age-capped), we ALWAYS capture the trail here. This is
the failsafe layer the Command Center can fall back to during forensic
review even when sessions are corrupt or missing.

Strict scope:
  • Insert-only. No reads from this module.
  • Best-effort: never raises into the caller. A shadow-write failure
    must NOT cause the API path to fail — it would defeat the purpose
    of being a failsafe.

Two infra-hardening rules layered on top of the failsafe:

  1. **Per-user 10s dedup gate.** A 1-second-ping device with a broken
     session would write 60 shadow rows/min — that's a write-amplification
     bomb that destroys ops visibility. We only need *proof of continuity*,
     not every sample. The first ping in a 10-second window writes;
     intermediate pings are dropped silently.

  2. **One-shot `shadow_mode_activated` WS event.** A device that
     silently slips into shadow mode is invisible to the operator
     unless we surface it. We emit ONE event per "shadow run" (defined
     as the first write after a >60 s gap), so the Command Center can
     light up a yellow badge without being flooded.
"""
from __future__ import annotations
import asyncio
import logging
import threading
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Allowed `source` values — keep tight so the Command Center filter is
# meaningful. Any new source must be added here AND in the migration's
# docstring.
SOURCES = frozenset({"no_session", "session_ended", "session_age_cap"})

# Write-amplification guard — first ping in a 10 s window persists,
# intermediate pings are dropped.
MIN_SHADOW_INTERVAL_S = 10.0

# Considered "the same shadow run" if pings keep arriving within this
# window. A gap larger than this opens a fresh run, which re-fires the
# `shadow_mode_activated` WS event. Tuning lever: the smaller this is,
# the noisier the WS event stream.
SHADOW_RUN_GAP_S = 60.0

# Per-user (last_write_ts, last_run_start_ts). Process-local. Two
# processes (api + scheduler) might double-fire the WS event in the
# worst case — that's acceptable for an *informational* signal.
_last_seen: dict[str, tuple[float, float]] = {}
_lock = threading.Lock()


def _decide(user_key: str, now: float) -> tuple[bool, bool]:
    """Returns (should_write, should_emit_run_start_event)."""
    with _lock:
        prev = _last_seen.get(user_key)
        if prev is None:
            _last_seen[user_key] = (now, now)
            return True, True
        last_write, run_start = prev
        # Inside the dedup window → drop silently
        if (now - last_write) < MIN_SHADOW_INTERVAL_S:
            return False, False
        # New run if the previous write is old enough
        if (now - last_write) > SHADOW_RUN_GAP_S:
            _last_seen[user_key] = (now, now)
            return True, True
        # Still in the same shadow run — write but don't re-emit event
        _last_seen[user_key] = (now, run_start)
        return True, False


async def _emit_shadow_run_event(user_id: str, source: str,
                                  session_id: str | None) -> None:
    """One-shot WS event so the Command Center can render a badge."""
    try:
        from app.services.event_broadcaster import broadcaster
        payload = {
            "type":       "shadow_mode_activated",
            "user_id":    user_id,
            "source":     source,
            "session_id": session_id,
            "ts":         datetime.now(timezone.utc).isoformat(),
        }
        # Targeted broadcast — only operators / admins need to see this.
        try:
            await broadcaster.broadcast_to_role("operator", "shadow_mode_activated", payload)
        except Exception:
            # Older broadcasters may not have a role API. Falling back
            # to the user's own channel keeps the signal alive.
            await broadcaster.broadcast_to_user(user_id, "shadow_mode_activated", payload)
        logger.info(f"[shadow_ping] SHADOW_MODE_ACTIVATED user={user_id} src={source}")
    except Exception as e:
        logger.debug(f"[shadow_ping] WS emit failed (non-fatal): {e}")


async def shadow_ping(
    session: AsyncSession,
    user_id: uuid.UUID | str,
    lat: float, lng: float,
    *, source: str,
    session_id: str | None = None,
    ts: datetime | None = None,
) -> bool:
    """Record a GPS ping outside the session layer. Returns True on
    successful insert, False on dedup-skip OR insert failure
    (intentionally swallowed)."""
    if source not in SOURCES:
        logger.warning(f"[shadow_ping] unknown source={source!r} — recording anyway")

    user_key = str(user_id)
    now_mono = time.monotonic()
    should_write, should_emit_event = _decide(user_key, now_mono)
    if not should_write:
        logger.debug(
            f"[shadow_ping] dedup-skip user={user_key} (window={MIN_SHADOW_INTERVAL_S}s)"
        )
        return False

    try:
        await session.execute(
            text("""
                INSERT INTO shadow_location_pings
                    (id, user_id, lat, lng, source, session_id, ts)
                VALUES (:id, :uid, :lat, :lng, :src, :sid, :ts)
            """),
            {
                "id": uuid.uuid4(),
                "uid": user_key,
                "lat": float(lat),
                "lng": float(lng),
                "src": source,
                "sid": session_id,
                "ts": ts or datetime.now(timezone.utc),
            },
        )
        await session.commit()
        logger.info(
            f"[shadow_ping] user={user_key} src={source} "
            f"lat={lat:.5f} lng={lng:.5f} sid={session_id} "
            f"new_run={should_emit_event}"
        )
        if should_emit_event:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(_emit_shadow_run_event(user_key, source, session_id))
            except RuntimeError:
                pass
        return True
    except Exception as e:
        try:
            await session.rollback()
        except Exception:
            pass
        logger.warning(f"[shadow_ping] write failed: {e}")
        return False


def reset_state_for_tests() -> None:
    """Clear in-process dedup state. Test-only — never call in prod."""
    with _lock:
        _last_seen.clear()
