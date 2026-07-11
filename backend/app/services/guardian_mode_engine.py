# Guardian Mode Engine
# Manages guardian networks, live sharing sessions, and alert dispatching.
# Persists to PostgreSQL via SQLAlchemy models.

import logging
import math
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guardian import Guardian, GuardianSession, GuardianAlert, JourneyPoint
from app.models.user import User
from app.services.safe_zone_engine import check_zone, _haversine

logger = logging.getLogger(__name__)


async def _broadcast_journey_event(gs: GuardianSession,
                                    event_type: str, payload: dict) -> None:
    """Best-effort SSE broadcast for journey lifecycle transitions.
    All events carry session_id + seq so clients can detect dropped
    sequences. Targets the affected session's channel and the operator
    role channel."""
    try:
        from app.services.event_broadcaster import broadcaster
        try:
            await broadcaster.broadcast(f"session:{gs.id}", event_type, payload)
        except Exception:
            pass
        try:
            await broadcaster.broadcast_to_role("operator", event_type, payload)
        except Exception:
            pass
        logger.info(
            f"[journey] {event_type} session={gs.id} "
            f"seq={payload.get('seq')} gap_s={payload.get('gap_seconds')}"
        )
    except Exception as e:
        logger.debug(f"[journey] WS emit suppressed: {e}")


IDLE_SPEED_THRESHOLD = 0.5
IDLE_DURATION_THRESHOLD_S = 120
ROUTE_DEVIATION_THRESHOLD_M = 120

ESC_ORDER = {"none": 0, "user": 1, "guardian": 2, "emergency": 3}
RISK_ESC_MAP = {"SAFE": "none", "LOW": "none", "HIGH": "user", "CRITICAL": "guardian"}
RISK_ORDER = {"SAFE": 0, "LOW": 1, "HIGH": 2, "CRITICAL": 3}

# ── In-memory state for real-time tracking (supplements DB) ──
_live_state: dict[str, dict] = {}


# ── Guardian CRUD ──

async def add_guardian(session: AsyncSession, user_id: str, name: str, phone: str | None, email: str | None, relationship: str) -> dict:
    g = Guardian(
        user_id=uuid.UUID(user_id), name=name, phone=phone, email=email,
        relationship=relationship,
    )
    session.add(g)
    await session.flush()
    return _guardian_to_dict(g)


async def list_guardians(session: AsyncSession, user_id: str) -> list[dict]:
    result = await session.execute(
        select(Guardian).where(Guardian.user_id == uuid.UUID(user_id), Guardian.is_active == True)  # noqa: E712
    )
    return [_guardian_to_dict(g) for g in result.scalars().all()]


async def remove_guardian(session: AsyncSession, guardian_id: str) -> dict:
    result = await session.execute(select(Guardian).where(Guardian.id == uuid.UUID(guardian_id)))
    g = result.scalar_one_or_none()
    if not g:
        return {"error": "Guardian not found"}
    g.is_active = False
    await session.flush()
    return {"removed": True, "guardian_id": guardian_id}


def _guardian_to_dict(g: Guardian) -> dict:
    return {
        "id": str(g.id), "user_id": str(g.user_id), "name": g.name,
        "phone": g.phone, "email": g.email, "relationship": g.relationship,
        "notification_pref": g.notification_pref, "is_active": g.is_active,
        "created_at": g.created_at.isoformat() if g.created_at else None,
    }


# ── Session Management ──

