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
import threading
from typing import Any, Dict, List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

_client = None
_db = None
_enabled = False

# Mongo is optional for this store. Remember the initialization result for the
# lifetime of the process so an unavailable Mongo server cannot add a blocking
# connection timeout to every request.
_init_attempted = False
_init_lock = threading.Lock()

COL_CONTACTS = "journey_contacts"
COL_USER_CONTACTS = "journey_user_contacts"
COL_SOS = "journey_sos_events"
COL_ESCALATIONS = "journey_escalations"


def _init() -> None:
    """
    Initialize the optional pymongo store at most once per process.

    If Mongo is unavailable, keep the existing in-memory fallback for the
    lifetime of this process instead of retrying a blocking connection on
    every request. A new deployment/process gets a fresh initialization
    attempt automatically.
    """
    global _client, _db, _enabled, _init_attempted

    # Fast path after either a successful initialization or a previous
    # connection failure.
    if _init_attempted or not settings.journey_mongo_enabled:
        return

    # Do not make concurrent request threads wait behind Mongo discovery.
    # One caller performs initialization; others immediately continue using
    # the existing in-memory fallback until initialization completes.
    if not _init_lock.acquire(blocking=False):
        return

    candidate = None

    try:
        # Re-check after obtaining the initialization slot.
        if _init_attempted or not settings.journey_mongo_enabled:
            return

        # Mark before any network operation so concurrent callers do not start
        # their own Mongo connection attempts.
        _init_attempted = True

        from pymongo import MongoClient

        candidate = MongoClient(
            settings.mongo_url,
            serverSelectionTimeoutMS=3000,
        )

        candidate.admin.command("ping")

        db = candidate[settings.db_name]

        # Preserve all existing indexes and persistence behaviour.
        db[COL_CONTACTS].create_index("layer")
        db[COL_SOS].create_index("received_at")
        db[COL_ESCALATIONS].create_index("updated_at")

        _client = candidate
        _db = db
        _enabled = True

        logger.info(
            f"[JOURNEY_STORE] MongoDB connected: db={settings.db_name}"
        )

    except Exception as e:
        # Dispose of a partially-created client cleanly.
        if candidate is not None:
            try:
                candidate.close()
            except Exception:
                pass

        _client = None
        _db = None
        _enabled = False

        # This warning now occurs once per process rather than once per caller.
        logger.warning(
            f"[JOURNEY_STORE] Mongo unavailable, "
            f"using in-memory only: {e}"
        )

    finally:
        _init_lock.release()


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
