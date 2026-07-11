"""
Guardian Trust Score Service — Human Reliability Intelligence Layer

Tracks how reliably each guardian responds to alerts. Score (0.0–1.0)
drives escalation priority: trusted guardians are notified FIRST.

Base trust formula:
    trust = 0.50 * response_rate
          + 0.30 * speed_factor
          + 0.20 * consistency

Where:
    response_rate   = acks / total_alerts_sent
    speed_factor    = max(0, 1 - avg_response_ms / 60_000)  # 60s = 0
    consistency     = max(0, 1 - missed_consecutive / 5)    # 5 misses = 0

V2 — Effective Trust at sort-time:
    effective_trust = trust_score * decay_factor * confidence_factor

        decay_factor       = exp(-days_since_last_event / 10)
        confidence_factor  = min(1.0, log(total_events + 1) / 3)

V2 — Dynamic Risk-Coupled Weighting (final sort key):
    sort_score = W_TRUST * effective_trust + W_PRIO * priority_norm

    WEIGHTS_BY_RISK:
        CRITICAL → trust 0.8 / priority 0.2
        RED      → trust 0.7 / priority 0.3
        YELLOW   → trust 0.6 / priority 0.4
        GREEN    → trust 0.5 / priority 0.5

Storage: Mongo collection `journey_guardian_trust` (upsert on every event).
In-memory cache is hydrated on module load.
"""
from __future__ import annotations

import logging
import math
import time
from typing import Any, Dict, List, Optional

from app.api import journey_store as _store

logger = logging.getLogger(__name__)

COL = "journey_guardian_trust"

# In-memory cache: contact_id -> stats dict
_CACHE: Dict[str, Dict[str, Any]] = {}

# V2 — Escalation Lock: incident_id -> [ordered_contact_ids]
# Once the first sort is done per SOS incident, the order is FROZEN.
# Prevents chaotic mid-incident re-ordering, duplicate notifications,
# and makes escalation deterministic for audit / replay.
_ESCALATION_LOCK: Dict[str, List[str]] = {}

# Weights
W_RESPONSE = 0.50
W_SPEED    = 0.30
W_CONSIST  = 0.20

# Bounds
SPEED_CAP_MS = 60_000     # > 60s = 0 speed credit
MISS_CAP     = 5          # 5+ consecutive misses = 0 consistency
DEFAULT_NEW_SCORE = 0.5   # fresh guardians start neutral (so they get chances)

# V2 — Time-decay + Confidence
DECAY_TAU_DAYS = 10.0     # exp(-days / 10) — gentler than 7
CONF_LOG_SCALE = 3.0      # log(n+1) / 3 caps at ~n=20

# V2 — Dynamic risk-coupled weights (trust vs configured priority)
WEIGHTS_BY_RISK: Dict[str, Dict[str, float]] = {
    "CRITICAL": {"trust": 0.8, "priority": 0.2},
    "RED":      {"trust": 0.7, "priority": 0.3},
    "YELLOW":   {"trust": 0.6, "priority": 0.4},
    "GREEN":    {"trust": 0.5, "priority": 0.5},
}
DEFAULT_RISK = "RED"  # fallback when risk_level is None/unknown

# Priority normalisation: lower priority number = more important.
# priority 1 → 1.0, priority 10+ → ~0.0
PRIO_MAX = 10.0


def _total_events(rec: Dict[str, Any]) -> int:
    """Total signal events for this guardian (alerts sent + misses + acks)."""
    return int(rec.get("total_alerts", 0) or 0) + int(rec.get("missed_consecutive", 0) or 0)


def _decay_factor(last_event_at: Optional[float]) -> float:
    """exp(-days_since_last_event / DECAY_TAU_DAYS). 1.0 when never-active (neutral)."""
    if not last_event_at:
        return 1.0
    days = max(0.0, (time.time() - float(last_event_at)) / 86400.0)
    return math.exp(-days / DECAY_TAU_DAYS)


def _confidence_factor(total_events: int) -> float:
    """min(1.0, log(n+1) / CONF_LOG_SCALE). 1 event ≈ 0.23, 20 events ≈ 1.0."""
    return min(1.0, math.log(total_events + 1) / CONF_LOG_SCALE)


def _priority_norm(priority: Any) -> float:
    """Normalise priority (1..PRIO_MAX) → (1.0..0.0). Lower priority # = higher value."""
    try:
        p = float(priority)
    except (TypeError, ValueError):
        p = 99.0
    if p <= 1:
        return 1.0
    if p >= PRIO_MAX:
        return 0.0
    return 1.0 - ((p - 1) / (PRIO_MAX - 1))