async def start_session(
    session: AsyncSession, user_id: str, lat: float, lng: float,
    dest_lat: float | None = None, dest_lng: float | None = None,
) -> dict:
    now = datetime.now(timezone.utc)
    zone = await check_zone(session, user_id, lat, lng, now)

    gs = GuardianSession(
        user_id=uuid.UUID(user_id), status="active",
        destination={"lat": dest_lat, "lng": dest_lng} if dest_lat else None,
        current_location={"lat": lat, "lng": lng},
        risk_level=zone["risk_level"], risk_score=zone["risk_score"],
        zone_name=zone["zone_name"],
        is_night=(now.hour >= 22 or now.hour < 5),
    )
    session.add(gs)
    await session.flush()

    # Init live state
    _live_state[str(gs.id)] = {
        "prev_location": {"lat": lat, "lng": lng},
        "prev_update_at": now, "idle_since": None, "safety_check_pending": False,
        "safety_check_sent_at": None, "route_points": [],
    }

    # Count guardians notified
    guardians = await list_guardians(session, user_id)

    # Invalidate active sessions cache
    from app.services.redis_service import delete_key
    delete_key("sessions", "active")

    logger.info(f"SESSION_START user={user_id} session={gs.id} zone={zone['risk_level']}")

    return {
        "session_id": str(gs.id), "status": "active", "user_id": user_id,
        "started_at": now.isoformat(), "initial_zone": {
            "risk_level": zone["risk_level"], "risk_score": zone["risk_score"],
            "zone_name": zone["zone_name"],
        },
        "destination": gs.destination, "guardians_notified": len(guardians),
        "is_night": gs.is_night,
    }


async def stop_session(session: AsyncSession, session_id: str) -> dict:
    result = await session.execute(select(GuardianSession).where(GuardianSession.id == uuid.UUID(session_id)))
    gs = result.scalar_one_or_none()
    if not gs:
        return {"error": "Session not found"}

    now = datetime.now(timezone.utc)
    gs.status = "ended"
    gs.ended_at = now
    await session.flush()
    _live_state.pop(session_id, None)

    # Invalidate active sessions cache
    from app.services.redis_service import delete_key
    delete_key("sessions", "active")

    duration = round((now - gs.started_at).total_seconds() / 60, 1)
    alert_count = await _count_alerts(session, session_id)

    logger.info(f"SESSION_END session={session_id} duration={duration}min alerts={alert_count}")

    return {
        "session_id": session_id, "status": "ended",
        "duration_minutes": duration, "total_distance_m": round(gs.total_distance_m, 1),
        "location_updates": gs.location_updates, "alerts_triggered": alert_count,
        "final_zone": {"risk_level": gs.risk_level, "risk_score": gs.risk_score, "zone_name": gs.zone_name},
    }


async def get_session(session: AsyncSession, session_id: str) -> dict | None:
    result = await session.execute(select(GuardianSession).where(GuardianSession.id == uuid.UUID(session_id)))
    gs = result.scalar_one_or_none()
    if not gs:
        return None

    now = datetime.now(timezone.utc)
    duration = round((now - gs.started_at).total_seconds() / 60, 1)
    alerts = await _get_session_alerts(session, session_id, limit=10)
    live = _live_state.get(session_id, {})

    return {
        "session_id": str(gs.id), "user_id": str(gs.user_id), "status": gs.status,
        "started_at": gs.started_at.isoformat(), "duration_minutes": duration,
        "current_location": gs.current_location, "destination": gs.destination,
        "risk_level": gs.risk_level, "risk_score": gs.risk_score,
        "zone_name": gs.zone_name, "eta_minutes": gs.eta_minutes,
        "speed_mps": round(gs.speed_mps, 2), "total_distance_m": round(gs.total_distance_m, 1),
        "location_updates": gs.location_updates, "escalation_level": gs.escalation_level,
        "is_night": gs.is_night, "route_deviated": gs.route_deviated,
        "is_idle": gs.is_idle, "alert_count": len(alerts),
        "alerts": alerts,
        "safety_check_pending": live.get("safety_check_pending", False),
    }


async def get_active_sessions(session: AsyncSession) -> list[dict]:
    # Try Redis cache first (short TTL for freshness)
    from app.services.redis_service import get_active_sessions as redis_get, cache_active_sessions

    cached = redis_get()
    if cached is not None:
        return cached

    result = await session.execute(
        select(GuardianSession).where(GuardianSession.status.in_(["active", "stale"]))
    )
    now = datetime.now(timezone.utc)
    sessions = []
    for gs in result.scalars().all():
        sessions.append({
            "session_id": str(gs.id), "user_id": str(gs.user_id),
            "status": gs.status,
            "duration_minutes": round((now - gs.started_at).total_seconds() / 60, 1),
            "risk_level": gs.risk_level, "risk_score": gs.risk_score,
            "zone_name": gs.zone_name, "is_idle": gs.is_idle,
            "route_deviated": gs.route_deviated, "escalation_level": gs.escalation_level,
            "location": gs.current_location, "eta_minutes": gs.eta_minutes,
            "location_updates": gs.location_updates,
        })
    sessions.sort(key=lambda x: x["risk_score"], reverse=True)

    # Cache in Redis with short TTL (120s)
    cache_active_sessions(sessions)

    return sessions


