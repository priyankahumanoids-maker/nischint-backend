# Escalation Scheduler - Multi-Level (Enqueue-Only) + Offline Device Detection
import logging
from datetime import datetime, timezone, timedelta
from uuid import UUID

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, and_, text
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.session import async_session
from app.models.device import Device
from app.models.incident import Incident, DEFAULT_ESCALATION_MINUTES
from app.models.notification_job import NotificationJob
from app.services.incident_events import log_event

logger = logging.getLogger(__name__)

LEVEL1_MINUTES = settings.escalation_l1_minutes
LEVEL2_MINUTES = settings.escalation_l2_minutes
LEVEL3_MINUTES = settings.escalation_l3_minutes

# Test mode: reduced thresholds (in minutes)
TEST_L1_MINUTES = 0.5   # 30 seconds
TEST_L2_MINUTES = 1.0   # 60 seconds
TEST_L3_MINUTES = 1.5   # 90 seconds
TEST_PREFIX = "[TEST ALERT] "

# Incident types that stay at L1 only — no L2/L3 escalation
L1_ONLY_INCIDENT_TYPES = {"device_offline", "low_battery", "signal_degradation", "reboot_anomaly", "device_instability"}

scheduler = AsyncIOScheduler()


def _get_thresholds(incident):
    """Return static escalation thresholds. For adaptive thresholds, use _get_adaptive_thresholds."""
    if getattr(incident, 'is_test', False):
        return TEST_L1_MINUTES, TEST_L2_MINUTES, TEST_L3_MINUTES
    return LEVEL1_MINUTES, LEVEL2_MINUTES, LEVEL3_MINUTES


async def _get_smart_thresholds(session, incident):
    """Return adaptive escalation thresholds using the Smart Escalation Engine.
    Falls back to static thresholds on error."""
    try:
        from app.services.smart_escalation_engine import get_adaptive_thresholds
        return await get_adaptive_thresholds(session, incident)
    except Exception as e:
        logger.warning(f"Smart thresholds fallback: {e}")
        return _get_thresholds(incident)


def _prefix_payload(payload: dict, is_test: bool) -> dict:
    """Add [TEST ALERT] prefix to notification payloads for test incidents."""
    if not is_test:
        return payload
    p = dict(payload)
    if 'subject' in p:
        p['subject'] = TEST_PREFIX + p['subject']
    if 'body' in p:
        p['body'] = TEST_PREFIX + p['body']
    if 'title' in p:
        p['title'] = TEST_PREFIX + p['title']
    return p


async def _enqueue_job(session, incident_id: UUID, channel: str, recipient: str, payload: dict, is_test: bool = False):
    """Insert a notification job with idempotency. Skips if duplicate key exists."""
    payload = _prefix_payload(payload, is_test)
    escalation_level = payload.get("escalation_level", 0)
    idem_key = f"{incident_id}:{channel}:{recipient}:{escalation_level}"

    # Check for existing job with same idempotency key
    existing = (await session.execute(
        select(NotificationJob).where(NotificationJob.idempotency_key == idem_key)
    )).scalar_one_or_none()

    if existing:
        logger.info(f"Idempotent skip: {channel} job for {recipient} already exists (key={idem_key})")
        return

    job = NotificationJob(
        incident_id=incident_id,
        channel=channel,
        recipient=recipient,
        payload=payload,
        status="pending",
        attempts=0,
        idempotency_key=idem_key,
    )
    session.add(job)
    logger.info(f"Enqueued {channel} job for {recipient} (incident {incident_id}, key={idem_key})")


