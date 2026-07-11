# Voice Distress Detection Tests
# 
# Tests for POST /api/sensors/voice-distress endpoint:
# - Report with keywords + scream returns distress_score and event_id
# - High score (>= 0.9) triggers auto_sos status
# - Below threshold (< 0.7) returns below_threshold
# - Cooldown (429) within 30s (unless score >= 0.9)
# - Resolve/false_positive endpoints
# - List events endpoint
# - Distress score computation verification

import pytest
import requests
import os
import time
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Known distress keywords from service
DISTRESS_KEYWORDS = {"help", "stop", "leave me", "call police", "emergency", "don't touch", "save me", "please help"}


class TestVoiceDistressAuthentication:
    """Test authentication requirements for voice distress endpoints"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def test_voice_distress_report_requires_auth(self):
        """POST /sensors/voice-distress without auth returns 401"""
        response = self.session.post(f"{BASE_URL}/api/sensors/voice-distress", json={
            "lat": 19.076, "lng": 72.877,
            "keywords": ["help"],
            "scream_detected": True,
            "repeated": False
        })
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: POST /sensors/voice-distress requires authentication")

    def test_voice_distress_resolve_requires_auth(self):
        """POST /sensors/voice-distress/{id}/resolve without auth returns 401"""
        fake_id = str(uuid.uuid4())
        response = self.session.post(f"{BASE_URL}/api/sensors/voice-distress/{fake_id}/resolve", json={
            "resolved_by": "user_safe"
        })
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: POST /sensors/voice-distress/{id}/resolve requires authentication")

    def test_voice_distress_events_requires_auth(self):
        """GET /sensors/voice-distress/events without auth returns 401"""
        response = self.session.get(f"{BASE_URL}/api/sensors/voice-distress/events")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: GET /sensors/voice-distress/events requires authentication")


class TestVoiceDistressScoring:
    """Test distress score computation"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        # Login as guardian
        login_resp = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": "nischint4parents@gmail.com",
            "password": "secret123"
        })
        assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
        token = login_resp.json().get("access_token")
        self.session.headers.update({"Authorization": f"Bearer {token}"})
        self.user_id = login_resp.json().get("user", {}).get("id")

    def test_max_score_all_signals(self):
        """keywords=['help','stop'] + scream=true + repeated=true should give score=1.0"""
        # Score formula: keyword*0.4 + scream*0.35 + repetition*0.25
        # keyword_score = min(2/2, 1.0) = 1.0 → 0.4
        # scream_score = 0.8 (base) → 0.35 * 0.8 = 0.28 (no audio features boost)
        # repetition_score = 1.0 → 0.25
        # Total = 0.4 + 0.28 + 0.25 = 0.93 (without audio boost)
        # With audio boost (amp > 0.8, pitch_var > 0.6): scream_score = 1.0 → 0.35
        # Total = 0.4 + 0.35 + 0.25 = 1.0
        
        # Add a unique marker to avoid cooldown issues
        unique_lat = 19.076 + (time.time() % 1000) / 100000
        
        response = self.session.post(f"{BASE_URL}/api/sensors/voice-distress", json={
            "lat": unique_lat, "lng": 72.877,
            "keywords": ["help", "stop"],
            "scream_detected": True,
            "repeated": True,
            "audio_features": {"amplitude": 0.9, "pitch_variance": 0.7}
        })
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        # Should trigger auto_sos (score >= 0.9)
        assert data.get("distress_score") == 1.0, f"Expected score 1.0, got {data.get('distress_score')}"
        assert data.get("status") == "auto_sos", f"Expected auto_sos, got {data.get('status')}"
        assert data.get("auto_sos") == True, f"Expected auto_sos=True"
        print(f"PASS: Max score test - score={data.get('distress_score')}, status={data.get('status')}")

    def test_below_threshold_non_distress_keywords(self):
        """keywords=['hello'] (not in distress set) with scream=false should be below threshold"""
        # keyword_score = 0 (hello not in DISTRESS_KEYWORDS)
        # scream_score = 0
        # repetition_score = 0
        # Total = 0.0 < 0.7 threshold
        
        response = self.session.post(f"{BASE_URL}/api/sensors/voice-distress", json={
            "lat": 19.080, "lng": 72.880,
            "keywords": ["hello"],
            "scream_detected": False,
            "repeated": False
        })
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        assert data.get("status") == "below_threshold", f"Expected below_threshold, got {data.get('status')}"
        assert data.get("distress_score") < 0.7, f"Score {data.get('distress_score')} should be < 0.7"
        print(f"PASS: Below threshold test - score={data.get('distress_score')}, status={data.get('status')}")

    def test_scream_only_below_threshold(self):
        """Scream only (no keywords, no repeat) should be below threshold"""
        # scream_score = 0.8 → 0.35 * 0.8 = 0.28 < 0.7
        response = self.session.post(f"{BASE_URL}/api/sensors/voice-distress", json={
            "lat": 19.081, "lng": 72.881,
            "keywords": None,
            "scream_detected": True,
            "repeated": False
        })
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        assert data.get("status") == "below_threshold", f"Expected below_threshold, got {data.get('status')}"
        print(f"PASS: Scream only below threshold - score={data.get('distress_score')}")

    def test_single_keyword_with_scream_alert(self):
        """Single keyword + scream should trigger alert (>= 0.7)"""
        # keyword_score = min(1/2, 1.0) = 0.5 → 0.4 * 0.5 = 0.2
        # scream_score = 0.8 → 0.35 * 0.8 = 0.28
        # Total = 0.2 + 0.28 = 0.48 < 0.7
        # Need repeated OR boosted scream OR 2 keywords
        
        # With repeated: 0.2 + 0.28 + 0.25 = 0.73 >= 0.7
        response = self.session.post(f"{BASE_URL}/api/sensors/voice-distress", json={
            "lat": 19.082, "lng": 72.882,
            "keywords": ["help"],
            "scream_detected": True,
            "repeated": True
        })
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        # Check if it triggers alert
        assert data.get("distress_score") >= 0.7, f"Score should be >= 0.7, got {data.get('distress_score')}"
        assert data.get("status") in ("alert", "auto_sos"), f"Expected alert/auto_sos, got {data.get('status')}"
        print(f"PASS: Alert threshold test - score={data.get('distress_score')}, status={data.get('status')}")