async def get_user_sessions(session: AsyncSession, user_id: str, limit: int = 10) -> list[dict]:
    result = await session.execute(
        select(GuardianSession).where(GuardianSession.user_id == uuid.UUID(user_id))
        .order_by(GuardianSession.started_at.desc()).limit(limit)
    )
    now = datetime.now(timezone.utc)
    return [{
        "session_id": str(gs.id), "status": gs.status,
        "started_at": gs.started_at.isoformat(),
        "ended_at": gs.ended_at.isoformat() if gs.ended_at else None,
        "duration_minutes": round(((gs.ended_at or now) - gs.started_at).total_seconds() / 60, 1),
        "risk_level": gs.risk_level, "total_distance_m": round(gs.total_distance_m, 1),
        "location_updates": gs.location_updates, "escalation_level": gs.escalation_level,
    } for gs in result.scalars().all()]


# ── Location Updates ──

async def update_location(
    session: AsyncSession, session_id: str, lat: float, lng: float,
    timestamp: datetime | None = None,
    accuracy: float | None = None,
) -> dict:
    result = await session.execute(select(GuardianSession).where(GuardianSession.id == uuid.UUID(session_id)))
    gs = result.scalar_one_or_none()
    if not gs:
        return {"error": "No active session"}

    # ╔══════════════════════════════════════════════════════════════╗
    # ║ STEP 3 — STALE PACKET GUARD (Invariant #2 — server clock    ║
    # ║ is the authority). FIRST. NO EXCEPTIONS. Out-of-order GPS   ║
    # ║ packets under poor mobile networks would otherwise produce  ║
    # ║ phantom recovery events. Drop silently — no log, no state, ║
    # ║ no SSE event.                                                ║
    # ║ See /app/memory/SYSTEM_INVARIANTS.md.                        ║
    # ╚══════════════════════════════════════════════════════════════╝
    if (timestamp is not None
            and gs.previous_update_at is not None
            and timestamp <= gs.previous_update_at):
        return {"stale": True}

    # ── 24-hour zombie-session hard cap ───────────────────────────────
    # The resurrection rule (`expired/stale → active` on the next ping)
    # is safety-correct, but it lets a session live forever as long as
    # the device keeps pinging. That's a leak: a journey started
    # yesterday should not be the active context for today's GPS.
    # Hard cap: any session older than 24h is auto-completed and rejects.
    # The API layer will then route the ping to shadow_ping, so the
    # trail is still captured — we just decline to keep the session row
    # alive past its bedtime.
    MAX_SESSION_AGE_S = 24 * 3600
    if gs.started_at and gs.status not in ("ended", "completed"):
        age_s = (datetime.now(timezone.utc) - gs.started_at).total_seconds()
        if age_s > MAX_SESSION_AGE_S:
            gs.status = "completed"
            gs.ended_at = datetime.now(timezone.utc)
            _live_state.pop(session_id, None)
            await session.flush()
            logger.info(
                f"SESSION_AGE_CAP id={session_id} age={age_s/3600:.1f}h → completed"
            )
            return {"error": "Session is completed — cannot update location"}

    # Safety-first session policy:
    #   • `ended` / `completed`  →  USER-INTENT terminal. The user (or a
    #     guardian) explicitly closed the journey. Auto-resurrecting
    #     these would silently restart a journey someone deliberately
    #     stopped — never do this. Reject the ping.
    #   • `expired` / `stale`    →  AUTO-SWEEPER marks (no inbound ping
    #     for >5 / >10 min). This is a TRACKING GAP, not a user intent
    #     to stop. The arrival of a fresh GPS ping IS the recovery
    #     signal — resurrect the session and accept the ping.
    #
    # Golden rule (safety system): tracking must NEVER stop because
    # an internal lifecycle timer ran out while the device is still
    # alive and pinging.
    if gs.status in ("ended", "completed"):
        return {"error": f"Session is {gs.status} — cannot update location"}
    if gs.status in ("expired", "stale"):
        prev_status = gs.status
        gs.status = "active"
        # Sweeper sets ended_at when it expires — clear it so the
        # journey looks alive again.
        if prev_status == "expired":
            gs.ended_at = None
        logger.info(
            f"SESSION_RESURRECTED id={session_id} from={prev_status} → active "
            f"(GPS ping recovered the session)"
        )

    now = timestamp or datetime.now(timezone.utc)
    live = _live_state.get(session_id, {})
    prev_loc = live.get("prev_location", gs.current_location or {"lat": lat, "lng": lng})
    prev_ts = live.get("prev_update_at", gs.started_at)

    # ╔══════════════════════════════════════════════════════════════╗
    # ║ STEP 4 — GAP DETECTION (server-clock based, Invariant #2)   ║
    # ║ Classifies the gap between this and the previous accepted   ║
    # ║ ping into 3 quality tiers and feeds is_offline into the      ║
    # ║ ACK engine's tracking_mode (Invariant #1 — single state      ║
    # ║ owner). Gap math uses the SERVER session clock, never the   ║
    # ║ device timestamp.                                            ║
    # ╚══════════════════════════════════════════════════════════════╝
    server_now = datetime.now(timezone.utc)
    server_prev = gs.previous_update_at or gs.started_at
    gap_s = (server_now - server_prev).total_seconds() if server_prev else 0.0
    if gap_s >= 30:
        quality = "offline"
        gs.offline_gaps = (gs.offline_gaps or 0) + 1
    elif gap_s >= 15:
        quality = "unstable"
    else:
        quality = "good"
    gs.max_gap_seconds = max(gs.max_gap_seconds or 0, int(gap_s))

    was_offline = bool(gs.is_offline)
    gs.is_offline = (quality == "offline")
    if quality != "offline":
        gs.last_seen_online_at = server_now

    # Append-only event log entry. seq is monotonic per session.
    next_seq = (gs.total_points or 0) + 1
    gs.total_points = next_seq
    session.add(JourneyPoint(
        session_id=gs.id,
        user_id=gs.user_id,
        seq=next_seq,
        lat=lat, lng=lng,
        accuracy=accuracy,
        speed_mps=None,  # filled in below after speed compute, see flush
        quality=quality,
        gap_before_s=int(gap_s) if server_prev else None,
        gps_recorded_at=timestamp,
        server_received_at=server_now,
    ))

    # Recovery transition — fires ONLY from the GPS path (Invariant #3).
    if was_offline and not gs.is_offline:
        await _broadcast_journey_event(gs, "journey_resumed", {
            "session_id": str(gs.id), "seq": next_seq,
            "gap_seconds": int(gap_s), "lat": lat, "lng": lng,
        })
    elif not was_offline and gs.is_offline:
        await _broadcast_journey_event(gs, "journey_paused", {
            "session_id": str(gs.id), "seq": next_seq,
            "gap_seconds": int(gap_s), "auto": False,
        })

    # Compute speed & distance
    dt = (now - prev_ts).total_seconds()
    dist = _haversine(prev_loc["lat"], prev_loc["lng"], lat, lng)
    speed = dist / dt if dt > 0 else 0.0

    # Zone check
    zone = await check_zone(session, str(gs.user_id), lat, lng, now)
    prev_risk = gs.risk_level
    new_risk = zone["risk_level"]

    alerts_generated = []

    # Zone escalation
    if RISK_ORDER.get(new_risk, 0) > RISK_ORDER.get(prev_risk, 0):
        esc = RISK_ESC_MAP.get(new_risk, "none")
        alert = await _create_alert(session, session_id, "zone_risk", new_risk.lower(),
            f"Risk escalation: {prev_risk} -> {new_risk}",
            f"Entered {zone['zone_name']} ({new_risk} risk, score {zone['risk_score']})",
            zone.get("recommendation_message", ""),
            {"lat": lat, "lng": lng}, user_id=str(gs.user_id),
        )
        alerts_generated.append(alert)
        if ESC_ORDER.get(esc, 0) > ESC_ORDER.get(gs.escalation_level, 0):
            gs.escalation_level = esc

    # Idle detection
    if speed < IDLE_SPEED_THRESHOLD:
        if not gs.is_idle:
            gs.is_idle = True
            live["idle_since"] = now
        else:
            idle_start = live.get("idle_since", now)
            idle_dur = (now - idle_start).total_seconds()
            if idle_dur >= IDLE_DURATION_THRESHOLD_S and not live.get("safety_check_pending"):
                live["safety_check_pending"] = True
                live["safety_check_sent_at"] = now
                alert = await _create_alert(session, session_id, "idle", "medium",
                    f"Stopped for {round(idle_dur)}s — are you safe?",
                    "Unexpected stop detected", "Tap to confirm you are safe",
                    {"lat": lat, "lng": lng}, user_id=str(gs.user_id),
                )
                alerts_generated.append(alert)
    else:
        gs.is_idle = False
        live["idle_since"] = None
        live["safety_check_pending"] = False

    # ETA
    eta = None
    if gs.destination and speed > 0.3:
        dest_dist = _haversine(lat, lng, gs.destination["lat"], gs.destination["lng"])
        eta = round(dest_dist / speed / 60, 1)
        if dest_dist < 200:
            alert = await _create_alert(session, session_id, "arrived", "low",
                "Arrived at destination safely",
                f"Within {round(dest_dist)}m of destination",
                "Journey complete.", {"lat": lat, "lng": lng}, user_id=str(gs.user_id),
            )
            alerts_generated.append(alert)

    # No-response escalation
    if live.get("safety_check_pending") and live.get("safety_check_sent_at"):
        elapsed = (now - live["safety_check_sent_at"]).total_seconds()
        if elapsed > 300 and gs.escalation_level != "emergency":
            gs.escalation_level = "emergency"
            alert = await _create_alert(session, session_id, "emergency", "critical",
                "No response — escalating to emergency",
                f"Unresponsive for {round(elapsed)}s",
                "Emergency services may be contacted",
                {"lat": lat, "lng": lng}, user_id=str(gs.user_id),
            )
            alerts_generated.append(alert)

    # Update DB
    gs.current_location = {"lat": lat, "lng": lng}
    gs.previous_update_at = now
    gs.risk_level = new_risk
    gs.risk_score = zone["risk_score"]
    gs.zone_name = zone["zone_name"]
    gs.speed_mps = speed
    gs.eta_minutes = eta
    gs.total_distance_m += dist
    gs.location_updates += 1
    gs.is_night = (now.hour >= 22 or now.hour < 5)
    await session.flush()

    live["prev_location"] = {"lat": lat, "lng": lng}
    live["prev_update_at"] = now
    _live_state[session_id] = live

    # ── Broadcast location_update to guardians via SSE ──
    try:
        from app.services.event_broadcaster import broadcaster

        logger.info(f"LOCATION_UPDATE_CALLED session={session_id} lat={lat} lng={lng}")

        # Cache guardian user_ids + child name + role for this session (avoids repeated DB lookups)
        guardian_ids = live.get("_guardian_user_ids")
        child_name = live.get("_child_name")
        child_role = live.get("_child_role")
        if guardian_ids is None:
            guardian_ids, child_name, child_role = await _resolve_guardian_ids(session, str(gs.user_id))
            live["_guardian_user_ids"] = guardian_ids
            live["_child_name"] = child_name
            live["_child_role"] = child_role
            _live_state[session_id] = live

        logger.info(f"LOCATION_UPDATE_GUARDIANS count={len(guardian_ids)} ids={guardian_ids}")

        if guardian_ids:
            location_event = {
                "lat": lat,
                "lng": lng,
                "child_id": str(gs.user_id),
                "child_name": child_name or "Unknown",
                "child_role": child_role or "child",
                "speed_mps": round(speed, 2),
                "zone": zone["zone_name"],
                "risk_level": new_risk,
                "timestamp": now.isoformat(),
            }
            for gid in guardian_ids:
                await broadcaster.broadcast_to_user(gid, "location_update", location_event)

            # ── Compute and broadcast risk_update to guardians ──
            # Score (mirrors `guardian_live._compute_child_risk`).
            risk_score = 0
            risk_factors = []
            stale_s = 0.0
            if gs.previous_update_at:
                stale_s = (now - gs.previous_update_at).total_seconds()
                if stale_s > 60:
                    risk_score += 4
                    risk_factors.append(f"No update {int(stale_s)}s")
                elif stale_s > 30:
                    risk_score += 2
                    risk_factors.append(f"Stale {int(stale_s)}s")
            if gs.is_night:
                risk_score += 2
                risk_factors.append("Night travel")
            if gs.route_deviated:
                risk_score += 3
                risk_factors.append("Route deviated")
            elif speed > 25:
                risk_score += 3
                risk_factors.append(f"High speed {round(speed*3.6)}km/h")
            alert_count = len(alerts_generated)
            if alert_count > 0:
                risk_score += 5
                risk_factors.append(f"{alert_count} alert(s)")
            if gs.escalation_level and ESC_ORDER.get(gs.escalation_level, 0) >= 2:
                risk_score += 2
                risk_factors.append(f"Escalation:{gs.escalation_level}")
            risk_color = "CRITICAL" if risk_score >= 9 else (
                "RED" if risk_score >= 7 else (
                    "YELLOW" if risk_score >= 4 else "GREEN"))

            # Hand off to the disciplined emitter — emits ONLY on
            # bucket change / score delta ≥ 2 / escalation change /
            # offline transition. Replaces the previous "emit on every
            # GPS ping" behavior which was effectively push-polling.
            from app.services.risk_emitter import maybe_emit_risk_update
            await maybe_emit_risk_update(
                child_id=str(gs.user_id),
                guardian_ids=guardian_ids,
                score=risk_score,
                risk_level=risk_color,
                escalation_level=gs.escalation_level,
                is_offline=stale_s > 60,
                payload_extras={
                    "child_name": child_name or "Unknown",
                    "lat": lat,
                    "lng": lng,
                    "factors": risk_factors,
                    "speed_kmh": round(speed * 3.6, 1),
                    "last_updated": now.isoformat(),
                },
            )
        else:
            logger.warning(f"LOCATION_UPDATE_NO_GUARDIANS child={gs.user_id}")
    except Exception as e:
        logger.error(f"LOCATION_UPDATE SSE broadcast failed: {e}", exc_info=True)

    return {
        "session_id": session_id, "location": {"lat": lat, "lng": lng},
        "zone": {"risk_level": new_risk, "risk_score": zone["risk_score"], "zone_name": zone["zone_name"]},
        "speed_mps": round(speed, 2), "eta_minutes": eta,
        "is_idle": gs.is_idle, "escalation_level": gs.escalation_level,
        "alerts": [_alert_to_dict(a) for a in alerts_generated],
        "alert_count": len(alerts_generated),
        "safety_check_pending": live.get("safety_check_pending", False),
        "timestamp": now.isoformat(),
    }