async def _enqueue_guardian(session, incident, senior, guardian):
    """Level 1: Enqueue email + SMS + push jobs for the primary guardian."""
    from app.services.notification_formatter import sms_escalation, push_escalation, email_escalation
    is_test = getattr(incident, 'is_test', False)
    name = senior.full_name
    itype = incident.incident_type

    # Email
    subj, html = email_escalation(name, 1, itype)
    await _enqueue_job(session, incident.id, "email", guardian.email, {
        "subject": subj,
        "body": html,
        "escalation_level": 1,
    }, is_test)

    # SMS (if phone provided)
    if guardian.phone:
        await _enqueue_job(session, incident.id, "sms", guardian.phone, {
            "body": sms_escalation(name, 1, itype),
            "escalation_level": 1,
        }, is_test)

    # Push
    title, body = push_escalation(name, 1, itype)
    await _enqueue_job(session, incident.id, "push", str(guardian.id), {
        "title": title,
        "body": body,
        "escalation_level": 1,
    }, is_test)

    logger.info(f"L1 jobs enqueued for guardian {guardian.email}")

    # SSE stays inline (in-memory, instant)
    from app.services.event_broadcaster import broadcaster, serialize_for_sse
    incident_data = serialize_for_sse({
        "id": incident.id,
        "senior_id": incident.senior_id,
        "device_id": incident.device_id,
        "incident_type": incident.incident_type,
        "severity": incident.severity,
        "status": incident.status,
        "escalated": incident.escalated,
        "escalation_level": incident.escalation_level,
        "escalated_at": incident.escalated_at,
        "created_at": incident.created_at,
    })
    await broadcaster.broadcast_incident_escalated(
        str(senior.guardian_id), incident_data
    )


async def _enqueue_secondary(session, incident, senior):
    """Level 2: Enqueue jobs for active secondary contacts per routing preferences."""
    from app.models.user import User
    from app.services.notification_formatter import sms_escalation, email_escalation
    is_test = getattr(incident, 'is_test', False)
    name = senior.full_name
    itype = incident.incident_type

    result = await session.execute(
        text("SELECT name, email, phone, notify_email, notify_sms FROM secondary_contacts WHERE senior_id = :sid AND is_active = TRUE ORDER BY priority_order ASC"),
        {"sid": senior.id},
    )
    contacts = result.fetchall()

    if not contacts:
        logger.info(f"L2: No active secondary contacts for senior {name}")
        return

    for contact in contacts:
        cname, email, phone, notify_email, notify_sms = contact
        if notify_email and email:
            subj, html = email_escalation(name, 2, itype)
            await _enqueue_job(session, incident.id, "email", email, {
                "subject": subj,
                "body": html,
                "escalation_level": 2,
                "contact_name": cname,
            }, is_test)
            logger.info(f"L2 email job enqueued for {cname} ({email})")
        if notify_sms and phone:
            await _enqueue_job(session, incident.id, "sms", phone, {
                "body": sms_escalation(name, 2, itype),
                "escalation_level": 2,
                "contact_name": cname,
            }, is_test)
            logger.info(f"L2 SMS job enqueued for {cname} ({phone})")


async def _enqueue_operators(session, incident, senior):
    """Level 3: Enqueue email + SMS + push jobs for all operators."""
    from app.models.user import User
    from app.services.notification_formatter import sms_escalation, push_escalation, email_escalation
    is_test = getattr(incident, 'is_test', False)

    result = await session.execute(
        select(User).where(User.role.in_(["operator", "admin"]))
    )
    operators = result.scalars().all()

    if not operators:
        logger.info("L3: No operators found in system")
        return

    name = senior.full_name if senior else "Unknown"
    itype = incident.incident_type

    for op in operators:
        if op.email:
            subj, html = email_escalation(name, 3, itype)
            await _enqueue_job(session, incident.id, "email", op.email, {
                "subject": subj,
                "body": html,
                "escalation_level": 3,
            }, is_test)
            logger.info(f"L3 email job enqueued for operator {op.email}")

        if op.phone:
            await _enqueue_job(session, incident.id, "sms", op.phone, {
                "body": sms_escalation(name, 3, itype),
                "escalation_level": 3,
            }, is_test)
            logger.info(f"L3 SMS job enqueued for operator {op.phone}")

        title, body = push_escalation(name, 3, itype)
        await _enqueue_job(session, incident.id, "push", str(op.id), {
            "title": title,
            "body": body,
            "escalation_level": 3,
        }, is_test)


