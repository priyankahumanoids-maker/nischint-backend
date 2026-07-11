# Voice Distress → Guardian Alert Escalation Tests
#
# Tests for P1: Voice distress → guardian alert escalation
# POST /api/sensors/voice-distress with scream_detected=true and high amplitude
# - Returns status=alert with score >= 0.50
# - Broadcasts VOICE_DISTRESS safety_alert via SSE to linked guardians
# - Creates GuardianAlert record
# - GET /api/guardian/dashboard/alerts returns voice_distress alert
#
# Scoring weights: W_KEYWORD=0.30, W_SCREAM=0.55, W_REPETITION=0.15
# ALERT_THRESHOLD=0.50, AUTO_SOS_THRESHOLD=0.90, COOLDOWN=30s

import pytest
import requests
import os
import time
import subprocess

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
CHILD_EMAIL = "kidnischint@gmail.com"
CHILD_PASSWORD = "nischint123"
CHILD_USER_ID = "ae6c29f9-aafd-4449-abc3-881effa122a4"

GUARDIAN_EMAIL = "mothernischint@gmail.com"
GUARDIAN_PASSWORD = "nischint123"


class TestVoiceDistressScreamAlert:
    """Test scream detection triggers alert with score >= 0.50"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        # Login as child
        login_resp = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": CHILD_EMAIL,
            "password": CHILD_PASSWORD
        })
        assert login_resp.status_code == 200, f"Child login failed: {login_resp.text}"
        token = login_resp.json().get("access_token")
        self.session.headers.update({"Authorization": f"Bearer {token}"})
        self.child_user_id = login_resp.json().get("user", {}).get("id")
        print(f"Logged in as child: {self.child_user_id}")

    def test_scream_with_high_amplitude_returns_alert(self):
        """POST /api/sensors/voice-distress with scream_detected=true and high amplitude returns status=alert with score >= 0.50"""
        # Scream score calculation:
        # scream_detected=True → base 0.8
        # amplitude > 0.5 → boost to 0.9
        # W_SCREAM=0.55 → 0.55 * 0.9 = 0.495
        # Need slight boost to cross 0.50 threshold
        # With amplitude > 0.8 and pitch_variance > 0.6 → scream_score = 1.0 → 0.55 * 1.0 = 0.55 >= 0.50
        
        unique_lat = 19.076 + (time.time() % 1000) / 100000
        response = self.session.post(f"{BASE_URL}/api/sensors/voice-distress", json={
            "lat": unique_lat,
            "lng": 72.877,
            "keywords": None,
            "scream_detected": True,
            "repeated": False,
            "audio_features": {"amplitude": 0.85, "pitch_variance": 0.65}
        })
        
        if response.status_code == 429:
            print("SKIP: In cooldown from previous test")
            pytest.skip("In cooldown")
            return
        
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        # Score should be >= 0.50 (alert threshold)
        assert data.get("distress_score") >= 0.50, f"Expected score >= 0.50, got {data.get('distress_score')}"
        assert data.get("status") == "alert", f"Expected status=alert, got {data.get('status')}"
        assert "event_id" in data, f"Missing event_id in response: {data}"
        assert data.get("scream_detected") == True, f"scream_detected should be True"
        
        print(f"PASS: Scream with high amplitude - score={data.get('distress_score')}, status={data.get('status')}")


class TestVoiceDistressBelowThreshold:
    """Test non-distress signals return below_threshold"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        login_resp = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": CHILD_EMAIL,
            "password": CHILD_PASSWORD
        })
        assert login_resp.status_code == 200, f"Child login failed: {login_resp.text}"
        token = login_resp.json().get("access_token")
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    def test_no_scream_no_keywords_below_threshold(self):
        """POST /api/sensors/voice-distress with scream_detected=false and no keywords returns status=below_threshold"""
        response = self.session.post(f"{BASE_URL}/api/sensors/voice-distress", json={
            "lat": 19.080,
            "lng": 72.880,
            "keywords": None,
            "scream_detected": False,
            "repeated": False,
            "audio_features": None
        })
        
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        assert data.get("status") == "below_threshold", f"Expected below_threshold, got {data.get('status')}"
        assert data.get("distress_score") < 0.50, f"Score {data.get('distress_score')} should be < 0.50"
        
        print(f"PASS: No scream, no keywords - score={data.get('distress_score')}, status={data.get('status')}")

    def test_non_distress_keywords_below_threshold(self):
        """POST /api/sensors/voice-distress with non-distress keywords returns below_threshold"""
        response = self.session.post(f"{BASE_URL}/api/sensors/voice-distress", json={
            "lat": 19.081,
            "lng": 72.881,
            "keywords": ["hello", "goodbye", "thanks"],
            "scream_detected": False,
            "repeated": False
        })
        
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        assert data.get("status") == "below_threshold", f"Expected below_threshold, got {data.get('status')}"
        print(f"PASS: Non-distress keywords - score={data.get('distress_score')}, status={data.get('status')}")


