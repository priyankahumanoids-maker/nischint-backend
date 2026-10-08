from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding='utf-8')


def test_logout_detaches_push_token_from_current_user_only():
    src = read('app/api/auth.py')
    assert 'device_token: Optional[str] = None' in src
    assert 'DELETE FROM push_tokens' in src
    assert 'WHERE user_id = :uid AND token = :token' in src
    assert 'DELETE FROM push_tokens WHERE user_id = :uid' in src  # logout-all


def test_presence_uses_server_receipt_heartbeat_not_batched_gps_timestamp():
    src = read('app/services/geofence_alerts.py')
    assert 'mark_user_ping(user_id, now.isoformat())' in src
    assert 'is_current = observation_age_s <= 300' in src


def test_guardian_presence_windows_tolerate_android_doze_batching():
    dashboard = read('app/services/guardian_dashboard_engine.py')
    live = read('app/api/guardian_live.py')
    assert 'window_s: int = 300' in dashboard
    assert '(now - ping_dt).total_seconds() <= 300' in live
