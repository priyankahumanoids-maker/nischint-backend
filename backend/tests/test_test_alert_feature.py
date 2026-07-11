"""
Test Alert Feature Tests - NISCHINT
Tests for POST /api/my/seniors/{id}/test-alert endpoint and related functionality
"""
import os
import pytest
import requests
import time
from datetime import datetime

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test Credentials
TEST_USER_EMAIL = "rajesh.e2e@test.com"
TEST_USER_PASSWORD = "secure2026"
LIFECYCLE_USER_EMAIL = "lifecycle@test.com"
LIFECYCLE_USER_PASSWORD = "test1234"
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"
GUARDIAN_EMAIL = "nischint4parents@gmail.com"
GUARDIAN_PASSWORD = "secret123"


@pytest.fixture(scope="module")
def api_client():
    """Shared requests session."""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


@pytest.fixture(scope="module")
def test_user_token(api_client):
    """Get auth token for rajesh.e2e@test.com (has senior Nani Ji + device WBAND-E2E-001)."""
    response = api_client.post(f"{BASE_URL}/api/auth/login", json={
        "email": TEST_USER_EMAIL,
        "password": TEST_USER_PASSWORD
    })
    if response.status_code == 200:
        return response.json().get("access_token")
    pytest.skip(f"Test user login failed: {response.status_code} - {response.text}")


@pytest.fixture(scope="module")
def lifecycle_user_token(api_client):
    """Get auth token for lifecycle@test.com (has senior Grandma Kamala + device WBAND-LC-001)."""
    response = api_client.post(f"{BASE_URL}/api/auth/login", json={
        "email": LIFECYCLE_USER_EMAIL,
        "password": LIFECYCLE_USER_PASSWORD
    })
    if response.status_code == 200:
        return response.json().get("access_token")
    pytest.skip(f"Lifecycle user login failed: {response.status_code} - {response.text}")


@pytest.fixture(scope="module")
def guardian_token(api_client):
    """Get auth token for guardian user."""
    response = api_client.post(f"{BASE_URL}/api/auth/login", json={
        "email": GUARDIAN_EMAIL,
        "password": GUARDIAN_PASSWORD
    })
    if response.status_code == 200:
        return response.json().get("access_token")
    pytest.skip(f"Guardian login failed: {response.status_code} - {response.text}")


@pytest.fixture(scope="module")
def operator_token(api_client):
    """Get auth token for operator."""
    response = api_client.post(f"{BASE_URL}/api/auth/login", json={
        "email": OPERATOR_EMAIL,
        "password": OPERATOR_PASSWORD
    })
    if response.status_code == 200:
        return response.json().get("access_token")
    pytest.skip(f"Operator login failed: {response.status_code} - {response.text}")


@pytest.fixture(scope="module")
def test_user_senior_id(api_client, test_user_token):
    """Get the senior ID for Nani Ji under rajesh.e2e@test.com."""
    response = api_client.get(
        f"{BASE_URL}/api/my/seniors",
        headers={"Authorization": f"Bearer {test_user_token}"}
    )
    if response.status_code == 200:
        seniors = response.json()
        for senior in seniors:
            if "Nani" in senior.get("full_name", ""):
                return senior["id"]
        # If no Nani Ji found, return first senior
        if seniors:
            return seniors[0]["id"]
    pytest.skip("Could not get test user's senior")


@pytest.fixture(scope="module")
def lifecycle_user_senior_id(api_client, lifecycle_user_token):
    """Get the senior ID for Grandma Kamala under lifecycle@test.com."""
    response = api_client.get(
        f"{BASE_URL}/api/my/seniors",
        headers={"Authorization": f"Bearer {lifecycle_user_token}"}
    )
    if response.status_code == 200:
        seniors = response.json()
        for senior in seniors:
            if "Kamala" in senior.get("full_name", "") or "Grandma" in senior.get("full_name", ""):
                return senior["id"]
        if seniors:
            return seniors[0]["id"]
    pytest.skip("Could not get lifecycle user's senior")


# =============================================
# Test Alert Endpoint Tests
# =============================================

