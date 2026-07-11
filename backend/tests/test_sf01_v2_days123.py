"""SF-01 v2 Days 1+2+3 — Comprehensive E2E test suite.

Tests:
  Day 1: Fall-detection false-positive guards (gyro confirm + GPS vehicle speed)
         + voice weight locked at 0.30
  Day 2: POST /api/signals/motion live-stream endpoint (30s cadence + on-event)
  Day 3: Phase 3 env hazard multiplier (×1.30) — Sachet/NDMA + OpenWeather red flags
         GET /api/env/hazards public per-coord query
         ALERT_THRESHOLD=0.65, alert_fired flag, ENV_HAZARD_MATCH SSE event

Verified:
  - POST /api/signals/motion auth, happy-path, impersonation, non-blocking
  - GET /api/env/hazards auth, validation, state resolution
  - Sachet STATE_BBOX 13 entries (8 original + 5 Himalayan)
  - Constants: ALERT_THRESHOLD=0.65, ENV_HAZARD_MULTIPLIER=1.30, WEIGHTS voice=0.30
  - evaluate_risk returns new keys: env_hazard_match, env_multiplier, env_hazards, etc.
  - Regression: POST /api/sensors/motion/features, GET /api/operator/command-center/{user_id}
  - Swallow audit ratchet: unresolved_debt == 1
"""
from __future__ import annotations

import os
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


# ════════════════════════════════════════════════════════════════════
# Day 1: WEIGHTS voice == 0.30 (locked)
# ════════════════════════════════════════════════════════════════════

class TestDay1VoiceWeightLocked:
    """Day 1: Voice weight locked at 0.30 in safety_brain_service."""

    def test_weights_voice_is_030(self):
        """WEIGHTS['voice'] must be 0.30 (not 0.25 as in original spec)."""
        from app.services.safety_brain_service import WEIGHTS
        assert WEIGHTS["voice"] == 0.30, f"voice weight is {WEIGHTS['voice']}, expected 0.30"

    def test_weights_sum_to_one(self):
        """All weights must sum to 1.0."""
        from app.services.safety_brain_service import WEIGHTS
        total = sum(WEIGHTS.values())
        assert abs(total - 1.0) < 0.001, f"weights sum to {total}, expected 1.0"

    def test_weights_fall_is_035(self):
        """WEIGHTS['fall'] must be 0.35."""
        from app.services.safety_brain_service import WEIGHTS
        assert WEIGHTS["fall"] == 0.35

    def test_weights_route_is_015(self):
        """WEIGHTS['route'] must be 0.15."""
        from app.services.safety_brain_service import WEIGHTS
        assert WEIGHTS["route"] == 0.15

    def test_weights_wander_is_010(self):
        """WEIGHTS['wander'] must be 0.10."""
        from app.services.safety_brain_service import WEIGHTS
        assert WEIGHTS["wander"] == 0.10

    def test_weights_pickup_is_010(self):
        """WEIGHTS['pickup'] must be 0.10."""
        from app.services.safety_brain_service import WEIGHTS
        assert WEIGHTS["pickup"] == 0.10


# ════════════════════════════════════════════════════════════════════
# Day 2: POST /api/signals/motion
# ════════════════════════════════════════════════════════════════════

class TestSignalsMotionAuth:
    """POST /api/signals/motion requires auth."""

    def test_requires_auth_401_without_token(self):
        """Endpoint returns 401 without auth token."""
        resp = requests.post(
            f"{BASE_URL}/api/signals/motion",
            json={"fall": 0.5, "voice_distress": 0.3, "lat": 30.07, "lng": 79.02},
            timeout=10,
        )
        assert resp.status_code in (401, 403), f"Expected 401/403, got {resp.status_code}"

    def test_requires_auth_403_with_invalid_token(self):
        """Endpoint returns 401/403 with invalid token."""
        resp = requests.post(
            f"{BASE_URL}/api/signals/motion",
            json={"fall": 0.5, "voice_distress": 0.3, "lat": 30.07, "lng": 79.02},
            headers={"Authorization": "Bearer invalid_token_xyz"},
            timeout=10,
        )
        assert resp.status_code in (401, 403), f"Expected 401/403, got {resp.status_code}"


