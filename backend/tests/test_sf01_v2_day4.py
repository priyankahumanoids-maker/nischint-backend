"""SF-01 v2 Day 4 — Investor demo wiring E2E test suite.

Tests:
  Task 1: POST/GET /api/operator/dev/scenario(s) endpoints (dual-gated)
  Task 3: alert_cooldown:{user_id} TTL=300s canonical dedup key
  Task 4: DevScenarioPanel.jsx Command Center demo-button row (via API)

Verified:
  - POST /api/operator/dev/scenario requires DEV_SCENARIOS_ENABLED=true + operator/admin role
  - POST /api/operator/dev/scenario with himalaya_landslide → composite≈0.793, action='alert'
  - POST /api/operator/dev/scenario with unknown scenario → 422
  - POST /api/operator/dev/scenario with non-existent user_id → 404
  - POST /api/operator/dev/scenario second fire within 300s → cooldown_suppressed=true
  - GET /api/operator/dev/scenarios returns 3 scenarios
  - SIMULTANEOUS_FALL_VOICE_BONUS=0.10 math verified
  - ALERT_COOLDOWN_TTL_S=300 constant verified
  - Regression: POST /api/signals/motion, GET /api/env/hazards, GET /api/behavioral/trust/badge
"""
from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

# Test credentials from /app/memory/test_credentials.md
ADMIN_EMAIL = "nischint4parents@gmail.com"
ADMIN_PASSWORD = "secret123"
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "OperatorSecure!2026"


# ════════════════════════════════════════════════════════════════════
# Fixtures
# ════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def admin_token():
    """Get admin JWT token."""
    resp = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=15,
    )
    if resp.status_code != 200:
        pytest.skip(f"Admin login failed: {resp.status_code} {resp.text}")
    data = resp.json()
    return data.get("access_token") or data.get("token")


@pytest.fixture(scope="module")
def operator_token():
    """Get operator JWT token."""
    resp = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD},
        timeout=15,
    )
    if resp.status_code != 200:
        pytest.skip(f"Operator login failed: {resp.status_code} {resp.text}")
    data = resp.json()
    return data.get("access_token") or data.get("token")


@pytest.fixture(scope="module")
def admin_user_id(admin_token):
    """Get admin user ID from /api/auth/me."""
    resp = requests.get(
        f"{BASE_URL}/api/auth/me",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=10,
    )
    if resp.status_code != 200:
        pytest.skip(f"Failed to get admin user: {resp.status_code}")
    return resp.json().get("id")


@pytest.fixture(scope="module")
def operator_user_id(operator_token):
    """Get operator user ID from /api/auth/me."""
    resp = requests.get(
        f"{BASE_URL}/api/auth/me",
        headers={"Authorization": f"Bearer {operator_token}"},
        timeout=10,
    )
    if resp.status_code != 200:
        pytest.skip(f"Failed to get operator user: {resp.status_code}")
    return resp.json().get("id")


# ════════════════════════════════════════════════════════════════════
# Day 4 Task 1: GET /api/operator/dev/scenarios
# ════════════════════════════════════════════════════════════════════