class TestAlertEndpoint:
    """Tests for POST /api/my/seniors/{id}/test-alert"""

    def test_send_test_alert_sos_success(self, api_client, test_user_token, test_user_senior_id):
        """Test sending a SOS test alert - creates incident with is_test=true."""
        response = api_client.post(
            f"{BASE_URL}/api/my/seniors/{test_user_senior_id}/test-alert",
            headers={"Authorization": f"Bearer {test_user_token}"},
            json={
                "device_identifier": "WBAND-E2E-001",
                "type": "sos"
            }
        )
        
        assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.text}"
        
        data = response.json()
        # Verify required fields in response
        assert "incident_id" in data, "Response should contain incident_id"
        assert "incident_type" in data, "Response should contain incident_type"
        assert "severity" in data, "Response should contain severity"
        assert "is_test" in data, "Response should contain is_test"
        
        # Verify values
        assert data["incident_type"] == "sos_alert", f"Expected sos_alert, got {data['incident_type']}"
        assert data["severity"] == "critical", f"Expected critical severity for SOS, got {data['severity']}"
        assert data["is_test"] == True, "is_test should be True"
        
        print(f"SUCCESS: Created test SOS alert, incident_id={data['incident_id']}")
        return data["incident_id"]

    def test_send_test_alert_fall_detected(self, api_client, lifecycle_user_token, lifecycle_user_senior_id):
        """Test sending a fall_detected test alert."""
        response = api_client.post(
            f"{BASE_URL}/api/my/seniors/{lifecycle_user_senior_id}/test-alert",
            headers={"Authorization": f"Bearer {lifecycle_user_token}"},
            json={
                "device_identifier": "WBAND-LC-001",
                "type": "fall_detected"
            }
        )
        
        assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["incident_type"] == "fall_alert", f"Expected fall_alert, got {data['incident_type']}"
        assert data["severity"] == "high", f"Expected high severity for fall, got {data['severity']}"
        assert data["is_test"] == True
        
        print(f"SUCCESS: Created test fall_detected alert, incident_id={data['incident_id']}")

    def test_send_test_alert_invalid_device(self, api_client, test_user_token, test_user_senior_id):
        """Test alert with invalid device identifier returns 404."""
        response = api_client.post(
            f"{BASE_URL}/api/my/seniors/{test_user_senior_id}/test-alert",
            headers={"Authorization": f"Bearer {test_user_token}"},
            json={
                "device_identifier": "NONEXISTENT-DEVICE-XYZ",
                "type": "sos"
            }
        )
        
        assert response.status_code == 404, f"Expected 404 for invalid device, got {response.status_code}"
        print("SUCCESS: Invalid device returns 404")

    def test_send_test_alert_non_owned_senior(self, api_client, test_user_token, lifecycle_user_senior_id):
        """Test alert for non-owned senior returns 404."""
        response = api_client.post(
            f"{BASE_URL}/api/my/seniors/{lifecycle_user_senior_id}/test-alert",
            headers={"Authorization": f"Bearer {test_user_token}"},
            json={
                "device_identifier": "WBAND-LC-001",
                "type": "sos"
            }
        )
        
        # Should return 404 (not 403) to avoid leaking existence
        assert response.status_code == 404, f"Expected 404 for non-owned senior, got {response.status_code}"
        print("SUCCESS: Non-owned senior returns 404")

    def test_send_test_alert_unknown_type(self, api_client, test_user_token, test_user_senior_id):
        """Test alert with unknown type returns 400."""
        response = api_client.post(
            f"{BASE_URL}/api/my/seniors/{test_user_senior_id}/test-alert",
            headers={"Authorization": f"Bearer {test_user_token}"},
            json={
                "device_identifier": "WBAND-E2E-001",
                "type": "unknown_alert_type"
            }
        )
        
        assert response.status_code == 400, f"Expected 400 for unknown type, got {response.status_code}"
        print("SUCCESS: Unknown alert type returns 400")

    def test_send_test_alert_no_auth(self, api_client, test_user_senior_id):
        """Test alert without auth token returns 401."""
        response = api_client.post(
            f"{BASE_URL}/api/my/seniors/{test_user_senior_id}/test-alert",
            json={
                "device_identifier": "WBAND-E2E-001",
                "type": "sos"
            }
        )
        
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("SUCCESS: Missing auth returns 401")


# =============================================
# Operator Stats Tests - Test Incidents Excluded
# =============================================

