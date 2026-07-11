# Test Senior Profile Creation & Device Linking (POST /api/my/seniors, GET /api/my/seniors, POST/GET /api/my/seniors/{id}/devices)
# Testing self-service guardian-scoped senior and device management

import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
GUARDIAN_EMAIL = "nischint4parents@gmail.com"
GUARDIAN_PASSWORD = "secret123"
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"

class TestSeniorProfileAndDeviceLinking:
    """Tests for POST /api/my/seniors, GET /api/my/seniors, and device linking endpoints"""

    @pytest.fixture(scope="class")
    def session(self):
        """Shared requests session"""
        s = requests.Session()
        s.headers.update({"Content-Type": "application/json"})
        return s

    @pytest.fixture(scope="class")
    def guardian_token(self, session):
        """Get guardian authentication token"""
        response = session.post(f"{BASE_URL}/api/auth/login", json={
            "email": GUARDIAN_EMAIL,
            "password": GUARDIAN_PASSWORD
        })
        assert response.status_code == 200, f"Guardian login failed: {response.text}"
        token = response.json().get("access_token")
        assert token, "No access_token in response"
        return token

    @pytest.fixture(scope="class")
    def operator_token(self, session):
        """Get operator authentication token"""
        response = session.post(f"{BASE_URL}/api/auth/login", json={
            "email": OPERATOR_EMAIL,
            "password": OPERATOR_PASSWORD
        })
        assert response.status_code == 200, f"Operator login failed: {response.text}"
        return response.json().get("access_token")

    @pytest.fixture(scope="class")
    def auth_header(self, guardian_token):
        """Auth header for guardian"""
        return {"Authorization": f"Bearer {guardian_token}"}

    # ====== GET /api/my/seniors (list) ======

    def test_get_my_seniors_without_token_returns_401(self, session):
        """GET /api/my/seniors returns 401 without authentication token"""
        response = session.get(f"{BASE_URL}/api/my/seniors")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"

    def test_get_my_seniors_with_valid_token(self, session, auth_header):
        """GET /api/my/seniors returns 200 and list of seniors for authenticated guardian"""
        response = session.get(f"{BASE_URL}/api/my/seniors", headers=auth_header)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert isinstance(data, list), "Response should be a list"
        # Existing guardian may already have seniors from seeding
        if len(data) > 0:
            # Verify structure of senior object
            senior = data[0]
            assert "id" in senior
            assert "full_name" in senior
            assert "created_at" in senior

    # ====== POST /api/my/seniors (create) ======

    def test_create_senior_without_token_returns_401(self, session):
        """POST /api/my/seniors returns 401 without authentication"""
        response = session.post(f"{BASE_URL}/api/my/seniors", json={
            "full_name": "Test Senior",
            "age": 75
        })
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"

    def test_create_senior_with_valid_data(self, session, auth_header):
        """POST /api/my/seniors creates a senior under authenticated guardian"""
        unique_name = f"TEST_Senior_{uuid.uuid4().hex[:8]}"
        response = session.post(f"{BASE_URL}/api/my/seniors", headers=auth_header, json={
            "full_name": unique_name,
            "age": 78,
            "medical_notes": "Diabetes, mild hypertension"
        })
        assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.text}"
        
        data = response.json()
        # Validate response structure
        assert "id" in data, "Response should contain id"
        assert data["full_name"] == unique_name
        assert data["age"] == 78
        assert data["medical_notes"] == "Diabetes, mild hypertension"
        assert "created_at" in data
        
        # Store for later tests
        self.__class__.test_senior_id = data["id"]
        self.__class__.test_senior_name = unique_name

    def test_create_senior_without_age(self, session, auth_header):
        """POST /api/my/seniors works without optional age field"""
        unique_name = f"TEST_NoAge_{uuid.uuid4().hex[:8]}"
        response = session.post(f"{BASE_URL}/api/my/seniors", headers=auth_header, json={
            "full_name": unique_name
        })
        assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["full_name"] == unique_name
        assert data["age"] is None

    def test_create_senior_empty_name_returns_422(self, session, auth_header):
        """POST /api/my/seniors with empty name returns 422"""
        response = session.post(f"{BASE_URL}/api/my/seniors", headers=auth_header, json={
            "full_name": "",
            "age": 70
        })
        assert response.status_code == 422, f"Expected 422, got {response.status_code}"

    def test_create_senior_missing_name_returns_422(self, session, auth_header):
        """POST /api/my/seniors without full_name returns 422"""
        response = session.post(f"{BASE_URL}/api/my/seniors", headers=auth_header, json={
            "age": 75
        })
        assert response.status_code == 422, f"Expected 422, got {response.status_code}"

    # ====== Verify persistence with GET ======

    def test_created_senior_appears_in_list(self, session, auth_header):
        """GET /api/my/seniors includes the newly created senior"""
        response = session.get(f"{BASE_URL}/api/my/seniors", headers=auth_header)
        assert response.status_code == 200
        data = response.json()
        
        # Check that our test senior is in the list
        test_senior_name = getattr(self.__class__, 'test_senior_name', None)
        if test_senior_name:
            found = any(s["full_name"] == test_senior_name for s in data)
            assert found, f"Created senior '{test_senior_name}' not found in list"

    # ====== GET /api/my/seniors/{id}/devices (list devices) ======

    def test_get_devices_for_senior_without_token_returns_401(self, session):
        """GET /api/my/seniors/{id}/devices returns 401 without token"""
        senior_id = getattr(self.__class__, 'test_senior_id', str(uuid.uuid4()))
        response = session.get(f"{BASE_URL}/api/my/seniors/{senior_id}/devices")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"

    def test_get_devices_for_owned_senior(self, session, auth_header):
        """GET /api/my/seniors/{id}/devices returns devices for owned senior"""
        senior_id = getattr(self.__class__, 'test_senior_id', None)
        if not senior_id:
            pytest.skip("No test senior created yet")
        
        response = session.get(f"{BASE_URL}/api/my/seniors/{senior_id}/devices", headers=auth_header)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert isinstance(data, list), "Response should be a list"

    def test_get_devices_for_non_owned_senior_returns_404(self, session, auth_header):
        """GET /api/my/seniors/{non-owned-id}/devices returns 404"""
        fake_uuid = str(uuid.uuid4())
        response = session.get(f"{BASE_URL}/api/my/seniors/{fake_uuid}/devices", headers=auth_header)
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"

    # ====== POST /api/my/seniors/{id}/devices (link device) ======

    def test_link_device_without_token_returns_401(self, session):
        """POST /api/my/seniors/{id}/devices returns 401 without token"""
        senior_id = getattr(self.__class__, 'test_senior_id', str(uuid.uuid4()))
        response = session.post(f"{BASE_URL}/api/my/seniors/{senior_id}/devices", json={
            "device_identifier": "TEST-DEVICE-001"
        })
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"

    def test_link_device_to_owned_senior(self, session, auth_header):
        """POST /api/my/seniors/{id}/devices links a device to owned senior"""
        senior_id = getattr(self.__class__, 'test_senior_id', None)
        if not senior_id:
            pytest.skip("No test senior created yet")
        
        device_id = f"TEST-WBAND-{uuid.uuid4().hex[:8]}"
        response = session.post(f"{BASE_URL}/api/my/seniors/{senior_id}/devices", headers=auth_header, json={
            "device_identifier": device_id,
            "device_type": "wristband"
        })
        assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.text}"
        
        data = response.json()
        # Validate response structure
        assert "id" in data
        assert data["device_identifier"] == device_id
        assert data["device_type"] == "wristband"
        assert data["status"] == "offline", "Default status should be 'offline'"
        assert data["senior_id"] == senior_id
        assert "created_at" in data
        
        # Store for duplicate test
        self.__class__.test_device_identifier = device_id
        self.__class__.test_device_id = data["id"]

    def test_link_device_without_type(self, session, auth_header):
        """POST /api/my/seniors/{id}/devices works without optional device_type"""
        senior_id = getattr(self.__class__, 'test_senior_id', None)
        if not senior_id:
            pytest.skip("No test senior created yet")
        
        device_id = f"TEST-NOTYPE-{uuid.uuid4().hex[:8]}"
        response = session.post(f"{BASE_URL}/api/my/seniors/{senior_id}/devices", headers=auth_header, json={
            "device_identifier": device_id
        })
        assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["device_type"] is None

    def test_link_duplicate_device_returns_409(self, session, auth_header):
        """POST /api/my/seniors/{id}/devices rejects duplicate device_identifier (409)"""
        senior_id = getattr(self.__class__, 'test_senior_id', None)
        device_id = getattr(self.__class__, 'test_device_identifier', None)
        if not senior_id or not device_id:
            pytest.skip("No test senior or device created yet")
        
        response = session.post(f"{BASE_URL}/api/my/seniors/{senior_id}/devices", headers=auth_header, json={
            "device_identifier": device_id,  # Same as previously created
            "device_type": "pendant"
        })
        assert response.status_code == 409, f"Expected 409 for duplicate device, got {response.status_code}: {response.text}"
        assert "already exists" in response.json().get("detail", "").lower()

    def test_link_device_to_non_owned_senior_returns_404(self, session, auth_header):
        """POST /api/my/seniors/{non-owned-id}/devices returns 404"""
        fake_uuid = str(uuid.uuid4())
        response = session.post(f"{BASE_URL}/api/my/seniors/{fake_uuid}/devices", headers=auth_header, json={
            "device_identifier": f"TEST-FAKE-{uuid.uuid4().hex[:8]}"
        })
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"

    def test_link_device_empty_identifier_returns_422(self, session, auth_header):
        """POST /api/my/seniors/{id}/devices with empty device_identifier returns 422"""
        senior_id = getattr(self.__class__, 'test_senior_id', None)
        if not senior_id:
            pytest.skip("No test senior created yet")
        
        response = session.post(f"{BASE_URL}/api/my/seniors/{senior_id}/devices", headers=auth_header, json={
            "device_identifier": ""
        })
        assert response.status_code == 422, f"Expected 422, got {response.status_code}"

    # ====== Verify device persistence ======

    def test_linked_device_appears_in_list(self, session, auth_header):
        """GET /api/my/seniors/{id}/devices includes the newly linked device"""
        senior_id = getattr(self.__class__, 'test_senior_id', None)
        device_id = getattr(self.__class__, 'test_device_identifier', None)
        if not senior_id or not device_id:
            pytest.skip("No test senior or device created yet")
        
        response = session.get(f"{BASE_URL}/api/my/seniors/{senior_id}/devices", headers=auth_header)
        assert response.status_code == 200
        data = response.json()
        
        found = any(d["device_identifier"] == device_id for d in data)
        assert found, f"Linked device '{device_id}' not found in devices list"

    # ====== Regression Tests ======

    def test_guardian_login_still_works(self, session):
        """Regression: Guardian login still works"""
        response = session.post(f"{BASE_URL}/api/auth/login", json={
            "email": GUARDIAN_EMAIL,
            "password": GUARDIAN_PASSWORD
        })
        assert response.status_code == 200, f"Guardian login failed: {response.text}"
        data = response.json()
        assert data["role"] == "guardian"
        assert "access_token" in data

    def test_operator_login_still_works(self, session):
        """Regression: Operator login still works"""
        response = session.post(f"{BASE_URL}/api/auth/login", json={
            "email": OPERATOR_EMAIL,
            "password": OPERATOR_PASSWORD
        })
        assert response.status_code == 200, f"Operator login failed: {response.text}"
        data = response.json()
        assert data["role"] == "operator"
        assert "access_token" in data

    def test_operator_can_access_operator_console(self, session, operator_token):
        """Regression: Operator can access operator endpoints"""
        headers = {"Authorization": f"Bearer {operator_token}"}
        response = session.get(f"{BASE_URL}/api/operator/incidents", headers=headers)
        # Should return 200 with list of incidents
        assert response.status_code == 200, f"Operator incidents endpoint failed: {response.status_code}: {response.text}"
        assert isinstance(response.json(), list)

    def test_dashboard_summary_accessible(self, session, auth_header):
        """Regression: Dashboard summary endpoint works"""
        response = session.get(f"{BASE_URL}/api/dashboard/summary", headers=auth_header)
        assert response.status_code == 200, f"Dashboard summary failed: {response.status_code}"
        data = response.json()
        # Should have total_seniors key reflecting new senior count
        assert "total_seniors" in data
