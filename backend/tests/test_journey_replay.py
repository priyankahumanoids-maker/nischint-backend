"""
Journey Replay Feature Tests
Tests for GET /api/replay/sessions and GET /api/replay/{session_id}
Includes RBAC verification (admin/operator allowed, caregiver blocked)
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
ADMIN_EMAIL = "nischint4parents@gmail.com"
ADMIN_PASSWORD = "secret123"
OPERATOR_EMAIL = "operator1@nischint.com"
OPERATOR_PASSWORD = "secret123"
CAREGIVER_EMAIL = "caregiver1@nischint.com"
CAREGIVER_PASSWORD = "secret123"


@pytest.fixture(scope="module")
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


@pytest.fixture(scope="module")
def admin_token(api_client):
    """Get admin authentication token"""
    response = api_client.post(f"{BASE_URL}/api/auth/login", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD
    })
    if response.status_code == 200:
        data = response.json()
        return data.get("access_token") or data.get("token")
    pytest.skip(f"Admin authentication failed: {response.status_code} - {response.text}")


@pytest.fixture(scope="module")
def operator_token(api_client):
    """Get operator authentication token"""
    response = api_client.post(f"{BASE_URL}/api/auth/login", json={
        "email": OPERATOR_EMAIL,
        "password": OPERATOR_PASSWORD
    })
    if response.status_code == 200:
        data = response.json()
        return data.get("access_token") or data.get("token")
    pytest.skip(f"Operator authentication failed: {response.status_code} - {response.text}")


@pytest.fixture(scope="module")
def caregiver_token(api_client):
    """Get caregiver authentication token"""
    response = api_client.post(f"{BASE_URL}/api/auth/login", json={
        "email": CAREGIVER_EMAIL,
        "password": CAREGIVER_PASSWORD
    })
    if response.status_code == 200:
        data = response.json()
        return data.get("access_token") or data.get("token")
    pytest.skip(f"Caregiver authentication failed: {response.status_code} - {response.text}")


class TestHealthCheck:
    """Basic health check"""
    
    def test_api_root(self, api_client):
        """Test API root responds"""
        response = api_client.get(f"{BASE_URL}/api/")
        # API may return 200 or redirect
        assert response.status_code in [200, 307, 404], f"API root failed: {response.status_code}"


class TestAuthentication:
    """Verify test accounts can log in"""
    
    def test_admin_login(self, api_client):
        """Admin can log in"""
        response = api_client.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200, f"Admin login failed: {response.text}"
        data = response.json()
        assert "access_token" in data or "token" in data
    
    def test_operator_login(self, api_client):
        """Operator can log in"""
        response = api_client.post(f"{BASE_URL}/api/auth/login", json={
            "email": OPERATOR_EMAIL,
            "password": OPERATOR_PASSWORD
        })
        assert response.status_code == 200, f"Operator login failed: {response.text}"
        data = response.json()
        assert "access_token" in data or "token" in data
    
    def test_caregiver_login(self, api_client):
        """Caregiver can log in"""
        response = api_client.post(f"{BASE_URL}/api/auth/login", json={
            "email": CAREGIVER_EMAIL,
            "password": CAREGIVER_PASSWORD
        })
        assert response.status_code == 200, f"Caregiver login failed: {response.text}"


class TestReplaySessionsList:
    """Tests for GET /api/replay/sessions"""
    
    def test_sessions_admin_access(self, api_client, admin_token):
        """Admin can access replay sessions list"""
        response = api_client.get(
            f"{BASE_URL}/api/replay/sessions",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200, f"Failed: {response.status_code} - {response.text}"
        data = response.json()
        
        # Validate response structure
        assert "sessions" in data, "Response should contain 'sessions' array"
        sessions = data["sessions"]
        assert isinstance(sessions, list), "Sessions should be a list"
        
        # If we have sessions, validate structure of each session
        if len(sessions) > 0:
            session = sessions[0]
            # Required fields per main agent spec
            assert "id" in session, "Session should have 'id'"
            assert "user_name" in session, "Session should have 'user_name'"
            assert "risk_level" in session, "Session should have 'risk_level'"
            assert "alert_count" in session, "Session should have 'alert_count'"
            assert "started_at" in session, "Session should have 'started_at'"
            
            # Additional expected fields
            assert "user_id" in session
            assert "status" in session
            assert "total_distance_m" in session
    
    def test_sessions_operator_access(self, api_client, operator_token):
        """Operator can access replay sessions list"""
        response = api_client.get(
            f"{BASE_URL}/api/replay/sessions",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200, f"Failed: {response.status_code} - {response.text}"
        data = response.json()
        assert "sessions" in data
    
    def test_sessions_caregiver_blocked(self, api_client, caregiver_token):
        """Caregiver cannot access replay sessions (RBAC check)"""
        response = api_client.get(
            f"{BASE_URL}/api/replay/sessions",
            headers={"Authorization": f"Bearer {caregiver_token}"}
        )
        assert response.status_code == 403, f"Caregiver should be blocked, got: {response.status_code}"
    
    def test_sessions_unauthenticated_blocked(self, api_client):
        """Unauthenticated requests are blocked"""
        response = api_client.get(f"{BASE_URL}/api/replay/sessions")
        assert response.status_code in [401, 403], f"Unauthenticated should be blocked, got: {response.status_code}"
    
    def test_sessions_limit_parameter(self, api_client, admin_token):
        """Sessions endpoint respects limit parameter"""
        response = api_client.get(
            f"{BASE_URL}/api/replay/sessions?limit=5",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        sessions = data.get("sessions", [])
        assert len(sessions) <= 5, f"Should return at most 5 sessions, got {len(sessions)}"
    
    def test_sessions_returns_30_by_default(self, api_client, admin_token):
        """Default limit should be 30"""
        response = api_client.get(
            f"{BASE_URL}/api/replay/sessions",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        sessions = data.get("sessions", [])
        # Should be at most 30
        assert len(sessions) <= 30


class TestReplaySessionDetail:
    """Tests for GET /api/replay/{session_id}"""
    
    @pytest.fixture(scope="class")
    def session_id(self, api_client, admin_token):
        """Get a valid session ID from the list"""
        response = api_client.get(
            f"{BASE_URL}/api/replay/sessions?limit=1",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        if response.status_code == 200:
            sessions = response.json().get("sessions", [])
            if sessions:
                return sessions[0]["id"]
        pytest.skip("No sessions available for detail testing")
    
    def test_session_detail_admin_access(self, api_client, admin_token, session_id):
        """Admin can access session detail with event stream"""
        response = api_client.get(
            f"{BASE_URL}/api/replay/{session_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200, f"Failed: {response.status_code} - {response.text}"
        data = response.json()
        
        # Validate required fields per main agent spec
        assert "session_id" in data, "Response should have 'session_id'"
        assert "events" in data, "Response should have 'events' array"
        assert "risk_level" in data, "Response should have 'risk_level'"
        
        # Validate event structure
        events = data["events"]
        assert isinstance(events, list), "Events should be a list"
        
        if len(events) > 0:
            event = events[0]
            # Each event should have these fields
            assert "timestamp" in event, "Event should have 'timestamp'"
            assert "type" in event, "Event should have 'type'"
            assert "lat" in event, "Event should have 'lat'"
            assert "lng" in event, "Event should have 'lng'"
            assert "description" in event, "Event should have 'description'"
    
    def test_session_detail_operator_access(self, api_client, operator_token, session_id):
        """Operator can access session detail"""
        response = api_client.get(
            f"{BASE_URL}/api/replay/{session_id}",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200, f"Failed: {response.status_code} - {response.text}"
        data = response.json()
        assert "events" in data
        assert "session_id" in data
    
    def test_session_detail_caregiver_blocked(self, api_client, caregiver_token, session_id):
        """Caregiver cannot access session detail (RBAC check)"""
        response = api_client.get(
            f"{BASE_URL}/api/replay/{session_id}",
            headers={"Authorization": f"Bearer {caregiver_token}"}
        )
        assert response.status_code == 403, f"Caregiver should be blocked, got: {response.status_code}"
    
    def test_session_detail_invalid_id_returns_404(self, api_client, admin_token):
        """Invalid session ID returns 404"""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = api_client.get(
            f"{BASE_URL}/api/replay/{fake_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 404, f"Should return 404 for invalid ID, got: {response.status_code}"
    
    def test_session_detail_malformed_id_returns_error(self, api_client, admin_token):
        """Malformed session ID returns error (400 or 422)"""
        response = api_client.get(
            f"{BASE_URL}/api/replay/invalid-uuid-format",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        # Should return 400, 404, or 422 for invalid UUID format
        assert response.status_code in [400, 404, 422], f"Should return error for malformed ID, got: {response.status_code}"
    
    def test_session_detail_events_are_chronological(self, api_client, admin_token, session_id):
        """Events should be sorted chronologically"""
        response = api_client.get(
            f"{BASE_URL}/api/replay/{session_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        events = response.json().get("events", [])
        
        # Verify events are sorted by timestamp
        timestamps = [e.get("timestamp") for e in events if e.get("timestamp")]
        sorted_timestamps = sorted(timestamps)
        assert timestamps == sorted_timestamps, "Events should be sorted chronologically"


class TestReplayEventTypes:
    """Tests for event types in replay"""
    
    @pytest.fixture(scope="class")
    def session_with_events(self, api_client, admin_token):
        """Get a session with events for testing"""
        # Get a session
        response = api_client.get(
            f"{BASE_URL}/api/replay/sessions?limit=5",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        if response.status_code == 200:
            sessions = response.json().get("sessions", [])
            for s in sessions:
                # Get session detail
                detail_response = api_client.get(
                    f"{BASE_URL}/api/replay/{s['id']}",
                    headers={"Authorization": f"Bearer {admin_token}"}
                )
                if detail_response.status_code == 200:
                    data = detail_response.json()
                    if len(data.get("events", [])) > 0:
                        return data
        pytest.skip("No sessions with events available")
    
    def test_session_start_event_exists(self, session_with_events):
        """Session should have session_start event"""
        events = session_with_events.get("events", [])
        event_types = [e.get("type") for e in events]
        assert "session_start" in event_types, "Session should have session_start event"
    
    def test_movement_events_exist(self, session_with_events):
        """Session should have movement events"""
        events = session_with_events.get("events", [])
        event_types = [e.get("type") for e in events]
        assert "movement" in event_types, "Session should have movement events"
    
    def test_events_have_required_fields(self, session_with_events):
        """All events should have required fields"""
        events = session_with_events.get("events", [])
        for event in events:
            assert "type" in event, f"Event missing 'type': {event}"
            assert "lat" in event, f"Event missing 'lat': {event}"
            assert "lng" in event, f"Event missing 'lng': {event}"
    
    def test_events_have_icon_and_color(self, session_with_events):
        """Events should have icon and color for UI rendering"""
        events = session_with_events.get("events", [])
        for event in events:
            assert "icon" in event, f"Event missing 'icon': {event}"
            assert "color" in event, f"Event missing 'color': {event}"


class TestReplayResponseFields:
    """Tests for response field completeness"""
    
    @pytest.fixture(scope="class")
    def session_detail(self, api_client, admin_token):
        """Get a session detail for field testing"""
        response = api_client.get(
            f"{BASE_URL}/api/replay/sessions?limit=1",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        if response.status_code == 200:
            sessions = response.json().get("sessions", [])
            if sessions:
                detail_response = api_client.get(
                    f"{BASE_URL}/api/replay/{sessions[0]['id']}",
                    headers={"Authorization": f"Bearer {admin_token}"}
                )
                if detail_response.status_code == 200:
                    return detail_response.json()
        pytest.skip("Could not get session detail")
    
    def test_session_detail_has_duration(self, session_detail):
        """Session detail should include duration_seconds"""
        assert "duration_seconds" in session_detail, "Response should have 'duration_seconds'"
    
    def test_session_detail_has_event_count(self, session_detail):
        """Session detail should include event_count"""
        assert "event_count" in session_detail, "Response should have 'event_count'"
        # event_count should match events array length
        events_len = len(session_detail.get("events", []))
        assert session_detail["event_count"] == events_len
    
    def test_session_detail_has_alert_count(self, session_detail):
        """Session detail should include alert_count"""
        assert "alert_count" in session_detail, "Response should have 'alert_count'"
    
    def test_session_detail_has_total_distance(self, session_detail):
        """Session detail should include total_distance_m"""
        assert "total_distance_m" in session_detail, "Response should have 'total_distance_m'"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
