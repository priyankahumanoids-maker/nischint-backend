from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = (ROOT / "app/services/guardian_mode_engine.py").read_text(encoding="utf-8")
GEOFENCE_PATH = ROOT / "app/services/geofence_alerts.py"
GEOFENCE = GEOFENCE_PATH.read_text(encoding="utf-8") if GEOFENCE_PATH.exists() else ""


def test_journey_ordering_is_decoupled_from_passive_previous_update_at():
    assert 'current_location_snapshot.get("_journey_recorded_at")' in ENGINE
    assert 'JourneyPoint.gps_recorded_at' in ENGINE
    assert 'normalized_timestamp <= last_journey_recorded_at' in ENGINE
    assert 'timestamp <= gs.previous_update_at' not in ENGINE


def test_accepted_journey_fix_persists_durable_journey_marker():
    assert 'next_current_location["_journey_recorded_at"]' in ENGINE
    assert 'gs.current_location = next_current_location' in ENGINE


def test_location_sse_includes_authoritative_session_eta():
    assert '"session_id": str(gs.id)' in ENGINE
    assert '"eta_minutes": eta' in ENGINE


def test_cross_path_contract_handles_passive_liveness_before_journey_packet():
    if GEOFENCE:
        assert 'active_session.previous_update_at = observed_at' in GEOFENCE
    assert 'normalized_timestamp <= last_journey_recorded_at' in ENGINE