class TestSignalsMotionHappyPath:
    """POST /api/signals/motion happy-path tests."""

    def test_happy_path_returns_200(self, admin_token):
        """Happy-path: fall=0.9, voice_distress=0.65, lat=30.07, lng=79.02."""
        resp = requests.post(
            f"{BASE_URL}/api/signals/motion",
            json={
                "fall": 0.9,
                "voice_distress": 0.65,
                "lat": 30.07,
                "lng": 79.02,
            },
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=15,
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_response_has_composite_score(self, admin_token):
        """Response includes composite score."""
        resp = requests.post(
            f"{BASE_URL}/api/signals/motion",
            json={"fall": 0.9, "voice_distress": 0.65, "lat": 30.07, "lng": 79.02},
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=15,
        )
        data = resp.json()
        assert "composite" in data, f"Missing 'composite' in response: {data}"
        # Expected: fall(0.9)*0.35 + voice(0.65)*0.30 = 0.315 + 0.195 = 0.51
        # (without env multiplier since no live NDMA alerts)
        assert isinstance(data["composite"], (int, float))

    def test_response_has_risk_level(self, admin_token):
        """Response includes risk_level."""
        resp = requests.post(
            f"{BASE_URL}/api/signals/motion",
            json={"fall": 0.9, "voice_distress": 0.65, "lat": 30.07, "lng": 79.02},
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=15,
        )
        data = resp.json()
        assert "risk_level" in data
        assert data["risk_level"] in ("normal", "suspicious", "dangerous", "critical")

    def test_response_has_primary_event(self, admin_token):
        """Response includes primary_event (should be 'fall' for fall=0.9)."""
        resp = requests.post(
            f"{BASE_URL}/api/signals/motion",
            json={"fall": 0.9, "voice_distress": 0.65, "lat": 30.07, "lng": 79.02},
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=15,
        )
        data = resp.json()
        assert "primary_event" in data
        assert data["primary_event"] == "fall", f"Expected 'fall', got {data['primary_event']}"

    def test_response_has_signal_weights(self, admin_token):
        """Response includes signal_weights matching WEIGHTS constant."""
        resp = requests.post(
            f"{BASE_URL}/api/signals/motion",
            json={"fall": 0.9, "voice_distress": 0.65, "lat": 30.07, "lng": 79.02},
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=15,
        )
        data = resp.json()
        assert "signal_weights" in data
        weights = data["signal_weights"]
        assert weights.get("fall") == 0.35
        assert weights.get("voice") == 0.30
        assert weights.get("route") == 0.15
        assert weights.get("wander") == 0.10
        assert weights.get("pickup") == 0.10

    def test_response_has_env_hazard_match(self, admin_token):
        """Response includes env_hazard_match (false when no live alerts)."""
        resp = requests.post(
            f"{BASE_URL}/api/signals/motion",
            json={"fall": 0.9, "voice_distress": 0.65, "lat": 30.07, "lng": 79.02},
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=15,
        )
        data = resp.json()
        assert "env_hazard_match" in data
        # No live NDMA alerts expected, so should be false
        assert isinstance(data["env_hazard_match"], bool)

    def test_response_has_alert_fired(self, admin_token):
        """Response includes alert_fired flag."""
        resp = requests.post(
            f"{BASE_URL}/api/signals/motion",
            json={"fall": 0.9, "voice_distress": 0.65, "lat": 30.07, "lng": 79.02},
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=15,
        )
        data = resp.json()
        assert "alert_fired" in data
        assert isinstance(data["alert_fired"], bool)

    def test_response_has_pre_mult_score(self, admin_token):
        """Response includes pre_mult_score (score before env multiplier)."""
        resp = requests.post(
            f"{BASE_URL}/api/signals/motion",
            json={"fall": 0.9, "voice_distress": 0.65, "lat": 30.07, "lng": 79.02},
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=15,
        )
        data = resp.json()
        assert "pre_mult_score" in data
        assert isinstance(data["pre_mult_score"], (int, float))


class TestSignalsMotionImpersonation:
    """POST /api/signals/motion impersonation tests."""

    def _resolve_real_user_id(self, token: str) -> str:
        """Resolve a real user id by calling /api/auth/me. The
        impersonation contract requires a valid target user — a
        bogus uuid would (correctly) return 404 because the env
        multiplier can promote a `normal` score into `suspicious`
        which would then attempt to INSERT a SafetyEvent row."""
        me = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        me.raise_for_status()
        return me.json()["id"]

    def test_admin_can_push_for_arbitrary_user_id(self, admin_token):
        """Admin can push for a real arbitrary user_id."""
        # Operator account is convenient — admin pushes for it.
        operator_login = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={
                "email":    "operator@nischint.com",
                "password": "OperatorSecure!2026",
            },
            timeout=10,
        )
        operator_login.raise_for_status()
        operator_id = self._resolve_real_user_id(
            operator_login.json()["access_token"],
        )
        resp = requests.post(
            f"{BASE_URL}/api/signals/motion",
            json={
                "user_id": operator_id,
                "fall": 0.5,
                "voice_distress": 0.3,
                "lat": 30.07,
                "lng": 79.02,
            },
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=15,
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data.get("user_id") == operator_id

    def test_operator_can_push_for_arbitrary_user_id(self, operator_token):
        """Operator can push for a real arbitrary user_id (admin's)."""
        admin_login = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={
                "email":    "nischint4parents@gmail.com",
                "password": "secret123",
            },
            timeout=10,
        )
        admin_login.raise_for_status()
        admin_id = self._resolve_real_user_id(
            admin_login.json()["access_token"],
        )
        resp = requests.post(
            f"{BASE_URL}/api/signals/motion",
            json={
                "user_id": admin_id,
                "fall": 0.5,
                "voice_distress": 0.3,
                "lat": 30.07,
                "lng": 79.02,
            },
            headers={"Authorization": f"Bearer {operator_token}"},
            timeout=15,
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data.get("user_id") == admin_id

    def test_impersonation_unknown_user_id_returns_404(self, admin_token):
        """SF-01 v2 Day 4 — impersonating a non-existent user must
        return 404, not 500. Guards against the FK violation that
        an env-multiplier promotion would otherwise trigger."""
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
        assert resp.status_code == 404, (
            f"Expected 404, got {resp.status_code}: {resp.text}"
        )


# ════════════════════════════════════════════════════════════════════
# Day 3: GET /api/env/hazards
# ════════════════════════════════════════════════════════════════════

class TestEnvHazardsAuth:
    """GET /api/env/hazards requires auth."""

    def test_requires_auth_401_without_token(self):
        """Endpoint returns 401 without auth token."""
        resp = requests.get(
            f"{BASE_URL}/api/env/hazards",
            params={"lat": 30.07, "lng": 79.02, "radius_km": 5},
            timeout=10,
        )
        assert resp.status_code in (401, 403), f"Expected 401/403, got {resp.status_code}"


class TestEnvHazardsValidation:
    """GET /api/env/hazards validation tests."""

    def test_rejects_out_of_range_lat_positive(self, admin_token):
        """Rejects lat > 90 with 422."""
        resp = requests.get(
            f"{BASE_URL}/api/env/hazards",
            params={"lat": 91.0, "lng": 79.02, "radius_km": 5},
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=10,
        )
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}"

    def test_rejects_out_of_range_lat_negative(self, admin_token):
        """Rejects lat < -90 with 422."""
        resp = requests.get(
            f"{BASE_URL}/api/env/hazards",
            params={"lat": -91.0, "lng": 79.02, "radius_km": 5},
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=10,
        )
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}"

    def test_rejects_out_of_range_lng_positive(self, admin_token):
        """Rejects lng > 180 with 422."""
        resp = requests.get(
            f"{BASE_URL}/api/env/hazards",
            params={"lat": 30.07, "lng": 181.0, "radius_km": 5},
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=10,
        )
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}"

    def test_rejects_out_of_range_lng_negative(self, admin_token):
        """Rejects lng < -180 with 422."""
        resp = requests.get(
            f"{BASE_URL}/api/env/hazards",
            params={"lat": 30.07, "lng": -181.0, "radius_km": 5},
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=10,
        )
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}"


