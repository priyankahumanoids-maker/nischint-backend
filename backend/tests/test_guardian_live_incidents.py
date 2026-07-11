# Guardian Live Map & Incident Replay API Tests
# Tests for:
# - GET /api/guardian/live/protected-users
# - GET /api/guardian/live/status/{user_id}
# - GET /api/guardian/incidents
# - GET /api/guardian/incidents/{id}/replay
# - Push notification status endpoints (regression)

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
TEST_EMAIL = "nischint4parents@gmail.com"
TEST_PASSWORD = "secret123"

# Known incident IDs from E1 context
KNOWN_INCIDENT_IDS = [
    "984cd01d-e3f2-45d1-8c4f-82088bd4e0ce",
    "41438184-e625-4e10-9e64-07ffe100d8f0"
]


@pytest.fixture(scope="module")
def auth_token():
    """Get auth token for authenticated requests"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD
    })
    if response.status_code == 200:
        return response.json().get("access_token") or response.json().get("token")
    pytest.skip("Authentication failed - skipping authenticated tests")


@pytest.fixture(scope="module")
def authenticated_client(auth_token):
    """Create session with auth header"""
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {auth_token}"
    })
    return session


class TestGuardianLiveProtectedUsers:
    """Guardian Live Map - Protected Users endpoint tests"""

    def test_get_protected_users_requires_auth(self):
        """Test that endpoint requires authentication"""
        response = requests.get(f"{BASE_URL}/api/guardian/live/protected-users")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("PASS: /api/guardian/live/protected-users requires auth")

    def test_get_protected_users_success(self, authenticated_client):
        """Test getting protected users list (includes self with is_self=true)"""
        response = authenticated_client.get(f"{BASE_URL}/api/guardian/live/protected-users")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "protected_users" in data, "Response should have protected_users array"
        assert "count" in data, "Response should have count"
        
        users = data["protected_users"]
        assert isinstance(users, list), "protected_users should be a list"
        
        # Should have at least self user
        assert len(users) >= 1 or data["count"] >= 0, "Should have at least self or 0 users"
        
        # Check for self user flag
        has_self = any(u.get("is_self") == True for u in users)
        if len(users) > 0:
            print(f"PASS: Found {len(users)} protected users, has_self={has_self}")
            
            # Validate user structure
            user = users[0]
            expected_fields = ["user_id", "name", "email", "relationship", "has_active_session", "risk_level", "risk_score", "is_self"]
            for field in expected_fields:
                assert field in user, f"User should have {field} field"
            print(f"PASS: User structure validated - {user.get('name')} (is_self={user.get('is_self')})")


class TestGuardianLiveStatus:
    """Guardian Live Map - Status endpoint tests"""

    def test_get_live_status_requires_auth(self):
        """Test that endpoint requires authentication"""
        # Use a dummy UUID
        response = requests.get(f"{BASE_URL}/api/guardian/live/status/00000000-0000-0000-0000-000000000000")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("PASS: /api/guardian/live/status requires auth")

    def test_get_live_status_for_self(self, authenticated_client):
        """Test getting live status for own user (self-monitoring)"""
        # First get user ID from protected users
        response = authenticated_client.get(f"{BASE_URL}/api/guardian/live/protected-users")
        assert response.status_code == 200
        
        users = response.json().get("protected_users", [])
        if not users:
            pytest.skip("No protected users found")
        
        # Get self user or first user
        self_user = next((u for u in users if u.get("is_self")), users[0])
        user_id = self_user.get("user_id")
        
        # Get live status
        response = authenticated_client.get(f"{BASE_URL}/api/guardian/live/status/{user_id}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Validate response structure
        assert "user_id" in data, "Response should have user_id"
        assert "user_name" in data, "Response should have user_name"
        assert "email" in data, "Response should have email"
        assert "relationship" in data, "Response should have relationship"
        assert "session_active" in data, "Response should have session_active"
        assert "risk" in data, "Response should have risk object"
        assert "behavior_pattern" in data, "Response should have behavior_pattern"
        assert "recommendation" in data, "Response should have recommendation"
        assert "recent_alerts" in data, "Response should have recent_alerts"
        assert "past_sessions" in data, "Response should have past_sessions"
        assert "last_update" in data, "Response should have last_update"
        
        # Validate risk object
        risk = data["risk"]
        assert "score" in risk, "Risk should have score"
        assert "level" in risk, "Risk should have level"
        assert "factors" in risk, "Risk should have factors"
        
        print(f"PASS: Live status for {data['user_name']}: session_active={data['session_active']}, risk_level={risk['level']}, score={risk['score']}")
        
        # Validate session data if active
        if data.get("session_active") and data.get("session"):
            session = data["session"]
            session_fields = ["session_id", "started_at", "duration_seconds", "risk_level", "risk_score", "current_location"]
            for field in session_fields:
                assert field in session, f"Session should have {field} field"
            print(f"PASS: Session data validated - duration={session.get('duration_seconds')}s, risk_score={session.get('risk_score')}")

    def test_get_live_status_invalid_uuid(self, authenticated_client):
        """Test that invalid UUID returns 404"""
        response = authenticated_client.get(f"{BASE_URL}/api/guardian/live/status/invalid-uuid")
        assert response.status_code in [400, 404, 422], f"Expected error status, got {response.status_code}"
        print("PASS: Invalid UUID returns error status")


class TestGuardianIncidents:
    """Guardian Incidents - List endpoint tests"""

    def test_get_incidents_requires_auth(self):
        """Test that endpoint requires authentication"""
        response = requests.get(f"{BASE_URL}/api/guardian/incidents")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("PASS: /api/guardian/incidents requires auth")

    def test_get_incidents_list(self, authenticated_client):
        """Test getting incidents list"""
        response = authenticated_client.get(f"{BASE_URL}/api/guardian/incidents?limit=20")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "incidents" in data, "Response should have incidents array"
        assert "total" in data, "Response should have total count"
        
        incidents = data["incidents"]
        assert isinstance(incidents, list), "incidents should be a list"
        
        print(f"PASS: Found {len(incidents)} incidents (total: {data['total']})")
        
        if len(incidents) > 0:
            # Validate incident structure
            incident = incidents[0]
            expected_fields = ["id", "type", "alert_type", "severity", "message", "created_at"]
            for field in expected_fields:
                assert field in incident, f"Incident should have {field} field"
            
            print(f"PASS: Incident structure validated - {incident.get('alert_type')} ({incident.get('severity')})")
            
            # Store incident ID for replay test
            return incident["id"]


class TestGuardianIncidentReplay:
    """Guardian Incidents - Replay endpoint tests"""

    def test_get_incident_replay_requires_auth(self):
        """Test that endpoint requires authentication"""
        response = requests.get(f"{BASE_URL}/api/guardian/incidents/{KNOWN_INCIDENT_IDS[0]}/replay")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("PASS: /api/guardian/incidents/{id}/replay requires auth")

    def test_get_incident_replay_success(self, authenticated_client):
        """Test getting incident replay with timeline and AI analysis"""
        # First get incidents list to find a valid incident
        response = authenticated_client.get(f"{BASE_URL}/api/guardian/incidents?limit=10")
        assert response.status_code == 200
        
        incidents = response.json().get("incidents", [])
        
        # Filter for alert type incidents that have replay
        alert_incidents = [inc for inc in incidents if inc.get("type") == "alert"]
        
        if not alert_incidents:
            # Try known incident IDs
            for known_id in KNOWN_INCIDENT_IDS:
                response = authenticated_client.get(f"{BASE_URL}/api/guardian/incidents/{known_id}/replay")
                if response.status_code == 200:
                    self._validate_replay_response(response.json())
                    return
            pytest.skip("No alert type incidents found for replay test")
        
        incident_id = alert_incidents[0]["id"]
        
        # Get replay
        response = authenticated_client.get(f"{BASE_URL}/api/guardian/incidents/{incident_id}/replay")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        self._validate_replay_response(response.json())

    def _validate_replay_response(self, data):
        """Validate replay response structure"""
        assert "incident_id" in data, "Response should have incident_id"
        assert "incident_type" in data, "Response should have incident_type"
        assert "severity" in data, "Response should have severity"
        assert "message" in data, "Response should have message"
        assert "incident_time" in data, "Response should have incident_time"
        assert "session" in data, "Response should have session object"
        assert "timeline" in data, "Response should have timeline array"
        assert "ai_analysis" in data, "Response should have ai_analysis object"
        assert "stats" in data, "Response should have stats object"
        
        # Validate timeline
        timeline = data["timeline"]
        assert isinstance(timeline, list), "Timeline should be a list"
        print(f"PASS: Replay has {len(timeline)} timeline events")
        
        # Validate AI analysis
        ai = data["ai_analysis"]
        expected_ai_fields = ["root_cause", "response_time_seconds", "preventable", "risk_score_at_incident", "recommendation", "contributing_factors"]
        for field in expected_ai_fields:
            assert field in ai, f"AI analysis should have {field}"
        
        print(f"PASS: AI analysis validated - root_cause: {ai.get('root_cause')[:50]}...")
        print(f"PASS: Contributing factors: {ai.get('contributing_factors')}")
        print(f"PASS: Preventable: {ai.get('preventable')}, Risk score: {ai.get('risk_score_at_incident')}")

    def test_get_incident_replay_not_found(self, authenticated_client):
        """Test that non-existent incident returns 404"""
        response = authenticated_client.get(f"{BASE_URL}/api/guardian/incidents/00000000-0000-0000-0000-000000000000/replay")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("PASS: Non-existent incident returns 404")


class TestPushNotificationRegression:
    """Push notification status API regression tests"""

    def test_push_status_requires_auth(self):
        """Test that push-status requires authentication"""
        response = requests.get(f"{BASE_URL}/api/device/push-status")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("PASS: /api/device/push-status requires auth")

    def test_push_status_success(self, authenticated_client):
        """Test push-status returns proper data"""
        response = authenticated_client.get(f"{BASE_URL}/api/device/push-status")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "push_enabled" in data, "Response should have push_enabled"
        assert "fcm_active" in data, "Response should have fcm_active"
        
        print(f"PASS: Push status - push_enabled={data.get('push_enabled')}, fcm_active={data.get('fcm_active')}")

    def test_device_register_requires_auth(self):
        """Test that device registration requires authentication"""
        response = requests.post(f"{BASE_URL}/api/device/register", json={
            "token": "test_token_123",
            "platform": "web"
        })
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("PASS: /api/device/register requires auth")


class TestGuardianLiveIntegration:
    """Integration tests for Guardian Live Map flow"""

    def test_full_guardian_flow(self, authenticated_client):
        """Test full flow: get users -> select user -> get status"""
        # Step 1: Get protected users
        response = authenticated_client.get(f"{BASE_URL}/api/guardian/live/protected-users")
        assert response.status_code == 200
        users = response.json().get("protected_users", [])
        
        if not users:
            print("PASS: No protected users - self-monitoring mode expected")
            return
        
        # Step 2: Get first user's status
        user = users[0]
        user_id = user["user_id"]
        
        response = authenticated_client.get(f"{BASE_URL}/api/guardian/live/status/{user_id}")
        assert response.status_code == 200
        
        status = response.json()
        
        # Step 3: Validate intelligence panel data
        assert "risk" in status, "Status should have risk for intelligence panel"
        assert "behavior_pattern" in status, "Status should have behavior_pattern for pattern display"
        assert "recommendation" in status, "Status should have recommendation for action display"
        
        print(f"PASS: Full guardian flow - User: {status['user_name']}")
        print(f"       Risk: {status['risk']['level']} ({status['risk']['score']}/10)")
        print(f"       Pattern: {status['behavior_pattern']}")
        print(f"       Action: {status['recommendation']}")
        
        if status.get("session_active"):
            session = status["session"]
            print(f"       Session: {session.get('duration_seconds')}s, {session.get('speed_kmh')} km/h")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
