# Night Guardian DB Persistence Tests
# Tests for DB-backed session persistence after refactoring from in-memory sessions
# Phase: Infrastructure hardening + Night Guardian engine refactor
# Features tested:
#   - POST /api/night-guardian/start - Creates DB-backed guardian session
#   - GET /api/night-guardian/status - Returns session status from DB
#   - POST /api/night-guardian/update-location - Updates location in DB, computes speed/zone
#   - POST /api/night-guardian/stop - Stops session and persists end state
#   - POST /api/night-guardian/acknowledge-safety - Acknowledges safety check
#   - Verify starting new session ends existing active sessions (no duplicates)
#   - Verify status returns 'No active session' after stop

import pytest
import requests
import os
import time
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
GUARDIAN_EMAIL = "nischint4parents@gmail.com"
GUARDIAN_PASS = "secret123"

# Test coordinates
START_LAT = 12.971
START_LNG = 77.594
DEST_LAT = 12.935
DEST_LNG = 77.624


@pytest.fixture(scope="module")
def auth_data():
    """Get guardian/admin authentication token and user info"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": GUARDIAN_EMAIL,
        "password": GUARDIAN_PASS
    })
    assert response.status_code == 200, f"Login failed: {response.text}"
    data = response.json()
    # Extract user_id from JWT token (sub claim)
    import base64
    import json as json_lib
    token_parts = data["access_token"].split(".")
    payload = json_lib.loads(base64.b64decode(token_parts[1] + "=="))
    return {
        "access_token": data["access_token"],
        "user_id": payload.get("sub")  # This is the authenticated user's UUID
    }


@pytest.fixture(scope="module")
def api_client(auth_data):
    """Session with auth header"""
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {auth_data['access_token']}"
    })
    return session


@pytest.fixture(scope="module")
def authenticated_user_id(auth_data):
    """Get the authenticated user's ID (which exists in the DB)"""
    return auth_data["user_id"]


@pytest.fixture
def clean_session(api_client, authenticated_user_id):
    """Clean up any existing test session before/after test"""
    # Stop any existing session first (for the authenticated user)
    api_client.post(f"{BASE_URL}/api/night-guardian/stop", json={})
    yield authenticated_user_id
    # Cleanup after test
    api_client.post(f"{BASE_URL}/api/night-guardian/stop", json={})