async def check_and_escalate_incidents():
    """Multi-level escalation check. Enqueues notification jobs instead of sending directly."""
    async with async_session() as session:
        try:
            now = datetime.now(timezone.utc)

            # ── Level 1: open + not yet escalated + NOT acknowledged ──
            stmt_l1 = (
                select(Incident)
                .options(selectinload(Incident.senior))
                .where(and_(
                    Incident.status == "open",
                    Incident.escalated.is_(False),
                    Incident.escalation_processing.is_(False),
                    Incident.acknowledged_at.is_(None),
                ))
                .with_for_update(skip_locked=True)
                .limit(50)
            )
            result_l1 = await session.execute(stmt_l1)
            l1_incidents = result_l1.scalars().all()

            l1_count = 0
            for incident in l1_incidents:
                l1_t, l2_t, l3_t = await _get_smart_thresholds(session, incident)
                # skip_l1: if l1_t == 0, escalate immediately to L2
                if l1_t == 0:
                    threshold = incident.created_at  # immediate
                else:
                    threshold = incident.created_at + timedelta(minutes=l1_t)
                if now > threshold:
                    incident.escalation_processing = True
                    incident.escalated = True
                    incident.escalated_at = now
                    incident.escalation_level = 1
                    l1_count += 1

                    logger.warning(
                        f">>> L1 ESCALATION: Incident {incident.id} "
                        f"({incident.incident_type}, {incident.severity})"
                    )

                    senior = incident.senior
                    if senior:
                        from app.models.user import User
                        guardian = (await session.execute(
                            select(User).where(User.id == senior.guardian_id)
                        )).scalar_one_or_none()
                        if guardian:
                            await _enqueue_guardian(session, incident, senior, guardian)
                            await log_event(session, incident.id, "escalation_l1", metadata={
                                "guardian_email": guardian.email,
                                "guardian_phone": guardian.phone,
                            })

            # ── Level 2: escalated L1 + still open + not yet L2 + NOT acknowledged (skip L1-only types) ──
            stmt_l2 = (
                select(Incident)
                .options(selectinload(Incident.senior))
                .where(and_(
                    Incident.status == "open",
                    Incident.escalated.is_(True),
                    Incident.escalation_level == 1,
                    Incident.level2_escalated_at.is_(None),
                    Incident.escalation_processing.is_(False),
                    Incident.acknowledged_at.is_(None),
                    Incident.incident_type.notin_(L1_ONLY_INCIDENT_TYPES),
                ))
                .with_for_update(skip_locked=True)
                .limit(50)
            )
            result_l2 = await session.execute(stmt_l2)
            l2_incidents = result_l2.scalars().all()

            l2_count = 0
            for incident in l2_incidents:
                l1_t, l2_t, l3_t = await _get_smart_thresholds(session, incident)
                threshold = incident.created_at + timedelta(minutes=l2_t)
                if now > threshold:
                    incident.escalation_processing = True
                    incident.escalation_level = 2
                    incident.level2_escalated_at = now
                    l2_count += 1

                    logger.warning(
                        f">>> L2 ESCALATION: Incident {incident.id} "
                        f"({incident.incident_type}, {incident.severity}) — secondary contacts"
                    )

                    senior = incident.senior
                    if senior:
                        await _enqueue_secondary(session, incident, senior)
                        await log_event(session, incident.id, "escalation_l2", metadata={
                            "senior_name": senior.full_name,
                        })

            # ── Level 3: L2 escalated + still open + not yet L3 + NOT acknowledged (skip L1-only types) ──
            stmt_l3 = (
                select(Incident)
                .options(selectinload(Incident.senior))
                .where(and_(
                    Incident.status == "open",
                    Incident.escalation_level == 2,
                    Incident.level3_escalated_at.is_(None),
                    Incident.escalation_processing.is_(False),
                    Incident.acknowledged_at.is_(None),
                    Incident.incident_type.notin_(L1_ONLY_INCIDENT_TYPES),
                ))
                .with_for_update(skip_locked=True)
                .limit(50)
            )
            result_l3 = await session.execute(stmt_l3)
            l3_incidents = result_l3.scalars().all()

            l3_count = 0
            for incident in l3_incidents:
                l1_t, l2_t, l3_t = await _get_smart_thresholds(session, incident)
                threshold = incident.created_at + timedelta(minutes=l3_t)
                if now > threshold:
                    incident.escalation_processing = True
                    incident.escalation_level = 3
                    incident.level3_escalated_at = now
                    l3_count += 1

                    logger.warning(
                        f">>> L3 ESCALATION: Incident {incident.id} "
                        f"({incident.incident_type}, {incident.severity}) — OPERATOR TEAM"
                    )

                    senior = incident.senior
                    await _enqueue_operators(session, incident, senior)
                    await log_event(session, incident.id, "escalation_l3", "operator", metadata={
                        "senior_name": senior.full_name if senior else "Unknown",
                    })

            total = l1_count + l2_count + l3_count

            # ── Offline Device Detection ──
            offline_threshold = now - timedelta(minutes=settings.device_offline_threshold_minutes)
            stmt_offline = (
                select(Device)
                .options(selectinload(Device.senior))
                .where(and_(
                    Device.last_seen.isnot(None),
                    Device.status == "online",
                    Device.last_seen < offline_threshold,
                ))
                .with_for_update(skip_locked=True)
                .limit(50)
            )
            result_offline = await session.execute(stmt_offline)
            stale_devices = result_offline.scalars().all()

            offline_count = 0
            for device in stale_devices:
                device.status = "offline"

                # Check for existing open device_offline incident
                existing_offline = (await session.execute(
                    select(Incident).where(and_(
                        Incident.device_id == device.id,
                        Incident.incident_type == "device_offline",
                        Incident.status == "open",
                    ))
                )).scalar_one_or_none()

                if existing_offline:
                    logger.debug(f"Offline incident already open for device {device.device_identifier}")
                    continue

                # Cooldown: skip if a device_offline incident was resolved recently
                cooldown_cutoff = now - timedelta(minutes=settings.device_offline_cooldown_minutes)
                recently_resolved = (await session.execute(
                    select(Incident).where(and_(
                        Incident.device_id == device.id,
                        Incident.incident_type == "device_offline",
                        Incident.status == "resolved",
                        Incident.resolved_at > cooldown_cutoff,
                    ))
                )).scalar_one_or_none()

                if recently_resolved:
                    logger.info(
                        f"Cooldown: skipping offline incident for {device.device_identifier} "
                        f"(resolved {recently_resolved.resolved_at}, cooldown={settings.device_offline_cooldown_minutes}min)"
                    )
                    continue

                # Create device_offline incident
                incident = Incident(
                    senior_id=device.senior_id,
                    device_id=device.id,
                    incident_type="device_offline",
                    severity="medium",
                    escalation_minutes=DEFAULT_ESCALATION_MINUTES.get("medium", 30),
                )
                session.add(incident)
                await session.flush()  # get incident.id for audit log

                await log_event(session, incident.id, "device_offline_detected", metadata={
                    "device_identifier": device.device_identifier,
                    "last_seen": device.last_seen.isoformat() if device.last_seen else None,
                    "threshold_minutes": settings.device_offline_threshold_minutes,
                })

                offline_count += 1
                logger.warning(
                    f">>> DEVICE OFFLINE: {device.device_identifier} "
                    f"(last_seen={device.last_seen}, threshold={settings.device_offline_threshold_minutes}min)"
                )

                # Broadcast SSE — incident created
                senior = device.senior
                if senior:
                    from app.services.event_broadcaster import broadcaster, serialize_for_sse
                    incident_data = serialize_for_sse({
                        "id": incident.id,
                        "senior_id": incident.senior_id,
                        "device_id": incident.device_id,
                        "incident_type": incident.incident_type,
                        "severity": incident.severity,
                        "status": incident.status,
                        "escalated": incident.escalated,
                        "escalation_level": incident.escalation_level,
                        "created_at": incident.created_at,
                    })
                    await broadcaster.broadcast_incident_created(str(senior.guardian_id), incident_data)

            total += offline_count

            # ── Auto-resolve test incidents after 2 minutes ──
            test_resolve_stmt = (
                select(Incident)
                .where(and_(
                    Incident.is_test.is_(True),
                    Incident.status == "open",
                    Incident.escalated.is_(True),
                ))
                .with_for_update(skip_locked=True)
                .limit(50)
            )
            test_result = await session.execute(test_resolve_stmt)
            test_incidents = test_result.scalars().all()
            test_resolved = 0
            for ti in test_incidents:
                if now > ti.created_at + timedelta(minutes=2):
                    ti.status = "resolved"
                    test_resolved += 1
                    await log_event(session, ti.id, "test_auto_resolved", metadata={
                        "resolved_by": "system",
                        "reason": "Test incident auto-resolved after 2 minutes",
                    })
                    logger.info(f"Test incident {ti.id} auto-resolved")
            total += test_resolved

            if total > 0:
                await session.commit()
                # Release processing lock after successful commit
                await session.execute(
                    text("UPDATE incidents SET escalation_processing = FALSE WHERE escalation_processing = TRUE")
                )
                await session.commit()
                logger.info(f"Escalation complete: L1={l1_count}, L2={l2_count}, L3={l3_count}, offline={offline_count}, test_resolved={test_resolved}")
            else:
                logger.debug("Escalation check: nothing to escalate")

        except Exception as e:
            logger.error(f"Escalation error: {e}")
            await session.rollback()


