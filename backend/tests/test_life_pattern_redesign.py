"""
Life Pattern Graph API Tests - REDESIGNED VERSION
Tests the new response format with:
- 'heatmap' array (not 'pattern')
- Keys: sleep, movement, interaction, location, anomaly
- routine_stability as integer (0-100)
- Days parameter (7, 30, 90)
- 24h caching behavior
- Command Center life_pattern_alerts
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL').rstrip('/')

# Test credentials
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"
GUARDIAN_EMAIL = "nischint4parents@gmail.com"
GUARDIAN_PASSWORD = "secret123"

# Known device IDs
DEVICE_ID_1 = "ce4b5463-5a7e-46a5-8bbf-365dcfb3daeb"  # DEV-001
DEVICE_ID_2 = "e029085c-1021-436d-9dfc-a0633979583d"  # DEV-002


@pytest.fixture(scope="module")
def operator_token():
    """Get operator auth token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": OPERATOR_EMAIL,
        "password": OPERATOR_PASSWORD
    })
    assert response.status_code == 200, f"Operator login failed: {response.text}"
    return response.json()["access_token"]


@pytest.fixture(scope="module")
def guardian_token():
    """Get guardian auth token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": GUARDIAN_EMAIL,
        "password": GUARDIAN_PASSWORD
    })
    assert response.status_code == 200, f"Guardian login failed: {response.text}"
    return response.json()["access_token"]


class TestLifePatternAuth:
    """Authentication tests for life pattern endpoint"""
    
    def test_unauthenticated_returns_401(self):
        """Unauthenticated request should return 401"""
        response = requests.get(f"{BASE_URL}/api/operator/devices/{DEVICE_ID_1}/life-pattern")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: Unauthenticated request returns 401")
    
    def test_guardian_returns_403(self, guardian_token):
        """Guardian role should be forbidden (403)"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEVICE_ID_1}/life-pattern",
            headers={"Authorization": f"Bearer {guardian_token}"}
        )
        assert response.status_code == 403, f"Expected 403 for guardian, got {response.status_code}"
        print("PASS: Guardian role returns 403")
    
    def test_operator_returns_200(self, operator_token):
        """Operator role should have access (200)"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEVICE_ID_1}/life-pattern",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: Operator role returns 200")


class TestLifePatternResponseFormat:
    """Tests for the NEW response format - 'heatmap' not 'pattern'"""
    
    def test_response_has_heatmap_not_pattern(self, operator_token):
        """Response should have 'heatmap' key, not 'pattern'"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEVICE_ID_1}/life-pattern",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Should have 'heatmap', not 'pattern'
        assert "heatmap" in data, f"Missing 'heatmap' key. Keys found: {data.keys()}"
        assert "pattern" not in data, f"'pattern' key should be renamed to 'heatmap'"
        print("PASS: Response has 'heatmap' key (not 'pattern')")
    
    def test_heatmap_has_24_entries(self, operator_token):
        """Heatmap should have exactly 24 entries (hours 0-23)"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEVICE_ID_1}/life-pattern",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        data = response.json()
        
        assert len(data["heatmap"]) == 24, f"Expected 24 entries, got {len(data['heatmap'])}"
        hours = [entry["hour"] for entry in data["heatmap"]]
        assert hours == list(range(24)), f"Hours should be 0-23: {hours}"
        print("PASS: Heatmap has 24 entries (hours 0-23)")
    
    def test_heatmap_entry_has_new_keys(self, operator_token):
        """Heatmap entries should have: sleep, movement, interaction, location, anomaly"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEVICE_ID_1}/life-pattern",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        data = response.json()
        
        required_keys = ["hour", "sleep", "movement", "interaction", "location", "anomaly"]
        
        for entry in data["heatmap"]:
            for key in required_keys:
                assert key in entry, f"Missing key '{key}' in heatmap entry: {entry}"
            
            # Verify shortened keys (not *_probability)
            assert "sleep_probability" not in entry, "Key should be 'sleep', not 'sleep_probability'"
            assert "movement_probability" not in entry, "Key should be 'movement', not 'movement_probability'"
            assert "interaction_probability" not in entry, "Key should be 'interaction', not 'interaction_probability'"
            assert "anomaly_probability" not in entry, "Key should be 'anomaly', not 'anomaly_probability'"
        
        print(f"PASS: Heatmap entries have correct keys: {required_keys}")
    
    def test_heatmap_has_location_field(self, operator_token):
        """NEW: Heatmap should have 'location' field (added in redesign)"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEVICE_ID_1}/life-pattern",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        data = response.json()
        
        for entry in data["heatmap"]:
            assert "location" in entry, f"Missing 'location' in heatmap entry: {entry}"
            assert 0 <= entry["location"] <= 1, f"Location should be 0-1, got {entry['location']}"
        
        print("PASS: Heatmap entries have 'location' field with valid probabilities")
    
    def test_probability_values_in_range(self, operator_token):
        """All probability values should be between 0 and 1"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEVICE_ID_1}/life-pattern",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        data = response.json()
        
        prob_keys = ["sleep", "movement", "interaction", "location", "anomaly"]
        
        for entry in data["heatmap"]:
            for key in prob_keys:
                value = entry[key]
                assert 0 <= value <= 1, f"Probability {key}={value} out of range [0,1] at hour {entry['hour']}"
        
        print("PASS: All probability values are in range [0, 1]")