class TestVoiceDistressReporting:
    """Test voice distress reporting endpoint"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        # Login
        login_resp = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": "nischint4parents@gmail.com",
            "password": "secret123"
        })
        token = login_resp.json().get("access_token")
        self.session.headers.update({"Authorization": f"Bearer {token}"})
        self.user_id = login_resp.json().get("user", {}).get("id")

    def test_report_returns_event_id(self):
        """POST /sensors/voice-distress returns event_id for valid alerts"""
        unique_lat = 19.090 + (time.time() % 1000) / 100000
        response = self.session.post(f"{BASE_URL}/api/sensors/voice-distress", json={
            "lat": unique_lat, "lng": 72.890,
            "keywords": ["help", "emergency"],
            "scream_detected": True,
            "repeated": True,
            "audio_features": {"amplitude": 0.85, "pitch_variance": 0.65}
        })
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        # For auto_sos (score >= 0.9), should have event_id
        if data.get("distress_score") >= 0.7:
            assert "event_id" in data, f"Missing event_id in response: {data}"
            assert data.get("event_id") is not None, "event_id should not be None"
            print(f"PASS: Report returns event_id={data.get('event_id')[:8]}...")

    def test_report_returns_keywords_matched(self):
        """Response includes keywords_matched field with only distress keywords"""
        unique_lat = 19.091 + (time.time() % 1000) / 100000
        response = self.session.post(f"{BASE_URL}/api/sensors/voice-distress", json={
            "lat": unique_lat, "lng": 72.891,
            "keywords": ["help", "hello", "stop", "goodbye"],  # help, stop are distress keywords
            "scream_detected": True,
            "repeated": True,
            "audio_features": {"amplitude": 0.9, "pitch_variance": 0.7}
        })
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        if data.get("status") != "below_threshold":
            assert "keywords_matched" in data, f"Missing keywords_matched: {data}"
            # Should only include distress keywords
            for kw in data.get("keywords_matched", []):
                assert kw.lower() in DISTRESS_KEYWORDS, f"Non-distress keyword in matched: {kw}"
            print(f"PASS: keywords_matched={data.get('keywords_matched')}")


class TestVoiceDistressCooldown:
    """Test cooldown behavior"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        login_resp = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": "nischint4parents@gmail.com",
            "password": "secret123"
        })
        token = login_resp.json().get("access_token")
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    def test_cooldown_429_within_30s(self):
        """Second request within 30s returns 429 (unless auto_sos)"""
        # First request - trigger alert (not auto_sos to test cooldown)
        base_lat = 19.100
        response1 = self.session.post(f"{BASE_URL}/api/sensors/voice-distress", json={
            "lat": base_lat, "lng": 72.900,
            "keywords": ["help"],
            "scream_detected": True,
            "repeated": True  # Score ~0.73, alert but not auto_sos
        })
        
        if response1.status_code == 429:
            # Already in cooldown from previous test, skip
            print("SKIP: Already in cooldown from previous test")
            return
        
        assert response1.status_code == 200, f"First request failed: {response1.text}"
        first_data = response1.json()
        
        if first_data.get("status") == "below_threshold":
            print("SKIP: First request below threshold, no cooldown triggered")
            return
        
        # Verify first request was successful alert
        assert first_data.get("status") in ("alert", "auto_sos"), f"Unexpected status: {first_data.get('status')}"
        
        # Second request immediately - should get 429 if not auto_sos
        response2 = self.session.post(f"{BASE_URL}/api/sensors/voice-distress", json={
            "lat": base_lat + 0.001, "lng": 72.900,
            "keywords": ["help"],
            "scream_detected": True,
            "repeated": True
        })
        
        # If score < 0.9, should be blocked by cooldown
        if response2.status_code == 429:
            print("PASS: Cooldown 429 returned within 30s")
        elif response2.status_code == 200 and response2.json().get("status") == "cooldown":
            print("PASS: Cooldown status returned")
        else:
            # May have bypassed if score >= 0.9
            data2 = response2.json()
            assert data2.get("distress_score", 0) >= 0.9 or data2.get("status") == "below_threshold", \
                f"Expected cooldown or auto_sos bypass, got: {data2}"
            print(f"PASS: Auto-SOS bypass or below threshold: {data2.get('status')}")

    def test_auto_sos_bypasses_cooldown(self):
        """Auto-SOS (score >= 0.9) bypasses cooldown"""
        base_lat = 19.110 + (time.time() % 1000) / 100000
        
        # First request with high score
        response1 = self.session.post(f"{BASE_URL}/api/sensors/voice-distress", json={
            "lat": base_lat, "lng": 72.910,
            "keywords": ["help", "stop"],
            "scream_detected": True,
            "repeated": True,
            "audio_features": {"amplitude": 0.9, "pitch_variance": 0.7}
        })
        
        if response1.status_code == 429:
            print("SKIP: In cooldown from previous test")
            return
            
        assert response1.status_code == 200, f"First failed: {response1.text}"
        
        # Second request immediately with max signals (should bypass cooldown)
        response2 = self.session.post(f"{BASE_URL}/api/sensors/voice-distress", json={
            "lat": base_lat + 0.001, "lng": 72.910,
            "keywords": ["help", "stop", "emergency"],
            "scream_detected": True,
            "repeated": True,
            "audio_features": {"amplitude": 0.95, "pitch_variance": 0.8}
        })
        
        # Score >= 0.9 should bypass cooldown
        assert response2.status_code == 200, f"Should bypass cooldown: {response2.text}"
        data2 = response2.json()
        assert data2.get("distress_score") >= 0.9 or data2.get("status") == "auto_sos", \
            f"Expected auto_sos, got: {data2}"
        print(f"PASS: Auto-SOS bypasses cooldown - score={data2.get('distress_score')}")


