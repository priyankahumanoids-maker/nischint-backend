"""Risk Update Emitter — disciplined SSE emission of `risk_update` events.

Design contract (locked 2026-05-04, hardened 2026-05-04 v2):
- Emit ONLY when one of these is true vs. the last emitted state for the
  same child:
    1. **Bucket change** (GREEN ↔ YELLOW ↔ RED ↔ CRITICAL)
    2. **Score delta ≥ 2**
    3. **Escalation tier change** (`none|user|guardian|emergency`)
    4. **Offline / stale transition** (boolean flip)
- Each event carries `event_id` (uuid), `version` (monotonic int per
  child), and `emit_key = "{child_id}:{version}"` so frontends can hard-
  reject duplicates even across reconnects / server restarts.

State persistence:
- **Primary**: Redis (namespace `risk:last`, child-keyed). Version is
  incremented atomically via `INCR` so multiple backend instances can
  never collide on a version number.
- **Fallback**: in-memory `_LOCAL_LAST_RISK` dict — used only when
  Redis is unavailable. Single-process safe, multi-process LOSSY by
  design (we'd rather emit a redundant event than miss one).

This module owns the emit decision. It does NOT compute the risk score
(that lives in the caller).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from typing import Optional
from uuid import uuid4

from app.services import redis_service

logger = logging.getLogger(__name__)

SCORE_DELTA_THRESHOLD = 2

# Numeric tier for escalation_level. Mirror of `guardian_live._ESC_TIER`.
ESC_TIER: dict[str, int] = {
    "none":      0,
    "user":      1,
    "guardian":  2,
    "emergency": 3,
}

# Redis namespacing — matches the project-wide `nischint:*` convention
# used elsewhere in `redis_service`.
_RS_NS_STATE = "risk:last"          # JSON state per child
_RS_VERSION_KEY = "nischint:risk:ver:{child_id}"  # raw INCR counter


@dataclass
class RiskState:
    score: int
    risk_level: str
    escalation_tier: int
    is_offline: bool
    version: int


# In-memory fallback only — used when Redis is unreachable.
_LOCAL_LAST_RISK: dict[str, RiskState] = {}


def _esc_to_tier(esc_raw) -> int:
    if isinstance(esc_raw, str):
        return ESC_TIER.get(esc_raw.lower(), 0)
    if isinstance(esc_raw, (int, float)):
        return int(esc_raw)
    return 0


def should_emit(
    prev: Optional[RiskState],
    *,
    score: int,
    risk_level: str,
    escalation_tier: int,
    is_offline: bool,
) -> Optional[str]:
    """Return a short reason string if an emit is warranted, else None.
    Pure function — tested directly."""
    if prev is None:
        return "first_observation"
    if prev.risk_level != risk_level:
        return "bucket_change"
    if abs(score - prev.score) >= SCORE_DELTA_THRESHOLD:
        return "score_delta"
    if prev.escalation_tier != escalation_tier:
        return "escalation_change"
    if prev.is_offline != is_offline:
        return "offline_transition"
    return None


# ── State accessors (Redis-first, in-memory fallback) ────────────────

def _get_state(child_id: str) -> Optional[RiskState]:
    if redis_service.is_available():
        raw = redis_service.get_json(_RS_NS_STATE, child_id)
        if raw is None:
            return None
        try:
            return RiskState(**raw)
        except TypeError:
            # Schema drift — treat as no prior state. The next emit
            # will overwrite it cleanly.
            logger.warning(f"[RISK_EMIT] dropping malformed state for {child_id}: {raw}")
            return None
    return _LOCAL_LAST_RISK.get(child_id)


def _put_state(child_id: str, state: RiskState) -> None:
    if redis_service.is_available():
        # 24h TTL — long enough that an idle session's first GPS
        # update doesn't re-fire a `first_observation`, short enough
        # that abandoned children get evicted.
        redis_service.set_json(_RS_NS_STATE, child_id, asdict(state), ttl=86400)
        return
    _LOCAL_LAST_RISK[child_id] = state


def _next_version(child_id: str, prev_version: int) -> int:
    """Return the next monotonic version for this child.

    On Redis: uses `INCR` so multiple backend instances cannot collide.
    On in-memory fallback: just `prev + 1`.
    """
    if redis_service.is_available():
        client = redis_service._get_client()
        if client is not None:
            try:
                key = _RS_VERSION_KEY.format(child_id=child_id)
                # If the counter doesn't exist yet (or was evicted),
                # INCR will start at 1.
                v = client.incr(key)
                # Refresh TTL on each emit — keeps active children
                # alive, lets stale ones expire naturally.
                client.expire(key, 86400)
                return int(v)
            except Exception as e:
                logger.warning(f"[RISK_EMIT] redis INCR failed for {child_id}: {e}; falling back to local")
    return prev_version + 1


def reset_state(child_id: Optional[str] = None) -> None:
    """Test-only helper — clear cached state for a child or everyone."""
    if child_id is None:
        _LOCAL_LAST_RISK.clear()
        if redis_service.is_available():
            try:
                client = redis_service._get_client()
                if client is not None:
                    # Best-effort scan + delete. Test-only path.
                    for k in client.scan_iter(match=f"nischint:{_RS_NS_STATE}:*"):
                        client.delete(k)
                    for k in client.scan_iter(match="nischint:risk:ver:*"):
                        client.delete(k)
            except Exception:
                pass
    else:
        _LOCAL_LAST_RISK.pop(str(child_id), None)
        if redis_service.is_available():
            redis_service.delete_key(_RS_NS_STATE, child_id)
            try:
                client = redis_service._get_client()
                if client is not None:
                    client.delete(_RS_VERSION_KEY.format(child_id=child_id))
            except Exception:
                pass


async def maybe_emit_risk_update(
    *,
    child_id: str,
    guardian_ids: list[str],
    score: int,
    risk_level: str,
    escalation_level,
    is_offline: bool,
    payload_extras: dict,
) -> Optional[dict]:
    """Decide whether to emit + broadcast to all guardians on the child.

    Returns the emitted event dict (with `event_id`, `version`,
    `emit_key`, `delta`, `reason`) when an emit happens, else None.
    """
    cid = str(child_id)
    prev = _get_state(cid)
    esc_tier = _esc_to_tier(escalation_level)

    reason = should_emit(
        prev,
        score=int(score),
        risk_level=risk_level,
        escalation_tier=esc_tier,
        is_offline=bool(is_offline),
    )
    if reason is None:
        return None

    version = _next_version(cid, prev.version if prev else 0)

    event_id = str(uuid4())
    delta = int(score) - (prev.score if prev else 0)
    emit_key = f"{cid}:{version}"

    event = {
        "event_id":   event_id,
        "emit_key":   emit_key,         # hard idempotency token
        "version":    version,
        "child_id":   cid,
        "risk_level": risk_level,
        "score":      int(score),
        "delta":      delta,
        "reason":     reason,
        "is_offline": bool(is_offline),
        "escalation": str(escalation_level) if escalation_level is not None else "none",
        **payload_extras,
    }

    # Broadcast — import inline to keep pure-logic tests fast.
    from app.services.event_broadcaster import broadcaster
    for gid in guardian_ids:
        try:
            await broadcaster.broadcast_to_user(gid, "risk_update", event)
        except Exception as e:  # noqa: BLE001
            logger.exception(f"[RISK_EMIT] broadcast failed gid={gid}: {e}")

    # Commit state AFTER the broadcast attempt. Even if some broadcasts
    # failed, we still cache so we don't loop on the same trigger.
    _put_state(cid, RiskState(
        score=int(score),
        risk_level=risk_level,
        escalation_tier=esc_tier,
        is_offline=bool(is_offline),
        version=version,
    ))

    logger.info(
        f"[RISK_EMIT] child={cid} score={score} delta={delta:+d} "
        f"level={risk_level} reason={reason} v={version}"
    )
    return event


__all__ = [
    "RiskState",
    "ESC_TIER",
    "SCORE_DELTA_THRESHOLD",
    "should_emit",
    "maybe_emit_risk_update",
    "reset_state",
]
