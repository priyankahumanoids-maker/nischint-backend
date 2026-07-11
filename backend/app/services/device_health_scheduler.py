# Device Health Scheduler — Generic Rule Engine (DB-backed configs)
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import text, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incident import Incident, DEFAULT_ESCALATION_MINUTES
from app.models.senior import Senior
from app.services.incident_events import log_event
from app.services.event_broadcaster import broadcaster, serialize_for_sse
from app.services.rule_config_loader import get_rule_config

logger = logging.getLogger(__name__)


# ── Generic Helpers ──

async def _check_idempotency(session, device_id, incident_type):
    """Return True if an open incident of this type already exists."""
    return (await session.execute(
        select(Incident).where(and_(
            Incident.device_id == device_id,
            Incident.incident_type == incident_type,
            Incident.status == "open",
        ))
    )).scalar_one_or_none() is not None


async def _check_cooldown(session, device_id, incident_type, cooldown_cutoff):
    """Return True if a recently resolved incident exists within cooldown."""
    return (await session.execute(
        select(Incident).where(and_(
            Incident.device_id == device_id,
            Incident.incident_type == incident_type,
            Incident.status == "resolved",
            Incident.resolved_at > cooldown_cutoff,
        ))
    )).scalar_one_or_none() is not None


async def _create_health_incident(session, device_id, senior_id, incident_type, severity, event_type, metadata):
    """Create incident, log event, broadcast SSE. Returns the Incident."""
    incident = Incident(
        senior_id=senior_id,
        device_id=device_id,
        incident_type=incident_type,
        severity=severity,
        escalation_minutes=DEFAULT_ESCALATION_MINUTES.get(severity, 60),
    )
    session.add(incident)
    await session.flush()
    await log_event(session, incident.id, event_type, metadata=metadata)

    senior = (await session.execute(
        select(Senior).where(Senior.id == senior_id)
    )).scalar_one_or_none()
    if senior:
        data = serialize_for_sse({
            "id": incident.id, "senior_id": incident.senior_id,
            "device_id": incident.device_id, "incident_type": incident.incident_type,
            "severity": incident.severity, "status": incident.status,
            "escalated": incident.escalated, "escalation_level": incident.escalation_level,
            "created_at": incident.created_at,
        })
        await broadcaster.broadcast_incident_created(str(senior.guardian_id), data)
    return incident


async def _auto_resolve(session, incident_type, recovery_event_type, check_fn):
    """
    Generic auto-resolve: for each open incident of `incident_type`,
    call `check_fn(session, inc)` which returns (should_resolve: bool, metadata: dict).
    """
    open_incidents = (await session.execute(
        select(Incident).where(and_(
            Incident.incident_type == incident_type,
            Incident.status == "open",
        ))
    )).scalars().all()

    resolved = 0
    for inc in open_incidents:
        should_resolve, meta = await check_fn(session, inc)
        if not should_resolve:
            continue

        inc.status = "resolved"
        inc.resolved_at = datetime.now(timezone.utc)
        await session.flush()
        await log_event(session, inc.id, recovery_event_type, metadata=meta)
        resolved += 1

        senior = (await session.execute(
            select(Senior).where(Senior.id == inc.senior_id)
        )).scalar_one_or_none()
        if senior:
            data = serialize_for_sse({
                "id": inc.id, "senior_id": inc.senior_id,
                "device_id": inc.device_id, "incident_type": inc.incident_type,
                "severity": inc.severity, "status": inc.status,
                "resolved_at": inc.resolved_at, "created_at": inc.created_at,
            })
            await broadcaster.broadcast_incident_updated(str(senior.guardian_id), data)

    if resolved:
        await session.commit()
        logger.info(f"{incident_type} recovery: {resolved} incident(s) resolved")
    return resolved


# ── Rule 1: Low Battery ──