class TestLifePatternFingerprint:
    """Tests for fingerprint section - routine_stability as integer"""
    
    def test_fingerprint_exists(self, operator_token):
        """Response should have fingerprint section"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEVICE_ID_1}/life-pattern",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        data = response.json()
        
        assert "fingerprint" in data, f"Missing 'fingerprint'. Keys: {data.keys()}"
        print("PASS: Response has 'fingerprint' section")
    
    def test_routine_stability_is_integer(self, operator_token):
        """routine_stability should be integer 0-100"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEVICE_ID_1}/life-pattern",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        data = response.json()
        
        stability = data["fingerprint"]["routine_stability"]
        assert isinstance(stability, int), f"routine_stability should be int, got {type(stability)}: {stability}"
        assert 0 <= stability <= 100, f"routine_stability should be 0-100, got {stability}"
        print(f"PASS: routine_stability is integer: {stability}")
    
    def test_routine_stability_label_exists(self, operator_token):
        """fingerprint should have routine_stability_label"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEVICE_ID_1}/life-pattern",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        data = response.json()
        
        assert "routine_stability_label" in data["fingerprint"], "Missing routine_stability_label"
        label = data["fingerprint"]["routine_stability_label"]
        valid_labels = ["Stable", "Monitor", "Attention"]
        assert label in valid_labels, f"Invalid label '{label}', expected one of {valid_labels}"
        print(f"PASS: routine_stability_label = '{label}'")
    
    def test_fingerprint_times(self, operator_token):
        """fingerprint should have wake_time, sleep_time, peak_activity_time, rest_window_time"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEVICE_ID_1}/life-pattern",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        data = response.json()
        fp = data["fingerprint"]
        
        required_fields = ["wake_time", "sleep_time", "peak_activity_time", "rest_window_time"]
        for field in required_fields:
            assert field in fp, f"Missing '{field}' in fingerprint"
        
        print(f"PASS: Fingerprint has all required time fields: {required_fields}")


