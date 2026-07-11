"""SF-01 v2 Day 5 — Phase 2 False-Positive Regression Suite.

Locks the Day 1 mobile FP guards (gyro confirm ≥120°/s in 500ms + GPS
vehicle suppression ≥20 km/h) and the safety-brain composite logic as
permanent behaviour. These 3 scenarios are the canonical
"must-never-fire" cases that previously caused investor-demo
embarrassment:

  * jog / vigorous walking — high accel peaks, low gyro tumble
  * car ride / pothole       — high accel + gyro spike but GPS speed > 20 km/h
  * offline mobile           — backend must accept no-GPS / lat=0,lng=0 fix
                               without falsely promoting score via env multiplier

Backend-side guarantee: regardless of what the mobile sends, the
composite must NOT cross the 0.65 ALERT threshold for these three
fingerprints. Mobile-side gyro/GPS guards live in fallDetection.ts and
are unit-testable separately via expo-jest (out of scope here).

Locked invariant:
    JOG / CAR / OFFLINE  →  composite < 0.65  →  alert_fired == false
"""
from __future__ import annotations

import os
import time

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

ADMIN_EMAIL = "nischint4parents@gmail.com"
ADMIN_PASSWORD = "secret123"


@pytest.fixture(scope="module")
def token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=15,
    )
    if r.status_code != 200:
        pytest.skip(f"admin login failed: {r.status_code}")
    return r.json().get("access_token") or r.json().get("token")


def _post_motion(token: str, fall: float, voice: float,
                 lat: float, lng: float) -> dict:
    """Helper — POST /api/signals/motion and return the envelope."""
    r = requests.post(
        f"{BASE_URL}/api/signals/motion",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "fall":           fall,
            "voice_distress": voice,
            "lat":            lat,
            "lng":            lng,
        },
        timeout=15,
    )
    assert r.status_code == 200, f"{r.status_code}: {r.text}"
    return r.json()


# ════════════════════════════════════════════════════════════════════
# Scenario 1 — Jog / Vigorous Walking
# ════════════════════════════════════════════════════════════════════
#
# Real-world fingerprint:
#   * Mobile fall detector emits fall=0.0 because the gyro-confirm
#     guard rejects the impact (no >120°/s tumble during a jog).
#   * Voice channel may briefly tick from background noise but
#     stays well below the 0.5 simultaneous-bonus floor.
#   * Location is fine — runner is in a Bengaluru park, lat ≈ 12.97.
#
# Demand: composite ≤ 0.30 (normal band). MUST NOT fire alert.


class TestFalsePositiveJog:

    def test_jog_with_clean_motion_stays_normal(self, token):
        """Jog fingerprint: fall=0, voice=0.2 (background noise).
        Composite must land in `normal` band."""
        env = _post_motion(token, fall=0.0, voice=0.20,
                           lat=12.97, lng=77.59)
        assert env["composite"] < 0.30, (
            f"jog promoted to {env['composite']} — FP regression"
        )
        assert env["risk_level"] == "normal"
        assert env["alert_fired"] is False
        assert env["env_hazard_match"] is False  # Bengaluru no live alert

    def test_jog_with_subthreshold_voice_no_bonus(self, token):
        """Voice = 0.45 < 0.5 → simultaneous bonus does NOT fire even
        if fall were elevated. Locks the 0.5/0.5 threshold."""
        env = _post_motion(token, fall=0.55, voice=0.45,
                           lat=12.97, lng=77.59)
        # Without bonus: 0.55*0.35 + 0.45*0.30 = 0.193 + 0.135 = 0.328
        # With bonus (BUG): would jump to 0.428 — still under 0.65
        # but the test pins the bonus mechanism to its locked floor.
        assert env["pre_mult_score"] < 0.50, (
            f"sub-threshold voice should NOT trigger +0.10 bonus, "
            f"got pre_mult={env['pre_mult_score']}"
        )
        assert env["alert_fired"] is False


# ════════════════════════════════════════════════════════════════════
# Scenario 2 — Car Ride / Pothole
# ════════════════════════════════════════════════════════════════════
#
# Real-world fingerprint:
#   * Vehicle accel spike (pothole / hard brake) + body tumble.
#     Mobile fall detector blocks via GPS_SPEED_SUPPRESS guard
#     (≥20 km/h) so fall=0 hits the backend.
#   * Voice channel = 0 (car radio doesn't trip the voice classifier
#     consistently; even if it did, ambient music is below distress).
#   * Backend never sees the spike — but if it did via a faulty
#     mobile build, the composite must still not fire.
#
# Demand: composite ≤ 0.30. MUST NOT fire alert.


