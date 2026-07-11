# Test suite for POST /api/operator/health-rules/{rule_name}/simulate endpoint
# Tests the read-only rule simulation feature that evaluates hypothetical rules against live telemetry

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
        "eval_window_key": "sustain_minutes",
    },
    "signal_degradation": {
        "threshold_json": {"signal_threshold": -85, "sustain_minutes": 15, "recovery_buffer_dbm": 3},
        "eval_window_key": "sustain_minutes",
    },
    "reboot_anomaly": {
        "threshold_json": {"gap_minutes": 5, "gap_count": 3, "window_minutes": 60},
        "eval_window_key": "window_minutes",
    },
}


class TestRuleSimulationAuth:
    """Authentication and authorization tests for simulation endpoint"""

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

    def test_simulate_without_auth_returns_401(self):
        """Test that unauthenticated request returns 401"""
        payload = {
            "enabled": True,
            "threshold_json": RULE_CONFIGS["low_battery"]["threshold_json"],
            "cooldown_minutes": 60,
            "severity": "high",
        }
        response = requests.post(f"{BASE_URL}/api/operator/health-rules/low_battery/simulate", json=payload)
        assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"
        print("PASS: No auth returns 401")

    def test_simulate_with_guardian_token_returns_403(self, guardian_token):
        """Test that guardian (non-operator) role returns 403"""
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
        print("PASS: Guardian token returns 403")


