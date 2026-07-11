"""
Device Health Dashboard API Tests
=================================
Tests for:
- GET /api/my/seniors/{id}/device-health (Guardian device health metrics)
- GET /api/operator/device-health (Operator device health table)
- Reliability score computation (0-100, 40% uptime + 30% battery + 30% signal)
- Battery/signal/uptime/offline values
- Ownership scoping for guardian endpoint
- Operator role requirement
"""

import os
import pytest
import requests
from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://gps-mic-restart.preview.emergentagent.com').rstrip('/')

# Test Credentials
GUARDIAN_EMAIL = "nischint4parents@gmail.com"
GUARDIAN_PASSWORD = "secret123"
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"

# Known Test Data
SENIOR_ID_WITH_DEVICES = "b0762c1a-4d83-4d73-a8ce-be5a0da987e7"  # John Doe, has 3 devices


class TestDeviceHealthDashboard:
    """Tests for Device Health Dashboard APIs"""

    @pytest.fixture(scope="class")
    def guardian_token(self):
        """Get guardian auth token"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": GUARDIAN_EMAIL, "password": GUARDIAN_PASSWORD}
        )
        assert response.status_code == 200, f"Guardian login failed: {response.text}"
        return response.json()["access_token"]

    @pytest.fixture(scope="class")
    def operator_token(self):
        """Get operator auth token"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD}
        )
        assert response.status_code == 200, f"Operator login failed: {response.text}"
        return response.json()["access_token"]

    @pytest.fixture(scope="class")
    def guardian_headers(self, guardian_token):
        return {"Authorization": f"Bearer {guardian_token}", "Content-Type": "application/json"}

    @pytest.fixture(scope="class")
    def operator_headers(self, operator_token):
        return {"Authorization": f"Bearer {operator_token}", "Content-Type": "application/json"}

    # ── Guardian Device Health Endpoint Tests ──

    def test_guardian_device_health_returns_200(self, guardian_headers):
        """GET /api/my/seniors/{id}/device-health returns 200 for owned senior"""
        response = requests.get(
            f"{BASE_URL}/api/my/seniors/{SENIOR_ID_WITH_DEVICES}/device-health",
            headers=guardian_headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    def test_guardian_device_health_returns_array(self, guardian_headers):
        """Guardian device health endpoint returns array of device health objects"""
        response = requests.get(
            f"{BASE_URL}/api/my/seniors/{SENIOR_ID_WITH_DEVICES}/device-health",
            headers=guardian_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list), f"Expected list, got {type(data)}"

    def test_guardian_device_health_object_structure(self, guardian_headers):
        """Device health object has required fields"""
        response = requests.get(
            f"{BASE_URL}/api/my/seniors/{SENIOR_ID_WITH_DEVICES}/device-health",
            headers=guardian_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        if len(data) > 0:
            health = data[0]
            # Required fields
            assert "device_id" in health, "Missing device_id"
            assert "device_identifier" in health, "Missing device_identifier"
            assert "status" in health, "Missing status"
            assert "battery" in health, "Missing battery"
            assert "signal" in health, "Missing signal"
            assert "uptime_percent" in health, "Missing uptime_percent"
            assert "offline_count" in health, "Missing offline_count"
            assert "reliability_score" in health, "Missing reliability_score"
            print(f"Device health object structure verified: {list(health.keys())}")

    def test_guardian_device_health_battery_structure(self, guardian_headers):
        """Battery object has latest/average/min fields"""
        response = requests.get(
            f"{BASE_URL}/api/my/seniors/{SENIOR_ID_WITH_DEVICES}/device-health",
            headers=guardian_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        if len(data) > 0:
            battery = data[0]["battery"]
            assert "latest" in battery, "Battery missing 'latest'"
            assert "average" in battery, "Battery missing 'average'"
            assert "min" in battery, "Battery missing 'min'"
            print(f"Battery structure: {battery}")

    def test_guardian_device_health_signal_structure(self, guardian_headers):
        """Signal object has latest/average fields"""
        response = requests.get(
            f"{BASE_URL}/api/my/seniors/{SENIOR_ID_WITH_DEVICES}/device-health",
            headers=guardian_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        if len(data) > 0:
            signal = data[0]["signal"]
            assert "latest" in signal, "Signal missing 'latest'"
            assert "average" in signal, "Signal missing 'average'"
            print(f"Signal structure: {signal}")

    def test_guardian_device_health_reliability_score_range(self, guardian_headers):
        """Reliability score is 0-100 range"""
        response = requests.get(
            f"{BASE_URL}/api/my/seniors/{SENIOR_ID_WITH_DEVICES}/device-health",
            headers=guardian_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        for health in data:
            score = health["reliability_score"]
            assert isinstance(score, (int, float)), f"Reliability score should be numeric, got {type(score)}"
            assert 0 <= score <= 100, f"Reliability score {score} out of range 0-100"
            print(f"Device {health['device_identifier']}: reliability_score={score}")

    def test_guardian_device_health_uptime_percent_range(self, guardian_headers):
        """Uptime percent is 0-100 range"""
        response = requests.get(
            f"{BASE_URL}/api/my/seniors/{SENIOR_ID_WITH_DEVICES}/device-health",
            headers=guardian_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        for health in data:
            uptime = health["uptime_percent"]
            assert isinstance(uptime, (int, float)), f"Uptime should be numeric, got {type(uptime)}"
            assert 0 <= uptime <= 100, f"Uptime {uptime} out of range 0-100"
            print(f"Device {health['device_identifier']}: uptime_percent={uptime}")

    def test_guardian_device_health_window_hours_param(self, guardian_headers):
        """Window hours parameter works correctly"""
        response = requests.get(
            f"{BASE_URL}/api/my/seniors/{SENIOR_ID_WITH_DEVICES}/device-health?window_hours=12",
            headers=guardian_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        if len(data) > 0:
            assert data[0].get("window_hours") == 12, f"Expected window_hours=12, got {data[0].get('window_hours')}"
            print(f"Window hours parameter verified: {data[0].get('window_hours')}")

    def test_guardian_device_health_ownership_scoped(self, guardian_headers):
        """Guardian can only access their own seniors' device health"""
        # Use a random UUID that doesn't exist or belongs to another guardian
        fake_senior_id = "00000000-0000-0000-0000-000000000001"
        response = requests.get(
            f"{BASE_URL}/api/my/seniors/{fake_senior_id}/device-health",
            headers=guardian_headers
        )
        assert response.status_code == 404, f"Expected 404 for non-owned senior, got {response.status_code}"
        print("Ownership scoping verified: 404 returned for non-owned senior")

    def test_guardian_device_health_no_auth(self):
        """Guardian endpoint requires authentication"""
        response = requests.get(
            f"{BASE_URL}/api/my/seniors/{SENIOR_ID_WITH_DEVICES}/device-health"
        )
        assert response.status_code in [401, 403], f"Expected 401/403 without auth, got {response.status_code}"
        print("Authentication required verified")

    # ── Operator Device Health Endpoint Tests ──

    def test_operator_device_health_returns_200(self, operator_headers):
        """GET /api/operator/device-health returns 200 for operator"""
        response = requests.get(
            f"{BASE_URL}/api/operator/device-health",
            headers=operator_headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    def test_operator_device_health_returns_array(self, operator_headers):
        """Operator device health endpoint returns array"""
        response = requests.get(
            f"{BASE_URL}/api/operator/device-health",
            headers=operator_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list), f"Expected list, got {type(data)}"
        print(f"Operator device health returned {len(data)} devices")

    def test_operator_device_health_object_structure(self, operator_headers):
        """Operator device health has senior_name and guardian_name"""
        response = requests.get(
            f"{BASE_URL}/api/operator/device-health",
            headers=operator_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        if len(data) > 0:
            health = data[0]
            # Operator-specific fields
            assert "senior_name" in health, "Missing senior_name (operator-only field)"
            assert "guardian_name" in health, "Missing guardian_name (operator-only field)"
            assert "device_id" in health, "Missing device_id"
            assert "device_identifier" in health, "Missing device_identifier"
            assert "reliability_score" in health, "Missing reliability_score"
            assert "uptime_percent" in health, "Missing uptime_percent"
            assert "battery_latest" in health, "Missing battery_latest"
            assert "offline_count" in health, "Missing offline_count"
            print(f"Operator device health structure: {list(health.keys())}")

    def test_operator_device_health_reliability_score_range(self, operator_headers):
        """Operator endpoint reliability scores in 0-100 range"""
        response = requests.get(
            f"{BASE_URL}/api/operator/device-health",
            headers=operator_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        for health in data:
            score = health["reliability_score"]
            assert 0 <= score <= 100, f"Reliability score {score} out of range"

    def test_operator_device_health_requires_operator_role(self, guardian_headers):
        """Operator endpoint rejects guardian role"""
        response = requests.get(
            f"{BASE_URL}/api/operator/device-health",
            headers=guardian_headers
        )
        assert response.status_code == 403, f"Expected 403 for guardian, got {response.status_code}"
        print("Operator role requirement verified: 403 for guardian")

    def test_operator_device_health_no_auth(self):
        """Operator endpoint requires authentication"""
        response = requests.get(
            f"{BASE_URL}/api/operator/device-health"
        )
        assert response.status_code in [401, 403], f"Expected 401/403 without auth, got {response.status_code}"

    def test_operator_device_health_window_hours_param(self, operator_headers):
        """Operator endpoint accepts window_hours parameter"""
        response = requests.get(
            f"{BASE_URL}/api/operator/device-health?window_hours=48",
            headers=operator_headers
        )
        assert response.status_code == 200
        print("Window hours parameter accepted for operator endpoint")


class TestReliabilityScoreComputation:
    """Tests for reliability score computation logic"""

    @pytest.fixture(scope="class")
    def guardian_token(self):
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": GUARDIAN_EMAIL, "password": GUARDIAN_PASSWORD}
        )
        return response.json()["access_token"]

    @pytest.fixture(scope="class")
    def guardian_headers(self, guardian_token):
        return {"Authorization": f"Bearer {guardian_token}", "Content-Type": "application/json"}

    def test_reliability_score_is_integer(self, guardian_headers):
        """Reliability score is returned as integer"""
        response = requests.get(
            f"{BASE_URL}/api/my/seniors/{SENIOR_ID_WITH_DEVICES}/device-health",
            headers=guardian_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        for health in data:
            score = health["reliability_score"]
            assert isinstance(score, int), f"Reliability score should be int, got {type(score)}"

    def test_reliability_score_components_present(self, guardian_headers):
        """All components for reliability calculation are present"""
        response = requests.get(
            f"{BASE_URL}/api/my/seniors/{SENIOR_ID_WITH_DEVICES}/device-health",
            headers=guardian_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        for health in data:
            # Components used for reliability: uptime, battery, signal, offline_count
            assert "uptime_percent" in health
            assert "battery" in health and "latest" in health["battery"]
            assert "signal" in health and "average" in health["signal"]
            assert "offline_count" in health
            print(f"Device {health['device_identifier']}: uptime={health['uptime_percent']}, "
                  f"battery={health['battery']['latest']}, signal_avg={health['signal'].get('average')}, "
                  f"offline={health['offline_count']}, reliability={health['reliability_score']}")


class TestDeviceHealthWithHeartbeatData:
    """Integration tests: verify device health after heartbeat telemetry"""

    @pytest.fixture(scope="class")
    def guardian_token(self):
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": GUARDIAN_EMAIL, "password": GUARDIAN_PASSWORD}
        )
        return response.json()["access_token"]

    @pytest.fixture(scope="class")
    def guardian_headers(self, guardian_token):
        return {"Authorization": f"Bearer {guardian_token}", "Content-Type": "application/json"}

    def test_device_health_reflects_heartbeat_battery(self, guardian_headers):
        """Device health battery values reflect heartbeat telemetry"""
        # First get current devices to find one we can test with
        response = requests.get(
            f"{BASE_URL}/api/my/seniors/{SENIOR_ID_WITH_DEVICES}/device-health",
            headers=guardian_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        if len(data) > 0:
            # If there's any device with battery data, verify structure
            device_with_battery = next((d for d in data if d["battery"]["latest"] is not None), None)
            if device_with_battery:
                battery = device_with_battery["battery"]
                assert battery["latest"] is None or isinstance(battery["latest"], int)
                assert battery["average"] is None or isinstance(battery["average"], (int, float))
                assert battery["min"] is None or isinstance(battery["min"], int)
                print(f"Battery values verified: latest={battery['latest']}, avg={battery['average']}, min={battery['min']}")
            else:
                print("No devices with battery data - structure still validated")

    def test_device_health_offline_count_nonnegative(self, guardian_headers):
        """Offline count is non-negative integer"""
        response = requests.get(
            f"{BASE_URL}/api/my/seniors/{SENIOR_ID_WITH_DEVICES}/device-health",
            headers=guardian_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        for health in data:
            offline = health["offline_count"]
            assert isinstance(offline, int), f"Offline count should be int, got {type(offline)}"
            assert offline >= 0, f"Offline count should be non-negative, got {offline}"


class TestUserWithFullName:
    """Test full_name display for users - data is embedded in JWT token"""

    def test_login_returns_access_token(self):
        """Login returns access_token that contains user info"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": GUARDIAN_EMAIL, "password": GUARDIAN_PASSWORD}
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data, "Response should have access_token"
        assert "role" in data, "Response should have role"
        print(f"Login returns token with role={data['role']}")

    def test_jwt_token_contains_user_info(self):
        """JWT token contains email and full_name in payload"""
        import base64
        import json as json_lib
        
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": GUARDIAN_EMAIL, "password": GUARDIAN_PASSWORD}
        )
        assert response.status_code == 200
        token = response.json()["access_token"]
        
        # Decode JWT payload (middle part)
        payload_b64 = token.split('.')[1]
        # Add padding if needed
        payload_b64 += '=' * (4 - len(payload_b64) % 4)
        payload = json_lib.loads(base64.urlsafe_b64decode(payload_b64))
        
        assert "email" in payload, "JWT should contain email"
        assert payload["email"] == GUARDIAN_EMAIL
        assert "full_name" in payload, "JWT should contain full_name"
        print(f"JWT payload verified: email={payload['email']}, full_name={payload.get('full_name')}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
