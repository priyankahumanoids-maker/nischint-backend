# Guardian AI Refinement Service — baseline engine, deviation scoring, fused risk, explainability
import logging
import uuid
import random
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import select, func, and_, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guardian_ai_v2 import GuardianBaseline, GuardianRiskScore, GuardianPrediction, GuardianRiskEvent
from app.models.guardian import GuardianSession, GuardianAlert
from app.models.incident import Incident
from app.models.user import User

logger = logging.getLogger(__name__)

# ── Risk weights ──
WEIGHTS = {
    "behavior": 0.30,
    "location": 0.25,
    "device": 0.20,
    "environment": 0.15,
    "response": 0.10,
}

RISK_THRESHOLDS = [(0.80, "critical"), (0.60, "high"), (0.35, "moderate"), (0.0, "low")]

BASELINE_THRESHOLD_DAYS = 7

ACTION_MAP = [
    (0.85, "dispatch_caregiver", "Dispatch nearest caregiver immediately"),
    (0.75, "escalate_operator", "Escalate to operator for immediate review"),
    (0.60, "increase_monitoring", "Increase monitoring frequency and alert guardian"),
    (0.45, "notify_guardian", "Send notification to guardian for awareness"),
    (0.0, "monitor", "Continue standard monitoring"),
]

# ── Factor descriptions ──
FACTOR_DESCRIPTIONS = {
    "device_offline": "Device offline or signal lost",
    "device_low_battery": "Device battery critically low",
    "behavior_deviation": "Behavior deviates from normal pattern",
    "time_deviation": "Activity outside normal hours",
    "location_deviation": "User in unusual location",
    "zone_risk_high": "User in high-risk geographic zone",
    "inactivity_anomaly": "Prolonged inactivity detected",
    "alert_spike": "Alert frequency above normal",
    "route_deviation": "Deviated from usual route",
    "no_caregiver_nearby": "No caregiver available within coverage area",
    "night_risk": "Night-time with elevated risk indicators",
    "environment_weather": "Adverse weather conditions in area",
    "response_delay": "Delayed response to recent alerts",
    "idle_duration": "Extended idle period detected",
}


def _classify_risk(score: float) -> str:
    for threshold, level in RISK_THRESHOLDS:
        if score >= threshold:
            return level
    return "low"


def _recommend_action(score: float) -> tuple[str, str]:
    for threshold, action, detail in ACTION_MAP:
        if score >= threshold:
            return action, detail
    return "monitor", "Continue standard monitoring"


# ════════════════════════════════════════════════════════
# BASELINE ENGINE
# ════════════════════════════════════════════════════════

def _generate_seed_baseline() -> dict:
    """Generate a realistic seed baseline for users without enough historical data."""
    hours = {}
    for h in range(24):
        if 6 <= h <= 8:
            hours[str(h)] = "moderate"
        elif 9 <= h <= 17:
            hours[str(h)] = "high"
        elif 18 <= h <= 21:
            hours[str(h)] = "moderate"
        elif 22 <= h <= 23 or 0 <= h <= 5:
            hours[str(h)] = "low"
        else:
            hours[str(h)] = "normal"

    return {
        "active_hours": hours,
        "avg_daily_distance": round(random.uniform(800, 3000), 1),
        "common_locations": [
            {"name": "Home", "lat": 19.076 + random.uniform(-0.01, 0.01), "lng": 72.877 + random.uniform(-0.01, 0.01), "frequency": 0.6},
            {"name": "Market", "lat": 19.076 + random.uniform(-0.02, 0.02), "lng": 72.877 + random.uniform(-0.02, 0.02), "frequency": 0.25},
        ],
        "route_clusters": [
            {"from": "Home", "to": "Market", "avg_time_min": random.randint(10, 25)},
        ],
        "avg_device_uptime": round(random.uniform(0.90, 0.98), 3),
        "avg_battery_drop": round(random.uniform(0.01, 0.04), 3),
        "avg_signal_loss_events": round(random.uniform(0.2, 1.5), 2),
        "normal_alerts_per_day": round(random.uniform(0.3, 2.0), 2),
        "normal_incidents_per_week": round(random.uniform(0.1, 1.0), 2),
        "avg_caregiver_visits_per_week": round(random.uniform(1.0, 4.0), 1),
    }


