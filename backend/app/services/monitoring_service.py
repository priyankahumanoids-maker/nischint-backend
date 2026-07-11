# Monitoring Service — Real-time application metrics collection
# Collects API latency, error rates, SOS triggers, AI alerts, DB pool stats,
# guardian sessions, and queue health. In-memory + Redis-backed.

import logging
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from threading import Lock

logger = logging.getLogger(__name__)

_lock = Lock()

# Rolling windows: store last N datapoints
_MAX_WINDOW = 1000

# API latency tracking (per-endpoint)
_api_latencies: dict[str, deque] = defaultdict(lambda: deque(maxlen=_MAX_WINDOW))
_api_error_counts: dict[str, int] = defaultdict(int)
_api_request_counts: dict[str, int] = defaultdict(int)

# Emergency system counters
_sos_triggers: deque = deque(maxlen=_MAX_WINDOW)
_guardian_alerts: deque = deque(maxlen=_MAX_WINDOW)
_escalations: deque = deque(maxlen=_MAX_WINDOW)
_fake_call_activations: deque = deque(maxlen=_MAX_WINDOW)
_fake_notification_activations: deque = deque(maxlen=_MAX_WINDOW)

# AI Safety Brain counters
_risk_spikes: deque = deque(maxlen=_MAX_WINDOW)
_heatmap_alerts: deque = deque(maxlen=_MAX_WINDOW)
_behavior_anomalies: deque = deque(maxlen=_MAX_WINDOW)

# Alert history
_alert_history: deque = deque(maxlen=200)

# Start time
_start_time = time.time()


def record_request(method: str, path: str, status_code: int, duration_ms: float):
    """Record an API request with latency and status."""
    key = f"{method} {path}"
    with _lock:
        _api_latencies[key].append(duration_ms)
        _api_request_counts[key] += 1
        if status_code >= 500:
            _api_error_counts[key] += 1


def record_sos_trigger():
    with _lock:
        _sos_triggers.append(time.time())
        _add_alert("emergency", "SOS triggered", "critical")


def record_guardian_alert(level: str = "medium"):
    with _lock:
        _guardian_alerts.append(time.time())
        if level in ("high", "critical"):
            _add_alert("guardian", f"Guardian alert: {level}", level)


def record_escalation():
    with _lock:
        _escalations.append(time.time())
        _add_alert("escalation", "Escalation to operator", "high")


def record_fake_call():
    with _lock:
        _fake_call_activations.append(time.time())


def record_fake_notification():
    with _lock:
        _fake_notification_activations.append(time.time())


def record_risk_spike(score: float):
    with _lock:
        _risk_spikes.append(time.time())
        if score >= 0.85:
            _add_alert("ai_safety", f"Critical risk spike: {score:.2f}", "critical")


def record_heatmap_alert():
    with _lock:
        _heatmap_alerts.append(time.time())


def record_behavior_anomaly():
    with _lock:
        _behavior_anomalies.append(time.time())


def _add_alert(category: str, message: str, severity: str):
    """Internal: add to alert history."""
    _alert_history.append({
        "category": category,
        "message": message,
        "severity": severity,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


def _count_in_window(dq: deque, window_seconds: int) -> int:
    """Count events within the last N seconds."""
    cutoff = time.time() - window_seconds
    return sum(1 for t in dq if t >= cutoff)


def _percentile(data: deque, p: float) -> float:
    """Calculate percentile from deque of floats."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    idx = int(len(sorted_data) * p / 100)
    idx = min(idx, len(sorted_data) - 1)
    return round(sorted_data[idx], 2)


def get_metrics() -> dict:
    """Get comprehensive platform metrics snapshot."""
    now = time.time()

    with _lock:
        # API metrics
        total_requests = sum(_api_request_counts.values())
        total_errors = sum(_api_error_counts.values())
        all_latencies = []
        for dq in _api_latencies.values():
            all_latencies.extend(dq)

        # Top 5 slowest endpoints
        endpoint_stats = []
        for key, dq in _api_latencies.items():
            if not dq:
                continue
            endpoint_stats.append({
                "endpoint": key,
                "p50_ms": _percentile(dq, 50),
                "p95_ms": _percentile(dq, 95),
                "requests": _api_request_counts.get(key, 0),
                "errors": _api_error_counts.get(key, 0),
            })
        endpoint_stats.sort(key=lambda x: x["p95_ms"], reverse=True)

        # Emergency metrics (last 1h, last 24h)
        emergency_1h = {
            "sos_triggers": _count_in_window(_sos_triggers, 3600),
            "guardian_alerts": _count_in_window(_guardian_alerts, 3600),
            "escalations": _count_in_window(_escalations, 3600),
            "fake_calls": _count_in_window(_fake_call_activations, 3600),
            "fake_notifications": _count_in_window(_fake_notification_activations, 3600),
        }
        emergency_24h = {
            "sos_triggers": _count_in_window(_sos_triggers, 86400),
            "guardian_alerts": _count_in_window(_guardian_alerts, 86400),
            "escalations": _count_in_window(_escalations, 86400),
            "fake_calls": _count_in_window(_fake_call_activations, 86400),
            "fake_notifications": _count_in_window(_fake_notification_activations, 86400),
        }

        # AI Safety metrics (last 1h)
        ai_safety_1h = {
            "risk_spikes": _count_in_window(_risk_spikes, 3600),
            "heatmap_alerts": _count_in_window(_heatmap_alerts, 3600),
            "behavior_anomalies": _count_in_window(_behavior_anomalies, 3600),
        }

    # DB pool stats
    db_pool = _get_db_pool_stats()

    # Redis stats
    redis_stats = _get_redis_stats()

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": round(now - _start_time),
        "platform_health": {
            "api_latency_p50_ms": _percentile(deque(all_latencies), 50) if all_latencies else 0,
            "api_latency_p95_ms": _percentile(deque(all_latencies), 95) if all_latencies else 0,
            "total_requests": total_requests,
            "total_errors_5xx": total_errors,
            "error_rate_pct": round((total_errors / total_requests * 100) if total_requests > 0 else 0, 2),
            "top_endpoints": endpoint_stats[:5],
        },
        "emergency_activity": {
            "last_1h": emergency_1h,
            "last_24h": emergency_24h,
        },
        "ai_safety": ai_safety_1h,
        "database": db_pool,
        "redis": redis_stats,
    }


def get_alerts(limit: int = 50) -> list[dict]:
    """Get recent alert history."""
    with _lock:
        return list(reversed(list(_alert_history)))[:limit]


def _get_db_pool_stats() -> dict:
    """Get SQLAlchemy connection pool statistics."""
    try:
        from app.db.session import engine
        pool = engine.pool
        return {
            "pool_size": pool.size(),
            "checked_out": pool.checkedout(),
            "checked_in": pool.checkedin(),
            "overflow": pool.overflow(),
            "max_overflow": engine.pool._max_overflow,
            "status": "healthy" if pool.checkedout() < pool.size() else "warning",
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _get_redis_stats() -> dict:
    """Get Redis connection and queue statistics."""
    try:
        from app.services.redis_service import is_available, get_info
        if not is_available():
            return {"status": "disconnected"}
        return get_info()
    except Exception:
        return {"status": "unavailable"}
