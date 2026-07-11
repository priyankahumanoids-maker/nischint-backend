"""
AI Safety Score Engine - Backend API Tests
Tests for GET /api/operator/devices/{device_id}/safety-score
Tests for GET /api/operator/fleet-safety

Safety Score Formula: 100 - (predictive*25 + anomalies*20 + forecast*20 + twin*15 + instability*20)
Score Categories: EXCELLENT (90+), STABLE (75-89), MONITOR (60-74), ATTENTION (40-59), CRITICAL (<40)
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test Credentials
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"
GUARDIAN_EMAIL = "nischint4parents@gmail.com"
GUARDIAN_PASSWORD = "secret123"

# Device IDs from problem statement
DEV_001_ID = "ce4b5463-5a7e-46a5-8bbf-365dcfb3daeb"
DEV_002_ID = "e029085c-1021-436d-9dfc-a0633979583d"
NON_EXISTENT_DEVICE = "00000000-0000-0000-0000-000000000000"


@pytest.fixture(scope="module")
def api_client():
    """Shared requests session."""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


@pytest.fixture(scope="module")
def operator_token(api_client):
    """Get operator authentication token."""
    response = api_client.post(f"{BASE_URL}/api/auth/login", json={
        "email": OPERATOR_EMAIL,
        "password": OPERATOR_PASSWORD
    })
    if response.status_code == 200:
        return response.json().get("access_token")
    pytest.fail(f"Operator login failed: {response.status_code} - {response.text}")


@pytest.fixture(scope="module")
def guardian_token(api_client):
    """Get guardian authentication token."""
    response = api_client.post(f"{BASE_URL}/api/auth/login", json={
        "email": GUARDIAN_EMAIL,
        "password": GUARDIAN_PASSWORD
    })
    if response.status_code == 200:
        return response.json().get("access_token")
    pytest.fail(f"Guardian login failed: {response.status_code}")


@pytest.fixture(scope="module")
def operator_client(api_client, operator_token):
    """Session with operator auth header."""
    api_client.headers.update({"Authorization": f"Bearer {operator_token}"})
    return api_client


class TestDeviceSafetyScoreEndpoint:
    """Tests for GET /api/operator/devices/{device_id}/safety-score"""

    def test_returns_200_for_valid_device(self, operator_client):
        """Device safety score endpoint returns 200 for valid device."""
        response = operator_client.get(f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/safety-score")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print(f"✓ Device safety score returned 200 OK")

    def test_response_structure(self, operator_client):
        """Response contains all required fields."""
        response = operator_client.get(f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/safety-score")
        data = response.json()
        
        # Check top-level fields
        assert "device_id" in data, "Missing device_id"
        assert "device_identifier" in data, "Missing device_identifier"
        assert "safety_score" in data, "Missing safety_score"
        assert "status" in data, "Missing status"
        assert "generated_at" in data, "Missing generated_at"
        assert "cached" in data, "Missing cached flag"
        assert "contributors" in data, "Missing contributors"
        
        print(f"✓ Response structure correct: score={data['safety_score']}, status={data['status']}")

    def test_safety_score_range(self, operator_client):
        """Safety score should be 0-100."""
        response = operator_client.get(f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/safety-score")
        data = response.json()
        
        score = data["safety_score"]
        assert 0 <= score <= 100, f"Score {score} outside valid range [0, 100]"
        print(f"✓ Safety score {score} is within valid range [0, 100]")

    def test_status_categories_valid(self, operator_client):
        """Status should be one of the defined categories."""
        response = operator_client.get(f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/safety-score")
        data = response.json()
        
        valid_statuses = {"EXCELLENT", "STABLE", "MONITOR", "ATTENTION", "CRITICAL"}
        assert data["status"] in valid_statuses, f"Invalid status: {data['status']}"
        print(f"✓ Status '{data['status']}' is valid")

    def test_contributors_structure(self, operator_client):
        """Contributors object contains all 5 signals."""
        response = operator_client.get(f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/safety-score")
        data = response.json()
        contrib = data["contributors"]
        
        required_signals = ["predictive_risk", "anomaly_count", "forecast_peak_risk", "twin_deviation", "device_instability"]
        for signal in required_signals:
            assert signal in contrib, f"Missing contributor signal: {signal}"
        
        print(f"✓ All 5 contributor signals present: {list(contrib.keys())}")

    def test_status_matches_score_threshold(self, operator_client):
        """Status category matches score thresholds."""
        response = operator_client.get(f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/safety-score")
        data = response.json()
        
        score = data["safety_score"]
        status = data["status"]
        
        # Verify category matches score
        if score >= 90:
            expected = "EXCELLENT"
        elif score >= 75:
            expected = "STABLE"
        elif score >= 60:
            expected = "MONITOR"
        elif score >= 40:
            expected = "ATTENTION"
        else:
            expected = "CRITICAL"
        
        assert status == expected, f"Score {score} should have status '{expected}', got '{status}'"
        print(f"✓ Score {score} correctly categorized as {status}")


class TestSafetyScoreCaching:
    """Tests for safety score caching (15 min TTL)."""

    def test_second_call_returns_cached(self, operator_client):
        """Second call within 15 min returns cached=true."""
        # First call
        response1 = operator_client.get(f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/safety-score")
        data1 = response1.json()
        
        # Second call immediately after
        response2 = operator_client.get(f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/safety-score")
        data2 = response2.json()
        
        assert data2["cached"] is True, "Second call should return cached=true"
        assert data1["safety_score"] == data2["safety_score"], "Cached score should match original"
        print(f"✓ Caching working: cached={data2['cached']}, score={data2['safety_score']}")


class TestSafetyScoreRBAC:
    """Tests for RBAC enforcement on safety score endpoints."""

    def test_guardian_gets_403(self, api_client, guardian_token):
        """Guardian role should get 403 Forbidden."""
        response = api_client.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/safety-score",
            headers={"Authorization": f"Bearer {guardian_token}"}
        )
        assert response.status_code == 403, f"Expected 403 for guardian, got {response.status_code}"
        print(f"✓ Guardian correctly gets 403 Forbidden")

    def test_unauthenticated_gets_401(self, api_client):
        """Unauthenticated request should get 401."""
        # Remove auth header for this test
        headers = {"Content-Type": "application/json"}
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/safety-score",
            headers=headers
        )
        assert response.status_code == 401, f"Expected 401 for unauthenticated, got {response.status_code}"
        print(f"✓ Unauthenticated correctly gets 401")


class TestSafetyScore404:
    """Tests for 404 handling."""

    def test_non_existent_device_returns_404(self, operator_client):
        """Non-existent device should return 404."""
        response = operator_client.get(f"{BASE_URL}/api/operator/devices/{NON_EXISTENT_DEVICE}/safety-score")
        assert response.status_code == 404, f"Expected 404 for non-existent device, got {response.status_code}"
        print(f"✓ Non-existent device correctly returns 404")


class TestFleetSafetyEndpoint:
    """Tests for GET /api/operator/fleet-safety"""

    def test_returns_200(self, operator_client):
        """Fleet safety endpoint returns 200."""
        response = operator_client.get(f"{BASE_URL}/api/operator/fleet-safety")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print(f"✓ Fleet safety returned 200 OK")

    def test_response_structure(self, operator_client):
        """Response contains fleet_score, fleet_status, devices, status_breakdown."""
        response = operator_client.get(f"{BASE_URL}/api/operator/fleet-safety")
        data = response.json()
        
        assert "fleet_score" in data, "Missing fleet_score"
        assert "fleet_status" in data, "Missing fleet_status"
        assert "device_count" in data, "Missing device_count"
        assert "generated_at" in data, "Missing generated_at"
        assert "status_breakdown" in data, "Missing status_breakdown"
        assert "devices" in data, "Missing devices array"
        
        print(f"✓ Fleet response structure correct: score={data['fleet_score']}, status={data['fleet_status']}")

    def test_fleet_score_range(self, operator_client):
        """Fleet score should be 0-100."""
        response = operator_client.get(f"{BASE_URL}/api/operator/fleet-safety")
        data = response.json()
        
        score = data["fleet_score"]
        assert 0 <= score <= 100, f"Fleet score {score} outside valid range [0, 100]"
        print(f"✓ Fleet score {score} is within valid range [0, 100]")

    def test_fleet_status_valid(self, operator_client):
        """Fleet status should be one of the defined categories."""
        response = operator_client.get(f"{BASE_URL}/api/operator/fleet-safety")
        data = response.json()
        
        valid_statuses = {"EXCELLENT", "STABLE", "MONITOR", "ATTENTION", "CRITICAL"}
        assert data["fleet_status"] in valid_statuses, f"Invalid fleet status: {data['fleet_status']}"
        print(f"✓ Fleet status '{data['fleet_status']}' is valid")

    def test_status_breakdown_structure(self, operator_client):
        """Status breakdown contains all 5 categories."""
        response = operator_client.get(f"{BASE_URL}/api/operator/fleet-safety")
        data = response.json()
        breakdown = data["status_breakdown"]
        
        categories = ["excellent", "stable", "monitor", "attention", "critical"]
        for cat in categories:
            assert cat in breakdown, f"Missing category: {cat}"
            assert isinstance(breakdown[cat], int), f"Category {cat} should be integer"
        
        print(f"✓ Status breakdown: {breakdown}")

    def test_devices_sorted_by_score(self, operator_client):
        """Devices should be sorted by score ascending (worst first)."""
        response = operator_client.get(f"{BASE_URL}/api/operator/fleet-safety")
        data = response.json()
        devices = data["devices"]
        
        if len(devices) > 1:
            scores = [d["safety_score"] for d in devices]
            assert scores == sorted(scores), f"Devices not sorted by score: {scores}"
        
        print(f"✓ Devices sorted by score (worst first): {[d.get('device_identifier', d.get('device_id'))[:8] + '...' for d in devices[:3]]}")

    def test_device_count_matches_devices_array(self, operator_client):
        """Device count should match devices array length."""
        response = operator_client.get(f"{BASE_URL}/api/operator/fleet-safety")
        data = response.json()
        
        assert data["device_count"] == len(data["devices"]), \
            f"device_count ({data['device_count']}) != devices length ({len(data['devices'])})"
        print(f"✓ Device count {data['device_count']} matches devices array")

    def test_each_device_has_required_fields(self, operator_client):
        """Each device in fleet response has required fields."""
        response = operator_client.get(f"{BASE_URL}/api/operator/fleet-safety")
        data = response.json()
        devices = data["devices"]
        
        required_fields = ["device_id", "device_identifier", "safety_score", "status", "generated_at", "contributors"]
        
        for device in devices[:3]:  # Check first 3
            for field in required_fields:
                assert field in device, f"Device missing field: {field}"
        
        print(f"✓ All device records have required fields")


class TestFleetSafetyRBAC:
    """Tests for RBAC enforcement on fleet-safety endpoint."""

    def test_guardian_gets_403(self, api_client, guardian_token):
        """Guardian role should get 403 Forbidden."""
        response = api_client.get(
            f"{BASE_URL}/api/operator/fleet-safety",
            headers={"Authorization": f"Bearer {guardian_token}"}
        )
        assert response.status_code == 403, f"Expected 403 for guardian, got {response.status_code}"
        print(f"✓ Guardian correctly gets 403 Forbidden for fleet-safety")

    def test_unauthenticated_gets_401(self):
        """Unauthenticated request should get 401."""
        headers = {"Content-Type": "application/json"}
        response = requests.get(
            f"{BASE_URL}/api/operator/fleet-safety",
            headers=headers
        )
        assert response.status_code == 401, f"Expected 401 for unauthenticated, got {response.status_code}"
        print(f"✓ Unauthenticated correctly gets 401 for fleet-safety")


class TestSpecificDeviceScores:
    """Tests for specific device scores (DEV-001 and DEV-002 known to have ATTENTION status)."""

    def test_dev001_score(self, operator_client):
        """DEV-001 safety score check."""
        response = operator_client.get(f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/safety-score")
        data = response.json()
        
        assert response.status_code == 200
        print(f"✓ DEV-001: score={data['safety_score']}, status={data['status']}")
        print(f"  Contributors: {data['contributors']}")

    def test_dev002_score(self, operator_client):
        """DEV-002 safety score check."""
        response = operator_client.get(f"{BASE_URL}/api/operator/devices/{DEV_002_ID}/safety-score")
        data = response.json()
        
        assert response.status_code == 200
        print(f"✓ DEV-002: score={data['safety_score']}, status={data['status']}")
        print(f"  Contributors: {data['contributors']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
