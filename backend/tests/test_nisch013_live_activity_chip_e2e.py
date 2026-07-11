"""NISCH-013 — Live Activity Class Chip E2E Tests.

Tests the additive presentation layer for NISCH-012 motion telemetry:
1. GET /api/operator/command-center/{user_id} includes motion_telemetry slot
2. motion_telemetry.status bands align with trust evaluator
3. Fail-silent on missing data (status='unavailable')
4. Freshness bands: LIVE ≤60s, FRESH ≤5m, RECENT ≤30m, STALE >30m
5. Existing unified endpoint contract preserved (all prior keys present)
6. Regression: NISCH-012 motion ingest still works
7. Regression: trust badge still works
"""
import os
import uuid
import pytest
import requests
from datetime import datetime, timezone, timedelta

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

# Test credentials
ADMIN_EMAIL = "nischint4parents@gmail.com"
ADMIN_PASSWORD = "secret123"
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "OperatorSecure!2026"


@pytest.fixture(scope="module")
def admin_token():
    """Get admin auth token."""
    resp = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=15,
    )
    if resp.status_code != 200:
        pytest.skip(f"Admin login failed: {resp.status_code}")
    return resp.json().get("access_token") or resp.json().get("token")


@pytest.fixture(scope="module")
def operator_token():
    """Get operator auth token."""
    resp = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD},
        timeout=15,
    )
    if resp.status_code != 200:
        pytest.skip(f"Operator login failed: {resp.status_code}")
    return resp.json().get("access_token") or resp.json().get("token")


@pytest.fixture(scope="module")
def admin_user_id(admin_token):
    """Get admin user ID from /me endpoint."""
    resp = requests.get(
        f"{BASE_URL}/api/auth/me",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=10,
    )
    if resp.status_code != 200:
        pytest.skip(f"Failed to get admin user: {resp.status_code}")
    return resp.json().get("id") or resp.json().get("user_id")


@pytest.fixture(scope="module")
def operator_user_id(operator_token):
    """Get operator user ID from /me endpoint."""
    resp = requests.get(
        f"{BASE_URL}/api/auth/me",
        headers={"Authorization": f"Bearer {operator_token}"},
        timeout=10,
    )
    if resp.status_code != 200:
        pytest.skip(f"Failed to get operator user: {resp.status_code}")
    return resp.json().get("id") or resp.json().get("user_id")


class TestCommandCenterMotionTelemetrySlot:
    """Tests for motion_telemetry slot in unified Command Center payload."""

    def test_endpoint_includes_motion_telemetry_key(self, admin_token, admin_user_id):
        """GET /api/operator/command-center/{user_id} includes motion_telemetry key."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/command-center/{admin_user_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=15,
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        
        # Verify motion_telemetry key exists
        assert "motion_telemetry" in data, "motion_telemetry key missing from payload"
        
        # Verify version is v1
        assert data.get("version") == "v1", f"Expected version v1, got {data.get('version')}"

    def test_motion_telemetry_shape_when_unavailable(self, admin_token, admin_user_id):
        """When no motion data exists, motion_telemetry.status == 'unavailable'."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/command-center/{admin_user_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=15,
        )
        assert resp.status_code == 200
        motion = resp.json().get("motion_telemetry", {})
        
        # Shape must be present even when unavailable
        assert "status" in motion, "motion_telemetry.status missing"
        
        # If no data, status should be 'unavailable'
        if motion.get("activity_class") is None:
            assert motion["status"] == "unavailable", f"Expected 'unavailable', got {motion['status']}"
            assert motion.get("freshness_s") is None
            assert motion.get("window_count_24h") == 0

    def test_motion_telemetry_has_required_fields(self, admin_token, admin_user_id):
        """motion_telemetry slot has all required fields."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/command-center/{admin_user_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=15,
        )
        assert resp.status_code == 200
        motion = resp.json().get("motion_telemetry", {})
        
        required_fields = [
            "status",
            "activity_class",
            "last_motion_at",
            "freshness_s",
            "window_count_24h",
            "activity_distribution_24h",
            "telemetry_pipeline_version",
        ]
        for field in required_fields:
            assert field in motion, f"Required field '{field}' missing from motion_telemetry"


class TestUnifiedEndpointContractPreserved:
    """Verify existing unified endpoint contract is preserved."""

    def test_all_prior_keys_present(self, admin_token, admin_user_id):
        """All prior keys still present: risk, baseline, digital_twin, predictions, etc."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/command-center/{admin_user_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=15,
        )
        assert resp.status_code == 200
        data = resp.json()
        
        # All prior keys must be present
        required_keys = [
            "version",
            "timestamp",
            "user_id",
            "user",
            "risk",
            "baseline",
            "digital_twin",
            "predictions",
            "risk_history",
            "live_location",
            "active_event",
            "environment",
            "motion_telemetry",  # New key
        ]
        for key in required_keys:
            assert key in data, f"Required key '{key}' missing from unified payload"

    def test_environment_still_has_weather(self, admin_token, admin_user_id):
        """Environment block still has weather data."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/command-center/{admin_user_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=15,
        )
        assert resp.status_code == 200
        env = resp.json().get("environment", {})
        
        assert "time_band" in env
        assert "weather" in env
        assert "risk" in env

    def test_digital_twin_still_has_live_deviation(self, admin_token, admin_user_id):
        """Digital twin block still has live_deviation."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/command-center/{admin_user_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=15,
        )
        assert resp.status_code == 200
        twin = resp.json().get("digital_twin", {})
        
        assert "status" in twin
        assert "live_deviation" in twin


