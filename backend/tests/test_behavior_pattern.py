"""
Backend Tests for Behavior Pattern AI API
Tests GET /api/operator/devices/{device_id}/behavior-pattern endpoint

Features tested:
- Returns correct JSON structure with current_risk, baseline_profile, recent_anomalies
- current_risk includes score (0-1), status (normal/mild/moderate/critical), reason
- baseline_profile is array of {hour, avg_movement, avg_interaction_rate, sample_count}
- recent_anomalies has behavior_score, anomaly_type, reason, created_at
- Includes inactivity_minutes and last_heartbeat
- Returns 404 for non-existent device
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Known device ID with behavior data
DEVICE_ID_WITH_DATA = "ce4b5463-5a7e-46a5-8bbf-365dcfb3daeb"
NON_EXISTENT_DEVICE_ID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture(scope="module")
def operator_token():
    """Get operator authentication token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "operator@nischint.com",
        "password": "operator123"
    })
    if response.status_code == 200:
        return response.json().get("access_token")
    pytest.skip("Operator authentication failed")


@pytest.fixture(scope="module")
def auth_headers(operator_token):
    """Headers with authentication token"""
    return {"Authorization": f"Bearer {operator_token}"}


class TestBehaviorPatternEndpoint:
    """Tests for GET /api/operator/devices/{device_id}/behavior-pattern"""

    def test_returns_correct_json_structure(self, auth_headers):
        """Test endpoint returns all required top-level fields"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEVICE_ID_WITH_DATA}/behavior-pattern?window_hours=168",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        # Verify top-level fields exist
        assert "device_id" in data
        assert "device_identifier" in data
        assert "current_risk" in data
        assert "last_heartbeat" in data
        assert "inactivity_minutes" in data
        assert "baseline_profile" in data
        assert "recent_anomalies" in data
        assert "total_anomalies_in_window" in data
        print(f"PASS - All required fields present: device_id, device_identifier, current_risk, baseline_profile, recent_anomalies, inactivity_minutes, last_heartbeat")

    def test_current_risk_structure(self, auth_headers):
        """Test current_risk has score, status, and reason"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEVICE_ID_WITH_DATA}/behavior-pattern?window_hours=168",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        current_risk = data.get("current_risk", {})
        
        # Verify current_risk fields
        assert "score" in current_risk
        assert "status" in current_risk
        assert "reason" in current_risk
        
        # Validate score range (0-1)
        score = current_risk["score"]
        assert 0 <= score <= 1, f"Score {score} outside 0-1 range"
        
        # Validate status is one of the valid values
        status = current_risk["status"]
        assert status in ["normal", "mild", "moderate", "critical"], f"Invalid status: {status}"
        
        # Validate reason is a string
        assert isinstance(current_risk["reason"], str)
        
        print(f"PASS - current_risk structure valid: score={score}, status={status}, reason present")

    def test_baseline_profile_structure(self, auth_headers):
        """Test baseline_profile is array with hour, avg_movement, avg_interaction_rate, sample_count"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEVICE_ID_WITH_DATA}/behavior-pattern?window_hours=168",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        baseline_profile = data.get("baseline_profile", [])
        
        # Should be a list
        assert isinstance(baseline_profile, list)
        
        # If there is baseline data, verify structure
        if len(baseline_profile) > 0:
            for entry in baseline_profile:
                assert "hour" in entry, "Missing 'hour' field"
                assert "avg_movement" in entry, "Missing 'avg_movement' field"
                assert "avg_interaction_rate" in entry, "Missing 'avg_interaction_rate' field"
                assert "sample_count" in entry, "Missing 'sample_count' field"
                
                # Validate types
                assert isinstance(entry["hour"], int)
                assert 0 <= entry["hour"] <= 23, f"Hour {entry['hour']} outside 0-23 range"
                assert isinstance(entry["avg_movement"], (int, float))
                assert isinstance(entry["avg_interaction_rate"], (int, float))
                assert isinstance(entry["sample_count"], int)
            
            print(f"PASS - baseline_profile has {len(baseline_profile)} entries with correct structure")
        else:
            print("PASS - baseline_profile is empty array (no baseline data yet)")

    def test_recent_anomalies_structure(self, auth_headers):
        """Test recent_anomalies has behavior_score, anomaly_type, reason, created_at"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEVICE_ID_WITH_DATA}/behavior-pattern?window_hours=168",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        recent_anomalies = data.get("recent_anomalies", [])
        
        # Should be a list
        assert isinstance(recent_anomalies, list)
        
        # Device DEV-001 has anomalies, so we expect at least 1
        assert len(recent_anomalies) >= 1, "Expected at least 1 anomaly for DEV-001"
        
        for anomaly in recent_anomalies:
            assert "behavior_score" in anomaly, "Missing 'behavior_score' field"
            assert "anomaly_type" in anomaly, "Missing 'anomaly_type' field"
            assert "reason" in anomaly, "Missing 'reason' field"
            assert "created_at" in anomaly, "Missing 'created_at' field"
            
            # Validate types
            score = anomaly["behavior_score"]
            assert 0 <= score <= 1, f"behavior_score {score} outside 0-1 range"
            assert isinstance(anomaly["anomaly_type"], str)
            assert isinstance(anomaly["reason"], str)
            assert isinstance(anomaly["created_at"], str)  # ISO format string
        
        print(f"PASS - recent_anomalies has {len(recent_anomalies)} entries with correct structure")

    def test_inactivity_and_heartbeat_fields(self, auth_headers):
        """Test inactivity_minutes and last_heartbeat are present"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEVICE_ID_WITH_DATA}/behavior-pattern?window_hours=168",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        # These can be null if device never had heartbeats
        assert "inactivity_minutes" in data
        assert "last_heartbeat" in data
        
        # For DEV-001, we expect values since it has telemetry
        if data["last_heartbeat"] is not None:
            assert isinstance(data["last_heartbeat"], str)  # ISO format
            assert isinstance(data["inactivity_minutes"], (int, float))
            assert data["inactivity_minutes"] >= 0
            print(f"PASS - inactivity_minutes={data['inactivity_minutes']}, last_heartbeat present")
        else:
            print("PASS - last_heartbeat is null (no telemetry)")

    def test_returns_404_for_nonexistent_device(self, auth_headers):
        """Test endpoint returns 404 for non-existent device"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{NON_EXISTENT_DEVICE_ID}/behavior-pattern?window_hours=24",
            headers=auth_headers
        )
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
        print(f"PASS - Returns 404 with detail: {data['detail']}")

    def test_requires_authentication(self):
        """Test endpoint requires authentication"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEVICE_ID_WITH_DATA}/behavior-pattern?window_hours=24"
        )
        assert response.status_code == 401
        print("PASS - Returns 401 without authentication")

    def test_window_hours_parameter(self, auth_headers):
        """Test window_hours parameter affects results"""
        # Test with 24h window
        response_24h = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEVICE_ID_WITH_DATA}/behavior-pattern?window_hours=24",
            headers=auth_headers
        )
        assert response_24h.status_code == 200
        
        # Test with 168h window (7 days)
        response_168h = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEVICE_ID_WITH_DATA}/behavior-pattern?window_hours=168",
            headers=auth_headers
        )
        assert response_168h.status_code == 200
        
        data_24h = response_24h.json()
        data_168h = response_168h.json()
        
        # Both should return valid structure
        assert "current_risk" in data_24h
        assert "current_risk" in data_168h
        
        # Longer window may have more anomalies
        print(f"PASS - window_hours parameter works: 24h anomalies={data_24h['total_anomalies_in_window']}, 168h anomalies={data_168h['total_anomalies_in_window']}")

    def test_risk_status_mapping(self, auth_headers):
        """Test risk status correctly maps based on score thresholds"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEVICE_ID_WITH_DATA}/behavior-pattern?window_hours=168",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        score = data["current_risk"]["score"]
        status = data["current_risk"]["status"]
        
        # Validate status matches score thresholds (from code):
        # 0-0.3: normal, 0.3-0.6: mild, 0.6-0.8: moderate, 0.8-1.0: critical
        if score >= 0.8:
            expected_status = "critical"
        elif score >= 0.6:
            expected_status = "moderate"
        elif score >= 0.3:
            expected_status = "mild"
        else:
            expected_status = "normal"
        
        assert status == expected_status, f"Score {score} should map to {expected_status}, got {status}"
        print(f"PASS - Risk status mapping correct: score={score} -> status={status}")

    def test_anomaly_types(self, auth_headers):
        """Test anomaly_type values are valid"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEVICE_ID_WITH_DATA}/behavior-pattern?window_hours=168",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        valid_types = ["extended_inactivity", "low_interaction", "movement_drop", 
                       "unusual_movement", "hyperactivity", "routine_break"]
        
        for anomaly in data.get("recent_anomalies", []):
            anomaly_type = anomaly["anomaly_type"]
            assert anomaly_type in valid_types, f"Invalid anomaly_type: {anomaly_type}"
        
        print(f"PASS - All anomaly types are valid")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