async def _compute_real_baseline(session: AsyncSession, user_id: uuid.UUID) -> Optional[dict]:
    """Compute baseline from historical guardian sessions and alerts."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    # Count session data
    sess_count = (await session.execute(
        select(func.count()).where(and_(
            GuardianSession.user_id == user_id,
            GuardianSession.started_at >= cutoff,
        ))
    )).scalar() or 0

    if sess_count < 3:
        return None

    sessions = (await session.execute(
        select(GuardianSession).where(and_(
            GuardianSession.user_id == user_id,
            GuardianSession.started_at >= cutoff,
        )).order_by(GuardianSession.started_at.desc()).limit(50)
    )).scalars().all()

    alerts = (await session.execute(
        select(GuardianAlert).where(and_(
            GuardianAlert.session_id.in_([s.id for s in sessions]),
        ))
    )).scalars().all()

    # Compute active hours histogram
    hours = {}
    for s in sessions:
        if s.started_at:
            h = str(s.started_at.hour)
            hours[h] = hours.get(h, 0) + 1
    total_sessions = len(sessions) or 1
    active_hours = {}
    for h in range(24):
        freq = hours.get(str(h), 0) / total_sessions
        active_hours[str(h)] = "high" if freq > 0.3 else "moderate" if freq > 0.1 else "low"

    # Mobility
    distances = [s.total_distance_m for s in sessions if s.total_distance_m]
    avg_distance = sum(distances) / len(distances) if distances else 1000.0

    # Common locations
    locations = []
    for s in sessions:
        if s.current_location and isinstance(s.current_location, dict):
            locations.append(s.current_location)
    common_locs = locations[:5] if locations else []

    # Alert frequency
    days_span = max((datetime.now(timezone.utc) - cutoff).days, 1)
    alerts_per_day = len(alerts) / days_span

    return {
        "active_hours": active_hours,
        "avg_daily_distance": round(avg_distance, 1),
        "common_locations": [{"lat": l.get("lat", 0), "lng": l.get("lng", 0), "frequency": 0.3} for l in common_locs],
        "route_clusters": [],
        "avg_device_uptime": 0.93,
        "avg_battery_drop": 0.02,
        "avg_signal_loss_events": 0.8,
        "normal_alerts_per_day": round(alerts_per_day, 2),
        "normal_incidents_per_week": round(alerts_per_day * 0.3, 2),
        "avg_caregiver_visits_per_week": 2.0,
        "data_days": days_span,
    }


async def get_or_create_baseline(session: AsyncSession, user_id: uuid.UUID) -> dict:
    """Get existing baseline or compute/seed one."""
    baseline = (await session.execute(
        select(GuardianBaseline).where(GuardianBaseline.user_id == user_id)
    )).scalar_one_or_none()

    if baseline:
        return _baseline_to_dict(baseline)

    # Try computing from real data
    real = await _compute_real_baseline(session, user_id)
    is_seeded = real is None
    data = real or _generate_seed_baseline()

    baseline = GuardianBaseline(
        user_id=user_id,
        active_hours=data["active_hours"],
        avg_daily_distance=data["avg_daily_distance"],
        common_locations=data.get("common_locations", []),
        route_clusters=data.get("route_clusters", []),
        avg_device_uptime=data.get("avg_device_uptime", 0.95),
        avg_battery_drop=data.get("avg_battery_drop", 0.02),
        avg_signal_loss_events=data.get("avg_signal_loss_events", 0.5),
        normal_alerts_per_day=data.get("normal_alerts_per_day", 1.0),
        normal_incidents_per_week=data.get("normal_incidents_per_week", 0.5),
        avg_caregiver_visits_per_week=data.get("avg_caregiver_visits_per_week", 2.0),
        data_days=data.get("data_days", 0),
        is_seeded=is_seeded,
    )
    session.add(baseline)
    await session.flush()
    return _baseline_to_dict(baseline)


def _baseline_to_dict(b: GuardianBaseline) -> dict:
    return {
        "id": str(b.id),
        "user_id": str(b.user_id),
        "active_hours": b.active_hours,
        "avg_daily_distance": b.avg_daily_distance,
        "common_locations": b.common_locations,
        "route_clusters": b.route_clusters,
        "avg_device_uptime": b.avg_device_uptime,
        "avg_battery_drop": b.avg_battery_drop,
        "avg_signal_loss_events": b.avg_signal_loss_events,
        "normal_alerts_per_day": b.normal_alerts_per_day,
        "normal_incidents_per_week": b.normal_incidents_per_week,
        "avg_caregiver_visits_per_week": b.avg_caregiver_visits_per_week,
        "data_days": b.data_days,
        "is_seeded": b.is_seeded,
        "last_computed_at": b.last_computed_at.isoformat() if b.last_computed_at else None,
    }


# ════════════════════════════════════════════════════════
# DEVIATION SCORING
# ════════════════════════════════════════════════════════

async def _prefetch_risk_inputs(session: AsyncSession, user_id: uuid.UUID) -> dict:
    """Batch-fetch every DB input the 5 sub-score functions need.

    Originally each `_compute_*` did its own queries — 7+ round-trips to
    Supabase, each costing ~1s of pooler RTT, all serialised on the
    caller's session. This batch pulls *everything* in ONE round-trip
    using a single SELECT with 6 scalar subqueries:

      - Latest active session row → behavior + location + environment
      - Latest session row of any status (fallback for location)
      - Alerts last 24h (count)
      - Device incidents last 6h (count)
      - Available caregivers (count)
      - Unacked open incidents last 2h (count)

    Returns a dict the sub-scores can read synchronously. The session
    rows come back as JSON (`row_to_json`) so we deserialize just the
    fields we actually need into a lightweight namespace, avoiding the
    overhead of ORM hydration for ~30 columns we don't use.
    """
    now = datetime.now(timezone.utc)
    six_h_ago = now - timedelta(hours=6)
    twenty_four_h_ago = now - timedelta(hours=24)
    two_h_ago = now - timedelta(hours=2)

    row = (await session.execute(text("""
        WITH active_sess AS (
            SELECT current_location, risk_level, is_idle, idle_duration_s,
                   route_deviated, route_deviation_m
            FROM guardian_sessions
            WHERE user_id = :uid AND status = 'active'
            ORDER BY started_at DESC LIMIT 1
        ),
        any_sess AS (
            SELECT current_location, risk_level
            FROM guardian_sessions
            WHERE user_id = :uid
            ORDER BY started_at DESC LIMIT 1
        )
        SELECT
            (SELECT row_to_json(active_sess.*) FROM active_sess) AS active_json,
            (SELECT row_to_json(any_sess.*) FROM any_sess)       AS any_json,
            (SELECT COUNT(*) FROM guardian_alerts
                WHERE created_at >= :h24)                        AS alerts_24h,
            (SELECT COUNT(*) FROM incidents
                WHERE created_at >= :h6
                  AND incident_type IN ('device_offline', 'low_battery', 'signal_lost')
                  AND is_test = false)                           AS device_incidents_6h,
            (SELECT COUNT(*) FROM caregiver_statuses
                WHERE status = 'available')                      AS caregivers_available,
            (SELECT COUNT(*) FROM incidents
                WHERE status = 'open'
                  AND created_at >= :h2
                  AND acknowledged_at IS NULL)                   AS unacked_2h
    """), {
        "uid": user_id,
        "h24": twenty_four_h_ago,
        "h6": six_h_ago,
        "h2": two_h_ago,
    })).first()

    # Light-weight session view — only the fields the sub-scores actually
    # read. Behaves like a duck-typed GuardianSession for the scorer.
    class _SessView:
        __slots__ = ("current_location", "risk_level", "is_idle",
                     "idle_duration_s", "route_deviated", "route_deviation_m")
        def __init__(self, d: dict):
            self.current_location = d.get("current_location")
            self.risk_level       = d.get("risk_level")
            self.is_idle          = d.get("is_idle", False)
            self.idle_duration_s  = d.get("idle_duration_s") or 0
            self.route_deviated   = d.get("route_deviated", False)
            self.route_deviation_m = d.get("route_deviation_m")

    active = _SessView(row.active_json) if row.active_json else None
    any_s  = _SessView(row.any_json)    if row.any_json    else active

    return {
        "now": now,
        "recent_active_session": active,
        "recent_any_session":    any_s,
        "alerts_24h":           int(row.alerts_24h or 0),
        "device_incidents_6h":  int(row.device_incidents_6h or 0),
        "caregivers_available": int(row.caregivers_available or 0),
        "unacked_2h":           int(row.unacked_2h or 0),
    }


# ────────────────────────────────────────────────────────────────────
# Pure-CPU scorers — consume `_prefetch_risk_inputs` output, no I/O.
# These are what compute_risk_score uses in the hot path.
# ────────────────────────────────────────────────────────────────────


def _score_behavior_deviation(inputs: dict, baseline: dict) -> tuple[float, list[str]]:
    factors: list[str] = []
    now = inputs["now"]
    current_hour = str(now.hour)

    hour_activity = baseline.get("active_hours", {}).get(current_hour, "normal")
    time_dev = 0.0
    if hour_activity == "low" and now.hour >= 22:
        time_dev = 0.7
        factors.append("time_deviation")
    elif hour_activity == "low":
        time_dev = 0.4
        factors.append("time_deviation")

    recent = inputs["recent_active_session"]
    inactivity_dev = 0.0
    if recent and recent.is_idle and recent.idle_duration_s and recent.idle_duration_s > 600:
        inactivity_dev = min(recent.idle_duration_s / 1800, 1.0)
        factors.append("inactivity_anomaly")

    route_dev = 0.0
    if recent and recent.route_deviated:
        route_dev = min((recent.route_deviation_m or 0) / 500, 1.0)
        factors.append("route_deviation")

    alert_count_24h = inputs["alerts_24h"]
    normal_rate = baseline.get("normal_alerts_per_day", 1.0) or 1.0
    alert_dev = (
        min(max(0, (alert_count_24h - normal_rate) / max(normal_rate, 1)), 1.0)
        if alert_count_24h > normal_rate * 1.5 else 0.0
    )
    if alert_dev > 0.3:
        factors.append("alert_spike")

    score = max(time_dev, inactivity_dev, route_dev, alert_dev)
    return round(min(score, 1.0), 3), factors


def _score_location_risk(inputs: dict, baseline: dict) -> tuple[float, list[str]]:
    factors: list[str] = []
    recent = inputs["recent_any_session"]
    score = 0.0
    if recent:
        loc = recent.current_location or {}
        common_locs = baseline.get("common_locations", [])
        if loc and common_locs:
            lat, lng = loc.get("lat", 0), loc.get("lng", 0)
            min_dist = min(
                (abs(lat - cl.get("lat", 0)) + abs(lng - cl.get("lng", 0))) for cl in common_locs
            ) if common_locs else 0
            if min_dist > 0.01:
                score = min(min_dist / 0.05, 1.0)
                factors.append("location_deviation")
        if recent.risk_level in ("HIGH", "CRITICAL"):
            score = max(score, 0.7 if recent.risk_level == "HIGH" else 0.9)
            factors.append("zone_risk_high")
    return round(min(score, 1.0), 3), factors


def _score_device_risk(inputs: dict) -> tuple[float, list[str]]:
    factors: list[str] = []
    device_incidents = inputs["device_incidents_6h"]
    score = 0.0
    if device_incidents > 0:
        score = min(device_incidents * 0.35, 1.0)
        if device_incidents >= 2:
            factors.append("device_offline")
        factors.append("device_low_battery")
    return round(min(score, 1.0), 3), factors


def _score_response_risk(inputs: dict) -> tuple[float, list[str]]:
    factors: list[str] = []
    available = inputs["caregivers_available"]
    score = 0.0
    if available == 0:
        score = 0.8
        factors.append("no_caregiver_nearby")
    elif available == 1:
        score = 0.3
    unacked = inputs["unacked_2h"]
    if unacked > 2:
        score = max(score, 0.6)
        factors.append("response_delay")
    return round(min(score, 1.0), 3), factors


async def _score_environment_risk(inputs: dict) -> tuple[float, list[str]]:
    """Mostly CPU but does a weather HTTP call (Redis-cached at the
    weather_service layer, so usually fast). Stays async for that.
    """
    factors: list[str] = []
    now = inputs["now"]
    hour = now.hour

    score = 0.0
    if 22 <= hour or hour <= 5:
        score = 0.5
        factors.append("night_risk")
    elif 20 <= hour <= 22:
        score = 0.25

    recent = inputs["recent_active_session"]
    try:
        if recent and recent.current_location:
            loc = recent.current_location
            lat = loc.get("lat") or loc.get("latitude")
            lng = loc.get("lng") or loc.get("longitude")
            if lat is not None and lng is not None:
                from app.services.weather_service import get_weather, compute_weather_risk
                weather = await get_weather(float(lat), float(lng))
                weather_risk, weather_factors = compute_weather_risk(weather)
                if weather_risk > 0:
                    score = max(score, weather_risk)
                    for wf in weather_factors:
                        if wf not in factors:
                            factors.append(wf)
    except Exception as e:
        logger.warning("[ENV_RISK] weather fetch skipped: %s", e)

    return round(min(score, 1.0), 3), factors




async def _compute_behavior_deviation(session: AsyncSession, user_id: uuid.UUID, baseline: dict) -> tuple[float, list[str]]:
    """LEGACY single-query variant — preserved for callers outside
    compute_risk_score. Internally, compute_risk_score uses
    `_prefetch_risk_inputs` + `_score_behavior_deviation` for a single
    batched fetch. Kept for back-compat with any code path that still
    calls _compute_behavior_deviation directly."""
    factors = []
    now = datetime.now(timezone.utc)
    current_hour = str(now.hour)

    # Time deviation
    hour_activity = baseline.get("active_hours", {}).get(current_hour, "normal")
    time_dev = 0.0
    if hour_activity == "low" and now.hour >= 22:
        time_dev = 0.7
        factors.append("time_deviation")
    elif hour_activity == "low":
        time_dev = 0.4
        factors.append("time_deviation")

    # Check recent sessions for inactivity
    recent_session = (await session.execute(
        select(GuardianSession)
        .where(and_(GuardianSession.user_id == user_id, GuardianSession.status == "active"))
        .order_by(GuardianSession.started_at.desc()).limit(1)
    )).scalar_one_or_none()

    inactivity_dev = 0.0
    if recent_session and recent_session.is_idle and recent_session.idle_duration_s > 600:
        inactivity_dev = min(recent_session.idle_duration_s / 1800, 1.0)
        factors.append("inactivity_anomaly")

    # Route deviation
    route_dev = 0.0
    if recent_session and recent_session.route_deviated:
        route_dev = min((recent_session.route_deviation_m or 0) / 500, 1.0)
        factors.append("route_deviation")

    # Alert frequency anomaly
    alert_count_24h = (await session.execute(
        select(func.count()).where(and_(
            GuardianAlert.created_at >= now - timedelta(hours=24),
        ))
    )).scalar() or 0
    normal_rate = baseline.get("normal_alerts_per_day", 1.0) or 1.0
    alert_dev = min(max(0, (alert_count_24h - normal_rate) / max(normal_rate, 1)), 1.0) if alert_count_24h > normal_rate * 1.5 else 0.0
    if alert_dev > 0.3:
        factors.append("alert_spike")

    score = max(time_dev, inactivity_dev, route_dev, alert_dev)
    return round(min(score, 1.0), 3), factors


async def _compute_location_risk(session: AsyncSession, user_id: uuid.UUID, baseline: dict) -> tuple[float, list[str]]:
    """Compute location-based risk. Returns (score, factors)."""
    factors = []

    recent_session = (await session.execute(
        select(GuardianSession)
        .where(GuardianSession.user_id == user_id)
        .order_by(GuardianSession.started_at.desc()).limit(1)
    )).scalar_one_or_none()

    score = 0.0
    if recent_session:
        loc = recent_session.current_location or {}
        # Check if in unusual location
        common_locs = baseline.get("common_locations", [])
        if loc and common_locs:
            lat, lng = loc.get("lat", 0), loc.get("lng", 0)
            min_dist = min(
                (abs(lat - cl.get("lat", 0)) + abs(lng - cl.get("lng", 0))) for cl in common_locs
            ) if common_locs else 0
            if min_dist > 0.01:  # ~1km away from all known locations
                score = min(min_dist / 0.05, 1.0)
                factors.append("location_deviation")

        # Zone risk
        if recent_session.risk_level in ("HIGH", "CRITICAL"):
            score = max(score, 0.7 if recent_session.risk_level == "HIGH" else 0.9)
            factors.append("zone_risk_high")

    return round(min(score, 1.0), 3), factors


async def _compute_device_risk(session: AsyncSession, user_id: uuid.UUID, baseline: dict) -> tuple[float, list[str]]:
    """Compute device reliability risk."""
    factors = []
    now = datetime.now(timezone.utc)

    # Check recent incidents for device issues
    device_incidents = (await session.execute(
        select(func.count()).where(and_(
            Incident.created_at >= now - timedelta(hours=6),
            Incident.incident_type.in_(["device_offline", "low_battery", "signal_lost"]),
            Incident.is_test == False,
        ))
    )).scalar() or 0

    score = 0.0
    if device_incidents > 0:
        score = min(device_incidents * 0.35, 1.0)
        if device_incidents >= 2:
            factors.append("device_offline")
        factors.append("device_low_battery")

    return round(min(score, 1.0), 3), factors


async def _compute_environment_risk(session: AsyncSession, user_id: uuid.UUID) -> tuple[float, list[str]]:
    """Compute environmental risk: time-of-day band + real weather (Phase 4)."""
    factors = []
    now = datetime.now(timezone.utc)
    hour = now.hour

    score = 0.0
    if 22 <= hour or hour <= 5:
        score = 0.5
        factors.append("night_risk")
    elif 20 <= hour <= 22:
        score = 0.25

    # Real weather signal (Phase 4 — replaced random stub).
    # Pull last known location from the most recent active GuardianSession.
    try:
        recent = (await session.execute(
            select(GuardianSession)
            .where(and_(
                GuardianSession.user_id == user_id,
                GuardianSession.status == "active",
            ))
            .order_by(GuardianSession.started_at.desc()).limit(1)
        )).scalar_one_or_none()
        if recent and recent.current_location:
            loc = recent.current_location
            lat = loc.get("lat") or loc.get("latitude")
            lng = loc.get("lng") or loc.get("longitude")
            if lat is not None and lng is not None:
                from app.services.weather_service import get_weather, compute_weather_risk
                weather = await get_weather(float(lat), float(lng))
                weather_risk, weather_factors = compute_weather_risk(weather)
                if weather_risk > 0:
                    score = max(score, weather_risk)
                    for wf in weather_factors:
                        if wf not in factors:
                            factors.append(wf)
    except Exception as e:
        logger.warning("[ENV_RISK] weather fetch skipped: %s", e)

    return round(min(score, 1.0), 3), factors


async def _compute_response_risk(session: AsyncSession, user_id: uuid.UUID) -> tuple[float, list[str]]:
    """Compute response-readiness risk (caregiver availability, recent response times)."""
    factors = []
    from app.models.caregiver import CaregiverStatus

    # Check available caregivers
    available = (await session.execute(
        select(func.count()).where(CaregiverStatus.status == "available")
    )).scalar() or 0

    score = 0.0
    if available == 0:
        score = 0.8
        factors.append("no_caregiver_nearby")
    elif available == 1:
        score = 0.3

    # Check unacknowledged alerts
    now = datetime.now(timezone.utc)
    unacked = (await session.execute(
        select(func.count()).where(and_(
            Incident.status == "open",
            Incident.created_at >= now - timedelta(hours=2),
            Incident.acknowledged_at == None,
        ))
    )).scalar() or 0

    if unacked > 2:
        score = max(score, 0.6)
        factors.append("response_delay")

    return round(min(score, 1.0), 3), factors


# ════════════════════════════════════════════════════════
# FUSED RISK SCORE
# ════════════════════════════════════════════════════════

async def compute_risk_score(
    session: AsyncSession,
    user_id: uuid.UUID,
    baseline: Optional[dict] = None,
) -> dict:
    """Compute full multi-factor risk score with explainability.

    Performance contract (June 2026 refactor — was 9s cold, target <1s):
      * 5 sub-score computations run **in parallel** via `asyncio.gather`,
        each on its OWN async session. Pre-refactor they ran sequentially
        on a single shared session (4.7s wall) — this drops to ~max
        single-section (≈ 900–1500ms).
      * Optional `baseline` param lets the caller (CC_unified) pass the
        baseline it already fetched — eliminates the triple-fetch
        previously incurred by CC_unified.baseline + compute_risk_score
        + sub-scores all calling `get_or_create_baseline` independently.
      * DB writes (GuardianRiskScore + GuardianRiskEvent + flush) run on
        the SAME session passed in by the caller — we keep the write
        path simple and let the caller decide commit semantics.
    """
    if baseline is None:
        baseline = await get_or_create_baseline(session, user_id)

    # Prefetch ALL DB inputs the 5 sub-scores need in a single round
    # trip (2 statements total — recent session + one batched COUNT).
    # Pre-refactor, each sub-score made 1-2 of its own queries on the
    # same session, paying ~1s of Supabase pooler RTT each. Now the
    # sub-scores are pure CPU once `inputs` lands.
    inputs = await _prefetch_risk_inputs(session, user_id)

    behavior_score, behavior_factors   = _score_behavior_deviation(inputs, baseline)
    location_score, location_factors   = _score_location_risk(inputs, baseline)
    device_score,   device_factors     = _score_device_risk(inputs)
    response_score, response_factors   = _score_response_risk(inputs)
    # environment_risk still does a weather HTTP call — keep as async.
    environment_score, env_factors     = await _score_environment_risk(inputs)

    # Fuse scores
    final_score = round(
        WEIGHTS["behavior"] * behavior_score +
        WEIGHTS["location"] * location_score +
        WEIGHTS["device"] * device_score +
        WEIGHTS["environment"] * environment_score +
        WEIGHTS["response"] * response_score,
        3,
    )

    risk_level = _classify_risk(final_score)
    action, action_detail = _recommend_action(final_score)

    # Build top factors (sorted by impact)
    all_factors = []
    factor_map = [
        (behavior_score, behavior_factors, "behavior"),
        (location_score, location_factors, "location"),
        (device_score, device_factors, "device"),
        (environment_score, env_factors, "environment"),
        (response_score, response_factors, "response"),
    ]
    for score, factors, category in factor_map:
        for f in factors:
            all_factors.append({
                "factor": f,
                "description": FACTOR_DESCRIPTIONS.get(f, f),
                "category": category,
                "impact": round(score * WEIGHTS[category], 3),
            })
    all_factors.sort(key=lambda x: x["impact"], reverse=True)
    top_factors = all_factors[:3]

    # Save to DB
    risk_score_record = GuardianRiskScore(
        user_id=user_id,
        behavior_score=behavior_score,
        location_score=location_score,
        device_score=device_score,
        environment_score=environment_score,
        response_score=response_score,
        final_score=final_score,
        risk_level=risk_level,
        top_factors=top_factors,
        recommended_action=action,
        action_detail=action_detail,
    )
    session.add(risk_score_record)

    # Log risk event
    risk_event = GuardianRiskEvent(
        user_id=user_id,
        baseline_deviation=behavior_score,
        location_risk=location_score,
        device_risk=device_score,
        environment_risk=environment_score,
        response_risk=response_score,
        final_risk_score=final_score,
        risk_level=risk_level,
        top_factors=top_factors,
        recommended_action=action,
        incident_created=risk_level in ("critical", "high"),
    )
    session.add(risk_event)

    await session.flush()

    # Push to Redis stream
    _push_to_redis(user_id, final_score, risk_level, top_factors, action)

    risk_payload = {
        "user_id": str(user_id),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scores": {
            "behavior": behavior_score,
            "location": location_score,
            "device": device_score,
            "environment": environment_score,
            "response": response_score,
        },
        "final_score": final_score,
        "risk_level": risk_level,
        "top_factors": top_factors,
        "recommended_action": action,
        "action_detail": action_detail,
        "baseline": {
            "is_seeded": baseline.get("is_seeded", True),
            "data_days": baseline.get("data_days", 0),
        },
    }

    # Phase 5 — emit COMMAND_CENTER_DELTA for changed `risk.*` paths
    try:
        from app.services.cc_delta_emitter import emit_namespaced_delta
        # Drop unstable fields (timestamp / user_id) from the diff input so
        # the cache doesn't churn on every compute.
        diff_input = {
            "scores": risk_payload["scores"],
            "final_score": final_score,
            "risk_level": risk_level,
            "top_factors": top_factors,
            "recommended_action": action,
        }
        await emit_namespaced_delta(str(user_id), "risk", diff_input)
    except Exception:
        logger.exception("[CC_DELTA] risk emit failed for %s", user_id)

    return risk_payload


def _push_to_redis(user_id, score, level, factors, action):
    """Push risk score to Redis stream for real-time consumers."""
    try:
        from app.services.queue_service import publish_event
        publish_event("ai_signal", {
            "type": "guardian_risk_score",
            "user_id": str(user_id),
            "risk_score": score,
            "risk_level": level,
            "top_factors": [f["factor"] for f in factors[:3]],
            "recommendation": action,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        pass  # Redis may not be available


# ════════════════════════════════════════════════════════
# PREDICTIONS
# ════════════════════════════════════════════════════════

async def generate_predictions(session: AsyncSession, user_id: uuid.UUID) -> list[dict]:
    """Generate forward-looking risk predictions."""
    baseline = await get_or_create_baseline(session, user_id)
    now = datetime.now(timezone.utc)
    predictions = []

    # Check for active sessions with elevated risk
    active_session = (await session.execute(
        select(GuardianSession).where(and_(
            GuardianSession.user_id == user_id,
            GuardianSession.status == "active",
        )).order_by(GuardianSession.started_at.desc()).limit(1)
    )).scalar_one_or_none()

    # Prediction 1: Wandering risk
    if active_session and active_session.route_deviated:
        confidence = min(0.5 + (active_session.route_deviation_m or 0) / 1000, 0.95)
        pred = GuardianPrediction(
            user_id=user_id,
            prediction_type="wandering_risk",
            prediction_window_minutes=30,
            confidence=round(confidence, 2),
            predicted_risk_level="high" if confidence > 0.7 else "moderate",
            recommended_action="increase_monitoring" if confidence < 0.7 else "dispatch_caregiver",
            reasoning=f"Route deviation of {int(active_session.route_deviation_m or 0)}m detected. "
                      f"Historical pattern suggests elevated wandering risk in next 30 minutes.",
        )
        session.add(pred)
        predictions.append(_prediction_to_dict(pred))

    # Prediction 2: Night risk (if approaching night hours)
    if 19 <= now.hour <= 21:
        hour_profile = baseline.get("active_hours", {}).get(str(now.hour + 2), "low")
        if hour_profile == "low":
            pred = GuardianPrediction(
                user_id=user_id,
                prediction_type="night_risk",
                prediction_window_minutes=120,
                confidence=0.65,
                predicted_risk_level="moderate",
                recommended_action="notify_guardian",
                reasoning="User approaching low-activity night hours. Ensure device is charged and location services active.",
            )
            session.add(pred)
            predictions.append(_prediction_to_dict(pred))

    # Prediction 3: Inactivity risk
    if active_session and active_session.is_idle and active_session.idle_duration_s > 300:
        idle_min = int(active_session.idle_duration_s / 60)
        confidence = min(0.4 + idle_min * 0.05, 0.9)
        pred = GuardianPrediction(
            user_id=user_id,
            prediction_type="inactivity_risk",
            prediction_window_minutes=30,
            confidence=round(confidence, 2),
            predicted_risk_level="high" if idle_min > 15 else "moderate",
            recommended_action="escalate_operator" if idle_min > 15 else "increase_monitoring",
            reasoning=f"User idle for {idle_min} minutes. Exceeds normal inactivity window. "
                      f"Risk of fall or medical event increases with duration.",
        )
        session.add(pred)
        predictions.append(_prediction_to_dict(pred))

    # Prediction 4: Zone escalation (based on recent incident density)
    recent_incidents = (await session.execute(
        select(func.count()).where(and_(
            Incident.created_at >= now - timedelta(hours=4),
            Incident.is_test == False,
        ))
    )).scalar() or 0

    if recent_incidents >= 3:
        pred = GuardianPrediction(
            user_id=user_id,
            prediction_type="zone_escalation",
            prediction_window_minutes=60,
            confidence=min(0.5 + recent_incidents * 0.08, 0.92),
            predicted_risk_level="high",
            recommended_action="escalate_operator",
            reasoning=f"{recent_incidents} incidents in last 4 hours indicates zone-level risk escalation. "
                      f"Recommend pre-positioning caregiver in affected area.",
        )
        session.add(pred)
        predictions.append(_prediction_to_dict(pred))

    await session.flush()
    return predictions


def _prediction_to_dict(p) -> dict:
    return {
        "id": str(p.id),
        "user_id": str(p.user_id),
        "prediction_type": p.prediction_type,
        "prediction_window_minutes": p.prediction_window_minutes,
        "confidence": p.confidence,
        "predicted_risk_level": p.predicted_risk_level,
        "recommended_action": p.recommended_action,
        "reasoning": p.reasoning,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


# ════════════════════════════════════════════════════════
# BATCH OPERATIONS
# ════════════════════════════════════════════════════════

async def compute_all_baselines(session: AsyncSession) -> dict:
    """Batch compute/update baselines for all users with guardian sessions."""
    user_ids = (await session.execute(
        select(GuardianSession.user_id).distinct()
    )).scalars().all()

    computed = 0
    for uid in user_ids:
        await get_or_create_baseline(session, uid)
        computed += 1

    await session.flush()
    return {"computed": computed, "total_users": len(user_ids)}


async def get_high_risk_users(session: AsyncSession, limit: int = 10) -> list[dict]:
    """Get users with highest current risk scores.

    Each row is enriched with the latest known lat/lng so the operator
    Command Center map can render every monitored user as a live pin
    without introducing a new endpoint. Source priority:
      1. Active GuardianSession.current_location (real-time)
      2. GuardianBaseline.common_locations[0] (last-known typical home/work)
    """
    scores = (await session.execute(
        select(GuardianRiskScore, User.full_name, User.email)
        .join(User, GuardianRiskScore.user_id == User.id, isouter=True)
        .order_by(GuardianRiskScore.timestamp.desc())
        .limit(100)
    )).all()

    # Deduplicate by user (latest score only)
    seen = set()
    results = []
    for score, name, email in scores:
        uid = str(score.user_id)
        if uid in seen:
            continue
        seen.add(uid)
        results.append({
            "user_id": uid,
            "user_name": name or email or "Unknown",
            "final_score": score.final_score,
            "risk_level": score.risk_level,
            "top_factors": score.top_factors,
            "recommended_action": score.recommended_action,
            "action_detail": score.action_detail,
            "scores": {
                "behavior": score.behavior_score,
                "location": score.location_score,
                "device": score.device_score,
                "environment": score.environment_score,
                "response": score.response_score,
            },
            "timestamp": score.timestamp.isoformat(),
            # Filled by enrichment step below.
            "lat": None,
            "lng": None,
            "location_source": None,
            "last_seen_at": None,
            # Pipeline integrity — distinct from location freshness so the
            # operator console can show "DATA GAP" instead of silently
            # decaying a missing pipeline into a "stale location".
            "last_ping_at": None,
        })
        if len(results) >= limit:
            break

    results.sort(key=lambda x: x["final_score"], reverse=True)

    # ── Enrich with last-known location ────────────────────────────────
    if results:
        user_uuids = [uuid.UUID(r["user_id"]) for r in results]

        # 1. Active session location (real-time priority).
        sess_rows = (await session.execute(
            select(GuardianSession).where(and_(
                GuardianSession.user_id.in_(user_uuids),
                GuardianSession.status == "active",
            ))
        )).scalars().all()
        session_loc: dict[str, dict] = {}
        for s in sess_rows:
            loc = s.current_location or {}
            lat = loc.get("lat") or loc.get("latitude")
            lng = loc.get("lng") or loc.get("longitude")
            if lat is None or lng is None:
                continue
            ts = s.previous_update_at or s.started_at
            session_loc[str(s.user_id)] = {
                "lat": float(lat),
                "lng": float(lng),
                "ts": ts.isoformat() if ts else None,
            }

        # 2. Baseline fallback (last-known typical location).
        bl_rows = (await session.execute(
            select(GuardianBaseline).where(GuardianBaseline.user_id.in_(user_uuids))
        )).scalars().all()
        baseline_loc: dict[str, dict] = {}
        for b in bl_rows:
            cl = b.common_locations or []
            if not cl:
                continue
            top = cl[0] if isinstance(cl, list) else None
            if not isinstance(top, dict):
                continue
            lat = top.get("lat") or top.get("latitude")
            lng = top.get("lng") or top.get("longitude")
            if lat is None or lng is None:
                continue
            baseline_loc[str(b.user_id)] = {
                "lat": float(lat),
                "lng": float(lng),
                "ts": b.last_computed_at.isoformat() if b.last_computed_at else None,
            }

        for r in results:
            uid = r["user_id"]
            if uid in session_loc:
                r["lat"] = session_loc[uid]["lat"]
                r["lng"] = session_loc[uid]["lng"]
                r["last_seen_at"] = session_loc[uid]["ts"]
                r["location_source"] = "session"
            elif uid in baseline_loc:
                r["lat"] = baseline_loc[uid]["lat"]
                r["lng"] = baseline_loc[uid]["lng"]
                r["last_seen_at"] = baseline_loc[uid]["ts"]
                r["location_source"] = "baseline"

        # 3. Pipeline-integrity heartbeat (Truth Layer). Bulk-fetch in one
        # MGET so we don't add round-trips proportional to user count.
        try:
            from app.services.redis_service import get_user_pings
            ping_map = get_user_pings([r["user_id"] for r in results])
            for r in results:
                pa = ping_map.get(r["user_id"])
                if pa:
                    r["last_ping_at"] = pa
        except Exception:
            logger.exception("[high-risk] pipeline-ping enrichment failed")

        # 4. SB-01 Day 3 — Hermes attenuation snapshot per user.
        # The Operator Confidence Engine surface: each row carries
        # the *current* per-signal attenuator the brain would apply on
        # the next evaluate_risk. New users → empty dict + source
        # `"no feedback yet"` (front-end suppresses the badge cleanly).
        try:
            from app.api.sb01_hermes import get_user_attenuation
            for r in results:
                snap = await get_user_attenuation(session, r["user_id"])
                r["attenuation"] = {
                    "multipliers": snap.get("multipliers", {}),
                    "samples":     snap.get("samples", {}),
                    "verdicts":    snap.get("verdicts", 0),
                    "source":      snap.get("source", "no feedback yet"),
                }
        except Exception:
            logger.exception("[high-risk] hermes attenuation enrichment failed")

    return results


async def get_risk_history(session: AsyncSession, user_id: uuid.UUID, limit: int = 50) -> list[dict]:
    """Get risk event history for a user (for audit/ML training)."""
    events = (await session.execute(
        select(GuardianRiskEvent)
        .where(GuardianRiskEvent.user_id == user_id)
        .order_by(GuardianRiskEvent.timestamp.desc())
        .limit(limit)
    )).scalars().all()

    return [{
        "id": str(e.id),
        "timestamp": e.timestamp.isoformat(),
        "baseline_deviation": e.baseline_deviation,
        "location_risk": e.location_risk,
        "device_risk": e.device_risk,
        "environment_risk": e.environment_risk,
        "response_risk": e.response_risk,
        "final_risk_score": e.final_risk_score,
        "risk_level": e.risk_level,
        "top_factors": e.top_factors,
        "recommended_action": e.recommended_action,
        "incident_created": e.incident_created,
    } for e in events]