async def acknowledge_safety(session: AsyncSession, session_id: str) -> dict:
    live = _live_state.get(session_id, {})
    live["safety_check_pending"] = False
    live["safety_check_sent_at"] = None
    _live_state[session_id] = live

    result = await session.execute(select(GuardianSession).where(GuardianSession.id == uuid.UUID(session_id)))
    gs = result.scalar_one_or_none()
    if gs and gs.escalation_level == "emergency":
        gs.escalation_level = RISK_ESC_MAP.get(gs.risk_level, "none")
        await session.flush()

    await _create_alert(session, session_id, "safety_confirmed", "low",
        "User confirmed safe", "Safety check acknowledged", "Continue monitoring", None)

    return {"acknowledged": True, "session_id": session_id}


# ── Helpers ──

async def _create_alert(session: AsyncSession, session_id: str, alert_type: str,
                         severity: str, message: str, details: str, recommendation: str,
                         location: dict | None, user_id: str | None = None) -> GuardianAlert:
    # Every alert MUST know its subject (the child). For session-scoped
    # alerts we derive user_id from the session if the caller didn't
    # pass it explicitly. NOT NULL on the column will reject mistakes.
    if user_id is None:
        gs = (await session.execute(
            select(GuardianSession).where(GuardianSession.id == uuid.UUID(session_id))
        )).scalar_one_or_none()
        if gs is not None:
            user_id = str(gs.user_id)
    if not user_id:
        # Audit trail is non-negotiable — fail fast with a clear error
        # rather than producing a row that the DB constraint will
        # silently reject inside a swallowed try/except higher up.
        raise ValueError(
            f"_create_alert: cannot derive user_id (session_id={session_id}, "
            f"alert_type={alert_type}). Caller must pass user_id explicitly "
            f"OR the session must exist."
        )
    alert = GuardianAlert(
        session_id=uuid.UUID(session_id),
        user_id=uuid.UUID(user_id),
        alert_type=alert_type,
        severity=severity, message=message, details=details,
        recommendation=recommendation, location=location,
    )
    session.add(alert)
    await session.flush()

    # Control Layer: critical-severity alerts demand a human ACK with
    # a 30s deadline. Lower severities stay fire-and-forget.
    try:
        from app.services.alert_ack_engine import (
            severity_requires_ack, mark_for_ack,
        )
        if severity_requires_ack(severity):
            await mark_for_ack(session, alert)
    except Exception:
        logger.exception("[alert_ack] mark_for_ack wiring failed (non-fatal)")

    # Dispatch real notifications to guardians
    if user_id:
        try:
            from app.services.guardian_notification_dispatcher import dispatch_guardian_alert
            dispatch_result = await dispatch_guardian_alert(session, alert, user_id, session_id)
            logger.info(f"Alert dispatch: {alert_type} -> push={dispatch_result.get('push_sent',0)}, sms={dispatch_result.get('sms_sent',0)}")
        except Exception as e:
            logger.error(f"Notification dispatch failed: {e}")

    return alert



