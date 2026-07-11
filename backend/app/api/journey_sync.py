"""
NISCHINT Journey Sync API v5
Dual-layer escalation (guardian + authority), time-weighted area risk,
multi-pipe critical notifications (SSE + push + SMS fallback).

v5.1 — Mongo persistence + real Twilio SMS + FCM Push (behind delivery guard).
"""
import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import List, Optional, Dict

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api import journey_store as _store
from app.api import journey_delivery as _delivery
from app.api import journey_rollout as _rollout
from app.services import guardian_trust_service as _trust

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/journey", tags=["Journey Lifecycle"])

_journey_events: list = []
_sos_store: dict = {}
_geo_anomalies: list = []

SOS_STATES = ["idle", "triggered", "delivered", "acknowledged", "actioned", "resolved", "failed"]

# ═══════════════════════════════════════════════
# DUAL-LAYER ESCALATION: GUARDIAN + AUTHORITY
# ═══════════════════════════════════════════════

LAYER_GUARDIAN  = "guardian"   # humans: family, friends
LAYER_AUTHORITY = "authority"  # institutions: police, ambulance

_contacts: Dict[str, dict] = {}
_user_contacts: Dict[str, dict] = {}  # user_id -> {"guardian": [ids], "authority": [ids]}
_escalations: Dict[str, "EscalationEngine"] = {}

# Triggers for authority layer
AUTHORITY_TRIGGER_RISK   = "critical"
AUTHORITY_TRIGGER_NO_ACK = True  # escalate when no guardian acks


def _hydrate_from_mongo() -> None:
    """Load persisted state into in-memory dicts on module import."""
    try:
        c = _store.load_all_contacts()
        if c:
            _contacts.update(c)
        uc = _store.load_all_user_contacts()
        if uc:
            _user_contacts.update(uc)
        sos = _store.load_all_sos()
        if sos:
            _sos_store.update(sos)
        # Escalations must be hydrated AFTER contacts
        esc = _store.load_all_escalations()
        for sid, state in esc.items():
            try:
                _escalations[sid] = EscalationEngine.from_state_dict(state)
            except Exception as e:
                logger.error(f"[HYDRATE] escalation {sid} failed: {e}")
        if _store.is_enabled():
            logger.info(f"[JOURNEY_HYDRATE] contacts={len(_contacts)} user_contacts={len(_user_contacts)} sos={len(_sos_store)} escalations={len(_escalations)}")
    except Exception as e:
        logger.error(f"[JOURNEY_HYDRATE] failed: {e}")


class ContactProfile(BaseModel):
    name: str
    phone: str
    email: Optional[str] = None
    layer: str = "guardian"       # "guardian" or "authority"
    priority: int = 1
    escalation_delay_sec: int = 30
    relationship: str = "guardian"
    jurisdiction: Optional[str] = None  # for authority: city/district
    push_token: Optional[str] = None    # direct FCM token (for non-app guardians)
    user_id: Optional[str] = None       # link to existing User.id (fallback push target)


class ContactAssign(BaseModel):
    user_id: str
    guardian_ids: List[str] = []
    authority_ids: List[str] = []