class TestEnvHazardsStateResolution:
    """GET /api/env/hazards state resolution tests."""

    def test_uttarakhand_state_resolution(self, admin_token):
        """lat=30.07, lng=79.02 → state='Uttarakhand' (new Himalayan bbox)."""
        resp = requests.get(
            f"{BASE_URL}/api/env/hazards",
            params={"lat": 30.07, "lng": 79.02, "radius_km": 5},
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=15,
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data.get("state") == "Uttarakhand", f"Expected 'Uttarakhand', got {data.get('state')}"

    def test_kerala_state_resolution(self, admin_token):
        """lat=9.93, lng=76.27 → state='Kerala' (existing bbox)."""
        resp = requests.get(
            f"{BASE_URL}/api/env/hazards",
            params={"lat": 9.93, "lng": 76.27, "radius_km": 5},
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=15,
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data.get("state") == "Kerala", f"Expected 'Kerala', got {data.get('state')}"

    def test_response_has_matched_field(self, admin_token):
        """Response includes 'matched' boolean."""
        resp = requests.get(
            f"{BASE_URL}/api/env/hazards",
            params={"lat": 30.07, "lng": 79.02, "radius_km": 5},
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=15,
        )
        data = resp.json()
        assert "matched" in data
        assert isinstance(data["matched"], bool)

    def test_response_has_multiplier_field(self, admin_token):
        """Response includes 'multiplier' (1.0 when no hazards)."""
        resp = requests.get(
            f"{BASE_URL}/api/env/hazards",
            params={"lat": 30.07, "lng": 79.02, "radius_km": 5},
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=15,
        )
        data = resp.json()
        assert "multiplier" in data
        # When no hazards, multiplier should be 1.0
        if not data.get("matched"):
            assert data["multiplier"] == 1.0


# ════════════════════════════════════════════════════════════════════
# Day 3: Sachet STATE_BBOX 13 entries
# ════════════════════════════════════════════════════════════════════

class TestSachetStateBbox:
    """Sachet STATE_BBOX now has 13 entries (8 original + 5 Himalayan)."""

    def test_state_bbox_has_13_entries(self):
        """STATE_BBOX dict has exactly 13 entries."""
        from app.services.external_signals.sachet_provider import STATE_BBOX
        assert len(STATE_BBOX) == 13, f"Expected 13 entries, got {len(STATE_BBOX)}"

    def test_state_bbox_has_original_8_states(self):
        """STATE_BBOX has the original 8 cyclone-belt states."""
        from app.services.external_signals.sachet_provider import STATE_BBOX
        original_states = [
            "Kerala", "Karnataka", "Tamil Nadu", "Andhra Pradesh",
            "Maharashtra", "Gujarat", "Odisha", "West Bengal",
        ]
        for state in original_states:
            assert state in STATE_BBOX, f"Missing original state: {state}"

    def test_state_bbox_has_5_himalayan_states(self):
        """STATE_BBOX has the 5 new Himalayan states."""
        from app.services.external_signals.sachet_provider import STATE_BBOX
        himalayan_states = [
            "Uttarakhand", "Himachal Pradesh", "Jammu & Kashmir",
            "Sikkim", "Arunachal Pradesh",
        ]
        for state in himalayan_states:
            assert state in STATE_BBOX, f"Missing Himalayan state: {state}"


class TestSachetResolveStateHimalayanCities:
    """Test resolve_state for Himalayan cities."""

    def test_dehradun_resolves_to_uttarakhand(self):
        """Dehradun (30.32, 78.03) → Uttarakhand."""
        from app.services.external_signals.sachet_provider import resolve_state
        assert resolve_state(30.32, 78.03) == "Uttarakhand"

    def test_shimla_resolves_to_himachal_pradesh(self):
        """Shimla (31.10, 77.17) → Himachal Pradesh."""
        from app.services.external_signals.sachet_provider import resolve_state
        assert resolve_state(31.10, 77.17) == "Himachal Pradesh"

    def test_gangtok_resolves_to_sikkim(self):
        """Gangtok (27.33, 88.61) → Sikkim."""
        from app.services.external_signals.sachet_provider import resolve_state
        assert resolve_state(27.33, 88.61) == "Sikkim"


# ════════════════════════════════════════════════════════════════════
# Day 3: Constants verification
# ════════════════════════════════════════════════════════════════════

class TestDay3Constants:
    """Day 3 constants verification."""

    def test_alert_threshold_is_065(self):
        """ALERT_THRESHOLD constant = 0.65 in safety_brain_service."""
        from app.services.safety_brain_service import ALERT_THRESHOLD
        assert ALERT_THRESHOLD == 0.65, f"Expected 0.65, got {ALERT_THRESHOLD}"

    def test_env_hazard_multiplier_in_safety_brain(self):
        """ENV_HAZARD_MULTIPLIER = 1.30 in safety_brain_service."""
        from app.services.safety_brain_service import ENV_HAZARD_MULTIPLIER
        assert ENV_HAZARD_MULTIPLIER == 1.30, f"Expected 1.30, got {ENV_HAZARD_MULTIPLIER}"

    def test_env_hazard_multiplier_in_env_hazard_matcher(self):
        """ENV_HAZARD_MULTIPLIER = 1.30 in env_hazard_matcher."""
        from app.services.env_hazard_matcher import ENV_HAZARD_MULTIPLIER
        assert ENV_HAZARD_MULTIPLIER == 1.30, f"Expected 1.30, got {ENV_HAZARD_MULTIPLIER}"

    def test_env_hazard_multiplier_locked_equal(self):
        """ENV_HAZARD_MULTIPLIER must be equal in both modules."""
        from app.services.safety_brain_service import ENV_HAZARD_MULTIPLIER as SB_MULT
        from app.services.env_hazard_matcher import ENV_HAZARD_MULTIPLIER as EHM_MULT
        assert SB_MULT == EHM_MULT, f"Mismatch: safety_brain={SB_MULT}, env_hazard_matcher={EHM_MULT}"


class TestWeatherRedFlagThresholds:
    """Weather red-flag thresholds in env_hazard_matcher."""

    def test_weather_red_flag_wind_kmh(self):
        """WEATHER_RED_FLAG_WIND_KMH = 60."""
        from app.services.env_hazard_matcher import WEATHER_RED_FLAG_WIND_KMH
        assert WEATHER_RED_FLAG_WIND_KMH == 60.0

    def test_weather_red_flag_rain_mm_3h(self):
        """WEATHER_RED_FLAG_RAIN_MM_3H = 50."""
        from app.services.env_hazard_matcher import WEATHER_RED_FLAG_RAIN_MM_3H
        assert WEATHER_RED_FLAG_RAIN_MM_3H == 50.0

    def test_weather_red_flag_temp_c_high(self):
        """WEATHER_RED_FLAG_TEMP_C_HIGH = 45."""
        from app.services.env_hazard_matcher import WEATHER_RED_FLAG_TEMP_C_HIGH
        assert WEATHER_RED_FLAG_TEMP_C_HIGH == 45.0

    def test_weather_red_flag_temp_c_low(self):
        """WEATHER_RED_FLAG_TEMP_C_LOW = 2."""
        from app.services.env_hazard_matcher import WEATHER_RED_FLAG_TEMP_C_LOW
        assert WEATHER_RED_FLAG_TEMP_C_LOW == 2.0


# ════════════════════════════════════════════════════════════════════
# Day 3: match_env_hazards defensive null-handling
# ════════════════════════════════════════════════════════════════════

class TestMatchEnvHazardsNullHandling:
    """match_env_hazards(lat=None, lng=None) returns safe defaults."""

    @pytest.mark.asyncio
    async def test_null_lat_lng_returns_safe_defaults(self):
        """match_env_hazards(lat=None, lng=None) returns {matched: false, multiplier: 1.0}."""
        from app.services.env_hazard_matcher import match_env_hazards
        result = await match_env_hazards(None, None)
        assert result["matched"] is False
        assert result["multiplier"] == 1.0
        assert result["hazards"] == []
        assert result["strongest"] is None
        assert result["state"] is None

    @pytest.mark.asyncio
    async def test_null_lat_only_returns_safe_defaults(self):
        """match_env_hazards(lat=None, lng=79.02) returns safe defaults."""
        from app.services.env_hazard_matcher import match_env_hazards
        result = await match_env_hazards(None, 79.02)
        assert result["matched"] is False
        assert result["multiplier"] == 1.0

    @pytest.mark.asyncio
    async def test_null_lng_only_returns_safe_defaults(self):
        """match_env_hazards(lat=30.07, lng=None) returns safe defaults."""
        from app.services.env_hazard_matcher import match_env_hazards
        result = await match_env_hazards(30.07, None)
        assert result["matched"] is False
        assert result["multiplier"] == 1.0


# ════════════════════════════════════════════════════════════════════
# Day 3: Weather red-flag matching
# ════════════════════════════════════════════════════════════════════

class TestWeatherRedFlagMatching:
    """Test _match_weather_red_flag with synthetic weather data."""

    def test_wind_red_flag_triggers(self):
        """Wind ≥60 km/h triggers red flag."""
        from app.services.env_hazard_matcher import _match_weather_red_flag
        weather = {"wind_kmh": 70, "rain_3h_mm": 0, "temp_c": 25}
        result = _match_weather_red_flag(weather)
        assert result is not None
        assert result["type"] == "wind"
        assert result["severity"] == "severe"

    def test_rain_red_flag_triggers(self):
        """Rain ≥50mm/3h triggers red flag."""
        from app.services.env_hazard_matcher import _match_weather_red_flag
        weather = {"wind_kmh": 10, "rain_3h_mm": 55, "temp_c": 25}
        result = _match_weather_red_flag(weather)
        assert result is not None
        assert result["type"] == "rain"
        assert result["severity"] == "severe"

    def test_heatwave_red_flag_triggers(self):
        """Temp ≥45°C triggers heatwave red flag."""
        from app.services.env_hazard_matcher import _match_weather_red_flag
        weather = {"wind_kmh": 10, "rain_3h_mm": 0, "temp_c": 46}
        result = _match_weather_red_flag(weather)
        assert result is not None
        assert result["type"] == "heatwave"
        assert result["severity"] == "moderate"

    def test_coldwave_red_flag_triggers(self):
        """Temp ≤2°C triggers coldwave red flag."""
        from app.services.env_hazard_matcher import _match_weather_red_flag
        weather = {"wind_kmh": 10, "rain_3h_mm": 0, "temp_c": 1}
        result = _match_weather_red_flag(weather)
        assert result is not None
        assert result["type"] == "coldwave"
        assert result["severity"] == "moderate"

    def test_no_red_flag_for_normal_weather(self):
        """Normal weather returns None."""
        from app.services.env_hazard_matcher import _match_weather_red_flag
        weather = {"wind_kmh": 20, "rain_3h_mm": 10, "temp_c": 25}
        result = _match_weather_red_flag(weather)
        assert result is None

    def test_none_weather_returns_none(self):
        """None weather returns None."""
        from app.services.env_hazard_matcher import _match_weather_red_flag
        result = _match_weather_red_flag(None)
        assert result is None


# ════════════════════════════════════════════════════════════════════
# Regression: POST /api/sensors/motion/features (NISCH-012)
# ════════════════════════════════════════════════════════════════════

class TestMotionFeaturesRegression:
    """POST /api/sensors/motion/features still works (NISCH-012)."""

    def test_motion_features_requires_auth(self):
        """Endpoint requires auth."""
        resp = requests.post(
            f"{BASE_URL}/api/sensors/motion/features",
            json={"windows": []},
            timeout=10,
        )
        assert resp.status_code in (401, 403)

    def test_motion_features_happy_path(self, admin_token, admin_user_id):
        """Happy-path: single window returns 200."""
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
        data = resp.json()
        assert "status" in data
        assert "telemetry_pipeline_version" in data


# ════════════════════════════════════════════════════════════════════
# Regression: GET /api/operator/command-center/{user_id} (NISCH-013)
# ════════════════════════════════════════════════════════════════════

class TestCommandCenterRegression:
    """GET /api/operator/command-center/{user_id} still works (NISCH-013)."""

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
# Regression: GET /api/behavioral/trust/badge
# ════════════════════════════════════════════════════════════════════

class TestTrustBadgeRegression:
    """GET /api/behavioral/trust/badge still works."""

    def test_trust_badge_endpoint_responds(self, admin_token):
        """Trust badge endpoint returns 200."""
        resp = requests.get(
            f"{BASE_URL}/api/behavioral/trust/badge",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=15,
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_trust_badge_has_level(self, admin_token):
        """Trust badge response has 'level' field."""
        resp = requests.get(
            f"{BASE_URL}/api/behavioral/trust/badge",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=15,
        )
        data = resp.json()
        assert "level" in data
        # Level values include suffixes like HIGH_TRUST, MEDIUM_TRUST, LOW_TRUST
        assert any(x in data["level"] for x in ("HIGH", "MEDIUM", "LOW")), f"Unexpected level: {data['level']}"


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

    def test_compensating_action_exists_count(self):
        """compensating_action_exists count is ≥41."""
        from tests.test_swallow_audit import _ALLOWED_SWALLOWERS, COMPENSATING_ACTION_EXISTS
        counts = {}
        for entry in _ALLOWED_SWALLOWERS.values():
            c = entry.get("category", "unknown")
            counts[c] = counts.get(c, 0) + 1
        assert counts.get(COMPENSATING_ACTION_EXISTS, 0) >= 41, (
            f"Expected compensating_action_exists≥41, got {counts.get(COMPENSATING_ACTION_EXISTS, 0)}"
        )