def _risk_weights(risk_level: Optional[str]) -> Dict[str, float]:
    key = (risk_level or DEFAULT_RISK).upper()
    # Legacy / alternative taxonomy aliases
    aliases = {
        "SAFE": "GREEN", "LOW": "GREEN", "OK": "GREEN",
        "MEDIUM": "YELLOW", "MED": "YELLOW", "WARN": "YELLOW", "WARNING": "YELLOW",
        "HIGH": "RED", "ELEVATED": "RED",
        "SEVERE": "CRITICAL", "SOS": "CRITICAL",
    }
    key = aliases.get(key, key)
    return WEIGHTS_BY_RISK.get(key, WEIGHTS_BY_RISK[DEFAULT_RISK])


def _blank(contact_id: str) -> Dict[str, Any]:
    return {
        "contact_id": contact_id,
        "total_alerts": 0,
        "ack_count": 0,
        "avg_response_ms": 0.0,  # running avg
        "missed_consecutive": 0,
        "last_event_at": None,
        "trust_score": DEFAULT_NEW_SCORE,
    }


def _compute_score(rec: Dict[str, Any]) -> float:
    total = rec.get("total_alerts", 0) or 0
    if total == 0:
        return DEFAULT_NEW_SCORE

    acks = rec.get("ack_count", 0) or 0
    response_rate = min(1.0, acks / total)

    avg_ms = rec.get("avg_response_ms", 0) or 0
    speed = max(0.0, 1.0 - (avg_ms / SPEED_CAP_MS))

    missed = rec.get("missed_consecutive", 0) or 0
    consistency = max(0.0, 1.0 - (missed / MISS_CAP))

    return round(W_RESPONSE * response_rate + W_SPEED * speed + W_CONSIST * consistency, 4)


def _db():
    _store._init()
    return _store._db if _store._enabled else None


def _persist(contact_id: str) -> None:
    db = _db()
    if db is None:
        return
    try:
        rec = _CACHE.get(contact_id)
        if rec is None:
            return
        db[COL].update_one({"_id": contact_id}, {"$set": {**rec, "_id": contact_id}}, upsert=True)
    except Exception as e:
        logger.error(f"[GUARDIAN_TRUST] persist({contact_id}) failed: {e}")


def _hydrate() -> None:
    """Load persisted trust scores on module import."""
    db = _db()
    if db is None:
        return
    try:
        for doc in db[COL].find():
            cid = doc.get("_id")
            if cid:
                doc.pop("_id", None)
                _CACHE[cid] = doc
        if _CACHE:
            logger.info(f"[GUARDIAN_TRUST] hydrated {len(_CACHE)} records from Mongo")
    except Exception as e:
        logger.error(f"[GUARDIAN_TRUST] hydrate failed: {e}")


# ── Public API ─────────────────────────────────────────────────────

def record_alert_sent(contact_id: str) -> None:
    rec = _CACHE.setdefault(contact_id, _blank(contact_id))
    rec["total_alerts"] = int(rec.get("total_alerts", 0)) + 1
    rec["last_event_at"] = time.time()
    rec["trust_score"] = _compute_score(rec)
    _persist(contact_id)


def record_ack(contact_id: str, latency_ms: float) -> None:
    rec = _CACHE.setdefault(contact_id, _blank(contact_id))
    n = int(rec.get("ack_count", 0))
    prev_avg = float(rec.get("avg_response_ms", 0) or 0)
    # Incremental mean
    rec["ack_count"] = n + 1
    rec["avg_response_ms"] = round(((prev_avg * n) + max(0.0, float(latency_ms))) / (n + 1), 1)
    rec["missed_consecutive"] = 0  # reset the streak
    rec["last_event_at"] = time.time()
    rec["trust_score"] = _compute_score(rec)
    _persist(contact_id)
    logger.info(
        f"[GUARDIAN_TRUST] ACK contact={contact_id} "
        f"latency={latency_ms}ms avg={rec['avg_response_ms']}ms score={rec['trust_score']}"
    )