class EscalationEngine:
    """Dual-layer escalation with authority verification gate."""
    def __init__(self, sos_id, guardians, authorities):
        self.sos_id = sos_id
        self.guardians = guardians
        self.authorities = authorities
        self.guardian_idx = 0
        self.authority_idx = 0
        self.active_layer = LAYER_GUARDIAN
        self.notified = {}
        self.started_at = time.time()
        self.authority_triggered = False
        self.authority_verified = False  # requires confirmation before full dispatch
        self.authority_pre_alerted = False
        self.notification_log = []

    def current_contact(self):
        if self.active_layer == LAYER_GUARDIAN:
            if self.guardian_idx < len(self.guardians):
                return self.guardians[self.guardian_idx]
            return None
        else:
            if self.authority_idx < len(self.authorities):
                return self.authorities[self.authority_idx]
            return None

    def mark_notified(self, cid, channel="webhook"):
        self.notified[cid] = {"notified_at": time.time(), "acked": False, "channel": channel}
        c = _contacts.get(cid, {})
        self.notification_log.append({
            "contact_id": cid, "name": c.get("name"), "layer": c.get("layer"),
            "channel": channel, "ts": time.time(),
        })

    def mark_acked(self, cid):
        if cid in self.notified:
            self.notified[cid]["acked"] = True

    def any_guardian_acked(self):
        for g in self.guardians:
            info = self.notified.get(g["id"])
            if info and info["acked"]:
                return True
        return False

    def should_escalate_guardian(self):
        c = self.current_contact()
        if not c or self.active_layer != LAYER_GUARDIAN:
            return False
        info = self.notified.get(c["id"])
        if not info:
            return True
        if info["acked"]:
            return False
        return (time.time() - info["notified_at"]) >= c.get("escalation_delay_sec", 30)

    def should_trigger_authority(self):
        """Authority triggers when: all guardians exhausted with no ACK, OR risk = critical."""
        if self.authority_triggered:
            return False
        if self.active_layer == LAYER_GUARDIAN and self.guardian_idx >= len(self.guardians) and not self.any_guardian_acked():
            return True
        return False

    def escalate(self):
        if self.active_layer == LAYER_GUARDIAN:
            self.guardian_idx += 1
            if self.guardian_idx >= len(self.guardians) and not self.any_guardian_acked():
                self.active_layer = LAYER_AUTHORITY
                self.authority_triggered = True
                logger.warning(f"[ESCALATION] SOS {self.sos_id}: No guardian ACK → escalating to AUTHORITY layer")
        else:
            self.authority_idx += 1
        return self.current_contact()

    def force_authority(self, reason="critical_risk"):
        """Pre-alert authority (not full dispatch). Requires verification to escalate."""
        if self.authority_pre_alerted:
            return
        self.authority_pre_alerted = True
        logger.warning(f"[ESCALATION] SOS {self.sos_id}: AUTHORITY PRE-ALERT ({reason}) — awaiting verification")

    def verify_authority(self, source="guardian_confirm"):
        """Verify and fully activate authority dispatch."""
        if self.authority_verified:
            return
        self.authority_verified = True
        self.authority_triggered = True
        self.active_layer = LAYER_AUTHORITY
        logger.warning(f"[ESCALATION] SOS {self.sos_id}: AUTHORITY VERIFIED ({source}) — dispatching")

    def auto_verify_check(self):
        """Auto-verify authority if: no guardian ACK after full chain + timeout, or user confirmed."""
        if self.authority_verified or not self.authority_pre_alerted:
            return False
        # All guardians exhausted with no ACK → auto-verify
        if self.guardian_idx >= len(self.guardians) and not self.any_guardian_acked():
            elapsed = time.time() - self.started_at
            if elapsed > 60:  # 60s minimum before auto-verify
                self.verify_authority("no_response_timeout")
                return True
        return False

    def to_dict(self):
        return {
            "sos_id": self.sos_id,
            "active_layer": self.active_layer,
            "authority_pre_alerted": self.authority_pre_alerted,
            "authority_verified": self.authority_verified,
            "authority_triggered": self.authority_triggered,
            "guardian_progress": f"{self.guardian_idx}/{len(self.guardians)}",
            "authority_progress": f"{self.authority_idx}/{len(self.authorities)}",
            "current_contact": self.current_contact(),
            "any_guardian_acked": self.any_guardian_acked(),
            "notified": {k: {**v, "name": _contacts.get(k, {}).get("name")} for k, v in self.notified.items()},
            "notification_log": self.notification_log[-10:],
            "elapsed_sec": round(time.time() - self.started_at, 1),
        }

    # ── Persistence snapshot ──
    def to_state_dict(self):
        return {
            "sos_id": self.sos_id,
            "guardian_ids": [g.get("id") for g in self.guardians],
            "authority_ids": [a.get("id") for a in self.authorities],
            "guardian_idx": self.guardian_idx,
            "authority_idx": self.authority_idx,
            "active_layer": self.active_layer,
            "notified": self.notified,
            "started_at": self.started_at,
            "authority_triggered": self.authority_triggered,
            "authority_verified": self.authority_verified,
            "authority_pre_alerted": self.authority_pre_alerted,
            "notification_log": self.notification_log[-30:],
        }

    @classmethod
    def from_state_dict(cls, d):
        guardians = [_contacts[gid] for gid in d.get("guardian_ids", []) if gid in _contacts]
        authorities = [_contacts[aid] for aid in d.get("authority_ids", []) if aid in _contacts]
        esc = cls(d["sos_id"], guardians, authorities)
        esc.guardian_idx = d.get("guardian_idx", 0)
        esc.authority_idx = d.get("authority_idx", 0)
        esc.active_layer = d.get("active_layer", LAYER_GUARDIAN)
        esc.notified = d.get("notified", {})
        esc.started_at = d.get("started_at", time.time())
        esc.authority_triggered = d.get("authority_triggered", False)
        esc.authority_verified = d.get("authority_verified", False)
        esc.authority_pre_alerted = d.get("authority_pre_alerted", False)
        esc.notification_log = d.get("notification_log", [])
        return esc


def _persist_escalation(esc: "EscalationEngine") -> None:
    try:
        _store.save_escalation(esc.sos_id, esc.to_state_dict())
    except Exception as e:
        logger.error(f"[PERSIST] escalation {esc.sos_id} failed: {e}")


# ═══════════════════════════════════════════════
# TIME-WEIGHTED AREA RISK
# ═══════════════════════════════════════════════

_user_baselines: Dict[str, dict] = {}
_risk_history: Dict[str, list] = {}  # session_id -> last N risk scores

# Area risk: (lat_bucket, lng_bucket) -> { base, night_multiplier }
AREA_RISK_ZONES = {
    (28.6, 77.2): {"base": 12, "night_mult": 2.0, "label": "Delhi Central"},
    (28.7, 77.1): {"base": 10, "night_mult": 1.8, "label": "Delhi West"},
    (28.5, 77.3): {"base": 15, "night_mult": 2.2, "label": "Delhi South-East"},
    (19.0, 72.8): {"base": 8,  "night_mult": 1.5, "label": "Mumbai South"},
    (19.1, 72.9): {"base": 10, "night_mult": 1.7, "label": "Mumbai Central"},
    (19.2, 72.8): {"base": 6,  "night_mult": 1.3, "label": "Mumbai Suburbs"},
    (12.9, 77.6): {"base": 7,  "night_mult": 1.4, "label": "Bangalore Central"},
    (13.0, 77.5): {"base": 5,  "night_mult": 1.2, "label": "Bangalore North"},
    (17.4, 78.5): {"base": 9,  "night_mult": 1.6, "label": "Hyderabad Central"},
    (13.1, 80.3): {"base": 8,  "night_mult": 1.5, "label": "Chennai Central"},
    (18.5, 73.9): {"base": 6,  "night_mult": 1.3, "label": "Pune"},
    (22.6, 88.4): {"base": 10, "night_mult": 1.8, "label": "Kolkata"},
}
DEFAULT_AREA = {"base": 3, "night_mult": 1.2, "label": "Unknown"}


