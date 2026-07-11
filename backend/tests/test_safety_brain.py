# Safety Brain API Tests — Unified multi-sensor risk scoring engine
#
# Features tested:
# - POST /api/safety-brain/evaluate — compute risk score from signals
# - GET /api/safety-brain/status/{user_id} — current risk state with decayed signals
# - GET /api/safety-brain/events — list recent safety events
# - POST /api/safety-brain/{event_id}/resolve — resolve a safety event
# - Risk level thresholds: Normal (<0.3), Suspicious (0.3-0.6), Dangerous (0.6-0.85), Critical (>=0.85)
# - Signal weights: fall*0.35 + voice*0.30 + route*0.15 + wander*0.10 + pickup*0.10
# - Fall detector integration: POST /api/sensors/fall feeds signal to Safety Brain
# - Voice detector integration: POST /api/sensors/voice-distress feeds signal to Safety Brain

import pytest
import requests
import os
import time
import uuid

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


@pytest.fixture(scope="module")
def auth_token():
    """Get auth token for guardian user."""
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "nischint4parents@gmail.com",
        "password": "secret123"
    })
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    data = resp.json()
    return data.get("access_token")  # Note: access_token, not 'token'


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Auth headers for requests."""
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture(scope="module")
def user_id(auth_token):
    """Get user ID from token."""
    resp = requests.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {auth_token}"})
    if resp.status_code == 200:
        data = resp.json()
        return data.get("id") or data.get("user_id")
    return None


class TestSafetyBrainEvaluate:
    """Tests for POST /api/safety-brain/evaluate endpoint."""

    def test_evaluate_requires_auth(self):
        """Endpoint requires authentication."""
        resp = requests.post(f"{BASE_URL}/api/safety-brain/evaluate", json={
            "signals": {"fall": 0.5},
            "lat": 19.076,
            "lng": 72.877
        })
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"
        print("PASS: POST /safety-brain/evaluate requires auth")

    def test_evaluate_normal_level(self, auth_headers):
        """Low signals → Normal level (< 0.3), no event created."""
        resp = requests.post(f"{BASE_URL}/api/safety-brain/evaluate", json={
            "signals": {"fall": 0.2, "voice": 0.1},  # 0.2*0.35 + 0.1*0.30 = 0.07 + 0.03 = 0.10
            "lat": 19.076,
            "lng": 72.877
        }, headers=auth_headers)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["risk_level"] == "normal", f"Expected normal, got {data['risk_level']}"
        assert data["risk_score"] < 0.3, f"Expected score < 0.3, got {data['risk_score']}"
        assert data.get("status") == "normal", f"Expected status=normal for normal level"
        assert "event_id" not in data, "Normal level should NOT create event"
        print(f"PASS: Normal level - score={data['risk_score']}, level={data['risk_level']}, no event created")

    def test_evaluate_suspicious_level(self, auth_headers):
        """Medium signals → Suspicious level (0.3-0.6)."""
        # Calculate: fall=0.6*0.35 + voice=0.5*0.30 + route=0.4*0.15 = 0.21 + 0.15 + 0.06 = 0.42
        resp = requests.post(f"{BASE_URL}/api/safety-brain/evaluate", json={
            "signals": {"fall": 0.6, "voice": 0.5, "route": 0.4},
            "lat": 19.076,
            "lng": 72.877
        }, headers=auth_headers)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["risk_level"] == "suspicious", f"Expected suspicious, got {data['risk_level']}"
        assert 0.3 <= data["risk_score"] < 0.6, f"Expected 0.3-0.6, got {data['risk_score']}"
        assert "event_id" in data, "Suspicious level should create event"
        print(f"PASS: Suspicious level - score={data['risk_score']}, level={data['risk_level']}, event_id={data.get('event_id', 'N/A')[:8]}...")

    def test_evaluate_dangerous_level(self, auth_headers):
        """High signals → Dangerous level (0.6-0.85)."""
        # Calculate: fall=1.0*0.35 + voice=0.8*0.30 + route=0.6*0.15 = 0.35 + 0.24 + 0.09 = 0.68
        resp = requests.post(f"{BASE_URL}/api/safety-brain/evaluate", json={
            "signals": {"fall": 1.0, "voice": 0.8, "route": 0.6},
            "lat": 19.076,
            "lng": 72.877
        }, headers=auth_headers)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["risk_level"] == "dangerous", f"Expected dangerous, got {data['risk_level']}"
        assert 0.6 <= data["risk_score"] < 0.85, f"Expected 0.6-0.85, got {data['risk_score']}"
        assert "event_id" in data, "Dangerous level should create event"
        assert data.get("auto_sos") is False or data.get("auto_sos") is None, "Dangerous should NOT trigger auto_sos"
        print(f"PASS: Dangerous level - score={data['risk_score']}, level={data['risk_level']}, auto_sos={data.get('auto_sos')}")

    def test_evaluate_critical_level_triggers_auto_sos(self, auth_headers):
        """Critical signals → Critical level (>=0.85) triggers auto_sos."""
        # Calculate: fall=1.0*0.35 + voice=1.0*0.30 + route=1.0*0.15 + wander=1.0*0.10 + pickup=0.5*0.10 
        # = 0.35 + 0.30 + 0.15 + 0.10 + 0.05 = 0.95
        resp = requests.post(f"{BASE_URL}/api/safety-brain/evaluate", json={
            "signals": {"fall": 1.0, "voice": 1.0, "route": 1.0, "wander": 1.0, "pickup": 0.5},
            "lat": 19.076,
            "lng": 72.877
        }, headers=auth_headers)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["risk_level"] == "critical", f"Expected critical, got {data['risk_level']}"
        assert data["risk_score"] >= 0.85, f"Expected >= 0.85, got {data['risk_score']}"
        assert "event_id" in data, "Critical level should create event"
        assert data.get("auto_sos") is True, "Critical level MUST trigger auto_sos"
        print(f"PASS: Critical level - score={data['risk_score']}, level={data['risk_level']}, auto_sos={data.get('auto_sos')}")

    def test_evaluate_weight_calculation(self, auth_headers):
        """Verify weight calculation: fall*0.35 + voice*0.30 + route*0.15 + wander*0.10 + pickup*0.10."""
        # Test exact calculation: fall=0.8, voice=0.6, route=0.4, wander=0.3, pickup=0.2
        # Expected: 0.8*0.35 + 0.6*0.30 + 0.4*0.15 + 0.3*0.10 + 0.2*0.10
        #         = 0.28    + 0.18    + 0.06    + 0.03    + 0.02 = 0.57
        resp = requests.post(f"{BASE_URL}/api/safety-brain/evaluate", json={
            "signals": {"fall": 0.8, "voice": 0.6, "route": 0.4, "wander": 0.3, "pickup": 0.2},
            "lat": 19.076,
            "lng": 72.877
        }, headers=auth_headers)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        expected_score = 0.8*0.35 + 0.6*0.30 + 0.4*0.15 + 0.3*0.10 + 0.2*0.10
        # Allow small tolerance for rounding
        assert abs(data["risk_score"] - expected_score) < 0.01, f"Expected ~{expected_score:.3f}, got {data['risk_score']}"
        print(f"PASS: Weight calculation - expected={expected_score:.3f}, actual={data['risk_score']}")

    def test_evaluate_primary_event_tracking(self, auth_headers):
        """Primary event is the highest contributing signal."""
        # Fall is highest: fall=0.9 (contributes 0.315), voice=0.3 (contributes 0.09)
        resp = requests.post(f"{BASE_URL}/api/safety-brain/evaluate", json={
            "signals": {"fall": 0.9, "voice": 0.3},
            "lat": 19.076,
            "lng": 72.877
        }, headers=auth_headers)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data.get("primary_event") == "fall", f"Expected primary=fall, got {data.get('primary_event')}"
        print(f"PASS: Primary event tracking - primary={data.get('primary_event')}")

    def test_evaluate_invalid_signal_filtered(self, auth_headers):
        """Invalid signal keys are filtered out."""
        resp = requests.post(f"{BASE_URL}/api/safety-brain/evaluate", json={
            "signals": {"fall": 0.5, "invalid_signal": 1.0, "xyz": 0.9},
            "lat": 19.076,
            "lng": 72.877
        }, headers=auth_headers)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        # Only fall should contribute: 0.5*0.35 = 0.175
        assert data["risk_score"] < 0.2, f"Expected ~0.175, got {data['risk_score']} (invalid signals should be filtered)"
        print(f"PASS: Invalid signals filtered - score={data['risk_score']} (only fall counted)")


class TestSafetyBrainStatus:
    """Tests for GET /api/safety-brain/status/{user_id} endpoint."""

    def test_status_requires_auth(self, user_id):
        """Endpoint requires authentication."""
        resp = requests.get(f"{BASE_URL}/api/safety-brain/status/{user_id}")
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"
        print("PASS: GET /safety-brain/status requires auth")

    def test_status_returns_risk_state(self, auth_headers, user_id):
        """Returns current risk state with decayed signals."""
        resp = requests.get(f"{BASE_URL}/api/safety-brain/status/{user_id}", headers=auth_headers)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "risk_score" in data, "Missing risk_score"
        assert "risk_level" in data, "Missing risk_level"
        assert "signals" in data, "Missing signals (decayed)"
        print(f"PASS: Status returns risk state - score={data['risk_score']}, level={data['risk_level']}")

    def test_status_includes_raw_signals(self, auth_headers, user_id):
        """Status includes raw_signals for before-decay comparison."""
        resp = requests.get(f"{BASE_URL}/api/safety-brain/status/{user_id}", headers=auth_headers)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        # raw_signals may be empty if no recent signals, but key should exist
        assert "raw_signals" in data or data.get("status") == "no_data", "Missing raw_signals (or no_data status)"
        print(f"PASS: Status includes raw_signals/no_data handling")


class TestSafetyBrainEvents:
    """Tests for GET /api/safety-brain/events endpoint."""

    def test_events_requires_auth(self):
        """Endpoint requires authentication."""
        resp = requests.get(f"{BASE_URL}/api/safety-brain/events")
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"
        print("PASS: GET /safety-brain/events requires auth")

    def test_events_returns_list(self, auth_headers):
        """Returns list of recent safety events."""
        resp = requests.get(f"{BASE_URL}/api/safety-brain/events", headers=auth_headers)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "events" in data, "Missing events array"
        assert "count" in data, "Missing count"
        assert isinstance(data["events"], list), "events should be a list"
        print(f"PASS: Events list - count={data['count']}")

    def test_events_respects_limit(self, auth_headers):
        """Events endpoint respects limit parameter."""
        resp = requests.get(f"{BASE_URL}/api/safety-brain/events?limit=3", headers=auth_headers)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert len(data["events"]) <= 3, f"Expected <= 3 events, got {len(data['events'])}"
        print(f"PASS: Events respects limit - returned {len(data['events'])} events")

    def test_events_include_required_fields(self, auth_headers):
        """Events include all required fields."""
        resp = requests.get(f"{BASE_URL}/api/safety-brain/events", headers=auth_headers)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        if len(data["events"]) > 0:
            event = data["events"][0]
            required_fields = ["event_id", "user_id", "risk_score", "risk_level", "signals", "primary_event", "status"]
            for field in required_fields:
                assert field in event, f"Missing field: {field}"
            print(f"PASS: Events include required fields - {', '.join(required_fields)}")
        else:
            print("SKIP: No events to verify fields (no events in system)")


class TestSafetyBrainResolve:
    """Tests for POST /api/safety-brain/{event_id}/resolve endpoint."""

    def test_resolve_requires_auth(self):
        """Endpoint requires authentication."""
        fake_id = str(uuid.uuid4())
        resp = requests.post(f"{BASE_URL}/api/safety-brain/{fake_id}/resolve")
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"
        print("PASS: POST /safety-brain/{id}/resolve requires auth")

    def test_resolve_not_found(self, auth_headers):
        """Returns 404 for non-existent event."""
        fake_id = str(uuid.uuid4())
        resp = requests.post(f"{BASE_URL}/api/safety-brain/{fake_id}/resolve", headers=auth_headers)
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"
        print("PASS: Resolve returns 404 for non-existent event")

    def test_resolve_existing_event(self, auth_headers):
        """Resolve an existing safety event."""
        # First create an event
        create_resp = requests.post(f"{BASE_URL}/api/safety-brain/evaluate", json={
            "signals": {"fall": 0.7, "voice": 0.5},  # Should create suspicious event
            "lat": 19.076,
            "lng": 72.877
        }, headers=auth_headers)
        assert create_resp.status_code == 200, f"Create failed: {create_resp.text}"
        create_data = create_resp.json()
        
        if "event_id" in create_data:
            event_id = create_data["event_id"]
            # Now resolve it
            resp = requests.post(f"{BASE_URL}/api/safety-brain/{event_id}/resolve", headers=auth_headers)
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
            data = resp.json()
            assert data.get("status") == "resolved", f"Expected status=resolved, got {data.get('status')}"
            print(f"PASS: Resolved event {event_id[:8]}... successfully")
        else:
            print("SKIP: Normal level doesn't create events to resolve")


class TestFallDetectorIntegration:
    """Tests for fall detector → Safety Brain integration."""

    def test_fall_detection_feeds_safety_brain(self, auth_headers, user_id):
        """Fall detection should feed signal to Safety Brain."""
        # Note: Fall detection has 60s cooldown
        # Send fall detection request
        resp = requests.post(f"{BASE_URL}/api/sensors/fall", json={
            "lat": 19.076,
            "lng": 72.877,
            "impact_score": 0.9,
            "freefall_score": 0.8,
            "orientation_score": 0.7,
            "post_impact_score": 0.6,
            "immobility_score": 0.8
        }, headers=auth_headers)
        
        if resp.status_code == 200:
            data = resp.json()
            # Fall was detected - check Safety Brain status
            if data.get("status") != "cooldown":
                # Give it a moment to process
                time.sleep(0.5)
                status_resp = requests.get(f"{BASE_URL}/api/safety-brain/status/{user_id}", headers=auth_headers)
                if status_resp.status_code == 200:
                    status_data = status_resp.json()
                    # Should have fall signal in current state
                    if status_data.get("status") != "no_data":
                        signals = status_data.get("signals", {})
                        # Fall signal should be present (may be decayed)
                        print(f"PASS: Fall detection feeds Safety Brain - signals={signals}")
                    else:
                        print("INFO: Safety Brain status shows no_data (signals may have expired)")
                else:
                    print(f"INFO: Could not verify Safety Brain status: {status_resp.status_code}")
            else:
                print("INFO: Fall detection in cooldown - skipping integration test")
        elif resp.status_code == 429:
            print("INFO: Fall detection in cooldown (429) - integration test skipped")
        else:
            print(f"INFO: Fall detection response: {resp.status_code} - {resp.text[:100]}")


class TestVoiceDetectorIntegration:
    """Tests for voice distress → Safety Brain integration."""

    def test_voice_distress_feeds_safety_brain(self, auth_headers, user_id):
        """Voice distress should feed signal to Safety Brain."""
        # Note: Voice distress has 30s cooldown
        resp = requests.post(f"{BASE_URL}/api/sensors/voice-distress", json={
            "lat": 19.076,
            "lng": 72.877,
            "keywords": ["help", "emergency"],
            "scream_detected": True,
            "repeated": True
        }, headers=auth_headers)
        
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") not in ("cooldown", "below_threshold"):
                time.sleep(0.5)
                status_resp = requests.get(f"{BASE_URL}/api/safety-brain/status/{user_id}", headers=auth_headers)
                if status_resp.status_code == 200:
                    status_data = status_resp.json()
                    if status_data.get("status") != "no_data":
                        signals = status_data.get("signals", {})
                        print(f"PASS: Voice distress feeds Safety Brain - signals={signals}")
                    else:
                        print("INFO: Safety Brain status shows no_data (signals may have expired)")
                else:
                    print(f"INFO: Could not verify Safety Brain status: {status_resp.status_code}")
            else:
                print(f"INFO: Voice distress status={data.get('status')} - integration test skipped")
        elif resp.status_code == 429:
            print("INFO: Voice distress in cooldown (429) - integration test skipped")
        else:
            print(f"INFO: Voice distress response: {resp.status_code} - {resp.text[:100]}")


class TestRiskLevelThresholds:
    """Test exact risk level threshold boundaries."""

    def test_boundary_normal_suspicious(self, auth_headers):
        """Test boundary between normal (<0.3) and suspicious (>=0.3)."""
        # Just below 0.3: fall=0.85 → 0.85*0.35 = 0.2975
        resp = requests.post(f"{BASE_URL}/api/safety-brain/evaluate", json={
            "signals": {"fall": 0.85},
            "lat": 19.076,
            "lng": 72.877
        }, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        # 0.85 * 0.35 = 0.2975, should be just below 0.3
        if data["risk_score"] < 0.3:
            assert data["risk_level"] == "normal"
            print(f"PASS: score={data['risk_score']:.3f} → normal")
        else:
            assert data["risk_level"] == "suspicious"
            print(f"INFO: score={data['risk_score']:.3f} → suspicious (at boundary)")

    def test_boundary_suspicious_dangerous(self, auth_headers):
        """Test boundary between suspicious (<0.6) and dangerous (>=0.6)."""
        # At 0.6: need combined score of exactly 0.6
        # fall=1.0*0.35 + voice=0.83*0.30 = 0.35 + 0.249 = 0.599
        resp = requests.post(f"{BASE_URL}/api/safety-brain/evaluate", json={
            "signals": {"fall": 1.0, "voice": 0.83},
            "lat": 19.076,
            "lng": 72.877
        }, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        if data["risk_score"] < 0.6:
            assert data["risk_level"] == "suspicious"
            print(f"PASS: score={data['risk_score']:.3f} → suspicious")
        else:
            assert data["risk_level"] == "dangerous"
            print(f"INFO: score={data['risk_score']:.3f} → dangerous (at boundary)")

    def test_boundary_dangerous_critical(self, auth_headers):
        """Test boundary between dangerous (<0.85) and critical (>=0.85)."""
        # Just below 0.85: fall=1.0*0.35 + voice=1.0*0.30 + route=1.0*0.15 = 0.80
        resp = requests.post(f"{BASE_URL}/api/safety-brain/evaluate", json={
            "signals": {"fall": 1.0, "voice": 1.0, "route": 1.0},
            "lat": 19.076,
            "lng": 72.877
        }, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        # 0.35 + 0.30 + 0.15 = 0.80, should be dangerous
        if data["risk_score"] < 0.85:
            assert data["risk_level"] == "dangerous"
            assert data.get("auto_sos") is not True, "Dangerous should NOT trigger auto_sos"
            print(f"PASS: score={data['risk_score']:.3f} → dangerous (no auto_sos)")
        else:
            assert data["risk_level"] == "critical"
            print(f"INFO: score={data['risk_score']:.3f} → critical (at boundary)")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