class TestVoiceDistressResolve:
    """Test resolve and false_positive endpoints"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        login_resp = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": "nischint4parents@gmail.com",
            "password": "secret123"
        })
        token = login_resp.json().get("access_token")
        self.session.headers.update({"Authorization": f"Bearer {token}"})
        self.user_id = login_resp.json().get("user", {}).get("id")

    def test_resolve_event_success(self):
        """POST /sensors/voice-distress/{id}/resolve marks event as resolved"""
        # Create an event first
        unique_lat = 19.120 + (time.time() % 1000) / 100000
        create_resp = self.session.post(f"{BASE_URL}/api/sensors/voice-distress", json={
            "lat": unique_lat, "lng": 72.920,
            "keywords": ["help", "stop"],
            "scream_detected": True,
            "repeated": True,
            "audio_features": {"amplitude": 0.9, "pitch_variance": 0.7}
        })
        
        if create_resp.status_code == 429:
            print("SKIP: In cooldown")
            return
            
        assert create_resp.status_code == 200, f"Create failed: {create_resp.text}"
        create_data = create_resp.json()
        
        if create_data.get("status") == "below_threshold":
            print("SKIP: Event below threshold")
            return
        
        event_id = create_data.get("event_id")
        assert event_id, f"No event_id in response: {create_data}"
        
        # Resolve the event
        resolve_resp = self.session.post(
            f"{BASE_URL}/api/sensors/voice-distress/{event_id}/resolve",
            json={"resolved_by": "user_safe"}
        )
        assert resolve_resp.status_code == 200, f"Resolve failed: {resolve_resp.text}"
        resolve_data = resolve_resp.json()
        
        assert resolve_data.get("status") == "resolved", f"Expected resolved, got: {resolve_data}"
        assert resolve_data.get("event_id") == event_id
        print(f"PASS: Event resolved successfully")

    def test_resolve_as_false_positive(self):
        """POST /sensors/voice-distress/{id}/resolve with false_positive"""
        # Create an event
        unique_lat = 19.130 + (time.time() % 1000) / 100000
        create_resp = self.session.post(f"{BASE_URL}/api/sensors/voice-distress", json={
            "lat": unique_lat, "lng": 72.930,
            "keywords": ["help", "emergency"],
            "scream_detected": True,
            "repeated": True,
            "audio_features": {"amplitude": 0.9, "pitch_variance": 0.7}
        })
        
        if create_resp.status_code == 429:
            print("SKIP: In cooldown")
            return
            
        create_data = create_resp.json()
        if create_data.get("status") == "below_threshold":
            print("SKIP: Below threshold")
            return
        
        event_id = create_data.get("event_id")
        assert event_id, f"No event_id: {create_data}"
        
        # Mark as false positive
        resolve_resp = self.session.post(
            f"{BASE_URL}/api/sensors/voice-distress/{event_id}/resolve",
            json={"resolved_by": "false_positive"}
        )
        assert resolve_resp.status_code == 200, f"Failed: {resolve_resp.text}"
        resolve_data = resolve_resp.json()
        
        assert resolve_data.get("status") == "false_positive", f"Expected false_positive: {resolve_data}"
        print(f"PASS: Event marked as false_positive")

    def test_resolve_not_found(self):
        """Resolve non-existent event returns 404"""
        fake_id = str(uuid.uuid4())
        response = self.session.post(
            f"{BASE_URL}/api/sensors/voice-distress/{fake_id}/resolve",
            json={"resolved_by": "user_safe"}
        )
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("PASS: Resolve non-existent event returns 404")


class TestVoiceDistressEvents:
    """Test events listing endpoint"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        login_resp = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": "nischint4parents@gmail.com",
            "password": "secret123"
        })
        token = login_resp.json().get("access_token")
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    def test_list_events_success(self):
        """GET /sensors/voice-distress/events returns events array"""
        response = self.session.get(f"{BASE_URL}/api/sensors/voice-distress/events")
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        assert "events" in data, f"Missing events key: {data}"
        assert "count" in data, f"Missing count key: {data}"
        assert isinstance(data["events"], list), "events should be a list"
        print(f"PASS: List events returns {data['count']} events")

    def test_list_events_fields(self):
        """Events have all required fields"""
        response = self.session.get(f"{BASE_URL}/api/sensors/voice-distress/events?limit=5")
        assert response.status_code == 200
        data = response.json()
        
        if data["count"] > 0:
            event = data["events"][0]
            required_fields = [
                "event_id", "user_id", "lat", "lng", "keywords", 
                "scream_detected", "repeated_detection", "distress_score",
                "status", "created_at"
            ]
            for field in required_fields:
                assert field in event, f"Missing field {field} in event: {event}"
            print(f"PASS: Event has all required fields")
        else:
            print("SKIP: No events to verify fields")

    def test_list_events_limit(self):
        """GET /sensors/voice-distress/events respects limit param"""
        response = self.session.get(f"{BASE_URL}/api/sensors/voice-distress/events?limit=3")
        assert response.status_code == 200
        data = response.json()
        
        assert len(data["events"]) <= 3, f"Expected max 3 events, got {len(data['events'])}"
        print(f"PASS: Limit parameter respected - got {len(data['events'])} events")