def _get_time_weighted_area_risk(lat, lng):
    """Time-weighted area risk: base score × night multiplier during 22:00-05:00."""
    if lat is None or lng is None:
        return 0, "no_location", 1.0

    bucket = (round(lat, 1), round(lng, 1))
    zone = AREA_RISK_ZONES.get(bucket, DEFAULT_AREA)

    hour = datetime.now(timezone.utc).hour
    is_night = hour >= 22 or hour <= 5
    is_late_evening = 20 <= hour < 22
    is_early_morning = 5 < hour <= 7

    if is_night:
        mult = zone["night_mult"]
    elif is_late_evening or is_early_morning:
        mult = 1.0 + (zone["night_mult"] - 1.0) * 0.5  # half the night bonus
    else:
        mult = 1.0

    score = round(zone["base"] * mult)
    return min(score, 30), zone["label"], mult


# ═══════════════════════════════════════════════
# MULTI-PIPE NOTIFICATION ENGINE
# ═══════════════════════════════════════════════

_sos_subscribers: Dict[str, list] = {}
_notification_log: list = []


def _notify_sos_subscribers(sos_id, data):
    for q in _sos_subscribers.get(sos_id, []):
        try:
            q.put_nowait(data)
        except Exception:
            pass


def _send_critical_notification(sos_id, state, meta=None):
    """Intelligent multi-pipe routing: SSE always, Push conditionally, SMS only if no ACK.
    Real SMS/Push dispatch gated by JOURNEY_LIVE_DELIVERY flag + per-session rate limiter."""
    ts = datetime.now(timezone.utc).isoformat()
    notification = {"sos_id": sos_id, "state": state, "ts": ts, "meta": meta or {}, "pipes": []}

    # Pipe 1: SSE — ALWAYS (real-time, zero cost)
    _notify_sos_subscribers(sos_id, {"sos_state": state, "ts": ts, **(meta or {})})
    notification["pipes"].append("sse")

    sos = _sos_store.get(sos_id, {})
    session_id = sos.get("session_id")

    # Delivery Guard check (once per notification)
    can_deliver, deliver_reason = _delivery.can_deliver(session_id)
    notification["delivery_guard"] = {"allowed": can_deliver, "reason": deliver_reason, "live_flag": _delivery.is_live()}

    # Pipe 2: Push — for critical state changes only
    push_states = {"delivered", "authority_dispatched", "actioned", "failed"}
    if state in push_states:
        notification["push_status"] = "queued"
        notification["pipes"].append("push")
        logger.info(f"[NOTIFY] Push: SOS {sos_id} → {state}")

        # Real push dispatch — gather tokens from all assigned contacts (push_token field)
        contacts = _user_contacts.get(session_id, {})
        ids = contacts.get("guardian", []) + contacts.get("authority", [])
        push_tokens = []
        for cid in ids:
            c = _contacts.get(cid, {})
            if c.get("push_token"):
                push_tokens.append(c["push_token"])

        if push_tokens:
            if can_deliver:
                title = "NISCHINT Safety Alert"
                body = f"SOS {state.upper()} — tap for details"
                push_result = _delivery.send_push_real(sos_id, push_tokens, title, body, {"state": state, **(meta or {})})
                notification["push_result"] = push_result
            else:
                notification["push_result"] = {"status": "withheld", "reason": deliver_reason}

    # Pipe 3: SMS — ONLY if no ACK within window or user unreachable
    esc = _escalations.get(sos_id)
    should_sms = False

    if state == "failed":
        should_sms = True  # always SMS on failure
    elif state in ("delivered", "authority_dispatched"):
        # Check if any guardian has acked
        if esc and not esc.any_guardian_acked():
            elapsed = time.time() - esc.started_at
            if elapsed >= 20:  # 20s no-ACK window
                should_sms = True
        # Check if user is unreachable (offline + low battery)
        if sos.get("network") == "offline" or (sos.get("battery") is not None and sos.get("battery", 1) <= 0.10):
            should_sms = True

    if should_sms:
        contacts = _user_contacts.get(session_id, {})
        guardian_ids = contacts.get("guardian", [])
        sms_targets = []
        for gid in guardian_ids[:2]:
            g = _contacts.get(gid, {})
            if g.get("phone"):
                sms_targets.append({"phone": g["phone"], "name": g.get("name")})
        if sms_targets:
            notification["sms_targets"] = sms_targets
            notification["sms_status"] = "queued"
            notification["sms_reason"] = "no_ack_timeout" if (esc and not esc.any_guardian_acked()) else "user_unreachable"
            notification["pipes"].append("sms")
            logger.info(f"[NOTIFY] SMS: SOS {sos_id} → {[t['name'] for t in sms_targets]} (reason: {notification['sms_reason']})")

            # Real SMS dispatch
            if can_deliver:
                sms_results = []
                body = f"NISCHINT SOS alert — SOS {sos_id} state={state}. Tap: nischint.care/sos/{sos_id}"
                for t in sms_targets:
                    sms_results.append({**t, **_delivery.send_sms_real(sos_id, t["phone"], body)})
                notification["sms_results"] = sms_results
            else:
                notification["sms_results"] = [{"status": "withheld", "reason": deliver_reason}]
    else:
        notification["sms_status"] = "withheld"
        notification["sms_reason"] = "ack_received_or_within_window"

    _notification_log.append(notification)
    if len(_notification_log) > 500:
        del _notification_log[:-500]

    # ── Rollout metrics recording ──
    try:
        push_r = notification.get("push_result") or {}
        push_real = 1 if push_r.get("status") in ("sent", "dispatched") else 0
        push_sim = 1 if push_r.get("status") == "simulated" else 0
        sms_real = 0
        sms_sim = 0
        for s in notification.get("sms_results", []) or []:
            if s.get("status") in ("sent", "dispatched"):
                sms_real += 1
            elif s.get("status") == "simulated":
                sms_sim += 1
        if session_id and (push_real or push_sim or sms_real or sms_sim):
            _rollout.record_delivery(session_id, sms_real=sms_real, sms_sim=sms_sim,
                                     push_real=push_real, push_sim=push_sim)
        # Delivery Confidence on 'delivered' or terminal states
        if state in ("delivered", "authority_dispatched", "acknowledged", "resolved", "failed") and session_id:
            sms_success = bool(sms_real) or any(s.get("status") == "simulated" for s in notification.get("sms_results", []) or [])
            push_success = bool(push_real) or push_r.get("status") == "simulated"
            esc_obj = _escalations.get(sos_id)
            guardian_acked = bool(esc_obj and esc_obj.any_guardian_acked())
            confidence = _rollout.compute_confidence(sms_success, push_success, guardian_acked)
            notification["delivery_confidence"] = confidence
            _rollout.record_confidence(session_id, confidence)
            if sos_id in _sos_store:
                _sos_store[sos_id]["delivery_confidence"] = confidence
        # Release Escalation Lock on terminal states so next incident re-sorts fresh
        if state in ("resolved", "failed"):
            _trust.release_escalation_lock(sos_id)
            _trust.release_escalation_lock(f"{sos_id}:auth")
    except Exception as e:
        logger.error(f"[ROLLOUT_METRIC] recording failed: {e}")

    return notification


