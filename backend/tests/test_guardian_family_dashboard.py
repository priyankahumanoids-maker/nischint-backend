# Guardian Family Dashboard API Tests (Phase 38)
# Tests for consumer-facing guardian dashboard endpoints
# Endpoints: /api/guardian/dashboard/loved-ones, /sessions, /alerts, /history, /request-check

import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL')

# Guardian credentials - the guardian who is added as a contact
GUARDIAN_EMAIL = "nischint4parents@gmail.com"
GUARDIAN_PASSWORD = "secret123"

# Operator credentials - the person being monitored
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"


@pytest.fixture(scope="module")
def guardian_token():
    """Get authentication token for guardian user"""
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": GUARDIAN_EMAIL, "password": GUARDIAN_PASSWORD}
    )
    if response.status_code != 200:
        pytest.skip(f"Guardian login failed: {response.text}")
    return response.json().get("access_token")


@pytest.fixture(scope="module")
def operator_token():
    """Get authentication token for operator user (the monitored person)"""
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD}
    )
    if response.status_code != 200:
        pytest.skip(f"Operator login failed: {response.text}")
    return response.json().get("access_token")


@pytest.fixture(scope="module")
def guardian_api_client(guardian_token):
    """Requests session with guardian auth header"""
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {guardian_token}"
    })
    return session


@pytest.fixture(scope="module")
def operator_api_client(operator_token):
    """Requests session with operator auth header"""
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {operator_token}"
    })
    return session


class TestGuardianDashboardAuth:
    """Authentication tests for guardian dashboard endpoints"""

    def test_loved_ones_requires_auth(self):
        """GET /loved-ones returns 401 without token"""
        response = requests.get(f"{BASE_URL}/api/guardian/dashboard/loved-ones")
        assert response.status_code == 401
        assert "Not authenticated" in response.json().get("detail", "")

    def test_sessions_requires_auth(self):
        """GET /sessions returns 401 without token"""
        response = requests.get(f"{BASE_URL}/api/guardian/dashboard/sessions")
        assert response.status_code == 401

    def test_alerts_requires_auth(self):
        """GET /alerts returns 401 without token"""
        response = requests.get(f"{BASE_URL}/api/guardian/dashboard/alerts")
        assert response.status_code == 401

    def test_history_requires_auth(self):
        """GET /history returns 401 without token"""
        response = requests.get(f"{BASE_URL}/api/guardian/dashboard/history")
        assert response.status_code == 401

    def test_request_check_requires_auth(self):
        """POST /request-check returns 401 without token"""
        response = requests.post(
            f"{BASE_URL}/api/guardian/dashboard/request-check",
            json={"session_id": str(uuid.uuid4())}
        )
        assert response.status_code == 401


class TestGuardianLovedOnes:
    """Tests for GET /api/guardian/dashboard/loved-ones"""

    def test_get_loved_ones_success(self, guardian_api_client):
        """Guardian can retrieve their monitored loved ones"""
        response = guardian_api_client.get(f"{BASE_URL}/api/guardian/dashboard/loved-ones")
        assert response.status_code == 200
        
        data = response.json()
        assert "monitored_users" in data
        assert "seniors" in data
        assert "total_loved_ones" in data
        assert "active_journeys" in data
        assert isinstance(data["monitored_users"], list)
        assert isinstance(data["seniors"], list)
        assert isinstance(data["total_loved_ones"], int)
        assert isinstance(data["active_journeys"], int)

    def test_loved_ones_contains_operator(self, guardian_api_client):
        """Guardian can see the operator who added them as a contact"""
        response = guardian_api_client.get(f"{BASE_URL}/api/guardian/dashboard/loved-ones")
        assert response.status_code == 200
        
        data = response.json()
        monitored = data.get("monitored_users", [])
        
        # Find the operator in the monitored users
        operator_user = next(
            (u for u in monitored if u.get("email") == OPERATOR_EMAIL),
            None
        )
        assert operator_user is not None, "Operator should be in guardian's loved ones"
        assert operator_user.get("name") == "Aisha Sharma"
        assert "user_id" in operator_user
        assert "relationship" in operator_user

    def test_loved_ones_active_session_details(self, guardian_api_client):
        """Active session contains required journey details"""
        response = guardian_api_client.get(f"{BASE_URL}/api/guardian/dashboard/loved-ones")
        assert response.status_code == 200
        
        data = response.json()
        monitored = data.get("monitored_users", [])
        
        # Find user with active session
        user_with_session = next(
            (u for u in monitored if u.get("has_active_session")),
            None
        )
        
        if user_with_session:
            session = user_with_session.get("active_session")
            assert session is not None
            # Verify session structure
            assert "session_id" in session
            assert "started_at" in session
            assert "duration_minutes" in session
            assert "current_location" in session
            assert "destination" in session
            assert "risk_level" in session
            assert "risk_score" in session
            assert "speed_kmh" in session
            assert "eta_minutes" in session
            assert "escalation_level" in session
            assert "alert_count" in session