async def evaluate_low_battery(session: AsyncSession):
    """Detect sustained low battery and auto-resolve on recovery."""
    cfg = await get_rule_config(session, "low_battery")
    if not cfg.enabled:
        return 0

    now = datetime.now(timezone.utc)
    t = cfg.threshold_json
    threshold = t.get("battery_percent", 20)
    sustain_minutes = t.get("sustain_minutes", 10)
    recovery_buffer = t.get("recovery_buffer", 5)
    sustain_cutoff = now - timedelta(minutes=sustain_minutes)
    cooldown_cutoff = now - timedelta(minutes=cfg.cooldown_minutes)

    rows = (await session.execute(text("""
        WITH recent AS (
            SELECT t.device_id,
                   (ARRAY_AGG((t.metric_value->>'battery_level')::float ORDER BY t.created_at DESC))[1] AS latest,
                   MIN((t.metric_value->>'battery_level')::float) AS min_val,
                   COUNT(*) AS cnt
            FROM telemetries t
            WHERE t.metric_type = 'heartbeat' AND t.created_at >= :cutoff
              AND (t.metric_value->>'battery_level') IS NOT NULL
            GROUP BY t.device_id
        )
        SELECT r.device_id, r.latest, r.min_val, r.cnt, d.device_identifier, d.senior_id
        FROM recent r JOIN devices d ON d.id = r.device_id
        WHERE r.latest < :threshold AND r.min_val < :threshold AND r.cnt >= 2
    """), {"cutoff": sustain_cutoff, "threshold": threshold})).fetchall()

    created = 0
    for r in rows:
        if await _check_idempotency(session, r.device_id, "low_battery"):
            continue
        if await _check_cooldown(session, r.device_id, "low_battery", cooldown_cutoff):
            continue

        await _create_health_incident(session, r.device_id, r.senior_id, "low_battery", cfg.severity,
            "low_battery_detected", {
                "device_identifier": r.device_identifier,
                "latest_battery": r.latest, "min_battery": r.min_val,
                "threshold": threshold, "sustain_minutes": sustain_minutes,
            })
        created += 1
        logger.warning(f">>> LOW BATTERY: {r.device_identifier} (latest={r.latest}%, threshold={threshold}%)")

    if created:
        await session.commit()

    # Auto-resolve
    recovery_threshold = threshold + recovery_buffer

    async def _check_battery_recovery(sess, inc):
        row = (await sess.execute(text("""
            SELECT (t.metric_value->>'battery_level')::float AS val
            FROM telemetries t WHERE t.device_id = :did AND t.metric_type = 'heartbeat'
              AND (t.metric_value->>'battery_level') IS NOT NULL
            ORDER BY t.created_at DESC LIMIT 1
        """), {"did": inc.device_id})).fetchone()
        if row and row.val is not None and row.val >= recovery_threshold:
            return True, {"recovery_threshold": recovery_threshold, "latest_battery": row.val}
        return False, {}

    await _auto_resolve(session, "low_battery", "low_battery_recovered", _check_battery_recovery)
    return created


# ── Rule 2: Signal Degradation ──

async def evaluate_signal_degradation(session: AsyncSession):
    """Detect sustained poor signal strength and auto-resolve on recovery."""
    cfg = await get_rule_config(session, "signal_degradation")
    if not cfg.enabled:
        return 0

    now = datetime.now(timezone.utc)
    t = cfg.threshold_json
    threshold = t.get("signal_threshold", -80)
    sustain_minutes = t.get("sustain_minutes", 10)
    recovery_buffer_dbm = t.get("recovery_buffer_dbm", 5)
    sustain_cutoff = now - timedelta(minutes=sustain_minutes)
    cooldown_cutoff = now - timedelta(minutes=cfg.cooldown_minutes)

    rows = (await session.execute(text("""
        WITH recent AS (
            SELECT t.device_id,
                   (ARRAY_AGG((t.metric_value->>'signal_strength')::float ORDER BY t.created_at DESC))[1] AS latest,
                   MAX((t.metric_value->>'signal_strength')::float) AS max_val,
                   COUNT(*) AS cnt
            FROM telemetries t
            WHERE t.metric_type = 'heartbeat' AND t.created_at >= :cutoff
              AND (t.metric_value->>'signal_strength') IS NOT NULL
            GROUP BY t.device_id
        )
        SELECT r.device_id, r.latest, r.max_val, r.cnt, d.device_identifier, d.senior_id
        FROM recent r JOIN devices d ON d.id = r.device_id
        WHERE r.latest < :threshold AND r.max_val < :threshold AND r.cnt >= 2
    """), {"cutoff": sustain_cutoff, "threshold": threshold})).fetchall()

    created = 0
    for r in rows:
        if await _check_idempotency(session, r.device_id, "signal_degradation"):
            continue
        if await _check_cooldown(session, r.device_id, "signal_degradation", cooldown_cutoff):
            continue

        await _create_health_incident(session, r.device_id, r.senior_id, "signal_degradation", cfg.severity,
            "signal_degradation_detected", {
                "device_identifier": r.device_identifier,
                "latest_signal": r.latest, "max_signal": r.max_val,
                "threshold_dbm": threshold, "sustain_minutes": sustain_minutes,
            })
        created += 1
        logger.warning(f">>> SIGNAL DEGRADATION: {r.device_identifier} (latest={r.latest}dBm, threshold={threshold}dBm)")

    if created:
        await session.commit()

    # Auto-resolve: signal improved above threshold + buffer
    recovery_threshold = threshold + recovery_buffer_dbm

    async def _check_signal_recovery(sess, inc):
        row = (await sess.execute(text("""
            SELECT (t.metric_value->>'signal_strength')::float AS val
            FROM telemetries t WHERE t.device_id = :did AND t.metric_type = 'heartbeat'
              AND (t.metric_value->>'signal_strength') IS NOT NULL
            ORDER BY t.created_at DESC LIMIT 1
        """), {"did": inc.device_id})).fetchone()
        if row and row.val is not None and row.val >= recovery_threshold:
            return True, {"recovery_threshold": recovery_threshold, "latest_signal": row.val}
        return False, {}

    await _auto_resolve(session, "signal_degradation", "signal_degradation_recovered", _check_signal_recovery)
    return created