# ═══════════════════════════════════════════════
# PYDANTIC MODELS
# ═══════════════════════════════════════════════

class SyncEvent(BaseModel):
    id: str
    type: str
    payload: dict = {}
    createdAt: int
    attempts: int = 0
    priority: str = "normal"
    requiresAck: bool = False
    lastAttemptAt: Optional[int] = None
    status: Optional[str] = None


class SyncPayload(BaseModel):
    events: List[SyncEvent]


class SOSPayload(BaseModel):
    sosId: Optional[str] = None
    sosState: Optional[str] = None
    location: Optional[dict] = None
    geoTrail: Optional[list] = None
    ts: int
    riskScore: int = 0
    riskLevel: str = "safe"
    battery: Optional[float] = None
    isMoving: bool = False
    network: str = "online"
    sessionId: Optional[str] = None
    anomalies: Optional[list] = None
    idleSinceMs: Optional[int] = None


class SOSSmsPayload(BaseModel):
    sosId: str
    location: Optional[dict] = None
    sessionId: Optional[str] = None


class SOSStateUpdate(BaseModel):
    sos_state: str
    meta: dict = {}


class ContactAck(BaseModel):
    contact_id: str
    sos_id: str


class RiskContextPayload(BaseModel):
    session_id: str
    location: Optional[dict] = None
    idle_ms: int = 0
    is_moving: bool = False
    speed: float = 0
    battery: Optional[float] = None
    network: str = "online"
    anomaly_count: int = 0
    sos_active: bool = False


class UserBaseline(BaseModel):
    session_id: str
    usual_active_hours: List[int] = list(range(7, 22))
    usual_speed_kmh: float = 5.0
    usual_locations: List[dict] = []


# ═══════════════════════════════════════════════
# CONTACT CRUD (unified guardian + authority)
# ═══════════════════════════════════════════════

@router.post("/contacts")
def add_contact(profile: ContactProfile):
    if profile.layer not in (LAYER_GUARDIAN, LAYER_AUTHORITY):
        raise HTTPException(status_code=400, detail="Layer must be 'guardian' or 'authority'")
    cid = f"{'grd' if profile.layer == LAYER_GUARDIAN else 'auth'}_{int(time.time())}_{profile.phone[-4:]}"
    record = {**profile.dict(), "id": cid, "created_at": datetime.now(timezone.utc).isoformat()}
    _contacts[cid] = record
    _store.save_contact(cid, record)
    logger.info(f"[CONTACT] Added {profile.layer}: {cid} ({profile.name})")
    return {"status": "ok", "contact_id": cid, "contact": record}


@router.get("/contacts")
def list_contacts(layer: Optional[str] = None):
    contacts = list(_contacts.values())
    if layer:
        contacts = [c for c in contacts if c["layer"] == layer]
    return {"contacts": contacts, "count": len(contacts)}


@router.delete("/contacts/{contact_id}")
def remove_contact(contact_id: str):
    if contact_id not in _contacts:
        raise HTTPException(status_code=404, detail="Contact not found")
    removed = _contacts.pop(contact_id)
    _store.delete_contact(contact_id)
    return {"status": "ok", "removed": removed}


