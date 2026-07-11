"""NISCH-005 — Generic Redis-backed event dedup gate.

The pattern was first proven in `risk_emitter` (Redis state + atomic INCR
+ emit_key) and then again in `alert_trigger` (NX+EX cooldown). This
module is the canonical, reusable surface every other emitter should
reach for instead of rolling their own.

Strict invariants:
* `should_emit(...)` is idempotent inside the cooldown window — the
  *first* call within the window wins, every other call returns False.
* Multi-instance safe via Redis NX semantics. Falls back to a per-pod
  in-memory LRU when Redis is unavailable.
* Never raises. A Redis blip can never silence an alert.
* `kind` and `key` are namespaced separately so two unrelated emitters
  using the same `key` (e.g. a child's UUID) won't collide.

Usage:
    from app.services.event_dedup import should_emit
    if not should_emit("voice_distress", child_id, cooldown_s=30):
        return  # recent duplicate — skip

    # ... fire the actual alert ...
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from app.services import redis_service

logger = logging.getLogger(__name__)


# ── Tunables ────────────────────────────────────────────────────────
_DEFAULT_COOLDOWN_S = 30
_RS_NS = "event:dedup"           # within `nischint:` keyspace
_LOCAL_LRU: dict[str, float] = {}
_LOCAL_LRU_MAX = 4096


# ── Internal ────────────────────────────────────────────────────────
def _compose_key(kind: str, key: str) -> str:
    return f"{kind}:{key}"


def _evict_local() -> None:
    """Cheap LRU pruning when the local cache exceeds its cap."""
    if len(_LOCAL_LRU) <= _LOCAL_LRU_MAX:
        return
    cutoff = sorted(_LOCAL_LRU.values())[len(_LOCAL_LRU) // 4]
    for k, v in list(_LOCAL_LRU.items()):
        if v <= cutoff:
            _LOCAL_LRU.pop(k, None)


# ── Public API ──────────────────────────────────────────────────────
def should_emit(
    kind: str,
    key: Optional[str],
    *,
    cooldown_s: int = _DEFAULT_COOLDOWN_S,
) -> bool:
    """Return True iff the caller should proceed with the emission.

    Args:
        kind:        emitter family (e.g. "voice_distress", "risk_update").
                     Required.
        key:         idempotency identifier (e.g. user_id, journey_id).
                     If None or empty, dedup is bypassed (always returns True).
        cooldown_s:  silence window in seconds. ≤0 disables dedup.

    Behavior:
        Atomically claims `(kind, key)` for `cooldown_s` seconds.
        First caller wins → True. Subsequent callers within the window → False.
    """
    if not key or not str(key).strip() or cooldown_s <= 0:
        return True

    composed = _compose_key(kind, str(key).strip())

    # 1) Try Redis NX+EX (atomic, multi-instance safe).
    if redis_service.is_available():
        try:
            client = redis_service._get_client()
            if client is not None:
                full_key = f"nischint:{_RS_NS}:{composed}"
                ok = client.set(full_key, "1", nx=True, ex=cooldown_s)
                return bool(ok)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[EVENT_DEDUP] redis NX failed; falling through: {e}")

    # 2) Local LRU fallback.
    now = time.time()
    last = _LOCAL_LRU.get(composed, 0.0)
    if now - last < cooldown_s:
        return False
    _LOCAL_LRU[composed] = now
    _evict_local()
    return True


def reset_local(kind: Optional[str] = None, key: Optional[str] = None) -> None:
    """Test-only helper. Clears the local LRU. Does NOT touch Redis."""
    if kind is None and key is None:
        _LOCAL_LRU.clear()
        return
    prefix = f"{kind or ''}:{key or ''}"
    for k in list(_LOCAL_LRU.keys()):
        if k.startswith(prefix):
            _LOCAL_LRU.pop(k, None)


__all__ = ["should_emit", "reset_local"]