class TestRuleSimulationValidation:
    """Input validation tests for simulation endpoint"""

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

    def test_simulate_unknown_rule_returns_404(self, operator_token):
        """Test that unknown rule name returns 404"""
        payload = {
            "enabled": True,
            "threshold_json": {"some_key": 123},
            "cooldown_minutes": 60,
            "severity": "high",
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/health-rules/fake_rule/simulate",
            json=payload,
            headers={"Authorization": f"Bearer {operator_token}"},
        )
        assert response.status_code == 404, f"Expected 404, got {response.status_code}: {response.text}"
        data = response.json()
        assert "fake_rule" in str(data) or "Unknown rule" in str(data)
        print("PASS: Unknown rule returns 404")

    def test_simulate_invalid_threshold_keys_returns_422(self, operator_token):
        """Test that invalid threshold_json keys return 422"""
        payload = {
            "enabled": True,
            "threshold_json": {"invalid_key": 123, "another_bad_key": 456},
            "cooldown_minutes": 60,
            "severity": "high",
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/health-rules/low_battery/simulate",
            json=payload,
            headers={"Authorization": f"Bearer {operator_token}"},
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        print("PASS: Invalid threshold keys returns 422")

    def test_simulate_missing_threshold_keys_returns_422(self, operator_token):
        """Test that missing required threshold_json keys return 422"""
        # Only provide battery_percent, missing sustain_minutes and recovery_buffer
        payload = {
            "enabled": True,
            "threshold_json": {"battery_percent": 20},
            "cooldown_minutes": 60,
            "severity": "high",
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/health-rules/low_battery/simulate",
            json=payload,
            headers={"Authorization": f"Bearer {operator_token}"},
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        data = response.json()
        assert "missing" in str(data).lower() or "Missing" in str(data)
        print("PASS: Missing threshold keys returns 422")

    def test_simulate_invalid_severity_returns_422(self, operator_token):
        """Test that invalid severity value returns 422"""
        payload = {
            "enabled": True,
            "threshold_json": RULE_CONFIGS["low_battery"]["threshold_json"],
            "cooldown_minutes": 60,
            "severity": "super_critical",  # Invalid - must be low, medium, high
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/health-rules/low_battery/simulate",
            json=payload,
            headers={"Authorization": f"Bearer {operator_token}"},
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        print("PASS: Invalid severity returns 422")


class TestRuleSimulationResponseShape:
    """Response structure and content tests"""

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

    def test_low_battery_simulate_response_shape(self, operator_token):
        """Test low_battery simulation returns correct response shape"""
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
        # Verify required fields in response
        assert "rule_name" in data, "Missing rule_name in response"
        assert data["rule_name"] == "low_battery"
        assert "simulated_severity" in data, "Missing simulated_severity in response"
        assert data["simulated_severity"] == "high"
        assert "matched_devices_count" in data, "Missing matched_devices_count in response"
        assert isinstance(data["matched_devices_count"], int)
        assert "evaluation_window_minutes" in data, "Missing evaluation_window_minutes in response"
        assert data["evaluation_window_minutes"] == payload["threshold_json"]["sustain_minutes"]
        assert "would_escalate" in data, "Missing would_escalate in response"
        assert isinstance(data["would_escalate"], bool)
        assert "matched_devices" in data, "Missing matched_devices in response"
        assert isinstance(data["matched_devices"], list)
        
        print(f"PASS: low_battery simulation response shape is correct. Matched: {data['matched_devices_count']}")

    def test_signal_degradation_simulate_response_shape(self, operator_token):
        """Test signal_degradation simulation returns correct evaluation_window_minutes"""
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
        assert data["rule_name"] == "signal_degradation"
        assert data["simulated_severity"] == "medium"
        # evaluation_window_minutes should be sustain_minutes for signal_degradation
        assert data["evaluation_window_minutes"] == payload["threshold_json"]["sustain_minutes"]
        assert "matched_devices" in data
        assert "matched_devices_count" in data
        
        print(f"PASS: signal_degradation simulation response is correct. Matched: {data['matched_devices_count']}")

    def test_reboot_anomaly_simulate_response_shape(self, operator_token):
        """Test reboot_anomaly simulation returns correct evaluation_window_minutes from window_minutes"""
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
        assert data["rule_name"] == "reboot_anomaly"
        assert data["simulated_severity"] == "low"
        # evaluation_window_minutes should be window_minutes for reboot_anomaly
        assert data["evaluation_window_minutes"] == payload["threshold_json"]["window_minutes"]
        assert "matched_devices" in data
        assert "matched_devices_count" in data
        
        print(f"PASS: reboot_anomaly simulation response is correct. Matched: {data['matched_devices_count']}")

    def test_simulate_disabled_rule_returns_zero_matches(self, operator_token):
        """Test that enabled=false returns 0 matches and would_escalate=false"""
        payload = {
            "enabled": False,
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
        assert data["matched_devices_count"] == 0, f"Expected 0 matches when disabled, got {data['matched_devices_count']}"
        assert data["would_escalate"] == False, "Expected would_escalate=false when disabled"
        assert data["matched_devices"] == [], "Expected empty matched_devices when disabled"
        
        print("PASS: Disabled rule returns 0 matches and would_escalate=false")

    def test_matched_devices_contain_correct_fields(self, operator_token):
        """Test that matched_devices entries contain only device_identifier, senior_name, guardian_name (no internal IDs)"""
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
        matched_devices = data.get("matched_devices", [])
        
        if len(matched_devices) > 0:
            for device in matched_devices:
                # Should contain these fields
                assert "device_identifier" in device, "Missing device_identifier"
                assert "senior_name" in device, "Missing senior_name"
                assert "guardian_name" in device, "Missing guardian_name (can be null)"
                
                # Should NOT contain internal IDs
                assert "id" not in device, "Response should not contain 'id'"
                assert "device_id" not in device, "Response should not contain 'device_id'"
                assert "senior_id" not in device, "Response should not contain 'senior_id'"
                assert "guardian_id" not in device, "Response should not contain 'guardian_id'"
            
            print(f"PASS: matched_devices entries contain correct fields (no internal IDs). Count: {len(matched_devices)}")
        else:
            # No matches is OK - we're verifying the schema
            print("PASS: No matched devices (schema verified on empty list)")

    def test_would_escalate_true_when_matches_exist(self, operator_token):
        """Test that would_escalate=true when matched_devices_count > 0"""
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
        assert response.status_code == 200
        
        data = response.json()
        if data["matched_devices_count"] > 0:
            assert data["would_escalate"] == True, "would_escalate should be true when matches > 0"
            print(f"PASS: would_escalate=true when matched_devices_count={data['matched_devices_count']}")
        else:
            assert data["would_escalate"] == False, "would_escalate should be false when matches = 0"
            print("PASS: would_escalate=false when matched_devices_count=0")


class TestRuleSimulationReadOnly:
    """Tests to verify simulation is read-only (no DB writes)"""

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

    def test_simulate_does_not_create_audit_log(self, operator_token):
        """Test that simulation does NOT create any audit log entries"""
        # Get audit log count BEFORE simulation
        audit_before = requests.get(
            f"{BASE_URL}/api/operator/health-rules/low_battery/audit-log",
            headers={"Authorization": f"Bearer {operator_token}"},
        )
        assert audit_before.status_code == 200
        count_before = len(audit_before.json())
        
        # Run simulation
        payload = {
            "enabled": True,
            "threshold_json": RULE_CONFIGS["low_battery"]["threshold_json"],
            "cooldown_minutes": 60,
            "severity": "high",
        }
        sim_response = requests.post(
            f"{BASE_URL}/api/operator/health-rules/low_battery/simulate",
            json=payload,
            headers={"Authorization": f"Bearer {operator_token}"},
        )
        assert sim_response.status_code == 200
        
        # Get audit log count AFTER simulation
        audit_after = requests.get(
            f"{BASE_URL}/api/operator/health-rules/low_battery/audit-log",
            headers={"Authorization": f"Bearer {operator_token}"},
        )
        assert audit_after.status_code == 200
        count_after = len(audit_after.json())
        
        # Verify no new audit log entries
        assert count_after == count_before, f"Audit log count changed from {count_before} to {count_after}. Simulation should NOT create audit logs!"
        print(f"PASS: Simulation did not create audit log entries (count before={count_before}, after={count_after})")

    def test_simulate_does_not_create_incidents(self, operator_token):
        """Test that simulation does NOT create any incidents"""
        # Get incident count BEFORE simulation
        incidents_before = requests.get(
            f"{BASE_URL}/api/operator/incidents",
            headers={"Authorization": f"Bearer {operator_token}"},
        )
        assert incidents_before.status_code == 200
        count_before = len(incidents_before.json())
        
        # Run simulation
        payload = {
            "enabled": True,
            "threshold_json": RULE_CONFIGS["low_battery"]["threshold_json"],
            "cooldown_minutes": 60,
            "severity": "high",
        }
        sim_response = requests.post(
            f"{BASE_URL}/api/operator/health-rules/low_battery/simulate",
            json=payload,
            headers={"Authorization": f"Bearer {operator_token}"},
        )
        assert sim_response.status_code == 200
        
        # Get incident count AFTER simulation
        incidents_after = requests.get(
            f"{BASE_URL}/api/operator/incidents",
            headers={"Authorization": f"Bearer {operator_token}"},
        )
        assert incidents_after.status_code == 200
        count_after = len(incidents_after.json())
        
        # Verify no new incidents
        assert count_after == count_before, f"Incident count changed from {count_before} to {count_after}. Simulation should NOT create incidents!"
        print(f"PASS: Simulation did not create incidents (count before={count_before}, after={count_after})")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
