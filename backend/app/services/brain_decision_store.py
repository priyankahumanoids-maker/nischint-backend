"""
AI Brain Decision Store — Permanent audit log of every brain decision.

Collection: `ai_brain_decisions`
    • Indexed on `user_id` and `decided_at` (DESC).
    • TTL index on `decided_at` — auto-expires documents after DECISION_TTL_DAYS.
    • Schema:
        {
          "_id":              <event_id>,
          "event_id":         str,
          "user_id":          str,
          "user_type":        str,
          "decided_at":       datetime (UTC, for TTL),
          "risk_score":       int,
          "risk_level":       "GREEN|YELLOW|RED|CRITICAL",
          "confidence":       float,
          "effective_score":  float,
          "recommended_action": str,
          "cooldown_applied": bool,
          "executed":         bool,
          "triggers_fired":   [str],
          "reason":           str,
          "guardian_selected": {id, name, trust_score, effective_trust} | null,
          "signals":          {...},
          "feedback":         {outcome, decision_confidence, received_at} | null  (populated later)
        }

Write path: `insert_decision(doc)` — fire-and-forget, never blocks decision flow.
Feedback path: `update_feedback(event_id, feedback)` — patches same doc.
Read path:     `recent(limit, user_id=None)` — prefer Mongo; timeline API delegates.

Silent fallback: if Mongo is unavailable, all ops no-op and the module stays
in-memory-only. Hot-path latency is never affected.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.api import journey_store as _store

logger = logging.getLogger(__name__)

COL = "ai_brain_decisions"

# TTL in days — documents auto-expire after this. 90d gives ample audit window
# without unbounded growth. Can be tuned per-compliance later.
DECISION_TTL_DAYS = 90
_TTL_SECONDS = DECISION_TTL_DAYS * 86400

_indexes_ensured = False


def _db():
    _store._init()
    return _store._db if _store._enabled else None


def _ensure_indexes() -> None:
    global _indexes_ensured
    if _indexes_ensured:
        return
    db = _db()
    if db is None:
        return
    try:
        col = db[COL]
        col.create_index("user_id")
        col.create_index([("decided_at", -1)])
        # Compound index — optimises the most common query: filter by user, sort by time.
        col.create_index(
            [("user_id", 1), ("decided_at", -1)],
            name="user_timeline",
        )
        # TTL — Mongo auto-deletes when (decided_at + expireAfterSeconds) < now
        col.create_index("decided_at", expireAfterSeconds=_TTL_SECONDS, name="ttl_decided_at")
        _indexes_ensured = True
        logger.info(
            f"[BRAIN_DECISION_STORE] indexes ensured on '{COL}' "
            f"(ttl={DECISION_TTL_DAYS}d)"
        )
    except Exception as e:
        logger.warning(f"[BRAIN_DECISION_STORE] index ensure failed: {e}")


# ── Read-path projection (performance) ─────────────────────────────
# When a caller only needs timeline rendering, skip the heavy fields
# (signals breakdown, guardian details, etc.). Cuts payload ~70%.
SUMMARY_PROJECTION: Dict[str, int] = {
    "_id": 0,
    "event_id": 1,
    "user_id": 1,
    "user_type": 1,
    "decided_at": 1,
    "risk_score": 1,
    "risk_level": 1,
    "confidence": 1,
    "recommended_action": 1,
    "executed": 1,
    "cooldown_applied": 1,
    "reason": 1,
    "triggers_fired": 1,
    "feedback": 1,
    "latency_ms": 1,
}

# Hard ceiling on any API-driven read to protect Mongo + bandwidth.
MAX_LIMIT = 100


# ── Write path ─────────────────────────────────────────────────────

def _to_doc(decision: Dict[str, Any]) -> Dict[str, Any]:
    """
    Project the decision dict into the Mongo schema.
    Drops verbose fields we don't need for audit (thresholds_used, stage_scores).
    """
    # decided_at must be a datetime for TTL to work
    raw_ts = decision.get("decided_at")
    if isinstance(raw_ts, str):
        try:
            ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
        except Exception:
            ts = datetime.now(timezone.utc)
    elif isinstance(raw_ts, datetime):
        ts = raw_ts
    else:
        ts = datetime.now(timezone.utc)

    return {
        "_id": decision.get("event_id"),
        "event_id": decision.get("event_id"),
        "user_id": decision.get("user_id"),
        "user_type": decision.get("user_type"),
        "decided_at": ts,
        "risk_score": decision.get("risk_score"),
        "risk_level": decision.get("risk_level"),
        "confidence": decision.get("confidence"),
        "effective_score": decision.get("effective_score"),
        "final_score": decision.get("final_score"),
        "recommended_action": decision.get("recommended_action"),
        "original_action": decision.get("original_action"),
        "cooldown_applied": bool(decision.get("cooldown_applied")),
        "executed": bool(decision.get("executed")),
        "triggers_fired": decision.get("triggers_fired") or [],
        "reason": decision.get("reason"),
        "guardian_selected": decision.get("guardian_selected"),
        "signals": decision.get("signals_breakdown") or {},
        "latency_ms": decision.get("latency_ms"),
        "feedback": decision.get("feedback"),
    }


def insert_decision(decision: Dict[str, Any]) -> None:
    """Fire-and-forget persistence. Never blocks the caller."""
    db = _db()
    if db is None:
        return
    _ensure_indexes()
    try:
        doc = _to_doc(decision)
        db[COL].update_one({"_id": doc["_id"]}, {"$set": doc}, upsert=True)
    except Exception as e:
        logger.warning(f"[BRAIN_DECISION_STORE] insert failed: {e}")


def update_feedback(event_id: str, feedback: Dict[str, Any]) -> None:
    """Patch the decision doc with feedback after record_feedback runs."""
    db = _db()
    if db is None or not event_id:
        return
    try:
        db[COL].update_one({"_id": event_id}, {"$set": {"feedback": feedback}})
    except Exception as e:
        logger.warning(f"[BRAIN_DECISION_STORE] feedback update failed: {e}")


# ── Read path ──────────────────────────────────────────────────────

def _serialize(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Convert Mongo doc → API-friendly dict (ISO string for decided_at, no _id)."""
    doc.pop("_id", None)
    ts = doc.get("decided_at")
    if isinstance(ts, datetime):
        doc["decided_at"] = ts.astimezone(timezone.utc).isoformat()
    return doc


