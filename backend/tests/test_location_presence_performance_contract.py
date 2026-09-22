from pathlib import Path
import os

ROOT = Path(os.environ.get('NISCHINT_BACKEND_ROOT', Path(__file__).resolve().parents[1]))


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding='utf-8')


def test_location_update_commits_core_telemetry_before_optional_geofence_evaluation():
    source = read('app/api/geofence.py')
    telemetry = source.index('telemetry = await record_protected_telemetry(')
    core_commit = source.index('await session.commit()', telemetry)
    availability = source.index('await record_location_availability(', core_commit)
    evaluation = source.index('result = await evaluate_user_location(', availability)
    rollback = source.index('await session.rollback()', evaluation)
    assert telemetry < core_commit < availability < evaluation < rollback
    assert 'evaluation_deferred' in source
    assert 'Location recorded; safety-boundary evaluation will retry on the next fix.' in source


def test_available_status_is_presence_only_not_fake_location_recovery():
    source = read('app/api/geofence.py')
    route = source[source.index('@router.post("/location-availability")'):]
    assert 'if req.available:' in route
    assert 'mark_user_ping(str(user.id), now)' in route
    assert '"presence_heartbeat": True' in route
    available_branch = route[route.index('if req.available:'):route.index('from app.services.location_availability import record_location_availability')]
    assert 'record_location_availability(' not in available_branch


def test_geofence_evaluator_skips_bad_assignment_instead_of_breaking_all_location_ingestion():
    source = read('app/services/geofence_alerts.py')
    evaluator = source[source.index('async def evaluate_user_location('):]
    assert 'invalid zone skipped' in evaluator
    assert 'invalid route skipped' in evaluator
    assert 'math.isfinite' in evaluator
    assert 'if not assignment_states:' in evaluator
    assert 'zone SSE skipped' in evaluator


def test_successful_protected_telemetry_refreshes_active_session_liveness():
    source = read('app/services/geofence_alerts.py')
    assert 'active_session.last_seen_online_at = now' in source
    assert 'active_session.is_offline = False' in source
    assert 'mark_user_ping(user_id, now.isoformat())' in source


def test_guardian_dashboard_has_durable_presence_fallback_without_changing_location_timestamp():
    source = read('app/services/guardian_dashboard_engine.py')
    assert 'def _presence_from_datetime' in source
    assert 'active_session.last_seen_online_at' in source
    assert 'elif _presence_from_datetime(user.last_known_at, now):' in source
    assert '"presence_online": presence_online' in source
    assert '"last_seen_online_at": last_seen_online_at' in source
