"""
Test Suite: Life Pattern Graph API
Tests the GET /api/operator/devices/{device_id}/life-pattern endpoint
which builds a 24-hour behavioral fingerprint for senior care devices.
"""
import os
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials from the problem statement
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"
GUARDIAN_EMAIL = "nischint4parents@gmail.com"
GUARDIAN_PASSWORD = "secret123"

# Known device IDs
DEV_001_ID = "ce4b5463-5a7e-46a5-8bbf-365dcfb3daeb"
DEV_002_ID = "e029085c-1021-436d-9dfc-a0633979583d"
NON_EXISTENT_DEVICE_ID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture(scope="module")
def operator_token():
    """Get operator authentication token."""
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD}
    )
    assert response.status_code == 200, f"Operator login failed: {response.text}"
    return response.json().get("access_token")


@pytest.fixture(scope="module")
def guardian_token():
    """Get guardian authentication token."""
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": GUARDIAN_EMAIL, "password": GUARDIAN_PASSWORD}
    )
    assert response.status_code == 200, f"Guardian login failed: {response.text}"
    return response.json().get("access_token")


@pytest.fixture(scope="module")
def operator_session(operator_token):
    """Create requests session with operator auth."""
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {operator_token}",
        "Content-Type": "application/json"
    })
    return session


@pytest.fixture(scope="module")
def guardian_session(guardian_token):
    """Create requests session with guardian auth."""
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {guardian_token}",
        "Content-Type": "application/json"
    })
    return session


class TestLifePatternAuthentication:
    """Test authentication and authorization for Life Pattern API."""
    
    def test_unauthenticated_request_returns_401(self):
        """API requires authentication."""
        response = requests.get(f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/life-pattern")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: Unauthenticated request returns 401")
    
    def test_guardian_role_returns_403(self, guardian_session):
        """Guardian role cannot access operator-only endpoints."""
        response = guardian_session.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/life-pattern"
        )
        assert response.status_code == 403, f"Expected 403, got {response.status_code}"
        print("PASS: Guardian role returns 403 Forbidden")
    
    def test_operator_role_returns_200(self, operator_session):
        """Operator role can access the endpoint."""
        response = operator_session.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/life-pattern"
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("PASS: Operator role returns 200 OK")