@router.post("/contacts/assign")
def assign_contacts(payload: ContactAssign):
    valid_g = [gid for gid in payload.guardian_ids if gid in _contacts and _contacts[gid]["layer"] == LAYER_GUARDIAN]
    valid_a = [aid for aid in payload.authority_ids if aid in _contacts and _contacts[aid]["layer"] == LAYER_AUTHORITY]
    sorted_g = sorted(valid_g, key=lambda x: _contacts[x].get("priority", 99))
    sorted_a = sorted(valid_a, key=lambda x: _contacts[x].get("priority", 99))
    mapping = {"guardian": sorted_g, "authority": sorted_a}
    _user_contacts[payload.user_id] = mapping
    _store.save_user_contacts(payload.user_id, mapping)
    return {"status": "ok", "user_id": payload.user_id, "guardians": sorted_g, "authorities": sorted_a}


@router.get("/contacts/for/{user_id}")
def get_user_contacts(user_id: str):
    mapping = _user_contacts.get(user_id, {"guardian": [], "authority": []})
    guardians = [_contacts[c] for c in mapping.get("guardian", []) if c in _contacts]
    authorities = [_contacts[c] for c in mapping.get("authority", []) if c in _contacts]
    return {"user_id": user_id, "guardians": guardians, "authorities": authorities}


# ═══════════════════════════════════════════════
# ESCALATION ENGINE
# ═══════════════════════════════════════════════

def _start_escalation(sos_id, session_id, risk_level="safe"):
    mapping = _user_contacts.get(session_id, {"guardian": [], "authority": []})
    guardians = [_contacts[c] for c in mapping.get("guardian", []) if c in _contacts]
    authorities = [_contacts[c] for c in mapping.get("authority", []) if c in _contacts]

    if not guardians and not authorities:
        # Fallback: all contacts sorted by priority
        all_g = sorted([c for c in _contacts.values() if c["layer"] == LAYER_GUARDIAN], key=lambda x: x.get("priority", 99))
        all_a = sorted([c for c in _contacts.values() if c["layer"] == LAYER_AUTHORITY], key=lambda x: x.get("priority", 99))
        guardians = all_g
        authorities = all_a

    if not guardians and not authorities:
        return None

    # ── Guardian Trust: risk-coupled weighted sort + Escalation Lock ──
    # CRITICAL SOS → trust dominates (0.8/0.2); lower risks respect configured priority more.
    # Applies time-decay + confidence damping inside the service.
    # Order is FROZEN per sos_id (Escalation Lock): prevents chaotic re-sorts mid-incident.
    _risk = (risk_level or "RED")
    guardians = _trust.sort_guardians_by_trust(guardians, risk_level=_risk, incident_id=sos_id)
    authorities = _trust.sort_guardians_by_trust(authorities, risk_level=_risk, incident_id=f"{sos_id}:auth")

    esc = EscalationEngine(sos_id, guardians, authorities)
    _escalations[sos_id] = esc

    # If risk is critical → PRE-ALERT authority (not full dispatch)
    if risk_level == AUTHORITY_TRIGGER_RISK:
        esc.force_authority("critical_risk_on_trigger")
        # DO NOT notify authority yet — just pre-alert status
        # Authority will be fully dispatched when:
        #   1. User confirms, OR
        #   2. Guardian confirms, OR
        #   3. No response timeout (60s)

    # Notify first guardian (always starts with guardian layer)
    if guardians:
        esc.active_layer = LAYER_GUARDIAN
        first = guardians[0]
        esc.mark_notified(first["id"], "webhook")
        _trust.record_alert_sent(first["id"])
        logger.warning(
            f"[ESCALATION] SOS {sos_id}: Guardian #1 {first['name']} "
            f"({first['phone']}) trust={_trust.get_trust_score(first['id'])}"
        )

    _persist_escalation(esc)
    return esc


@router.post("/contacts/ack")
def contact_ack(payload: ContactAck):
    ts = datetime.now(timezone.utc).isoformat()
    esc = _escalations.get(payload.sos_id)
    if not esc:
        raise HTTPException(status_code=404, detail="No escalation found")

    esc.mark_acked(payload.contact_id)
    contact = _contacts.get(payload.contact_id, {})

    sos = _sos_store.get(payload.sos_id)
    if sos:
        sos["sos_state"] = "acknowledged"
        sos["state_history"].append({
            "state": "acknowledged", "ts": ts, "source": contact.get("layer", "guardian"),
            "contact_id": payload.contact_id, "contact_name": contact.get("name"),
        })
        _store.save_sos(payload.sos_id, sos)
        # Rollout ACK latency metric + Guardian Trust score update
        try:
            ack_latency_ms = int((time.time() - esc.started_at) * 1000)
            sid = sos.get("session_id")
            if sid:
                _rollout.record_ack(sid, ack_latency_ms)
            # Record ACK against the guardian's trust score (only guardians, not authorities)
            if contact.get("layer") == LAYER_GUARDIAN:
                _trust.record_ack(payload.contact_id, ack_latency_ms)
        except Exception as e:
            logger.error(f"[ROLLOUT_METRIC] ack latency failed: {e}")
        _send_critical_notification(payload.sos_id, "acknowledged", {"by": contact.get("name"), "layer": contact.get("layer")})

    _persist_escalation(esc)
    return {"status": "ok", "acked_by": contact.get("name"), "layer": contact.get("layer"), "escalation": esc.to_dict()}


