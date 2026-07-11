"""NISCH-012 — Motion Features E2E Tests.

End-to-end validation of the Continuous Motion Telemetry Bridge against
the live preview backend. Tests the full API surface:

1. POST /api/sensors/motion/features — auth, validation, idempotency
2. GET /api/behavioral/trust/badge — motion_telemetry_stale reason
3. Regression: Fall detection pipeline still works
4. Regression: Behavioral endpoints still respond
5. Regression: Risk predict endpoint still works

Test credentials:
  - Operator: operator@nischint.com / OperatorSecure!2026
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    BASE_URL = "https://gps-mic-restart.preview.emergentagent.com"


# ── Fixtures ─────────────────────────────────────────────────────

# Cache token at module level to avoid repeated logins
_CACHED_TOKEN = None


def _get_operator_token():
    """Get operator auth token (cached)."""
    global _CACHED_TOKEN
    if _CACHED_TOKEN is not None:
        return _CACHED_TOKEN
    
    resp = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={
            "email": "operator@nischint.com",
            "password": "OperatorSecure!2026",
        },
        timeout=30,
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    _CACHED_TOKEN = resp.json()["access_token"]
    return _CACHED_TOKEN


@pytest.fixture(scope="session")
def operator_token():
    """Get operator auth token for authenticated requests."""
    return _get_operator_token()


@pytest.fixture
def auth_headers(operator_token):
    """Headers with auth token."""
    return {
        "Authorization": f"Bearer {operator_token}",
        "Content-Type": "application/json",
    }


# ── Motion Features Endpoint Tests ───────────────────────────────


class TestMotionFeaturesAuth:
    """Auth boundary tests for POST /api/sensors/motion/features."""

    def test_requires_auth_401_without_token(self):
        """Unauth call must be rejected with 401."""
        resp = requests.post(
            f"{BASE_URL}/api/sensors/motion/features",
            json={
                "device_id": "test-device",
                "windows": [{
                    "window_started_at": "2026-05-13T13:00:00Z",
                    "accel_mean_g": 1.0,
                    "accel_stddev_g": 0.1,
                    "accel_peak_g": 1.5,
                    "gyro_variance": 0.05,
                    "activity_class": "walking",
                    "sample_count": 300,
                    "sample_rate_hz": 5.0,
                }],
            },
            timeout=30,
        )
        assert resp.status_code in (401, 403), f"Expected 401/403, got {resp.status_code}"


class TestMotionFeaturesValidation:
    """Validation boundary tests for POST /api/sensors/motion/features."""

    def test_rejects_invalid_activity_class_422(self, auth_headers):
        """Out-of-taxonomy activity_class must be rejected with 422."""
        resp = requests.post(
            f"{BASE_URL}/api/sensors/motion/features",
            headers=auth_headers,
            json={
                "device_id": "test-validate",
                "windows": [{
                    "window_started_at": "2026-05-13T13:00:00Z",
                    "accel_mean_g": 1.0,
                    "accel_stddev_g": 0.1,
                    "accel_peak_g": 1.5,
                    "gyro_variance": 0.05,
                    "activity_class": "definitely_not_a_class",
                    "sample_count": 300,
                    "sample_rate_hz": 5.0,
                }],
            },
            timeout=30,
        )
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
        # Verify error mentions activity_class
        assert "activity_class" in resp.text.lower()

    def test_rejects_batch_over_12_windows_422(self, auth_headers):
        """Batches > 12 windows must be rejected with 422 (per-call cost cap)."""
        windows = [{
            "window_started_at": f"2026-05-13T16:{str(i).zfill(2)}:00Z",
            "accel_mean_g": 1.0,
            "accel_stddev_g": 0.1,
            "accel_peak_g": 1.5,
            "gyro_variance": 0.05,
            "activity_class": "walking",
            "sample_count": 300,
            "sample_rate_hz": 5.0,
        } for i in range(13)]  # 13 windows = over the cap

        resp = requests.post(
            f"{BASE_URL}/api/sensors/motion/features",
            headers=auth_headers,
            json={"device_id": "test-cap", "windows": windows},
            timeout=30,
        )
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"

    @pytest.mark.parametrize("activity_class", [
        "stationary", "walking", "running", "vehicle", "anomalous"
    ])
    def test_accepts_valid_activity_classes(self, auth_headers, activity_class):
        """All 5 valid activity classes must be accepted."""
        unique_ts = f"2026-01-15T20:{str(hash(activity_class) % 60).zfill(2)}:00Z"
        resp = requests.post(
            f"{BASE_URL}/api/sensors/motion/features",
            headers=auth_headers,
            json={
                "device_id": f"test-class-{activity_class}-{uuid.uuid4()}",
                "windows": [{
                    "window_started_at": unique_ts,
                    "accel_mean_g": 1.0,
                    "accel_stddev_g": 0.1,
                    "accel_peak_g": 1.5,
                    "gyro_variance": 0.05,
                    "activity_class": activity_class,
                    "sample_count": 300,
                    "sample_rate_hz": 5.0,
                }],
            },
            timeout=30,
        )
        assert resp.status_code == 200, f"Expected 200 for {activity_class}, got {resp.status_code}: {resp.text}"


class TestMotionFeaturesIdempotency:
    """Idempotency tests for POST /api/sensors/motion/features."""

    def test_idempotency_duplicate_returns_duplicate_status(self, auth_headers):
        """Same (device_id, window_started_at) twice → second call returns status=duplicate."""
        device_id = f"test-idem-{uuid.uuid4()}"
        unique_ts = "2026-01-15T21:30:00Z"
        payload = {
            "device_id": device_id,
            "windows": [{
                "window_started_at": unique_ts,
                "accel_mean_g": 1.0,
                "accel_stddev_g": 0.1,
                "accel_peak_g": 1.5,
                "gyro_variance": 0.05,
                "activity_class": "walking",
                "sample_count": 300,
                "sample_rate_hz": 5.0,
            }],
        }

        # First call — should insert
        r1 = requests.post(
            f"{BASE_URL}/api/sensors/motion/features",
            headers=auth_headers,
            json=payload,
            timeout=30,
        )
        assert r1.status_code == 200, f"First call failed: {r1.text}"
        b1 = r1.json()
        assert b1["status"] == "ok"
        assert b1["inserted"] == 1
        assert b1["duplicate"] == 0

        # Second call — should report duplicate
        r2 = requests.post(
            f"{BASE_URL}/api/sensors/motion/features",
            headers=auth_headers,
            json=payload,
            timeout=30,
        )
        assert r2.status_code == 200, f"Second call failed: {r2.text}"
        b2 = r2.json()
        assert b2["status"] == "ok"
        assert b2["inserted"] == 0
        assert b2["duplicate"] == 1
        # Verify per-row result
        assert b2["results"][0]["status"] == "duplicate"


class TestMotionFeaturesHappyPath:
    """Happy-path tests for POST /api/sensors/motion/features."""

    def test_single_window_returns_200_with_correct_shape(self, auth_headers):
        """Single valid window returns 200 with inserted=1, duplicate=0, failed=0."""
        device_id = f"test-happy-{uuid.uuid4()}"
        unique_ts = f"2026-01-15T22:{str(uuid.uuid4().int % 60).zfill(2)}:00Z"

        resp = requests.post(
            f"{BASE_URL}/api/sensors/motion/features",
            headers=auth_headers,
            json={
                "device_id": device_id,
                "windows": [{
                    "window_started_at": unique_ts,
                    "accel_mean_g": 0.05,
                    "accel_stddev_g": 0.02,
                    "accel_peak_g": 0.12,
                    "gyro_variance": 0.0001,
                    "activity_class": "stationary",
                    "sample_count": 300,
                    "sample_rate_hz": 5.0,
                }],
            },
            timeout=30,
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        body = resp.json()

        # Verify response shape
        assert body["status"] == "ok"
        assert body["inserted"] == 1
        assert body["duplicate"] == 0
        assert body["failed"] == 0
        assert "results" in body
        assert len(body["results"]) == 1
        assert body["results"][0]["status"] == "inserted"
        assert "id" in body["results"][0]

    def test_response_includes_telemetry_pipeline_version(self, auth_headers):
        """Response must include telemetry_pipeline_version field."""
        device_id = f"test-version-{uuid.uuid4()}"
        unique_ts = f"2026-01-15T23:{str(uuid.uuid4().int % 60).zfill(2)}:00Z"

        resp = requests.post(
            f"{BASE_URL}/api/sensors/motion/features",
            headers=auth_headers,
            json={
                "device_id": device_id,
                "windows": [{
                    "window_started_at": unique_ts,
                    "accel_mean_g": 1.0,
                    "accel_stddev_g": 0.1,
                    "accel_peak_g": 1.5,
                    "gyro_variance": 0.05,
                    "activity_class": "running",
                    "sample_count": 300,
                    "sample_rate_hz": 5.0,
                }],
            },
            timeout=30,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "telemetry_pipeline_version" in body
        assert body["telemetry_pipeline_version"].startswith("motion-")

    def test_partial_batch_returns_per_row_results(self, auth_headers):
        """Batch with multiple windows returns per-row results array."""
        device_id = f"test-batch-{uuid.uuid4()}"
        windows = [{
            "window_started_at": f"2026-01-16T0{i}:00:00Z",
            "accel_mean_g": 1.0,
            "accel_stddev_g": 0.1,
            "accel_peak_g": 1.5,
            "gyro_variance": 0.05,
            "activity_class": "walking",
            "sample_count": 300,
            "sample_rate_hz": 5.0,
        } for i in range(3)]

        resp = requests.post(
            f"{BASE_URL}/api/sensors/motion/features",
            headers=auth_headers,
            json={"device_id": device_id, "windows": windows},
            timeout=30,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["inserted"] == 3
        assert len(body["results"]) == 3
        for r in body["results"]:
            assert r["status"] == "inserted"


# ── Trust Badge Tests ────────────────────────────────────────────


class TestTrustBadgeMotionFreshness:
    """Trust badge tests for motion_telemetry_stale reason."""

    def test_badge_returns_3_field_shape(self):
        """GET /api/behavioral/trust/badge returns exactly {level, color, reason}."""
        resp = requests.get(f"{BASE_URL}/api/behavioral/trust/badge", timeout=30)
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == {"level", "color", "reason"}
        assert body["level"] in ("HIGH_TRUST", "MEDIUM_TRUST", "LOW_TRUST")
        assert body["color"] in ("green", "yellow", "red")

    def test_badge_never_returns_low_for_stale_motion_alone(self):
        """Motion staleness alone must surface MEDIUM, never LOW."""
        # This is a contract test — the badge should never be LOW just
        # because motion telemetry is stale. We verify the current state
        # is not LOW with motion_telemetry_stale as the only reason.
        resp = requests.get(f"{BASE_URL}/api/behavioral/trust/badge", timeout=30)
        assert resp.status_code == 200
        body = resp.json()
        if body["reason"] == "motion_telemetry_stale":
            assert body["level"] != "LOW_TRUST", "Motion staleness alone must not cause LOW_TRUST"


# ── Regression Tests: Fall Detection Pipeline ────────────────────


class TestFallDetectionRegression:
    """Regression tests for the 5-stage fall detection pipeline."""

    def test_fall_events_endpoint_responds(self, auth_headers):
        """GET /api/sensors/fall/events must still respond."""
        resp = requests.get(
            f"{BASE_URL}/api/sensors/fall/events",
            headers=auth_headers,
            timeout=30,
        )
        assert resp.status_code == 200, f"Fall events endpoint failed: {resp.text}"
        body = resp.json()
        assert "events" in body
        assert "count" in body

    def test_fall_report_endpoint_responds(self, auth_headers):
        """POST /api/sensors/fall must still respond."""
        resp = requests.post(
            f"{BASE_URL}/api/sensors/fall",
            headers=auth_headers,
            json={
                "lat": 12.97,
                "lng": 77.59,
                "signals": {
                    "impact_score": 0.9,
                    "freefall_score": 0.8,
                    "orientation_score": 0.7,
                    "post_impact_score": 0.6,
                    "immobility_score": 0.5,
                },
            },
            timeout=30,
        )
        # May be 200 or 429 (cooldown) — both are valid
        assert resp.status_code in (200, 429), f"Fall report failed: {resp.text}"


# ── Regression Tests: Behavioral Endpoints ───────────────────────


class TestBehavioralEndpointsRegression:
    """Regression tests for existing behavioral endpoints."""

    def test_baseline_endpoint_responds(self):
        """GET /api/behavioral/baseline/{entity_id} must still respond."""
        entity_id = str(uuid.uuid4())
        resp = requests.get(
            f"{BASE_URL}/api/behavioral/baseline/{entity_id}",
            timeout=30,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "cold_start"
        assert "baseline_version" in body

    def test_anomalies_endpoint_responds(self):
        """GET /api/behavioral/anomalies/{entity_id} must still respond."""
        entity_id = str(uuid.uuid4())
        resp = requests.get(
            f"{BASE_URL}/api/behavioral/anomalies/{entity_id}",
            timeout=30,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "count" in body
        assert "items" in body
        assert "anomaly_pipeline_version" in body

    def test_metrics_endpoint_responds(self):
        """GET /api/behavioral/metrics must still respond."""
        resp = requests.get(f"{BASE_URL}/api/behavioral/metrics", timeout=30)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "anomaly_pipeline_version" in body
        assert "baseline_version" in body

    def test_dlq_endpoint_responds(self):
        """GET /api/behavioral/dlq must still respond."""
        resp = requests.get(f"{BASE_URL}/api/behavioral/dlq", timeout=30)
        assert resp.status_code == 200
        body = resp.json()
        assert "depth" in body
        assert "items" in body


# ── Regression Tests: Risk Predict Endpoint ──────────────────────


class TestRiskPredictRegression:
    """Regression tests for /api/risk/predict endpoint."""

    def test_risk_predict_endpoint_responds(self):
        """GET /api/risk/predict must still respond."""
        resp = requests.get(
            f"{BASE_URL}/api/risk/predict",
            params={"lat": 12.97, "lng": 77.59},
            timeout=30,
        )
        assert resp.status_code == 200
        body = resp.json()
        # Verify response shape
        assert "status" in body
        assert "model_version" in body
        assert "pipeline_version" in body


# ── Run tests ────────────────────────────────────────────────────


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
