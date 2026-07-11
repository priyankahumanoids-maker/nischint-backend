# Behavioral Pattern Analyzer
#
# Multi-day anomaly detection for the 3-Layer Safety Brain.
# Analyzes patterns across 3 time windows (7/14/30 days):
#   - Repeated wandering times
#   - Evening/night distress patterns
#   - Route deviation frequency
#   - Voice distress clustering
#
# Outputs anomaly score + confidence + stability.

import logging
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Analysis windows
WINDOWS = {"short": 7, "medium": 14, "long": 30}

# Anomaly thresholds
WANDER_THRESHOLD = {"short": 2, "medium": 4, "long": 6}
FALL_THRESHOLD = {"short": 1, "medium": 2, "long": 3}
VOICE_THRESHOLD = {"short": 1, "medium": 2, "long": 4}
ROUTE_DEVIATION_THRESHOLD = {"short": 2, "medium": 3, "long": 5}

# Time bucket labels (4-hour blocks)
TIME_BUCKETS = {
    0: "late_night", 1: "late_night", 2: "late_night", 3: "late_night",
    4: "early_morning", 5: "early_morning", 6: "early_morning", 7: "early_morning",
    8: "morning", 9: "morning", 10: "morning", 11: "morning",
    12: "afternoon", 13: "afternoon", 14: "afternoon", 15: "afternoon",
    16: "evening", 17: "evening", 18: "evening", 19: "evening",
    20: "night", 21: "night", 22: "night", 23: "night",
}


