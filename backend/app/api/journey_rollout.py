"""
NISCHINT Journey Engine — Staged Rollout Control System

Dual-control gate:
    GLOBAL_FLAG (JOURNEY_LIVE_DELIVERY env)  +  SESSION_ALLOWLIST (Mongo)  +  KILL_SWITCH (Mongo)

Mongo Collections:
    journey_rollout_config     — single doc {_id='config', emergency_stop, current_stage}
    journey_rollout_allowlist  — {_id=session_id, enabled, stage, added_at, added_by, notes}
    journey_rollout_metrics    — {_id=session_id, sos_count, sms_real, sms_sim, push_real, push_sim,
                                  ack_count, total_ack_ms, confidence_sum, confidence_count, last_sos_at}

Rollout Stages:
    stage1_internal      target=5    purpose="Internal testing (you + trusted circle)"
    stage2_controlled    target=50   purpose="Controlled pilot (mixed user profiles)"
    stage3_soft_launch   target=500  purpose="Soft launch measuring TTHR + delivery success"
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api import journey_store as _store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/journey/rollout", tags=["Journey Rollout"])

COL_CONFIG = "journey_rollout_config"
COL_ALLOWLIST = "journey_rollout_allowlist"
COL_METRICS = "journey_rollout_metrics"

STAGES = {
    "stage1_internal":   {"target": 5,   "purpose": "Internal testing (you + trusted circle)"},
    "stage2_controlled": {"target": 50,  "purpose": "Controlled pilot (mixed user profiles + cities)"},
    "stage3_soft_launch":{"target": 500, "purpose": "Soft launch — measure TTHR + delivery success"},
}

# In-memory cache (write-through)
_config_cache: Dict[str, Any] = {"emergency_stop": False, "current_stage": "stage1_internal"}
_allowlist_cache: Dict[str, Dict[str, Any]] = {}   # session_id -> record
_metrics_cache: Dict[str, Dict[str, Any]] = {}     # session_id -> counters

_DEFAULT_METRICS = {
    "sos_count": 0, "sms_real": 0, "sms_sim": 0, "push_real": 0, "push_sim": 0,
    "ack_count": 0, "total_ack_ms": 0, "confidence_sum": 0, "confidence_count": 0,
    "last_sos_at": None,
}


def _db():
    """Get pymongo DB handle via journey_store (shares the same client)."""
    _store._init()
    return _store._db if _store._enabled else None


# ── CONFIG (global kill switch + stage) ──

def load_config() -> Dict[str, Any]:
    db = _db()
    if db is None:
        return _config_cache
    try:
        doc = db[COL_CONFIG].find_one({"_id": "config"}) or {}
        doc.pop("_id", None)
        _config_cache.update({
            "emergency_stop": bool(doc.get("emergency_stop", False)),
            "current_stage": doc.get("current_stage", "stage1_internal"),
        })
    except Exception as e:
        logger.error(f"[ROLLOUT] load_config failed: {e}")
    return _config_cache


def save_config(emergency_stop: Optional[bool] = None, current_stage: Optional[str] = None, actor: str = "system") -> Dict[str, Any]:
    if emergency_stop is not None:
        _config_cache["emergency_stop"] = bool(emergency_stop)
    if current_stage is not None:
        if current_stage not in STAGES:
            raise HTTPException(status_code=400, detail=f"Invalid stage. Valid: {list(STAGES.keys())}")
        _config_cache["current_stage"] = current_stage
    _config_cache["updated_at"] = datetime.now(timezone.utc).isoformat()
    _config_cache["updated_by"] = actor
    db = _db()
    if db is not None:
        try:
            db[COL_CONFIG].update_one({"_id": "config"}, {"$set": {**_config_cache, "_id": "config"}}, upsert=True)
        except Exception as e:
            logger.error(f"[ROLLOUT] save_config failed: {e}")
    if emergency_stop is True:
        logger.critical(f"[ROLLOUT_KILL_SWITCH] Emergency stop ENGAGED by {actor}")
    elif emergency_stop is False:
        logger.warning(f"[ROLLOUT_KILL_SWITCH] Emergency stop RELEASED by {actor}")
    return _config_cache


# ── ALLOWLIST ──

def load_allowlist() -> Dict[str, Dict[str, Any]]:
    db = _db()
    if db is None:
        return _allowlist_cache
    try:
        _allowlist_cache.clear()
        for doc in db[COL_ALLOWLIST].find():
            sid = doc.get("_id")
            if sid:
                doc.pop("_id", None)
                doc["session_id"] = sid
                _allowlist_cache[sid] = doc
    except Exception as e:
        logger.error(f"[ROLLOUT] load_allowlist failed: {e}")
    return _allowlist_cache


def is_session_allowlisted(session_id: str) -> bool:
    if not session_id:
        return False
    rec = _allowlist_cache.get(session_id)
    if not rec:
        return False
    return bool(rec.get("enabled", False))


def upsert_session(session_id: str, enabled: bool = True, stage: str = "stage1_internal",
                   added_by: str = "admin", notes: str = "") -> Dict[str, Any]:
    if stage not in STAGES:
        raise HTTPException(status_code=400, detail=f"Invalid stage")
    now = datetime.now(timezone.utc).isoformat()
    existing = _allowlist_cache.get(session_id, {})
    rec = {
        "session_id": session_id,
        "enabled": bool(enabled),
        "stage": stage,
        "added_at": existing.get("added_at", now),
        "updated_at": now,
        "added_by": existing.get("added_by", added_by),
        "notes": notes or existing.get("notes", ""),
    }
    _allowlist_cache[session_id] = rec
    db = _db()
    if db is not None:
        try:
            db[COL_ALLOWLIST].update_one({"_id": session_id}, {"$set": {**rec, "_id": session_id}}, upsert=True)
        except Exception as e:
            logger.error(f"[ROLLOUT] upsert_session failed: {e}")
    logger.info(f"[ROLLOUT] session {session_id} → enabled={enabled} stage={stage}")
    return rec


def remove_session(session_id: str) -> bool:
    if session_id not in _allowlist_cache:
        return False
    _allowlist_cache.pop(session_id, None)
    db = _db()
    if db is not None:
        try:
            db[COL_ALLOWLIST].delete_one({"_id": session_id})
        except Exception as e:
            logger.error(f"[ROLLOUT] remove_session failed: {e}")
    return True


# ── METRICS ──

def _metric_record(session_id: str) -> Dict[str, Any]:
    rec = _metrics_cache.get(session_id)
    if rec is None:
        rec = {**_DEFAULT_METRICS, "session_id": session_id}
        _metrics_cache[session_id] = rec
    return rec


def _persist_metric(session_id: str, rec: Dict[str, Any]) -> None:
    db = _db()
    if db is None:
        return
    try:
        db[COL_METRICS].update_one({"_id": session_id}, {"$set": {**rec, "_id": session_id}}, upsert=True)
    except Exception as e:
        logger.error(f"[ROLLOUT] _persist_metric failed: {e}")


def record_sos(session_id: str) -> None:
    if not session_id:
        return
    rec = _metric_record(session_id)
    rec["sos_count"] += 1
    rec["last_sos_at"] = datetime.now(timezone.utc).isoformat()
    _persist_metric(session_id, rec)


def record_delivery(session_id: str, sms_real: int = 0, sms_sim: int = 0,
                    push_real: int = 0, push_sim: int = 0) -> None:
    if not session_id:
        return
    rec = _metric_record(session_id)
    rec["sms_real"] += sms_real
    rec["sms_sim"] += sms_sim
    rec["push_real"] += push_real
    rec["push_sim"] += push_sim
    _persist_metric(session_id, rec)


def record_ack(session_id: str, ack_latency_ms: int) -> None:
    if not session_id:
        return
    rec = _metric_record(session_id)
    rec["ack_count"] += 1
    rec["total_ack_ms"] += max(0, int(ack_latency_ms))
    _persist_metric(session_id, rec)


def record_confidence(session_id: str, confidence: int) -> None:
    if not session_id:
        return
    rec = _metric_record(session_id)
    rec["confidence_sum"] += int(confidence)
    rec["confidence_count"] += 1
    _persist_metric(session_id, rec)


def compute_confidence(sms_success: bool, push_success: bool, guardian_acked: bool) -> int:
    """Delivery Confidence = 40 (sms) + 30 (push) + 30 (ack) = 0..100."""
    return (40 if sms_success else 0) + (30 if push_success else 0) + (30 if guardian_acked else 0)


def get_metrics_summary() -> Dict[str, Any]:
    sessions = list(_metrics_cache.values())
    total_sos = sum(r["sos_count"] for r in sessions)
    total_sms_real = sum(r["sms_real"] for r in sessions)
    total_sms_sim = sum(r["sms_sim"] for r in sessions)
    total_push_real = sum(r["push_real"] for r in sessions)
    total_push_sim = sum(r["push_sim"] for r in sessions)
    total_ack = sum(r["ack_count"] for r in sessions)
    total_ack_ms = sum(r["total_ack_ms"] for r in sessions)
    conf_sum = sum(r["confidence_sum"] for r in sessions)
    conf_count = sum(r["confidence_count"] for r in sessions)
    avg_ack_sec = round((total_ack_ms / total_ack) / 1000, 2) if total_ack else None
    avg_confidence = round(conf_sum / conf_count, 1) if conf_count else None
    # Top sessions
    top = sorted(sessions, key=lambda r: r["sos_count"], reverse=True)[:10]
    return {
        "totals": {
            "sos": total_sos,
            "sms_real": total_sms_real, "sms_sim": total_sms_sim,
            "push_real": total_push_real, "push_sim": total_push_sim,
            "ack_count": total_ack,
            "avg_ack_seconds": avg_ack_sec,
            "avg_delivery_confidence": avg_confidence,
        },
        "sessions_tracked": len(sessions),
        "top_sessions": top,
    }


def _hydrate_metrics() -> None:
    db = _db()
    if db is None:
        return
    try:
        for doc in db[COL_METRICS].find():
            sid = doc.get("_id")
            if sid:
                doc.pop("_id", None)
                _metrics_cache[sid] = {**_DEFAULT_METRICS, **doc, "session_id": sid}
    except Exception as e:
        logger.error(f"[ROLLOUT] _hydrate_metrics failed: {e}")


# ── UNIFIED GATE (used by journey_delivery) ──

def rollout_gate(session_id: Optional[str]) -> Dict[str, Any]:
    """
    Returns {allowed, reason, stage} for a given session.
    Priority: emergency_stop > live_flag (checked by caller) > allowlist.
    """
    cfg = _config_cache
    if cfg.get("emergency_stop"):
        return {"allowed": False, "reason": "emergency_stop", "stage": cfg.get("current_stage")}
    if not session_id:
        return {"allowed": False, "reason": "no_session_id", "stage": cfg.get("current_stage")}
    rec = _allowlist_cache.get(session_id)
    if not rec or not rec.get("enabled"):
        return {"allowed": False, "reason": "session_not_allowlisted", "stage": cfg.get("current_stage")}
    return {"allowed": True, "reason": "ok", "stage": rec.get("stage", cfg.get("current_stage"))}


# ═══════════════════════════════════════════════
# API ENDPOINTS
# ═══════════════════════════════════════════════

class ConfigUpdate(BaseModel):
    emergency_stop: Optional[bool] = None
    current_stage: Optional[str] = None
    actor: str = "admin"


class SessionUpsert(BaseModel):
    session_id: str
    enabled: bool = True
    stage: str = "stage1_internal"
    added_by: str = "admin"
    notes: str = ""


class BulkUpsert(BaseModel):
    session_ids: List[str]
    enabled: bool = True
    stage: str = "stage1_internal"
    added_by: str = "admin"
    notes: str = ""


@router.get("/config")
def get_config():
    """Returns global rollout config: kill switch + current stage + env flag."""
    from app.core.config import settings
    cfg = load_config()
    allow = load_allowlist()
    counts_by_stage = {s: 0 for s in STAGES}
    enabled_total = 0
    for rec in allow.values():
        if rec.get("enabled"):
            enabled_total += 1
            st = rec.get("stage", "stage1_internal")
            counts_by_stage[st] = counts_by_stage.get(st, 0) + 1
    return {
        "config": cfg,
        "env": {
            "live_delivery_flag": bool(settings.journey_live_delivery),
            "max_sos_per_hour": settings.journey_max_sos_per_hour,
        },
        "stages": STAGES,
        "allowlist_counts": {
            "total_sessions": len(allow),
            "enabled_total": enabled_total,
            "by_stage": counts_by_stage,
        },
    }


@router.post("/config")
def update_config(payload: ConfigUpdate):
    cfg = save_config(payload.emergency_stop, payload.current_stage, payload.actor)
    return {"status": "ok", "config": cfg}


@router.post("/emergency-stop")
def emergency_stop(actor: str = "admin"):
    """KILL SWITCH — engage emergency stop (blocks ALL real delivery)."""
    cfg = save_config(emergency_stop=True, actor=actor)
    return {"status": "engaged", "config": cfg}


@router.post("/emergency-release")
def emergency_release(actor: str = "admin"):
    """Release emergency stop. Requires explicit call to prevent accidental resumes."""
    cfg = save_config(emergency_stop=False, actor=actor)
    return {"status": "released", "config": cfg}


@router.get("/allowlist")
def list_allowlist(stage: Optional[str] = None, enabled_only: bool = False):
    allow = load_allowlist()
    items = list(allow.values())
    if stage:
        items = [r for r in items if r.get("stage") == stage]
    if enabled_only:
        items = [r for r in items if r.get("enabled")]
    items.sort(key=lambda r: r.get("added_at", ""), reverse=True)
    return {"allowlist": items, "count": len(items)}


@router.post("/allowlist")
def add_session(payload: SessionUpsert):
    rec = upsert_session(payload.session_id, payload.enabled, payload.stage, payload.added_by, payload.notes)
    return {"status": "ok", "session": rec}


@router.post("/allowlist/bulk")
def bulk_add(payload: BulkUpsert):
    results = []
    for sid in payload.session_ids:
        sid = sid.strip()
        if not sid:
            continue
        results.append(upsert_session(sid, payload.enabled, payload.stage, payload.added_by, payload.notes))
    return {"status": "ok", "added": len(results), "sessions": results}


@router.delete("/allowlist/{session_id}")
def delete_session(session_id: str):
    if not remove_session(session_id):
        raise HTTPException(status_code=404, detail="Session not in allowlist")
    return {"status": "ok", "removed": session_id}


@router.get("/metrics")
def get_metrics():
    return get_metrics_summary()


@router.get("/metrics/{session_id}")
def get_session_metrics(session_id: str):
    rec = _metrics_cache.get(session_id)
    if not rec:
        return {"session_id": session_id, **_DEFAULT_METRICS}
    avg_ack = round((rec["total_ack_ms"] / rec["ack_count"]) / 1000, 2) if rec["ack_count"] else None
    avg_conf = round(rec["confidence_sum"] / rec["confidence_count"], 1) if rec["confidence_count"] else None
    return {**rec, "avg_ack_seconds": avg_ack, "avg_delivery_confidence": avg_conf}


@router.get("/gate-check/{session_id}")
def check_gate(session_id: str):
    """Diagnostic: returns what the gate would decide for this session."""
    from app.core.config import settings
    cfg = load_config()
    gate = rollout_gate(session_id)
    return {
        "session_id": session_id,
        "global_live_flag": bool(settings.journey_live_delivery),
        "emergency_stop": cfg.get("emergency_stop"),
        "gate_decision": gate,
        "would_deliver_real": (
            bool(settings.journey_live_delivery)
            and not cfg.get("emergency_stop")
            and gate["allowed"]
        ),
    }


# ── Hydrate on module load ──
load_config()
load_allowlist()
_hydrate_metrics()