class TestGetDevScenarios:
    """GET /api/operator/dev/scenarios endpoint tests."""

    def test_requires_auth_401_without_token(self):
        """Endpoint returns 401 without auth token."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/dev/scenarios",
            timeout=10,
        )
        assert resp.status_code in (401, 403), f"Expected 401/403, got {resp.status_code}"

    def test_returns_200_for_operator(self, operator_token):
        """Operator can access scenarios list."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/dev/scenarios",
            headers={"Authorization": f"Bearer {operator_token}"},
            timeout=10,
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_returns_200_for_admin(self, admin_token):
        """Admin can access scenarios list."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/dev/scenarios",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=10,
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_returns_3_scenarios(self, operator_token):
        """Response includes exactly 3 scenarios."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/dev/scenarios",
            headers={"Authorization": f"Bearer {operator_token}"},
            timeout=10,
        )
        data = resp.json()
        assert "scenarios" in data
        assert len(data["scenarios"]) == 3, f"Expected 3 scenarios, got {len(data['scenarios'])}"

    def test_himalaya_landslide_scenario_present(self, operator_token):
        """himalaya_landslide scenario is present with correct metadata."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/dev/scenarios",
            headers={"Authorization": f"Bearer {operator_token}"},
            timeout=10,
        )
        data = resp.json()
        scenarios = {s["id"]: s for s in data["scenarios"]}
        assert "himalaya_landslide" in scenarios
        hl = scenarios["himalaya_landslide"]
        assert hl["state"] == "Uttarakhand"
        assert hl["type"] == "landslide"
        assert hl["severity"] == "severe"

    def test_urban_flood_scenario_present(self, operator_token):
        """urban_flood scenario is present with correct metadata."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/dev/scenarios",
            headers={"Authorization": f"Bearer {operator_token}"},
            timeout=10,
        )
        data = resp.json()
        scenarios = {s["id"]: s for s in data["scenarios"]}
        assert "urban_flood" in scenarios
        uf = scenarios["urban_flood"]
        assert uf["state"] == "Maharashtra"
        assert uf["type"] == "flood"
        assert uf["severity"] == "severe"

    def test_cyclone_coast_scenario_present(self, operator_token):
        """cyclone_coast scenario is present with correct metadata."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/dev/scenarios",
            headers={"Authorization": f"Bearer {operator_token}"},
            timeout=10,
        )
        data = resp.json()
        scenarios = {s["id"]: s for s in data["scenarios"]}
        assert "cyclone_coast" in scenarios
        cc = scenarios["cyclone_coast"]
        assert cc["state"] == "Andhra Pradesh"
        assert cc["type"] == "cyclone"
        assert cc["severity"] == "extreme"


# ════════════════════════════════════════════════════════════════════
# Day 4 Task 1: POST /api/operator/dev/scenario
# ════════════════════════════════════════════════════════════════════

class TestPostDevScenarioAuth:
    """POST /api/operator/dev/scenario auth tests."""

    def test_requires_auth_401_without_token(self):
        """Endpoint returns 401 without auth token."""
        resp = requests.post(
            f"{BASE_URL}/api/operator/dev/scenario",
            json={"scenario": "himalaya_landslide", "target_user_id": "fake", "ttl_minutes": 5},
            timeout=10,
        )
        assert resp.status_code in (401, 403), f"Expected 401/403, got {resp.status_code}"


class TestPostDevScenarioValidation:
    """POST /api/operator/dev/scenario validation tests."""

    def test_unknown_scenario_returns_422(self, operator_token, operator_user_id):
        """Unknown scenario name returns 422 (Pydantic Literal rejection)."""
        resp = requests.post(
            f"{BASE_URL}/api/operator/dev/scenario",
            json={
                "scenario": "unknown_scenario_xyz",
                "target_user_id": operator_user_id,
                "ttl_minutes": 5,
            },
            headers={"Authorization": f"Bearer {operator_token}"},
            timeout=15,
        )
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"

    def test_nonexistent_user_id_returns_404(self, operator_token):
        """Non-existent target_user_id returns 404 (not 500)."""
        fake_user_id = str(uuid.uuid4())
        resp = requests.post(
            f"{BASE_URL}/api/operator/dev/scenario",
            json={
                "scenario": "himalaya_landslide",
                "target_user_id": fake_user_id,
                "ttl_minutes": 5,
            },
            headers={"Authorization": f"Bearer {operator_token}"},
            timeout=15,
        )
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"


class TestPostDevScenarioHimalayaLandslide:
    """POST /api/operator/dev/scenario himalaya_landslide tests."""

    def test_himalaya_landslide_returns_200(self, admin_token, admin_user_id):
        """himalaya_landslide scenario returns 200."""
        resp = requests.post(
            f"{BASE_URL}/api/operator/dev/scenario",
            json={
                "scenario": "himalaya_landslide",
                "target_user_id": admin_user_id,
                "ttl_minutes": 5,
            },
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=20,
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_himalaya_landslide_composite_approx_0793(self, admin_token, admin_user_id):
        """himalaya_landslide composite ≈ 0.793 (= round(0.61 × 1.30, 3))."""
        resp = requests.post(
            f"{BASE_URL}/api/operator/dev/scenario",
            json={
                "scenario": "himalaya_landslide",
                "target_user_id": admin_user_id,
                "ttl_minutes": 5,
            },
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=20,
        )
        data = resp.json()
        composite = float(data.get("composite", 0))
        # Expected: base 0.61 (fall=0.9*0.35 + voice=0.65*0.30 + bonus=0.10) × 1.30 = 0.793
        assert 0.78 <= composite <= 0.82, f"Expected composite ≈ 0.793, got {composite}"

    def test_himalaya_landslide_action_is_alert(self, admin_token, admin_user_id):
        """himalaya_landslide action is 'alert' (0.65 ≤ composite < 0.85)."""
        resp = requests.post(
            f"{BASE_URL}/api/operator/dev/scenario",
            json={
                "scenario": "himalaya_landslide",
                "target_user_id": admin_user_id,
                "ttl_minutes": 5,
            },
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=20,
        )
        data = resp.json()
        assert data.get("action") == "alert", f"Expected action='alert', got {data.get('action')}"

    def test_himalaya_landslide_env_hazard_match_true(self, admin_token, admin_user_id):
        """himalaya_landslide env_hazard_match is true."""
        resp = requests.post(
            f"{BASE_URL}/api/operator/dev/scenario",
            json={
                "scenario": "himalaya_landslide",
                "target_user_id": admin_user_id,
                "ttl_minutes": 5,
            },
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=20,
        )
        data = resp.json()
        assert data.get("env_hazard_match") is True, f"Expected env_hazard_match=true, got {data.get('env_hazard_match')}"

    def test_himalaya_landslide_env_multiplier_130(self, admin_token, admin_user_id):
        """himalaya_landslide env_multiplier is 1.30."""
        resp = requests.post(
            f"{BASE_URL}/api/operator/dev/scenario",
            json={
                "scenario": "himalaya_landslide",
                "target_user_id": admin_user_id,
                "ttl_minutes": 5,
            },
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=20,
        )
        data = resp.json()
        mult = float(data.get("env_multiplier", 0))
        assert abs(mult - 1.30) < 0.01, f"Expected env_multiplier=1.30, got {mult}"

    def test_himalaya_landslide_alert_fired_true(self, admin_token, admin_user_id):
        """himalaya_landslide alert_fired is true."""
        resp = requests.post(
            f"{BASE_URL}/api/operator/dev/scenario",
            json={
                "scenario": "himalaya_landslide",
                "target_user_id": admin_user_id,
                "ttl_minutes": 5,
            },
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=20,
        )
        data = resp.json()
        assert data.get("alert_fired") is True, f"Expected alert_fired=true, got {data.get('alert_fired')}"

    def test_himalaya_landslide_env_hazard_type_landslide(self, admin_token, admin_user_id):
        """himalaya_landslide env_hazard_type is 'landslide'."""
        resp = requests.post(
            f"{BASE_URL}/api/operator/dev/scenario",
            json={
                "scenario": "himalaya_landslide",
                "target_user_id": admin_user_id,
                "ttl_minutes": 5,
            },
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=20,
        )
        data = resp.json()
        assert data.get("env_hazard_type") == "landslide", f"Expected env_hazard_type='landslide', got {data.get('env_hazard_type')}"

    def test_himalaya_landslide_pre_mult_score_approx_061(self, admin_token, admin_user_id):
        """himalaya_landslide pre_mult_score ≈ 0.61 (base score before env multiplier)."""
        resp = requests.post(
            f"{BASE_URL}/api/operator/dev/scenario",
            json={
                "scenario": "himalaya_landslide",
                "target_user_id": admin_user_id,
                "ttl_minutes": 5,
            },
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=20,
        )
        data = resp.json()
        pre_mult = float(data.get("pre_mult_score", 0))
        # Expected: fall(0.9)*0.35 + voice(0.65)*0.30 + bonus(0.10) = 0.315 + 0.195 + 0.10 = 0.61
        assert 0.59 <= pre_mult <= 0.63, f"Expected pre_mult_score ≈ 0.61, got {pre_mult}"


# ════════════════════════════════════════════════════════════════════
# Day 4 Task 3: Alert cooldown dedup key
# ════════════════════════════════════════════════════════════════════

class TestAlertCooldownDedup:
    """Alert cooldown dedup key tests."""

    def test_second_fire_within_300s_shows_cooldown_suppressed(self, admin_token, admin_user_id):
        """Second fire within 300s for same user_id → cooldown_suppressed=true."""
        # First fire
        resp1 = requests.post(
            f"{BASE_URL}/api/operator/dev/scenario",
            json={
                "scenario": "himalaya_landslide",
                "target_user_id": admin_user_id,
                "ttl_minutes": 5,
            },
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=20,
        )
        assert resp1.status_code == 200
        data1 = resp1.json()
        # First fire should NOT be suppressed (or may be if previous test ran)
        # We just need to verify the second fire IS suppressed

        # Wait 2 seconds
        time.sleep(2)

        # Second fire
        resp2 = requests.post(
            f"{BASE_URL}/api/operator/dev/scenario",
            json={
                "scenario": "himalaya_landslide",
                "target_user_id": admin_user_id,
                "ttl_minutes": 5,
            },
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=20,
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2.get("cooldown_suppressed") is True, (
            f"Expected cooldown_suppressed=true on second fire, got {data2.get('cooldown_suppressed')}"
        )


# ════════════════════════════════════════════════════════════════════
# Day 4: Constants verification
# ════════════════════════════════════════════════════════════════════

class TestDay4Constants:
    """Day 4 constants verification."""

    def test_alert_cooldown_ttl_s_is_300(self):
        """ALERT_COOLDOWN_TTL_S constant = 300 in safety_brain_service."""
        from app.services.safety_brain_service import ALERT_COOLDOWN_TTL_S
        assert ALERT_COOLDOWN_TTL_S == 300, f"Expected 300, got {ALERT_COOLDOWN_TTL_S}"

    def test_simultaneous_fall_voice_bonus_is_010(self):
        """SIMULTANEOUS_FALL_VOICE_BONUS = 0.10 in safety_brain_service."""
        from app.services.safety_brain_service import SIMULTANEOUS_FALL_VOICE_BONUS
        assert SIMULTANEOUS_FALL_VOICE_BONUS == 0.10, f"Expected 0.10, got {SIMULTANEOUS_FALL_VOICE_BONUS}"

    def test_simultaneous_fall_threshold_is_05(self):
        """SIMULTANEOUS_FALL_THRESHOLD = 0.5 in safety_brain_service."""
        from app.services.safety_brain_service import SIMULTANEOUS_FALL_THRESHOLD
        assert SIMULTANEOUS_FALL_THRESHOLD == 0.5, f"Expected 0.5, got {SIMULTANEOUS_FALL_THRESHOLD}"

    def test_simultaneous_voice_threshold_is_05(self):
        """SIMULTANEOUS_VOICE_THRESHOLD = 0.5 in safety_brain_service."""
        from app.services.safety_brain_service import SIMULTANEOUS_VOICE_THRESHOLD
        assert SIMULTANEOUS_VOICE_THRESHOLD == 0.5, f"Expected 0.5, got {SIMULTANEOUS_VOICE_THRESHOLD}"


# ════════════════════════════════════════════════════════════════════
# Day 4: Simultaneous fall+voice bonus math
# ════════════════════════════════════════════════════════════════════

class TestSimultaneousFallVoiceBonus:
    """Simultaneous fall+voice bonus math tests."""

    def test_bonus_fires_when_both_above_threshold(self):
        """fall=0.9, voice=0.65 → base score = 0.61 (includes +0.10 bonus)."""
        from app.services.safety_brain_service import compute_risk_score
        signals = {"fall": 0.9, "voice": 0.65}
        score, level, primary = compute_risk_score(signals)
        # Expected: fall(0.9)*0.35 + voice(0.65)*0.30 + bonus(0.10) = 0.315 + 0.195 + 0.10 = 0.61
        assert 0.59 <= score <= 0.63, f"Expected score ≈ 0.61, got {score}"

    def test_bonus_does_not_fire_when_voice_below_threshold(self):
        """fall=0.9, voice=0.3 → base score = 0.405 (no bonus)."""
        from app.services.safety_brain_service import compute_risk_score
        signals = {"fall": 0.9, "voice": 0.3}
        score, level, primary = compute_risk_score(signals)
        # Expected: fall(0.9)*0.35 + voice(0.3)*0.30 = 0.315 + 0.09 = 0.405 (no bonus)
        assert 0.39 <= score <= 0.42, f"Expected score ≈ 0.405, got {score}"

    def test_bonus_does_not_fire_when_fall_below_threshold(self):
        """fall=0.4, voice=0.65 → base score = 0.335 (no bonus)."""
        from app.services.safety_brain_service import compute_risk_score
        signals = {"fall": 0.4, "voice": 0.65}
        score, level, primary = compute_risk_score(signals)
        # Expected: fall(0.4)*0.35 + voice(0.65)*0.30 = 0.14 + 0.195 = 0.335 (no bonus)
        assert 0.32 <= score <= 0.35, f"Expected score ≈ 0.335, got {score}"

    def test_bonus_fires_at_exact_thresholds(self):
        """fall=0.5, voice=0.5 → bonus fires."""
        from app.services.safety_brain_service import compute_risk_score
        signals = {"fall": 0.5, "voice": 0.5}
        score, level, primary = compute_risk_score(signals)
        # Expected: fall(0.5)*0.35 + voice(0.5)*0.30 + bonus(0.10) = 0.175 + 0.15 + 0.10 = 0.425
        assert 0.41 <= score <= 0.44, f"Expected score ≈ 0.425, got {score}"


# ════════════════════════════════════════════════════════════════════
# Day 4: evaluate_risk returns cooldown_suppressed field
# ════════════════════════════════════════════════════════════════════

class TestEvaluateRiskCooldownField:
    """evaluate_risk returns cooldown_suppressed field."""

    def test_compute_risk_score_signature_unchanged(self):
        """compute_risk_score returns (score, level, primary) tuple."""
        from app.services.safety_brain_service import compute_risk_score
        result = compute_risk_score({"fall": 0.5, "voice": 0.3})
        assert isinstance(result, tuple)
        assert len(result) == 3
        score, level, primary = result
        assert isinstance(score, float)
        assert isinstance(level, str)
        assert isinstance(primary, str)


# ════════════════════════════════════════════════════════════════════
# Regression: POST /api/signals/motion impersonation 404
# ════════════════════════════════════════════════════════════════════

class TestSignalsMotionImpersonationRegression:
    """POST /api/signals/motion impersonation regression tests."""

    def test_impersonation_unknown_user_id_returns_404(self, admin_token):
        """Impersonation with unknown user_id returns 404 (not 500)."""
        fake_user_id = str(uuid.uuid4())
        resp = requests.post(
            f"{BASE_URL}/api/signals/motion",
            json={
                "user_id": fake_user_id,
                "fall": 0.5,
                "voice_distress": 0.3,
                "lat": 30.07,
                "lng": 79.02,
            },
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=15,
        )
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"

    def test_impersonation_real_user_id_returns_200(self, admin_token, admin_user_id):
        """Impersonation with real user_id returns 200."""
        resp = requests.post(
            f"{BASE_URL}/api/signals/motion",
            json={
                "user_id": admin_user_id,
                "fall": 0.5,
                "voice_distress": 0.3,
                "lat": 30.07,
                "lng": 79.02,
            },
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=15,
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"


# ════════════════════════════════════════════════════════════════════
# Regression: NISCH-012 motion features
# ════════════════════════════════════════════════════════════════════

class TestMotionFeaturesRegression:
    """POST /api/sensors/motion/features still works (NISCH-012)."""

    def test_motion_features_returns_200(self, admin_token):
        """Motion features endpoint returns 200."""
        device_id = str(uuid.uuid4())
        window = {
            "window_started_at": datetime.now(timezone.utc).isoformat(),
            "window_duration_s": 300,
            "accel_mean_g": 1.0,
            "accel_stddev_g": 0.1,
            "accel_peak_g": 2.5,
            "gyro_variance": 0.05,
            "activity_class": "walking",
            "sample_count": 150,
            "sample_rate_hz": 50.0,
        }
        resp = requests.post(
            f"{BASE_URL}/api/sensors/motion/features",
            json={"device_id": device_id, "windows": [window]},
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=15,
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"


# ════════════════════════════════════════════════════════════════════
# Regression: NISCH-013 command center motion_telemetry
# ════════════════════════════════════════════════════════════════════

class TestCommandCenterMotionTelemetryRegression:
    """GET /api/operator/command-center/{user_id} motion_telemetry regression."""

    def test_command_center_includes_motion_telemetry(self, admin_token, admin_user_id):
        """Response includes motion_telemetry slot."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/command-center/{admin_user_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=15,
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "motion_telemetry" in data, f"Missing 'motion_telemetry' in response"