async def _fetch_events_by_window(session: AsyncSession, user_id: str, table: str, time_col: str, days: int) -> list[dict]:
    """Fetch events within a time window."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        result = await session.execute(
            text(f"SELECT * FROM {table} WHERE user_id = :uid AND {time_col} > :cutoff ORDER BY {time_col} DESC"),
            {"uid": user_id, "cutoff": cutoff},
        )
        return [dict(row._mapping) for row in result]
    except Exception as e:
        logger.debug(f"Behavior analyzer: skip {table}: {e}")
        return []


def _time_distribution(events: list[dict], time_col: str = "created_at") -> dict:
    """Analyze time-of-day distribution of events."""
    buckets = defaultdict(int)
    hours = defaultdict(int)
    for e in events:
        ts = e.get(time_col)
        if ts:
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            h = ts.hour if hasattr(ts, 'hour') else 0
            buckets[TIME_BUCKETS.get(h, "unknown")] += 1
            hours[h] += 1
    return {"buckets": dict(buckets), "hours": dict(hours)}


def _detect_clustering(events: list[dict], time_col: str = "created_at") -> dict:
    """Detect temporal clustering — repeated events at similar times."""
    if len(events) < 2:
        return {"clustered": False, "peak_hour": None, "cluster_score": 0.0}

    hours = defaultdict(int)
    for e in events:
        ts = e.get(time_col)
        if ts and hasattr(ts, 'hour'):
            hours[ts.hour] += 1

    if not hours:
        return {"clustered": False, "peak_hour": None, "cluster_score": 0.0}

    peak_hour = max(hours, key=hours.get)
    peak_count = hours[peak_hour]
    total = sum(hours.values())
    concentration = peak_count / total if total > 0 else 0

    return {
        "clustered": concentration >= 0.4,
        "peak_hour": peak_hour,
        "peak_count": peak_count,
        "cluster_score": round(concentration, 3),
    }


async def analyze_behavior(session: AsyncSession, user_id: str) -> dict:
    """
    Full behavioral pattern analysis across 7/14/30 day windows.

    Returns: {
        anomaly_score: 0-1,
        confidence: 0-1,
        stability: 'low'|'medium'|'high',
        patterns: [...],
        window_data: {...},
        recommendations: [...]
    }
    """
    patterns = []
    window_data = {}
    raw_scores = {"short": 0.0, "medium": 0.0, "long": 0.0}

    for window_name, days in WINDOWS.items():
        wander_events = await _fetch_events_by_window(session, user_id, "wandering_events", "created_at", days)
        fall_events = await _fetch_events_by_window(session, user_id, "fall_events", "created_at", days)
        voice_events = await _fetch_events_by_window(session, user_id, "voice_distress_events", "created_at", days)
        safety_events = await _fetch_events_by_window(session, user_id, "safety_events", "created_at", days)

        wander_count = len(wander_events)
        fall_count = len(fall_events)
        voice_count = len(voice_events)
        safety_count = len(safety_events)

        # Compute per-window anomaly signals
        w_score = 0.0

        # Wandering pattern
        wander_thresh = WANDER_THRESHOLD[window_name]
        if wander_count >= wander_thresh:
            wander_ratio = min(1.0, wander_count / (wander_thresh * 2))
            w_score += wander_ratio * 0.30
            cluster = _detect_clustering(wander_events)
            if cluster["clustered"]:
                patterns.append({
                    "type": "repeated_wandering",
                    "window": window_name,
                    "count": wander_count,
                    "peak_hour": cluster["peak_hour"],
                    "severity": "high" if wander_ratio > 0.7 else "medium",
                })

        # Fall pattern
        fall_thresh = FALL_THRESHOLD[window_name]
        if fall_count >= fall_thresh:
            fall_ratio = min(1.0, fall_count / (fall_thresh * 2))
            w_score += fall_ratio * 0.25
            patterns.append({
                "type": "recurring_falls",
                "window": window_name,
                "count": fall_count,
                "severity": "high" if fall_ratio > 0.7 else "medium",
            })

        # Voice distress pattern
        voice_thresh = VOICE_THRESHOLD[window_name]
        if voice_count >= voice_thresh:
            voice_ratio = min(1.0, voice_count / (voice_thresh * 2))
            w_score += voice_ratio * 0.25
            cluster = _detect_clustering(voice_events)
            if cluster["clustered"]:
                patterns.append({
                    "type": "voice_distress_clustering",
                    "window": window_name,
                    "count": voice_count,
                    "peak_hour": cluster["peak_hour"],
                    "severity": "high" if voice_ratio > 0.7 else "medium",
                })

        # Overall safety event frequency
        if safety_count >= 3:
            safety_ratio = min(1.0, safety_count / 10.0)
            w_score += safety_ratio * 0.20
            time_dist = _time_distribution(safety_events)
            if time_dist["buckets"].get("night", 0) + time_dist["buckets"].get("late_night", 0) > safety_count * 0.4:
                patterns.append({
                    "type": "nighttime_incidents",
                    "window": window_name,
                    "count": safety_count,
                    "night_ratio": round((time_dist["buckets"].get("night", 0) + time_dist["buckets"].get("late_night", 0)) / max(safety_count, 1), 2),
                    "severity": "high",
                })

        raw_scores[window_name] = round(min(1.0, w_score), 3)
        window_data[window_name] = {
            "days": days,
            "wandering": wander_count,
            "falls": fall_count,
            "voice_distress": voice_count,
            "safety_events": safety_count,
            "score": raw_scores[window_name],
        }

    # Compute composite anomaly score (weighted across windows)
    anomaly_score = (
        raw_scores["short"] * 0.50 +
        raw_scores["medium"] * 0.30 +
        raw_scores["long"] * 0.20
    )

    # Confidence: how many windows show anomalies
    active_windows = sum(1 for s in raw_scores.values() if s > 0.1)
    confidence = round(min(1.0, active_windows / 3.0 * (0.5 + anomaly_score * 0.5)), 3)

    # Stability: pattern must appear across multiple windows
    pattern_types = set(p["type"] for p in patterns)
    multi_window_patterns = sum(
        1 for pt in pattern_types
        if sum(1 for p in patterns if p["type"] == pt) >= 2
    )
    stability = "high" if multi_window_patterns >= 2 else "medium" if multi_window_patterns >= 1 else "low"

    # Deduplicate patterns (keep highest severity per type)
    seen = {}
    for p in patterns:
        key = p["type"]
        if key not in seen or (p["severity"] == "high" and seen[key]["severity"] != "high"):
            seen[key] = p
    unique_patterns = list(seen.values())

    # Generate recommendations
    recommendations = []
    for p in unique_patterns:
        if p["type"] == "repeated_wandering":
            recommendations.append(f"Consider tightening safe zone boundaries. Wandering detected {p['count']}x in {p['window']} window, peaking around {p.get('peak_hour', '?')}:00.")
        elif p["type"] == "recurring_falls":
            recommendations.append(f"Review physical environment. {p['count']} fall events in {p['window']} window suggest potential hazards.")
        elif p["type"] == "voice_distress_clustering":
            recommendations.append(f"Voice distress clustering detected {p['count']}x, peak hour {p.get('peak_hour', '?')}:00. Consider scheduling check-ins at this time.")
        elif p["type"] == "nighttime_incidents":
            recommendations.append("High proportion of nighttime incidents. Consider activating Night Guardian mode.")

    return {
        "anomaly_score": round(min(1.0, anomaly_score), 3),
        "confidence": confidence,
        "stability": stability,
        "patterns": unique_patterns,
        "window_data": window_data,
        "recommendations": recommendations,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
    }