@router.get("/escalation/{sos_id}")
def get_escalation(sos_id: str):
    esc = _escalations.get(sos_id)
    if not esc:
        raise HTTPException(status_code=404, detail="No escalation found")

    # Auto-escalate guardian chain if needed
    if esc.active_layer == LAYER_GUARDIAN and esc.should_escalate_guardian():
        # Record "missed" trust penalty for the previous guardian who didn't ACK
        try:
            prev_contact = esc.current_contact()
            if prev_contact and prev_contact.get("id") not in esc.notified and False:
                pass  # placeholder
            if prev_contact and not esc.any_guardian_acked():
                _trust.record_missed(prev_contact["id"])
        except Exception as e:
            logger.error(f"[GUARDIAN_TRUST] missed hook failed: {e}")

        next_c = esc.escalate()
        if next_c:
            esc.mark_notified(next_c["id"], "webhook")
            _trust.record_alert_sent(next_c["id"])
            logger.warning(
                f"[ESCALATION] SOS {sos_id}: Guardian → {next_c['name']} "
                f"trust={_trust.get_trust_score(next_c['id'])}"
            )
        elif esc.should_trigger_authority():
            esc.force_authority("no_guardian_ack")

    # Auto-verify authority if timeout reached
    if esc.auto_verify_check():
        auth = esc.current_contact()
        if auth:
            esc.mark_notified(auth["id"], "authority_dispatch")
            _send_critical_notification(sos_id, "authority_dispatched", {"authority": auth.get("name"), "verified": True})

    _persist_escalation(esc)
    return {"escalation": esc.to_dict()}


@router.post("/escalation/{sos_id}/verify")
def verify_authority_dispatch(sos_id: str, source: str = "user_confirm"):
    """Explicitly verify authority dispatch — called by user or guardian confirmation."""
    esc = _escalations.get(sos_id)
    if not esc:
        raise HTTPException(status_code=404, detail="No escalation found")
    if not esc.authority_pre_alerted:
        raise HTTPException(status_code=400, detail="Authority not pre-alerted for this SOS")
    if esc.authority_verified:
        return {"status": "already_verified", "escalation": esc.to_dict()}

    esc.verify_authority(source)
    # Now dispatch to first authority
    auth = esc.current_contact()
    if auth:
        esc.mark_notified(auth["id"], "verified_authority_dispatch")
        _send_critical_notification(sos_id, "authority_dispatched", {"authority": auth.get("name"), "verified_by": source})

    # Update SOS state
    sos = _sos_store.get(sos_id)
    if sos:
        ts = datetime.now(timezone.utc).isoformat()
        sos["state_history"].append({"state": "authority_verified", "ts": ts, "source": source})
        _store.save_sos(sos_id, sos)

    _persist_escalation(esc)
    logger.warning(f"[ESCALATION] SOS {sos_id}: Authority VERIFIED by {source}")
    return {"status": "verified", "authority": auth, "escalation": esc.to_dict()}


# ═══════════════════════════════════════════════
# CONTEXT-AWARE RISK (TIME-WEIGHTED)
# ═══════════════════════════════════════════════

@router.post("/risk/baseline")
def set_baseline(payload: UserBaseline):
    _user_baselines[payload.session_id] = payload.dict()
    return {"status": "ok", "session_id": payload.session_id}


@router.post("/risk/score")
def compute_contextual_risk(payload: RiskContextPayload):
    score = 0
    factors = []

    # 1. Idle
    if payload.idle_ms > 15 * 60 * 1000:
        score += 40; factors.append(("idle_critical", 40))
    elif payload.idle_ms > 5 * 60 * 1000:
        score += 20; factors.append(("idle_high", 20))
    elif payload.idle_ms > 2.5 * 60 * 1000:
        score += 10; factors.append(("idle_medium", 10))

    # 2. Anomalies
    a = min(payload.anomaly_count * 15, 30)
    if a > 0:
        score += a; factors.append(("anomalies", a))

    # 3. Speed drop
    if not payload.is_moving and payload.speed > 5:
        score += 25; factors.append(("speed_drop", 25))

    # 4. Time of day (handled more granularly in area risk)
    hour = datetime.now(timezone.utc).hour
    if hour >= 22 or hour <= 5:
        score += 15; factors.append(("late_night", 15))
    elif 20 <= hour < 22 or 5 < hour <= 7:
        score += 7; factors.append(("evening_morning", 7))

    # 5. Battery
    if payload.battery is not None:
        if payload.battery <= 0.05:
            score += 15; factors.append(("battery_critical", 15))
        elif payload.battery <= 0.10:
            score += 10; factors.append(("battery_low", 10))
        elif payload.battery <= 0.15:
            score += 5; factors.append(("battery_warning", 5))

    # 6. Network
    if payload.network == "offline":
        score += 15; factors.append(("offline", 15))

    # 7. Active SOS
    if payload.sos_active:
        score += 20; factors.append(("sos_active", 20))

    # 8. TIME-WEIGHTED AREA RISK
    area_score = 0
    area_label = "no_location"
    area_mult = 1.0
    if payload.location:
        area_score, area_label, area_mult = _get_time_weighted_area_risk(
            payload.location.get("lat"), payload.location.get("lng"))
        if area_score > 0:
            score += area_score; factors.append(("area_risk", area_score, area_label, f"{area_mult}x"))

    # 9. Baseline deviation
    baseline = _user_baselines.get(payload.session_id)
    if baseline:
        if hour not in baseline.get("usual_active_hours", list(range(7, 22))):
            score += 10; factors.append(("outside_usual_hours", 10))
        usual_speed = baseline.get("usual_speed_kmh", 5.0)
        if payload.speed > usual_speed * 3 and payload.speed > 0:
            score += 10; factors.append(("speed_above_baseline", 10))

    score = min(score, 100)

    # ── STABILITY CONTROL ──
    history = _risk_history.setdefault(payload.session_id, [])
    history.append({"score": score, "ts": time.time()})
    if len(history) > 10:
        del history[:-10]

    recent_scores = [h["score"] for h in history]
    momentum = round(sum(recent_scores[-3:]) / min(len(recent_scores), 3), 1) if recent_scores else score
    volatility = 0.0
    if len(recent_scores) >= 2:
        mean = sum(recent_scores[-5:]) / min(len(recent_scores), 5)
        volatility = round((sum((s - mean) ** 2 for s in recent_scores[-5:]) / min(len(recent_scores), 5)) ** 0.5, 1)

    # Dampen: only escalate if momentum is also high (prevents spike-based false alarms)
    effective_score = score
    if score >= 61 and momentum < 50:
        effective_score = min(score, 60)  # cap at caution if momentum is low
        factors.append(("stability_dampened", -(score - effective_score)))
    if score >= 81 and volatility > 25:
        effective_score = min(effective_score, 75)  # cap below critical if volatile
        factors.append(("volatility_dampened", -(score - effective_score)))

    effective_score = min(effective_score, 100)
    level = "critical" if effective_score >= 81 else "high" if effective_score >= 61 else "caution" if effective_score >= 31 else "safe"

    actions = []
    if level == "caution":
        actions.append({"type": "ui_alert", "message": "NISCHINT is monitoring your safety"})
    if level == "high":
        actions.append({"type": "push_notification", "message": "Are you safe? Tap to confirm."})
        actions.append({"type": "guardian_ping", "message": "Pre-alert: User may need help"})
    if level == "critical":
        actions.append({"type": "auto_pre_sos", "message": "Initiating safety check..."})
        actions.append({"type": "guardian_alert", "message": "URGENT: User safety at risk"})
        actions.append({"type": "authority_pre_alert", "message": "Emergency services on standby"})
        actions.append({"type": "sms_fallback", "message": "SMS SOS queued to guardians"})

    return {
        "risk_score": score, "effective_score": effective_score, "risk_level": level,
        "momentum": momentum, "volatility": volatility,
        "factors": factors, "actions": actions,
        "area_risk": {"score": area_score, "zone": area_label, "time_multiplier": area_mult},
        "baseline_active": payload.session_id in _user_baselines,
        "stability": {"dampened": effective_score < score, "raw_score": score, "effective_score": effective_score},
    }


