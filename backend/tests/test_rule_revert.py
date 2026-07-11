# Test: POST /api/operator/health-rules/{rule_name}/revert/{created_at}
# Tests the rule revert endpoint that reverts a health rule to a previous state
import pytest
import requests
import os
from urllib.parse import quote

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"
GUARDIAN_EMAIL = "nischint4parents@gmail.com"
GUARDIAN_PASSWORD = "secret123"

# Test rule - using low_battery as it was used in context
TEST_RULE_NAME = "low_battery"

# Original config to restore after tests
ORIGINAL_CONFIG = {
    "severity": "low",
    "cooldown_minutes": 60,
    "enabled": True,
    "threshold_json": {
        "battery_percent": 20,
        "sustain_minutes": 10,
        "recovery_buffer": 5
    }
}


class TestRuleRevertEndpoint:
    """Tests for POST /api/operator/health-rules/{rule_name}/revert/{created_at}"""

    @pytest.fixture(scope="class")
    def operator_token(self):
        """Get operator authentication token"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD}
        )
        assert response.status_code == 200, f"Operator login failed: {response.text}"
        token = response.json().get("access_token")
        assert token, "No access_token in operator login response"
        return token

    @pytest.fixture(scope="class")
    def guardian_token(self):
        """Get guardian authentication token"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": GUARDIAN_EMAIL, "password": GUARDIAN_PASSWORD}
        )
        assert response.status_code == 200, f"Guardian login failed: {response.text}"
        token = response.json().get("access_token")
        assert token, "No access_token in guardian login response"
        return token

    @pytest.fixture(scope="class")
    def operator_headers(self, operator_token):
        """Headers with operator auth"""
        return {"Authorization": f"Bearer {operator_token}", "Content-Type": "application/json"}

    @pytest.fixture(scope="class")
    def guardian_headers(self, guardian_token):
        """Headers with guardian auth"""
        return {"Authorization": f"Bearer {guardian_token}", "Content-Type": "application/json"}

    def restore_original_config(self, headers):
        """Restore rule to original config"""
        requests.put(
            f"{BASE_URL}/api/operator/health-rules/{TEST_RULE_NAME}",
            headers=headers,
            json=ORIGINAL_CONFIG
        )

    # ── RBAC Tests ──

    def test_revert_no_auth_returns_401(self):
        """POST revert with no auth → 401"""
        response = requests.post(
            f"{BASE_URL}/api/operator/health-rules/{TEST_RULE_NAME}/revert/2024-01-01T00:00:00+00:00"
        )
        assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"
        print("PASS: No auth returns 401")

    def test_revert_guardian_token_returns_403(self, guardian_headers):
        """POST revert with guardian token → 403"""
        response = requests.post(
            f"{BASE_URL}/api/operator/health-rules/{TEST_RULE_NAME}/revert/2024-01-01T00:00:00+00:00",
            headers=guardian_headers
        )
        assert response.status_code == 403, f"Expected 403, got {response.status_code}: {response.text}"
        print("PASS: Guardian token returns 403")

    # ── Validation Tests ──

    def test_revert_unknown_rule_returns_404(self, operator_headers):
        """POST revert with unknown rule_name → 404"""
        response = requests.post(
            f"{BASE_URL}/api/operator/health-rules/unknown_rule_xyz/revert/2024-01-01T00:00:00+00:00",
            headers=operator_headers
        )
        assert response.status_code == 404, f"Expected 404, got {response.status_code}: {response.text}"
        data = response.json()
        assert "Unknown rule" in data.get("detail", ""), f"Expected 'Unknown rule' in detail: {data}"
        print("PASS: Unknown rule returns 404")

    def test_revert_invalid_timestamp_returns_422(self, operator_headers):
        """POST revert with invalid timestamp → 422"""
        response = requests.post(
            f"{BASE_URL}/api/operator/health-rules/{TEST_RULE_NAME}/revert/not-a-timestamp",
            headers=operator_headers
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        data = response.json()
        assert "Invalid timestamp" in data.get("detail", ""), f"Expected 'Invalid timestamp' in detail: {data}"
        print("PASS: Invalid timestamp returns 422")

    def test_revert_nonexistent_audit_entry_returns_404(self, operator_headers):
        """POST revert with non-existent audit entry → 404"""
        # Use a valid but non-existent timestamp
        response = requests.post(
            f"{BASE_URL}/api/operator/health-rules/{TEST_RULE_NAME}/revert/1999-01-01T00:00:00+00:00",
            headers=operator_headers
        )
        assert response.status_code == 404, f"Expected 404, got {response.status_code}: {response.text}"
        data = response.json()
        assert "Audit entry not found" in data.get("detail", ""), f"Expected 'Audit entry not found' in detail: {data}"
        print("PASS: Non-existent audit entry returns 404")

    # ── Response Format Tests ──

    def test_no_internal_ids_in_response(self, operator_headers):
        """Verify no internal IDs exposed in revert response (when successful)"""
        # First create an audit entry by updating the rule
        update_response = requests.put(
            f"{BASE_URL}/api/operator/health-rules/{TEST_RULE_NAME}",
            headers=operator_headers,
            json={"severity": "high"}
        )
        assert update_response.status_code == 200, f"Update failed: {update_response.text}"

        # Get audit log to find timestamp
        audit_response = requests.get(
            f"{BASE_URL}/api/operator/health-rules/{TEST_RULE_NAME}/audit-log",
            headers=operator_headers
        )
        assert audit_response.status_code == 200
        audit_entries = audit_response.json()
        assert len(audit_entries) > 0, "No audit entries found"

        # Find the update entry we just created
        update_audit = next((e for e in audit_entries if e["change_type"] == "update"), None)
        assert update_audit, "No update audit entry found"
        audit_timestamp = update_audit["created_at"]

        # Revert to that entry
        revert_response = requests.post(
            f"{BASE_URL}/api/operator/health-rules/{TEST_RULE_NAME}/revert/{audit_timestamp}",
            headers=operator_headers
        )
        
        if revert_response.status_code == 200:
            data = revert_response.json()
            # Check no internal IDs like 'id', '_id', 'changed_by' (UUID)
            assert "id" not in data, "Internal 'id' field exposed in response"
            assert "_id" not in data, "MongoDB '_id' field exposed in response"
            assert "changed_by" not in data, "Internal 'changed_by' field exposed in response"
            print("PASS: No internal IDs exposed in response")
        else:
            print(f"Revert status: {revert_response.status_code} - {revert_response.text}")

        # Restore original config
        self.restore_original_config(operator_headers)

    # ── Full Round-Trip Test ──

    def test_full_round_trip_update_then_revert(self, operator_headers):
        """Full round-trip: PUT update → capture audit timestamp → POST revert → verify rule is back to original"""
        
        # Step 0: Ensure rule is at original state
        self.restore_original_config(operator_headers)
        
        # Get current rule state
        get_before = requests.get(
            f"{BASE_URL}/api/operator/health-rules",
            headers=operator_headers
        )
        assert get_before.status_code == 200
        rules_before = get_before.json()
        rule_before = next((r for r in rules_before if r["rule_name"] == TEST_RULE_NAME), None)
        assert rule_before, f"Rule {TEST_RULE_NAME} not found"
        original_severity = rule_before["severity"]
        print(f"Original severity: {original_severity}")

        # Step 1: PUT update to change severity to 'high'
        update_response = requests.put(
            f"{BASE_URL}/api/operator/health-rules/{TEST_RULE_NAME}",
            headers=operator_headers,
            json={"severity": "high"}
        )
        assert update_response.status_code == 200, f"Update failed: {update_response.text}"
        updated_rule = update_response.json()
        assert updated_rule["severity"] == "high", f"Update did not apply: {updated_rule}"
        print("Step 1 PASS: Rule updated to severity=high")

        # Step 2: GET audit log to capture the timestamp of the update
        audit_response = requests.get(
            f"{BASE_URL}/api/operator/health-rules/{TEST_RULE_NAME}/audit-log",
            headers=operator_headers
        )
        assert audit_response.status_code == 200
        audit_entries = audit_response.json()
        
        # Find the most recent update entry
        update_audit = next((e for e in audit_entries if e["change_type"] == "update"), None)
        assert update_audit, "No update audit entry found"
        audit_timestamp = update_audit["created_at"]
        print(f"Step 2 PASS: Got audit timestamp: {audit_timestamp}")

        # Verify audit entry has correct old_config and new_config
        assert update_audit["old_config"]["severity"] == original_severity, "old_config severity mismatch"
        assert update_audit["new_config"]["severity"] == "high", "new_config severity mismatch"

        # Step 3: POST revert to that audit entry (reverts to old_config = original state)
        revert_response = requests.post(
            f"{BASE_URL}/api/operator/health-rules/{TEST_RULE_NAME}/revert/{audit_timestamp}",
            headers=operator_headers
        )
        assert revert_response.status_code == 200, f"Revert failed: {revert_response.text}"
        revert_data = revert_response.json()
        
        # Verify response format
        assert revert_data["rule_name"] == TEST_RULE_NAME, f"rule_name mismatch: {revert_data}"
        assert revert_data["status"] == "reverted", f"status mismatch: {revert_data}"
        assert revert_data["reverted_to_timestamp"] == audit_timestamp, f"timestamp mismatch: {revert_data}"
        print(f"Step 3 PASS: Revert response: {revert_data}")

        # Step 4: GET health-rules to verify rule is back to original
        get_after = requests.get(
            f"{BASE_URL}/api/operator/health-rules",
            headers=operator_headers
        )
        assert get_after.status_code == 200
        rules_after = get_after.json()
        rule_after = next((r for r in rules_after if r["rule_name"] == TEST_RULE_NAME), None)
        assert rule_after, f"Rule {TEST_RULE_NAME} not found after revert"
        assert rule_after["severity"] == original_severity, f"Severity not reverted! Expected {original_severity}, got {rule_after['severity']}"
        print(f"Step 4 PASS: Rule severity reverted to {original_severity}")

        # Step 5: Verify revert created an audit entry with change_type='revert'
        audit_after = requests.get(
            f"{BASE_URL}/api/operator/health-rules/{TEST_RULE_NAME}/audit-log",
            headers=operator_headers
        )
        assert audit_after.status_code == 200
        audit_entries_after = audit_after.json()
        
        revert_audit = next((e for e in audit_entries_after if e["change_type"] == "revert"), None)
        assert revert_audit, "No revert audit entry found"
        
        # Verify revert audit entry structure
        # old_config = state before revert (high), new_config = state after revert (original)
        assert revert_audit["old_config"]["severity"] == "high", f"Revert audit old_config wrong: {revert_audit['old_config']}"
        assert revert_audit["new_config"]["severity"] == original_severity, f"Revert audit new_config wrong: {revert_audit['new_config']}"
        print(f"Step 5 PASS: Revert audit entry created with correct old_config and new_config")

        # Cleanup: ensure original config is restored
        self.restore_original_config(operator_headers)
        print("Full round-trip test PASS!")

    def test_cache_invalidation_after_revert(self, operator_headers):
        """Verify cache is invalidated after revert (GET reflects the change immediately)"""
        # This test verifies that GET /health-rules reflects changes immediately after revert
        
        # Setup: ensure original state
        self.restore_original_config(operator_headers)
        
        # Change severity
        requests.put(
            f"{BASE_URL}/api/operator/health-rules/{TEST_RULE_NAME}",
            headers=operator_headers,
            json={"severity": "critical"}
        )
        
        # Get audit timestamp
        audit_response = requests.get(
            f"{BASE_URL}/api/operator/health-rules/{TEST_RULE_NAME}/audit-log",
            headers=operator_headers
        )
        update_audit = next((e for e in audit_response.json() if e["change_type"] == "update"), None)
        audit_timestamp = update_audit["created_at"]

        # Revert
        requests.post(
            f"{BASE_URL}/api/operator/health-rules/{TEST_RULE_NAME}/revert/{audit_timestamp}",
            headers=operator_headers
        )

        # Immediately GET - should reflect the reverted state (cache invalidation working)
        get_response = requests.get(
            f"{BASE_URL}/api/operator/health-rules",
            headers=operator_headers
        )
        assert get_response.status_code == 200
        rules = get_response.json()
        rule = next((r for r in rules if r["rule_name"] == TEST_RULE_NAME), None)
        
        # Should be back to 'low' (original), not 'critical'
        assert rule["severity"] == "low", f"Cache not invalidated! Got severity: {rule['severity']}"
        print("PASS: Cache invalidation verified - GET reflects reverted state immediately")

        # Cleanup
        self.restore_original_config(operator_headers)

    def test_revert_audit_entry_structure(self, operator_headers):
        """Verify revert creates audit entry with old_config=state before revert, new_config=target old_config"""
        
        # Setup: ensure original state
        self.restore_original_config(operator_headers)
        
        # Get initial state
        get_initial = requests.get(f"{BASE_URL}/api/operator/health-rules", headers=operator_headers)
        rule_initial = next((r for r in get_initial.json() if r["rule_name"] == TEST_RULE_NAME), None)
        initial_cooldown = rule_initial["cooldown_minutes"]

        # Update cooldown
        requests.put(
            f"{BASE_URL}/api/operator/health-rules/{TEST_RULE_NAME}",
            headers=operator_headers,
            json={"cooldown_minutes": 120}
        )
        
        # Get update audit
        audit_response = requests.get(
            f"{BASE_URL}/api/operator/health-rules/{TEST_RULE_NAME}/audit-log",
            headers=operator_headers
        )
        update_audit = next((e for e in audit_response.json() if e["change_type"] == "update"), None)
        audit_timestamp = update_audit["created_at"]

        # Revert
        requests.post(
            f"{BASE_URL}/api/operator/health-rules/{TEST_RULE_NAME}/revert/{audit_timestamp}",
            headers=operator_headers
        )

        # Get revert audit entry
        audit_after = requests.get(
            f"{BASE_URL}/api/operator/health-rules/{TEST_RULE_NAME}/audit-log",
            headers=operator_headers
        )
        revert_audit = next((e for e in audit_after.json() if e["change_type"] == "revert"), None)
        assert revert_audit, "No revert audit entry found"

        # Verify structure:
        # old_config = state before revert (cooldown=120)
        # new_config = state after revert (cooldown=60, the target's old_config)
        assert revert_audit["old_config"]["cooldown_minutes"] == 120, f"old_config should have cooldown=120"
        assert revert_audit["new_config"]["cooldown_minutes"] == initial_cooldown, f"new_config should have cooldown={initial_cooldown}"
        print(f"PASS: Revert audit entry structure correct - old_config=120, new_config={initial_cooldown}")

        # Cleanup
        self.restore_original_config(operator_headers)


class TestCleanup:
    """Cleanup tests - run last to restore original state"""

    def test_restore_low_battery_original_config(self):
        """Restore low_battery to original config after all tests"""
        # Login as operator
        login_response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD}
        )
        assert login_response.status_code == 200
        token = login_response.json().get("access_token")
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        # Restore original config
        response = requests.put(
            f"{BASE_URL}/api/operator/health-rules/{TEST_RULE_NAME}",
            headers=headers,
            json=ORIGINAL_CONFIG
        )
        assert response.status_code == 200, f"Failed to restore original config: {response.text}"
        
        # Verify restoration
        get_response = requests.get(
            f"{BASE_URL}/api/operator/health-rules",
            headers=headers
        )
        rule = next((r for r in get_response.json() if r["rule_name"] == TEST_RULE_NAME), None)
        assert rule["severity"] == "low"
        assert rule["cooldown_minutes"] == 60
        assert rule["enabled"] == True
        assert rule["threshold_json"]["battery_percent"] == 20
        assert rule["threshold_json"]["sustain_minutes"] == 10
        assert rule["threshold_json"]["recovery_buffer"] == 5
        print(f"PASS: {TEST_RULE_NAME} restored to original config: severity=low, cooldown=60, enabled=true, threshold_json={{battery_percent:20, sustain_minutes:10, recovery_buffer:5}}")