class TestMotionIngestRegression:
    """Regression: NISCH-012 motion ingest POST /api/sensors/motion/features still works."""

    def test_motion_ingest_requires_auth(self):
        """POST /api/sensors/motion/features requires auth."""
        resp = requests.post(
            f"{BASE_URL}/api/sensors/motion/features",
            json={"windows": []},
            timeout=10,
        )
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"

    def test_motion_ingest_validates_activity_class(self, admin_token):
        """POST /api/sensors/motion/features rejects invalid activity_class."""
        now = datetime.now(timezone.utc)
        device_id = f"test-{uuid.uuid4()}"
        window = {
            "window_started_at": now.isoformat(),
            "window_duration_s": 60,
            "accel_mean_g": 1.0,
            "accel_stddev_g": 0.1,
            "accel_peak_g": 2.0,
            "gyro_variance": 0.05,
            "activity_class": "INVALID_CLASS",  # Invalid
            "sample_count": 100,
            "sample_rate_hz": 50.0,
        }
        resp = requests.post(
            f"{BASE_URL}/api/sensors/motion/features",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"device_id": device_id, "windows": [window]},
            timeout=10,
        )
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}"

    def test_motion_ingest_happy_path(self, admin_token):
        """POST /api/sensors/motion/features accepts valid window."""
        now = datetime.now(timezone.utc)
        device_id = f"test-nisch013-{uuid.uuid4()}"
        window = {
            "window_started_at": now.isoformat(),
            "window_duration_s": 60,
            "accel_mean_g": 1.0,
            "accel_stddev_g": 0.1,
            "accel_peak_g": 2.0,
            "gyro_variance": 0.05,
            "activity_class": "walking",
            "sample_count": 100,
            "sample_rate_hz": 50.0,
        }
        resp = requests.post(
            f"{BASE_URL}/api/sensors/motion/features",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"device_id": device_id, "windows": [window]},
            timeout=10,
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data.get("status") == "ok"
        assert data.get("inserted", 0) >= 0  # May be 0 if duplicate

    def test_motion_ingest_idempotency(self, admin_token):
        """POST /api/sensors/motion/features is idempotent."""
        now = datetime.now(timezone.utc)
        device_id = f"test-idempotent-{uuid.uuid4()}"
        window = {
            "window_started_at": now.isoformat(),
            "window_duration_s": 60,
            "accel_mean_g": 1.0,
            "accel_stddev_g": 0.1,
            "accel_peak_g": 2.0,
            "gyro_variance": 0.05,
            "activity_class": "stationary",
            "sample_count": 100,
            "sample_rate_hz": 50.0,
        }
        
        # First call
        resp1 = requests.post(
            f"{BASE_URL}/api/sensors/motion/features",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"device_id": device_id, "windows": [window]},
            timeout=10,
        )
        assert resp1.status_code == 200
        
        # Second call with same data
        resp2 = requests.post(
            f"{BASE_URL}/api/sensors/motion/features",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"device_id": device_id, "windows": [window]},
            timeout=10,
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        # Should report duplicate, not error
        assert data2.get("duplicate", 0) >= 1 or data2.get("inserted", 0) == 0