def record_missed(contact_id: str) -> None:
    rec = _CACHE.setdefault(contact_id, _blank(contact_id))
    rec["missed_consecutive"] = int(rec.get("missed_consecutive", 0)) + 1
    rec["last_event_at"] = time.time()
    rec["trust_score"] = _compute_score(rec)
    _persist(contact_id)
    logger.warning(
        f"[GUARDIAN_TRUST] MISSED contact={contact_id} "
        f"consecutive={rec['missed_consecutive']} score={rec['trust_score']}"
    )


def get_trust_score(contact_id: str) -> float:
    rec = _CACHE.get(contact_id)
    if rec is None:
        return DEFAULT_NEW_SCORE
    return float(rec.get("trust_score", DEFAULT_NEW_SCORE))


def get_stats(contact_id: str) -> Dict[str, Any]:
    rec = dict(_CACHE.get(contact_id) or _blank(contact_id))
    rec["effective_trust"] = get_effective_trust(contact_id)
    rec["decay_factor"] = round(_decay_factor(rec.get("last_event_at")), 4)
    rec["confidence_factor"] = round(_confidence_factor(_total_events(rec)), 4)
    return rec


def list_all() -> List[Dict[str, Any]]:
    return [dict(v) for v in _CACHE.values()]


def get_effective_trust(contact_id: str) -> float:
    """
    trust_score * decay_factor * confidence_factor

    • decay_factor: older inactivity → lower weight (τ=10 days)
    • confidence_factor: few events → damped (log scale)
    """
    rec = _CACHE.get(contact_id)
    if rec is None:
        return DEFAULT_NEW_SCORE
    base = float(rec.get("trust_score", DEFAULT_NEW_SCORE))
    decay = _decay_factor(rec.get("last_event_at"))
    conf = _confidence_factor(_total_events(rec))
    return round(base * decay * conf, 4)


def sort_guardians_by_trust(
    guardians: List[Dict[str, Any]],
    risk_level: Optional[str] = None,
    incident_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Sort contact dicts (each has 'id' and 'priority') using risk-coupled
    weighted score:

        score = W_TRUST * effective_trust
              + W_PRIO  * priority_norm

    Escalation Lock (when `incident_id` is provided):
        • If lock already exists for this incident → return guardians reordered
          to match the frozen order (any unknown extras appended at the end).
        • Otherwise compute fresh sort AND freeze the order under `incident_id`.

    Without `incident_id` the sort runs fresh every call (legacy behaviour).
    Tiebreaker: raw priority ASC (configured family order).
    """
    if not guardians:
        return []

    # ── 1. Escalation lock hit → replay frozen order ──
    if incident_id and incident_id in _ESCALATION_LOCK:
        frozen = _ESCALATION_LOCK[incident_id]
        by_id = {g.get("id", ""): g for g in guardians}
        ordered = [by_id[cid] for cid in frozen if cid in by_id]
        # Append any newly-added guardians not present at lock time
        seen = set(frozen)
        for g in guardians:
            if g.get("id", "") not in seen:
                ordered.append(g)
        return ordered

    # ── 2. Fresh weighted sort ──
    weights = _risk_weights(risk_level)
    w_trust = weights["trust"]
    w_prio = weights["priority"]

    def key(g: Dict[str, Any]):
        cid = g.get("id", "")
        eff_trust = get_effective_trust(cid)
        prio_norm = _priority_norm(g.get("priority", 99))
        score = (w_trust * eff_trust) + (w_prio * prio_norm)
        # Sort DESC by score → negate; tiebreak ASC priority
        return (-score, int(g.get("priority", 99) or 99))

    sorted_list = sorted(guardians, key=key)

    # ── 3. Freeze lock for this incident ──
    if incident_id:
        _ESCALATION_LOCK[incident_id] = [g.get("id", "") for g in sorted_list]
        logger.info(
            f"[ESCALATION_LOCK] incident={incident_id} locked order "
            f"({risk_level or DEFAULT_RISK}): "
            f"{[g.get('id') for g in sorted_list]}"
        )

    return sorted_list


def release_escalation_lock(incident_id: str) -> bool:
    """Clear the frozen order for an incident (on resolve / fail)."""
    removed = _ESCALATION_LOCK.pop(incident_id, None)
    if removed is not None:
        logger.info(f"[ESCALATION_LOCK] incident={incident_id} released")
        return True
    return False


def get_escalation_lock(incident_id: str) -> Optional[List[str]]:
    """Return the frozen order for an incident, or None."""
    order = _ESCALATION_LOCK.get(incident_id)
    return list(order) if order is not None else None


# Hydrate on import
_hydrate()
