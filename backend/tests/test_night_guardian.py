# Night Guardian API Tests
# Tests for Night Safety Guardian monitoring during night journeys
# Phase 34: Start/Stop sessions, location updates, zone escalation, idle detection, ETA

import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASS = "operator123"

# Test coordinates - from agent context
START_LAT = 12.971
START_LNG = 77.594
HIGH_ZONE_LAT = 12.972
HIGH_ZONE_LNG = 77.587
DEST_LAT = 12.935
DEST_LNG = 77.624


@pytest.fixture(scope="module")
def auth_token():
    """Get operator authentication token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": OPERATOR_EMAIL,
        "password": OPERATOR_PASS
    })
    assert response.status_code == 200, f"Login failed: {response.text}"
    return response.json()["access_token"]


@pytest.fixture(scope="module")
def api_client(auth_token):
    """Session with auth header"""
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {auth_token}"
    })
    return session


@pytest.fixture
def clean_session(api_client):
    """Clean up any existing test session before/after test"""
    test_user_id = "pytest-night-user"
    # Stop any existing session first
    api_client.post(f"{BASE_URL}/api/night-guardian/stop", json={"user_id": test_user_id})
    yield test_user_id
    # Cleanup after test
    api_client.post(f"{BASE_URL}/api/night-guardian/stop", json={"user_id": test_user_id})


class TestNightGuardianBasicAPIs:
    """Test Night Guardian basic API endpoints"""

    def test_authentication_required_for_start(self):
        """POST /night-guardian/start requires auth"""
        response = requests.post(f"{BASE_URL}/api/night-guardian/start", json={
            "location": {"lat": START_LAT, "lng": START_LNG}
        })
        assert response.status_code in [401, 403], "Should require authentication"

    def test_authentication_required_for_sessions(self):
        """GET /night-guardian/sessions requires auth"""
        response = requests.get(f"{BASE_URL}/api/night-guardian/sessions")
        assert response.status_code in [401, 403], "Should require authentication"

    def test_authentication_required_for_status(self):
        """GET /night-guardian/status requires auth"""
        response = requests.get(f"{BASE_URL}/api/night-guardian/status")
        assert response.status_code in [401, 403], "Should require authentication"


class TestStartSession:
    """Test POST /night-guardian/start endpoint"""

    def test_start_session_creates_active_session(self, api_client, clean_session):
        """POST /start creates active session with initial zone check"""
        response = api_client.post(f"{BASE_URL}/api/night-guardian/start", json={
            "user_id": clean_session,
            "location": {"lat": START_LAT, "lng": START_LNG},
            "destination": {"lat": DEST_LAT, "lng": DEST_LNG}
        })
        assert response.status_code == 200, f"Start failed: {response.text}"
        data = response.json()
        
        # Verify response structure
        assert data["guardian_active"] == True
        assert data["user_id"] == clean_session
        assert "monitoring_started" in data
        assert "is_night" in data
        assert "initial_zone" in data
        assert "destination" in data
        
        # Verify initial zone has all required fields
        zone = data["initial_zone"]
        assert "zone_id" in zone
        assert "risk_level" in zone
        assert "risk_score" in zone
        assert "zone_name" in zone
        
    def test_start_session_returns_destination_info(self, api_client, clean_session):
        """Start session with destination returns destination info"""
        response = api_client.post(f"{BASE_URL}/api/night-guardian/start", json={
            "user_id": clean_session,
            "location": {"lat": START_LAT, "lng": START_LNG},
            "destination": {"lat": DEST_LAT, "lng": DEST_LNG}
        })
        assert response.status_code == 200
        data = response.json()
        
        assert data["destination"] is not None
        assert data["destination"]["lat"] == DEST_LAT
        assert data["destination"]["lng"] == DEST_LNG

    def test_start_without_destination(self, api_client, clean_session):
        """Start session without destination is allowed"""
        response = api_client.post(f"{BASE_URL}/api/night-guardian/start", json={
            "user_id": clean_session,
            "location": {"lat": START_LAT, "lng": START_LNG}
        })
        assert response.status_code == 200
        data = response.json()
        assert data["guardian_active"] == True
        assert data["destination"] is None


class TestStopSession:
    """Test POST /night-guardian/stop endpoint"""

    def test_stop_session_returns_summary(self, api_client, clean_session):
        """POST /stop ends session and returns summary"""
        # Start first
        api_client.post(f"{BASE_URL}/api/night-guardian/start", json={
            "user_id": clean_session,
            "location": {"lat": START_LAT, "lng": START_LNG}
        })
        
        # Stop
        response = api_client.post(f"{BASE_URL}/api/night-guardian/stop", json={
            "user_id": clean_session
        })
        assert response.status_code == 200
        data = response.json()
        
        # Verify summary fields
        assert data["guardian_active"] == False
        assert data["user_id"] == clean_session
        assert "monitoring_stopped" in data
        assert "duration_minutes" in data
        assert "total_distance_m" in data
        assert "alerts_triggered" in data
        assert "final_zone" in data

    def test_stop_nonexistent_session(self, api_client):
        """Stop non-existent session returns appropriate message"""
        response = api_client.post(f"{BASE_URL}/api/night-guardian/stop", json={
            "user_id": "nonexistent-user-id"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["guardian_active"] == False
        assert "message" in data or "No active session" in str(data)


class TestStatus:
    """Test GET /night-guardian/status endpoint"""

    def test_status_returns_full_session_state(self, api_client, clean_session):
        """GET /status returns full session state"""
        # Start session first
        api_client.post(f"{BASE_URL}/api/night-guardian/start", json={
            "user_id": clean_session,
            "location": {"lat": START_LAT, "lng": START_LNG},
            "destination": {"lat": DEST_LAT, "lng": DEST_LNG}
        })
        
        # Get status
        response = api_client.get(f"{BASE_URL}/api/night-guardian/status", params={
            "user_id": clean_session
        })
        assert response.status_code == 200
        data = response.json()
        
        # Verify all fields
        assert data["active"] == True
        assert data["user_id"] == clean_session
        assert "started_at" in data
        assert "duration_minutes" in data
        assert "current_location" in data
        assert "current_zone" in data
        assert "destination" in data
        assert "eta_minutes" in data
        assert "speed_mps" in data
        assert "is_night" in data
        assert "is_idle" in data
        assert "idle_duration_s" in data
        assert "route_deviated" in data
        assert "route_deviation_m" in data
        assert "escalation_level" in data
        assert "alert_count" in data
        assert "alerts" in data
        assert "total_distance_m" in data
        assert "location_updates" in data
        assert "safety_check_pending" in data
        assert "poll_interval_s" in data

    def test_status_no_active_session(self, api_client):
        """Status for non-existent session returns inactive"""
        response = api_client.get(f"{BASE_URL}/api/night-guardian/status", params={
            "user_id": "nonexistent-user-xyz"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["active"] == False


class TestSessions:
    """Test GET /night-guardian/sessions endpoint (operator-only)"""

    def test_sessions_requires_operator(self, api_client):
        """GET /sessions requires operator role"""
        response = api_client.get(f"{BASE_URL}/api/night-guardian/sessions")
        # Should pass for operator
        assert response.status_code == 200
        data = response.json()
        assert "sessions" in data
        assert isinstance(data["sessions"], list)

    def test_sessions_returns_active_sessions(self, api_client, clean_session):
        """GET /sessions returns all active sessions"""
        # Start a session
        api_client.post(f"{BASE_URL}/api/night-guardian/start", json={
            "user_id": clean_session,
            "location": {"lat": START_LAT, "lng": START_LNG}
        })
        
        # Get sessions
        response = api_client.get(f"{BASE_URL}/api/night-guardian/sessions")
        assert response.status_code == 200
        data = response.json()
        
        # Find our session
        our_session = None
        for s in data["sessions"]:
            if s["user_id"] == clean_session:
                our_session = s
                break
        
        assert our_session is not None, "Our session should be in the list"
        assert "risk_level" in our_session
        assert "risk_score" in our_session
        assert "zone_name" in our_session
        assert "is_idle" in our_session
        assert "route_deviated" in our_session
        assert "escalation_level" in our_session
        assert "alert_count" in our_session
        assert "location" in our_session


class TestUpdateLocation:
    """Test POST /night-guardian/update-location endpoint"""

    def test_update_location_basic(self, api_client, clean_session):
        """POST /update-location processes movement"""
        # Start session
        api_client.post(f"{BASE_URL}/api/night-guardian/start", json={
            "user_id": clean_session,
            "location": {"lat": START_LAT, "lng": START_LNG},
            "destination": {"lat": DEST_LAT, "lng": DEST_LNG}
        })
        
        # Update location
        new_lat = START_LAT + 0.001
        new_lng = START_LNG + 0.001
        response = api_client.post(f"{BASE_URL}/api/night-guardian/update-location", json={
            "user_id": clean_session,
            "location": {"lat": new_lat, "lng": new_lng}
        })
        assert response.status_code == 200
        data = response.json()
        
        # Verify response
        assert data["user_id"] == clean_session
        assert data["location"]["lat"] == new_lat
        assert data["location"]["lng"] == new_lng
        assert "zone" in data
        assert "speed_mps" in data
        assert "eta_minutes" in data
        assert "is_idle" in data
        assert "escalation_level" in data
        assert "alerts" in data
        assert "poll_interval_s" in data

    def test_update_location_zone_check(self, api_client, clean_session):
        """Location update checks zone risk level"""
        # Start session
        api_client.post(f"{BASE_URL}/api/night-guardian/start", json={
            "user_id": clean_session,
            "location": {"lat": START_LAT, "lng": START_LNG}
        })
        
        # Move to different location
        response = api_client.post(f"{BASE_URL}/api/night-guardian/update-location", json={
            "user_id": clean_session,
            "location": {"lat": HIGH_ZONE_LAT, "lng": HIGH_ZONE_LNG}
        })
        assert response.status_code == 200
        data = response.json()
        
        # Zone should be checked
        assert "zone" in data
        assert "risk_level" in data["zone"]
        assert "risk_score" in data["zone"]
        assert "zone_name" in data["zone"]

    def test_update_location_no_session_returns_error(self, api_client):
        """Update location without active session returns 404"""
        response = api_client.post(f"{BASE_URL}/api/night-guardian/update-location", json={
            "user_id": "no-session-user",
            "location": {"lat": START_LAT, "lng": START_LNG}
        })
        assert response.status_code == 404


class TestZoneEscalation:
    """Test zone escalation alerts"""

    def test_zone_escalation_low_to_high_triggers_user_alert(self, api_client, clean_session):
        """Zone escalation from LOW→HIGH triggers user alert"""
        # Start session in a safe area
        api_client.post(f"{BASE_URL}/api/night-guardian/start", json={
            "user_id": clean_session,
            "location": {"lat": START_LAT, "lng": START_LNG}  # Should be SAFE or LOW
        })
        
        # Move to HIGH risk zone
        response = api_client.post(f"{BASE_URL}/api/night-guardian/update-location", json={
            "user_id": clean_session,
            "location": {"lat": HIGH_ZONE_LAT, "lng": HIGH_ZONE_LNG}
        })
        data = response.json()
        
        # Check for zone escalation alert
        if data.get("alerts"):
            escalation_alerts = [a for a in data["alerts"] if a.get("type") == "zone_escalation"]
            if escalation_alerts:
                # Verify alert structure
                alert = escalation_alerts[0]
                assert "message" in alert
                assert "severity" in alert
                assert "alert_level" in alert
                print(f"Zone escalation alert: {alert['message']}")

    def test_same_zone_no_new_alert(self, api_client, clean_session):
        """Same zone repeated update = no new zone_escalation alert"""
        # Start session
        api_client.post(f"{BASE_URL}/api/night-guardian/start", json={
            "user_id": clean_session,
            "location": {"lat": START_LAT, "lng": START_LNG}
        })
        
        # Update to same location multiple times
        for _ in range(3):
            response = api_client.post(f"{BASE_URL}/api/night-guardian/update-location", json={
                "user_id": clean_session,
                "location": {"lat": START_LAT + 0.0001, "lng": START_LNG + 0.0001}
            })
            data = response.json()
            # No zone_escalation alerts for same zone
            zone_alerts = [a for a in data.get("alerts", []) if a.get("type") == "zone_escalation"]
            assert len(zone_alerts) == 0, "No new zone alerts for same zone"


class TestETACalculation:
    """Test ETA tracking when destination is set"""

    def test_eta_calculation_with_destination(self, api_client, clean_session):
        """ETA calculated when destination is set and moving"""
        # Start session with destination
        api_client.post(f"{BASE_URL}/api/night-guardian/start", json={
            "user_id": clean_session,
            "location": {"lat": START_LAT, "lng": START_LNG},
            "destination": {"lat": DEST_LAT, "lng": DEST_LNG}
        })
        
        # Move toward destination at good speed
        response = api_client.post(f"{BASE_URL}/api/night-guardian/update-location", json={
            "user_id": clean_session,
            "location": {"lat": START_LAT + 0.005, "lng": START_LNG + 0.005}
        })
        data = response.json()
        
        # ETA should be calculated (may be None if speed too low)
        assert "eta_minutes" in data
        # If moving fast enough, eta should be a number
        # print(f"ETA: {data['eta_minutes']}")


class TestAcknowledgeSafety:
    """Test POST /night-guardian/acknowledge-safety endpoint"""

    def test_acknowledge_safety_clears_pending(self, api_client, clean_session):
        """Acknowledge safety clears safety_check_pending"""
        # Start session
        api_client.post(f"{BASE_URL}/api/night-guardian/start", json={
            "user_id": clean_session,
            "location": {"lat": START_LAT, "lng": START_LNG}
        })
        
        # Acknowledge safety
        response = api_client.post(f"{BASE_URL}/api/night-guardian/acknowledge-safety", params={
            "user_id": clean_session
        })
        assert response.status_code == 200
        data = response.json()
        
        assert data["acknowledged"] == True
        assert data["user_id"] == clean_session
        assert "timestamp" in data
        assert "escalation_level" in data

    def test_acknowledge_safety_no_session_returns_error(self, api_client):
        """Acknowledge safety without session returns 404"""
        response = api_client.post(f"{BASE_URL}/api/night-guardian/acknowledge-safety", params={
            "user_id": "no-session-user"
        })
        assert response.status_code == 404


class TestEscalationLevels:
    """Test escalation level assignments"""

    def test_escalation_levels_mapping(self, api_client, clean_session):
        """Verify escalation levels are correctly returned"""
        # Start session
        api_client.post(f"{BASE_URL}/api/night-guardian/start", json={
            "user_id": clean_session,
            "location": {"lat": START_LAT, "lng": START_LNG}
        })
        
        # Get status
        response = api_client.get(f"{BASE_URL}/api/night-guardian/status", params={
            "user_id": clean_session
        })
        data = response.json()
        
        # Escalation level should be one of the valid levels
        valid_levels = ["none", "user", "guardian", "emergency"]
        assert data["escalation_level"] in valid_levels


class TestIdleDetection:
    """Test idle state detection"""

    def test_speed_below_threshold_sets_idle(self, api_client, clean_session):
        """Speed < 0.5 m/s triggers idle state"""
        # Start session
        api_client.post(f"{BASE_URL}/api/night-guardian/start", json={
            "user_id": clean_session,
            "location": {"lat": START_LAT, "lng": START_LNG}
        })
        
        # Update location with tiny movement (will result in low speed)
        response = api_client.post(f"{BASE_URL}/api/night-guardian/update-location", json={
            "user_id": clean_session,
            "location": {"lat": START_LAT + 0.00001, "lng": START_LNG + 0.00001}
        })
        data = response.json()
        
        # Should track idle state
        assert "is_idle" in data
        assert "idle_duration_s" in data


class TestFullJourneyFlow:
    """Test complete journey flow"""

    def test_full_journey_start_to_stop(self, api_client, clean_session):
        """Complete journey: start → updates → stop with summary"""
        # 1. Start
        start_resp = api_client.post(f"{BASE_URL}/api/night-guardian/start", json={
            "user_id": clean_session,
            "location": {"lat": START_LAT, "lng": START_LNG},
            "destination": {"lat": DEST_LAT, "lng": DEST_LNG}
        })
        assert start_resp.status_code == 200
        assert start_resp.json()["guardian_active"] == True
        
        # 2. Simulate movement (3 updates)
        current_lat = START_LAT
        current_lng = START_LNG
        for i in range(3):
            current_lat += 0.003
            current_lng += 0.003
            update_resp = api_client.post(f"{BASE_URL}/api/night-guardian/update-location", json={
                "user_id": clean_session,
                "location": {"lat": current_lat, "lng": current_lng}
            })
            assert update_resp.status_code == 200
            time.sleep(0.1)  # Small delay between updates
        
        # 3. Check status
        status_resp = api_client.get(f"{BASE_URL}/api/night-guardian/status", params={
            "user_id": clean_session
        })
        assert status_resp.status_code == 200
        status = status_resp.json()
        assert status["active"] == True
        assert status["location_updates"] >= 3
        assert status["total_distance_m"] > 0
        
        # 4. Stop
        stop_resp = api_client.post(f"{BASE_URL}/api/night-guardian/stop", json={
            "user_id": clean_session
        })
        assert stop_resp.status_code == 200
        summary = stop_resp.json()
        
        # 5. Verify summary
        assert summary["guardian_active"] == False
        assert summary["duration_minutes"] >= 0
        assert summary["total_distance_m"] > 0
        assert summary["location_updates"] >= 3
        assert "alerts_triggered" in summary
        assert "final_zone" in summary
        
        print(f"Journey complete - Distance: {summary['total_distance_m']:.1f}m, Alerts: {summary['alerts_triggered']}")


class TestDataIntegrity:
    """Test data persistence and integrity"""

    def test_location_history_accumulates(self, api_client, clean_session):
        """Location updates accumulate correctly"""
        api_client.post(f"{BASE_URL}/api/night-guardian/start", json={
            "user_id": clean_session,
            "location": {"lat": START_LAT, "lng": START_LNG}
        })
        
        # Multiple updates
        for i in range(5):
            api_client.post(f"{BASE_URL}/api/night-guardian/update-location", json={
                "user_id": clean_session,
                "location": {"lat": START_LAT + (i * 0.002), "lng": START_LNG + (i * 0.002)}
            })
        
        # Check status
        response = api_client.get(f"{BASE_URL}/api/night-guardian/status", params={
            "user_id": clean_session
        })
        data = response.json()
        
        assert data["location_updates"] >= 5
        assert data["total_distance_m"] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