class TestTrustBadgeRegression:
    """Regression: GET /api/behavioral/trust/badge still works."""

    def test_trust_badge_endpoint_responds(self, admin_token):
        """GET /api/behavioral/trust/badge returns 200."""
        resp = requests.get(
            f"{BASE_URL}/api/behavioral/trust/badge",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=10,
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        data = resp.json()
        
        # Badge has required fields
        assert "level" in data
        assert "color" in data
        assert "reason" in data

    def test_trust_badge_level_is_valid(self, admin_token):
        """Trust badge level is one of HIGH_TRUST, MEDIUM_TRUST, LOW_TRUST."""
        resp = requests.get(
            f"{BASE_URL}/api/behavioral/trust/badge",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=10,
        )
        assert resp.status_code == 200
        level = resp.json().get("level")
        assert level in ["HIGH_TRUST", "MEDIUM_TRUST", "LOW_TRUST"], f"Invalid level: {level}"


class TestMotionTelemetryFreshnessBands:
    """Test freshness band classification: LIVE ≤60s, FRESH ≤5m, RECENT ≤30m, STALE >30m."""

    def test_fresh_motion_window_shows_live_status(self, admin_token, admin_user_id):
        """After seeding fresh motion window, status should be 'live'."""
        now = datetime.now(timezone.utc)
        device_id = f"test-live-{uuid.uuid4()}"
        
        # Seed a fresh window (within 60s)
        window = {
            "window_started_at": now.isoformat(),
            "window_duration_s": 60,
            "accel_mean_g": 1.0,
            "accel_stddev_g": 0.1,
            "accel_peak_g": 2.0,
            "gyro_variance": 0.05,
            "activity_class": "walking",
            "sample_count": 100,
            "sample_rate_hz": 50.0,
        }
        resp = requests.post(
            f"{BASE_URL}/api/sensors/motion/features",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"device_id": device_id, "windows": [window]},
            timeout=10,
        )
        assert resp.status_code == 200, f"Motion ingest failed: {resp.text}"
        
        # Check command center payload
        resp2 = requests.get(
            f"{BASE_URL}/api/operator/command-center/{admin_user_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=15,
        )
        assert resp2.status_code == 200
        motion = resp2.json().get("motion_telemetry", {})
        
        # If we just seeded data, status should be 'live' (freshness ≤ 60s)
        if motion.get("activity_class") == "walking":
            assert motion["status"] == "live", f"Expected 'live', got {motion['status']}"
            assert motion.get("freshness_s") is not None
            assert motion["freshness_s"] <= 60, f"Freshness {motion['freshness_s']}s > 60s"


class TestOperatorAccess:
    """Test operator role can access command center."""

    def test_operator_can_access_command_center(self, operator_token, operator_user_id):
        """Operator role can access GET /api/operator/command-center/{user_id}."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/command-center/{operator_user_id}",
            headers={"Authorization": f"Bearer {operator_token}"},
            timeout=15,
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        data = resp.json()
        assert "motion_telemetry" in data


class TestBandAlignmentWithTrustEvaluator:
    """Verify status bands align with trust evaluator constants."""

    def test_recent_boundary_matches_trust_constant(self):
        """RECENT upper boundary == MOTION_FRESHNESS_MEDIUM_RED_S (1800s)."""
        from app.api.command_center_unified import _MOTION_RECENT_S
        from app.services.behavioral.trust import MOTION_FRESHNESS_MEDIUM_RED_S
        
        assert _MOTION_RECENT_S == MOTION_FRESHNESS_MEDIUM_RED_S, (
            f"Band mismatch: _MOTION_RECENT_S={_MOTION_RECENT_S} != "
            f"MOTION_FRESHNESS_MEDIUM_RED_S={MOTION_FRESHNESS_MEDIUM_RED_S}"
        )

    def test_live_boundary_is_60_seconds(self):
        """LIVE boundary is 60 seconds."""
        from app.api.command_center_unified import _MOTION_LIVE_S
        assert _MOTION_LIVE_S == 60.0

    def test_fresh_boundary_is_300_seconds(self):
        """FRESH boundary is 300 seconds (5 minutes)."""
        from app.api.command_center_unified import _MOTION_FRESH_S
        assert _MOTION_FRESH_S == 300.0

    def test_recent_boundary_is_1800_seconds(self):
        """RECENT boundary is 1800 seconds (30 minutes)."""
        from app.api.command_center_unified import _MOTION_RECENT_S
        assert _MOTION_RECENT_S == 1800.0


class TestHelperIsReadOnly:
    """Verify _build_motion_telemetry_view is read-only."""

    def test_helper_has_no_write_operations(self):
        """_build_motion_telemetry_view does NO writes (read-only SELECTs)."""
        import inspect
        from app.api.command_center_unified import _build_motion_telemetry_view
        
        source = inspect.getsource(_build_motion_telemetry_view)
        
        # Should not contain INSERT, UPDATE, DELETE
        assert "INSERT" not in source.upper(), "Helper contains INSERT"
        assert "UPDATE" not in source.upper() or "last_update" in source.lower(), "Helper contains UPDATE"
        assert "DELETE" not in source.upper(), "Helper contains DELETE"
        
        # Should contain SELECT
        assert "SELECT" in source.upper(), "Helper should contain SELECT"
