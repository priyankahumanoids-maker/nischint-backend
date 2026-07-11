# Smart Escalation Engine
# Learns from historical incident response patterns to dynamically adjust escalation windows.

import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

logger = logging.getLogger(__name__)

# Time-of-day buckets
TOD_NIGHT = "night"          # 10pm - 6am
TOD_MORNING = "morning"      # 6am - 12pm
TOD_AFTERNOON = "afternoon"  # 12pm - 6pm
TOD_EVENING = "evening"      # 6pm - 10pm

TOD_FACTORS = {
    TOD_NIGHT: 0.6,      # Faster escalation at night (guardians asleep)
    TOD_MORNING: 0.85,
    TOD_AFTERNOON: 1.0,   # Normal during business hours
    TOD_EVENING: 0.9,
}

SEVERITY_FACTORS = {
    "critical": 0.65,    # Fastest escalation for critical
    "high": 0.8,
    "medium": 1.0,
    "low": 1.3,          # More patience for low-severity
}

SKIP_L1_RESPONSE_RATE = 0.30   # Skip L1 if guardian responds < 30% of the time
SLOW_RESPONDER_RATE = 0.50     # Compress L1 if guardian responds < 50%
MIN_TIMER_MINUTES = 1          # Floor — never go below 1 min
MIN_INCIDENTS_FOR_PROFILE = 3  # Need at least 3 incidents for reliable profile


def _get_tod_bucket(hour: int) -> str:
    if 22 <= hour or hour < 6:
        return TOD_NIGHT
    if 6 <= hour < 12:
        return TOD_MORNING
    if 12 <= hour < 18:
        return TOD_AFTERNOON
    return TOD_EVENING


async def build_guardian_profile(session: AsyncSession, guardian_id: str) -> dict:
    """Build a behavioral response profile for a guardian from historical data."""

    # Fetch all incidents linked to this guardian's seniors
    rows = (await session.execute(text("""
        SELECT i.id, i.incident_type, i.severity, i.status,
               i.created_at, i.acknowledged_at, i.escalation_level,
               EXTRACT(HOUR FROM i.created_at) as created_hour
        FROM incidents i
        JOIN seniors s ON i.senior_id = s.id
        WHERE s.guardian_id = :gid
        ORDER BY i.created_at DESC
        LIMIT 200
    """), {"gid": guardian_id})).fetchall()

    if not rows:
        return _empty_profile(guardian_id)

    total = len(rows)
    acked = [r for r in rows if r.acknowledged_at is not None]
    acked_count = len(acked)
    response_rate = acked_count / total if total > 0 else 0

    # Average response time (for acknowledged incidents)
    response_times = []
    for r in acked:
        delta = (r.acknowledged_at - r.created_at).total_seconds() / 60
        if delta > 0:
            response_times.append(delta)
    avg_response = sum(response_times) / len(response_times) if response_times else None

    # Response by time-of-day
    tod_stats = {}
    for bucket in [TOD_NIGHT, TOD_MORNING, TOD_AFTERNOON, TOD_EVENING]:
        bucket_rows = [r for r in rows if _get_tod_bucket(int(r.created_hour)) == bucket]
        bucket_acked = [r for r in bucket_rows if r.acknowledged_at is not None]
        bucket_times = []
        for r in bucket_acked:
            delta = (r.acknowledged_at - r.created_at).total_seconds() / 60
            if delta > 0:
                bucket_times.append(delta)
        tod_stats[bucket] = {
            "count": len(bucket_rows),
            "acknowledged": len(bucket_acked),
            "rate": len(bucket_acked) / len(bucket_rows) if bucket_rows else 0,
            "avg_minutes": round(sum(bucket_times) / len(bucket_times), 1) if bucket_times else None,
        }

    # Response by severity
    sev_stats = {}
    for sev in ["critical", "high", "medium", "low"]:
        sev_rows = [r for r in rows if r.severity == sev]
        sev_acked = [r for r in sev_rows if r.acknowledged_at is not None]
        sev_times = []
        for r in sev_acked:
            delta = (r.acknowledged_at - r.created_at).total_seconds() / 60
            if delta > 0:
                sev_times.append(delta)
        sev_stats[sev] = {
            "count": len(sev_rows),
            "acknowledged": len(sev_acked),
            "rate": len(sev_acked) / len(sev_rows) if sev_rows else 0,
            "avg_minutes": round(sum(sev_times) / len(sev_times), 1) if sev_times else None,
        }

    # Reliability score (0-100)
    reliability = _compute_reliability(response_rate, avg_response, total)

    # Recommendation
    if total < MIN_INCIDENTS_FOR_PROFILE:
        recommendation = "insufficient_data"
    elif response_rate < SKIP_L1_RESPONSE_RATE:
        recommendation = "skip_l1"
    elif response_rate < SLOW_RESPONDER_RATE:
        recommendation = "slow_responder"
    elif avg_response and avg_response > settings.escalation_l1_minutes:
        recommendation = "slow_responder"
    else:
        recommendation = "normal"

    return {
        "guardian_id": guardian_id,
        "total_incidents": total,
        "acknowledged_count": acked_count,
        "response_rate": round(response_rate, 3),
        "avg_response_minutes": round(avg_response, 1) if avg_response else None,
        "response_by_time_of_day": tod_stats,
        "response_by_severity": sev_stats,
        "reliability_score": reliability,
        "recommendation": recommendation,
        "has_sufficient_data": total >= MIN_INCIDENTS_FOR_PROFILE,
    }


