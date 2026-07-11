# Demo Mode Engine — Simulates realistic safety scenarios for investor demos
# Generates a 30-second scenario: Session → Risk → Anomaly → SOS → Incident

import asyncio
import uuid
import logging
import random
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import text, select, and_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guardian import GuardianSession, GuardianAlert
from app.models.user import User

logger = logging.getLogger(__name__)

# Demo user profiles
DEMO_PROFILES = [
    {"name": "Riya Sharma", "email": "riya.demo@nischint.app",
     "route": [
         {"lat": 19.0760, "lng": 72.8777},  # Start: Sion
         {"lat": 19.0720, "lng": 72.8700},
         {"lat": 19.0680, "lng": 72.8620},
         {"lat": 19.0640, "lng": 72.8550},
         {"lat": 19.0600, "lng": 72.8480},  # Deviation point
         {"lat": 19.0550, "lng": 72.8350},  # Risk zone
         {"lat": 19.0520, "lng": 72.8300},  # SOS point
     ],
     "destination": {"lat": 19.0544, "lng": 72.8402, "name": "Bandra Station"},
    },
    {"name": "Ananya Patel", "email": "ananya.demo@nischint.app",
     "route": [
         {"lat": 19.1197, "lng": 72.9052},  # Powai
         {"lat": 19.1150, "lng": 72.9000},
         {"lat": 19.1100, "lng": 72.8940},
         {"lat": 19.1050, "lng": 72.8880},
         {"lat": 19.1000, "lng": 72.8820},
     ],
     "destination": {"lat": 19.1000, "lng": 72.8820, "name": "Hiranandani"},
    },
    {"name": "Neha Verma", "email": "neha.demo@nischint.app",
     "route": [
         {"lat": 19.0178, "lng": 72.8478},  # Dadar
         {"lat": 19.0200, "lng": 72.8500},
         {"lat": 19.0230, "lng": 72.8530},
         {"lat": 19.0260, "lng": 72.8560},
         {"lat": 19.0290, "lng": 72.8590},
     ],
     "destination": {"lat": 19.0290, "lng": 72.8590, "name": "Mahim"},
    },
]

# Scenario timeline (seconds from start → action)
SCENARIO_TIMELINE = [
    (0,  "session_start",  "Safety session started"),
    (4,  "location_1",     "Moving along route"),
    (8,  "risk_low",       "Entering area with elevated risk"),
    (12, "anomaly",        "Behavioral anomaly: unusual pace change"),
    (16, "risk_high",      "Risk score increasing — multiple factors"),
    (18, "deviation",      "Route deviation detected"),
    (20, "sos",            "SOS triggered"),
    (23, "notification",   "Guardian notified via push + email"),
    (25, "escalation",     "Command Center alert escalated"),
    (28, "resolved",       "Incident created — replay available"),
]

# Module-level demo state
_demo_state = {
    "running": False,
    "task": None,
    "started_at": None,
    "current_step": 0,
    "sessions": {},
    "scenario_user": None,
}


def is_demo_running():
    return _demo_state["running"]


def get_demo_status():
    return {
        "running": _demo_state["running"],
        "started_at": _demo_state["started_at"].isoformat() if _demo_state["started_at"] else None,
        "current_step": _demo_state["current_step"],
        "total_steps": len(SCENARIO_TIMELINE),
        "scenario_user": _demo_state["scenario_user"],
        "elapsed_seconds": int((datetime.now(timezone.utc) - _demo_state["started_at"]).total_seconds()) if _demo_state["started_at"] else 0,
    }


async def ensure_demo_users(session: AsyncSession, guardian_user_id=None):
    """Create or fetch demo user accounts and link them to the guardian."""
    from app.models.guardian_network import GuardianRelationship

    demo_users = []
    for profile in DEMO_PROFILES:
        user = (await session.execute(
            select(User).where(User.email == profile["email"])
        )).scalar_one_or_none()

        if not user:
            user = User(
                email=profile["email"],
                full_name=profile["name"],
                password_hash="demo_no_login",
                role="guardian",
            )
            session.add(user)
            await session.flush()

        # Create guardian relationship if admin user provided
        if guardian_user_id:
            existing_rel = (await session.execute(
                select(GuardianRelationship).where(and_(
                    GuardianRelationship.user_id == user.id,
                    GuardianRelationship.guardian_user_id == guardian_user_id,
                ))
            )).scalar_one_or_none()

            if not existing_rel:
                rel = GuardianRelationship(
                    user_id=user.id,
                    guardian_user_id=guardian_user_id,
                    guardian_name="Admin Guardian",
                    relationship_type="demo_guardian",
                    priority=1,
                    is_active=True,
                )
                session.add(rel)

        demo_users.append({
            "user": user,
            "profile": profile,
        })

    await session.commit()
    return demo_users