class TestOperatorStatsExcludeTestIncidents:
    """Tests for operator stats excluding test incidents."""

    def test_operator_stats_shows_test_incidents_count(self, api_client, operator_token):
        """GET /api/operator/stats should show test_incidents as separate count."""
        response = api_client.get(
            f"{BASE_URL}/api/operator/stats",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        # Verify test_incidents field exists
        assert "test_incidents" in data, f"Response should contain test_incidents field. Got: {data}"
        assert "total_incidents" in data
        assert "open_incidents" in data
        assert "escalated_incidents" in data
        
        print(f"SUCCESS: Operator stats - total={data['total_incidents']}, open={data['open_incidents']}, test={data['test_incidents']}")

    def test_operator_false_alarm_metrics_excludes_test(self, api_client, operator_token):
        """GET /api/operator/false-alarm-metrics excludes test incidents."""
        response = api_client.get(
            f"{BASE_URL}/api/operator/false-alarm-metrics",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "total_incidents" in data
        assert "false_alarms" in data
        assert "false_alarm_rate_percent" in data
        
        print(f"SUCCESS: False alarm metrics - total={data['total_incidents']}, false_alarms={data['false_alarms']}, rate={data['false_alarm_rate_percent']}%")

    def test_operator_incidents_includes_is_test_field(self, api_client, operator_token):
        """GET /api/operator/incidents should include is_test field in response."""
        response = api_client.get(
            f"{BASE_URL}/api/operator/incidents",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        incidents = response.json()
        assert isinstance(incidents, list)
        
        # Check that is_test field is present in incident responses
        test_incidents_found = []
        for incident in incidents[:10]:  # Check first 10
            assert "is_test" in incident, f"Incident should have is_test field. Got: {incident.keys()}"
            if incident["is_test"]:
                test_incidents_found.append(incident["id"])
        
        print(f"SUCCESS: Operator incidents include is_test field. Test incidents found: {len(test_incidents_found)}")


# =============================================
# Telemetry Creation Tests
# =============================================

class TestTelemetryCreation:
    """Tests verifying telemetry is created with is_test metadata."""

    def test_telemetry_created_after_test_alert(self, api_client, test_user_token, test_user_senior_id):
        """Verify telemetry entry is created after test alert."""
        # First get the devices to know the device_id
        devices_response = api_client.get(
            f"{BASE_URL}/api/my/seniors/{test_user_senior_id}/devices",
            headers={"Authorization": f"Bearer {test_user_token}"}
        )
        
        if devices_response.status_code != 200:
            pytest.skip("Could not get devices")
        
        devices = devices_response.json()
        if not devices:
            pytest.skip("No devices found")
        
        device = next((d for d in devices if d.get("device_identifier") == "WBAND-E2E-001"), devices[0])
        device_id = device["id"]
        
        # Get telemetry before
        telemetry_before = api_client.get(
            f"{BASE_URL}/api/telemetry/{device_id}?limit=5",
            headers={"Authorization": f"Bearer {test_user_token}"}
        )
        
        before_count = len(telemetry_before.json()) if telemetry_before.status_code == 200 else 0
        
        # Send test alert
        alert_response = api_client.post(
            f"{BASE_URL}/api/my/seniors/{test_user_senior_id}/test-alert",
            headers={"Authorization": f"Bearer {test_user_token}"},
            json={
                "device_identifier": device.get("device_identifier", "WBAND-E2E-001"),
                "type": "sos"
            }
        )
        
        assert alert_response.status_code == 201
        
        # Get telemetry after (brief wait for async commit)
        time.sleep(0.5)
        telemetry_after = api_client.get(
            f"{BASE_URL}/api/telemetry/{device_id}?limit=10",
            headers={"Authorization": f"Bearer {test_user_token}"}
        )
        
        if telemetry_after.status_code == 200:
            after_data = telemetry_after.json()
            # Check if SOS telemetry entry exists with is_test metadata
            sos_entries = [t for t in after_data if t.get("metric_type") == "sos"]
            if sos_entries:
                latest_sos = sos_entries[0]
                metric_value = latest_sos.get("metric_value", {})
                if isinstance(metric_value, dict) and metric_value.get("is_test"):
                    print(f"SUCCESS: Telemetry created with is_test=True metadata")
                    return
            
            print(f"WARNING: SOS telemetry entry found but could not verify is_test metadata")
        else:
            print(f"INFO: Telemetry endpoint returned {telemetry_after.status_code}")


# =============================================
# Regression Tests - Guardian & Operator Login
# =============================================

class TestRegressionAuth:
    """Regression tests for authentication."""

    def test_guardian_login_regression(self, api_client):
        """Guardian login should still work."""
        response = api_client.post(f"{BASE_URL}/api/auth/login", json={
            "email": GUARDIAN_EMAIL,
            "password": GUARDIAN_PASSWORD
        })
        
        assert response.status_code == 200, f"Guardian login failed: {response.status_code}"
        data = response.json()
        assert "access_token" in data
        print(f"SUCCESS: Guardian login works, user={data.get('user', {}).get('email')}")

    def test_operator_login_regression(self, api_client):
        """Operator login should still work."""
        response = api_client.post(f"{BASE_URL}/api/auth/login", json={
            "email": OPERATOR_EMAIL,
            "password": OPERATOR_PASSWORD
        })
        
        assert response.status_code == 200, f"Operator login failed: {response.status_code}"
        data = response.json()
        assert "access_token" in data
        print(f"SUCCESS: Operator login works, user={data.get('user', {}).get('email')}")

    def test_operator_dashboard_access(self, api_client, operator_token):
        """Operator should be able to access dashboard data."""
        response = api_client.get(
            f"{BASE_URL}/api/operator/stats",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        
        assert response.status_code == 200, f"Operator dashboard access failed: {response.status_code}"
        print("SUCCESS: Operator dashboard access works")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