# ═══════════════════════════════════════════════
# BATCH SYNC
# ═══════════════════════════════════════════════

@router.post("/sync")
def sync_events(payload: SyncPayload):
    ts = datetime.now(timezone.utc).isoformat()
    sos_count = 0
    for event in payload.events:
        _journey_events.append({
            "id": event.id, "type": event.type, "payload": event.payload,
            "priority": event.priority, "client_ts": event.createdAt, "received_at": ts,
        })
        if event.type == "sos":
            sos_count += 1
    if len(_journey_events) > 2000:
        del _journey_events[:-2000]
    return {"status": "ok", "received": len(payload.events), "sos_count": sos_count, "sos_acked": sos_count > 0}


# ═══════════════════════════════════════════════
# SOS ENDPOINTS
# ═══════════════════════════════════════════════

@router.post("/sos")
def receive_sos(payload: SOSPayload):
    ts = datetime.now(timezone.utc).isoformat()
    sos_id = payload.sosId or f"sos_{int(payload.ts)}"

    sos_record = {
        "sos_id": sos_id, "sos_state": "delivered",
        "state_history": [
            {"state": "triggered", "ts": payload.ts, "source": "client"},
            {"state": "delivered", "ts": ts, "source": "api"},
        ],
        "location": payload.location, "geo_trail": payload.geoTrail or [],
        "risk_score": payload.riskScore, "risk_level": payload.riskLevel,
        "battery": payload.battery, "is_moving": payload.isMoving, "network": payload.network,
        "session_id": payload.sessionId, "anomalies": payload.anomalies or [],
        "received_at": ts, "channels_delivered": ["api"],
    }

    _sos_store[sos_id] = sos_record
    _store.save_sos(sos_id, sos_record)
    _journey_events.append({"id": sos_id, "type": "sos", "priority": "high", "received_at": ts})

    # Rollout: record SOS for this session
    _rollout.record_sos(payload.sessionId or "default")

    esc = _start_escalation(sos_id, payload.sessionId or "default", payload.riskLevel)
    _send_critical_notification(sos_id, "delivered", {"risk": payload.riskLevel})

    logger.warning(f"[SOS] DELIVERED: {sos_id} | risk={payload.riskLevel}({payload.riskScore}) | escalation={'pre-alert' if esc and esc.authority_pre_alerted else 'guardian' if esc else 'none'}")

    return {
        "status": "ok", "acked": True, "sos_id": sos_id, "sos_state": "delivered",
        "received_at": ts, "escalation_started": esc is not None,
        "authority_pre_alerted": esc.authority_pre_alerted if esc else False,
        "authority_verified": False,
    }


@router.post("/sos-sms")
def sos_sms_fallback(payload: SOSSmsPayload):
    ts = datetime.now(timezone.utc).isoformat()
    sos = _sos_store.get(payload.sosId)
    if sos:
        sos["channels_delivered"].append("sms")
        sos["state_history"].append({"state": "sms_queued", "ts": ts, "source": "sms_fallback"})
        _store.save_sos(payload.sosId, sos)
    _send_critical_notification(payload.sosId, "sms_queued")
    return {"status": "ok", "channel": "sms", "sos_id": payload.sosId, "sms_status": "queued"}


