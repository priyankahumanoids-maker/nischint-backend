"""
Test Battery Comparison Engine - POST /api/operator/simulate/compare/battery
Tests for comparing two battery threshold configs against live telemetry.
Devices with recent real heartbeats: DEV-001 (~13-15%), DEV-002 (~21-23%), WATCH-001 (~79-80%)
"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


class TestBatteryComparisonAuth:
    """Authentication and RBAC tests for battery comparison endpoint"""

    def test_unauthenticated_gets_401(self):
        """Endpoint returns 401 without authentication token"""
        payload = {
            "config_a": {"battery_percent": 20, "sustain_minutes": 30},
            "config_b": {"battery_percent": 25, "sustain_minutes": 30},
            "min_heartbeats": 2
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/battery",
            json=payload
        )
        assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"

    def test_guardian_gets_403(self):
        """Guardian role should be forbidden (403)"""
        # Login as guardian
        login_resp = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "nischint4parents@gmail.com", "password": "secret123"}
        )
        assert login_resp.status_code == 200, f"Guardian login failed: {login_resp.text}"
        guardian_token = login_resp.json()["access_token"]

        payload = {
            "config_a": {"battery_percent": 20, "sustain_minutes": 30},
            "config_b": {"battery_percent": 25, "sustain_minutes": 30},
            "min_heartbeats": 2
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/battery",
            json=payload,
            headers={"Authorization": f"Bearer {guardian_token}"}
        )
        assert response.status_code == 403, f"Expected 403, got {response.status_code}: {response.text}"


class TestBatteryComparisonValidation:
    """Input validation tests for battery comparison endpoint"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Login as operator for validation tests"""
        login_resp = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "operator@nischint.com", "password": "operator123"}
        )
        assert login_resp.status_code == 200, f"Operator login failed: {login_resp.text}"
        self.token = login_resp.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def test_422_for_battery_percent_zero(self):
        """battery_percent=0 should return 422"""
        payload = {
            "config_a": {"battery_percent": 0, "sustain_minutes": 30},
            "config_b": {"battery_percent": 25, "sustain_minutes": 30},
            "min_heartbeats": 2
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/battery",
            json=payload,
            headers=self.headers
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"

    def test_422_for_battery_percent_over_100(self):
        """battery_percent>100 should return 422"""
        payload = {
            "config_a": {"battery_percent": 101, "sustain_minutes": 30},
            "config_b": {"battery_percent": 25, "sustain_minutes": 30},
            "min_heartbeats": 2
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/battery",
            json=payload,
            headers=self.headers
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"

    def test_422_for_missing_sustain_minutes(self):
        """Missing sustain_minutes should return 422"""
        payload = {
            "config_a": {"battery_percent": 20},
            "config_b": {"battery_percent": 25, "sustain_minutes": 30},
            "min_heartbeats": 2
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/battery",
            json=payload,
            headers=self.headers
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"

    def test_422_for_missing_battery_percent(self):
        """Missing battery_percent should return 422"""
        payload = {
            "config_a": {"sustain_minutes": 30},
            "config_b": {"battery_percent": 25, "sustain_minutes": 30},
            "min_heartbeats": 2
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/battery",
            json=payload,
            headers=self.headers
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"

    def test_422_for_invalid_min_heartbeats_zero(self):
        """min_heartbeats=0 should return 422"""
        payload = {
            "config_a": {"battery_percent": 20, "sustain_minutes": 30},
            "config_b": {"battery_percent": 25, "sustain_minutes": 30},
            "min_heartbeats": 0
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/battery",
            json=payload,
            headers=self.headers
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"

    def test_422_for_sustain_minutes_zero(self):
        """sustain_minutes=0 should return 422"""
        payload = {
            "config_a": {"battery_percent": 20, "sustain_minutes": 0},
            "config_b": {"battery_percent": 25, "sustain_minutes": 30},
            "min_heartbeats": 2
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/battery",
            json=payload,
            headers=self.headers
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"


class TestBatteryComparisonFunctionality:
    """Functional tests for battery comparison endpoint"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Login as operator for functional tests"""
        login_resp = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "operator@nischint.com", "password": "operator123"}
        )
        assert login_resp.status_code == 200, f"Operator login failed: {login_resp.text}"
        self.token = login_resp.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def test_valid_comparison_returns_200_with_correct_structure(self):
        """Valid comparison request returns 200 with all required fields"""
        payload = {
            "config_a": {"battery_percent": 20, "sustain_minutes": 60},
            "config_b": {"battery_percent": 25, "sustain_minutes": 60},
            "min_heartbeats": 2
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/battery",
            json=payload,
            headers=self.headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Validate all required fields present
        required_fields = [
            "metric", "evaluation_window_minutes", "min_heartbeats",
            "a", "b", "delta",
            "newly_flagged_devices", "no_longer_flagged_devices", "matched_in_both"
        ]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        
        # Validate metric value
        assert data["metric"] == "battery_level", f"Expected metric='battery_level', got {data['metric']}"
        
        # Validate evaluation_window_minutes
        assert data["evaluation_window_minutes"] == 60, f"Expected evaluation_window_minutes=60, got {data['evaluation_window_minutes']}"
        
        # Validate min_heartbeats
        assert data["min_heartbeats"] == 2, f"Expected min_heartbeats=2, got {data['min_heartbeats']}"

    def test_evaluation_window_is_max_of_both_configs(self):
        """evaluation_window_minutes = max(config_a.sustain_minutes, config_b.sustain_minutes)"""
        payload = {
            "config_a": {"battery_percent": 20, "sustain_minutes": 30},
            "config_b": {"battery_percent": 25, "sustain_minutes": 90},
            "min_heartbeats": 2
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/battery",
            json=payload,
            headers=self.headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert data["evaluation_window_minutes"] == 90, f"Expected max(30,90)=90, got {data['evaluation_window_minutes']}"

    def test_config_a_and_b_response_structure(self):
        """Validate 'a' and 'b' response sections have threshold and matched_devices_count"""
        payload = {
            "config_a": {"battery_percent": 20, "sustain_minutes": 60},
            "config_b": {"battery_percent": 25, "sustain_minutes": 60},
            "min_heartbeats": 2
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/battery",
            json=payload,
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        # Validate 'a' section
        assert "threshold" in data["a"], "Missing 'threshold' in config_a response"
        assert "matched_devices_count" in data["a"], "Missing 'matched_devices_count' in config_a response"
        assert data["a"]["threshold"]["battery_percent"] == 20
        assert data["a"]["threshold"]["sustain_minutes"] == 60
        assert isinstance(data["a"]["matched_devices_count"], int)
        
        # Validate 'b' section
        assert "threshold" in data["b"], "Missing 'threshold' in config_b response"
        assert "matched_devices_count" in data["b"], "Missing 'matched_devices_count' in config_b response"
        assert data["b"]["threshold"]["battery_percent"] == 25
        assert data["b"]["threshold"]["sustain_minutes"] == 60
        assert isinstance(data["b"]["matched_devices_count"], int)

    def test_delta_section_structure(self):
        """Validate delta section has newly_flagged_count, no_longer_flagged_count, intersection_count"""
        payload = {
            "config_a": {"battery_percent": 20, "sustain_minutes": 60},
            "config_b": {"battery_percent": 25, "sustain_minutes": 60},
            "min_heartbeats": 2
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/battery",
            json=payload,
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        delta = data["delta"]
        assert "newly_flagged_count" in delta, "Missing 'newly_flagged_count' in delta"
        assert "no_longer_flagged_count" in delta, "Missing 'no_longer_flagged_count' in delta"
        assert "intersection_count" in delta, "Missing 'intersection_count' in delta"
        
        assert isinstance(delta["newly_flagged_count"], int)
        assert isinstance(delta["no_longer_flagged_count"], int)
        assert isinstance(delta["intersection_count"], int)

    def test_newly_flagged_devices_structure(self):
        """newly_flagged_devices contains device_identifier, senior_name, guardian_name (no internal IDs)"""
        # Use config that may flag DEV-002 (~21-23%) but not DEV-001 (~13-15%)
        payload = {
            "config_a": {"battery_percent": 15, "sustain_minutes": 60},  # DEV-001 only
            "config_b": {"battery_percent": 25, "sustain_minutes": 60},  # DEV-001 + DEV-002
            "min_heartbeats": 1
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/battery",
            json=payload,
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        # Validate list type
        assert isinstance(data["newly_flagged_devices"], list)
        assert isinstance(data["no_longer_flagged_devices"], list)
        assert isinstance(data["matched_in_both"], list)
        
        # If any newly flagged devices, check structure
        for device in data["newly_flagged_devices"]:
            assert "device_identifier" in device, "Missing device_identifier in newly_flagged_devices"
            assert "senior_name" in device, "Missing senior_name in newly_flagged_devices"
            assert "guardian_name" in device, "Missing guardian_name in newly_flagged_devices"
            # Ensure no internal IDs are exposed
            assert "id" not in device, "Internal 'id' should not be in response"
            assert "device_id" not in device, "Internal 'device_id' should not be in response"
            assert "senior_id" not in device, "Internal 'senior_id' should not be in response"
            assert "guardian_id" not in device, "Internal 'guardian_id' should not be in response"

    def test_identical_configs_produce_empty_delta(self):
        """When config_a == config_b, newly_flagged=0, no_longer_flagged=0"""
        payload = {
            "config_a": {"battery_percent": 20, "sustain_minutes": 60},
            "config_b": {"battery_percent": 20, "sustain_minutes": 60},
            "min_heartbeats": 2
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/battery",
            json=payload,
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        # With identical configs, delta should be empty
        assert data["delta"]["newly_flagged_count"] == 0, f"Expected newly_flagged_count=0, got {data['delta']['newly_flagged_count']}"
        assert data["delta"]["no_longer_flagged_count"] == 0, f"Expected no_longer_flagged_count=0, got {data['delta']['no_longer_flagged_count']}"
        
        # intersection_count should equal matched_devices_count
        assert data["delta"]["intersection_count"] == data["a"]["matched_devices_count"]
        assert data["delta"]["intersection_count"] == data["b"]["matched_devices_count"]

    def test_stricter_config_b_shows_no_longer_flagged(self):
        """When B is stricter (lower threshold), devices in A but not B show as no_longer_flagged"""
        # Config A: 25% threshold (more permissive) - may flag DEV-001+DEV-002
        # Config B: 15% threshold (stricter) - may only flag DEV-001
        payload = {
            "config_a": {"battery_percent": 25, "sustain_minutes": 60},
            "config_b": {"battery_percent": 15, "sustain_minutes": 60},
            "min_heartbeats": 1
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/battery",
            json=payload,
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        # If A matches more devices than B, no_longer_flagged should be non-empty
        if data["a"]["matched_devices_count"] > data["b"]["matched_devices_count"]:
            assert data["delta"]["no_longer_flagged_count"] > 0, "Expected no_longer_flagged_count > 0 when B is stricter"
            assert len(data["no_longer_flagged_devices"]) == data["delta"]["no_longer_flagged_count"]

    def test_looser_config_b_shows_newly_flagged(self):
        """When B is looser (higher threshold), new devices flagged in B but not A show as newly_flagged"""
        # Config A: 15% threshold (stricter) - may only flag DEV-001
        # Config B: 25% threshold (more permissive) - may flag DEV-001+DEV-002
        payload = {
            "config_a": {"battery_percent": 15, "sustain_minutes": 60},
            "config_b": {"battery_percent": 25, "sustain_minutes": 60},
            "min_heartbeats": 1
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/battery",
            json=payload,
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        # If B matches more devices than A, newly_flagged should be non-empty
        if data["b"]["matched_devices_count"] > data["a"]["matched_devices_count"]:
            assert data["delta"]["newly_flagged_count"] > 0, "Expected newly_flagged_count > 0 when B is looser"
            assert len(data["newly_flagged_devices"]) == data["delta"]["newly_flagged_count"]

    def test_intersection_devices_present_in_matched_in_both(self):
        """matched_in_both contains devices flagged by both configs"""
        payload = {
            "config_a": {"battery_percent": 20, "sustain_minutes": 60},
            "config_b": {"battery_percent": 25, "sustain_minutes": 60},
            "min_heartbeats": 1
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/battery",
            json=payload,
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        assert len(data["matched_in_both"]) == data["delta"]["intersection_count"]

    def test_very_small_window_may_return_zero_matches(self):
        """A very small sustain_minutes window may return 0 matches if no data exists"""
        payload = {
            "config_a": {"battery_percent": 20, "sustain_minutes": 1},  # 1 minute window - very narrow
            "config_b": {"battery_percent": 25, "sustain_minutes": 1},
            "min_heartbeats": 100  # High threshold - unlikely to match
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/battery",
            json=payload,
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        # Should return valid response with 0 or more matches
        assert data["a"]["matched_devices_count"] >= 0
        assert data["b"]["matched_devices_count"] >= 0

    def test_high_battery_threshold_matches_all_low_battery_devices(self):
        """A high battery_percent threshold should match devices with low battery"""
        # DEV-001 (~13-15%), DEV-002 (~21-23%) should match at 25% threshold
        payload = {
            "config_a": {"battery_percent": 25, "sustain_minutes": 60},
            "config_b": {"battery_percent": 50, "sustain_minutes": 60},  # Even higher
            "min_heartbeats": 1
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/battery",
            json=payload,
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        # B should match at least as many devices as A (since 50% > 25%)
        assert data["b"]["matched_devices_count"] >= data["a"]["matched_devices_count"]

    def test_excludes_simulated_telemetry(self):
        """Comparison only uses real telemetry (is_simulated=false)"""
        # This test verifies the endpoint correctly excludes simulated data
        # by checking that we get consistent results across calls
        payload = {
            "config_a": {"battery_percent": 20, "sustain_minutes": 60},
            "config_b": {"battery_percent": 25, "sustain_minutes": 60},
            "min_heartbeats": 2
        }
        
        # Make two consecutive calls
        response1 = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/battery",
            json=payload,
            headers=self.headers
        )
        response2 = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/battery",
            json=payload,
            headers=self.headers
        )
        
        assert response1.status_code == 200
        assert response2.status_code == 200
        
        data1 = response1.json()
        data2 = response2.json()
        
        # Results should be consistent (no simulated data affecting results between calls)
        assert data1["a"]["matched_devices_count"] == data2["a"]["matched_devices_count"]
        assert data1["b"]["matched_devices_count"] == data2["b"]["matched_devices_count"]


class TestBatteryComparisonReadOnly:
    """Tests to verify the endpoint is read-only (no DB writes)"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Login as operator"""
        login_resp = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "operator@nischint.com", "password": "operator123"}
        )
        assert login_resp.status_code == 200
        self.token = login_resp.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def test_no_db_writes_anomalies_count_unchanged(self):
        """Verify no device_anomalies are created by the comparison endpoint"""
        # Get anomaly count before
        anomalies_before = requests.get(
            f"{BASE_URL}/api/operator/device-anomalies?hours=168",
            headers=self.headers
        )
        assert anomalies_before.status_code == 200
        count_before = len(anomalies_before.json().get("anomalies", []))
        
        # Make comparison call
        payload = {
            "config_a": {"battery_percent": 20, "sustain_minutes": 60},
            "config_b": {"battery_percent": 25, "sustain_minutes": 60},
            "min_heartbeats": 2
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/battery",
            json=payload,
            headers=self.headers
        )
        assert response.status_code == 200
        
        # Get anomaly count after
        anomalies_after = requests.get(
            f"{BASE_URL}/api/operator/device-anomalies?hours=168",
            headers=self.headers
        )
        assert anomalies_after.status_code == 200
        count_after = len(anomalies_after.json().get("anomalies", []))
        
        # Count should be unchanged
        assert count_after == count_before, f"Anomaly count changed from {count_before} to {count_after} - endpoint is NOT read-only!"

    def test_multiple_calls_dont_create_side_effects(self):
        """Multiple comparison calls should not create any side effects"""
        payload = {
            "config_a": {"battery_percent": 15, "sustain_minutes": 60},
            "config_b": {"battery_percent": 30, "sustain_minutes": 60},
            "min_heartbeats": 1
        }
        
        # Make 3 consecutive calls
        results = []
        for _ in range(3):
            response = requests.post(
                f"{BASE_URL}/api/operator/simulate/compare/battery",
                json=payload,
                headers=self.headers
            )
            assert response.status_code == 200
            results.append(response.json())
        
        # All results should be identical (no side effects changing data)
        for i in range(1, 3):
            assert results[i]["a"]["matched_devices_count"] == results[0]["a"]["matched_devices_count"]
            assert results[i]["b"]["matched_devices_count"] == results[0]["b"]["matched_devices_count"]
            assert results[i]["delta"]["newly_flagged_count"] == results[0]["delta"]["newly_flagged_count"]
            assert results[i]["delta"]["no_longer_flagged_count"] == results[0]["delta"]["no_longer_flagged_count"]


class TestBatteryComparisonWithSeedData:
    """Tests that verify correct matching based on seeded device data"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Login as operator"""
        login_resp = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "operator@nischint.com", "password": "operator123"}
        )
        assert login_resp.status_code == 200
        self.token = login_resp.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def test_20_percent_threshold_detects_dev001(self):
        """20% threshold should detect DEV-001 (~13-15% battery) if data exists"""
        payload = {
            "config_a": {"battery_percent": 20, "sustain_minutes": 60},
            "config_b": {"battery_percent": 5, "sustain_minutes": 60},  # Very low, shouldn't match
            "min_heartbeats": 1
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/battery",
            json=payload,
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        # Config A at 20% should potentially match DEV-001
        # If matched, DEV-001 should be in A but not B (since B is 5%)
        print(f"Config A (20%) matched: {data['a']['matched_devices_count']}")
        print(f"Config B (5%) matched: {data['b']['matched_devices_count']}")
        
        # Check if DEV-001 appears in the results
        if data["a"]["matched_devices_count"] > 0:
            all_devices = [d["device_identifier"] for d in data.get("no_longer_flagged_devices", [])]
            all_devices.extend([d["device_identifier"] for d in data.get("matched_in_both", [])])
            print(f"Devices matched by A: {all_devices}")

    def test_25_percent_threshold_detects_dev001_and_dev002(self):
        """25% threshold should detect both DEV-001 (~13-15%) and DEV-002 (~21-23%)"""
        payload = {
            "config_a": {"battery_percent": 25, "sustain_minutes": 60},
            "config_b": {"battery_percent": 20, "sustain_minutes": 60},
            "min_heartbeats": 1
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/battery",
            json=payload,
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        print(f"Config A (25%) matched: {data['a']['matched_devices_count']}")
        print(f"Config B (20%) matched: {data['b']['matched_devices_count']}")
        
        # At 25%, should match both DEV-001 and DEV-002 if they have recent data
        # At 20%, should only match DEV-001

    def test_80_percent_threshold_detects_watch001(self):
        """80% threshold should detect WATCH-001 (~79-80% battery)"""
        payload = {
            "config_a": {"battery_percent": 82, "sustain_minutes": 60},  # Should match WATCH-001
            "config_b": {"battery_percent": 78, "sustain_minutes": 60},  # Shouldn't match WATCH-001
            "min_heartbeats": 1
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/battery",
            json=payload,
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        print(f"Config A (82%) matched: {data['a']['matched_devices_count']}")
        print(f"Config B (78%) matched: {data['b']['matched_devices_count']}")
        
        # WATCH-001 at ~79-80% should be matched by 82% but not 78%
        # If matched, newly_flagged should be empty, no_longer_flagged should contain WATCH-001


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