def _compute_reliability(response_rate: float, avg_response: float | None, total: int) -> int:
    """Compute a 0-100 reliability score."""
    if total < MIN_INCIDENTS_FOR_PROFILE:
        return 50  # Neutral — insufficient data

    # Response rate component (0-50 points)
    rate_score = min(50, response_rate * 50)

    # Speed component (0-30 points) — faster = higher
    if avg_response is not None:
        if avg_response <= 2:
            speed_score = 30
        elif avg_response <= 5:
            speed_score = 25
        elif avg_response <= 10:
            speed_score = 15
        elif avg_response <= 20:
            speed_score = 8
        else:
            speed_score = 3
    else:
        speed_score = 0

    # Volume component (0-20 points)
    vol_score = min(20, total * 2)

    return min(100, round(rate_score + speed_score + vol_score))


def _empty_profile(guardian_id: str) -> dict:
    return {
        "guardian_id": guardian_id,
        "total_incidents": 0,
        "acknowledged_count": 0,
        "response_rate": 0,
        "avg_response_minutes": None,
        "response_by_time_of_day": {b: {"count": 0, "acknowledged": 0, "rate": 0, "avg_minutes": None}
                                     for b in [TOD_NIGHT, TOD_MORNING, TOD_AFTERNOON, TOD_EVENING]},
        "response_by_severity": {s: {"count": 0, "acknowledged": 0, "rate": 0, "avg_minutes": None}
                                  for s in ["critical", "high", "medium", "low"]},
        "reliability_score": 50,
        "recommendation": "insufficient_data",
        "has_sufficient_data": False,
    }


async def compute_adaptive_timers(session: AsyncSession, incident_id: str) -> dict:
    """Compute adaptive escalation timers for a specific incident."""

    # Fetch incident + guardian info
    row = (await session.execute(text("""
        SELECT i.id, i.incident_type, i.severity, i.created_at, i.is_test,
               s.guardian_id, s.full_name as senior_name,
               u.email as guardian_email,
               EXTRACT(HOUR FROM i.created_at) as created_hour
        FROM incidents i
        JOIN seniors s ON i.senior_id = s.id
        JOIN users u ON s.guardian_id = u.id
        WHERE i.id = :iid
    """), {"iid": incident_id})).fetchone()

    if not row:
        return {"error": "Incident not found"}

    base_l1 = settings.escalation_l1_minutes
    base_l2 = settings.escalation_l2_minutes
    base_l3 = settings.escalation_l3_minutes

    # For test incidents, use test thresholds
    if row.is_test:
        return {
            "incident_id": incident_id,
            "mode": "test",
            "timers": {"l1": 1, "l2": 2, "l3": 3},
            "static_timers": {"l1": base_l1, "l2": base_l2, "l3": base_l3},
            "factors": {},
            "skip_l1": False,
            "reason": "Test incident — using fast test thresholds",
        }

    # Build guardian profile
    profile = await build_guardian_profile(session, str(row.guardian_id))

    # Factor 1: Time-of-day
    tod_bucket = _get_tod_bucket(int(row.created_hour))
    tod_factor = TOD_FACTORS.get(tod_bucket, 1.0)

    # Factor 2: Severity
    severity_factor = SEVERITY_FACTORS.get(row.severity, 1.0)

    # Factor 3: Guardian response behavior
    guardian_factor = 1.0
    skip_l1 = False
    guardian_reason = "normal"

    if profile["has_sufficient_data"]:
        if profile["recommendation"] == "skip_l1":
            skip_l1 = True
            guardian_factor = 0.5
            guardian_reason = f"Guardian responds to only {profile['response_rate']*100:.0f}% of incidents — skip L1, go direct to L2"
        elif profile["recommendation"] == "slow_responder":
            # Compress L1 based on how slow they are
            if profile["avg_response_minutes"] and profile["avg_response_minutes"] > base_l1:
                guardian_factor = 0.7
                guardian_reason = f"Guardian avg response {profile['avg_response_minutes']}min > L1 window {base_l1}min — compressing timers"
            else:
                guardian_factor = 0.85
                guardian_reason = f"Guardian response rate {profile['response_rate']*100:.0f}% below threshold — slightly compressed"

        # Time-of-day specific override
        tod_profile = profile["response_by_time_of_day"].get(tod_bucket, {})
        if tod_profile.get("count", 0) >= 2 and tod_profile.get("rate", 1) < 0.3:
            # Guardian almost never responds during this time bucket
            skip_l1 = True
            guardian_reason = f"Guardian rarely responds during {tod_bucket} hours ({tod_profile['rate']*100:.0f}% rate) — skip L1"

    # Compute adaptive timers
    combined_factor = tod_factor * severity_factor * guardian_factor

    adaptive_l1 = max(MIN_TIMER_MINUTES, round(base_l1 * combined_factor, 1))
    adaptive_l2 = max(MIN_TIMER_MINUTES + 1, round(base_l2 * combined_factor, 1))
    adaptive_l3 = max(MIN_TIMER_MINUTES + 2, round(base_l3 * combined_factor, 1))

    # If skip_l1, set L1 to 0 (immediate L2 escalation)
    if skip_l1:
        adaptive_l1 = 0
        adaptive_l2 = max(MIN_TIMER_MINUTES, round(base_l1 * tod_factor * severity_factor * 0.7, 1))

    reasons = []
    if tod_factor != 1.0:
        reasons.append(f"Time-of-day ({tod_bucket}): {tod_factor}x")
    if severity_factor != 1.0:
        reasons.append(f"Severity ({row.severity}): {severity_factor}x")
    if guardian_factor != 1.0 or skip_l1:
        reasons.append(f"Guardian behavior: {guardian_reason}")

    return {
        "incident_id": incident_id,
        "mode": "adaptive",
        "senior_name": row.senior_name,
        "guardian_email": row.guardian_email,
        "timers": {
            "l1": adaptive_l1,
            "l2": adaptive_l2,
            "l3": adaptive_l3,
        },
        "static_timers": {"l1": base_l1, "l2": base_l2, "l3": base_l3},
        "factors": {
            "time_of_day": {"bucket": tod_bucket, "factor": tod_factor},
            "severity": {"level": row.severity, "factor": severity_factor},
            "guardian": {"factor": guardian_factor, "reason": guardian_reason},
            "combined": round(combined_factor, 3),
        },
        "skip_l1": skip_l1,
        "guardian_profile_summary": {
            "response_rate": profile["response_rate"],
            "avg_response_minutes": profile["avg_response_minutes"],
            "reliability_score": profile["reliability_score"],
            "recommendation": profile["recommendation"],
        },
        "reasons": reasons,
    }