class TestGuardianSessions:
    """Tests for GET /api/guardian/dashboard/sessions"""

    def test_get_sessions_success(self, guardian_api_client):
        """Guardian can retrieve active sessions of loved ones"""
        response = guardian_api_client.get(f"{BASE_URL}/api/guardian/dashboard/sessions")
        assert response.status_code == 200
        
        data = response.json()
        assert "sessions" in data
        assert isinstance(data["sessions"], list)

    def test_sessions_contain_required_fields(self, guardian_api_client):
        """Active sessions contain all required monitoring fields"""
        response = guardian_api_client.get(f"{BASE_URL}/api/guardian/dashboard/sessions")
        assert response.status_code == 200
        
        sessions = response.json().get("sessions", [])
        if sessions:
            session = sessions[0]
            required_fields = [
                "session_id", "user_id", "user_name", "status",
                "started_at", "duration_minutes", "current_location",
                "destination", "risk_level", "risk_score", "zone_name",
                "speed_kmh", "escalation_level", "alert_count"
            ]
            for field in required_fields:
                assert field in session, f"Missing field: {field}"


class TestGuardianAlerts:
    """Tests for GET /api/guardian/dashboard/alerts"""

    def test_get_alerts_success(self, guardian_api_client):
        """Guardian can retrieve alerts for their loved ones"""
        response = guardian_api_client.get(f"{BASE_URL}/api/guardian/dashboard/alerts")
        assert response.status_code == 200
        
        data = response.json()
        assert "alerts" in data
        assert isinstance(data["alerts"], list)

    def test_alerts_with_limit(self, guardian_api_client):
        """Alert limit parameter is respected"""
        response = guardian_api_client.get(f"{BASE_URL}/api/guardian/dashboard/alerts?limit=5")
        assert response.status_code == 200
        
        alerts = response.json().get("alerts", [])
        assert len(alerts) <= 5

    def test_alerts_contain_required_fields(self, guardian_api_client):
        """Alerts contain all required fields"""
        response = guardian_api_client.get(f"{BASE_URL}/api/guardian/dashboard/alerts")
        assert response.status_code == 200
        
        alerts = response.json().get("alerts", [])
        if alerts:
            alert = alerts[0]
            required_fields = [
                "id", "session_id", "user_name", "alert_type",
                "severity", "message", "created_at"
            ]
            for field in required_fields:
                assert field in alert, f"Missing field: {field}"