async def _resolve_guardian_ids(session: AsyncSession, child_user_id: str) -> tuple[list[str], str | None, str | None]:
    """Look up guardian user_ids + child name + role for SSE broadcasting.
    Uses 3 resolution paths (same sources as alerts API) + fallback via CheckIn records."""
    child_uuid = uuid.UUID(child_user_id)

    # Get child name and role
    child_result = await session.execute(select(User).where(User.id == child_uuid))
    child = child_result.scalar_one_or_none()
    child_name = child.full_name if child else None
    child_role = child.role if child else None
    logger.info(f"RESOLVE_GUARDIAN child={child_user_id} name={child_name} role={child_role}")

    guardian_user_ids: set[str] = set()

    # Path 1: Guardian table — Guardian.user_id is the CHILD, Guardian.email is the GUARDIAN
    try:
        g_result = await session.execute(
            select(Guardian).where(Guardian.user_id == child_uuid)
        )
        g_rows = g_result.scalars().all()
        logger.info(f"RESOLVE_GUARDIAN Path1(Guardian table): {len(g_rows)} records, emails={[g.email for g in g_rows]}")
        for g in g_rows:
            if g.email:
                u_result = await session.execute(select(User).where(User.email == g.email))
                u = u_result.scalar_one_or_none()
                if u:
                    guardian_user_ids.add(str(u.id))
                    logger.info(f"RESOLVE_GUARDIAN Path1 matched: email={g.email} → user_id={u.id}")
                else:
                    logger.warning(f"RESOLVE_GUARDIAN Path1 no User for email={g.email}")
    except Exception as e:
        logger.error(f"RESOLVE_GUARDIAN Path1 failed: {e}")

    # Path 2: Relationship table — direct ID link
    try:
        from app.models.relationship import Relationship
        rel_result = await session.execute(
            select(Relationship).where(Relationship.child_id == child_uuid, Relationship.status == "accepted")
        )
        rel_rows = rel_result.scalars().all()
        logger.info(f"RESOLVE_GUARDIAN Path2(Relationship table): {len(rel_rows)} records")
        for r in rel_rows:
            gid = str(r.guardian_id)
            guardian_user_ids.add(gid)
            logger.info(f"RESOLVE_GUARDIAN Path2 matched: guardian_id={gid}")
    except Exception as e:
        logger.error(f"RESOLVE_GUARDIAN Path2 failed: {e}")

    # Path 3 FALLBACK: CheckIn table — find guardians who have sent check-ins to this child
    if not guardian_user_ids:
        try:
            from app.models.checkin import CheckIn
            ci_result = await session.execute(
                select(CheckIn.guardian_id).where(CheckIn.child_id == child_uuid).distinct()
            )
            for row in ci_result.all():
                gid = str(row[0])
                guardian_user_ids.add(gid)
                logger.info(f"RESOLVE_GUARDIAN Path3(CheckIn fallback) matched: guardian_id={gid}")
        except Exception as e:
            logger.error(f"RESOLVE_GUARDIAN Path3 failed: {e}")

    result = list(guardian_user_ids)
    logger.info(f"RESOLVE_GUARDIAN FINAL: {len(result)} guardian(s) for child {child_user_id}: {result}")
    return result, child_name, child_role


