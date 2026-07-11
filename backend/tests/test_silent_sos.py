"""
Silent SOS Emergency API Tests
Tests all emergency endpoints: trigger, location-update, cancel, resolve, active, status
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"
GUARDIAN_EMAIL = "nischint4parents@gmail.com"
GUARDIAN_PASSWORD = "secret123"


@pytest.fixture(scope="module")
def operator_token():
    """Get operator JWT token"""
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD}
    )
    assert response.status_code == 200, f"Operator login failed: {response.text}"
    data = response.json()
    assert "access_token" in data
    assert data.get("role") == "operator"
    return data["access_token"]


@pytest.fixture(scope="module")
def guardian_token():
    """Get guardian JWT token"""
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": GUARDIAN_EMAIL, "password": GUARDIAN_PASSWORD}
    )
    assert response.status_code == 200, f"Guardian login failed: {response.text}"
    data = response.json()
    assert "access_token" in data
    return data["access_token"]


@pytest.fixture
def auth_headers(operator_token):
    """Standard auth headers for operator"""
    return {
        "Authorization": f"Bearer {operator_token}",
        "Content-Type": "application/json"
    }


@pytest.fixture
def guardian_auth_headers(guardian_token):
    """Auth headers for guardian"""
    return {
        "Authorization": f"Bearer {guardian_token}",
        "Content-Type": "application/json"
    }


class TestAuthenticationEndpoints:
    """Test login endpoints"""

    def test_operator_login_success(self):
        """Operator login returns valid JWT with role=operator"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD}
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["role"] == "operator"
        assert data["token_type"] == "bearer"

    def test_guardian_login_success(self):
        """Guardian login returns valid JWT"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": GUARDIAN_EMAIL, "password": GUARDIAN_PASSWORD}
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["role"] in ["guardian", "user", "parent"]

    def test_invalid_credentials_rejected(self):
        """Invalid credentials return 401"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "fake@email.com", "password": "wrongpass"}
        )
        assert response.status_code in [401, 400, 404]