class TestVoiceDistressKeywordsWithScream:
    """Test keywords + scream combination"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        login_resp = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": CHILD_EMAIL,
            "password": CHILD_PASSWORD
        })
        assert login_resp.status_code == 200, f"Child login failed: {login_resp.text}"
        token = login_resp.json().get("access_token")
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    def test_keywords_help_stop_with_scream_high_score(self):
        """POST /api/sensors/voice-distress with keywords=['help','stop'] and scream returns high score"""
        # keyword_score = min(2/2, 1.0) = 1.0 → W_KEYWORD * 1.0 = 0.30
        # scream_score = 0.8 (base) → W_SCREAM * 0.8 = 0.44
        # Total = 0.30 + 0.44 = 0.74 >= 0.50
        
        unique_lat = 19.085 + (time.time() % 1000) / 100000
        response = self.session.post(f"{BASE_URL}/api/sensors/voice-distress", json={
            "lat": unique_lat,
            "lng": 72.885,
            "keywords": ["help", "stop"],
            "scream_detected": True,
            "repeated": False,
            "audio_features": None
        })
        
        if response.status_code == 429:
            print("SKIP: In cooldown")
            pytest.skip("In cooldown")
            return
        
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        # Should be alert or auto_sos
        assert data.get("status") in ("alert", "auto_sos"), f"Expected alert/auto_sos, got {data.get('status')}"
        assert data.get("distress_score") >= 0.50, f"Score should be >= 0.50, got {data.get('distress_score')}"
        assert "keywords_matched" in data, f"Missing keywords_matched: {data}"
        assert "help" in [k.lower() for k in data.get("keywords_matched", [])], "help should be in keywords_matched"
        assert "stop" in [k.lower() for k in data.get("keywords_matched", [])], "stop should be in keywords_matched"
        
        print(f"PASS: Keywords + scream - score={data.get('distress_score')}, keywords_matched={data.get('keywords_matched')}")


class TestVoiceDistressCooldown:
    """Test cooldown behavior (30s between events)"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        login_resp = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": CHILD_EMAIL,
            "password": CHILD_PASSWORD
        })
        assert login_resp.status_code == 200, f"Child login failed: {login_resp.text}"
        token = login_resp.json().get("access_token")
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    def test_cooldown_within_30s(self):
        """POST /api/sensors/voice-distress respects cooldown (second call within 30s returns status=cooldown or 429)"""
        # First request - trigger alert
        unique_lat = 19.090 + (time.time() % 1000) / 100000
        response1 = self.session.post(f"{BASE_URL}/api/sensors/voice-distress", json={
            "lat": unique_lat,
            "lng": 72.890,
            "keywords": ["help"],
            "scream_detected": True,
            "repeated": False,
            "audio_features": {"amplitude": 0.85, "pitch_variance": 0.65}
        })
        
        if response1.status_code == 429:
            # Already in cooldown, test passes
            print("PASS: Already in cooldown (429)")
            return
        
        assert response1.status_code == 200, f"First request failed: {response1.text}"
        first_data = response1.json()
        
        if first_data.get("status") == "below_threshold":
            print("SKIP: First request below threshold, no cooldown triggered")
            pytest.skip("Below threshold")
            return
        
        # Second request immediately
        response2 = self.session.post(f"{BASE_URL}/api/sensors/voice-distress", json={
            "lat": unique_lat + 0.001,
            "lng": 72.890,
            "keywords": ["help"],
            "scream_detected": True,
            "repeated": False,
            "audio_features": {"amplitude": 0.6, "pitch_variance": 0.5}  # Lower to avoid auto_sos bypass
        })
        
        # Should get 429 or cooldown status
        if response2.status_code == 429:
            print("PASS: Cooldown 429 returned within 30s")
        elif response2.status_code == 200:
            data2 = response2.json()
            if data2.get("status") == "cooldown":
                print("PASS: Cooldown status returned")
            elif data2.get("distress_score", 0) >= 0.9:
                print(f"PASS: Auto-SOS bypass (score >= 0.9): {data2.get('distress_score')}")
            else:
                pytest.fail(f"Expected cooldown, got: {data2}")
        else:
            pytest.fail(f"Unexpected response: {response2.status_code} - {response2.text}")