def _alert_to_dict(a: GuardianAlert) -> dict:
    return {
        "id": str(a.id), "alert_type": a.alert_type, "severity": a.severity,
        "message": a.message, "details": a.details,
        "recommendation": a.recommendation, "location": a.location,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "notifications_dispatched": True,
    }


async def _get_session_alerts(session: AsyncSession, session_id: str, limit: int = 10) -> list[dict]:
    result = await session.execute(
        select(GuardianAlert).where(GuardianAlert.session_id == uuid.UUID(session_id))
        .order_by(GuardianAlert.created_at.desc()).limit(limit)
    )
    return [_alert_to_dict(a) for a in result.scalars().all()]


async def _count_alerts(session: AsyncSession, session_id: str) -> int:
    from sqlalchemy import func
    result = await session.execute(
        select(func.count()).where(GuardianAlert.session_id == uuid.UUID(session_id))
    )
    return result.scalar() or 0



# ── Session Lifecycle: Stale / Expired ──

STALE_THRESHOLD_MINUTES = 5
EXPIRE_THRESHOLD_MINUTES = 10


async def expire_stale_sessions(session: AsyncSession) -> dict:
    """Mark stale and expired sessions. Called by background scheduler every 60s."""
    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(minutes=STALE_THRESHOLD_MINUTES)
    expire_cutoff = now - timedelta(minutes=EXPIRE_THRESHOLD_MINUTES)

    # 1. Expire: active or stale sessions with no update for >10 minutes
    expire_result = await session.execute(
        select(GuardianSession).where(
            GuardianSession.status.in_(["active", "stale"]),
            GuardianSession.previous_update_at < expire_cutoff,
            GuardianSession.previous_update_at.isnot(None),
        )
    )
    expired_count = 0
    for gs in expire_result.scalars().all():
        gs.status = "expired"
        gs.ended_at = now
        _live_state.pop(str(gs.id), None)
        expired_count += 1

    # Also expire sessions that never got a location update (use started_at)
    no_update_result = await session.execute(
        select(GuardianSession).where(
            GuardianSession.status.in_(["active", "stale"]),
            GuardianSession.previous_update_at.is_(None),
            GuardianSession.started_at < expire_cutoff,
        )
    )
    for gs in no_update_result.scalars().all():
        gs.status = "expired"
        gs.ended_at = now
        _live_state.pop(str(gs.id), None)
        expired_count += 1

    # 2. Stale: active sessions with no update for >5 minutes (but <10)
    stale_result = await session.execute(
        select(GuardianSession).where(
            GuardianSession.status == "active",
            GuardianSession.previous_update_at < stale_cutoff,
            GuardianSession.previous_update_at.isnot(None),
        )
    )
    stale_count = 0
    for gs in stale_result.scalars().all():
        gs.status = "stale"
        stale_count += 1

    # Also stale sessions with no update at all
    no_update_stale = await session.execute(
        select(GuardianSession).where(
            GuardianSession.status == "active",
            GuardianSession.previous_update_at.is_(None),
            GuardianSession.started_at < stale_cutoff,
        )
    )
    for gs in no_update_stale.scalars().all():
        gs.status = "stale"
        stale_count += 1

    if stale_count or expired_count:
        await session.flush()
        # Invalidate cache
        from app.services.redis_service import delete_key
        delete_key("sessions", "active")

    logger = logging.getLogger(__name__)
    if stale_count or expired_count:
        logger.info(f"SESSION_LIFECYCLE stale={stale_count} expired={expired_count}")

    return {"stale": stale_count, "expired": expired_count}