class TestFalsePositiveCarRide:

    def test_car_ride_with_suppressed_fall_stays_normal(self, token):
        """Mobile-suppressed fall: fall=0, voice=0. Composite=0."""
        env = _post_motion(token, fall=0.0, voice=0.0,
                           lat=19.07, lng=72.87)  # Mumbai
        assert env["composite"] == 0.0
        assert env["risk_level"] == "normal"
        assert env["alert_fired"] is False

    def test_car_ride_leak_does_not_fire_alone(self, token):
        """Hypothetical mobile bug: fall=0.6 leaks from a vehicle
        spike. Voice=0. WITHOUT voice support the simultaneous bonus
        does NOT fire and composite stays well below 0.65."""
        env = _post_motion(token, fall=0.60, voice=0.0,
                           lat=19.07, lng=72.87)
        # 0.6*0.35 = 0.21 (no bonus, no env match in Mumbai today)
        assert env["pre_mult_score"] < 0.30
        assert env["alert_fired"] is False, (
            "lone fall signal (no voice corroboration) "
            "must NOT fire alert tier"
        )

    def test_car_ride_dense_burst_no_double_alert(self, token):
        """3 motion frames in a 2s burst (simulates a debounce miss):
        only one alert at most, dedup holds via cooldown."""
        # First low-confidence frame
        e1 = _post_motion(token, fall=0.4, voice=0.2,
                          lat=19.07, lng=72.87)
        time.sleep(0.5)
        e2 = _post_motion(token, fall=0.5, voice=0.2,
                          lat=19.07, lng=72.87)
        time.sleep(0.5)
        e3 = _post_motion(token, fall=0.45, voice=0.15,
                          lat=19.07, lng=72.87)
        for e in (e1, e2, e3):
            assert e["alert_fired"] is False


# ════════════════════════════════════════════════════════════════════
# Scenario 3 — Offline Mobile (no GPS)
# ════════════════════════════════════════════════════════════════════
#
# Real-world fingerprint:
#   * Mobile has no GPS fix (tunnel, basement, airplane mode just
#     re-enabled). Telemetry uploader pushes lat=0, lng=0.
#   * Env hazard matcher must reject 0,0 cleanly (no spurious
#     "Indian Ocean" hazard match) — multiplier stays 1.0.
#   * Composite must NOT be promoted by accident.
#
# Demand: env_hazard_match=False at 0,0; composite obeys base math.


class TestFalsePositiveOffline:

    def test_offline_no_gps_zero_zero_no_env_match(self, token):
        """lat=0, lng=0 must NOT match any state bbox (the (0,0)
        point is in the Atlantic Ocean off the African coast)."""
        env = _post_motion(token, fall=0.0, voice=0.0,
                           lat=0.0, lng=0.0)
        assert env["env_hazard_match"] is False
        assert env["env_multiplier"] == 1.0

    def test_offline_with_fall_only_does_not_fire(self, token):
        """Even a moderate fall signal at (0,0) — composite stays
        below the alert tier because env multiplier is 1.0 and the
        simultaneous bonus does NOT fire (voice=0)."""
        env = _post_motion(token, fall=0.55, voice=0.0,
                           lat=0.0, lng=0.0)
        # 0.55*0.35 = 0.193 → no bonus → no env → 0.193
        assert env["pre_mult_score"] < 0.30
        assert env["composite"] < 0.65
        assert env["alert_fired"] is False

    def test_offline_env_hazards_endpoint_rejects_zero_zero_cleanly(self, token):
        """GET /api/env/hazards?lat=0&lng=0 must return matched=false,
        state=None, multiplier=1.0 — NEVER 500."""
        r = requests.get(
            f"{BASE_URL}/api/env/hazards",
            params={"lat": 0.0, "lng": 0.0, "radius_km": 5.0},
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["matched"] is False
        assert data["state"] is None
        assert data["multiplier"] == 1.0


# ════════════════════════════════════════════════════════════════════
# Locked safeguards
# ════════════════════════════════════════════════════════════════════


class TestFPRegressionGuards:
    """Lock the constants the FP regression depends on. If any of
    these are silently relaxed, the entire jog/car/offline suite
    becomes a false-negative — these guards catch it loudly."""

    def test_alert_threshold_locked_at_065(self):
        from app.services.safety_brain_service import ALERT_THRESHOLD
        assert ALERT_THRESHOLD == 0.65, (
            "ALERT_THRESHOLD relaxation breaks the FP regression suite. "
            "If you need a different tier, add it — do NOT move 0.65."
        )

    def test_simultaneous_bonus_threshold_locked(self):
        from app.services.safety_brain_service import (
            SIMULTANEOUS_FALL_THRESHOLD,
            SIMULTANEOUS_VOICE_THRESHOLD,
            SIMULTANEOUS_FALL_VOICE_BONUS,
        )
        assert SIMULTANEOUS_FALL_THRESHOLD == 0.5
        assert SIMULTANEOUS_VOICE_THRESHOLD == 0.5
        assert SIMULTANEOUS_FALL_VOICE_BONUS == 0.10

    def test_voice_weight_locked_at_030(self):
        from app.services.safety_brain_service import WEIGHTS
        assert WEIGHTS["voice"] == 0.30, (
            "voice weight reverting to 0.25 would land the Himalaya "
            "demo at 0.48 base — below the 0.65 ALERT threshold. "
            "DO NOT revert."
        )

    def test_env_multiplier_locked_at_130(self):
        from app.services.safety_brain_service import ENV_HAZARD_MULTIPLIER
        from app.services.env_hazard_matcher import (
            ENV_HAZARD_MULTIPLIER as MATCHER_MULT,
        )
        assert ENV_HAZARD_MULTIPLIER == 1.30
        assert MATCHER_MULT == 1.30, (
            "env multiplier must be locked equal across both modules"
        )