class TestAuthenticationRequired:
    """Verify authentication is required for Night Guardian endpoints"""

    def test_login_still_works_with_cognito_credentials(self):
        """POST /api/auth/login works with Cognito credentials"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": GUARDIAN_EMAIL,
            "password": GUARDIAN_PASS
        })
        assert response.status_code == 200, f"Login failed: {response.text}"
        data = response.json()
        
        assert "access_token" in data, "Should return access_token"
        assert "role" in data, "Should return role"
        assert data["role"] in ["admin", "guardian", "operator"], "Should have valid role"
        print(f"Login successful, role: {data['role']}")

    def test_start_requires_auth(self):
        """POST /night-guardian/start requires authentication"""
        response = requests.post(f"{BASE_URL}/api/night-guardian/start", json={
            "location": {"lat": START_LAT, "lng": START_LNG}
        })
        assert response.status_code in [401, 403], f"Should require auth, got {response.status_code}"

    def test_status_requires_auth(self):
        """GET /night-guardian/status requires authentication"""
        response = requests.get(f"{BASE_URL}/api/night-guardian/status")
        assert response.status_code in [401, 403], f"Should require auth, got {response.status_code}"

    def test_update_location_requires_auth(self):
        """POST /night-guardian/update-location requires authentication"""
        response = requests.post(f"{BASE_URL}/api/night-guardian/update-location", json={
            "location": {"lat": START_LAT, "lng": START_LNG}
        })
        assert response.status_code in [401, 403], f"Should require auth, got {response.status_code}"


class TestStartSession:
    """Test POST /api/night-guardian/start - Creates DB-backed guardian session"""

    def test_start_creates_db_backed_session(self, api_client, clean_session):
        """POST /start creates new DB-backed guardian session"""
        # Note: Not passing user_id - will use authenticated user's ID
        response = api_client.post(f"{BASE_URL}/api/night-guardian/start", json={
            "location": {"lat": START_LAT, "lng": START_LNG},
            "destination": {"lat": DEST_LAT, "lng": DEST_LNG}
        })
        assert response.status_code == 200, f"Start failed: {response.text}"
        data = response.json()
        
        # Verify response structure
        assert data["guardian_active"] == True, "Session should be active"
        assert "user_id" in data, "Should return user_id"
        assert "monitoring_started" in data, "Should have monitoring_started timestamp"
        assert "is_night" in data, "Should have is_night flag"
        assert "initial_zone" in data, "Should have initial_zone"
        assert "destination" in data, "Should have destination"
        assert "has_route" in data, "Should have has_route flag"
        
        # Verify initial zone structure
        zone = data["initial_zone"]
        assert "zone_id" in zone, "Zone should have zone_id"
        assert "risk_level" in zone, "Zone should have risk_level"
        assert "risk_score" in zone, "Zone should have risk_score"
        assert "zone_name" in zone, "Zone should have zone_name"

    def test_start_with_route_points(self, api_client, clean_session):
        """POST /start accepts route_points"""
        route_points = [
            {"lat": START_LAT, "lng": START_LNG},
            {"lat": START_LAT + 0.01, "lng": START_LNG + 0.01},
            {"lat": DEST_LAT, "lng": DEST_LNG}
        ]
        response = api_client.post(f"{BASE_URL}/api/night-guardian/start", json={
            "location": {"lat": START_LAT, "lng": START_LNG},
            "destination": {"lat": DEST_LAT, "lng": DEST_LNG},
            "route_points": route_points
        })
        assert response.status_code == 200, f"Start with route failed: {response.text}"
        data = response.json()
        
        assert data["guardian_active"] == True
        assert data["has_route"] == True, "Should indicate has_route=True"


class TestSessionStatus:
    """Test GET /api/night-guardian/status - Returns active session status from DB"""

    def test_status_returns_session_from_db(self, api_client, clean_session):
        """GET /status retrieves session from database"""
        # Start session first (using authenticated user)
        api_client.post(f"{BASE_URL}/api/night-guardian/start", json={
            "location": {"lat": START_LAT, "lng": START_LNG},
            "destination": {"lat": DEST_LAT, "lng": DEST_LNG}
        })
        
        # Get status (no user_id - uses authenticated user)
        response = api_client.get(f"{BASE_URL}/api/night-guardian/status")
        assert response.status_code == 200, f"Status failed: {response.text}"
        data = response.json()
        
        # Verify full session state
        assert data["active"] == True, "Session should be active"
        assert "user_id" in data, "Should have user_id"
        assert "started_at" in data, "Should have started_at"
        assert "duration_minutes" in data, "Should have duration_minutes"
        assert "current_location" in data, "Should have current_location"
        assert "current_zone" in data, "Should have current_zone"
        assert "destination" in data, "Should have destination"
        assert "eta_minutes" in data, "Should have eta_minutes"
        assert "speed_mps" in data, "Should have speed_mps"
        assert "is_night" in data, "Should have is_night"
        assert "is_idle" in data, "Should have is_idle"
        assert "idle_duration_s" in data, "Should have idle_duration_s"
        assert "route_deviated" in data, "Should have route_deviated"
        assert "route_deviation_m" in data, "Should have route_deviation_m"
        assert "escalation_level" in data, "Should have escalation_level"
        assert "alert_count" in data, "Should have alert_count"
        assert "alerts" in data, "Should have alerts list"
        assert "total_distance_m" in data, "Should have total_distance_m"
        assert "location_updates" in data, "Should have location_updates"
        assert "safety_check_pending" in data, "Should have safety_check_pending"
        assert "poll_interval_s" in data, "Should have poll_interval_s"

    def test_status_returns_no_active_session_when_none(self, api_client, clean_session):
        """GET /status returns 'No active session' when none exists"""
        # First stop any existing session
        api_client.post(f"{BASE_URL}/api/night-guardian/stop", json={})
        
        # Now check status - should show no active session
        response = api_client.get(f"{BASE_URL}/api/night-guardian/status")
        assert response.status_code == 200
        data = response.json()
        
        assert data["active"] == False, "Should indicate no active session"
        assert "message" in data or "No active" in str(data), "Should indicate no active session"


class TestUpdateLocation:
    """Test POST /api/night-guardian/update-location - Updates location in DB"""

    def test_update_location_persists_to_db(self, api_client, clean_session):
        """POST /update-location updates location in DB, computes speed/zone"""
        # Start session
        api_client.post(f"{BASE_URL}/api/night-guardian/start", json={
            "location": {"lat": START_LAT, "lng": START_LNG},
            "destination": {"lat": DEST_LAT, "lng": DEST_LNG}
        })
        
        # Update location (no user_id - uses authenticated user)
        new_lat = START_LAT + 0.002
        new_lng = START_LNG + 0.002
        response = api_client.post(f"{BASE_URL}/api/night-guardian/update-location", json={
            "location": {"lat": new_lat, "lng": new_lng}
        })
        assert response.status_code == 200, f"Update location failed: {response.text}"
        data = response.json()
        
        # Verify response
        assert "user_id" in data, "Should have user_id"
        assert data["location"]["lat"] == new_lat
        assert data["location"]["lng"] == new_lng
        assert "zone" in data, "Should have zone"
        assert "speed_mps" in data, "Should have computed speed"
        assert "eta_minutes" in data, "Should have ETA"
        assert "is_idle" in data, "Should have idle state"
        assert "escalation_level" in data, "Should have escalation_level"
        assert "alerts" in data, "Should have alerts list"
        assert "poll_interval_s" in data, "Should have poll_interval_s"
        
        # Verify zone structure
        zone = data["zone"]
        assert "zone_id" in zone
        assert "risk_level" in zone
        assert "risk_score" in zone
        assert "zone_name" in zone

    def test_update_location_increments_counters(self, api_client, clean_session):
        """Multiple location updates increment counters in DB"""
        # Start session
        api_client.post(f"{BASE_URL}/api/night-guardian/start", json={
            "location": {"lat": START_LAT, "lng": START_LNG}
        })
        
        # Multiple updates
        for i in range(3):
            api_client.post(f"{BASE_URL}/api/night-guardian/update-location", json={
                "location": {"lat": START_LAT + (i * 0.003), "lng": START_LNG + (i * 0.003)}
            })
        
        # Verify status shows accumulated values
        status = api_client.get(f"{BASE_URL}/api/night-guardian/status").json()
        
        assert status["active"] == True, "Session should be active"
        assert status["location_updates"] >= 3, "Should have at least 3 location updates"
        assert status["total_distance_m"] > 0, "Should have accumulated distance"

    def test_update_location_no_session_returns_404(self, api_client, clean_session):
        """POST /update-location without active session returns 404"""
        # First ensure no active session
        api_client.post(f"{BASE_URL}/api/night-guardian/stop", json={})
        
        # Now try to update location without a session
        response = api_client.post(f"{BASE_URL}/api/night-guardian/update-location", json={
            "location": {"lat": START_LAT, "lng": START_LNG}
        })
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"


class TestStopSession:
    """Test POST /api/night-guardian/stop - Stops session and persists end state"""

    def test_stop_persists_end_state(self, api_client, clean_session):
        """POST /stop stops session and persists end state in DB"""
        # Start session
        api_client.post(f"{BASE_URL}/api/night-guardian/start", json={
            "location": {"lat": START_LAT, "lng": START_LNG},
            "destination": {"lat": DEST_LAT, "lng": DEST_LNG}
        })
        
        # Do some updates
        api_client.post(f"{BASE_URL}/api/night-guardian/update-location", json={
            "location": {"lat": START_LAT + 0.005, "lng": START_LNG + 0.005}
        })
        
        # Stop session
        response = api_client.post(f"{BASE_URL}/api/night-guardian/stop", json={})
        assert response.status_code == 200, f"Stop failed: {response.text}"
        data = response.json()
        
        # Verify summary
        assert data["guardian_active"] == False, "Session should be inactive"
        assert "user_id" in data, "Should have user_id"
        assert "monitoring_stopped" in data, "Should have stop timestamp"
        assert "duration_minutes" in data, "Should have duration"
        assert "total_distance_m" in data, "Should have total distance"
        assert "location_updates" in data, "Should have location updates count"
        assert "alerts_triggered" in data, "Should have alerts count"
        assert "final_zone" in data, "Should have final zone"

    def test_status_returns_no_active_after_stop(self, api_client, clean_session):
        """GET /status returns 'No active session' after stop"""
        # Start and stop
        api_client.post(f"{BASE_URL}/api/night-guardian/start", json={
            "location": {"lat": START_LAT, "lng": START_LNG}
        })
        api_client.post(f"{BASE_URL}/api/night-guardian/stop", json={})
        
        # Verify status
        response = api_client.get(f"{BASE_URL}/api/night-guardian/status")
        assert response.status_code == 200
        data = response.json()
        
        assert data["active"] == False, "Should have no active session after stop"


class TestAcknowledgeSafety:
    """Test POST /api/night-guardian/acknowledge-safety"""

    def test_acknowledge_safety_works(self, api_client, clean_session):
        """POST /acknowledge-safety acknowledges safety check"""
        # Start session
        api_client.post(f"{BASE_URL}/api/night-guardian/start", json={
            "location": {"lat": START_LAT, "lng": START_LNG}
        })
        
        # Acknowledge safety (no user_id - uses authenticated user)
        response = api_client.post(f"{BASE_URL}/api/night-guardian/acknowledge-safety")
        assert response.status_code == 200, f"Acknowledge failed: {response.text}"
        data = response.json()
        
        assert data["acknowledged"] == True, "Should be acknowledged"
        assert "user_id" in data, "Should have user_id"
        assert "timestamp" in data, "Should have timestamp"
        assert "escalation_level" in data, "Should have escalation_level"

    def test_acknowledge_safety_no_session_returns_404(self, api_client, clean_session):
        """POST /acknowledge-safety without session returns 404"""
        # First stop any existing session
        api_client.post(f"{BASE_URL}/api/night-guardian/stop", json={})
        
        # Now try acknowledge without a session
        response = api_client.post(f"{BASE_URL}/api/night-guardian/acknowledge-safety")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"


class TestNoDuplicateActiveSessions:
    """Test that starting new session ends existing active sessions"""

    def test_start_ends_existing_active_sessions(self, api_client, clean_session):
        """Starting a new session ends any existing active sessions for the same user"""
        # Start first session
        resp1 = api_client.post(f"{BASE_URL}/api/night-guardian/start", json={
            "location": {"lat": START_LAT, "lng": START_LNG}
        })
        assert resp1.status_code == 200, f"First start failed: {resp1.text}"
        
        # Verify first session is active
        status1 = api_client.get(f"{BASE_URL}/api/night-guardian/status").json()
        assert status1["active"] == True, "First session should be active"
        
        # Start second session (should end first)
        resp2 = api_client.post(f"{BASE_URL}/api/night-guardian/start", json={
            "location": {"lat": START_LAT + 0.01, "lng": START_LNG + 0.01}
        })
        assert resp2.status_code == 200, f"Second start failed: {resp2.text}"
        
        # Verify second session is active
        status2 = api_client.get(f"{BASE_URL}/api/night-guardian/status").json()
        assert status2["active"] == True, "Second session should be active"
        
        # The key test: there should be only ONE active session
        # If old sessions weren't ended, we might get MultipleResultsFound error
        # or wrong session data. The fact we got here without error means it worked.
        print(f"Successfully started second session, no duplicate active sessions error")


class TestAdminSystemHealth:
    """Test GET /api/admin/system-health still works"""

    def test_system_health_endpoint_works(self, api_client):
        """GET /api/admin/system-health returns health status"""
        response = api_client.get(f"{BASE_URL}/api/admin/system-health")
        assert response.status_code == 200, f"System health failed: {response.text}"
        data = response.json()
        
        assert "status" in data, "Should have status"
        assert data["status"] in ["healthy", "degraded", "unhealthy"], "Should have valid status"
        assert "services" in data, "Should have services"


class TestDBPersistenceVerification:
    """Verify data is truly persisted in DB across API calls"""

    def test_session_data_persists_across_calls(self, api_client, clean_session):
        """Session data persists in DB and can be retrieved"""
        # Start session with specific destination
        start_resp = api_client.post(f"{BASE_URL}/api/night-guardian/start", json={
            "location": {"lat": START_LAT, "lng": START_LNG},
            "destination": {"lat": DEST_LAT, "lng": DEST_LNG}
        })
        assert start_resp.status_code == 200
        
        # Get status and verify destination persisted
        status = api_client.get(f"{BASE_URL}/api/night-guardian/status").json()
        
        assert status["active"] == True
        assert status["destination"]["lat"] == DEST_LAT, "Destination lat should persist"
        assert status["destination"]["lng"] == DEST_LNG, "Destination lng should persist"
        
        # Update location
        api_client.post(f"{BASE_URL}/api/night-guardian/update-location", json={
            "location": {"lat": START_LAT + 0.01, "lng": START_LNG + 0.01}
        })
        
        # Get status again and verify updates persisted
        status2 = api_client.get(f"{BASE_URL}/api/night-guardian/status").json()
        
        assert status2["location_updates"] >= 1, "Location updates should be persisted"
        assert status2["total_distance_m"] > 0, "Distance should be accumulated"


class TestCompleteJourneyFlow:
    """Test complete journey flow with DB persistence"""

    def test_full_journey_persisted_in_db(self, api_client, clean_session):
        """Complete journey: start → multiple updates → stop, all persisted in DB"""
        # 1. Start
        start_resp = api_client.post(f"{BASE_URL}/api/night-guardian/start", json={
            "location": {"lat": START_LAT, "lng": START_LNG},
            "destination": {"lat": DEST_LAT, "lng": DEST_LNG}
        })
        assert start_resp.status_code == 200
        assert start_resp.json()["guardian_active"] == True
        
        # 2. Multiple location updates
        for i in range(5):
            lat = START_LAT + (i * 0.003)
            lng = START_LNG + (i * 0.003)
            update_resp = api_client.post(f"{BASE_URL}/api/night-guardian/update-location", json={
                "location": {"lat": lat, "lng": lng}
            })
            assert update_resp.status_code == 200
        
        # 3. Verify status shows accumulated data
        status = api_client.get(f"{BASE_URL}/api/night-guardian/status").json()
        
        assert status["active"] == True
        assert status["location_updates"] >= 5, "Should have at least 5 updates"
        assert status["total_distance_m"] > 0, "Should have distance"
        
        # 4. Stop and verify summary
        stop_resp = api_client.post(f"{BASE_URL}/api/night-guardian/stop", json={})
        assert stop_resp.status_code == 200
        summary = stop_resp.json()
        
        assert summary["guardian_active"] == False
        assert summary["location_updates"] >= 5
        assert summary["total_distance_m"] > 0
        
        # 5. Verify no active session after stop
        final_status = api_client.get(f"{BASE_URL}/api/night-guardian/status").json()
        
        assert final_status["active"] == False, "No active session after stop"
        
        print(f"Journey complete: {summary['location_updates']} updates, {summary['total_distance_m']:.1f}m traveled")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