@router.post("/sos-webhook")
def sos_webhook(payload: SOSPayload):
    ts = datetime.now(timezone.utc).isoformat()
    sos_id = payload.sosId or f"sos_{int(payload.ts)}"
    sos = _sos_store.get(sos_id)
    if sos:
        sos["channels_delivered"].append("webhook")
        sos["state_history"].append({"state": "guardian_notified", "ts": ts, "source": "webhook"})
        _store.save_sos(sos_id, sos)
    return {"status": "ok", "channel": "webhook", "sos_id": sos_id}


@router.get("/sos/{sos_id}")
def get_sos_state(sos_id: str):
    sos = _sos_store.get(sos_id)
    if not sos:
        raise HTTPException(status_code=404, detail="SOS not found")
    esc = _escalations.get(sos_id)
    return {
        "sos_id": sos_id, "sos_state": sos["sos_state"],
        "state_history": sos["state_history"],
        "channels_delivered": sos["channels_delivered"],
        "location": sos["location"], "risk_score": sos["risk_score"], "risk_level": sos["risk_level"],
        "escalation": esc.to_dict() if esc else None,
    }


@router.put("/sos/{sos_id}")
def update_sos_state(sos_id: str, payload: SOSStateUpdate):
    sos = _sos_store.get(sos_id)
    if not sos:
        raise HTTPException(status_code=404, detail="SOS not found")
    if payload.sos_state not in SOS_STATES:
        raise HTTPException(status_code=400, detail=f"Invalid state")
    ts = datetime.now(timezone.utc).isoformat()
    sos["sos_state"] = payload.sos_state
    sos["state_history"].append({"state": payload.sos_state, "ts": ts, "source": "operator", **payload.meta})
    _store.save_sos(sos_id, sos)
    _send_critical_notification(sos_id, payload.sos_state, payload.meta)
    return {"status": "ok", "sos_id": sos_id, "sos_state": payload.sos_state}


# ── SSE Stream ──

@router.get("/sos/{sos_id}/stream")
async def sos_stream(sos_id: str):
    if sos_id not in _sos_store:
        raise HTTPException(status_code=404, detail="SOS not found")
    queue = asyncio.Queue()
    _sos_subscribers.setdefault(sos_id, []).append(queue)

    async def gen():
        try:
            sos = _sos_store.get(sos_id, {})
            yield f"data: {json.dumps({'sos_state': sos.get('sos_state'), 'ts': datetime.now(timezone.utc).isoformat()})}\n\n"
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"data: {json.dumps(data)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    sos = _sos_store.get(sos_id, {})
                    if sos.get("sos_state") in ("resolved", "failed"):
                        yield f"data: {json.dumps({'sos_state': sos['sos_state'], 'stream': 'closing'})}\n\n"
                        break
        finally:
            subs = _sos_subscribers.get(sos_id, [])
            if queue in subs:
                subs.remove(queue)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Notifications log ──

@router.get("/notifications")
def get_notifications(limit: int = 30):
    return {"notifications": _notification_log[-limit:], "count": len(_notification_log)}


# ── Query endpoints ──

@router.get("/events")
def get_events(type: Optional[str] = None, limit: int = 50):
    events = _journey_events
    if type:
        events = [e for e in events if e.get("type") == type]
    return {"events": events[-limit:], "count": len(events)}


@router.get("/sos")
def get_sos_list(limit: int = 20):
    all_sos = sorted(_sos_store.values(), key=lambda x: x.get("received_at", ""), reverse=True)
    return {
        "sos_events": all_sos[:limit], "count": len(_sos_store),
        "active": sum(1 for s in _sos_store.values() if s["sos_state"] not in ("resolved", "idle")),
    }


@router.get("/anomalies")
def get_anomalies(limit: int = 30):
    return {"anomalies": _geo_anomalies[-limit:], "count": len(_geo_anomalies)}


@router.get("/guardians/trust")
def list_guardian_trust():
    """Ranked list of guardians by trust score — drives escalation priority."""
    items = sorted(_trust.list_all(), key=lambda r: -r.get("trust_score", 0))
    return {"guardians": items, "count": len(items)}


@router.get("/guardians/trust/{contact_id}")
def get_guardian_trust(contact_id: str):
    """Per-guardian trust diagnostic."""
    return _trust.get_stats(contact_id)


@router.get("/stats")
def get_journey_stats():
    types = {}
    for e in _journey_events:
        types[e.get("type", "unknown")] = types.get(e.get("type", "unknown"), 0) + 1
    return {
        "total_events": len(_journey_events),
        "total_sos": len(_sos_store),
        "active_sos": sum(1 for s in _sos_store.values() if s["sos_state"] not in ("resolved", "idle")),
        "total_contacts": len(_contacts),
        "guardians": sum(1 for c in _contacts.values() if c["layer"] == LAYER_GUARDIAN),
        "authorities": sum(1 for c in _contacts.values() if c["layer"] == LAYER_AUTHORITY),
        "active_escalations": len([e for e in _escalations.values() if not e.any_guardian_acked()]),
        "user_baselines": len(_user_baselines),
        "notifications_sent": len(_notification_log),
        "by_type": types,
        "persistence": {"mongo_enabled": _store.is_enabled()},
        "delivery": _delivery.delivery_status(),
    }


@router.get("/delivery/status")
def get_delivery_status():
    """Exposes the delivery guard config + live state for admin/dashboard."""
    return {
        "delivery": _delivery.delivery_status(),
        "persistence": {"mongo_enabled": _store.is_enabled()},
    }


# ── Hydrate from Mongo on module load ──
_hydrate_from_mongo()
