# Test suite for POST /api/operator/health-rules/{rule_name}/simulate with total_devices_count
# Tests the new risk banner feature where simulate returns total_devices_count field
# Iteration 16: Testing total_devices_count field and related features

import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

# Credentials
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"
GUARDIAN_EMAIL = "nischint4parents@gmail.com"
GUARDIAN_PASSWORD = "secret123"

# Known rules and their required threshold keys
RULE_CONFIGS = {
    "low_battery": {
        "threshold_json": {"battery_percent": 20, "sustain_minutes": 10, "recovery_buffer": 5},
    },
    "signal_degradation": {
        "threshold_json": {"signal_threshold": -85, "sustain_minutes": 15, "recovery_buffer_dbm": 3},
    },
    "reboot_anomaly": {
        "threshold_json": {"gap_minutes": 5, "gap_count": 3, "window_minutes": 60},
    },
}


class TestTotalDevicesCount:
    """Tests for the new total_devices_count field in simulation response"""

    @pytest.fixture
    def operator_token(self):
        """Get operator authentication token"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD},
        )
        if response.status_code == 200:
            return response.json().get("access_token")
        pytest.skip(f"Operator login failed: {response.status_code}")

    @pytest.fixture
    def guardian_token(self):
        """Get guardian authentication token"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": GUARDIAN_EMAIL, "password": GUARDIAN_PASSWORD},
        )
        if response.status_code == 200:
            return response.json().get("access_token")
        pytest.skip(f"Guardian login failed: {response.status_code}")

    def test_low_battery_returns_total_devices_count(self, operator_token):
        """Test that low_battery simulation returns total_devices_count field"""
        payload = {
            "enabled": True,
            "threshold_json": RULE_CONFIGS["low_battery"]["threshold_json"],
            "cooldown_minutes": 60,
            "severity": "high",
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/health-rules/low_battery/simulate",
            json=payload,
            headers={"Authorization": f"Bearer {operator_token}"},
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        # Verify total_devices_count is present and valid
        assert "total_devices_count" in data, "Missing total_devices_count in response"
        assert isinstance(data["total_devices_count"], int), f"total_devices_count should be int, got {type(data['total_devices_count'])}"
        assert data["total_devices_count"] > 0, f"total_devices_count should be > 0, got {data['total_devices_count']}"
        
        print(f"PASS: low_battery returns total_devices_count={data['total_devices_count']}")

    def test_signal_degradation_returns_total_devices_count(self, operator_token):
        """Test that signal_degradation simulation returns total_devices_count field"""
        payload = {
            "enabled": True,
            "threshold_json": RULE_CONFIGS["signal_degradation"]["threshold_json"],
            "cooldown_minutes": 30,
            "severity": "medium",
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/health-rules/signal_degradation/simulate",
            json=payload,
            headers={"Authorization": f"Bearer {operator_token}"},
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "total_devices_count" in data, "Missing total_devices_count in response"
        assert isinstance(data["total_devices_count"], int), f"total_devices_count should be int"
        assert data["total_devices_count"] > 0, f"total_devices_count should be > 0"
        
        print(f"PASS: signal_degradation returns total_devices_count={data['total_devices_count']}")

    def test_reboot_anomaly_returns_total_devices_count(self, operator_token):
        """Test that reboot_anomaly simulation returns total_devices_count field"""
        payload = {
            "enabled": True,
            "threshold_json": RULE_CONFIGS["reboot_anomaly"]["threshold_json"],
            "cooldown_minutes": 120,
            "severity": "low",
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/health-rules/reboot_anomaly/simulate",
            json=payload,
            headers={"Authorization": f"Bearer {operator_token}"},
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "total_devices_count" in data, "Missing total_devices_count in response"
        assert isinstance(data["total_devices_count"], int), f"total_devices_count should be int"
        assert data["total_devices_count"] > 0, f"total_devices_count should be > 0"
        
        print(f"PASS: reboot_anomaly returns total_devices_count={data['total_devices_count']}")

    def test_disabled_rule_still_returns_total_devices_count(self, operator_token):
        """Test that even when rule is disabled, total_devices_count is returned"""
        payload = {
            "enabled": False,  # Disabled rule
            "threshold_json": RULE_CONFIGS["low_battery"]["threshold_json"],
            "cooldown_minutes": 60,
            "severity": "high",
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/health-rules/low_battery/simulate",
            json=payload,
            headers={"Authorization": f"Bearer {operator_token}"},
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "total_devices_count" in data, "Missing total_devices_count in response"
        assert data["matched_devices_count"] == 0, "Disabled rule should have 0 matched devices"
        assert data["total_devices_count"] > 0, "total_devices_count should still be > 0 even when disabled"
        
        print(f"PASS: Disabled rule returns total_devices_count={data['total_devices_count']}, matched=0")

    def test_total_devices_count_is_consistent_across_rules(self, operator_token):
        """Test that total_devices_count is consistent across all rule simulations"""
        totals = []
        
        for rule_name, config in RULE_CONFIGS.items():
            payload = {
                "enabled": True,
                "threshold_json": config["threshold_json"],
                "cooldown_minutes": 60,
                "severity": "low",
            }
            response = requests.post(
                f"{BASE_URL}/api/operator/health-rules/{rule_name}/simulate",
                json=payload,
                headers={"Authorization": f"Bearer {operator_token}"},
            )
            assert response.status_code == 200
            totals.append(response.json()["total_devices_count"])
        
        # All rules should report the same total_devices_count
        assert len(set(totals)) == 1, f"total_devices_count inconsistent across rules: {totals}"
        print(f"PASS: total_devices_count is consistent across all rules: {totals[0]}")


class TestSimulateValidation:
    """Validation tests - ensure invalid requests are rejected"""

    @pytest.fixture
    def operator_token(self):
        """Get operator authentication token"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD},
        )
        if response.status_code == 200:
            return response.json().get("access_token")
        pytest.skip(f"Operator login failed: {response.status_code}")

    @pytest.fixture
    def guardian_token(self):
        """Get guardian authentication token"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": GUARDIAN_EMAIL, "password": GUARDIAN_PASSWORD},
        )
        if response.status_code == 200:
            return response.json().get("access_token")
        pytest.skip(f"Guardian login failed: {response.status_code}")

    def test_simulate_rejects_guardian_role_403(self, guardian_token):
        """Test that guardian role is rejected with 403"""
        payload = {
            "enabled": True,
            "threshold_json": RULE_CONFIGS["low_battery"]["threshold_json"],
            "cooldown_minutes": 60,
            "severity": "high",
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/health-rules/low_battery/simulate",
            json=payload,
            headers={"Authorization": f"Bearer {guardian_token}"},
        )
        assert response.status_code == 403, f"Expected 403, got {response.status_code}: {response.text}"
        print("PASS: Guardian role rejected with 403")

    def test_simulate_rejects_unknown_rule_404(self, operator_token):
        """Test that unknown rule name returns 404"""
        payload = {
            "enabled": True,
            "threshold_json": {"some_key": 123},
            "cooldown_minutes": 60,
            "severity": "high",
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/health-rules/unknown_rule/simulate",
            json=payload,
            headers={"Authorization": f"Bearer {operator_token}"},
        )
        assert response.status_code == 404, f"Expected 404, got {response.status_code}: {response.text}"
        print("PASS: Unknown rule rejected with 404")

    def test_simulate_validates_threshold_json_keys(self, operator_token):
        """Test that invalid threshold_json keys are rejected"""
        payload = {
            "enabled": True,
            "threshold_json": {"invalid_key": 123},  # Invalid key
            "cooldown_minutes": 60,
            "severity": "high",
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/health-rules/low_battery/simulate",
            json=payload,
            headers={"Authorization": f"Bearer {operator_token}"},
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        print("PASS: Invalid threshold_json keys rejected with 422")


class TestExistingFeatures:
    """Ensure existing features still work (regression)"""

    @pytest.fixture
    def operator_token(self):
        """Get operator authentication token"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD},
        )
        if response.status_code == 200:
            return response.json().get("access_token")
        pytest.skip(f"Operator login failed: {response.status_code}")

    def test_toggle_rule_still_works(self, operator_token):
        """Test that toggle endpoint still works"""
        # Get current state
        rules_resp = requests.get(
            f"{BASE_URL}/api/operator/health-rules",
            headers={"Authorization": f"Bearer {operator_token}"},
        )
        assert rules_resp.status_code == 200
        rules = rules_resp.json()
        low_battery = next((r for r in rules if r["rule_name"] == "low_battery"), None)
        assert low_battery is not None
        
        current_enabled = low_battery["enabled"]
        
        # Toggle
        toggle_resp = requests.patch(
            f"{BASE_URL}/api/operator/health-rules/low_battery/toggle",
            json={"enabled": not current_enabled},
            headers={"Authorization": f"Bearer {operator_token}"},
        )
        assert toggle_resp.status_code == 200
        
        # Toggle back
        toggle_back_resp = requests.patch(
            f"{BASE_URL}/api/operator/health-rules/low_battery/toggle",
            json={"enabled": current_enabled},
            headers={"Authorization": f"Bearer {operator_token}"},
        )
        assert toggle_back_resp.status_code == 200
        
        print("PASS: Toggle endpoint still works")

    def test_audit_log_still_works(self, operator_token):
        """Test that audit log endpoint still works"""
        response = requests.get(
            f"{BASE_URL}/api/operator/health-rules/low_battery/audit-log",
            headers={"Authorization": f"Bearer {operator_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"PASS: Audit log endpoint returns {len(data)} entries")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