async def check_device_health():
    """Periodic device health evaluator — all rules."""
    async with async_session() as session:
        try:
            from app.services.device_health_scheduler import evaluate_all_rules
            await evaluate_all_rules(session)
        except Exception as e:
            logger.error(f"Device health evaluation error: {e}")
            await session.rollback()


async def expire_stale_checkins_job():
    """Background job: expire pending check-ins older than 5 min."""
    async with async_session() as session:
        try:
            from app.services.checkin_service import expire_stale_checkins
            count = await expire_stale_checkins(session)
            if count > 0:
                logger.info(f"Expired {count} stale check-ins")
        except Exception as e:
            logger.error(f"Check-in expiry job error: {e}")


async def expire_stale_sessions_job():
    """Background job: mark stale/expired journey sessions."""
    async with async_session() as session:
        try:
            from app.services.guardian_mode_engine import expire_stale_sessions
            result = await expire_stale_sessions(session)
            await session.commit()
        except Exception as e:
            logger.error(f"Session lifecycle job error: {e}")


async def detect_stale_location_heartbeats_job():
    """Report enrolled protected phones that stopped sending real fixes."""
    async with async_session() as session:
        try:
            from app.services.location_availability import (
                detect_stale_location_heartbeats,
            )
            count = await detect_stale_location_heartbeats(session)
            if count:
                logger.info("Marked %s protected location heartbeat(s) stale", count)
        except Exception as e:
            logger.error(f"Location heartbeat watchdog error: {e}")



