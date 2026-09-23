from pathlib import Path
import os

ROOT = Path(os.environ.get("NISCHINT_BACKEND_ROOT", Path(__file__).resolve().parents[1]))


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_core_location_write_is_atomic_monotonic_and_committed_before_optional_side_effects():
    source = read("app/services/geofence_alerts.py")
    fn = source[source.index("async def record_protected_telemetry("):source.index("\ndef _compute_state", source.index("async def record_protected_telemetry("))]
    assert "WITH previous AS" in fn
    assert "UPDATE users" in fn
    assert "last_known_at <= :observed_at" in fn
    assert "EXISTS(SELECT 1 FROM updated) AS accepted_as_latest" in fn
    core_commit = fn.index("await session.commit()")
    redis_write = fn.index('set_json("protected_telemetry"')
    session_lookup = fn.index("active_result = await session.execute(")
    assert core_commit < redis_write < session_lookup
    assert "select(User).where" not in fn


def test_previous_location_for_zone_route_transition_comes_from_same_atomic_core_write():
    service = read("app/services/geofence_alerts.py")
    api = read("app/api/geofence.py")
    fn = service[service.index("async def record_protected_telemetry("):service.index("\ndef _compute_state", service.index("async def record_protected_telemetry("))]
    assert '"previous_lat": previous_lat' in fn
    assert '"previous_lng": previous_lng' in fn
    route = api[api.index('@router.post("/location-update")'):api.index('@router.post("/location-availability")')]
    assert 'previous_lat = telemetry.get("previous_lat")' in route
    assert 'previous_lng = telemetry.get("previous_lng")' in route
    assert "select(User.last_known_lat, User.last_known_lng)" not in route


def test_optional_session_cache_alert_and_sse_failures_cannot_rollback_core_location():
    source = read("app/services/geofence_alerts.py")
    fn = source[source.index("async def record_protected_telemetry("):source.index("\ndef _compute_state", source.index("async def record_protected_telemetry("))]
    assert "cache/presence side effect skipped" in fn
    assert "active-session enrichment skipped" in fn
    assert "live guardian fan-out skipped" in fn
    assert fn.count("await session.rollback()") >= 3
    assert '"core_persisted": accepted_as_latest' in fn


def test_stale_replay_preserves_newer_location_without_optional_pipeline_work():
    source = read("app/services/geofence_alerts.py")
    fn = source[source.index("async def record_protected_telemetry("):source.index("\ndef _compute_state", source.index("async def record_protected_telemetry("))]
    preserved = fn.index('snapshot["latest_preserved"] = True')
    redis_write = fn.index('set_json("protected_telemetry"')
    assert preserved < redis_write
    assert "return snapshot" in fn[preserved:redis_write]


def test_location_response_exposes_safe_core_persistence_fingerprint():
    source = read("app/api/geofence.py")
    route = source[source.index('@router.post("/location-update")'):source.index('@router.post("/location-availability")')]
    assert '"core_persisted": bool(telemetry.get("core_persisted"))' in route
    assert '"evaluation_deferred": evaluation_deferred' in route


def test_location_availability_exposes_v2_deployment_fingerprint():
    source = read("app/api/geofence.py")
    route = source[source.index('@router.post("/location-availability")'):]
    assert '"location_core_version": "v2"' in route