async def get_adaptive_thresholds(session: AsyncSession, incident) -> tuple[float, float, float]:
    """Get adaptive L1, L2, L3 thresholds for an incident.
    Returns (l1_minutes, l2_minutes, l3_minutes).
    Falls back to static thresholds on any error."""
    try:
        if getattr(incident, 'is_test', False):
            return (1, 2, 3)

        # Get guardian_id via senior
        senior = incident.senior
        if not senior:
            return _static_thresholds()

        profile = await build_guardian_profile(session, str(senior.guardian_id))

        base_l1 = settings.escalation_l1_minutes
        base_l2 = settings.escalation_l2_minutes
        base_l3 = settings.escalation_l3_minutes

        # Time-of-day factor
        hour = incident.created_at.hour if incident.created_at else datetime.now(timezone.utc).hour
        tod_factor = TOD_FACTORS.get(_get_tod_bucket(hour), 1.0)

        # Severity factor
        severity_factor = SEVERITY_FACTORS.get(incident.severity, 1.0)

        # Guardian factor
        guardian_factor = 1.0
        skip_l1 = False

        if profile["has_sufficient_data"]:
            if profile["recommendation"] == "skip_l1":
                skip_l1 = True
                guardian_factor = 0.5
            elif profile["recommendation"] == "slow_responder":
                guardian_factor = 0.7 if (profile["avg_response_minutes"] or 0) > base_l1 else 0.85

            # Time-of-day specific
            tod_bucket = _get_tod_bucket(hour)
            tod_prof = profile["response_by_time_of_day"].get(tod_bucket, {})
            if tod_prof.get("count", 0) >= 2 and tod_prof.get("rate", 1) < 0.3:
                skip_l1 = True

        combined = tod_factor * severity_factor * guardian_factor

        l1 = max(MIN_TIMER_MINUTES, round(base_l1 * combined, 1))
        l2 = max(MIN_TIMER_MINUTES + 1, round(base_l2 * combined, 1))
        l3 = max(MIN_TIMER_MINUTES + 2, round(base_l3 * combined, 1))

        if skip_l1:
            l1 = 0
            l2 = max(MIN_TIMER_MINUTES, round(base_l1 * tod_factor * severity_factor * 0.7, 1))

        return (l1, l2, l3)

    except Exception as e:
        logger.warning(f"Smart escalation fallback to static: {e}")
        return _static_thresholds()


def _static_thresholds():
    return (settings.escalation_l1_minutes, settings.escalation_l2_minutes, settings.escalation_l3_minutes)