def start_scheduler():
    if not scheduler.running:
        # Every interval job here gets `coalesce=True` +
        # `misfire_grace_time=30`. Rationale:
        #   • These fire on the same minute boundary, so when one
        #     runs long the others get "was missed by 1-3s" warnings
        #     even though the delay is harmless.
        #   • coalesce=True: if multiple fires queued up during a
        #     stall, run ONCE (what we actually want — not catch-up
        #     spam).
        #   • misfire_grace_time=30s: 30s is well under the shortest
        #     interval (60s), so we never confuse "delayed by 5s"
        #     with "genuinely failing".
        scheduler.add_job(
            check_and_escalate_incidents,
            'interval',
            seconds=settings.escalation_check_interval,
            id='escalation_check',
            replace_existing=True,
            max_instances=1, coalesce=True, misfire_grace_time=30,
        )
        scheduler.add_job(
            check_device_health,
            'interval',
            seconds=300,  # every 5 minutes
            id='device_health_check',
            replace_existing=True,
            max_instances=1, coalesce=True, misfire_grace_time=60,
        )
        scheduler.add_job(
            expire_stale_checkins_job,
            'interval',
            seconds=60,
            id='checkin_expiry',
            replace_existing=True,
            max_instances=1, coalesce=True, misfire_grace_time=30,
        )
        scheduler.add_job(
            expire_stale_sessions_job,
            'interval',
            seconds=60,
            id='session_lifecycle',
            replace_existing=True,
            max_instances=1, coalesce=True, misfire_grace_time=30,
        )
        scheduler.add_job(
            detect_stale_location_heartbeats_job,
            'interval',
            seconds=60,
            id='location_heartbeat_watchdog',
            replace_existing=True,
            max_instances=1, coalesce=True, misfire_grace_time=30,
        )
        scheduler.start()
        logger.info(f"Escalation scheduler started - checking every {settings.escalation_check_interval}s")
        logger.info("Device health scheduler started - checking every 300s")
        logger.info("Check-in expiry scheduler started - checking every 60s")
        logger.info("Session lifecycle scheduler started - checking every 60s")
        logger.info("Location heartbeat watchdog started - checking every 60s")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Escalation scheduler stopped")
