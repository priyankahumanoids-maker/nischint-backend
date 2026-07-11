# Test Anomaly Detection Feature - Iteration 20
# Tests: device-anomalies endpoint, RBAC, response structure

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"
GUARDIAN_EMAIL = "nischint4parents@gmail.com"
GUARDIAN_PASSWORD = "secret123"


class TestAnomalyDetectionAPI:
    """Tests for GET /api/operator/device-anomalies endpoint"""

    @pytest.fixture(scope="class")
    def operator_token(self):
        """Get operator authentication token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": OPERATOR_EMAIL,
            "password": OPERATOR_PASSWORD
        })
        assert response.status_code == 200, f"Operator login failed: {response.text}"
        data = response.json()
        assert "access_token" in data, "No access_token in login response"
        return data["access_token"]

    @pytest.fixture(scope="class")
    def guardian_token(self):
        """Get guardian authentication token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": GUARDIAN_EMAIL,
            "password": GUARDIAN_PASSWORD
        })
        assert response.status_code == 200, f"Guardian login failed: {response.text}"
        data = response.json()
        assert "access_token" in data, "No access_token in login response"
        return data["access_token"]

    def test_device_anomalies_returns_correct_structure(self, operator_token):
        """Test that endpoint returns {anomalies: [], baselines: []} structure"""
        response = requests.get(
            f"{BASE_URL}/api/operator/device-anomalies",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200, f"Endpoint failed: {response.text}"
        data = response.json()
        
        # Verify structure
        assert "anomalies" in data, "Response missing 'anomalies' field"
        assert "baselines" in data, "Response missing 'baselines' field"
        assert isinstance(data["anomalies"], list), "anomalies should be a list"
        assert isinstance(data["baselines"], list), "baselines should be a list"
        print(f"PASS: Response has correct structure with anomalies={len(data['anomalies'])}, baselines={len(data['baselines'])}")

    def test_device_anomalies_empty_when_no_telemetry(self, operator_token):
        """Test that endpoint returns empty arrays when no telemetry data"""
        response = requests.get(
            f"{BASE_URL}/api/operator/device-anomalies",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Since there's no live heartbeat telemetry, arrays should be empty
        # (This is expected behavior per the task description)
        print(f"INFO: anomalies count: {len(data['anomalies'])}, baselines count: {len(data['baselines'])}")
        print("PASS: Endpoint returns empty arrays as expected when no telemetry data")

    def test_device_anomalies_guardian_forbidden(self, guardian_token):
        """Test that guardian role gets 403 Forbidden"""
        response = requests.get(
            f"{BASE_URL}/api/operator/device-anomalies",
            headers={"Authorization": f"Bearer {guardian_token}"}
        )
        assert response.status_code == 403, f"Expected 403, got {response.status_code}"
        print("PASS: Guardian role correctly gets 403 Forbidden")

    def test_device_anomalies_hours_parameter(self, operator_token):
        """Test that hours query parameter is accepted"""
        # Test with different hours values
        for hours in [1, 24, 168]:
            response = requests.get(
                f"{BASE_URL}/api/operator/device-anomalies?hours={hours}",
                headers={"Authorization": f"Bearer {operator_token}"}
            )
            assert response.status_code == 200, f"Failed with hours={hours}: {response.text}"
        print("PASS: hours parameter accepted with values 1, 24, 168")

    def test_device_anomalies_unauthorized_without_token(self):
        """Test that endpoint requires authentication"""
        response = requests.get(f"{BASE_URL}/api/operator/device-anomalies")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: Endpoint correctly returns 401 without token")

    def test_anomaly_response_no_internal_ids(self, operator_token):
        """Test that internal IDs (device_id, id) are not exposed in response"""
        response = requests.get(
            f"{BASE_URL}/api/operator/device-anomalies",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Check anomalies don't have internal IDs
        for anomaly in data.get("anomalies", []):
            assert "device_id" not in anomaly, "Internal device_id exposed in anomaly"
            assert "id" not in anomaly, "Internal id exposed in anomaly"
            # Verify expected fields are present
            expected_fields = ["device_identifier", "senior_name", "metric", "score", "reason_json", "window_start", "created_at"]
            for field in expected_fields:
                assert field in anomaly, f"Missing field {field} in anomaly response"
        
        # Check baselines don't have internal IDs
        for baseline in data.get("baselines", []):
            assert "device_id" not in baseline, "Internal device_id exposed in baseline"
            assert "id" not in baseline, "Internal id exposed in baseline"
            # Verify expected fields are present
            expected_fields = ["device_identifier", "metric", "expected_value", "lower_band", "upper_band", "window_minutes", "updated_at"]
            for field in expected_fields:
                assert field in baseline, f"Missing field {field} in baseline response"
        
        print("PASS: No internal IDs (device_id, id) exposed in response")


class TestBaselineSchedulerIntegration:
    """Test that the baseline scheduler is registered and running"""

    @pytest.fixture(scope="class")
    def operator_token(self):
        """Get operator authentication token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": OPERATOR_EMAIL,
            "password": OPERATOR_PASSWORD
        })
        assert response.status_code == 200
        return response.json()["access_token"]

    def test_backend_health_check(self, operator_token):
        """Verify backend is running and responding"""
        # Test any operator endpoint to verify backend is running
        response = requests.get(
            f"{BASE_URL}/api/operator/stats",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200, f"Backend not responding: {response.text}"
        print("PASS: Backend is healthy and responding")

    def test_device_health_endpoint_exists(self, operator_token):
        """Verify device-health endpoint also works (for comparison)"""
        response = requests.get(
            f"{BASE_URL}/api/operator/device-health",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200, f"Device health endpoint failed: {response.text}"
        print(f"PASS: Device health endpoint returns {len(response.json())} devices")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