async def start_demo(session_factory, guardian_user_id=None):
    """Start the demo scenario in background."""
    if _demo_state["running"]:
        return {"status": "already_running", **get_demo_status()}

    _demo_state["running"] = True
    _demo_state["started_at"] = datetime.now(timezone.utc)
    _demo_state["current_step"] = 0
    _demo_state["sessions"] = {}

    # Run scenario in background
    _demo_state["task"] = asyncio.create_task(
        _run_demo_scenario(session_factory, guardian_user_id)
    )

    return {"status": "started", **get_demo_status()}


async def stop_demo(session_factory):
    """Stop the demo and clean up."""
    if _demo_state["task"] and not _demo_state["task"].done():
        _demo_state["task"].cancel()

    # End any active demo sessions
    async with session_factory() as session:
        for sid in list(_demo_state["sessions"].values()):
            try:
                gs = (await session.execute(
                    select(GuardianSession).where(GuardianSession.id == uuid.UUID(sid))
                )).scalar_one_or_none()
                if gs and gs.status == "active":
                    gs.status = "completed"
                    gs.ended_at = datetime.now(timezone.utc)
            except Exception:
                pass
        await session.commit()

    _demo_state["running"] = False
    _demo_state["task"] = None
    _demo_state["current_step"] = 0
    _demo_state["sessions"] = {}
    _demo_state["scenario_user"] = None

    return {"status": "stopped"}


async def _run_demo_scenario(session_factory, guardian_user_id=None):
    """Execute the full demo scenario timeline."""
    try:
        async with session_factory() as session:
            demo_users = await ensure_demo_users(session, guardian_user_id)

        # Pick primary demo user (Riya)
        primary = demo_users[0]
        profile = primary["profile"]
        user = primary["user"]
        user_id = user.id
        _demo_state["scenario_user"] = profile["name"]

        route = profile["route"]
        prev_time = 0

        for step_idx, (time_s, action, description) in enumerate(SCENARIO_TIMELINE):
            if not _demo_state["running"]:
                break

            # Wait for the right time
            wait = time_s - prev_time
            if wait > 0:
                await asyncio.sleep(wait)
            prev_time = time_s
            _demo_state["current_step"] = step_idx + 1

            logger.info(f"[DEMO] Step {step_idx + 1}/{len(SCENARIO_TIMELINE)}: {action} — {description}")

            async with session_factory() as session:
                if action == "session_start":
                    await _demo_start_session(session, user_id, profile)

                elif action.startswith("location_"):
                    idx = min(1, len(route) - 1)
                    await _demo_update_location(session, user_id, route[idx])

                elif action == "risk_low":
                    idx = min(2, len(route) - 1)
                    await _demo_update_location(session, user_id, route[idx], risk_score=2.5, risk_level="LOW")
                    await _demo_create_alert(session, user_id, "zone_escalation", "low",
                                              "Entering elevated risk area — historical incident zone",
                                              "Stay alert. Area has moderate incident history.", route[idx])

                elif action == "anomaly":
                    idx = min(3, len(route) - 1)
                    await _demo_update_location(session, user_id, route[idx], risk_score=4.2, risk_level="MODERATE")
                    await _demo_create_alert(session, user_id, "behavior_anomaly", "moderate",
                                              "Unusual pace detected — 60% slower than baseline",
                                              "Behavioral change detected. Consider check-in.", route[idx])

                elif action == "risk_high":
                    idx = min(4, len(route) - 1)
                    await _demo_update_location(session, user_id, route[idx], risk_score=6.8, risk_level="HIGH")
                    await _demo_create_alert(session, user_id, "risk_escalation", "high",
                                              "Risk score spike: MODERATE → HIGH (6.8/10)",
                                              "Multiple risk factors converging. Guardian alert recommended.", route[idx])

                elif action == "deviation":
                    idx = min(5, len(route) - 1)
                    await _demo_update_location(session, user_id, route[idx], risk_score=7.5, risk_level="HIGH",
                                                 route_deviated=True)
                    await _demo_create_alert(session, user_id, "route_deviation", "high",
                                              "Route deviation: 450m from planned safe route",
                                              "User has deviated significantly. Immediate check-in advised.", route[idx])

                elif action == "sos":
                    idx = min(6, len(route) - 1)
                    await _demo_update_location(session, user_id, route[idx], risk_score=9.2, risk_level="CRITICAL")
                    await _demo_create_alert(session, user_id, "sos_triggered", "critical",
                                              f"SOS triggered by {profile['name']} near Bandra",
                                              "IMMEDIATE: Contact user and alert authorities.", route[idx])
                    # Create SOS event
                    await _demo_create_sos(session, user_id, route[idx])

                elif action == "notification":
                    # Send push notifications to all demo user guardians
                    await _demo_send_notifications(session_factory, user_id, profile["name"], route[-1])

                elif action == "escalation":
                    await _demo_create_alert(session, user_id, "command_escalation", "critical",
                                              "Incident escalated to Command Center — Level 2",
                                              "All operators notified. Response team dispatched.", route[-1])

                elif action == "resolved":
                    # Mark session complete
                    sid = _demo_state["sessions"].get(str(user_id))
                    if sid:
                        gs = (await session.execute(
                            select(GuardianSession).where(GuardianSession.id == uuid.UUID(sid))
                        )).scalar_one_or_none()
                        if gs:
                            gs.status = "completed"
                            gs.ended_at = datetime.now(timezone.utc)
                            await session.commit()

        # Demo complete
        _demo_state["running"] = False
        logger.info("[DEMO] Scenario complete — all steps executed")

    except asyncio.CancelledError:
        logger.info("[DEMO] Scenario cancelled")
    except (SQLAlchemyError, asyncio.TimeoutError, RuntimeError, ValueError) as e:
        # Compensating action: `_demo_state["running"]=False` flips
        # the demo into idle so the operator can restart. Demo path
        # is non-production but worth narrowing — a coding bug here
        # should propagate, not be silently absorbed into the demo
        # state machine.
        logger.error(
            "demo_scenario_failed",
            extra={
                "event":      "demo_scenario_failed",
                "error_type": type(e).__name__,
            },
        )
        _demo_state["running"] = False