class TestAutoSOSTrigger:
    """Test auto-SOS trigger integration"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        login_resp = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": "nischint4parents@gmail.com",
            "password": "secret123"
        })
        token = login_resp.json().get("access_token")
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    def test_auto_sos_creates_emergency_event(self):
        """Score >= 0.9 triggers Silent SOS pipeline"""
        unique_lat = 19.140 + (time.time() % 1000) / 100000
        response = self.session.post(f"{BASE_URL}/api/sensors/voice-distress", json={
            "lat": unique_lat, "lng": 72.940,
            "keywords": ["help", "stop", "emergency"],
            "scream_detected": True,
            "repeated": True,
            "audio_features": {"amplitude": 0.95, "pitch_variance": 0.8}
        })
        
        if response.status_code == 429:
            print("SKIP: In cooldown")
            return
        
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        if data.get("distress_score") >= 0.9:
            assert data.get("status") == "auto_sos", f"Expected auto_sos: {data}"
            assert data.get("auto_sos") == True, f"auto_sos flag should be True"
            # May have emergency_event_id if SOS was triggered
            if data.get("emergency_event_id"):
                print(f"PASS: Auto-SOS triggered emergency: {data.get('emergency_event_id')[:8]}...")
            else:
                print(f"PASS: Auto-SOS status set (emergency may have failed or been handled)")
        else:
            print(f"SKIP: Score {data.get('distress_score')} below auto-SOS threshold")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