class TestSilentSOSTrigger:
    """Test POST /api/emergency/silent-sos endpoint"""

    def test_trigger_sos_success(self, auth_headers):
        """Trigger SOS with valid data returns event_id and status=active"""
        response = requests.post(
            f"{BASE_URL}/api/emergency/silent-sos",
            headers=auth_headers,
            json={
                "lat": 12.9716,
                "lng": 77.5946,
                "trigger_source": "shake",
                "cancel_pin": "TEST1234",
                "device_metadata": {"device": "pytest", "platform": "test"}
            }
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        # Verify response structure
        assert "event_id" in data
        assert data["status"] == "active"
        assert data["severity_level"] == 2  # distress level
        assert "guardians_notified" in data
        assert "created_at" in data
        assert "message" in data

    def test_trigger_sos_with_hidden_button(self, auth_headers):
        """Trigger SOS with hidden_button source"""
        response = requests.post(
            f"{BASE_URL}/api/emergency/silent-sos",
            headers=auth_headers,
            json={
                "lat": 12.9800,
                "lng": 77.6000,
                "trigger_source": "hidden_button",
                "cancel_pin": "PIN5678"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "active"
        
        # Clean up - resolve this event
        requests.post(
            f"{BASE_URL}/api/emergency/resolve",
            headers=auth_headers,
            json={"event_id": data["event_id"]}
        )

    def test_trigger_sos_without_auth_fails(self):
        """Trigger SOS without authentication returns 401"""
        response = requests.post(
            f"{BASE_URL}/api/emergency/silent-sos",
            json={
                "lat": 12.9716,
                "lng": 77.5946,
                "trigger_source": "manual"
            }
        )
        assert response.status_code == 401

    def test_double_trigger_creates_two_events(self, auth_headers):
        """Triggering SOS twice should create two separate events"""
        # First trigger
        resp1 = requests.post(
            f"{BASE_URL}/api/emergency/silent-sos",
            headers=auth_headers,
            json={"lat": 12.97, "lng": 77.59, "trigger_source": "shake", "cancel_pin": "DBL1"}
        )
        assert resp1.status_code == 200
        event1_id = resp1.json()["event_id"]
        
        # Second trigger
        resp2 = requests.post(
            f"{BASE_URL}/api/emergency/silent-sos",
            headers=auth_headers,
            json={"lat": 12.98, "lng": 77.60, "trigger_source": "shake", "cancel_pin": "DBL2"}
        )
        assert resp2.status_code == 200
        event2_id = resp2.json()["event_id"]
        
        # Verify different event IDs
        assert event1_id != event2_id
        
        # Clean up
        requests.post(f"{BASE_URL}/api/emergency/resolve", headers=auth_headers, json={"event_id": event1_id})
        requests.post(f"{BASE_URL}/api/emergency/resolve", headers=auth_headers, json={"event_id": event2_id})


class TestLocationUpdate:
    """Test POST /api/emergency/location-update endpoint"""

    def test_location_update_success(self, auth_headers):
        """Update location for active emergency"""
        # Create emergency first
        create_resp = requests.post(
            f"{BASE_URL}/api/emergency/silent-sos",
            headers=auth_headers,
            json={"lat": 12.9716, "lng": 77.5946, "trigger_source": "shake", "cancel_pin": "LOC123"}
        )
        assert create_resp.status_code == 200
        event_id = create_resp.json()["event_id"]
        
        # Update location
        update_resp = requests.post(
            f"{BASE_URL}/api/emergency/location-update",
            headers=auth_headers,
            json={"event_id": event_id, "lat": 12.9720, "lng": 77.5950}
        )
        assert update_resp.status_code == 200
        data = update_resp.json()
        assert data["event_id"] == event_id
        assert data["status"] == "active"
        assert data["location_updates"] == 2  # Initial + this update
        assert "latest" in data
        assert data["latest"]["lat"] == 12.972
        assert data["latest"]["lng"] == 77.595
        
        # Clean up
        requests.post(f"{BASE_URL}/api/emergency/resolve", headers=auth_headers, json={"event_id": event_id})

    def test_location_update_invalid_event_fails(self, auth_headers):
        """Location update with invalid event_id returns error"""
        response = requests.post(
            f"{BASE_URL}/api/emergency/location-update",
            headers=auth_headers,
            json={"event_id": "00000000-0000-0000-0000-000000000000", "lat": 12.97, "lng": 77.59}
        )
        assert response.status_code == 400
        assert "not found" in response.json()["detail"].lower()


class TestCancelSOS:
    """Test POST /api/emergency/cancel endpoint"""

    def test_cancel_sos_with_correct_pin(self, auth_headers):
        """Cancel SOS with correct PIN succeeds"""
        # Create emergency
        create_resp = requests.post(
            f"{BASE_URL}/api/emergency/silent-sos",
            headers=auth_headers,
            json={"lat": 12.97, "lng": 77.59, "trigger_source": "shake", "cancel_pin": "CANCEL123"}
        )
        event_id = create_resp.json()["event_id"]
        
        # Cancel with correct PIN
        cancel_resp = requests.post(
            f"{BASE_URL}/api/emergency/cancel",
            headers=auth_headers,
            json={"event_id": event_id, "cancel_pin": "CANCEL123"}
        )
        assert cancel_resp.status_code == 200
        data = cancel_resp.json()
        assert data["event_id"] == event_id
        assert data["status"] == "cancelled"
        assert "resolved_at" in data
        assert "message" in data

    def test_cancel_sos_with_wrong_pin_fails(self, auth_headers):
        """Cancel SOS with wrong PIN returns error"""
        # Create emergency
        create_resp = requests.post(
            f"{BASE_URL}/api/emergency/silent-sos",
            headers=auth_headers,
            json={"lat": 12.97, "lng": 77.59, "trigger_source": "shake", "cancel_pin": "CORRECT"}
        )
        event_id = create_resp.json()["event_id"]
        
        # Try to cancel with wrong PIN
        cancel_resp = requests.post(
            f"{BASE_URL}/api/emergency/cancel",
            headers=auth_headers,
            json={"event_id": event_id, "cancel_pin": "WRONGPIN"}
        )
        assert cancel_resp.status_code == 400
        assert "invalid" in cancel_resp.json()["detail"].lower()
        
        # Clean up
        requests.post(f"{BASE_URL}/api/emergency/resolve", headers=auth_headers, json={"event_id": event_id})

    def test_cancel_already_cancelled_fails(self, auth_headers):
        """Cannot cancel an already cancelled emergency"""
        # Create and cancel
        create_resp = requests.post(
            f"{BASE_URL}/api/emergency/silent-sos",
            headers=auth_headers,
            json={"lat": 12.97, "lng": 77.59, "trigger_source": "shake", "cancel_pin": "TWICE"}
        )
        event_id = create_resp.json()["event_id"]
        
        # First cancel
        requests.post(
            f"{BASE_URL}/api/emergency/cancel",
            headers=auth_headers,
            json={"event_id": event_id, "cancel_pin": "TWICE"}
        )
        
        # Try to cancel again
        second_cancel = requests.post(
            f"{BASE_URL}/api/emergency/cancel",
            headers=auth_headers,
            json={"event_id": event_id, "cancel_pin": "TWICE"}
        )
        assert second_cancel.status_code == 400
        assert "already" in second_cancel.json()["detail"].lower()


class TestResolveSOS:
    """Test POST /api/emergency/resolve endpoint"""

    def test_resolve_sos_success(self, auth_headers):
        """Resolve SOS returns success"""
        # Create emergency
        create_resp = requests.post(
            f"{BASE_URL}/api/emergency/silent-sos",
            headers=auth_headers,
            json={"lat": 12.97, "lng": 77.59, "trigger_source": "manual", "cancel_pin": "RES123"}
        )
        event_id = create_resp.json()["event_id"]
        
        # Resolve
        resolve_resp = requests.post(
            f"{BASE_URL}/api/emergency/resolve",
            headers=auth_headers,
            json={"event_id": event_id}
        )
        assert resolve_resp.status_code == 200
        data = resolve_resp.json()
        assert data["event_id"] == event_id
        assert data["status"] == "resolved"
        assert "resolved_at" in data
        assert "duration_seconds" in data
        assert "location_updates" in data

    def test_resolve_invalid_event_fails(self, auth_headers):
        """Resolve with invalid event_id returns error"""
        response = requests.post(
            f"{BASE_URL}/api/emergency/resolve",
            headers=auth_headers,
            json={"event_id": "00000000-0000-0000-0000-000000000000"}
        )
        assert response.status_code == 400


class TestGetActiveEmergencies:
    """Test GET /api/emergency/active endpoint"""

    def test_get_active_returns_list(self, auth_headers):
        """Get active emergencies returns list structure"""
        response = requests.get(
            f"{BASE_URL}/api/emergency/active",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "events" in data
        assert "count" in data
        assert isinstance(data["events"], list)
        assert isinstance(data["count"], int)

    def test_get_active_includes_event_details(self, auth_headers):
        """Active events include expected fields"""
        # Create emergency
        create_resp = requests.post(
            f"{BASE_URL}/api/emergency/silent-sos",
            headers=auth_headers,
            json={"lat": 12.97, "lng": 77.59, "trigger_source": "shake", "cancel_pin": "ACT123"}
        )
        event_id = create_resp.json()["event_id"]
        
        # Get active
        active_resp = requests.get(f"{BASE_URL}/api/emergency/active", headers=auth_headers)
        data = active_resp.json()
        
        # Find our event
        our_event = next((e for e in data["events"] if e["event_id"] == event_id), None)
        assert our_event is not None
        assert our_event["status"] == "active"
        assert "lat" in our_event
        assert "lng" in our_event
        assert "trigger_source" in our_event
        assert "severity_level" in our_event
        assert "guardians_notified" in our_event
        
        # Clean up
        requests.post(f"{BASE_URL}/api/emergency/resolve", headers=auth_headers, json={"event_id": event_id})


class TestGetEmergencyStatus:
    """Test GET /api/emergency/status/{event_id} endpoint"""

    def test_get_status_returns_full_details(self, auth_headers):
        """Get emergency status returns full details with location trail"""
        # Create emergency
        create_resp = requests.post(
            f"{BASE_URL}/api/emergency/silent-sos",
            headers=auth_headers,
            json={"lat": 12.97, "lng": 77.59, "trigger_source": "shake", "cancel_pin": "STAT123", "device_metadata": {"test": True}}
        )
        event_id = create_resp.json()["event_id"]
        
        # Add location update
        requests.post(
            f"{BASE_URL}/api/emergency/location-update",
            headers=auth_headers,
            json={"event_id": event_id, "lat": 12.98, "lng": 77.60}
        )
        
        # Get status
        status_resp = requests.get(
            f"{BASE_URL}/api/emergency/status/{event_id}",
            headers=auth_headers
        )
        assert status_resp.status_code == 200
        data = status_resp.json()
        
        # Verify all fields
        assert data["event_id"] == event_id
        assert data["status"] == "active"
        assert "user_id" in data
        assert "lat" in data
        assert "lng" in data
        assert "trigger_source" in data
        assert "severity_level" in data
        assert "guardians_notified" in data
        assert "location_trail" in data
        assert len(data["location_trail"]) >= 2
        assert "created_at" in data
        
        # Clean up
        requests.post(f"{BASE_URL}/api/emergency/resolve", headers=auth_headers, json={"event_id": event_id})

    def test_get_status_invalid_id_returns_404(self, auth_headers):
        """Get status with invalid event_id returns 404"""
        response = requests.get(
            f"{BASE_URL}/api/emergency/status/00000000-0000-0000-0000-000000000000",
            headers=auth_headers
        )
        assert response.status_code == 404


class TestFullSOSLifecycle:
    """Test complete SOS lifecycle flows"""

    def test_lifecycle_trigger_update_cancel(self, auth_headers):
        """Full lifecycle: trigger → location updates → cancel with PIN"""
        # 1. Trigger
        trigger_resp = requests.post(
            f"{BASE_URL}/api/emergency/silent-sos",
            headers=auth_headers,
            json={"lat": 12.97, "lng": 77.59, "trigger_source": "shake", "cancel_pin": "LIFE123"}
        )
        assert trigger_resp.status_code == 200
        event_id = trigger_resp.json()["event_id"]
        
        # 2. Location updates
        for i in range(3):
            update_resp = requests.post(
                f"{BASE_URL}/api/emergency/location-update",
                headers=auth_headers,
                json={"event_id": event_id, "lat": 12.97 + (i * 0.001), "lng": 77.59 + (i * 0.001)}
            )
            assert update_resp.status_code == 200
        
        # 3. Check active
        active_resp = requests.get(f"{BASE_URL}/api/emergency/active", headers=auth_headers)
        assert any(e["event_id"] == event_id for e in active_resp.json()["events"])
        
        # 4. Get details
        status_resp = requests.get(f"{BASE_URL}/api/emergency/status/{event_id}", headers=auth_headers)
        assert len(status_resp.json()["location_trail"]) >= 4  # Initial + 3 updates
        
        # 5. Cancel with PIN
        cancel_resp = requests.post(
            f"{BASE_URL}/api/emergency/cancel",
            headers=auth_headers,
            json={"event_id": event_id, "cancel_pin": "LIFE123"}
        )
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["status"] == "cancelled"

    def test_lifecycle_trigger_update_resolve(self, auth_headers):
        """Full lifecycle: trigger → location updates → resolve (by operator/guardian)"""
        # 1. Trigger
        trigger_resp = requests.post(
            f"{BASE_URL}/api/emergency/silent-sos",
            headers=auth_headers,
            json={"lat": 12.97, "lng": 77.59, "trigger_source": "hidden_button", "cancel_pin": "RESV123"}
        )
        event_id = trigger_resp.json()["event_id"]
        
        # 2. Location updates
        requests.post(
            f"{BASE_URL}/api/emergency/location-update",
            headers=auth_headers,
            json={"event_id": event_id, "lat": 12.98, "lng": 77.60}
        )
        
        # 3. Resolve
        resolve_resp = requests.post(
            f"{BASE_URL}/api/emergency/resolve",
            headers=auth_headers,
            json={"event_id": event_id}
        )
        assert resolve_resp.status_code == 200
        assert resolve_resp.json()["status"] == "resolved"
        
        # 4. Verify no longer in active list
        active_resp = requests.get(f"{BASE_URL}/api/emergency/active", headers=auth_headers)
        assert not any(e["event_id"] == event_id for e in active_resp.json()["events"])


class TestGuardianAccess:
    """Test guardian user access to emergency endpoints"""

    def test_guardian_can_trigger_sos(self, guardian_auth_headers):
        """Guardian can trigger SOS for themselves"""
        response = requests.post(
            f"{BASE_URL}/api/emergency/silent-sos",
            headers=guardian_auth_headers,
            json={"lat": 12.97, "lng": 77.59, "trigger_source": "shake", "cancel_pin": "GUARD123"}
        )
        assert response.status_code == 200
        event_id = response.json()["event_id"]
        
        # Clean up
        requests.post(
            f"{BASE_URL}/api/emergency/resolve",
            headers=guardian_auth_headers,
            json={"event_id": event_id}
        )

    def test_guardian_can_view_own_active(self, guardian_auth_headers):
        """Guardian can view their own active emergencies"""
        response = requests.get(
            f"{BASE_URL}/api/emergency/active",
            headers=guardian_auth_headers
        )
        assert response.status_code == 200
        assert "events" in response.json()