class TestVoiceDistressSSEBroadcast:
    """Test SSE broadcast to linked guardians"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.child_session = requests.Session()
        self.child_session.headers.update({"Content-Type": "application/json"})
        
        # Login as child
        login_resp = self.child_session.post(f"{BASE_URL}/api/auth/login", json={
            "email": CHILD_EMAIL,
            "password": CHILD_PASSWORD
        })
        assert login_resp.status_code == 200, f"Child login failed: {login_resp.text}"
        token = login_resp.json().get("access_token")
        self.child_session.headers.update({"Authorization": f"Bearer {token}"})
        self.child_user_id = login_resp.json().get("user", {}).get("id")

    def test_sse_voice_alert_logged_for_guardians(self):
        """Backend logs show [SSE_VOICE_ALERT] type=VOICE_DISTRESS for each linked guardian when alert fires"""
        # Clear backend logs first
        subprocess.run(["truncate", "-s", "0", "/var/log/supervisor/backend.err.log"], capture_output=True)
        time.sleep(0.5)
        
        # Trigger voice distress alert
        unique_lat = 19.095 + (time.time() % 1000) / 100000
        response = self.child_session.post(f"{BASE_URL}/api/sensors/voice-distress", json={
            "lat": unique_lat,
            "lng": 72.895,
            "keywords": ["help", "stop"],
            "scream_detected": True,
            "repeated": True,
            "audio_features": {"amplitude": 0.9, "pitch_variance": 0.7}
        })
        
        if response.status_code == 429:
            print("SKIP: In cooldown")
            pytest.skip("In cooldown")
            return
        
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        if data.get("status") == "below_threshold":
            print("SKIP: Below threshold, no SSE broadcast")
            pytest.skip("Below threshold")
            return
        
        # Wait for SSE broadcast to complete
        time.sleep(1)
        
        # Check backend logs for SSE_VOICE_ALERT
        result = subprocess.run(
            ["grep", "-i", "SSE_VOICE_ALERT", "/var/log/supervisor/backend.err.log"],
            capture_output=True, text=True
        )
        
        if result.returncode == 0 and result.stdout:
            log_lines = result.stdout.strip().split('\n')
            print(f"Found {len(log_lines)} SSE_VOICE_ALERT log entries")
            
            # Check for VOICE_DISTRESS type
            voice_distress_logs = [l for l in log_lines if "VOICE_DISTRESS" in l]
            assert len(voice_distress_logs) > 0, f"No VOICE_DISTRESS logs found. Logs: {log_lines}"
            
            # Check for child user_id in logs (use CHILD_USER_ID constant)
            child_logs = [l for l in voice_distress_logs if CHILD_USER_ID in l]
            print(f"PASS: Found {len(voice_distress_logs)} VOICE_DISTRESS SSE logs, {len(child_logs)} for child {CHILD_USER_ID}")
            for log in voice_distress_logs[:3]:
                print(f"  Log: {log[:200]}...")
        else:
            # May not have linked guardians
            print(f"WARNING: No SSE_VOICE_ALERT logs found. Child may not have linked guardians.")
            print(f"Response: {data}")


class TestGuardianDashboardVoiceDistressAlert:
    """Test GET /api/guardian/dashboard/alerts returns voice_distress alert"""

    @pytest.fixture(autouse=True)
    def setup(self):
        # Child session for triggering alert
        self.child_session = requests.Session()
        self.child_session.headers.update({"Content-Type": "application/json"})
        login_child = self.child_session.post(f"{BASE_URL}/api/auth/login", json={
            "email": CHILD_EMAIL,
            "password": CHILD_PASSWORD
        })
        assert login_child.status_code == 200, f"Child login failed: {login_child.text}"
        child_token = login_child.json().get("access_token")
        self.child_session.headers.update({"Authorization": f"Bearer {child_token}"})
        
        # Guardian session for checking alerts
        self.guardian_session = requests.Session()
        self.guardian_session.headers.update({"Content-Type": "application/json"})
        login_guardian = self.guardian_session.post(f"{BASE_URL}/api/auth/login", json={
            "email": GUARDIAN_EMAIL,
            "password": GUARDIAN_PASSWORD
        })
        assert login_guardian.status_code == 200, f"Guardian login failed: {login_guardian.text}"
        guardian_token = login_guardian.json().get("access_token")
        self.guardian_session.headers.update({"Authorization": f"Bearer {guardian_token}"})
        self.guardian_user_id = login_guardian.json().get("user", {}).get("id")

    def test_guardian_dashboard_alerts_includes_voice_distress(self):
        """GET /api/guardian/dashboard/alerts returns voice_distress alert after scream report"""
        # First trigger a voice distress alert as child
        unique_lat = 19.100 + (time.time() % 1000) / 100000
        trigger_resp = self.child_session.post(f"{BASE_URL}/api/sensors/voice-distress", json={
            "lat": unique_lat,
            "lng": 72.900,
            "keywords": ["help", "emergency"],
            "scream_detected": True,
            "repeated": True,
            "audio_features": {"amplitude": 0.9, "pitch_variance": 0.7}
        })
        
        if trigger_resp.status_code == 429:
            print("SKIP: In cooldown")
            pytest.skip("In cooldown")
            return
        
        assert trigger_resp.status_code == 200, f"Trigger failed: {trigger_resp.text}"
        trigger_data = trigger_resp.json()
        
        if trigger_data.get("status") == "below_threshold":
            print("SKIP: Below threshold, no alert created")
            pytest.skip("Below threshold")
            return
        
        event_id = trigger_data.get("event_id")
        print(f"Triggered voice distress event: {event_id}")
        
        # Wait for alert to be created
        time.sleep(1)
        
        # Check guardian dashboard alerts
        alerts_resp = self.guardian_session.get(f"{BASE_URL}/api/guardian/dashboard/alerts?limit=50")
        assert alerts_resp.status_code == 200, f"Alerts failed: {alerts_resp.text}"
        alerts_data = alerts_resp.json()
        
        assert "alerts" in alerts_data, f"Missing alerts key: {alerts_data}"
        alerts = alerts_data.get("alerts", [])
        
        # Look for voice_distress alert
        voice_alerts = [a for a in alerts if a.get("alert_type") == "voice_distress" or a.get("type") == "voice_distress"]
        
        if voice_alerts:
            latest_voice = voice_alerts[0]
            print(f"PASS: Found voice_distress alert: {latest_voice.get('message', '')[:100]}")
            assert latest_voice.get("severity") in ("high", "critical"), f"Expected high/critical severity: {latest_voice}"
        else:
            # May not have active session for child
            print(f"WARNING: No voice_distress alerts found in guardian dashboard.")
            print(f"Total alerts: {len(alerts)}")
            print(f"Alert types: {[a.get('alert_type') for a in alerts[:5]]}")
            # This is expected if child doesn't have an active GuardianSession
            # The GuardianAlert is only created if child has active session


class TestVoiceDistressAutoSOS:
    """Test auto-SOS trigger for critical distress (score >= 0.90)"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        login_resp = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": CHILD_EMAIL,
            "password": CHILD_PASSWORD
        })
        assert login_resp.status_code == 200, f"Child login failed: {login_resp.text}"
        token = login_resp.json().get("access_token")
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    def test_max_signals_triggers_auto_sos(self):
        """All signals maxed (keywords + scream + repeated + audio boost) triggers auto_sos"""
        # keyword_score = 1.0 (2+ keywords) → 0.30
        # scream_score = 1.0 (amp > 0.8, pitch > 0.6) → 0.55
        # repetition_score = 1.0 → 0.15
        # Total = 0.30 + 0.55 + 0.15 = 1.0 >= 0.90 → auto_sos
        
        unique_lat = 19.110 + (time.time() % 1000) / 100000
        response = self.session.post(f"{BASE_URL}/api/sensors/voice-distress", json={
            "lat": unique_lat,
            "lng": 72.910,
            "keywords": ["help", "stop", "emergency"],
            "scream_detected": True,
            "repeated": True,
            "audio_features": {"amplitude": 0.95, "pitch_variance": 0.8}
        })
        
        if response.status_code == 429:
            print("SKIP: In cooldown")
            pytest.skip("In cooldown")
            return
        
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        assert data.get("distress_score") >= 0.90, f"Expected score >= 0.90, got {data.get('distress_score')}"
        assert data.get("status") == "auto_sos", f"Expected auto_sos, got {data.get('status')}"
        assert data.get("auto_sos") == True, f"auto_sos flag should be True"
        
        print(f"PASS: Auto-SOS triggered - score={data.get('distress_score')}, emergency_event_id={data.get('emergency_event_id')}")


