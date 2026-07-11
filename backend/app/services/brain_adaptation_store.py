"""
AI Brain Adaptation Store — Personal Safety Model persistence.

Stores the learned threshold adjustment + rich behavioral profile per user in
MongoDB (`ai_brain_adaptation` collection) so intelligence compounds across
container restarts — learned lessons are never lost.

Document shape:
    {
      "_id": "<user_id>",
      "user_id": "<user_id>",
      "adjustment": +7,               # signed, bounded ±_USER_ADJUST_MAX
      "updated_at": "2026-02-XX…",    # ISO UTC
      "feedback_summary": {
        "true_positive": 12,
        "false_alarm":   4,
        "missed":        2,
        "weighted_fp_rate":     0.22,
        "weighted_missed_rate": 0.11
      },
      "confidence_profile": {
        "avg_confidence":       0.71,
        "high_conf_error_rate": 0.18
      }
    }

Read-path applies TIME-DECAY automatically: old adjustments fade.
    decayed = adjustment * exp(-days_since_update / DECAY_TAU_DAYS)

Write-path applies SMOOTHING to prevent sudden jumps:
    new = round(0.7 * old + 0.3 * target_delta)
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.api import journey_store as _store

logger = logging.getLogger(__name__)

COL = "ai_brain_adaptation"

# Time-decay: old adjustments fade if the user has not produced feedback in a while.
# exp(-days / 30) — 30d inactivity ≈ 37% retained, 60d ≈ 14%, 90d ≈ 5%.
DECAY_TAU_DAYS = 30.0

# Smoothing coefficient on write: new = 0.7 * old + 0.3 * target
# Protects against sudden big jumps from a single batch of feedback.
SMOOTHING_ALPHA_OLD = 0.7
SMOOTHING_ALPHA_NEW = 0.3


def _db():
    _store._init()
    return _store._db if _store._enabled else None


# ── Persistence ────────────────────────────────────────────────────

def load_all() -> Dict[str, Dict[str, Any]]:
    """Hydrate all adaptation records from Mongo (called on module startup)."""
    db = _db()
    if db is None:
        return {}
    try:
        records = {}
        for doc in db[COL].find():
            uid = doc.get("_id") or doc.get("user_id")
            if uid:
                doc.pop("_id", None)
                records[uid] = doc
        if records:
            logger.info(f"[BRAIN_ADAPT] hydrated {len(records)} user profiles from Mongo")
        return records
    except Exception as e:
        logger.error(f"[BRAIN_ADAPT] hydrate failed: {e}")
        return {}


def upsert(user_id: str, record: Dict[str, Any]) -> None:
    """Persist full adaptation record for a user."""
    db = _db()
    if db is None:
        return
    try:
        payload = {**record, "_id": user_id, "user_id": user_id}
        db[COL].update_one({"_id": user_id}, {"$set": payload}, upsert=True)
    except Exception as e:
        logger.error(f"[BRAIN_ADAPT] upsert({user_id}) failed: {e}")


# ── Time-decay (read-path) ──────────────────────────────────────────

def apply_decay(adjustment: int, updated_at_iso: Optional[str]) -> int:
    """
    Fade the stored adjustment based on days since last update.
    Returns a rounded, bounded int.
    """
    if not adjustment or not updated_at_iso:
        return int(adjustment or 0)
    try:
        last = datetime.fromisoformat(updated_at_iso.replace("Z", "+00:00"))
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        days = max(0.0, (now - last).total_seconds() / 86400.0)
        factor = math.exp(-days / DECAY_TAU_DAYS)
        return int(round(adjustment * factor))
    except Exception:
        return int(adjustment)


# ── Smoothing (write-path) ──────────────────────────────────────────

def smooth(old_adjustment: int, target_adjustment: int) -> int:
    """
    new = round(0.7 * old + 0.3 * target)
    Prevents sudden jumps from a single burst of feedback.
    """
    val = SMOOTHING_ALPHA_OLD * old_adjustment + SMOOTHING_ALPHA_NEW * target_adjustment
    return int(round(val))


def build_profile(
    user_id: str,
    adjustment: int,
    feedbacks: list[dict],
) -> Dict[str, Any]:
    """
    Build the rich adaptation document (summary + confidence profile) from
    the current in-memory feedback list.
    """
    n = len(feedbacks)

    def _w(fb: dict) -> float:
        return max(0.0, min(1.0, float(fb.get("decision_confidence", 0.5) or 0.5)))

    tp = sum(1 for f in feedbacks if f.get("outcome") == "true_positive")
    fa = sum(1 for f in feedbacks if f.get("outcome") == "false_alarm")
    miss = sum(1 for f in feedbacks if f.get("outcome") == "missed")

    wtot = sum(_w(f) for f in feedbacks) or 0.0
    w_fa = sum(_w(f) for f in feedbacks if f.get("outcome") == "false_alarm")
    w_miss = sum(_w(f) for f in feedbacks if f.get("outcome") == "missed")

    avg_conf = (wtot / n) if n else 0.0
    # "High-conf error rate" = fraction of feedbacks that are errors AND have conf>=0.7
    wrong_high = sum(
        1 for f in feedbacks
        if f.get("outcome") in {"false_alarm", "missed"} and _w(f) >= 0.7
    )
    high_conf_error_rate = (wrong_high / n) if n else 0.0

    return {
        "user_id": user_id,
        "adjustment": int(adjustment),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "feedback_summary": {
            "true_positive": tp,
            "false_alarm": fa,
            "missed": miss,
            "weighted_fp_rate": round(w_fa / wtot, 3) if wtot else 0.0,
            "weighted_missed_rate": round(w_miss / wtot, 3) if wtot else 0.0,
        },
        "confidence_profile": {
            "avg_confidence": round(avg_conf, 3),
            "high_conf_error_rate": round(high_conf_error_rate, 3),
        },
    }