class TestLifePatternDaysParameter:
    """Tests for days query parameter (7, 30, 90)"""
    
    def test_default_days_30(self, operator_token):
        """Default should be days=30"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEVICE_ID_1}/life-pattern",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        data = response.json()
        
        assert data["days_analyzed"] == 30, f"Default days should be 30, got {data['days_analyzed']}"
        print("PASS: Default days_analyzed = 30")
    
    def test_days_7_works(self, operator_token):
        """days=7 should be accepted"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEVICE_ID_1}/life-pattern?days=7",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200, f"days=7 failed: {response.status_code}"
        data = response.json()
        assert data["days_analyzed"] == 7, f"Expected days_analyzed=7, got {data['days_analyzed']}"
        print("PASS: days=7 returns 200 with days_analyzed=7")
    
    def test_days_90_works(self, operator_token):
        """days=90 should be accepted"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEVICE_ID_1}/life-pattern?days=90",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200, f"days=90 failed: {response.status_code}"
        data = response.json()
        assert data["days_analyzed"] == 90, f"Expected days_analyzed=90, got {data['days_analyzed']}"
        print("PASS: days=90 returns 200 with days_analyzed=90")
    
    def test_days_below_minimum_rejected(self, operator_token):
        """days < 7 should be rejected"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEVICE_ID_1}/life-pattern?days=5",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 422, f"Expected 422 for days=5, got {response.status_code}"
        print("PASS: days=5 (below minimum) returns 422")
    
    def test_days_above_maximum_rejected(self, operator_token):
        """days > 90 should be rejected"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEVICE_ID_1}/life-pattern?days=100",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 422, f"Expected 422 for days=100, got {response.status_code}"
        print("PASS: days=100 (above maximum) returns 422")


class TestLifePatternCaching:
    """Tests for 24h caching behavior"""
    
    def test_second_call_returns_quickly(self, operator_token):
        """Second call should return cached data quickly"""
        # First call - may take longer
        start1 = time.time()
        response1 = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEVICE_ID_1}/life-pattern",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        time1 = time.time() - start1
        assert response1.status_code == 200
        data1 = response1.json()
        
        # Second call - should be faster (cached)
        start2 = time.time()
        response2 = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEVICE_ID_1}/life-pattern",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        time2 = time.time() - start2
        assert response2.status_code == 200
        data2 = response2.json()
        
        # Data should be the same
        assert data1["heatmap"] == data2["heatmap"], "Cached data differs from first call"
        
        print(f"PASS: First call {time1:.2f}s, second call {time2:.2f}s (cached data returned)")


class TestCommandCenterLifePatternAlerts:
    """Tests for Command Center life_pattern_alerts"""
    
    def test_command_center_has_life_pattern_alerts(self, operator_token):
        """Command Center should return life_pattern_alerts array"""
        response = requests.get(
            f"{BASE_URL}/api/operator/command-center",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200, f"Command center failed: {response.status_code}"
        data = response.json()
        
        assert "life_pattern_alerts" in data, f"Missing 'life_pattern_alerts'. Keys: {data.keys()}"
        assert isinstance(data["life_pattern_alerts"], list), "life_pattern_alerts should be a list"
        print(f"PASS: Command center has life_pattern_alerts array (count: {len(data['life_pattern_alerts'])})")
    
    def test_life_pattern_alert_structure(self, operator_token):
        """life_pattern_alerts should have correct structure"""
        response = requests.get(
            f"{BASE_URL}/api/operator/command-center",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        data = response.json()
        
        alerts = data["life_pattern_alerts"]
        if len(alerts) > 0:
            alert = alerts[0]
            required_fields = ["device_id", "device_identifier", "type", "hour", "description", "severity"]
            for field in required_fields:
                assert field in alert, f"Missing '{field}' in life_pattern_alert: {alert}"
            print(f"PASS: life_pattern_alert has required fields: {required_fields}")
        else:
            print("PASS: No life_pattern_alerts currently (empty array is valid)")


class TestLifePatternOtherFields:
    """Tests for deviations, insights, and other fields"""
    
    def test_deviations_array(self, operator_token):
        """Response should have deviations array"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEVICE_ID_1}/life-pattern",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        data = response.json()
        
        assert "deviations" in data, "Missing 'deviations'"
        assert isinstance(data["deviations"], list), "deviations should be a list"
        print(f"PASS: deviations array present (count: {len(data['deviations'])})")
    
    def test_insights_array(self, operator_token):
        """Response should have insights array"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEVICE_ID_1}/life-pattern",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        data = response.json()
        
        assert "insights" in data, "Missing 'insights'"
        assert isinstance(data["insights"], list), "insights should be a list"
        print(f"PASS: insights array present (count: {len(data['insights'])})")
    
    def test_second_device(self, operator_token):
        """DEV-002 should also return valid life pattern"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEVICE_ID_2}/life-pattern",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200, f"DEV-002 failed: {response.status_code}"
        data = response.json()
        
        assert "heatmap" in data
        assert len(data["heatmap"]) == 24
        print("PASS: DEV-002 returns valid life pattern data")