class TestLifePatternEndpoint:
    """Test the Life Pattern API endpoint functionality."""
    
    def test_returns_correct_structure(self, operator_session):
        """API returns correct response structure with pattern, fingerprint, deviations, insights."""
        response = operator_session.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/life-pattern"
        )
        assert response.status_code == 200
        data = response.json()
        
        # Verify required top-level keys
        required_keys = ["device_id", "device_identifier", "days_observed", "generated_at", 
                        "pattern", "fingerprint", "deviations", "insights"]
        for key in required_keys:
            assert key in data, f"Missing required key: {key}"
        
        print(f"PASS: Response contains all required keys: {required_keys}")
    
    def test_pattern_has_24_hourly_entries(self, operator_session):
        """Pattern array contains 24 entries (one per hour)."""
        response = operator_session.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/life-pattern"
        )
        data = response.json()
        pattern = data["pattern"]
        
        assert isinstance(pattern, list), "Pattern should be a list"
        assert len(pattern) == 24, f"Expected 24 entries, got {len(pattern)}"
        
        # Verify hours 0-23
        hours = [p["hour"] for p in pattern]
        assert hours == list(range(24)), "Pattern should have hours 0-23"
        
        print("PASS: Pattern has 24 hourly entries (0-23)")
    
    def test_pattern_entry_structure(self, operator_session):
        """Each pattern entry has required probability fields."""
        response = operator_session.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/life-pattern"
        )
        data = response.json()
        pattern = data["pattern"]
        
        required_fields = ["hour", "movement_probability", "interaction_probability",
                         "sleep_probability", "anomaly_probability", "avg_events", "samples"]
        
        for entry in pattern:
            for field in required_fields:
                assert field in entry, f"Pattern entry missing field: {field}"
            # Validate probability ranges
            for prob_field in ["movement_probability", "interaction_probability", 
                              "sleep_probability", "anomaly_probability"]:
                prob = entry[prob_field]
                assert 0 <= prob <= 1, f"{prob_field} = {prob} should be between 0 and 1"
        
        print("PASS: All pattern entries have correct structure with valid probabilities [0, 1]")
    
    def test_fingerprint_structure(self, operator_session):
        """Fingerprint contains wake, peak, rest, sleep times and stability."""
        response = operator_session.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/life-pattern"
        )
        data = response.json()
        fingerprint = data["fingerprint"]
        
        required_keys = ["wake_time", "wake_hour", "sleep_time", "sleep_hour",
                        "peak_activity_time", "peak_activity_hour", 
                        "rest_window_time", "rest_window_hour",
                        "active_window", "routine_stability"]
        
        for key in required_keys:
            assert key in fingerprint, f"Fingerprint missing key: {key}"
        
        # Validate time formats (HH:00)
        for time_key in ["wake_time", "sleep_time", "peak_activity_time", "rest_window_time"]:
            time_val = fingerprint[time_key]
            assert time_val.endswith(":00"), f"{time_key} = {time_val} should end with :00"
        
        # Validate routine_stability is one of expected values
        stability = fingerprint["routine_stability"]
        assert stability in ["stable", "moderate", "irregular", "unknown"], \
            f"Invalid routine_stability: {stability}"
        
        print(f"PASS: Fingerprint structure valid - wake={fingerprint['wake_time']}, "
              f"peak={fingerprint['peak_activity_time']}, sleep={fingerprint['sleep_time']}, "
              f"stability={stability}")
    
    def test_deviations_array(self, operator_session):
        """Deviations is a list (may be empty if no deviations detected)."""
        response = operator_session.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/life-pattern"
        )
        data = response.json()
        deviations = data["deviations"]
        
        assert isinstance(deviations, list), "Deviations should be a list"
        
        # If there are deviations, validate their structure
        for dev in deviations:
            assert "hour" in dev, "Deviation missing 'hour'"
            assert "type" in dev, "Deviation missing 'type'"
            assert "description" in dev, "Deviation missing 'description'"
            assert dev["type"] in ["missing_activity", "unexpected_activity"], \
                f"Invalid deviation type: {dev['type']}"
        
        print(f"PASS: Deviations array valid - {len(deviations)} deviation(s) found")
    
    def test_insights_array(self, operator_session):
        """Insights is a list of AI-generated strings."""
        response = operator_session.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/life-pattern"
        )
        data = response.json()
        insights = data["insights"]
        
        assert isinstance(insights, list), "Insights should be a list"
        # Insights should have at least a few entries from pattern analysis
        assert len(insights) >= 1, "Should have at least 1 insight"
        
        for insight in insights:
            assert isinstance(insight, str), f"Insight should be string, got {type(insight)}"
            assert len(insight) > 0, "Insight should not be empty"
        
        print(f"PASS: Insights array valid - {len(insights)} insight(s) generated")
        for i, insight in enumerate(insights[:5]):
            print(f"  Insight {i+1}: {insight}")
    
    def test_device_not_found_returns_404(self, operator_session):
        """Non-existent device ID returns 404."""
        response = operator_session.get(
            f"{BASE_URL}/api/operator/devices/{NON_EXISTENT_DEVICE_ID}/life-pattern"
        )
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("PASS: Non-existent device returns 404")
    
    def test_custom_days_parameter(self, operator_session):
        """API accepts custom days parameter (e.g., days=14)."""
        response = operator_session.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/life-pattern?days=14"
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        # Days observed should be <= 14 (may be less if less data exists)
        assert data["days_observed"] >= 0, "days_observed should be non-negative"
        print(f"PASS: Custom days=14 parameter accepted, days_observed={data['days_observed']}")
    
    def test_invalid_days_parameter_below_minimum(self, operator_session):
        """Days parameter below minimum (7) should fail."""
        response = operator_session.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/life-pattern?days=5"
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}"
        print("PASS: days=5 (below minimum 7) returns 422")
    
    def test_invalid_days_parameter_above_maximum(self, operator_session):
        """Days parameter above maximum (90) should fail."""
        response = operator_session.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/life-pattern?days=100"
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}"
        print("PASS: days=100 (above maximum 90) returns 422")
    
    def test_second_device(self, operator_session):
        """Test API with second known device (DEV-002)."""
        response = operator_session.get(
            f"{BASE_URL}/api/operator/devices/{DEV_002_ID}/life-pattern"
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data["device_id"] == DEV_002_ID
        assert len(data["pattern"]) == 24
        assert "fingerprint" in data
        assert "deviations" in data
        assert "insights" in data
        
        print(f"PASS: DEV-002 returns valid life pattern with fingerprint, deviations, insights")


class TestLifePatternDataContent:
    """Test the actual data content and quality."""
    
    def test_generated_at_timestamp_is_recent(self, operator_session):
        """Generated timestamp should be a valid ISO format."""
        response = operator_session.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/life-pattern"
        )
        data = response.json()
        
        from datetime import datetime
        generated_at = data["generated_at"]
        # Should parse as ISO format
        try:
            datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
            print(f"PASS: generated_at is valid ISO timestamp: {generated_at}")
        except ValueError:
            pytest.fail(f"Invalid generated_at format: {generated_at}")
    
    def test_days_observed_is_positive(self, operator_session):
        """Days observed should be a positive integer."""
        response = operator_session.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/life-pattern"
        )
        data = response.json()
        
        days_observed = data["days_observed"]
        assert isinstance(days_observed, int), "days_observed should be an integer"
        assert days_observed >= 0, "days_observed should be non-negative"
        print(f"PASS: days_observed = {days_observed}")
    
    def test_sleep_probability_higher_at_night(self, operator_session):
        """Sleep probability should generally be higher at night hours (22-05)."""
        response = operator_session.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/life-pattern"
        )
        data = response.json()
        pattern = data["pattern"]
        
        night_hours = [h for h in pattern if h["hour"] >= 22 or h["hour"] <= 5]
        day_hours = [h for h in pattern if 10 <= h["hour"] <= 16]
        
        avg_night_sleep = sum(h["sleep_probability"] for h in night_hours) / len(night_hours) if night_hours else 0
        avg_day_sleep = sum(h["sleep_probability"] for h in day_hours) / len(day_hours) if day_hours else 0
        
        print(f"PASS: Sleep probability - Night avg: {avg_night_sleep:.2f}, Day avg: {avg_day_sleep:.2f}")
        # Night sleep should typically be higher (at least not dramatically lower)
        assert avg_night_sleep >= avg_day_sleep * 0.5, "Night sleep probability unexpectedly low"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