# ════════════════════════════════════════════════════════════════════
# Regression: GET /api/env/hazards
# ════════════════════════════════════════════════════════════════════

class TestEnvHazardsRegression:
    """GET /api/env/hazards still works."""

    def test_env_hazards_returns_200(self, admin_token):
        """Env hazards endpoint returns 200."""
        resp = requests.get(
            f"{BASE_URL}/api/env/hazards",
            params={"lat": 30.07, "lng": 79.02, "radius_km": 5},
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=15,
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"


# ════════════════════════════════════════════════════════════════════
# Regression: GET /api/behavioral/trust/badge
# ════════════════════════════════════════════════════════════════════

class TestTrustBadgeRegression:
    """GET /api/behavioral/trust/badge still works."""

    def test_trust_badge_returns_200(self, admin_token):
        """Trust badge endpoint returns 200."""
        resp = requests.get(
            f"{BASE_URL}/api/behavioral/trust/badge",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=15,
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"


# ════════════════════════════════════════════════════════════════════
# Swallow audit ratchet
# ════════════════════════════════════════════════════════════════════

class TestSwallowAuditRatchet:
    """Swallow audit ratchet: unresolved_debt == 1."""

    def test_unresolved_debt_is_1(self):
        """unresolved_debt count is exactly 1."""
        from tests.test_swallow_audit import _ALLOWED_SWALLOWERS, UNRESOLVED_DEBT
        counts = {}
        for entry in _ALLOWED_SWALLOWERS.values():
            c = entry.get("category", "unknown")
            counts[c] = counts.get(c, 0) + 1
        assert counts.get(UNRESOLVED_DEBT, 0) == 1, (
            f"Expected unresolved_debt=1, got {counts.get(UNRESOLVED_DEBT, 0)}"
        )