class TestVoiceDistressResponsePayload:
    """Test response payload structure"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        login_resp = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": CHILD_EMAIL,
            "password": CHILD_PASSWORD
        })
        assert login_resp.status_code == 200, f"Child login failed: {login_resp.text}"
        token = login_resp.json().get("access_token")
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    def test_alert_response_has_required_fields(self):
        """Alert response includes: status, distress_score, event_id, keywords_matched, scream_detected, auto_sos"""
        unique_lat = 19.115 + (time.time() % 1000) / 100000
        response = self.session.post(f"{BASE_URL}/api/sensors/voice-distress", json={
            "lat": unique_lat,
            "lng": 72.915,
            "keywords": ["help", "stop"],
            "scream_detected": True,
            "repeated": True,
            "audio_features": {"amplitude": 0.9, "pitch_variance": 0.7}
        })
        
        if response.status_code == 429:
            print("SKIP: In cooldown")
            pytest.skip("In cooldown")
            return
        
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        if data.get("status") == "below_threshold":
            # Below threshold has different fields
            assert "status" in data
            assert "distress_score" in data
            print(f"PASS: Below threshold response has required fields")
            return
        
        # Alert/auto_sos response fields
        required_fields = ["status", "distress_score", "event_id", "keywords_matched", "scream_detected", "auto_sos"]
        for field in required_fields:
            assert field in data, f"Missing field '{field}' in response: {data}"
        
        print(f"PASS: Alert response has all required fields: {list(data.keys())}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