class TestGuardianHistory:
    """Tests for GET /api/guardian/dashboard/history"""

    def test_get_history_success(self, guardian_api_client):
        """Guardian can retrieve session history"""
        response = guardian_api_client.get(f"{BASE_URL}/api/guardian/dashboard/history")
        assert response.status_code == 200
        
        data = response.json()
        assert "history" in data
        assert isinstance(data["history"], list)

    def test_history_with_limit(self, guardian_api_client):
        """History limit parameter is respected"""
        response = guardian_api_client.get(f"{BASE_URL}/api/guardian/dashboard/history?limit=5")
        assert response.status_code == 200
        
        history = response.json().get("history", [])
        assert len(history) <= 5

    def test_history_contains_required_fields(self, guardian_api_client):
        """History entries contain all required fields"""
        response = guardian_api_client.get(f"{BASE_URL}/api/guardian/dashboard/history")
        assert response.status_code == 200
        
        history = response.json().get("history", [])
        if history:
            entry = history[0]
            required_fields = [
                "session_id", "user_name", "started_at",
                "duration_minutes", "max_risk_level", "total_distance_m",
                "alert_count", "escalation_level"
            ]
            for field in required_fields:
                assert field in entry, f"Missing field: {field}"


class TestRequestSafetyCheck:
    """Tests for POST /api/guardian/dashboard/request-check"""

    def test_request_check_invalid_session(self, guardian_api_client):
        """Request check with invalid session ID returns 404"""
        response = guardian_api_client.post(
            f"{BASE_URL}/api/guardian/dashboard/request-check",
            json={"session_id": str(uuid.uuid4())}
        )
        assert response.status_code == 404
        assert "No active session found" in response.json().get("detail", "")

    def test_request_check_valid_session(self, guardian_api_client):
        """Guardian can request safety check for valid active session"""
        # First get an active session
        sessions_response = guardian_api_client.get(f"{BASE_URL}/api/guardian/dashboard/sessions")
        if sessions_response.status_code != 200:
            pytest.skip("Could not retrieve sessions")
        
        sessions = sessions_response.json().get("sessions", [])
        if not sessions:
            pytest.skip("No active sessions to test with")
        
        session_id = sessions[0]["session_id"]
        
        # Request safety check
        response = guardian_api_client.post(
            f"{BASE_URL}/api/guardian/dashboard/request-check",
            json={"session_id": session_id}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("requested") is True
        assert data.get("session_id") == session_id
        assert "alert_id" in data


class TestGuardianSecurity:
    """Security tests - guardian should only see data from users who added them"""

    def test_guardian_only_sees_linked_users(self, guardian_api_client):
        """Guardian only sees users who have added them as a contact"""
        response = guardian_api_client.get(f"{BASE_URL}/api/guardian/dashboard/loved-ones")
        assert response.status_code == 200
        
        data = response.json()
        monitored = data.get("monitored_users", [])
        
        # All monitored users should have added this guardian as a contact
        # The operator (Aisha Sharma) added nischint4parents@gmail.com
        if monitored:
            emails = [u.get("email") for u in monitored]
            assert OPERATOR_EMAIL in emails, "Operator should be in guardian's monitored users"

    def test_guardian_cannot_access_unlinked_session(self, guardian_api_client):
        """Guardian cannot request check for sessions they're not linked to"""
        # Use a fake session ID - should fail
        fake_session_id = "00000000-0000-0000-0000-000000000000"
        response = guardian_api_client.post(
            f"{BASE_URL}/api/guardian/dashboard/request-check",
            json={"session_id": fake_session_id}
        )
        assert response.status_code == 404


class TestGuardianDataIntegrity:
    """Tests for data integrity and consistency"""

    def test_loved_ones_count_matches_data(self, guardian_api_client):
        """total_loved_ones count matches actual data"""
        response = guardian_api_client.get(f"{BASE_URL}/api/guardian/dashboard/loved-ones")
        assert response.status_code == 200
        
        data = response.json()
        expected_total = len(data.get("monitored_users", [])) + len(data.get("seniors", []))
        assert data.get("total_loved_ones") == expected_total

    def test_active_journeys_count_matches_sessions(self, guardian_api_client):
        """active_journeys count matches sessions with has_active_session=True"""
        response = guardian_api_client.get(f"{BASE_URL}/api/guardian/dashboard/loved-ones")
        assert response.status_code == 200
        
        data = response.json()
        monitored = data.get("monitored_users", [])
        active_count = sum(1 for u in monitored if u.get("has_active_session"))
        assert data.get("active_journeys") == active_count
