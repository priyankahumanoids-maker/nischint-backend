"""
NISCHINT Journey Engine — Persistence Layer (MongoDB)

Collections:
    journey_contacts        — {_id=contact_id, name, phone, email, layer, priority, ...}
    journey_user_contacts   — {_id=user_id/session_id, guardian: [cid], authority: [cid]}
    journey_sos_events      — {_id=sos_id, sos_state, state_history, location, ...}
    journey_escalations     — {_id=sos_id, state snapshot of EscalationEngine}

Usage:
    Synchronous pymongo client (matches sync FastAPI handlers in journey_sync.py).
    Silent fallback to in-memory-only mode if Mongo connection fails or flag disabled.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

_client = None
_db = None
_enabled = False

COL_CONTACTS = "journey_contacts"
COL_USER_CONTACTS = "journey_user_contacts"
COL_SOS = "journey_sos_events"
COL_ESCALATIONS = "journey_escalations"


def _init() -> None:
    """Initialize pymongo client once. Falls back silently on failure."""
    global _client, _db, _enabled
    if _client is not None or not settings.journey_mongo_enabled:
        return
    try:
        from pymongo import MongoClient
        _client = MongoClient(settings.mongo_url, serverSelectionTimeoutMS=3000)
        _client.admin.command("ping")
        _db = _client[settings.db_name]
        _enabled = True
        # Indexes
        _db[COL_CONTACTS].create_index("layer")
        _db[COL_SOS].create_index("received_at")
        _db[COL_ESCALATIONS].create_index("updated_at")
        logger.info(f"[JOURNEY_STORE] MongoDB connected: db={settings.db_name}")
    except Exception as e:
        logger.warning(f"[JOURNEY_STORE] Mongo unavailable, using in-memory only: {e}")
        _client = None
        _db = None
        _enabled = False


def is_enabled() -> bool:
    _init()
    return _enabled


def _safe(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Strip Mongo _id when document came from DB with a non-string _id."""
    if not doc:
        return doc
    doc.pop("_id", None)
    return doc


# ── CONTACTS ──

def save_contact(cid: str, record: Dict[str, Any]) -> None:
    _init()
    if not _enabled:
        return
    try:
        _db[COL_CONTACTS].update_one({"_id": cid}, {"$set": {**record, "_id": cid}}, upsert=True)
    except Exception as e:
        logger.error(f"[JOURNEY_STORE] save_contact({cid}) failed: {e}")


def delete_contact(cid: str) -> None:
    _init()
    if not _enabled:
        return
    try:
        _db[COL_CONTACTS].delete_one({"_id": cid})
    except Exception as e:
        logger.error(f"[JOURNEY_STORE] delete_contact({cid}) failed: {e}")


def load_all_contacts() -> Dict[str, Dict[str, Any]]:
    _init()
    if not _enabled:
        return {}
    try:
        out: Dict[str, Dict[str, Any]] = {}
        for doc in _db[COL_CONTACTS].find():
            cid = doc.get("_id")
            if cid:
                doc.pop("_id", None)
                doc["id"] = cid
                out[cid] = doc
        return out
    except Exception as e:
        logger.error(f"[JOURNEY_STORE] load_all_contacts failed: {e}")
        return {}


# ── USER CONTACTS ──

def save_user_contacts(user_id: str, mapping: Dict[str, List[str]]) -> None:
    _init()
    if not _enabled:
        return
    try:
        _db[COL_USER_CONTACTS].update_one(
            {"_id": user_id},
            {"$set": {"_id": user_id, "guardian": mapping.get("guardian", []), "authority": mapping.get("authority", [])}},
            upsert=True,
        )
    except Exception as e:
        logger.error(f"[JOURNEY_STORE] save_user_contacts({user_id}) failed: {e}")


def load_all_user_contacts() -> Dict[str, Dict[str, List[str]]]:
    _init()
    if not _enabled:
        return {}
    try:
        out: Dict[str, Dict[str, List[str]]] = {}
        for doc in _db[COL_USER_CONTACTS].find():
            uid = doc.get("_id")
            if uid:
                out[uid] = {
                    "guardian": doc.get("guardian", []),
                    "authority": doc.get("authority", []),
                }
        return out
    except Exception as e:
        logger.error(f"[JOURNEY_STORE] load_all_user_contacts failed: {e}")
        return {}


# ── SOS EVENTS ──

def save_sos(sos_id: str, record: Dict[str, Any]) -> None:
    _init()
    if not _enabled:
        return
    try:
        _db[COL_SOS].update_one({"_id": sos_id}, {"$set": {**record, "_id": sos_id}}, upsert=True)
    except Exception as e:
        logger.error(f"[JOURNEY_STORE] save_sos({sos_id}) failed: {e}")


def load_all_sos() -> Dict[str, Dict[str, Any]]:
    _init()
    if not _enabled:
        return {}
    try:
        out: Dict[str, Dict[str, Any]] = {}
        # Load last 500 to keep memory bounded
        for doc in _db[COL_SOS].find().sort("received_at", -1).limit(500):
            sid = doc.get("_id")
            if sid:
                doc.pop("_id", None)
                out[sid] = doc
        return out
    except Exception as e:
        logger.error(f"[JOURNEY_STORE] load_all_sos failed: {e}")
        return {}


# ── ESCALATIONS ──

def save_escalation(sos_id: str, state_dict: Dict[str, Any]) -> None:
    _init()
    if not _enabled:
        return
    try:
        import time as _t
        _db[COL_ESCALATIONS].update_one(
            {"_id": sos_id},
            {"$set": {**state_dict, "_id": sos_id, "updated_at": _t.time()}},
            upsert=True,
        )
    except Exception as e:
        logger.error(f"[JOURNEY_STORE] save_escalation({sos_id}) failed: {e}")


def load_all_escalations() -> Dict[str, Dict[str, Any]]:
    _init()
    if not _enabled:
        return {}
    try:
        out: Dict[str, Dict[str, Any]] = {}
        # Only reload active (not resolved/failed) from last 7 days
        import time as _t
        cutoff = _t.time() - 7 * 24 * 3600
        for doc in _db[COL_ESCALATIONS].find({"updated_at": {"$gte": cutoff}}):
            sid = doc.get("_id")
            if sid:
                doc.pop("_id", None)
                out[sid] = doc
        return out
    except Exception as e:
        logger.error(f"[JOURNEY_STORE] load_all_escalations failed: {e}")
        return {}