# ── Rule 3: Reboot Anomaly ──

async def evaluate_reboot_anomaly(session: AsyncSession):
    """Detect excessive device reboots (heartbeat gaps suggesting restarts)."""
    cfg = await get_rule_config(session, "reboot_anomaly")
    if not cfg.enabled:
        return 0

    now = datetime.now(timezone.utc)
    t = cfg.threshold_json
    gap_minutes = t.get("gap_minutes", 3)
    max_reboots = t.get("gap_count", 3)
    window_minutes = t.get("window_minutes", 60)
    window_cutoff = now - timedelta(minutes=window_minutes)
    cooldown_cutoff = now - timedelta(minutes=cfg.cooldown_minutes)

    rows = (await session.execute(text("""
        WITH heartbeats AS (
            SELECT t.device_id, t.created_at,
                   LAG(t.created_at) OVER (PARTITION BY t.device_id ORDER BY t.created_at) AS prev_ts
            FROM telemetries t
            WHERE t.metric_type = 'heartbeat' AND t.created_at >= :cutoff
        ),
        gaps AS (
            SELECT device_id, COUNT(*) AS reboot_count
            FROM heartbeats
            WHERE prev_ts IS NOT NULL
              AND EXTRACT(EPOCH FROM (created_at - prev_ts)) > :gap_seconds
            GROUP BY device_id
        )
        SELECT g.device_id, g.reboot_count, d.device_identifier, d.senior_id
        FROM gaps g JOIN devices d ON d.id = g.device_id
        WHERE g.reboot_count >= :max_reboots
    """), {"cutoff": window_cutoff, "max_reboots": max_reboots, "gap_seconds": gap_minutes * 60})).fetchall()

    created = 0
    for r in rows:
        if await _check_idempotency(session, r.device_id, "reboot_anomaly"):
            continue
        if await _check_cooldown(session, r.device_id, "reboot_anomaly", cooldown_cutoff):
            continue

        await _create_health_incident(session, r.device_id, r.senior_id, "reboot_anomaly", cfg.severity,
            "reboot_anomaly_detected", {
                "device_identifier": r.device_identifier,
                "reboot_count": r.reboot_count,
                "window_minutes": window_minutes,
                "max_allowed": max_reboots,
            })
        created += 1
        logger.warning(f">>> REBOOT ANOMALY: {r.device_identifier} ({r.reboot_count} reboots in {window_minutes}min)")

    if created:
        await session.commit()

    # Reboot anomaly auto-resolves after cooldown naturally (no active recovery check)
    return created


# ── Main Entry Point ──

async def evaluate_all_rules(session: AsyncSession):
    """Run all device health rules. Called by the scheduler."""
    total = 0
    total += await evaluate_low_battery(session)
    total += await evaluate_signal_degradation(session)
    total += await evaluate_reboot_anomaly(session)
    return total