async def _demo_start_session(session: AsyncSession, user_id, profile):
    """Start a demo safety session."""
    route = profile["route"]
    gs = GuardianSession(
        user_id=user_id,
        status="active",
        destination=profile["destination"],
        route_points=route,
        current_location=route[0],
        risk_level="SAFE",
        risk_score=0.0,
    )
    session.add(gs)
    await session.commit()
    await session.refresh(gs)
    _demo_state["sessions"][str(user_id)] = str(gs.id)


async def _demo_update_location(session: AsyncSession, user_id, location,
                                  risk_score=0, risk_level="SAFE",
                                  route_deviated=False):
    """Update demo user's session location and risk."""
    sid = _demo_state["sessions"].get(str(user_id))
    if not sid:
        return

    gs = (await session.execute(
        select(GuardianSession).where(GuardianSession.id == uuid.UUID(sid))
    )).scalar_one_or_none()

    if gs and gs.status == "active":
        gs.current_location = {"lat": location["lat"], "lng": location["lng"],
                                "updated_at": datetime.now(timezone.utc).isoformat()}
        gs.risk_score = risk_score
        gs.risk_level = risk_level
        gs.route_deviated = route_deviated
        gs.previous_update_at = datetime.now(timezone.utc)
        # Add to route points for trail
        if gs.route_points:
            gs.route_points = gs.route_points + [location]
        await session.commit()


async def _demo_create_alert(session: AsyncSession, user_id, alert_type, severity,
                               message, recommendation, location):
    """Create a demo alert in the session."""
    sid = _demo_state["sessions"].get(str(user_id))
    if not sid:
        return

    alert = GuardianAlert(
        session_id=uuid.UUID(sid),
        user_id=uuid.UUID(str(user_id)),
        alert_type=alert_type,
        severity=severity,
        message=message,
        recommendation=recommendation,
        location={"lat": location["lat"], "lng": location["lng"]},
    )
    session.add(alert)

    # Increment alert count on session
    gs = (await session.execute(
        select(GuardianSession).where(GuardianSession.id == uuid.UUID(sid))
    )).scalar_one_or_none()
    if gs:
        gs.alert_count = (gs.alert_count or 0) + 1

    await session.commit()


async def _demo_create_sos(session: AsyncSession, user_id, location):
    """Create a demo SOS event."""
    import json as json_mod
    try:
        loc_json = json_mod.dumps({"lat": location["lat"], "lng": location["lng"]})
        await session.execute(text("""
            INSERT INTO sos_events (id, user_id, trigger_type, location, risk_level, risk_score, guardians_notified, status, created_at)
            VALUES (:id, :uid, 'demo_manual', CAST(:loc AS jsonb), 'CRITICAL', 9.2, 3, 'triggered', :now)
        """), {
            "id": str(uuid.uuid4()),
            "uid": str(user_id),
            "loc": loc_json,
            "now": datetime.now(timezone.utc),
        })
        await session.commit()
    except SQLAlchemyError as e:
        # Compensating action: SOS-event row is demo-visualization
        # only — the SSE broadcast already fired in the surrounding
        # demo step. A failure here just means the historical
        # `sos_events` table is missing one demo row.
        logger.debug(f"[DEMO] SOS event creation skipped: {e}")
        await session.rollback()


async def _demo_send_notifications(session_factory, user_id, user_name, location):
    """Send push notifications to demonstrate the notification pipeline."""
    try:
        from app.services.notification_service import NotificationService
        ns = NotificationService(session_factory)

        # Send SOS notification to the demo user's own device (for demo visibility)
        await ns.send_push(
            user_id=str(user_id),
            title="SOS Alert",
            body=f"{user_name} triggered SOS near Bandra. Tap to view.",
            data={"type": "sos", "demo": "true"},
            tag="nischint-sos",
            url="/m/live",
        )
    except Exception as e:
        logger.debug(f"[DEMO] Notification skipped: {e}")
