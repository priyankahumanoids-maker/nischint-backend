# Operator Router - Admin/Operator-only endpoints
import json
import logging
import uuid as uuid_mod
from typing import Optional
from uuid import UUID
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, and_, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db_session
from app.core.roles import require_role
from app.models.incident import Incident
from app.models.notification_job import NotificationJob
from app.models.user import User
from app.schemas.incident import IncidentResponse

router = APIRouter(prefix="/operator", tags=["Operator"])
logger = logging.getLogger(__name__)


@router.get("/incidents")
async def get_all_incidents(
    status: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    escalated: Optional[bool] = Query(None),
    escalation_level: Optional[int] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Get ALL incidents across all guardians with enriched data. Operator/Admin only."""
    from app.models.senior import Senior
    from app.models.device import Device

    conditions = []
    if status:
        conditions.append(Incident.status == status)
    if severity:
        conditions.append(Incident.severity == severity)
    if escalated is not None:
        conditions.append(Incident.escalated == escalated)
    if escalation_level is not None:
        conditions.append(Incident.escalation_level == escalation_level)

    stmt = (
        select(Incident, Senior.full_name.label("senior_name"), Senior.guardian_id, Device.device_identifier)
        .join(Senior, Incident.senior_id == Senior.id, isouter=True)
        .join(Device, Incident.device_id == Device.id, isouter=True)
        .order_by(Incident.created_at.desc())
        .limit(limit)
    )
    if conditions:
        stmt = stmt.where(and_(*conditions))

    result = await session.execute(stmt)
    rows = result.all()

    return [
        {
            "id": str(inc.id),
            "senior_id": str(inc.senior_id),
            "user_id": str(guardian_id) if guardian_id else None,
            "device_id": str(inc.device_id),
            "incident_type": inc.incident_type,
            "severity": inc.severity,
            "status": inc.status,
            "escalation_minutes": inc.escalation_minutes,
            "escalated": inc.escalated,
            "escalated_at": inc.escalated_at.isoformat() if inc.escalated_at else None,
            "created_at": inc.created_at.isoformat() if inc.created_at else None,
            "resolved_at": inc.resolved_at.isoformat() if inc.resolved_at else None,
            "acknowledged_at": inc.acknowledged_at.isoformat() if inc.acknowledged_at else None,
            "escalation_level": inc.escalation_level,
            "assigned_to_user_id": str(inc.assigned_to_user_id) if inc.assigned_to_user_id else None,
            "assigned_at": inc.assigned_at.isoformat() if inc.assigned_at else None,
            "is_test": inc.is_test,
            "senior_name": senior_name or "Unknown",
            "device_identifier": device_identifier or "Unknown",
        }
        for inc, senior_name, guardian_id, device_identifier in rows
    ]


@router.get("/incidents/{incident_id}/notification-jobs")
async def get_incident_notification_jobs_operator(
    incident_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Get all notification jobs for any incident. Operator/Admin only."""
    result = await session.execute(
        select(NotificationJob)
        .where(NotificationJob.incident_id == incident_id)
        .order_by(NotificationJob.created_at.asc())
    )
    jobs = result.scalars().all()
    return [
        {
            "id": str(j.id),
            "channel": j.channel,
            "recipient": j.recipient,
            "status": j.status,
            "attempts": j.attempts,
            "idempotency_key": j.idempotency_key,
            "last_attempt_at": j.last_attempt_at.isoformat() if j.last_attempt_at else None,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "escalation_level": j.payload.get("escalation_level") if j.payload else None,
        }
        for j in jobs
    ]


@router.get("/stats")
async def get_operator_stats(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Get platform-wide stats. Operator/Admin only."""
    from sqlalchemy import func, text
    from app.models.senior import Senior
    from app.models.device import Device

    # Exclude test incidents from operational stats
    real_filter = Incident.is_test.is_(False)
    total_incidents = (await session.execute(select(func.count(Incident.id)).where(real_filter))).scalar() or 0
    open_incidents = (await session.execute(select(func.count(Incident.id)).where(and_(Incident.status == "open", real_filter)))).scalar() or 0
    escalated_incidents = (await session.execute(select(func.count(Incident.id)).where(and_(Incident.escalated == True, real_filter)))).scalar() or 0
    test_incidents = (await session.execute(select(func.count(Incident.id)).where(Incident.is_test.is_(True)))).scalar() or 0
    total_seniors = (await session.execute(select(func.count(Senior.id)))).scalar() or 0
    total_devices = (await session.execute(select(func.count(Device.id)))).scalar() or 0
    total_guardians = (await session.execute(select(func.count(User.id)).where(User.role == "guardian"))).scalar() or 0

    return {
        "total_incidents": total_incidents,
        "open_incidents": open_incidents,
        "escalated_incidents": escalated_incidents,
        "test_incidents": test_incidents,
        "total_seniors": total_seniors,
        "total_devices": total_devices,
        "total_guardians": total_guardians,
    }


@router.get("/false-alarm-metrics")
async def get_false_alarm_metrics(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Get false alarm rate and metrics. Operator/Admin only."""
    from sqlalchemy import func

    real_filter = Incident.is_test.is_(False)
    total = (await session.execute(select(func.count(Incident.id)).where(real_filter))).scalar() or 0
    false_alarms = (await session.execute(
        select(func.count(Incident.id)).where(and_(Incident.status == "false_alarm", real_filter))
    )).scalar() or 0
    escalated_false = (await session.execute(
        select(func.count(Incident.id)).where(and_(
            Incident.status == "false_alarm",
            Incident.escalation_level > 1,
            real_filter,
        ))
    )).scalar() or 0

    rate = (false_alarms / total * 100) if total > 0 else 0

    return {
        "total_incidents": total,
        "false_alarms": false_alarms,
        "false_alarm_rate_percent": round(rate, 2),
        "escalated_false_alarms": escalated_false,
    }


# ── Notification Job Control Tower ──


@router.get("/notification-jobs/stats")
async def notification_job_stats(
    window_minutes: Optional[int] = Query(None, ge=1, le=10080, description="Time window in minutes. Omit for all-time."),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Notification delivery health stats. Operator/Admin only."""
    from datetime import datetime, timezone, timedelta

    conditions = []
    if window_minutes:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
        conditions.append(NotificationJob.created_at >= cutoff)

    where = and_(*conditions) if conditions else True

    # Totals by status
    totals_q = (
        select(NotificationJob.status, func.count())
        .where(where)
        .group_by(NotificationJob.status)
    )
    totals_rows = (await session.execute(totals_q)).all()
    totals = {row[0]: row[1] for row in totals_rows}

    # Breakdown by channel × status
    channel_q = (
        select(NotificationJob.channel, NotificationJob.status, func.count())
        .where(where)
        .group_by(NotificationJob.channel, NotificationJob.status)
    )
    channel_rows = (await session.execute(channel_q)).all()
    by_channel: dict = {}
    for ch, st, cnt in channel_rows:
        by_channel.setdefault(ch, {})[st] = cnt

    sent_count = totals.get("sent", 0)
    throughput = round(sent_count / window_minutes, 2) if window_minutes and window_minutes > 0 else None

    return {
        "window_minutes": window_minutes,
        "totals": totals,
        "by_channel": by_channel,
        "throughput_per_minute": throughput,
    }

def _job_to_dict(job: NotificationJob) -> dict:
    return {
        "id": str(job.id),
        "incident_id": str(job.incident_id) if job.incident_id else None,
        "channel": job.channel,
        "recipient": job.recipient,
        "payload": job.payload,
        "status": job.status,
        "attempts": job.attempts,
        "idempotency_key": job.idempotency_key,
        "last_attempt_at": job.last_attempt_at.isoformat() if job.last_attempt_at else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }


@router.get("/notification-jobs")
async def list_notification_jobs(
    status: Optional[str] = Query(None, description="Filter by status: pending, retrying, sent, dead_letter, cancelled"),
    channel: Optional[str] = Query(None, description="Filter by channel: email, sms, push"),
    incident_id: Optional[UUID] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """List notification jobs with filters. Operator/Admin only."""
    conditions = []
    if status:
        conditions.append(NotificationJob.status == status)
    if channel:
        conditions.append(NotificationJob.channel == channel)
    if incident_id:
        conditions.append(NotificationJob.incident_id == incident_id)

    stmt = select(NotificationJob).order_by(NotificationJob.created_at.desc())
    if conditions:
        stmt = stmt.where(and_(*conditions))
    stmt = stmt.offset(offset).limit(limit)

    count_stmt = select(func.count(NotificationJob.id))
    if conditions:
        count_stmt = count_stmt.where(and_(*conditions))

    result, total = await session.execute(stmt), await session.execute(count_stmt)
    jobs = result.scalars().all()

    return {
        "total": total.scalar() or 0,
        "jobs": [_job_to_dict(j) for j in jobs],
    }


@router.post("/notification-jobs/{job_id}/retry")
async def retry_notification_job(
    job_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Reset a failed/dead_letter job to pending for re-delivery. Operator/Admin only."""
    job = (await session.execute(
        select(NotificationJob).where(NotificationJob.id == job_id)
    )).scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Notification job not found")

    if job.status not in ("dead_letter", "failed", "retrying"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot retry job with status '{job.status}'. Only dead_letter/failed/retrying jobs can be retried.",
        )

    job.status = "pending"
    job.attempts = 0
    job.last_attempt_at = None
    await session.commit()

    return {"message": "Job reset to pending", "job": _job_to_dict(job)}


@router.post("/notification-jobs/{job_id}/cancel")
async def cancel_notification_job(
    job_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Cancel a pending/retrying job so the worker skips it. Operator/Admin only."""
    job = (await session.execute(
        select(NotificationJob).where(NotificationJob.id == job_id)
    )).scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Notification job not found")

    if job.status in ("sent", "cancelled"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel job with status '{job.status}'.",
        )

    job.status = "cancelled"
    await session.commit()

    return {"message": "Job cancelled", "job": _job_to_dict(job)}


@router.get("/device-health")
async def get_all_device_health(
    window_hours: int = Query(24, ge=1, le=168),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Get device health metrics across all devices. Operator/Admin only."""
    from app.services.device_health_service import get_all_devices_health
    return await get_all_devices_health(session, window_hours)


@router.get("/device-anomalies")
async def get_device_anomalies(
    hours: int = Query(24, ge=1, le=168),
    include_simulated: bool = Query(False, description="Include simulated anomalies"),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Get recent anomaly data across all devices with baselines. Operator/Admin only."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    from app.models.device_anomaly import DeviceAnomaly
    from app.models.device_baseline import DeviceBaseline
    from app.models.device import Device
    from app.models.senior import Senior

    # Fetch recent anomalies — exclude simulated by default
    anomaly_query = (
        select(DeviceAnomaly, Device.device_identifier, Senior.full_name.label("senior_name"))
        .join(Device, DeviceAnomaly.device_id == Device.id)
        .join(Senior, Device.senior_id == Senior.id)
        .where(DeviceAnomaly.created_at >= cutoff)
    )
    if not include_simulated:
        anomaly_query = anomaly_query.where(DeviceAnomaly.is_simulated == False)  # noqa: E712
    anomaly_rows = (await session.execute(
        anomaly_query.order_by(DeviceAnomaly.created_at.desc()).limit(100)
    )).all()

    anomalies = [
        {
            "device_identifier": r.device_identifier,
            "senior_name": r.senior_name,
            "metric": r.DeviceAnomaly.metric,
            "score": r.DeviceAnomaly.score,
            "reason_json": r.DeviceAnomaly.reason_json,
            "window_start": r.DeviceAnomaly.window_start.isoformat(),
            "created_at": r.DeviceAnomaly.created_at.isoformat(),
            "is_simulated": r.DeviceAnomaly.is_simulated,
            "simulation_run_id": r.DeviceAnomaly.simulation_run_id,
        }
        for r in anomaly_rows
    ]

    # Fetch all baselines
    baseline_rows = (await session.execute(
        select(DeviceBaseline, Device.device_identifier)
        .join(Device, DeviceBaseline.device_id == Device.id)
        .order_by(Device.device_identifier)
    )).all()

    baselines = [
        {
            "device_identifier": r.device_identifier,
            "metric": r.DeviceBaseline.metric,
            "expected_value": r.DeviceBaseline.expected_value,
            "lower_band": r.DeviceBaseline.lower_band,
            "upper_band": r.DeviceBaseline.upper_band,
            "window_minutes": r.DeviceBaseline.window_minutes,
            "updated_at": r.DeviceBaseline.updated_at.isoformat(),
        }
        for r in baseline_rows
    ]

    return {"anomalies": anomalies, "baselines": baselines}


# ── Health Rule Management ──

from app.models.rule_config import DeviceHealthRuleConfig
from app.models.rule_audit import DeviceHealthRuleAuditLog
from app.services.rule_config_cache import rule_config_cache
from app.services.rule_simulator import SIMULATORS, EVALUATION_WINDOWS
from app.schemas.rule import (
    RuleUpdateRequest, RuleToggleRequest, RuleResponse,
    RuleSimulationRequest, RuleSimulationResponse,
    KNOWN_RULE_NAMES, validate_threshold_json,
)


def _rule_row_to_response(row: DeviceHealthRuleConfig) -> dict:
    return {
        "rule_name": row.rule_name,
        "enabled": row.enabled,
        "threshold_json": row.threshold_json,
        "cooldown_minutes": row.cooldown_minutes,
        "severity": row.severity,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _rule_snapshot(row: DeviceHealthRuleConfig) -> dict:
    return {
        "enabled": row.enabled,
        "threshold_json": row.threshold_json,
        "cooldown_minutes": row.cooldown_minutes,
        "severity": row.severity,
    }


@router.get("/health-rules", response_model=list[RuleResponse])
async def list_health_rules(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """List all device health rule configurations."""
    rows = (await session.execute(
        select(DeviceHealthRuleConfig).order_by(DeviceHealthRuleConfig.rule_name)
    )).scalars().all()
    return [_rule_row_to_response(r) for r in rows]


@router.put("/health-rules/{rule_name}", response_model=RuleResponse)
async def update_health_rule(
    rule_name: str,
    payload: RuleUpdateRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Update a health rule's config. Atomic: update + audit → commit → invalidate cache."""
    if rule_name not in KNOWN_RULE_NAMES:
        raise HTTPException(status_code=404, detail=f"Unknown rule '{rule_name}'. Valid rules: {', '.join(sorted(KNOWN_RULE_NAMES))}")

    row = (await session.execute(
        select(DeviceHealthRuleConfig)
        .where(DeviceHealthRuleConfig.rule_name == rule_name)
    )).scalar_one_or_none()

    if not row:
        raise HTTPException(status_code=404, detail=f"Rule '{rule_name}' not found in database")

    # Snapshot before mutation
    old_snapshot = _rule_snapshot(row)

    # Validate threshold_json keys if provided
    if payload.threshold_json is not None:
        try:
            validate_threshold_json(rule_name, payload.threshold_json)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        row.threshold_json = payload.threshold_json

    if payload.enabled is not None:
        row.enabled = payload.enabled
    if payload.cooldown_minutes is not None:
        row.cooldown_minutes = payload.cooldown_minutes
    if payload.severity is not None:
        row.severity = payload.severity

    # Snapshot after mutation
    new_snapshot = _rule_snapshot(row)

    # Audit log — same transaction
    session.add(DeviceHealthRuleAuditLog(
        rule_name=rule_name,
        changed_by=user.id,
        changed_by_name=user.full_name or user.email,
        change_type="update",
        old_config=old_snapshot,
        new_config=new_snapshot,
        ip_address=request.client.host if request.client else None,
    ))

    # Atomic commit: update + audit
    await session.commit()
    await session.refresh(row)
    rule_config_cache.invalidate(rule_name)

    return _rule_row_to_response(row)


@router.patch("/health-rules/{rule_name}/toggle", response_model=RuleResponse)
async def toggle_health_rule(
    rule_name: str,
    payload: RuleToggleRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Enable or disable a health rule. Atomic: toggle + audit → commit → invalidate cache."""
    if rule_name not in KNOWN_RULE_NAMES:
        raise HTTPException(status_code=404, detail=f"Unknown rule '{rule_name}'. Valid rules: {', '.join(sorted(KNOWN_RULE_NAMES))}")

    row = (await session.execute(
        select(DeviceHealthRuleConfig)
        .where(DeviceHealthRuleConfig.rule_name == rule_name)
    )).scalar_one_or_none()

    if not row:
        raise HTTPException(status_code=404, detail=f"Rule '{rule_name}' not found in database")

    old_snapshot = _rule_snapshot(row)
    row.enabled = payload.enabled
    new_snapshot = _rule_snapshot(row)

    session.add(DeviceHealthRuleAuditLog(
        rule_name=rule_name,
        changed_by=user.id,
        changed_by_name=user.full_name or user.email,
        change_type="toggle",
        old_config=old_snapshot,
        new_config=new_snapshot,
        ip_address=request.client.host if request.client else None,
    ))

    await session.commit()
    await session.refresh(row)
    rule_config_cache.invalidate(rule_name)

    return _rule_row_to_response(row)


@router.get("/health-rules/{rule_name}/audit-log")
async def get_rule_audit_log(
    rule_name: str,
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Get audit log for a specific rule. Operator/Admin only."""
    if rule_name not in KNOWN_RULE_NAMES:
        raise HTTPException(status_code=404, detail=f"Unknown rule '{rule_name}'. Valid rules: {', '.join(sorted(KNOWN_RULE_NAMES))}")

    rows = (await session.execute(
        select(DeviceHealthRuleAuditLog)
        .where(DeviceHealthRuleAuditLog.rule_name == rule_name)
        .order_by(DeviceHealthRuleAuditLog.created_at.desc())
        .limit(limit)
    )).scalars().all()

    return [
        {
            "rule_name": r.rule_name,
            "changed_by_name": r.changed_by_name,
            "change_type": r.change_type,
            "old_config": r.old_config,
            "new_config": r.new_config,
            "ip_address": r.ip_address,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.post("/health-rules/{rule_name}/simulate", response_model=RuleSimulationResponse)
async def simulate_rule(
    rule_name: str,
    payload: RuleSimulationRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Dry-run a rule config against live telemetry. Pure read-only — no DB writes."""
    if rule_name not in KNOWN_RULE_NAMES:
        raise HTTPException(status_code=404, detail=f"Unknown rule '{rule_name}'. Valid rules: {', '.join(sorted(KNOWN_RULE_NAMES))}")

    try:
        validate_threshold_json(rule_name, payload.threshold_json)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    from app.models.device import Device
    total_devices = (await session.execute(select(func.count(Device.id)))).scalar() or 0

    if not payload.enabled:
        return {
            "rule_name": rule_name,
            "simulated_severity": payload.severity,
            "matched_devices_count": 0,
            "total_devices_count": total_devices,
            "evaluation_window_minutes": EVALUATION_WINDOWS[rule_name](payload.threshold_json),
            "would_escalate": False,
            "matched_devices": [],
        }

    simulator = SIMULATORS[rule_name]
    matched = await simulator(session, payload.threshold_json)

    return {
        "rule_name": rule_name,
        "simulated_severity": payload.severity,
        "matched_devices_count": len(matched),
        "total_devices_count": total_devices,
        "evaluation_window_minutes": EVALUATION_WINDOWS[rule_name](payload.threshold_json),
        "would_escalate": len(matched) > 0,
        "matched_devices": matched,
    }


# ── Synthetic Telemetry Seeder ──

from app.schemas.seed import (
    HeartbeatSeedRequest, HeartbeatSeedResponse,
    FleetSimulationRequest, FleetSimulationResponse,
    DeviceSeedResult, AnomalyHistogramBucket,
)


def _compute_metric_value(
    pattern,
    elapsed_minutes: float,
    rng,
    noise_pct: float,
) -> float:
    """Compute a metric's value at a given time offset, applying normal/anomaly rates + noise."""
    if pattern.anomaly and elapsed_minutes >= pattern.anomaly.start_at_minute:
        # Normal phase up to anomaly start, then anomaly rate after
        normal_duration = pattern.anomaly.start_at_minute
        anomaly_duration = elapsed_minutes - normal_duration
        value = (
            pattern.start_value
            + pattern.normal_rate_per_minute * normal_duration
            + pattern.anomaly.rate_per_minute * anomaly_duration
        )
    else:
        value = pattern.start_value + pattern.normal_rate_per_minute * elapsed_minutes

    # Add noise
    if noise_pct > 0 and value != 0:
        noise = rng.uniform(-noise_pct / 100, noise_pct / 100) * abs(value)
        value += noise

    return round(value, 2)


def _is_in_gap(elapsed_minutes: float, gap_patterns) -> bool:
    """Check if a given time offset falls within any gap window."""
    for gap in gap_patterns:
        gap_end = gap.start_at_minute + gap.duration_minutes
        if gap.start_at_minute <= elapsed_minutes < gap_end:
            return True
    return False


@router.post("/simulate/heartbeat-seed", response_model=HeartbeatSeedResponse)
async def seed_heartbeat_telemetry(
    payload: HeartbeatSeedRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """
    Generate synthetic heartbeat telemetry for testing the adaptive anomaly detection system.

    - Creates backdated telemetry records for the specified device
    - All records marked with is_simulated=True + unique simulation_run_id
    - Supports multi-metric patterns (battery_level, signal_strength)
    - Supports gap patterns for reboot anomaly testing
    - Optionally triggers baseline recalculation + anomaly detection (isolated to this run)
    - Deterministic mode via random_seed for regression testing
    """
    import random as stdlib_random

    from app.models.device import Device
    from app.models.telemetry import Telemetry

    # Deterministic RNG
    rng = stdlib_random.Random(payload.random_seed)

    # Generate unique simulation run ID
    run_id = f"seed-{uuid_mod.uuid4().hex[:12]}"

    # Resolve device
    device = (await session.execute(
        select(Device).where(Device.device_identifier == payload.device_identifier)
    )).scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail=f"Device '{payload.device_identifier}' not found")

    # Validate anomaly start times are within duration
    for mp in payload.metric_patterns:
        if mp.anomaly and mp.anomaly.start_at_minute >= payload.duration_minutes:
            raise HTTPException(
                status_code=422,
                detail=f"Anomaly start_at_minute ({mp.anomaly.start_at_minute}) for metric '{mp.metric}' "
                        f"must be < duration_minutes ({payload.duration_minutes})",
            )
    for gp in payload.gap_patterns:
        if gp.start_at_minute >= payload.duration_minutes:
            raise HTTPException(
                status_code=422,
                detail=f"Gap start_at_minute ({gp.start_at_minute}) must be < duration_minutes ({payload.duration_minutes})",
            )

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=payload.duration_minutes)
    step = timedelta(seconds=payload.interval_seconds)

    records_created = 0
    records_skipped = 0
    latest_ts = window_start

    # Generate telemetry records
    current_ts = window_start
    while current_ts <= now:
        elapsed = (current_ts - window_start).total_seconds() / 60.0

        # Check gap patterns
        if _is_in_gap(elapsed, payload.gap_patterns):
            records_skipped += 1
            current_ts += step
            continue

        # Build metric_value dict from all patterns
        metric_value = {}
        for pattern in payload.metric_patterns:
            val = _compute_metric_value(pattern, elapsed, rng, payload.noise_percent)
            # Clamp battery_level to 0-100
            if pattern.metric == "battery_level":
                val = max(0.0, min(100.0, val))
            # Clamp signal_strength to -120..0
            elif pattern.metric == "signal_strength":
                val = max(-120.0, min(0.0, val))
            metric_value[pattern.metric] = val

        session.add(Telemetry(
            device_id=device.id,
            metric_type="heartbeat",
            metric_value=metric_value,
            created_at=current_ts,
            is_simulated=True,
            simulation_run_id=run_id,
        ))
        records_created += 1
        latest_ts = current_ts
        current_ts += step

    # Update device last_seen
    device.last_seen = latest_ts
    device.status = "online"

    await session.flush()

    # Trigger evaluation if requested (scoped to this simulation run)
    baselines_updated = None
    anomalies_detected = None
    if payload.trigger_evaluation:
        from app.services.baseline_scheduler import _update_baselines, _detect_battery_slope_anomalies, _detect_signal_anomalies, _detect_combined_anomalies
        try:
            bat_count, slope_count, sig_count = await _update_baselines(session, simulation_run_id=run_id)
            baselines_updated = {"battery_level": bat_count, "battery_slope": slope_count, "signal_strength": sig_count}
        except Exception as e:
            import traceback
            logger.error(f"Baseline update failed during seed: {traceback.format_exc()}")
            baselines_updated = {"error": str(e)}

        try:
            result = await _detect_battery_slope_anomalies(session, simulation_run_id=run_id)
            bat_anom = result[0] if isinstance(result, tuple) else result
        except Exception:
            import traceback
            logger.error(f"Battery anomaly detection failed during seed: {traceback.format_exc()}")
            bat_anom = 0

        try:
            result = await _detect_signal_anomalies(session, simulation_run_id=run_id)
            sig_anom = result[0] if isinstance(result, tuple) else result
        except Exception:
            import traceback
            logger.error(f"Signal anomaly detection failed during seed: {traceback.format_exc()}")
            sig_anom = 0

        try:
            result = await _detect_combined_anomalies(session, simulation_run_id=run_id)
            combined_anom = result[0] if isinstance(result, tuple) else result
        except Exception:
            import traceback
            logger.error(f"Combined anomaly detection failed during seed: {traceback.format_exc()}")
            combined_anom = 0

        anomalies_detected = bat_anom + sig_anom + combined_anom

    # Persist simulation run history — ATOMIC: telemetry + evaluation + history in one commit
    from app.models.simulation_run import SimulationRun
    response_data = {
        "simulation_run_id": run_id,
        "device_identifier": payload.device_identifier,
        "records_created": records_created,
        "records_skipped_by_gaps": records_skipped,
        "duration_minutes": payload.duration_minutes,
        "time_range_start": window_start.isoformat(),
        "time_range_end": latest_ts.isoformat(),
        "metrics_seeded": [p.metric for p in payload.metric_patterns],
        "anomaly_evaluation_triggered": payload.trigger_evaluation,
        "baselines_updated": baselines_updated,
        "anomalies_detected": anomalies_detected,
    }
    session.add(SimulationRun(
        simulation_run_id=run_id,
        run_type="single",
        config_json=payload.model_dump(mode="json"),
        summary_json=response_data,
        total_devices_affected=1,
        anomalies_triggered=anomalies_detected if isinstance(anomalies_detected, int) and anomalies_detected >= 0 else 0,
        scheduler_execution_ms=None,
        db_write_volume=records_created,
        executed_by_name=user.email,
    ))
    await session.commit()

    return HeartbeatSeedResponse(**response_data)


# ── Fleet Simulation ──

def _seed_device_telemetry(
    device_id,
    metric_patterns,
    gap_patterns,
    duration_minutes: int,
    interval_seconds: int,
    rng,
    noise_percent: float,
    run_id: str,
    now: datetime,
):
    """Generate telemetry records for a single device. Returns (records, skipped, latest_ts)."""
    from app.models.telemetry import Telemetry

    window_start = now - timedelta(minutes=duration_minutes)
    step = timedelta(seconds=interval_seconds)
    records = []
    skipped = 0
    latest_ts = window_start
    current_ts = window_start

    while current_ts <= now:
        elapsed = (current_ts - window_start).total_seconds() / 60.0
        if _is_in_gap(elapsed, gap_patterns):
            skipped += 1
            current_ts += step
            continue

        metric_value = {}
        for pattern in metric_patterns:
            val = _compute_metric_value(pattern, elapsed, rng, noise_percent)
            if pattern.metric == "battery_level":
                val = max(0.0, min(100.0, val))
            elif pattern.metric == "signal_strength":
                val = max(-120.0, min(0.0, val))
            metric_value[pattern.metric] = val

        records.append(Telemetry(
            device_id=device_id,
            metric_type="heartbeat",
            metric_value=metric_value,
            created_at=current_ts,
            is_simulated=True,
            simulation_run_id=run_id,
        ))
        latest_ts = current_ts
        current_ts += step

    return records, skipped, latest_ts


@router.post("/simulate/fleet", response_model=FleetSimulationResponse)
async def fleet_simulation(
    payload: FleetSimulationRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """
    Fleet-wide simulation: seed synthetic telemetry across multiple devices simultaneously.

    - All records tagged with shared simulation_run_id + is_simulated=True
    - Isolated from production baselines and anomaly history
    - Rich summary: device count, anomalies, execution time, DB write volume, score histogram
    """
    import random as stdlib_random
    import time

    from app.models.device import Device

    rng = stdlib_random.Random(payload.random_seed)
    run_id = f"fleet-{uuid_mod.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=payload.duration_minutes)

    # Resolve all devices upfront
    identifiers = [dp.device_identifier for dp in payload.device_patterns]
    devices = (await session.execute(
        select(Device).where(Device.device_identifier.in_(identifiers))
    )).scalars().all()
    device_map = {d.device_identifier: d for d in devices}

    missing = set(identifiers) - set(device_map.keys())
    if missing:
        raise HTTPException(status_code=404, detail=f"Devices not found: {', '.join(sorted(missing))}")

    # Validate anomaly/gap start times
    for dp in payload.device_patterns:
        for mp in dp.metric_patterns:
            if mp.anomaly and mp.anomaly.start_at_minute >= payload.duration_minutes:
                raise HTTPException(
                    status_code=422,
                    detail=f"Device '{dp.device_identifier}': anomaly start_at_minute ({mp.anomaly.start_at_minute}) "
                            f"must be < duration_minutes ({payload.duration_minutes})",
                )
        for gp in dp.gap_patterns:
            if gp.start_at_minute >= payload.duration_minutes:
                raise HTTPException(
                    status_code=422,
                    detail=f"Device '{dp.device_identifier}': gap start_at_minute ({gp.start_at_minute}) "
                            f"must be < duration_minutes ({payload.duration_minutes})",
                )

    # Seed telemetry for all devices
    total_records = 0
    total_skipped = 0
    per_device_results = []

    for dp in payload.device_patterns:
        device = device_map[dp.device_identifier]
        records, skipped, latest_ts = _seed_device_telemetry(
            device_id=device.id,
            metric_patterns=dp.metric_patterns,
            gap_patterns=dp.gap_patterns,
            duration_minutes=payload.duration_minutes,
            interval_seconds=payload.interval_seconds,
            rng=rng,
            noise_percent=payload.noise_percent,
            run_id=run_id,
            now=now,
        )
        for rec in records:
            session.add(rec)
        total_records += len(records)
        total_skipped += skipped
        per_device_results.append(DeviceSeedResult(
            device_identifier=dp.device_identifier,
            records_created=len(records),
            records_skipped_by_gaps=skipped,
            metrics_seeded=[p.metric for p in dp.metric_patterns],
        ))

    await session.flush()

    # Trigger evaluation scoped to this simulation run
    baselines_updated = None
    anomalies_triggered = 0
    anomaly_details = []
    scheduler_ms = None
    db_write_volume = total_records  # start with telemetry rows

    if payload.trigger_evaluation:
        from app.services.baseline_scheduler import _update_baselines, _detect_battery_slope_anomalies, _detect_signal_anomalies, _detect_combined_anomalies
        t0 = time.monotonic()

        try:
            bat_count, slope_count, sig_count = await _update_baselines(session, simulation_run_id=run_id)
            baselines_updated = {"battery_level": bat_count, "battery_slope": slope_count, "signal_strength": sig_count}
        except Exception:
            logger.exception("Fleet sim: baseline update failed")
            baselines_updated = {"error": "baseline computation failed"}

        try:
            result = await _detect_battery_slope_anomalies(session, simulation_run_id=run_id)
            if isinstance(result, tuple):
                bat_anom, bat_details = result
                anomalies_triggered += bat_anom
                anomaly_details.extend(bat_details)
            else:
                anomalies_triggered += result
        except Exception:
            logger.exception("Fleet sim: battery anomaly detection failed")

        try:
            result = await _detect_signal_anomalies(session, simulation_run_id=run_id)
            if isinstance(result, tuple):
                sig_anom, sig_details = result
                anomalies_triggered += sig_anom
                anomaly_details.extend(sig_details)
            else:
                anomalies_triggered += result
        except Exception:
            logger.exception("Fleet sim: signal anomaly detection failed")

        try:
            result = await _detect_combined_anomalies(session, simulation_run_id=run_id)
            if isinstance(result, tuple):
                comb_anom, comb_details = result
                anomalies_triggered += comb_anom
                anomaly_details.extend(comb_details)
            else:
                anomalies_triggered += result
        except Exception:
            logger.exception("Fleet sim: combined anomaly detection failed")

        scheduler_ms = int((time.monotonic() - t0) * 1000)
        db_write_volume += anomalies_triggered

    # Build anomaly score histogram
    score_buckets = [0, 0, 0, 0]  # 0-25, 25-50, 50-75, 75-100
    for ad in anomaly_details:
        s = ad.get("score", 0)
        if s < 25:
            score_buckets[0] += 1
        elif s < 50:
            score_buckets[1] += 1
        elif s < 75:
            score_buckets[2] += 1
        else:
            score_buckets[3] += 1

    histogram = [
        AnomalyHistogramBucket(range_label="0-25", count=score_buckets[0]),
        AnomalyHistogramBucket(range_label="25-50", count=score_buckets[1]),
        AnomalyHistogramBucket(range_label="50-75", count=score_buckets[2]),
        AnomalyHistogramBucket(range_label="75-100", count=score_buckets[3]),
    ]

    # Build FULL raw response (store everything for future replay/comparison)
    response_data = {
        "simulation_run_id": run_id,
        "total_devices_affected": len(payload.device_patterns),
        "total_records_created": total_records,
        "total_records_skipped": total_skipped,
        "duration_minutes": payload.duration_minutes,
        "time_range_start": window_start.isoformat(),
        "time_range_end": now.isoformat(),
        "db_write_volume": db_write_volume,
        "scheduler_execution_ms": scheduler_ms,
        "anomalies_triggered": anomalies_triggered,
        "baselines_updated": baselines_updated,
        "anomaly_distribution": [b.model_dump() for b in histogram],
        "per_device_results": [d.model_dump() for d in per_device_results],
        "anomaly_details": anomaly_details,
        "is_simulated": True,
    }

    # ATOMIC: telemetry + evaluation + history record in a single commit
    from app.models.simulation_run import SimulationRun
    session.add(SimulationRun(
        simulation_run_id=run_id,
        run_type="fleet",
        config_json=payload.model_dump(mode="json"),
        summary_json=response_data,
        total_devices_affected=len(payload.device_patterns),
        anomalies_triggered=anomalies_triggered,
        scheduler_execution_ms=scheduler_ms,
        db_write_volume=db_write_volume,
        executed_by_name=user.email,
    ))
    await session.commit()

    return FleetSimulationResponse(
        simulation_run_id=run_id,
        total_devices_affected=len(payload.device_patterns),
        total_records_created=total_records,
        total_records_skipped=total_skipped,
        duration_minutes=payload.duration_minutes,
        time_range_start=window_start.isoformat(),
        time_range_end=now.isoformat(),
        db_write_volume=db_write_volume,
        scheduler_execution_ms=scheduler_ms,
        anomalies_triggered=anomalies_triggered,
        baselines_updated=baselines_updated,
        anomaly_distribution=histogram,
        per_device_results=per_device_results,
        anomaly_details=anomaly_details,
    )


# ── Behavioral Scenario Simulation ──

from app.schemas.behavior_sim import (
    BehaviorSimRequest, BehaviorSimResponse, BehaviorScenario,
    ScenarioResult, TimelineStep,
    SCENARIO_TYPES, SCENARIO_DESCRIPTIONS,
)

def _generate_behavior_score_at(minute: int, scenario: BehaviorScenario) -> float:
    """
    Generate a behavior_score at a given minute for a scenario.
    Ramp-up curve: score rises from ~0.2 to peak intensity over ramp_minutes,
    then holds at peak (with mild oscillation) for the rest of the duration.
    """
    import math
    ramp = max(scenario.ramp_minutes, 1)
    intensity = scenario.intensity

    if minute <= 0:
        return 0.15  # baseline noise
    elif minute <= ramp:
        # Sigmoid-like ramp: smooth S-curve from 0.15 to intensity
        progress = minute / ramp
        score = 0.15 + (intensity - 0.15) * (1 / (1 + math.exp(-8 * (progress - 0.5))))
    else:
        # Post-ramp: hold at intensity with small oscillation
        phase = (minute - ramp) / max(scenario.duration_minutes - ramp, 1)
        oscillation = 0.02 * math.sin(phase * math.pi * 4)
        score = min(1.0, intensity + oscillation)

    return round(max(0.0, min(1.0, score)), 3)


def _anomaly_type_for_scenario(scenario_type: str) -> str:
    """Map scenario type to behavior anomaly type."""
    mapping = {
        "prolonged_inactivity": "extended_inactivity",
        "movement_drop": "movement_drop",
        "routine_disruption": "routine_break",
        "location_wandering": "unusual_movement",
        "route_deviation": "unusual_movement",
    }
    return mapping.get(scenario_type, "routine_break")


def _escalation_tier_for_score(score: float, tiers: dict) -> str | None:
    """Map combined risk score to escalation tier."""
    for range_str, tier in sorted(tiers.items(), reverse=True):
        parts = range_str.split("-")
        if len(parts) == 2:
            low, high = float(parts[0]), float(parts[1])
            if low <= score <= high:
                return tier
    return None


@router.post("/simulate/behavior", response_model=BehaviorSimResponse)
async def simulate_behavior_scenarios(
    payload: BehaviorSimRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """
    Behavioral Scenario Simulation — generate synthetic behavior anomalies and
    evaluate their impact through the combined risk + escalation engine.

    Flow:
    1. Validate scenarios & resolve devices
    2. Generate behavior_anomalies (is_simulated=true) per scenario timeline step
    3. Evaluate combined risk score at each step (battery + signal + behavior)
    4. Determine escalation tier at each step
    5. Return full escalation timeline per scenario
    """
    import time
    import json as json_mod
    from app.models.device import Device
    from app.models.simulation_run import SimulationRun

    t0 = time.monotonic()

    # Validate scenario types
    for s in payload.scenarios:
        if s.scenario_type not in SCENARIO_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid scenario_type '{s.scenario_type}'. Must be one of: {SCENARIO_TYPES}",
            )
        if s.ramp_minutes > s.duration_minutes:
            raise HTTPException(
                status_code=422,
                detail=f"ramp_minutes ({s.ramp_minutes}) must be <= duration_minutes ({s.duration_minutes})",
            )

    # Resolve devices
    identifiers = list({s.device_identifier for s in payload.scenarios})
    devices = (await session.execute(
        select(Device).where(Device.device_identifier.in_(identifiers))
    )).scalars().all()
    device_map = {d.device_identifier: d for d in devices}

    missing = set(identifiers) - set(device_map.keys())
    if missing:
        raise HTTPException(status_code=404, detail=f"Devices not found: {', '.join(sorted(missing))}")

    run_id = f"behavior-{uuid_mod.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)
    step_minutes = payload.step_interval_minutes

    # Load combined_anomaly config for escalation evaluation
    config_row = (await session.execute(text("""
        SELECT threshold_json FROM device_health_rule_configs
        WHERE rule_name = 'combined_anomaly' AND enabled = true
    """))).fetchone()

    combined_cfg = config_row.threshold_json if config_row else {}
    w_bat = combined_cfg.get("weight_battery", 0.5)
    w_sig = combined_cfg.get("weight_signal", 0.3)
    w_beh = combined_cfg.get("weight_behavior", 0.2)
    trigger_threshold = combined_cfg.get("trigger_threshold", 60)
    correlation_bonus = combined_cfg.get("correlation_bonus", 10)
    escalation_tiers = combined_cfg.get("escalation_tiers", {"60-75": "L1", "75-90": "L2", "90-100": "L3"})

    # Fetch existing battery + signal anomaly scores for each device (last hour)
    existing_scores = {}
    anomaly_rows = (await session.execute(text("""
        SELECT da.device_id, da.metric, da.score
        FROM device_anomalies da
        WHERE da.created_at >= :lookback AND da.is_simulated = false
          AND da.metric IN ('battery_slope', 'signal_strength')
        ORDER BY da.device_id, da.metric, da.created_at DESC
    """), {"lookback": now - timedelta(hours=1)})).fetchall()

    for r in anomaly_rows:
        did = str(r.device_id)
        if did not in existing_scores:
            existing_scores[did] = {"battery": None, "signal": None}
        entry = existing_scores[did]
        if r.metric == "battery_slope" and entry["battery"] is None:
            entry["battery"] = float(r.score)
        elif r.metric == "signal_strength" and entry["signal"] is None:
            entry["signal"] = float(r.score)

    total_behavior_anomalies = 0
    total_escalations = 0
    scenario_results = []

    for scenario in payload.scenarios:
        device = device_map[scenario.device_identifier]
        device_id = device.id
        anomaly_type = _anomaly_type_for_scenario(scenario.scenario_type)

        timeline = []
        anomalies_created = 0
        peak_behavior = 0.0
        peak_combined = 0.0
        final_tier = None
        time_to_first_escalation = None

        for minute in range(0, scenario.duration_minutes + 1, step_minutes):
            behavior_score = _generate_behavior_score_at(minute, scenario)
            peak_behavior = max(peak_behavior, behavior_score)

            # Write simulated behavior anomaly
            reason = f"[Simulated] {SCENARIO_DESCRIPTIONS.get(scenario.scenario_type, '')} — minute {minute}/{scenario.duration_minutes}"
            await session.execute(text("""
                INSERT INTO behavior_anomalies (id, device_id, behavior_score, anomaly_type, reason, is_simulated, created_at)
                VALUES (gen_random_uuid(), :device_id, :score, :anomaly_type, :reason, true, :ts)
            """), {
                "device_id": device_id,
                "score": behavior_score,
                "anomaly_type": anomaly_type,
                "reason": reason,
                "ts": now + timedelta(minutes=minute),
            })
            anomalies_created += 1

            # Evaluate combined risk score
            combined_score = None
            tier = None
            escalation_reason = None

            if payload.trigger_escalation:
                did_str = str(device_id)
                bat = existing_scores.get(did_str, {}).get("battery") or 0.0
                sig = existing_scores.get(did_str, {}).get("signal") or 0.0
                beh_normalized = behavior_score * 100  # 0-1 → 0-100

                combined = bat * w_bat + sig * w_sig + beh_normalized * w_beh

                # Correlation bonus when 2+ metrics active
                active_count = sum(1 for v in [bat, sig, beh_normalized] if v > 0)
                if active_count >= 2:
                    combined += correlation_bonus

                combined = round(min(combined, 100.0), 1)
                combined_score = combined
                peak_combined = max(peak_combined, combined)

                if combined > trigger_threshold:
                    tier = _escalation_tier_for_score(combined, escalation_tiers)
                    final_tier = tier
                    if tier and time_to_first_escalation is None:
                        time_to_first_escalation = minute
                    escalation_reason = f"Combined={combined:.1f} (bat={bat:.0f}×{w_bat}+sig={sig:.0f}×{w_sig}+beh={beh_normalized:.0f}×{w_beh}{f'+{correlation_bonus}corr' if active_count >= 2 else ''}) → {tier}"

            timeline.append(TimelineStep(
                minute=minute,
                behavior_score=behavior_score,
                anomaly_type=anomaly_type,
                combined_risk_score=combined_score,
                escalation_tier=tier,
                escalation_reason=escalation_reason,
            ))

        total_behavior_anomalies += anomalies_created
        if final_tier:
            total_escalations += 1

        scenario_results.append(ScenarioResult(
            device_identifier=scenario.device_identifier,
            scenario_type=scenario.scenario_type,
            scenario_description=SCENARIO_DESCRIPTIONS.get(scenario.scenario_type, ""),
            duration_minutes=scenario.duration_minutes,
            intensity=scenario.intensity,
            behavior_anomalies_created=anomalies_created,
            timeline=timeline,
            peak_behavior_score=round(peak_behavior, 3),
            peak_combined_score=round(peak_combined, 1) if payload.trigger_escalation else None,
            final_escalation_tier=final_tier,
            time_to_first_escalation_minutes=time_to_first_escalation,
        ))

    # Save simulation run to history
    scheduler_ms = int((time.monotonic() - t0) * 1000)
    response_data = {
        "simulation_run_id": run_id,
        "total_scenarios": len(payload.scenarios),
        "total_behavior_anomalies": total_behavior_anomalies,
        "total_escalations": total_escalations,
        "scenario_results": [sr.model_dump() for sr in scenario_results],
        "is_simulated": True,
    }

    session.add(SimulationRun(
        simulation_run_id=run_id,
        run_type="behavior",
        config_json=payload.model_dump(mode="json"),
        summary_json=response_data,
        total_devices_affected=len(identifiers),
        anomalies_triggered=total_behavior_anomalies,
        scheduler_execution_ms=scheduler_ms,
        db_write_volume=total_behavior_anomalies,
        executed_by_name=user.email,
    ))
    await session.commit()

    return BehaviorSimResponse(
        simulation_run_id=run_id,
        total_scenarios=len(payload.scenarios),
        total_behavior_anomalies=total_behavior_anomalies,
        total_escalations=total_escalations,
        scenario_results=scenario_results,
    )


# ── Simulation Comparison Engine ──

from app.schemas.simulation import BatteryCompareRequest, BatteryCompareResponse


@router.post("/simulate/compare/battery", response_model=BatteryCompareResponse)
async def compare_battery_configs(
    payload: BatteryCompareRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """
    Compare two battery threshold configs against live telemetry.
    Pure read-only — no DB writes, no audit logs, no side effects.
    Returns a diff report: who matches A, who matches B, newly flagged, no longer flagged.
    """
    from app.services.simulation_compare import compare_battery_configs as _compare
    result = await _compare(
        session,
        config_a=payload.config_a.model_dump(),
        config_b=payload.config_b.model_dump(),
        min_heartbeats=payload.min_heartbeats,
    )
    return result


@router.post("/health-rules/{rule_name}/revert/{created_at:path}")
async def revert_rule(
    rule_name: str,
    created_at: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Revert a rule to the old_config of a specific audit entry. Atomic + auditable."""
    if rule_name not in KNOWN_RULE_NAMES:
        raise HTTPException(status_code=404, detail=f"Unknown rule '{rule_name}'. Valid rules: {', '.join(sorted(KNOWN_RULE_NAMES))}")

    # Parse timestamp
    try:
        target_ts = datetime.fromisoformat(created_at)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid timestamp format. Use ISO 8601.")

    # Fetch rule
    row = (await session.execute(
        select(DeviceHealthRuleConfig).where(DeviceHealthRuleConfig.rule_name == rule_name)
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail=f"Rule '{rule_name}' not found in database")

    # Fetch audit entry
    audit = (await session.execute(
        select(DeviceHealthRuleAuditLog).where(
            DeviceHealthRuleAuditLog.rule_name == rule_name,
            DeviceHealthRuleAuditLog.created_at == target_ts,
        )
    )).scalar_one_or_none()
    if not audit:
        raise HTTPException(status_code=404, detail="Audit entry not found for this timestamp")

    target_config = audit.old_config
    required_keys = {"enabled", "threshold_json", "cooldown_minutes", "severity"}
    if not required_keys.issubset(target_config.keys()):
        raise HTTPException(status_code=422, detail="Audit snapshot is malformed — missing required keys")

    # Snapshot current state
    current_snapshot = _rule_snapshot(row)

    # Apply revert
    row.enabled = target_config["enabled"]
    row.threshold_json = target_config["threshold_json"]
    row.cooldown_minutes = target_config["cooldown_minutes"]
    row.severity = target_config["severity"]

    # Audit the revert
    session.add(DeviceHealthRuleAuditLog(
        rule_name=rule_name,
        changed_by=user.id,
        changed_by_name=user.full_name or user.email,
        change_type="revert",
        old_config=current_snapshot,
        new_config=target_config,
        ip_address=request.client.host if request.client else None,
    ))

    await session.commit()
    await session.refresh(row)
    rule_config_cache.invalidate(rule_name)

    return {
        "rule_name": rule_name,
        "status": "reverted",
        "reverted_to_timestamp": created_at,
    }


# ── Simulation History (Immutable Research Log) ──

from app.models.simulation_run import SimulationRun as SimulationRunModel


@router.get("/simulations")
async def list_simulation_runs(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    run_type: Optional[str] = Query(None, description="Filter by run_type: single | fleet"),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """
    Paginated, immutable simulation history. Read-only research log.
    Sorted by created_at DESC. No edit, no delete, no revert.
    """
    conditions = []
    if run_type:
        conditions.append(SimulationRunModel.run_type == run_type)

    where_clause = and_(*conditions) if conditions else True

    # Count
    total_count = (await session.execute(
        select(func.count(SimulationRunModel.id)).where(where_clause)
    )).scalar() or 0

    # Paginated fetch
    offset = (page - 1) * limit
    rows = (await session.execute(
        select(SimulationRunModel)
        .where(where_clause)
        .order_by(SimulationRunModel.created_at.desc())
        .offset(offset)
        .limit(limit)
    )).scalars().all()

    items = [
        {
            "id": str(r.id),
            "simulation_run_id": r.simulation_run_id,
            "run_type": r.run_type,
            "total_devices_affected": r.total_devices_affected,
            "anomalies_triggered": r.anomalies_triggered,
            "scheduler_execution_ms": r.scheduler_execution_ms,
            "db_write_volume": r.db_write_volume,
            "executed_by_name": r.executed_by_name,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]

    return {
        "items": items,
        "total_count": total_count,
        "page": page,
        "limit": limit,
    }


@router.get("/simulations/{simulation_run_id}")
async def get_simulation_run_detail(
    simulation_run_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """
    Full detail view for a single simulation run. Immutable — read-only.
    Returns config_json + summary_json (full raw data, never trimmed).
    """
    row = (await session.execute(
        select(SimulationRunModel)
        .where(SimulationRunModel.simulation_run_id == simulation_run_id)
    )).scalar_one_or_none()

    if not row:
        raise HTTPException(status_code=404, detail=f"Simulation run '{simulation_run_id}' not found")

    return {
        "id": str(row.id),
        "simulation_run_id": row.simulation_run_id,
        "run_type": row.run_type,
        "config_json": row.config_json,
        "summary_json": row.summary_json,
        "total_devices_affected": row.total_devices_affected,
        "anomalies_triggered": row.anomalies_triggered,
        "scheduler_execution_ms": row.scheduler_execution_ms,
        "db_write_volume": row.db_write_volume,
        "executed_by_name": row.executed_by_name,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


# ── Instability Escalation (Diagnostic) ──

@router.post("/escalation/evaluate-instability")
async def evaluate_instability(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """
    Manually trigger the instability escalation evaluation (Gate 2 + Gate 3).
    Only considers production (non-simulated) multi_metric anomalies.
    """
    from app.services.baseline_scheduler import _evaluate_instability_escalation
    incidents_created = await _evaluate_instability_escalation(session)
    return {
        "incidents_created": incidents_created,
        "message": f"Evaluated multi_metric persistence. {incidents_created} instability incident(s) created.",
    }


@router.post("/escalation/evaluate-recovery")
async def evaluate_recovery(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """
    Manually trigger the instability recovery evaluation.
    Checks if any open device_instability incidents can be auto-resolved.
    """
    from app.services.baseline_scheduler import _evaluate_instability_recovery
    resolved = await _evaluate_instability_recovery(session)
    return {
        "incidents_resolved": resolved,
        "message": f"Recovery evaluation complete. {resolved} instability incident(s) resolved.",
    }


# ── Escalation Analytics (KPI Dashboard) ──

@router.get("/escalation-analytics")
async def get_escalation_analytics(
    window_minutes: int = Query(1440, ge=15, le=10080, description="Analytics window in minutes (default 24h)"),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """
    Returns escalation + recovery KPIs for the Safety Ops dashboard.
    Single CTE-based query. Incident-centric windowing.
    """
    analytics_query = text("""
    WITH
    -- All incidents in window (non-test)
    window_incidents AS (
        SELECT i.*, d.device_identifier,
               s.full_name AS senior_name,
               u.full_name AS guardian_name
        FROM incidents i
        LEFT JOIN devices d ON d.id = i.device_id
        LEFT JOIN seniors s ON s.id = i.senior_id
        LEFT JOIN users u ON u.id = s.guardian_id
        WHERE i.created_at >= NOW() - make_interval(mins => :window_minutes)
          AND i.is_test = false
    ),

    -- Volume metrics
    volume AS (
        SELECT
            COUNT(*) AS total_incidents,
            COUNT(*) FILTER (WHERE status = 'open') AS open_incidents,
            COUNT(*) FILTER (WHERE incident_type = 'device_instability') AS instability_total,
            COUNT(*) FILTER (WHERE escalation_level = 1) AS l1_count,
            COUNT(*) FILTER (WHERE escalation_level = 2) AS l2_count,
            COUNT(*) FILTER (WHERE escalation_level >= 3) AS l3_count
        FROM window_incidents
    ),

    -- Timing metrics (incident-centric, exclude artificial timestamps)
    timings AS (
        SELECT
            AVG(EXTRACT(EPOCH FROM (acknowledged_at - created_at)))
                FILTER (WHERE acknowledged_at IS NOT NULL
                    AND EXTRACT(EPOCH FROM (acknowledged_at - created_at)) > 0) AS avg_ack_s,
            AVG(EXTRACT(EPOCH FROM (resolved_at - created_at)))
                FILTER (WHERE resolved_at IS NOT NULL AND status = 'resolved'
                    AND EXTRACT(EPOCH FROM (resolved_at - created_at)) > 0) AS avg_resolve_s
        FROM window_incidents
    ),

    -- First escalation timing from events
    first_esc AS (
        SELECT AVG(esc_delay) AS avg_first_esc_s
        FROM (
            SELECT MIN(EXTRACT(EPOCH FROM (ie.created_at - wi.created_at))) AS esc_delay
            FROM window_incidents wi
            JOIN incident_events ie ON ie.incident_id = wi.id
            WHERE ie.event_type IN ('escalation_l1', 'escalation_l2', 'escalation_l3')
            GROUP BY wi.id
        ) sub
    ),

    -- Device instability recovery breakdown
    instability_recovery AS (
        SELECT
            COUNT(*) FILTER (
                WHERE wi.incident_type = 'device_instability'
                  AND wi.status = 'resolved'
                  AND EXISTS (
                    SELECT 1 FROM incident_events ie2
                    WHERE ie2.incident_id = wi.id
                      AND ie2.event_type = 'device_instability_recovered'
                  )
            ) AS auto_recovered,
            COUNT(*) FILTER (
                WHERE wi.incident_type = 'device_instability'
                  AND wi.status = 'resolved'
                  AND NOT EXISTS (
                    SELECT 1 FROM incident_events ie2
                    WHERE ie2.incident_id = wi.id
                      AND ie2.event_type = 'device_instability_recovered'
                  )
            ) AS manual_resolved
        FROM window_incidents wi
    ),

    -- Recovery path counts (Case A vs Case B)
    recovery_paths AS (
        SELECT
            COUNT(*) FILTER (
                WHERE ie.event_metadata->>'case' = 'A'
            ) AS case_a_count,
            COUNT(*) FILTER (
                WHERE ie.event_metadata->>'case' = 'B'
            ) AS case_b_count
        FROM window_incidents wi
        JOIN incident_events ie ON ie.incident_id = wi.id
        WHERE ie.event_type = 'device_instability_recovered'
          AND wi.incident_type = 'device_instability'
    ),

    -- Repeat device instability rate
    repeat_devices AS (
        SELECT
            COUNT(*) FILTER (WHERE inst_count > 1) AS devices_with_repeat,
            COUNT(*) AS devices_with_instability
        FROM (
            SELECT device_id, COUNT(*) AS inst_count
            FROM window_incidents
            WHERE incident_type = 'device_instability'
            GROUP BY device_id
        ) sub
    ),

    -- Cooldown blocks (only reason='cooldown')
    cooldown_blocks AS (
        SELECT COUNT(*) AS cooldown_count
        FROM incident_events ie
        JOIN window_incidents wi ON wi.id = ie.incident_id
        WHERE ie.event_type = 'device_instability_escalation_blocked'
          AND ie.event_metadata->>'reason' = 'cooldown'
    ),

    -- Top 10 devices by instability
    top_devices AS (
        SELECT
            device_identifier,
            senior_name,
            guardian_name,
            COUNT(*) AS instability_count,
            ROUND(AVG(
                COALESCE(
                    (SELECT (ie.event_metadata->>'max_score')::float
                     FROM incident_events ie
                     WHERE ie.incident_id = wi.id
                       AND ie.event_type = 'device_instability_detected'
                     LIMIT 1),
                    0
                )
            )::numeric, 1) AS avg_score
        FROM window_incidents wi
        WHERE incident_type = 'device_instability'
        GROUP BY device_identifier, senior_name, guardian_name
        ORDER BY instability_count DESC, avg_score DESC
        LIMIT 10
    )

    SELECT
        v.total_incidents, v.open_incidents,
        v.l1_count, v.l2_count, v.l3_count,
        v.instability_total,
        t.avg_ack_s, t.avg_resolve_s,
        fe.avg_first_esc_s,
        ir.auto_recovered, ir.manual_resolved,
        rp.case_a_count, rp.case_b_count,
        rd.devices_with_repeat, rd.devices_with_instability,
        cb.cooldown_count,
        COALESCE(json_agg(json_build_object(
            'device_identifier', td.device_identifier,
            'senior_name', td.senior_name,
            'guardian_name', td.guardian_name,
            'instability_count', td.instability_count,
            'avg_score', td.avg_score
        )) FILTER (WHERE td.device_identifier IS NOT NULL), '[]'::json) AS top_devices
    FROM volume v
    CROSS JOIN timings t
    CROSS JOIN first_esc fe
    CROSS JOIN instability_recovery ir
    CROSS JOIN recovery_paths rp
    CROSS JOIN repeat_devices rd
    CROSS JOIN cooldown_blocks cb
    LEFT JOIN top_devices td ON true
    GROUP BY
        v.total_incidents, v.open_incidents,
        v.l1_count, v.l2_count, v.l3_count,
        v.instability_total,
        t.avg_ack_s, t.avg_resolve_s,
        fe.avg_first_esc_s,
        ir.auto_recovered, ir.manual_resolved,
        rp.case_a_count, rp.case_b_count,
        rd.devices_with_repeat, rd.devices_with_instability,
        cb.cooldown_count
    """)

    row = (await session.execute(analytics_query, {"window_minutes": window_minutes})).fetchone()

    if not row:
        # Empty system — return zeroed structure
        return _empty_analytics(window_minutes)

    # Compute repeat rate
    devices_with_instability = row.devices_with_instability or 0
    devices_with_repeat = row.devices_with_repeat or 0
    repeat_rate = round((devices_with_repeat / devices_with_instability * 100), 1) if devices_with_instability > 0 else 0.0

    return {
        "window_minutes": window_minutes,
        "total_incidents": row.total_incidents or 0,
        "open_incidents": row.open_incidents or 0,
        "tier_counts": {
            "l1": row.l1_count or 0,
            "l2": row.l2_count or 0,
            "l3": row.l3_count or 0,
        },
        "timings": {
            "avg_time_to_ack_seconds": round(row.avg_ack_s, 1) if row.avg_ack_s else None,
            "avg_time_to_resolve_seconds": round(row.avg_resolve_s, 1) if row.avg_resolve_s else None,
            "avg_time_to_first_escalation_seconds": round(row.avg_first_esc_s, 1) if row.avg_first_esc_s else None,
        },
        "device_instability": {
            "total": row.instability_total or 0,
            "auto_recovered": row.auto_recovered or 0,
            "manual_resolved": row.manual_resolved or 0,
            "recovery_paths": {
                "case_a_no_anomaly_window": row.case_a_count or 0,
                "case_b_clear_cycles_below_hysteresis": row.case_b_count or 0,
            },
            "repeat_device_rate_percent": repeat_rate,
            "cooldown_blocks_count": row.cooldown_count or 0,
        },
        "top_devices_by_instability": row.top_devices if isinstance(row.top_devices, list) else [],
    }


def _empty_analytics(window_minutes: int) -> dict:
    return {
        "window_minutes": window_minutes,
        "total_incidents": 0,
        "open_incidents": 0,
        "tier_counts": {"l1": 0, "l2": 0, "l3": 0},
        "timings": {
            "avg_time_to_ack_seconds": None,
            "avg_time_to_resolve_seconds": None,
            "avg_time_to_first_escalation_seconds": None,
        },
        "device_instability": {
            "total": 0,
            "auto_recovered": 0,
            "manual_resolved": 0,
            "recovery_paths": {
                "case_a_no_anomaly_window": 0,
                "case_b_clear_cycles_below_hysteresis": 0,
            },
            "repeat_device_rate_percent": 0.0,
            "cooldown_blocks_count": 0,
        },
        "top_devices_by_instability": [],
    }


# ── Multi-Metric Simulation Comparison Engine ──

from pydantic import BaseModel, Field


class CombinedAnomalyConfig(BaseModel):
    weight_battery: float = Field(0.5, ge=0, le=1)
    weight_signal: float = Field(0.3, ge=0, le=1)
    weight_behavior: float = Field(0.2, ge=0, le=1)
    trigger_threshold: float = Field(60, ge=0, le=100)
    correlation_bonus: float = Field(10, ge=0, le=50)
    persistence_minutes: float = Field(15, ge=1)
    escalation_tiers: dict = Field(default_factory=lambda: {"60-75": "L1", "75-90": "L2", "90-100": "L3"})


class ComparisonConfigBlock(BaseModel):
    combined_anomaly: CombinedAnomalyConfig


class CompareMultiMetricRequest(BaseModel):
    window_minutes: int = Field(60, ge=5, le=10080)  # up to 7 days
    fleet_scope: str = Field("all", pattern="^(all)$")
    config_a: ComparisonConfigBlock
    config_b: ComparisonConfigBlock
    mode: str = Field("live", pattern="^(live|replay)$")
    start_time: str | None = Field(None)  # ISO format, required for replay
    end_time: str | None = Field(None)    # ISO format, required for replay


def _evaluate_config_in_memory(
    device_scores: dict,
    cfg: CombinedAnomalyConfig,
    persistence_data: dict,
) -> dict:
    """
    Pure in-memory multi-metric evaluation. No DB writes.
    Returns per-device anomaly results + tier mapping.
    """
    from app.services.baseline_scheduler import _map_score_to_tier

    w_bat = cfg.weight_battery
    w_sig = cfg.weight_signal
    w_beh = cfg.weight_behavior
    threshold = cfg.trigger_threshold
    bonus = cfg.correlation_bonus
    persistence_minutes = cfg.persistence_minutes
    tiers = cfg.escalation_tiers

    results = {}  # device_id -> {score, tier, flagged, ...}
    anomaly_count = 0
    instability_count = 0
    tier_counts = {"L1": 0, "L2": 0, "L3": 0}

    for did, data in device_scores.items():
        bat = data["battery_score"] or 0.0
        sig = data["signal_score"] or 0.0
        beh = data.get("behavior_score") or 0.0

        if bat == 0.0 and sig == 0.0 and beh == 0.0:
            results[did] = {"flagged": False, "score": 0, "tier": None,
                            "device_identifier": data["device_identifier"],
                            "would_escalate": False}
            continue

        # Layer 1: Weighted combined score
        combined = bat * w_bat + sig * w_sig + beh * w_beh

        # Layer 2: Correlation bonus when 2+ metrics active
        active_count = sum(1 for v in [bat, sig, beh] if v > 0)
        correlation = active_count >= 2
        if correlation:
            combined += bonus

        combined = round(min(combined, 100.0), 1)

        # Layer 3: Threshold check
        flagged = combined > threshold
        tier = None
        would_escalate = False

        if flagged:
            anomaly_count += 1
            tier = _map_score_to_tier(combined, tiers)

            # Check persistence for escalation
            dev_persistence = persistence_data.get(did, 0.0)
            if dev_persistence >= persistence_minutes and tier:
                would_escalate = True
                instability_count += 1
                if tier in tier_counts:
                    tier_counts[tier] += 1

        results[did] = {
            "flagged": flagged,
            "score": combined,
            "tier": tier,
            "would_escalate": would_escalate,
            "device_identifier": data["device_identifier"],
            "battery_score": bat,
            "signal_score": sig,
            "behavior_score": beh,
            "correlation": correlation,
        }

    return {
        "anomalies": anomaly_count,
        "instability_incidents": instability_count,
        "tier_counts": tier_counts,
        "per_device": results,
    }



@router.get("/devices/{device_id}/metric-trends")
async def get_device_metric_trends(
    device_id: UUID,
    window_minutes: int = Query(60, ge=5, le=10080),
    metrics: str = Query("battery,signal,combined"),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """
    Returns time-series metric trend data for sparkline visualization.
    Aggregates telemetry and anomaly scores into bucketed points (max 120).
    """
    now = datetime.now(timezone.utc)
    lookback = now - timedelta(minutes=window_minutes)
    requested_metrics = [m.strip() for m in metrics.split(",")]

    # Determine bucket size to keep max ~120 points
    total_seconds = window_minutes * 60
    bucket_seconds = max(30, total_seconds // 120)

    points = []

    # 1. Fetch raw telemetry (heartbeat) for battery_level and signal_strength
    telemetry_rows = (await session.execute(text("""
        SELECT
            to_timestamp(FLOOR(EXTRACT(EPOCH FROM created_at) / :bucket) * :bucket) AS bucket_ts,
            AVG((metric_value->>'battery_level')::float) AS avg_battery,
            AVG((metric_value->>'signal_strength')::float) AS avg_signal,
            COUNT(*) AS sample_count
        FROM telemetries
        WHERE device_id = :device_id
          AND metric_type = 'heartbeat'
          AND is_simulated = false
          AND created_at >= :lookback
          AND created_at <= :now
        GROUP BY bucket_ts
        ORDER BY bucket_ts
    """), {
        "device_id": device_id,
        "bucket": bucket_seconds,
        "lookback": lookback,
        "now": now,
    })).fetchall()

    # 2. Fetch anomaly scores (battery_slope, signal_strength, multi_metric)
    anomaly_rows = (await session.execute(text("""
        SELECT
            to_timestamp(FLOOR(EXTRACT(EPOCH FROM created_at) / :bucket) * :bucket) AS bucket_ts,
            metric,
            AVG(score) AS avg_score
        FROM device_anomalies
        WHERE device_id = :device_id
          AND is_simulated = false
          AND created_at >= :lookback
          AND created_at <= :now
          AND metric IN ('battery_slope', 'signal_strength', 'multi_metric')
        GROUP BY bucket_ts, metric
        ORDER BY bucket_ts
    """), {
        "device_id": device_id,
        "bucket": bucket_seconds,
        "lookback": lookback,
        "now": now,
    })).fetchall()

    # 3. Build a timestamp → data map from telemetry
    ts_map: dict = {}
    for r in telemetry_rows:
        ts_key = r.bucket_ts.isoformat() if r.bucket_ts else None
        if not ts_key:
            continue
        ts_map[ts_key] = {
            "timestamp": ts_key,
            "battery_level": round(float(r.avg_battery), 2) if r.avg_battery is not None else None,
            "signal_strength": round(float(r.avg_signal), 2) if r.avg_signal is not None else None,
            "battery_score": None,
            "signal_score": None,
            "combined_score": None,
            "samples": int(r.sample_count),
        }

    # 4. Overlay anomaly scores on the same timestamp buckets
    for r in anomaly_rows:
        ts_key = r.bucket_ts.isoformat() if r.bucket_ts else None
        if not ts_key:
            continue
        if ts_key not in ts_map:
            ts_map[ts_key] = {
                "timestamp": ts_key,
                "battery_level": None,
                "signal_strength": None,
                "battery_score": None,
                "signal_score": None,
                "combined_score": None,
                "samples": 0,
            }
        score_val = round(float(r.avg_score), 2) if r.avg_score is not None else None
        if r.metric == "battery_slope":
            ts_map[ts_key]["battery_score"] = score_val
        elif r.metric == "signal_strength":
            ts_map[ts_key]["signal_score"] = score_val
        elif r.metric == "multi_metric":
            ts_map[ts_key]["combined_score"] = score_val

    # 5. Sort by timestamp, limit to 120 points
    sorted_points = sorted(ts_map.values(), key=lambda p: p["timestamp"])
    if len(sorted_points) > 120:
        # Downsample by taking every Nth point
        step = len(sorted_points) / 120
        sorted_points = [sorted_points[int(i * step)] for i in range(120)]

    return {
        "device_id": str(device_id),
        "window_minutes": window_minutes,
        "bucket_seconds": bucket_seconds,
        "total_points": len(sorted_points),
        "points": sorted_points,
    }



@router.get("/devices/{device_id}/behavior-pattern")
async def get_device_behavior_pattern(
    device_id: UUID,
    window_hours: int = Query(24, ge=1, le=168),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """
    Returns behavioral baseline, recent anomalies, and current risk score for a device.
    """
    now = datetime.now(timezone.utc)
    lookback = now - timedelta(hours=window_hours)
    current_hour = now.hour

    # 1. Get device info
    device_row = (await session.execute(text("""
        SELECT id, device_identifier FROM devices WHERE id = :did
    """), {"did": device_id})).fetchone()

    if not device_row:
        raise HTTPException(status_code=404, detail="Device not found")

    # 2. Get baseline for current hour (SB-02 — via user_signal_baselines
    #    matview helper; was an inline `behavior_baselines` SELECT).
    from app.services.user_signal_baseline_service import (
        get_device_baseline, get_device_baselines_24h,
    )
    current_baseline = await get_device_baseline(
        session, str(device_id), current_hour,
    )

    # 3. Get full 24h baseline profile (matview helper, same source).
    baselines_24h = await get_device_baselines_24h(session, str(device_id))

    baseline_profile = [
        {
            "hour": r["hour_of_day"],
            "avg_movement": r["avg_movement"],
            "avg_location_switch": r["avg_location_switch"],
            "avg_interaction_rate": r["avg_interaction_rate"],
            "sample_count": r["sample_count"],
        }
        for r in baselines_24h
    ]

    # 4. Get recent behavior anomalies
    anomaly_rows = (await session.execute(text("""
        SELECT behavior_score, anomaly_type, reason, created_at
        FROM behavior_anomalies
        WHERE device_id = :did
          AND is_simulated = false
          AND created_at >= :lookback
        ORDER BY created_at DESC
        LIMIT 20
    """), {"did": device_id, "lookback": lookback})).fetchall()

    anomalies = [
        {
            "behavior_score": round(float(r.behavior_score), 3),
            "anomaly_type": r.anomaly_type,
            "reason": r.reason,
            "created_at": r.created_at.isoformat(),
        }
        for r in anomaly_rows
    ]

    # 5. Compute current risk score
    current_risk = 0.0
    risk_status = "normal"
    risk_reason = "No deviations detected"

    if anomalies:
        # Use most recent anomaly score
        current_risk = anomalies[0]["behavior_score"]
        risk_reason = anomalies[0]["reason"]
        if current_risk >= 0.8:
            risk_status = "critical"
        elif current_risk >= 0.6:
            risk_status = "moderate"
        elif current_risk >= 0.3:
            risk_status = "mild"

    # 6. Last heartbeat time
    last_hb_row = (await session.execute(text("""
        SELECT MAX(created_at) AS last_heartbeat FROM telemetries
        WHERE device_id = :did AND metric_type = 'heartbeat' AND is_simulated = false
    """), {"did": device_id})).fetchone()

    last_heartbeat = last_hb_row.last_heartbeat.isoformat() if last_hb_row and last_hb_row.last_heartbeat else None
    inactivity_minutes = None
    if last_hb_row and last_hb_row.last_heartbeat:
        inactivity_minutes = round((now - last_hb_row.last_heartbeat).total_seconds() / 60.0, 1)

    # 7. Twin-awareness context
    twin_row = (await session.execute(text("""
        SELECT confidence_score, wake_hour, sleep_hour, typical_inactivity_max_minutes,
               daily_rhythm, profile_summary
        FROM device_digital_twins WHERE device_id = :did
    """), {"did": device_id})).fetchone()

    twin_aware = None
    if twin_row and twin_row.confidence_score >= 0.15:
        rhythm = twin_row.daily_rhythm or {}
        hour_data = rhythm.get(str(current_hour))
        expected_active = hour_data["expected_active"] if hour_data else None
        twin_aware = {
            "twin_active": True,
            "confidence": round(twin_row.confidence_score, 3),
            "expected_active_now": expected_active,
            "personal_inactivity_max": twin_row.typical_inactivity_max_minutes,
            "personality_tag": (twin_row.profile_summary or {}).get("personality_tag"),
        }

    # Count twin-aware anomalies
    twin_anomaly_count = sum(1 for a in anomalies if "TWIN" in (a.get("reason") or "") or a.get("anomaly_type", "").startswith("twin_"))

    return {
        "device_id": str(device_id),
        "device_identifier": device_row.device_identifier,
        "current_risk": {
            "score": round(current_risk, 3),
            "status": risk_status,
            "reason": risk_reason,
            "twin_aware": twin_aware is not None,
        },
        "last_heartbeat": last_heartbeat,
        "inactivity_minutes": inactivity_minutes,
        "twin_context": twin_aware,
        "current_hour_baseline": {
            "hour": current_hour,
            "avg_movement": current_baseline["avg_movement"] if current_baseline else None,
            "avg_interaction_rate": current_baseline["avg_interaction_rate"] if current_baseline else None,
            "sample_count": current_baseline["sample_count"] if current_baseline else 0,
        } if current_baseline else None,
        "baseline_profile": baseline_profile,
        "recent_anomalies": anomalies,
        "total_anomalies_in_window": len(anomalies),
        "twin_anomaly_count": twin_anomaly_count,
    }


# ── Digital Twin Endpoints ──

@router.get("/devices/{device_id}/digital-twin")
async def get_device_digital_twin(
    device_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """
    Returns the Digital Twin profile for a device.
    The twin is a personalized behavioral model containing wake/sleep rhythm,
    activity windows, movement intervals, and personalized thresholds.
    """
    # Verify device exists
    device_row = (await session.execute(text("""
        SELECT id, device_identifier FROM devices WHERE id = :did
    """), {"did": device_id})).fetchone()
    if not device_row:
        raise HTTPException(status_code=404, detail="Device not found")

    # Fetch twin
    twin = (await session.execute(text("""
        SELECT twin_version, wake_hour, sleep_hour, peak_activity_hour,
               movement_interval_minutes, typical_inactivity_max_minutes,
               daily_rhythm, activity_windows, profile_summary,
               confidence_score, training_data_points, last_trained_at,
               created_at, updated_at
        FROM device_digital_twins WHERE device_id = :did
    """), {"did": device_id})).fetchone()

    if not twin:
        return {
            "device_id": str(device_id),
            "device_identifier": device_row.device_identifier,
            "twin_exists": False,
            "message": "Digital twin not yet built. Requires sufficient behavioral baseline data.",
        }

    # Current state: where is the person relative to their twin?
    now = datetime.now(timezone.utc)
    current_hour = now.hour
    rhythm = twin.daily_rhythm or {}
    current_hour_data = rhythm.get(str(current_hour))

    expected_active = current_hour_data["expected_active"] if current_hour_data else None

    # Check last heartbeat for actual state
    last_hb = (await session.execute(text("""
        SELECT MAX(created_at) AS last_heartbeat FROM telemetries
        WHERE device_id = :did AND metric_type = 'heartbeat' AND is_simulated = false
    """), {"did": device_id})).fetchone()

    actual_inactive_minutes = None
    actual_state = "unknown"
    if last_hb and last_hb.last_heartbeat:
        actual_inactive_minutes = round((now - last_hb.last_heartbeat).total_seconds() / 60.0, 1)
        actual_state = "active" if actual_inactive_minutes < 30 else "inactive"

    # Deviation from twin
    deviation_status = "aligned"
    deviation_reason = None
    if expected_active is not None and actual_state != "unknown":
        if expected_active and actual_state == "inactive":
            deviation_status = "deviation"
            deviation_reason = f"Expected active at {current_hour:02d}:00 but inactive for {actual_inactive_minutes:.0f}min"
        elif not expected_active and actual_state == "active":
            deviation_status = "positive_deviation"
            deviation_reason = f"Unexpectedly active at {current_hour:02d}:00 (normally inactive)"

    return {
        "device_id": str(device_id),
        "device_identifier": device_row.device_identifier,
        "twin_exists": True,
        "twin_version": twin.twin_version,
        "confidence_score": round(twin.confidence_score, 3),
        "training_data_points": twin.training_data_points,
        "last_trained_at": twin.last_trained_at.isoformat() if twin.last_trained_at else None,
        "profile_summary": twin.profile_summary,
        "wake_hour": twin.wake_hour,
        "sleep_hour": twin.sleep_hour,
        "peak_activity_hour": twin.peak_activity_hour,
        "movement_interval_minutes": twin.movement_interval_minutes,
        "typical_inactivity_max_minutes": twin.typical_inactivity_max_minutes,
        "activity_windows": twin.activity_windows,
        "daily_rhythm": twin.daily_rhythm,
        "current_state": {
            "hour": current_hour,
            "expected_active": expected_active,
            "actual_state": actual_state,
            "actual_inactive_minutes": actual_inactive_minutes,
            "deviation_status": deviation_status,
            "deviation_reason": deviation_reason,
        },
    }


@router.post("/devices/{device_id}/digital-twin/rebuild")
async def rebuild_device_digital_twin(
    device_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Force rebuild the Digital Twin for a specific device."""
    from app.services.digital_twin_builder import build_single_twin

    # Verify device exists
    device_row = (await session.execute(text("""
        SELECT id, device_identifier FROM devices WHERE id = :did
    """), {"did": device_id})).fetchone()
    if not device_row:
        raise HTTPException(status_code=404, detail="Device not found")

    twin_data = await build_single_twin(session, device_id)
    if not twin_data:
        raise HTTPException(status_code=422, detail="Insufficient baseline data to build digital twin")

    return {
        "device_id": str(device_id),
        "device_identifier": device_row.device_identifier,
        "status": "rebuilt",
        "twin_version": twin_data.get("twin_version", 1),
        "confidence_score": twin_data["confidence_score"],
        "profile_summary": twin_data["profile_summary"],
    }


@router.get("/digital-twins/fleet")
async def get_fleet_digital_twins(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Returns a summary of all device digital twins for fleet-wide overview."""
    twins = (await session.execute(text("""
        SELECT dt.device_id, d.device_identifier,
               dt.twin_version, dt.confidence_score, dt.wake_hour, dt.sleep_hour,
               dt.peak_activity_hour, dt.training_data_points,
               dt.profile_summary, dt.last_trained_at
        FROM device_digital_twins dt
        JOIN devices d ON dt.device_id = d.id
        ORDER BY dt.confidence_score DESC
    """))).fetchall()

    return {
        "total_twins": len(twins),
        "twins": [
            {
                "device_id": str(t.device_id),
                "device_identifier": t.device_identifier,
                "twin_version": t.twin_version,
                "confidence_score": round(t.confidence_score, 3),
                "wake_hour": t.wake_hour,
                "sleep_hour": t.sleep_hour,
                "peak_activity_hour": t.peak_activity_hour,
                "training_data_points": t.training_data_points,
                "profile_summary": t.profile_summary,
                "last_trained_at": t.last_trained_at.isoformat() if t.last_trained_at else None,
            }
            for t in twins
        ],
    }


# ── Predictive Safety Engine Endpoints ──

@router.get("/devices/{device_id}/predictive-risk")
async def get_device_predictive_risk(
    device_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """
    Returns predictive risk analysis for a device.
    Computes fresh predictions from 7-day trend data + digital twin context.
    Also returns historical predictions.
    """
    from app.services.predictive_engine import predict_for_device

    # Verify device
    device_row = (await session.execute(text("""
        SELECT id, device_identifier FROM devices WHERE id = :did
    """), {"did": device_id})).fetchone()
    if not device_row:
        raise HTTPException(status_code=404, detail="Device not found")

    # Fresh prediction
    predictions = await predict_for_device(session, device_id, device_row.device_identifier)

    # Historical active predictions
    history = (await session.execute(text("""
        SELECT prediction_type, prediction_score, prediction_window_hours,
               confidence, explanation, feature_vector, trend_data, created_at
        FROM predictive_risks
        WHERE device_id = :did AND is_active = true
        ORDER BY created_at DESC
        LIMIT 10
    """), {"did": device_id})).fetchall()

    return {
        "device_id": str(device_id),
        "device_identifier": device_row.device_identifier,
        "live_predictions": [
            {
                "prediction_type": p["type"],
                "prediction_score": round(p["score"], 3),
                "prediction_window_hours": p["window_hours"],
                "confidence": round(p["confidence"], 3),
                "explanation": p["explanation"],
                "feature_vector": p["feature_vector"],
                "trend_data": p["trend_data"],
                "meets_alert_threshold": p["score"] >= 0.7 and p["confidence"] >= 0.6,
            }
            for p in predictions
        ],
        "active_alerts": [
            {
                "prediction_type": h.prediction_type,
                "prediction_score": round(h.prediction_score, 3),
                "prediction_window_hours": h.prediction_window_hours,
                "confidence": round(h.confidence, 3),
                "explanation": h.explanation,
                "feature_vector": h.feature_vector,
                "trend_data": h.trend_data,
                "created_at": h.created_at.isoformat(),
            }
            for h in history
        ],
        "total_live_predictions": len(predictions),
        "total_active_alerts": len(history),
    }


@router.get("/predictive-alerts")
async def get_fleet_predictive_alerts(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Fleet-wide predictive alerts — active high-risk predictions across all devices."""
    alerts = (await session.execute(text("""
        SELECT pr.device_id, d.device_identifier,
               pr.prediction_type, pr.prediction_score, pr.prediction_window_hours,
               pr.confidence, pr.explanation, pr.created_at
        FROM predictive_risks pr
        JOIN devices d ON pr.device_id = d.id
        WHERE pr.is_active = true
          AND pr.prediction_score >= 0.7
          AND pr.confidence >= 0.6
        ORDER BY pr.prediction_score DESC, pr.created_at DESC
        LIMIT 50
    """))).fetchall()

    return {
        "total_alerts": len(alerts),
        "alerts": [
            {
                "device_id": str(a.device_id),
                "device_identifier": a.device_identifier,
                "prediction_type": a.prediction_type,
                "prediction_score": round(a.prediction_score, 3),
                "prediction_window_hours": a.prediction_window_hours,
                "confidence": round(a.confidence, 3),
                "explanation": a.explanation,
                "created_at": a.created_at.isoformat(),
            }
            for a in alerts
        ],
    }


@router.get("/fleet-health-trends")
async def get_fleet_health_trends(
    window_minutes: int = Query(1440, ge=30, le=10080),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """
    Fleet-wide aggregated health trends for dashboard sparklines.
    Returns time-bucketed fleet averages/maxes for battery, signal, and combined scores,
    plus device reporting counts and threshold breach counts.
    """
    now = datetime.now(timezone.utc)
    lookback = now - timedelta(minutes=window_minutes)
    total_seconds = window_minutes * 60
    bucket_seconds = max(60, total_seconds // 120)

    # 1. Fleet-wide anomaly score aggregates per bucket
    score_rows = (await session.execute(text("""
        SELECT
            to_timestamp(FLOOR(EXTRACT(EPOCH FROM da.created_at) / :bucket) * :bucket) AS bucket_ts,
            da.metric,
            AVG(da.score) AS avg_score,
            MAX(da.score) AS max_score,
            COUNT(DISTINCT da.device_id) AS device_count
        FROM device_anomalies da
        WHERE da.is_simulated = false
          AND da.created_at >= :lookback
          AND da.created_at <= :now
          AND da.metric IN ('battery_slope', 'signal_strength', 'multi_metric')
        GROUP BY bucket_ts, da.metric
        ORDER BY bucket_ts
    """), {
        "bucket": bucket_seconds,
        "lookback": lookback,
        "now": now,
    })).fetchall()

    # 2. Fleet-wide telemetry reporting counts per bucket
    reporting_rows = (await session.execute(text("""
        SELECT
            to_timestamp(FLOOR(EXTRACT(EPOCH FROM created_at) / :bucket) * :bucket) AS bucket_ts,
            COUNT(DISTINCT device_id) AS devices_reporting,
            COUNT(*) AS heartbeat_count
        FROM telemetries
        WHERE metric_type = 'heartbeat'
          AND is_simulated = false
          AND created_at >= :lookback
          AND created_at <= :now
        GROUP BY bucket_ts
        ORDER BY bucket_ts
    """), {
        "bucket": bucket_seconds,
        "lookback": lookback,
        "now": now,
    })).fetchall()

    # Build timestamp map
    ts_map: dict = {}

    for r in reporting_rows:
        ts_key = r.bucket_ts.isoformat() if r.bucket_ts else None
        if not ts_key:
            continue
        ts_map[ts_key] = {
            "timestamp": ts_key,
            "devices_reporting": int(r.devices_reporting or 0),
            "heartbeats": int(r.heartbeat_count or 0),
            "avg_battery_score": None,
            "max_battery_score": None,
            "avg_signal_score": None,
            "max_signal_score": None,
            "avg_combined_score": None,
            "max_combined_score": None,
            "devices_with_anomalies": 0,
        }

    for r in score_rows:
        ts_key = r.bucket_ts.isoformat() if r.bucket_ts else None
        if not ts_key:
            continue
        if ts_key not in ts_map:
            ts_map[ts_key] = {
                "timestamp": ts_key,
                "devices_reporting": 0,
                "heartbeats": 0,
                "avg_battery_score": None,
                "max_battery_score": None,
                "avg_signal_score": None,
                "max_signal_score": None,
                "avg_combined_score": None,
                "max_combined_score": None,
                "devices_with_anomalies": 0,
            }
        entry = ts_map[ts_key]
        avg_val = round(float(r.avg_score), 2) if r.avg_score is not None else None
        max_val = round(float(r.max_score), 2) if r.max_score is not None else None

        if r.metric == "battery_slope":
            entry["avg_battery_score"] = avg_val
            entry["max_battery_score"] = max_val
        elif r.metric == "signal_strength":
            entry["avg_signal_score"] = avg_val
            entry["max_signal_score"] = max_val
        elif r.metric == "multi_metric":
            entry["avg_combined_score"] = avg_val
            entry["max_combined_score"] = max_val
            entry["devices_with_anomalies"] = int(r.device_count or 0)

    # Sort and limit to 120 points
    sorted_points = sorted(ts_map.values(), key=lambda p: p["timestamp"])
    if len(sorted_points) > 120:
        step = len(sorted_points) / 120
        sorted_points = [sorted_points[int(i * step)] for i in range(120)]

    # Summary stats
    total_devices_reporting = max((p["devices_reporting"] for p in sorted_points), default=0)
    peak_combined = max((p["max_combined_score"] or 0 for p in sorted_points), default=0)
    peak_battery = max((p["max_battery_score"] or 0 for p in sorted_points), default=0)
    peak_signal = max((p["max_signal_score"] or 0 for p in sorted_points), default=0)

    return {
        "window_minutes": window_minutes,
        "bucket_seconds": bucket_seconds,
        "total_points": len(sorted_points),
        "summary": {
            "peak_devices_reporting": total_devices_reporting,
            "peak_combined_score": peak_combined,
            "peak_battery_score": peak_battery,
            "peak_signal_score": peak_signal,
        },
        "points": sorted_points,
    }



@router.get("/replay-timeline")
async def get_replay_timeline(
    start_time: str = Query(...),
    end_time: str = Query(...),
    threshold: float = Query(60, ge=0, le=100),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """
    Returns time-series data for the replay timeline visualization.
    Aggregates anomaly scores and incident events within the window.
    Read-only.
    """
    try:
        window_start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        window_end = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="Invalid ISO datetime format")

    if window_end <= window_start:
        raise HTTPException(status_code=422, detail="end_time must be after start_time")

    window_span = (window_end - window_start).total_seconds()
    if window_span > 7 * 24 * 3600:
        raise HTTPException(status_code=422, detail="Window cannot exceed 7 days")

    bucket_seconds = max(60, int(window_span // 120))

    # 1. Aggregated anomaly scores per time bucket (fleet-wide)
    score_rows = (await session.execute(text("""
        SELECT
            to_timestamp(FLOOR(EXTRACT(EPOCH FROM da.created_at) / :bucket) * :bucket) AS bucket_ts,
            MAX(da.score) AS max_score,
            AVG(da.score) AS avg_score,
            COUNT(DISTINCT da.device_id) AS device_count,
            COUNT(DISTINCT CASE WHEN da.score >= :threshold THEN da.device_id END) AS devices_above
        FROM device_anomalies da
        WHERE da.metric = 'multi_metric'
          AND da.is_simulated = false
          AND da.created_at >= :start
          AND da.created_at <= :end
        GROUP BY bucket_ts
        ORDER BY bucket_ts
    """), {
        "bucket": bucket_seconds,
        "threshold": threshold,
        "start": window_start,
        "end": window_end,
    })).fetchall()

    score_timeline = []
    for r in score_rows:
        ts = r.bucket_ts.isoformat() if r.bucket_ts else None
        if not ts:
            continue
        score_timeline.append({
            "timestamp": ts,
            "max_combined": round(float(r.max_score), 2) if r.max_score is not None else 0,
            "avg_combined": round(float(r.avg_score), 2) if r.avg_score is not None else 0,
            "devices_above_threshold": int(r.devices_above or 0),
            "total_devices": int(r.device_count or 0),
        })

    # Limit to 120 points
    if len(score_timeline) > 120:
        step = len(score_timeline) / 120
        score_timeline = [score_timeline[int(i * step)] for i in range(120)]

    # 2. Key incident events in the window
    event_rows = (await session.execute(text("""
        SELECT
            ie.created_at,
            ie.event_type,
            ie.event_metadata,
            d.device_identifier,
            i.severity,
            i.incident_type
        FROM incident_events ie
        JOIN incidents i ON ie.incident_id = i.id
        LEFT JOIN devices d ON i.device_id = d.id
        WHERE ie.created_at >= :start
          AND ie.created_at <= :end
          AND ie.event_type IN (
            'device_instability_detected',
            'device_instability_recovered',
            'escalation_l1', 'escalation_l2', 'escalation_l3',
            'device_instability_escalation_blocked'
          )
        ORDER BY ie.created_at
        LIMIT 500
    """), {"start": window_start, "end": window_end})).fetchall()

    events = []
    for r in event_rows:
        events.append({
            "timestamp": r.created_at.isoformat() if r.created_at else None,
            "event_type": r.event_type,
            "device_identifier": r.device_identifier,
            "severity": r.severity,
            "incident_type": r.incident_type,
        })

    return {
        "window": {
            "start_time": window_start.isoformat(),
            "end_time": window_end.isoformat(),
            "span_minutes": round(window_span / 60, 1),
        },
        "threshold": threshold,
        "bucket_seconds": bucket_seconds,
        "score_timeline": score_timeline,
        "events": events,
        "total_score_points": len(score_timeline),
        "total_events": len(events),
    }




@router.post("/simulate/compare/multi-metric")
async def compare_multi_metric(
    payload: CompareMultiMetricRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """
    Pure read-only multi-metric comparison engine.
    Evaluates two configs (A vs B) against production telemetry.
    Supports two modes:
      - live: evaluates against recent anomaly data (lookback from now)
      - replay: evaluates against historical anomaly data (start_time to end_time)
    No DB writes. No audit logs. No scheduler triggers.
    """
    now = datetime.now(timezone.utc)

    # ── Determine time window based on mode ──
    if payload.mode == "replay":
        if not payload.start_time or not payload.end_time:
            raise HTTPException(status_code=422, detail="start_time and end_time required for replay mode")
        try:
            window_start = datetime.fromisoformat(payload.start_time.replace("Z", "+00:00"))
            window_end = datetime.fromisoformat(payload.end_time.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            raise HTTPException(status_code=422, detail="Invalid ISO datetime format for start_time/end_time")

        if window_end <= window_start:
            raise HTTPException(status_code=422, detail="end_time must be after start_time")

        window_span_minutes = (window_end - window_start).total_seconds() / 60.0
        if window_span_minutes > 10080:  # 7 days
            raise HTTPException(status_code=422, detail="Replay window cannot exceed 7 days")

        if window_end > now:
            raise HTTPException(status_code=422, detail="end_time cannot be in the future")

        lookback = window_start
        lookback_end = window_end
        reference_time = window_end
    else:
        lookback = now - timedelta(minutes=payload.window_minutes)
        lookback_end = now
        reference_time = now

    # 1. Pull anomaly data (battery_slope + signal_strength) within the window
    anomaly_rows = (await session.execute(text("""
        SELECT da.device_id, d.device_identifier,
               da.metric, da.score, da.created_at
        FROM device_anomalies da
        JOIN devices d ON da.device_id = d.id
        WHERE da.created_at >= :lookback
          AND da.created_at <= :lookback_end
          AND da.metric IN ('battery_slope', 'signal_strength')
          AND da.is_simulated = false
        ORDER BY da.device_id, da.metric, da.created_at DESC
    """), {"lookback": lookback, "lookback_end": lookback_end})).fetchall()

    # Group by device: pick latest score per metric
    device_scores: dict = {}
    for r in anomaly_rows:
        did = str(r.device_id)
        if did not in device_scores:
            device_scores[did] = {
                "device_id": r.device_id,
                "device_identifier": r.device_identifier,
                "battery_score": None,
                "signal_score": None,
                "behavior_score": None,
            }
        entry = device_scores[did]
        if r.metric == "battery_slope" and entry["battery_score"] is None:
            entry["battery_score"] = float(r.score)
        elif r.metric == "signal_strength" and entry["signal_score"] is None:
            entry["signal_score"] = float(r.score)

    # 1b. Pull behavior anomalies within the window (behavior_score 0-1 → normalize to 0-100)
    behavior_rows = (await session.execute(text("""
        SELECT ba.device_id, d.device_identifier,
               ba.behavior_score, ba.created_at
        FROM behavior_anomalies ba
        JOIN devices d ON ba.device_id = d.id
        WHERE ba.created_at >= :lookback
          AND ba.created_at <= :lookback_end
          AND ba.is_simulated = false
        ORDER BY ba.device_id, ba.created_at DESC
    """), {"lookback": lookback, "lookback_end": lookback_end})).fetchall()

    for r in behavior_rows:
        did = str(r.device_id)
        if did not in device_scores:
            device_scores[did] = {
                "device_id": r.device_id,
                "device_identifier": r.device_identifier,
                "battery_score": None,
                "signal_score": None,
                "behavior_score": None,
            }
        entry = device_scores[did]
        if entry["behavior_score"] is None:
            entry["behavior_score"] = round(float(r.behavior_score) * 100, 1)

    # 2. Pull persistence data (multi_metric anomalies for duration calc)
    persistence_lookback = timedelta(minutes=max(payload.window_minutes, 60) * 3)
    persistence_rows = (await session.execute(text("""
        SELECT device_id,
               MIN(created_at) AS first_detected_at,
               COUNT(*) AS anomaly_count
        FROM device_anomalies
        WHERE metric = 'multi_metric'
          AND is_simulated = false
          AND created_at >= :lookback_wide
          AND created_at <= :lookback_end
        GROUP BY device_id
        HAVING COUNT(*) >= 1
    """), {
        "lookback_wide": reference_time - persistence_lookback,
        "lookback_end": lookback_end,
    })).fetchall()

    persistence_data = {}
    for r in persistence_rows:
        did = str(r.device_id)
        persistence_data[did] = (reference_time - r.first_detected_at).total_seconds() / 60.0

    # 3. Evaluate Config A (in-memory)
    result_a = _evaluate_config_in_memory(device_scores, payload.config_a.combined_anomaly, persistence_data)

    # 4. Evaluate Config B (in-memory)
    result_b = _evaluate_config_in_memory(device_scores, payload.config_b.combined_anomaly, persistence_data)

    # 5. Compute deltas
    anomalies_diff = result_b["anomalies"] - result_a["anomalies"]
    instability_diff = result_b["instability_incidents"] - result_a["instability_incidents"]
    tier_shift = {
        "L1": result_b["tier_counts"]["L1"] - result_a["tier_counts"]["L1"],
        "L2": result_b["tier_counts"]["L2"] - result_a["tier_counts"]["L2"],
        "L3": result_b["tier_counts"]["L3"] - result_a["tier_counts"]["L3"],
    }

    # 6. Compute per-device changes
    newly_flagged = []
    no_longer_flagged = []
    tier_upgraded = []
    tier_downgraded = []

    tier_order = {"L1": 1, "L2": 2, "L3": 3}
    all_device_ids = set(result_a["per_device"].keys()) | set(result_b["per_device"].keys())

    for did in all_device_ids:
        da = result_a["per_device"].get(did, {"flagged": False, "tier": None, "score": 0})
        db = result_b["per_device"].get(did, {"flagged": False, "tier": None, "score": 0})
        dev_id = da.get("device_identifier") or db.get("device_identifier", did)

        change_entry = {
            "device_identifier": dev_id,
            "score_a": da.get("score", 0),
            "score_b": db.get("score", 0),
            "tier_a": da.get("tier"),
            "tier_b": db.get("tier"),
        }

        if not da["flagged"] and db["flagged"]:
            newly_flagged.append(change_entry)
        elif da["flagged"] and not db["flagged"]:
            no_longer_flagged.append(change_entry)
        elif da["flagged"] and db["flagged"] and da.get("tier") and db.get("tier"):
            a_ord = tier_order.get(da["tier"], 0)
            b_ord = tier_order.get(db["tier"], 0)
            if b_ord > a_ord:
                tier_upgraded.append(change_entry)
            elif b_ord < a_ord:
                tier_downgraded.append(change_entry)

    # 7. Build replay metadata (count raw telemetry events in the window)
    replay_metadata = None
    if payload.mode == "replay":
        telemetry_count_row = (await session.execute(text("""
            SELECT COUNT(*) AS event_count
            FROM telemetries
            WHERE metric_type = 'heartbeat'
              AND is_simulated = false
              AND created_at >= :start
              AND created_at <= :end
        """), {"start": lookback, "end": lookback_end})).fetchone()

        replay_metadata = {
            "mode": "replay",
            "start_time": lookback.isoformat(),
            "end_time": lookback_end.isoformat(),
            "window_span_minutes": round((lookback_end - lookback).total_seconds() / 60.0, 1),
            "telemetry_events_analyzed": telemetry_count_row.event_count if telemetry_count_row else 0,
            "anomaly_records_evaluated": len(anomaly_rows),
        }

    response = {
        "mode": payload.mode,
        "window_minutes": payload.window_minutes,
        "devices_evaluated": len(device_scores),
        "summary": {
            "config_a": {
                "anomalies": result_a["anomalies"],
                "instability_incidents": result_a["instability_incidents"],
                "tier_counts": result_a["tier_counts"],
            },
            "config_b": {
                "anomalies": result_b["anomalies"],
                "instability_incidents": result_b["instability_incidents"],
                "tier_counts": result_b["tier_counts"],
            },
        },
        "delta": {
            "anomalies_diff": anomalies_diff,
            "instability_diff": instability_diff,
            "tier_shift": tier_shift,
        },
        "device_changes": {
            "newly_flagged": newly_flagged,
            "no_longer_flagged": no_longer_flagged,
            "tier_upgraded": tier_upgraded,
            "tier_downgraded": tier_downgraded,
        },
    }

    if replay_metadata:
        response["replay_metadata"] = replay_metadata

    return response


# ── AI Incident Narrative Engine ──

@router.post("/incidents/{incident_id}/narrative")
async def generate_incident_narrative(
    incident_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """
    Generate a new AI narrative for an incident.
    Uses two-stage generation: deterministic facts pack → GPT-5.2 narrative.
    Falls back to template if AI is unavailable.
    Narratives are immutable — each call creates a new versioned entry.
    """
    from app.services.narrative_engine import build_facts_pack, generate_narrative, compute_input_hash

    # 1. Build facts pack
    facts = await build_facts_pack(session, str(incident_id))
    if not facts:
        raise HTTPException(status_code=404, detail="Incident not found")

    input_hash = compute_input_hash(facts)

    # 2. Check if we already have a narrative with the same input hash (no change)
    existing = (await session.execute(text("""
        SELECT id, narrative_json, confidence, created_at
        FROM incident_narratives
        WHERE incident_id = :iid AND input_hash = :hash
        ORDER BY created_at DESC LIMIT 1
    """), {"iid": str(incident_id), "hash": input_hash})).fetchone()

    if existing:
        return {
            "id": str(existing.id),
            "incident_id": str(incident_id),
            "narrative": existing.narrative_json,
            "confidence": existing.confidence,
            "created_at": existing.created_at.isoformat(),
            "cached": True,
            "message": "Narrative is up-to-date (incident data unchanged)",
        }

    # 3. Get current version number
    version_row = (await session.execute(text("""
        SELECT COALESCE(MAX(narrative_version), 0) AS max_ver
        FROM incident_narratives WHERE incident_id = :iid
    """), {"iid": str(incident_id)})).fetchone()
    next_version = (version_row.max_ver if version_row else 0) + 1

    # 4. Generate narrative (AI with template fallback)
    narrative = await generate_narrative(facts)
    confidence = narrative.get("confidence", 0.5)

    # Determine if AI or template was used
    generated_by = "ai" if confidence > 0.6 else "template"

    # 5. Persist immutable narrative record
    narrative_id = str(uuid_mod.uuid4())
    await session.execute(text("""
        INSERT INTO incident_narratives
        (id, incident_id, narrative_version, generated_by, mode, model, input_hash, narrative_json, confidence, created_at)
        VALUES (:id, :iid, :ver, :gen_by, :mode, :model, :hash, CAST(:narrative AS jsonb), :conf, NOW())
    """), {
        "id": narrative_id,
        "iid": str(incident_id),
        "ver": next_version,
        "gen_by": generated_by,
        "mode": facts.get("mode", "live"),
        "model": "gpt-5.2" if generated_by == "ai" else "template",
        "hash": input_hash,
        "narrative": json.dumps(narrative, default=str),
        "conf": confidence,
    })
    await session.commit()

    return {
        "id": narrative_id,
        "incident_id": str(incident_id),
        "narrative_version": next_version,
        "generated_by": generated_by,
        "model": "gpt-5.2" if generated_by == "ai" else "template",
        "narrative": narrative,
        "confidence": confidence,
        "cached": False,
        "message": f"Narrative v{next_version} generated successfully",
    }


@router.get("/incidents/{incident_id}/narrative")
async def get_incident_narratives(
    incident_id: UUID,
    limit: int = Query(10, ge=1, le=50),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """
    Fetch the history of narratives for an incident.
    Returns all versions, most recent first.
    """
    rows = (await session.execute(text("""
        SELECT id, incident_id, narrative_version, generated_by, mode, model,
               input_hash, narrative_json, confidence, created_at
        FROM incident_narratives
        WHERE incident_id = :iid
        ORDER BY created_at DESC
        LIMIT :lim
    """), {"iid": str(incident_id), "lim": limit})).fetchall()

    return [
        {
            "id": str(r.id),
            "incident_id": str(r.incident_id),
            "narrative_version": r.narrative_version,
            "generated_by": r.generated_by,
            "mode": r.mode,
            "model": r.model,
            "input_hash": r.input_hash,
            "narrative": r.narrative_json,
            "confidence": r.confidence,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/incidents/{incident_id}/narrative/status")
async def get_narrative_status(
    incident_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """
    Check if a narrative exists and whether it's up-to-date.
    Compares the latest narrative's input_hash against current facts.
    """
    from app.services.narrative_engine import build_facts_pack, compute_input_hash

    # Check if incident exists
    incident = (await session.execute(text("""
        SELECT id FROM incidents WHERE id = :iid
    """), {"iid": str(incident_id)})).fetchone()

    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    # Get latest narrative
    latest = (await session.execute(text("""
        SELECT id, narrative_version, input_hash, confidence, generated_by, model, created_at
        FROM incident_narratives
        WHERE incident_id = :iid
        ORDER BY created_at DESC LIMIT 1
    """), {"iid": str(incident_id)})).fetchone()

    if not latest:
        return {
            "has_narrative": False,
            "is_stale": True,
            "latest_version": None,
            "message": "No narrative generated yet",
        }

    # Build current facts and compare hash
    facts = await build_facts_pack(session, str(incident_id))
    current_hash = compute_input_hash(facts) if facts else ""
    is_stale = latest.input_hash != current_hash

    return {
        "has_narrative": True,
        "is_stale": is_stale,
        "latest_version": latest.narrative_version,
        "generated_by": latest.generated_by,
        "model": latest.model,
        "confidence": latest.confidence,
        "created_at": latest.created_at.isoformat(),
        "message": "Narrative is stale — incident data has changed" if is_stale else "Narrative is up-to-date",
    }


# ── AI Risk Forecast Timeline ──

@router.get("/devices/{device_id}/risk-forecast")
async def get_device_risk_forecast(
    device_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """
    Generate a 24-hour risk forecast for a device.
    Uses predictive signals, digital twin rhythm, telemetry trends, and recent incidents.
    Returns 6 time buckets with risk scores, levels, and reasons.
    Caches forecast in risk_forecasts table (15 min TTL).
    """
    from app.services.forecast_engine import generate_forecast

    # Check for cached forecast (< 15 min old)
    cached_rows = (await session.execute(text("""
        SELECT bucket_name, bucket_start, bucket_end, risk_score, risk_level, reason, created_at
        FROM risk_forecasts
        WHERE device_id = :did AND created_at > NOW() - INTERVAL '15 minutes'
        ORDER BY bucket_start
    """), {"did": str(device_id)})).fetchall()

    if cached_rows:
        buckets = [
            {
                "bucket": r.bucket_name,
                "label": r.bucket_name.replace("_", " ").title(),
                "start_hour": r.bucket_start,
                "end_hour": r.bucket_end,
                "risk_score": round(r.risk_score, 3),
                "risk_level": r.risk_level,
                "reason": r.reason or "normal activity expected",
            }
            for r in cached_rows
        ]
        max_bucket = max(buckets, key=lambda b: b["risk_score"])
        high_count = sum(1 for b in buckets if b["risk_level"] == "HIGH")
        medium_count = sum(1 for b in buckets if b["risk_level"] == "MEDIUM")

        # Get device identifier
        dev = (await session.execute(text(
            "SELECT device_identifier FROM devices WHERE id = :did"
        ), {"did": str(device_id)})).fetchone()

        return {
            "device_id": str(device_id),
            "device_identifier": dev.device_identifier if dev else str(device_id),
            "forecast_window_hours": 24,
            "generated_at": cached_rows[0].created_at.isoformat(),
            "cached": True,
            "buckets": buckets,
            "summary": {
                "peak_risk_bucket": max_bucket["label"],
                "peak_risk_score": max_bucket["risk_score"],
                "peak_risk_level": max_bucket["risk_level"],
                "high_risk_count": high_count,
                "medium_risk_count": medium_count,
            },
        }

    # Generate fresh forecast
    forecast = await generate_forecast(session, str(device_id))
    if not forecast:
        raise HTTPException(status_code=404, detail="Device not found or insufficient data")

    # Persist to risk_forecasts for caching + history
    for b in forecast["buckets"]:
        await session.execute(text("""
            INSERT INTO risk_forecasts (device_id, bucket_name, bucket_start, bucket_end, risk_score, risk_level, reason)
            VALUES (:did, :name, :start, :end, :score, :level, :reason)
        """), {
            "did": str(device_id),
            "name": b["bucket"],
            "start": b["start_hour"],
            "end": b["end_hour"],
            "score": b["risk_score"],
            "level": b["risk_level"],
            "reason": b["reason"],
        })
    await session.commit()

    forecast["cached"] = False
    return forecast


# ── AI Safety Score Engine ──

@router.get("/devices/{device_id}/safety-score")
async def get_device_safety_score(
    device_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """
    Calculate and return the AI Safety Score for a device.
    Aggregates: predictive risk, anomalies, forecast peak, twin deviation, device instability.
    Caches score in safety_scores table (15 min TTL).
    """
    from app.services.safety_score_engine import calculate_safety_score

    # Check cache (< 15 min)
    cached = (await session.execute(text("""
        SELECT score, status, predictive_risk, anomaly_count, forecast_peak_risk,
               twin_deviation, device_instability, created_at
        FROM safety_scores
        WHERE device_id = :did AND created_at > NOW() - INTERVAL '15 minutes'
        ORDER BY created_at DESC LIMIT 1
    """), {"did": str(device_id)})).fetchone()

    if cached:
        dev = (await session.execute(text(
            "SELECT device_identifier FROM devices WHERE id = :did"
        ), {"did": str(device_id)})).fetchone()
        return {
            "device_id": str(device_id),
            "device_identifier": dev.device_identifier if dev else str(device_id),
            "safety_score": cached.score,
            "status": cached.status,
            "generated_at": cached.created_at.isoformat(),
            "cached": True,
            "contributors": {
                "predictive_risk": cached.predictive_risk,
                "anomaly_count": cached.anomaly_count,
                "forecast_peak_risk": cached.forecast_peak_risk,
                "twin_deviation": cached.twin_deviation,
                "device_instability": cached.device_instability,
            },
        }

    result = await calculate_safety_score(session, str(device_id))
    if not result:
        raise HTTPException(status_code=404, detail="Device not found")

    # Persist
    contrib = result["contributors"]
    await session.execute(text("""
        INSERT INTO safety_scores
        (device_id, score, status, predictive_risk, anomaly_count,
         forecast_peak_risk, twin_deviation, device_instability)
        VALUES (:did, :score, :status, :pred, :anom, :forecast, :twin, :inst)
    """), {
        "did": str(device_id),
        "score": result["safety_score"],
        "status": result["status"],
        "pred": contrib["predictive_risk"],
        "anom": contrib["anomaly_count"],
        "forecast": contrib["forecast_peak_risk"],
        "twin": contrib["twin_deviation"],
        "inst": contrib["device_instability"],
    })
    await session.commit()

    result["cached"] = False
    return result


@router.get("/fleet-safety")
async def get_fleet_safety(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """
    Calculate fleet-wide safety scores for all devices.
    Returns average fleet score and individual device scores.
    """
    from app.services.safety_score_engine import calculate_fleet_safety
    return await calculate_fleet_safety(session)


# ── Twin Evolution Timeline ──

@router.get("/devices/{device_id}/twin-evolution")
async def get_twin_evolution(
    device_id: UUID,
    weeks: int = Query(8, ge=2, le=52),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """
    Get the Twin Evolution Timeline for a device.
    Analyzes weekly behavioral snapshots to detect long-term shifts.
    Returns weekly metrics, trends, shift detections, and interpretation.
    """
    from app.services.twin_evolution_engine import get_twin_evolution

    result = await get_twin_evolution(session, str(device_id), weeks)
    if not result:
        raise HTTPException(status_code=404, detail="Device not found")
    return result


# ── Life Pattern Graph ──

@router.get("/devices/{device_id}/life-pattern")
async def get_life_pattern(
    device_id: UUID,
    days: int = Query(30, ge=7, le=90),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """
    Build and return the 24-hour life pattern profile for a device.
    Aggregates telemetry over the given window to create a behavioral
    fingerprint with hourly probabilities, deviations, and insights.
    """
    from app.services.life_pattern_engine import build_life_pattern

    result = await build_life_pattern(session, str(device_id), days)
    if not result:
        raise HTTPException(status_code=404, detail="Device not found or insufficient data")
    return result


# ── Location Risk Intelligence ──

@router.get("/location-risk")
async def evaluate_location(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Evaluate the safety risk score for a given location."""
    from app.services.location_risk_engine import evaluate_location_risk
    return await evaluate_location_risk(session, lat, lng)


@router.get("/location-risk/heatmap")
async def get_location_heatmap(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Get all data for the Location Risk Heatmap visualization."""
    from app.services.location_risk_engine import get_risk_heatmap_data
    return await get_risk_heatmap_data(session)


@router.post("/devices/{device_id}/location")
async def update_location(
    device_id: UUID,
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Update a device's GPS location and check geofence rules."""
    from app.services.location_risk_engine import update_device_location
    return await update_device_location(session, str(device_id), lat, lng)


@router.post("/devices/{device_id}/geofence")
async def create_device_geofence(
    device_id: UUID,
    name: str = Query(...),
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius: float = Query(500, ge=50, le=5000),
    fence_type: str = Query("safe"),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Create a geofence rule for a device."""
    from app.services.location_risk_engine import create_geofence
    return await create_geofence(session, str(device_id), name, lat, lng, radius, fence_type)


@router.post("/geofence-alert")
async def check_geofence(
    device_id: str = Query(...),
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Check if a device's position breaches any geofence rules."""
    from app.services.location_risk_engine import check_geofence_breach
    return await check_geofence_breach(session, device_id, lat, lng)


# ── Environmental Risk AI ──

@router.get("/environment-risk")
async def evaluate_environment(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Evaluate environmental risk for a given location using live weather data."""
    from app.services.environment_risk_engine import evaluate_environment_risk
    return await evaluate_environment_risk(lat, lng)


@router.get("/environment-risk/fleet")
async def get_fleet_environment(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Get environmental risk status for all tracked devices."""
    from app.services.environment_risk_engine import get_fleet_environment_status
    return await get_fleet_environment_status(session)


# ── Route Safety ──

@router.post("/route-safety")
async def evaluate_route(
    start_lat: float = Query(..., ge=-90, le=90),
    start_lng: float = Query(..., ge=-180, le=180),
    end_lat: float = Query(..., ge=-90, le=90),
    end_lng: float = Query(..., ge=-180, le=180),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Evaluate safety of routes between two points. Returns 3 options: shortest, safest, balanced."""
    from app.services.route_safety_engine import evaluate_route_safety
    result = await evaluate_route_safety(session, start_lat, start_lng, end_lat, end_lng)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


# ── Command Center ──

@router.get("/command-center")
async def get_command_center(
    fresh: bool = Query(False, description="Skip the 10s Redis cache (ops debug)"),
    user: User = Depends(require_role("operator", "admin")),
):
    """
    Unified intelligence endpoint combining all AI layers into a single payload.
    Returns: fleet safety, predictive alerts, risk forecast highlights,
    twin evolution shifts, and active incidents.

    Performance contract (locked June 2026):
      * Each of the 7 sections runs in its OWN async session — so they
        execute in parallel via `asyncio.gather`, not serialised on a
        single connection.
      * Result is Redis-cached for 10s (key `cc:unified:v1`). Operators
        polling at 30s see ≤ 1 cold computation every 3 polls; the rest
        are sub-10ms cache hits.
      * Any section that raises is *isolated* — it returns an empty
        default, the panel still renders, and a structured log line is
        emitted so we can spot which section is the next bottleneck.

    The response shape MUST stay byte-stable with the pre-refactor
    payload (frontend `CommandCenterPage` reads ~12 keys directly).
    Do NOT add/rename keys without coordinating the FE change.
    """
    from app.services.safety_score_engine import calculate_fleet_safety
    from app.services.life_pattern_engine import get_fleet_life_pattern_alerts
    from app.services.environment_risk_engine import get_fleet_environment_status
    from app.db.session import async_session as _async_session
    from app.services import redis_service
    import asyncio

    CACHE_NS = "command_center"
    CACHE_KEY = "unified:v1"
    CACHE_TTL_S = 10

    # ── Cache check ───────────────────────────────────────────
    if not fresh:
        try:
            cached = redis_service.get_json(CACHE_NS, CACHE_KEY)
            if cached:
                cached["_cache"] = {"hit": True, "ttl_s": CACHE_TTL_S}
                return cached
        except Exception as e:
            logger.debug(f"command-center cache read failed: {e}")

    now_ts = datetime.utcnow()

    # ── Per-section fetchers, each on its OWN session ─────────
    # The whole point is to bypass the single-connection bottleneck.
    # gather with return_exceptions=True so one bad section can't
    # break the panel.

    async def _fetch_fleet():
        async with _async_session() as s:
            return await calculate_fleet_safety(s)

    async def _fetch_predictive_alerts():
        async with _async_session() as s:
            rows = (await s.execute(text("""
                SELECT pr.device_id, d.device_identifier,
                       pr.prediction_type, pr.prediction_score, pr.confidence, pr.explanation,
                       pr.prediction_window_hours, pr.created_at
                FROM predictive_risks pr
                JOIN devices d ON pr.device_id = d.id
                WHERE pr.is_active = true AND pr.prediction_score >= 0.5
                ORDER BY pr.prediction_score DESC
                LIMIT 15
            """))).fetchall()
            return [
                {
                    "device_id": str(r.device_id),
                    "device_identifier": r.device_identifier,
                    "prediction_type": r.prediction_type,
                    "score": round(r.prediction_score, 3),
                    "confidence": round(r.confidence, 3),
                    "explanation": r.explanation,
                    "window_hours": r.prediction_window_hours,
                }
                for r in rows
            ]

    async def _fetch_forecast_highlights():
        async with _async_session() as s:
            rows = (await s.execute(text("""
                SELECT rf.device_id, d.device_identifier,
                       rf.bucket_name, rf.bucket_start, rf.bucket_end,
                       rf.risk_score, rf.risk_level, rf.reason
                FROM risk_forecasts rf
                JOIN devices d ON rf.device_id = d.id
                WHERE rf.risk_level IN ('HIGH', 'MEDIUM')
                  AND rf.created_at > NOW() - INTERVAL '30 minutes'
                ORDER BY rf.risk_score DESC
                LIMIT 15
            """))).fetchall()
            return [
                {
                    "device_id": str(r.device_id),
                    "device_identifier": r.device_identifier,
                    "bucket": r.bucket_name.replace("_", " ").title(),
                    "start_hour": r.bucket_start,
                    "end_hour": r.bucket_end,
                    "risk_score": round(r.risk_score, 3),
                    "risk_level": r.risk_level,
                    "reason": r.reason,
                }
                for r in rows
            ]

    async def _fetch_evolution_shifts():
        # This used to scan the WHOLE twin_evolution_snapshots table
        # with no time filter — fine when the table was small, brutal
        # now. Cap at last 60 days; that's already 8 weekly buckets
        # per device which is more than enough to detect a trend.
        async with _async_session() as s:
            rows = (await s.execute(text("""
                SELECT tes.device_id, d.device_identifier,
                       tes.week_start, tes.movement_frequency, tes.active_hours,
                       tes.avg_battery, tes.avg_signal, tes.anomaly_count,
                       tes.week_number
                FROM twin_evolution_snapshots tes
                JOIN devices d ON tes.device_id = d.id
                WHERE tes.week_number >= 2
                  AND tes.week_start > NOW() - INTERVAL '60 days'
                ORDER BY tes.device_id, tes.week_start
            """))).fetchall()

            device_snapshots: dict = {}
            for r in rows:
                did = str(r.device_id)
                if did not in device_snapshots:
                    device_snapshots[did] = {"identifier": r.device_identifier, "weeks": []}
                device_snapshots[did]["weeks"].append({
                    "week_start": r.week_start.isoformat(),
                    "week_number": r.week_number,
                    "movement_frequency": float(r.movement_frequency or 0),
                    "active_hours": float(r.active_hours or 0),
                    "avg_battery": float(r.avg_battery or 0),
                    "avg_signal": float(r.avg_signal or 0),
                })

            shifts = []
            for did, info in device_snapshots.items():
                weeks = info["weeks"]
                if len(weeks) < 2:
                    continue
                first = weeks[0]
                last = weeks[-1]
                for metric, label, threshold in [
                    ("movement_frequency", "Movement", -20),
                    ("active_hours", "Active hours", -20),
                    ("avg_battery", "Battery", -15),
                    ("avg_signal", "Signal", -20),
                ]:
                    if first[metric] != 0:
                        change = ((last[metric] - first[metric]) / abs(first[metric])) * 100
                        if change <= threshold:
                            shifts.append({
                                "device_id": did,
                                "device_identifier": info["identifier"],
                                "metric": metric,
                                "label": label,
                                "change_percent": round(change, 1),
                                "from_value": round(first[metric], 1),
                                "to_value": round(last[metric], 1),
                                "weeks_span": len(weeks),
                                "severity": "high" if abs(change) > 40 else "medium",
                            })
            shifts.sort(key=lambda s: abs(s["change_percent"]), reverse=True)
            return shifts

    async def _fetch_active_incidents():
        async with _async_session() as s:
            rows = (await s.execute(text("""
                SELECT i.id, i.device_id, d.device_identifier, s.full_name AS senior_name,
                       s.guardian_id AS user_id,
                       i.incident_type, i.severity, i.status, i.escalation_level,
                       i.created_at, i.is_test
                FROM incidents i
                JOIN devices d ON i.device_id = d.id
                JOIN seniors s ON i.senior_id = s.id
                WHERE i.status NOT IN ('resolved', 'false_alarm')
                ORDER BY
                    CASE i.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                    i.created_at DESC
                LIMIT 20
            """))).fetchall()
            return [
                {
                    "id": str(r.id),
                    "device_id": str(r.device_id),
                    "device_identifier": r.device_identifier,
                    "senior_name": r.senior_name,
                    "user_id": str(r.user_id) if r.user_id else None,
                    "incident_type": r.incident_type,
                    "severity": r.severity,
                    "status": r.status,
                    "escalation_level": r.escalation_level,
                    "created_at": r.created_at.isoformat(),
                    "is_test": r.is_test,
                }
                for r in rows
            ]

    async def _fetch_life_pattern():
        async with _async_session() as s:
            return await get_fleet_life_pattern_alerts(s)

    async def _fetch_environment():
        async with _async_session() as s:
            return await get_fleet_environment_status(s)

    # ── Fire all 7 in parallel ────────────────────────────────
    sections = [
        ("fleet",              _fetch_fleet()),
        ("predictive_alerts",  _fetch_predictive_alerts()),
        ("forecast_highlights", _fetch_forecast_highlights()),
        ("evolution_shifts",   _fetch_evolution_shifts()),
        ("active_incidents",   _fetch_active_incidents()),
        ("life_pattern_alerts", _fetch_life_pattern()),
        ("environment_status", _fetch_environment()),
    ]
    results_raw = await asyncio.gather(*(coro for _, coro in sections), return_exceptions=True)

    # ── Per-section failure isolation ─────────────────────────
    defaults = {
        "fleet": {"fleet_score": 0, "fleet_status": "MONITOR", "device_count": 0,
                  "status_breakdown": {}, "devices": []},
        "predictive_alerts":   [],
        "forecast_highlights": [],
        "evolution_shifts":    [],
        "active_incidents":    [],
        "life_pattern_alerts": [],
        "environment_status":  [],
    }
    out: dict = {}
    failed_sections: list[str] = []
    for (name, _), result in zip(sections, results_raw):
        if isinstance(result, Exception):
            logger.warning(
                f"[command-center] section '{name}' failed: "
                f"{type(result).__name__}: {result}"
            )
            failed_sections.append(name)
            out[name] = defaults[name]
        else:
            out[name] = result

    fleet = out["fleet"]
    predictive_alerts   = out["predictive_alerts"]
    forecast_highlights = out["forecast_highlights"]
    evolution_shifts    = out["evolution_shifts"]
    active_incidents    = out["active_incidents"]

    payload = {
        "generated_at": now_ts.isoformat(),
        "fleet_safety": {
            "fleet_score":      fleet.get("fleet_score", 0),
            "fleet_status":     fleet.get("fleet_status", "MONITOR"),
            "device_count":     fleet.get("device_count", 0),
            "status_breakdown": fleet.get("status_breakdown", {}),
            "devices": [
                {
                    "device_id": d["device_id"],
                    "device_identifier": d["device_identifier"],
                    "safety_score": d["safety_score"],
                    "status": d["status"],
                }
                for d in fleet.get("devices", [])
            ],
        },
        "predictive_alerts":   predictive_alerts,
        "forecast_highlights": forecast_highlights,
        "evolution_shifts":    evolution_shifts,
        "active_incidents":    active_incidents,
        "life_pattern_alerts": out["life_pattern_alerts"],
        "environment_status":  out["environment_status"],
        "counts": {
            "predictive_alerts":  len(predictive_alerts),
            "high_risk_windows":  sum(1 for f in forecast_highlights if f["risk_level"] == "HIGH"),
            "evolution_shifts":   len(evolution_shifts),
            "active_incidents":   len(active_incidents),
            "critical_devices":   fleet.get("status_breakdown", {}).get("critical", 0)
                                  + fleet.get("status_breakdown", {}).get("attention", 0),
        },
        "_cache": {"hit": False, "ttl_s": CACHE_TTL_S},
        "_degraded_sections": failed_sections,  # operators see which sections fell back to empty
    }

    # ── Cache write (only on at least partial success) ────────
    # We intentionally cache even on partial failures — a stale-ish
    # panel is better than 7 fresh slow queries on the next poll.
    try:
        redis_service.set_json(CACHE_NS, CACHE_KEY, payload, ttl=CACHE_TTL_S)
    except Exception as e:
        logger.debug(f"command-center cache write failed: {e}")

    return payload


# ── Split Command Center endpoints (parallel loading) ──

@router.get("/command-center/fleet")
async def get_command_center_fleet(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Fleet safety scores + twin evolution shifts."""
    from app.services.safety_score_engine import calculate_fleet_safety

    fleet = await calculate_fleet_safety(session)

    # Twin Evolution Shifts
    shift_rows = (await session.execute(text("""
        SELECT tes.device_id, d.device_identifier,
               tes.week_start, tes.movement_frequency, tes.active_hours,
               tes.avg_battery, tes.avg_signal, tes.anomaly_count,
               tes.week_number
        FROM twin_evolution_snapshots tes
        JOIN devices d ON tes.device_id = d.id
        WHERE tes.week_number >= 2
        ORDER BY tes.device_id, tes.week_start
    """))).fetchall()

    device_snapshots = {}
    for r in shift_rows:
        did = str(r.device_id)
        if did not in device_snapshots:
            device_snapshots[did] = {"identifier": r.device_identifier, "weeks": []}
        device_snapshots[did]["weeks"].append({
            "week_start": r.week_start.isoformat(),
            "week_number": r.week_number,
            "movement_frequency": float(r.movement_frequency or 0),
            "active_hours": float(r.active_hours or 0),
            "avg_battery": float(r.avg_battery or 0),
            "avg_signal": float(r.avg_signal or 0),
        })

    evolution_shifts = []
    for did, info in device_snapshots.items():
        weeks = info["weeks"]
        if len(weeks) < 2:
            continue
        first, last = weeks[0], weeks[-1]
        for metric, label, threshold in [
            ("movement_frequency", "Movement", -20),
            ("active_hours", "Active hours", -20),
            ("avg_battery", "Battery", -15),
            ("avg_signal", "Signal", -20),
        ]:
            if first[metric] != 0:
                change = ((last[metric] - first[metric]) / abs(first[metric])) * 100
                if change <= threshold:
                    evolution_shifts.append({
                        "device_id": did,
                        "device_identifier": info["identifier"],
                        "metric": metric, "label": label,
                        "change_percent": round(change, 1),
                        "from_value": round(first[metric], 1),
                        "to_value": round(last[metric], 1),
                        "weeks_span": len(weeks),
                        "severity": "high" if abs(change) > 40 else "medium",
                    })
    evolution_shifts.sort(key=lambda s: abs(s["change_percent"]), reverse=True)

    return {
        "fleet_safety": {
            "fleet_score": fleet["fleet_score"],
            "fleet_status": fleet["fleet_status"],
            "device_count": fleet["device_count"],
            "status_breakdown": fleet["status_breakdown"],
            "devices": [
                {"device_id": d["device_id"], "device_identifier": d["device_identifier"],
                 "safety_score": d["safety_score"], "status": d["status"]}
                for d in fleet["devices"]
            ],
        },
        "evolution_shifts": evolution_shifts,
    }


@router.get("/command-center/risk")
async def get_command_center_risk(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Predictive alerts + risk forecast highlights."""
    pred_rows = (await session.execute(text("""
        SELECT pr.device_id, d.device_identifier,
               pr.prediction_type, pr.prediction_score, pr.confidence, pr.explanation,
               pr.prediction_window_hours, pr.created_at
        FROM predictive_risks pr
        JOIN devices d ON pr.device_id = d.id
        WHERE pr.is_active = true AND pr.prediction_score >= 0.5
        ORDER BY pr.prediction_score DESC
        LIMIT 15
    """))).fetchall()

    predictive_alerts = [
        {
            "device_id": str(r.device_id), "device_identifier": r.device_identifier,
            "prediction_type": r.prediction_type,
            "score": round(r.prediction_score, 3), "confidence": round(r.confidence, 3),
            "explanation": r.explanation, "window_hours": r.prediction_window_hours,
        }
        for r in pred_rows
    ]

    forecast_rows = (await session.execute(text("""
        SELECT rf.device_id, d.device_identifier,
               rf.bucket_name, rf.bucket_start, rf.bucket_end,
               rf.risk_score, rf.risk_level, rf.reason
        FROM risk_forecasts rf
        JOIN devices d ON rf.device_id = d.id
        WHERE rf.risk_level IN ('HIGH', 'MEDIUM')
          AND rf.created_at > NOW() - INTERVAL '30 minutes'
        ORDER BY rf.risk_score DESC
        LIMIT 15
    """))).fetchall()

    forecast_highlights = [
        {
            "device_id": str(r.device_id), "device_identifier": r.device_identifier,
            "bucket": r.bucket_name.replace("_", " ").title(),
            "start_hour": r.bucket_start, "end_hour": r.bucket_end,
            "risk_score": round(r.risk_score, 3), "risk_level": r.risk_level,
            "reason": r.reason,
        }
        for r in forecast_rows
    ]

    return {
        "predictive_alerts": predictive_alerts,
        "forecast_highlights": forecast_highlights,
    }


@router.get("/command-center/incidents")
async def get_command_center_incidents(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Active incidents."""
    incident_rows = (await session.execute(text("""
        SELECT i.id, i.device_id, d.device_identifier, s.full_name AS senior_name,
               i.incident_type, i.severity, i.status, i.escalation_level,
               i.created_at, i.is_test
        FROM incidents i
        JOIN devices d ON i.device_id = d.id
        JOIN seniors s ON i.senior_id = s.id
        WHERE i.status NOT IN ('resolved', 'false_alarm')
        ORDER BY
            CASE i.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
            i.created_at DESC
        LIMIT 20
    """))).fetchall()

    return {
        "active_incidents": [
            {
                "id": str(r.id), "device_id": str(r.device_id),
                "device_identifier": r.device_identifier, "senior_name": r.senior_name,
                "incident_type": r.incident_type, "severity": r.severity,
                "status": r.status, "escalation_level": r.escalation_level,
                "created_at": r.created_at.isoformat(), "is_test": r.is_test,
            }
            for r in incident_rows
        ],
    }


@router.get("/command-center/environment")
async def get_command_center_environment(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Environmental risk + life pattern alerts."""
    from app.services.life_pattern_engine import get_fleet_life_pattern_alerts
    from app.services.environment_risk_engine import get_fleet_environment_status

    import asyncio
    life_alerts, env_status = await asyncio.gather(
        get_fleet_life_pattern_alerts(session),
        get_fleet_environment_status(session),
    )

    return {
        "life_pattern_alerts": life_alerts,
        "environment_status": env_status,
    }


# ── Live Route Monitoring ──

@router.post("/route-monitor")
async def assign_route_monitor_endpoint(
    device_id: str,
    route_index: int = 0,
    start_lat: float = 0, start_lng: float = 0,
    end_lat: float = 0, end_lng: float = 0,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
    body: dict = None,
):
    """Assign a route to a device for live monitoring."""
    from app.services.route_monitor_service import assign_route_monitor

    if not body or "route_data" not in body:
        raise HTTPException(status_code=400, detail="route_data is required in request body")

    result = await assign_route_monitor(
        session, device_id, body["route_data"], route_index,
        start_lat, start_lng, end_lat, end_lng,
    )
    return result


@router.get("/route-monitor/{device_id}")
async def get_route_monitor_status(
    device_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Check device position against its active monitored route."""
    from app.services.route_monitor_service import get_device_route_status

    result = await get_device_route_status(session, device_id)
    if result is None:
        return {"status": "none", "message": "No active route monitor for this device"}
    return result


@router.get("/route-monitors")
async def list_active_route_monitors(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """List all active route monitors for the Command Center."""
    from app.services.route_monitor_service import get_fleet_route_monitors
    return {"monitors": await get_fleet_route_monitors(session)}


@router.delete("/route-monitor/{device_id}")
async def cancel_route_monitor(
    device_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Cancel active route monitoring for a device."""
    # First, delete any old cancelled monitors to prevent unique constraint issues
    await session.execute(text("""
        DELETE FROM active_route_monitors 
        WHERE device_id = :did AND status != 'active'
    """), {"did": device_id})
    
    # Now cancel the active one
    result = await session.execute(text("""
        UPDATE active_route_monitors SET status = 'cancelled', completed_at = NOW()
        WHERE device_id = :did AND status = 'active'
        RETURNING id
    """), {"did": device_id})
    row = result.fetchone()
    await session.commit()
    if not row:
        return {"status": "none", "message": "No active monitor to cancel"}
    return {"status": "cancelled", "monitor_id": str(row.id)}



# ── Dynamic Rerouting Endpoints ──

@router.post("/route-monitor/{device_id}/reroute")
async def suggest_device_reroute(
    device_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Evaluate alternative routes from device's current position to destination."""
    from app.services.route_monitor_service import suggest_reroute
    return await suggest_reroute(session, device_id)


@router.post("/route-monitor/{device_id}/accept-reroute")
async def accept_device_reroute(
    device_id: str,
    body: dict,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Accept a reroute suggestion — replaces the current monitored route."""
    from app.services.route_monitor_service import accept_reroute
    if not body or "route_data" not in body:
        raise HTTPException(status_code=400, detail="route_data is required")
    return await accept_reroute(session, device_id, body["route_data"])


@router.get("/route-monitor/{device_id}/risk-update")
async def recalculate_device_route_risk(
    device_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Recalculate route risk for the active monitor using current conditions."""
    from app.services.route_monitor_service import recalculate_route_risk
    return await recalculate_route_risk(session, device_id)



# ── Notification Endpoints ──

@router.post("/notifications/send")
async def send_alert_notification(
    body: dict,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Manually trigger a notification for a device."""
    from app.services.route_alert_service import dispatch_route_alert

    required = ["device_id", "event_type", "severity", "title", "message"]
    for field in required:
        if field not in body:
            raise HTTPException(status_code=400, detail=f"Missing field: {field}")

    result = await dispatch_route_alert(
        session, body["device_id"], body["event_type"],
        body["severity"], body["title"], body["message"],
        body.get("metadata"),
    )
    return result


@router.get("/notifications/log")
async def get_notifications_log(
    device_id: str = None,
    limit: int = 50,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Get notification history, optionally filtered by device."""
    from app.services.route_alert_service import get_notification_history
    return {"notifications": await get_notification_history(session, device_id=device_id, limit=limit)}


@router.get("/notifications/log/{device_id}")
async def get_device_notifications(
    device_id: str,
    limit: int = 50,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Get notification history for a specific device."""
    from app.services.route_alert_service import get_notification_history
    return {"notifications": await get_notification_history(session, device_id=device_id, limit=limit)}


@router.post("/notifications/{notification_id}/acknowledge")
async def acknowledge_alert(
    notification_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin", "guardian")),
):
    """Mark a notification as acknowledged."""
    from app.services.route_alert_service import acknowledge_notification
    success = await acknowledge_notification(session, notification_id)
    if not success:
        raise HTTPException(status_code=404, detail="Notification not found or already acknowledged")
    return {"status": "acknowledged", "notification_id": notification_id}


# ── Guardian AI Decision Engine (Escalation Management) ──

@router.post("/incidents/{incident_id}/acknowledge")
async def acknowledge_incident_endpoint(
    incident_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin", "guardian")),
):
    """Acknowledge an incident, stopping further auto-escalation."""
    from app.services.route_alert_service import acknowledge_incident
    success = await acknowledge_incident(session, incident_id, str(user.id))
    if not success:
        raise HTTPException(status_code=404, detail="Incident not found or already acknowledged")
    return {"status": "acknowledged", "incident_id": incident_id}


@router.get("/escalation/config")
async def get_escalation_config(
    user: User = Depends(require_role("operator", "admin")),
):
    """Get current escalation configuration."""
    from app.services.escalation_scheduler import L1_ONLY_INCIDENT_TYPES
    from app.core.config import settings as _settings
    return {
        "timers": {
            "level1_minutes": _settings.escalation_l1_minutes,
            "level2_minutes": _settings.escalation_l2_minutes,
            "level3_minutes": _settings.escalation_l3_minutes,
        },
        "levels": {
            "level1": {"target": "Primary Guardian", "channels": ["email", "sms", "push", "sse"]},
            "level2": {"target": "Secondary Contacts", "channels": ["email", "sms"]},
            "level3": {"target": "All Operators", "channels": ["email", "sms", "push"]},
        },
        "l1_only_types": list(L1_ONLY_INCIDENT_TYPES),
        "acknowledgment_stops_escalation": True,
        "check_interval_seconds": _settings.escalation_check_interval,
    }


@router.get("/escalation/pending")
async def get_pending_escalations(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Get incidents about to escalate with time remaining."""
    from datetime import datetime, timezone, timedelta
    from app.core.config import settings as _settings

    now = datetime.now(timezone.utc)

    rows = (await session.execute(text("""
        SELECT i.id, i.incident_type, i.severity, i.status,
               i.escalation_level, i.escalated, i.created_at,
               i.escalated_at, i.level2_escalated_at, i.level3_escalated_at,
               i.acknowledged_at, i.acknowledged_by_user_id,
               i.escalation_minutes,
               s.full_name as senior_name,
               d.device_identifier,
               u.email as guardian_email
        FROM incidents i
        JOIN seniors s ON i.senior_id = s.id
        JOIN devices d ON i.device_id = d.id
        JOIN users u ON s.guardian_id = u.id
        WHERE i.status = 'open' AND i.acknowledged_at IS NULL
        ORDER BY i.created_at ASC
        LIMIT 50
    """))).fetchall()

    l1_min = _settings.escalation_l1_minutes
    l2_min = _settings.escalation_l2_minutes
    l3_min = _settings.escalation_l3_minutes

    pending = []
    for r in rows:
        created = r.created_at
        level = r.escalation_level
        age_min = (now - created).total_seconds() / 60

        # Determine next escalation
        if not r.escalated:
            next_level = 1
            next_at = created + timedelta(minutes=l1_min)
        elif level == 1 and r.level2_escalated_at is None:
            next_level = 2
            next_at = created + timedelta(minutes=l2_min)
        elif level == 2 and r.level3_escalated_at is None:
            next_level = 3
            next_at = created + timedelta(minutes=l3_min)
        else:
            # Fully escalated — skip from pending list
            continue

        time_remaining_s = max(0, (next_at - now).total_seconds()) if next_at else None

        pending.append({
            "incident_id": str(r.id),
            "incident_type": r.incident_type,
            "severity": r.severity,
            "senior_name": r.senior_name,
            "device_identifier": r.device_identifier,
            "guardian_email": r.guardian_email,
            "current_level": level,
            "next_escalation_level": next_level,
            "time_remaining_seconds": round(time_remaining_s) if time_remaining_s is not None else None,
            "overdue": time_remaining_s == 0 if time_remaining_s is not None else False,
            "age_minutes": round(age_min, 1),
            "created_at": created.isoformat(),
        })

    return {
        "count": len(pending),
        "pending": pending,
        "config": {
            "l1_minutes": l1_min,
            "l2_minutes": l2_min,
            "l3_minutes": l3_min,
        },
    }


@router.get("/escalation/history")
async def get_escalation_history(
    limit: int = 20,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Get recent escalation events."""
    rows = (await session.execute(text("""
        SELECT i.id, i.incident_type, i.severity,
               i.escalation_level, i.escalated_at, i.level2_escalated_at, i.level3_escalated_at,
               i.acknowledged_at, i.acknowledged_by_user_id, i.status,
               i.created_at, i.resolved_at,
               s.full_name as senior_name,
               d.device_identifier,
               ack_u.email as acknowledged_by_email
        FROM incidents i
        JOIN seniors s ON i.senior_id = s.id
        JOIN devices d ON i.device_id = d.id
        LEFT JOIN users ack_u ON i.acknowledged_by_user_id = ack_u.id
        WHERE i.escalated = TRUE
        ORDER BY i.escalated_at DESC NULLS LAST
        LIMIT :lim
    """), {"lim": limit})).fetchall()

    return [{
        "incident_id": str(r.id),
        "incident_type": r.incident_type,
        "severity": r.severity,
        "senior_name": r.senior_name,
        "device_identifier": r.device_identifier,
        "escalation_level": r.escalation_level,
        "escalated_at": r.escalated_at.isoformat() if r.escalated_at else None,
        "level2_at": r.level2_escalated_at.isoformat() if r.level2_escalated_at else None,
        "level3_at": r.level3_escalated_at.isoformat() if r.level3_escalated_at else None,
        "acknowledged_at": r.acknowledged_at.isoformat() if r.acknowledged_at else None,
        "acknowledged_by": r.acknowledged_by_email,
        "status": r.status,
        "created_at": r.created_at.isoformat(),
        "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
        "response_time_min": round((r.acknowledged_at - r.created_at).total_seconds() / 60, 1) if r.acknowledged_at else None,
    } for r in rows]



@router.get("/escalation/smart-profile/{guardian_id}")
async def get_smart_guardian_profile(
    guardian_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Get AI-generated response profile for a guardian."""
    from app.services.smart_escalation_engine import build_guardian_profile
    return await build_guardian_profile(session, guardian_id)


@router.get("/escalation/smart-recommendation/{incident_id}")
async def get_smart_escalation_recommendation(
    incident_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Get AI-recommended adaptive escalation timers for an incident."""
    from app.services.smart_escalation_engine import compute_adaptive_timers
    result = await compute_adaptive_timers(session, incident_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ── AI Adaptive Risk Learning ──

@router.get("/risk-learning/stats")
async def get_risk_learning_stats(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Get learning statistics and hotspot zones."""
    from app.services.adaptive_risk_engine import get_learning_stats
    return await get_learning_stats(session)


@router.get("/risk-learning/hotspots")
async def get_learned_hotspots(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Get all learned hotspot zones."""
    from app.services.adaptive_risk_engine import get_learning_stats
    stats = await get_learning_stats(session)
    return {"hotspots": stats["learned_zones"], "count": stats["learned_zones_count"]}


@router.post("/risk-learning/recalculate")
async def trigger_risk_recalculation(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Manually trigger risk learning recalculation."""
    from app.services.adaptive_risk_engine import analyze_and_update_hotspots
    stats = await analyze_and_update_hotspots(session)
    return {"status": "completed", **stats}


@router.get("/risk-learning/trends")
async def get_hotspot_trends(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Get trend analysis for all learned hotspot zones."""
    from app.services.hotspot_trend_engine import get_all_trends
    return await get_all_trends(session)


@router.get("/risk-learning/trend-stats")
async def get_trend_stats(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Get high-level trend summary statistics."""
    from app.services.hotspot_trend_engine import get_trend_summary
    return await get_trend_summary(session)


@router.get("/risk-learning/hotspots/{zone_id}/trend")
async def get_single_zone_trend(
    zone_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Get detailed trend for a specific hotspot zone."""
    from app.services.hotspot_trend_engine import get_zone_trend
    result = await get_zone_trend(session, zone_id)
    if result is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Zone not found")
    return result


@router.get("/risk-learning/forecast")
async def get_risk_forecasts(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Get predictive risk forecasts for all learned hotspot zones."""
    from app.services.risk_forecast_engine import get_all_forecasts
    return await get_all_forecasts(session)


@router.get("/risk-learning/forecast-stats")
async def get_forecast_stats(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Get lightweight forecast summary statistics."""
    from app.services.risk_forecast_engine import get_forecast_summary
    return await get_forecast_summary(session)


@router.get("/risk-learning/hotspots/{zone_id}/forecast")
async def get_single_zone_forecast(
    zone_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Get detailed forecast for a specific hotspot zone."""
    from app.services.risk_forecast_engine import get_zone_forecast
    result = await get_zone_forecast(session, zone_id)
    if result is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Zone not found")
    return result


# ── Human Activity Risk AI ────────────────────────────────────

@router.get("/human-activity-risk/assess")
async def assess_activity_risk(
    lat: float,
    lng: float,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Assess human activity risk at a specific location."""
    from app.services.human_activity_risk_engine import assess_location_activity_risk
    return await assess_location_activity_risk(session, lat, lng)


@router.get("/human-activity-risk/fleet")
async def get_fleet_activity(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Get human activity risk overlay for all fleet devices."""
    from app.services.human_activity_risk_engine import get_fleet_activity_risk
    return await get_fleet_activity_risk(session)


@router.get("/human-activity-risk/hotspots")
async def get_activity_hotspots(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Get activity risk analysis for all learned hotspot zones."""
    from app.services.human_activity_risk_engine import get_activity_hotspots
    return await get_activity_hotspots(session)


# ── Forecast Simulation Lab ────────────────────────────────────

@router.get("/simulate/forecast-scenarios")
async def list_forecast_scenarios(
    user: User = Depends(require_role("operator", "admin")),
):
    """List available forecast simulation scenario types."""
    from app.services.forecast_simulation_engine import get_available_scenarios
    return get_available_scenarios()


@router.post("/simulate/forecast-scenario")
async def run_forecast_sim(
    payload: dict,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Run a what-if forecast simulation scenario."""
    from app.services.forecast_simulation_engine import run_forecast_scenario
    return await run_forecast_scenario(session, payload)


@router.get("/notifications/preferences/{user_id}")
async def get_notification_preferences(
    user_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin", "guardian")),
):
    """Get notification preferences for a user."""
    row = (await session.execute(text("""
        SELECT push_enabled, sms_enabled, in_app_enabled,
               severity_threshold, quiet_hours_start, quiet_hours_end
        FROM notification_preferences WHERE user_id = :uid
    """), {"uid": user_id})).fetchone()

    if not row:
        return {"push_enabled": True, "sms_enabled": True, "in_app_enabled": True,
                "severity_threshold": "low", "quiet_hours_start": None, "quiet_hours_end": None}

    return {
        "push_enabled": row.push_enabled, "sms_enabled": row.sms_enabled,
        "in_app_enabled": row.in_app_enabled,
        "severity_threshold": row.severity_threshold,
        "quiet_hours_start": row.quiet_hours_start, "quiet_hours_end": row.quiet_hours_end,
    }


@router.put("/notifications/preferences/{user_id}")
async def update_notification_preferences(
    user_id: str,
    body: dict,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin", "guardian")),
):
    """Update notification preferences."""
    await session.execute(text("""
        INSERT INTO notification_preferences (user_id, push_enabled, sms_enabled, in_app_enabled, severity_threshold, quiet_hours_start, quiet_hours_end, updated_at)
        VALUES (:uid, :push, :sms, :inapp, :threshold, :qs, :qe, NOW())
        ON CONFLICT (user_id) DO UPDATE SET
            push_enabled = :push, sms_enabled = :sms, in_app_enabled = :inapp,
            severity_threshold = :threshold, quiet_hours_start = :qs, quiet_hours_end = :qe,
            updated_at = NOW()
    """), {
        "uid": user_id,
        "push": body.get("push_enabled", True),
        "sms": body.get("sms_enabled", True),
        "inapp": body.get("in_app_enabled", True),
        "threshold": body.get("severity_threshold", "low"),
        "qs": body.get("quiet_hours_start"),
        "qe": body.get("quiet_hours_end"),
    })
    await session.commit()
    return {"status": "updated"}


@router.get("/notifications/providers")
async def get_notification_providers(
    user: User = Depends(require_role("operator", "admin")),
):
    """Check which notification providers are live vs stub."""
    import os
    from app.core.config import settings

    sa_path = settings.firebase_sa_key_path
    has_firebase = (sa_path and os.path.exists(sa_path)) or bool(settings.firebase_sa_key_json)
    has_twilio = bool(settings.twilio_account_sid and settings.twilio_auth_token)
    has_ses = bool(settings.aws_access_key_id and settings.aws_secret_access_key)

    return {
        "sms": {"provider": "twilio" if has_twilio else "stub", "live": has_twilio},
        "push": {"provider": "fcm" if has_firebase else "stub", "live": has_firebase},
        "email": {"provider": "ses" if has_ses else "stub", "live": has_ses},
        "in_app": {"provider": "native", "live": True},
    }



# ── Incident Replay ──

@router.get("/incidents/{incident_id}/replay")
async def get_incident_replay(
    incident_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Get full replay dataset for an incident."""
    from app.services.incident_replay_engine import get_incident_replay, generate_replay_narrative

    replay = await get_incident_replay(session, incident_id)
    if not replay:
        raise HTTPException(status_code=404, detail="Incident not found")

    # Generate AI narrative
    narrative = await generate_replay_narrative(session, replay)
    replay["ai_narrative"] = narrative

    return replay


@router.get("/incidents/{incident_id}/timeline")
async def get_incident_timeline(
    incident_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Get concise timeline summary for an incident."""
    from app.services.incident_replay_engine import get_incident_replay

    replay = await get_incident_replay(session, incident_id)
    if not replay:
        raise HTTPException(status_code=404, detail="Incident not found")

    return {
        "incident_id": replay["incident_id"],
        "device_identifier": replay["device_identifier"],
        "incident_type": replay["incident_type"],
        "severity": replay["severity"],
        "incident_time": replay["incident_time"],
        "events": replay["events"],
        "replay_window": replay["replay_window"],
    }


# ── Automated Patrol Routing AI ──

@router.get("/patrol/generate")
async def generate_patrol_route_endpoint(
    shift: str = Query("morning", description="Shift: morning, afternoon, night"),
    max_zones: int = Query(15, ge=1, le=30, description="Maximum zones in route"),
    dwell_minutes: int = Query(10, ge=5, le=30, description="Minutes per zone stop"),
    start_lat: Optional[float] = Query(None, description="Patrol start latitude"),
    start_lng: Optional[float] = Query(None, description="Patrol start longitude"),
    use_heatmap: bool = Query(False, description="Enable city heatmap boost scoring"),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Generate an optimized patrol route using composite AI scoring + TSP optimization."""
    from app.services.patrol_routing_engine import generate_patrol_route

    if shift not in ("morning", "afternoon", "night"):
        raise HTTPException(status_code=422, detail="Invalid shift. Must be: morning, afternoon, night")

    result = await generate_patrol_route(
        session,
        shift=shift,
        start_lat=start_lat,
        start_lng=start_lng,
        max_zones=max_zones,
        dwell_minutes=dwell_minutes,
        use_heatmap=use_heatmap,
    )
    return result


@router.get("/patrol/summary")
async def get_patrol_summary_endpoint(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Lightweight patrol summary for Command Center widget."""
    from app.services.patrol_routing_engine import get_patrol_summary
    return await get_patrol_summary(session)


@router.get("/patrol/shifts")
async def get_patrol_shifts(
    user: User = Depends(require_role("operator", "admin")),
):
    """Get available shift definitions."""
    from app.services.patrol_routing_engine import SHIFTS
    return {
        "shifts": [
            {"id": k, "label": v["label"], "start_hour": v["start"], "end_hour": v["end"]}
            for k, v in SHIFTS.items()
        ],
        "weights": {
            "forecast": 0.30,
            "trend": 0.25,
            "activity": 0.20,
            "learning": 0.15,
            "temporal": 0.10,
        },
    }


# ── City-Scale Safety Heatmap (Dynamic Risk Engine — Phase 39) ──

@router.get("/city-heatmap")
async def get_city_heatmap(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Generate city-scale safety heatmap with 8 AI signal layers."""
    from app.services.dynamic_risk_engine import compute_city_risk_snapshot
    return await compute_city_risk_snapshot(session)


@router.get("/city-heatmap/live")
async def get_city_heatmap_live(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Get pre-computed live heatmap from cache (<50ms). Falls back to compute."""
    from app.services.dynamic_risk_engine import get_live_heatmap, compute_city_risk_snapshot
    cached = get_live_heatmap()
    if cached:
        return cached
    return await compute_city_risk_snapshot(session)


@router.get("/city-heatmap/delta")
async def get_city_heatmap_delta(
    user: User = Depends(require_role("operator", "admin")),
):
    """Get risk changes since last computation cycle."""
    from app.services.dynamic_risk_engine import get_heatmap_delta
    delta = get_heatmap_delta()
    if not delta:
        return {"escalated": [], "de_escalated": [], "new_hotspots": [], "cooling": [],
                "escalated_count": 0, "de_escalated_count": 0, "new_hotspot_count": 0, "cooling_count": 0, "net_change": 0}
    return delta


@router.get("/city-heatmap/timeline")
async def get_city_heatmap_timeline(
    limit: int = 12,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Get last 12 risk snapshots (1 hour history) for timeline scrubber."""
    from app.services.dynamic_risk_engine import get_heatmap_timeline, get_db_timeline
    timeline = get_heatmap_timeline()
    if timeline:
        return {"timeline": timeline, "source": "cache"}
    db_timeline = await get_db_timeline(session, limit=limit)
    return {"timeline": db_timeline, "source": "database"}


@router.get("/city-heatmap/status")
async def get_city_heatmap_status(
    user: User = Depends(require_role("operator", "admin")),
):
    """Get dynamic risk engine cache status."""
    from app.services.dynamic_risk_engine import get_cache_status
    return get_cache_status()


@router.get("/city-heatmap/stats")
async def get_city_heatmap_stats(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Lightweight heatmap summary for Command Center widget."""
    from app.services.dynamic_risk_engine import get_heatmap_stats
    return await get_heatmap_stats(session)


@router.get("/city-heatmap/cell/{grid_id}")
async def get_city_heatmap_cell(
    grid_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Get detailed breakdown for a specific grid cell (8 signals)."""
    from app.services.dynamic_risk_engine import get_cell_detail
    result = await get_cell_detail(session, grid_id)
    if not result:
        raise HTTPException(status_code=404, detail="Cell not found")
    return result


# ── Operator Dashboard Endpoints ──

@router.get("/dashboard/metrics")
async def get_operator_metrics(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Get operator dashboard summary metrics."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    from app.models.caregiver import CaregiverStatus

    # Incident counts
    active_sos = (await session.execute(
        select(func.count()).select_from(Incident).where(
            Incident.severity == "critical", Incident.status.in_(["open", "in_progress"])
        )
    )).scalar() or 0

    new_alerts = (await session.execute(
        select(func.count()).select_from(Incident).where(Incident.status == "open")
    )).scalar() or 0

    assigned = (await session.execute(
        select(func.count()).select_from(Incident).where(
            Incident.assigned_to_user_id.isnot(None),
            Incident.status.in_(["open", "in_progress"])
        )
    )).scalar() or 0

    resolved_today = (await session.execute(
        select(func.count()).select_from(Incident).where(
            Incident.status == "resolved",
            Incident.resolved_at >= today_start,
        )
    )).scalar() or 0

    # Caregiver counts
    caregivers_online = (await session.execute(
        select(func.count()).select_from(CaregiverStatus).where(
            CaregiverStatus.status.in_(["available", "busy"])
        )
    )).scalar() or 0

    return {
        "active_sos": active_sos,
        "new_alerts": new_alerts,
        "assigned": assigned,
        "resolved_today": resolved_today,
        "caregivers_online": caregivers_online,
    }


@router.get("/dashboard/caregivers")
async def get_operator_caregivers(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """List all caregivers with their status for assignment."""
    from app.models.caregiver import CaregiverStatus

    # Get all caregiver-role users
    result = await session.execute(
        select(User).where(User.role == "caregiver", User.is_active == True)
    )
    caregivers = result.scalars().all()

    data = []
    for cg in caregivers:
        status = (await session.execute(
            select(CaregiverStatus).where(CaregiverStatus.user_id == cg.id)
        )).scalar_one_or_none()

        data.append({
            "id": str(cg.id),
            "full_name": cg.full_name or cg.email.split("@")[0],
            "email": cg.email,
            "phone": cg.phone,
            "facility_id": cg.facility_id,
            "status": status.status if status else "offline",
            "current_assignment_id": str(status.current_assignment_id) if status and status.current_assignment_id else None,
        })

    return {"caregivers": data, "total": len(data)}


@router.post("/incidents/{incident_id}/assign")
async def assign_incident(
    incident_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
    caregiver_id: str = None,
):
    """Assign an incident to a caregiver."""
    from app.models.caregiver import CaregiverStatus

    inc = (await session.execute(
        select(Incident).where(Incident.id == uuid_mod.UUID(incident_id))
    )).scalar_one_or_none()
    if not inc:
        raise HTTPException(404, "Incident not found")

    now = datetime.now(timezone.utc)

    if caregiver_id:
        cg_user = (await session.execute(
            select(User).where(User.id == uuid_mod.UUID(caregiver_id))
        )).scalar_one_or_none()
        if not cg_user:
            raise HTTPException(404, "Caregiver not found")

        inc.assigned_to_user_id = cg_user.id
        inc.assigned_at = now
        inc.assigned_by_user_id = user.id

        # Update caregiver status
        cg_status = (await session.execute(
            select(CaregiverStatus).where(CaregiverStatus.user_id == cg_user.id)
        )).scalar_one_or_none()
        if cg_status:
            cg_status.status = "busy"
            cg_status.current_assignment_id = inc.id
            cg_status.updated_at = now
        else:
            session.add(CaregiverStatus(
                user_id=cg_user.id, status="busy",
                current_assignment_id=inc.id, updated_at=now,
            ))

    await session.commit()
    return {
        "assigned": True,
        "incident_id": incident_id,
        "caregiver_id": caregiver_id,
        "assigned_at": now.isoformat(),
    }


@router.post("/incidents/{incident_id}/escalate")
async def escalate_incident(
    incident_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
):
    """Manually escalate an incident to the next level."""
    inc = (await session.execute(
        select(Incident).where(Incident.id == uuid_mod.UUID(incident_id))
    )).scalar_one_or_none()
    if not inc:
        raise HTTPException(404, "Incident not found")

    now = datetime.now(timezone.utc)
    inc.escalated = True
    inc.escalated_at = inc.escalated_at or now
    inc.escalation_level = min(inc.escalation_level + 1, 3)

    if inc.escalation_level == 2:
        inc.level2_escalated_at = now
    elif inc.escalation_level == 3:
        inc.level3_escalated_at = now

    await session.commit()
    return {
        "escalated": True,
        "incident_id": incident_id,
        "escalation_level": inc.escalation_level,
    }


@router.patch("/incidents/{incident_id}/status")
async def update_incident_status(
    incident_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("operator", "admin")),
    new_status: str = "in_progress",
):
    """Update incident status: open, in_progress, resolved."""
    inc = (await session.execute(
        select(Incident).where(Incident.id == uuid_mod.UUID(incident_id))
    )).scalar_one_or_none()
    if not inc:
        raise HTTPException(404, "Incident not found")

    now = datetime.now(timezone.utc)
    inc.status = new_status
    if new_status == "resolved":
        inc.resolved_at = now

    await session.commit()
    return {"status": new_status, "incident_id": incident_id}
