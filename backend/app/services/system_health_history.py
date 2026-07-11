"""System-health transition history — Redis-backed replay tail.

Locked scope (user-mandated, NISCH-012.4+):
  * Two sources only: `v2_parity` (ALERT_TRIGGER_V2 shadow) and
    `sachet_health` (NDMA pre-warmer state machine). Future sources
    must be added explicitly in `KNOWN_SOURCES` so the schema is
    auditable.
  * Per-source capped list of **10** most recent transitions.
  * Storage primitive: `LPUSH` + `LTRIM 0 9` — atomic enough that
    a concurrent emitter never grows the list past the cap.
  * Replay format: same envelope as the live WS payload. No new
    schema, no transformation — operators see exactly what they
    would have received over WS.

Closes the operator-reload gap: every transition broadcast on
`cc:system_health_delta` is mirrored to a Redis history list, and
the SSE replay endpoint streams the tail to a freshly-connected
operator before resuming normal live delivery via the existing
WS channel.

Best-effort: Redis failures never propagate. A failed history
write is logged but does not block the live broadcast (the
operationally critical path).
"""
from __future__ import annotations

import json
import logging
from typing import Iterable

from app.services import redis_service

logger = logging.getLogger(__name__)

# Locked source allow-list. Adding a source is a deliberate decision —
# it controls what the SSE replay endpoint surfaces.
KNOWN_SOURCES: tuple[str, ...] = (
    "v2_parity", "sachet_health", "tomtom_health", "news_health",
)

# `nischint:system_health_history:<source>` — capped list, newest at head.
NAMESPACE = "system_health_history"
HISTORY_CAP = 10


def _key(source: str) -> str:
    return f"{redis_service.PREFIX}:{NAMESPACE}:{source}"


def record_transition(source: str, payload: dict) -> bool:
    """Append a transition envelope to the per-source capped list.

    Atomic primitive: `LPUSH` then `LTRIM 0 9` so the list NEVER
    exceeds `HISTORY_CAP`. Concurrent writers may briefly see 11
    entries between LPUSH and LTRIM but the next read always sees
    ≤10 — acceptable for an operator UI replay tail.

    Returns False (and logs at debug) on any error path. Never
    raises — the caller (live broadcaster) MUST not be blocked."""
    if source not in KNOWN_SOURCES:
        # Unknown source = silent drop. Prevents a typo'd hook from
        # creating an unbounded Redis key.
        logger.debug("[SH_HISTORY] dropping unknown source=%r", source)
        return False
    client = redis_service._get_client()
    if client is None:
        return False
    try:
        key = _key(source)
        client.lpush(key, json.dumps(payload, default=str))
        client.ltrim(key, 0, HISTORY_CAP - 1)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "[SH_HISTORY] record failed source=%s err=%r", source, e,
        )
        return False


def _decode_entries(raw_entries: Iterable) -> list[dict]:
    out: list[dict] = []
    for r in raw_entries:
        if r is None:
            continue
        try:
            out.append(json.loads(r))
        except Exception:
            # Malformed entry — skip. Don't fail the replay because
            # one history row has bad JSON.
            continue
    return out


def get_recent_transitions(source: str,
                           limit: int = HISTORY_CAP) -> list[dict]:
    """Return the latest `limit` transitions for `source` in
    **chronological order** (oldest first) — replay-friendly.

    Empty list on cold Redis, unknown source, or any error path."""
    if source not in KNOWN_SOURCES:
        return []
    client = redis_service._get_client()
    if client is None:
        return []
    try:
        # Redis list is newest-at-head; LRANGE 0..N-1 gives newest→oldest,
        # so we reverse to deliver oldest→newest for chronological replay.
        raw = client.lrange(_key(source), 0, max(0, limit - 1))
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "[SH_HISTORY] lrange failed source=%s err=%r", source, e,
        )
        return []
    entries = _decode_entries(raw)
    entries.reverse()
    return entries


def get_all_recent_transitions(limit_per_source: int = HISTORY_CAP) -> dict:
    """Return `{source: [chrono ordered events]}` for every known
    source. Stable shape — sources with no history yet appear as
    empty lists. Safe for the SSE endpoint's initial-replay step."""
    return {
        s: get_recent_transitions(s, limit=limit_per_source)
        for s in KNOWN_SOURCES
    }


def _clear_for_test(source: str | None = None) -> None:
    """Test-only seam. Removes history for one source (or all)."""
    client = redis_service._get_client()
    if client is None:
        return
    try:
        if source is None:
            for s in KNOWN_SOURCES:
                client.delete(_key(s))
        else:
            client.delete(_key(source))
    except Exception:
        pass


__all__ = [
    "KNOWN_SOURCES",
    "NAMESPACE",
    "HISTORY_CAP",
    "record_transition",
    "get_recent_transitions",
    "get_all_recent_transitions",
]