def find_by_event_id(event_id: str) -> Optional[Dict[str, Any]]:
    """Direct `_id` lookup — used by record_feedback rehydration path."""
    db = _db()
    if db is None or not event_id:
        return None
    try:
        doc = db[COL].find_one({"_id": event_id})
        return _serialize(doc) if doc else None
    except Exception as e:
        logger.warning(f"[BRAIN_DECISION_STORE] find_by_event_id failed: {e}")
        return None


def recent(
    limit: int = 50,
    user_id: Optional[str] = None,
    summary: bool = True,
) -> List[Dict[str, Any]]:
    """
    Read last N decisions (descending by decided_at).

    Args:
        limit:    cap is enforced server-side at MAX_LIMIT (100).
        user_id:  when provided, uses the compound index `user_timeline`.
        summary:  when True (default), returns only fields needed by the Timeline
                  UI — cuts payload ~70%. Set False for full audit pulls.

    Returns [] when Mongo is unavailable — caller falls back to in-memory log.
    """
    db = _db()
    if db is None:
        return []
    try:
        safe_limit = max(1, min(MAX_LIMIT, int(limit)))
        query = {"user_id": user_id} if user_id else {}
        projection = SUMMARY_PROJECTION if summary else None
        cur = db[COL].find(query, projection=projection).sort("decided_at", -1).limit(safe_limit)
        return [_serialize(d) for d in cur]
    except Exception as e:
        logger.warning(f"[BRAIN_DECISION_STORE] read failed: {e}")
        return []


def is_enabled() -> bool:
    return _db() is not None
