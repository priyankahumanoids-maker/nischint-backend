# Test Device Health Rule Audit Logging Feature
# Iteration 12: Immutable audit logging for health rule changes
# Tests: PUT creates 'update' audit, PATCH toggle creates 'toggle' audit
# Audit contains: rule_name, changed_by_name, change_type, old_config, new_config, ip_address, created_at
# RBAC: operator/admin only (guardian gets 403)

import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
OPERATOR_CREDS = {"email": "operator@nischint.com", "password": "operator123"}
GUARDIAN_CREDS = {"email": "nischint4parents@gmail.com", "password": "secret123"}

# Original rule values for restoration after tests
ORIGINAL_LOW_BATTERY = {
    "threshold_json": {"battery_percent": 20, "sustain_minutes": 10, "recovery_buffer": 5},
    "cooldown_minutes": 60,
    "severity": "low",
    "enabled": True
}

# Config snapshot keys expected in audit logs
CONFIG_SNAPSHOT_KEYS = {"enabled", "threshold_json", "cooldown_minutes", "severity"}


@pytest.fixture(scope="module")
def operator_token():
    """Get operator authentication token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json=OPERATOR_CREDS)
    if response.status_code == 200:
        return response.json().get("access_token")
    pytest.skip(f"Operator login failed: {response.status_code} - {response.text}")


@pytest.fixture(scope="module")
def guardian_token():
    """Get guardian authentication token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json=GUARDIAN_CREDS)
    if response.status_code == 200:
        return response.json().get("access_token")
    pytest.skip(f"Guardian login failed: {response.status_code} - {response.text}")


@pytest.fixture
def operator_client(operator_token):
    """Session with operator auth header"""
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {operator_token}"
    })
    return session


@pytest.fixture
def guardian_client(guardian_token):
    """Session with guardian auth header"""
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {guardian_token}"
    })
    return session


def restore_rule(operator_client, rule_name: str, original: dict):
    """Helper to restore a rule to its original state"""
    response = operator_client.put(f"{BASE_URL}/api/operator/health-rules/{rule_name}", json=original)
    assert response.status_code == 200, f"Failed to restore {rule_name}: {response.text}"


# ────────────────────────────────────────────────────────────────────────────────
# Test GET /api/operator/health-rules/{rule_name}/audit-log
# ────────────────────────────────────────────────────────────────────────────────

class TestAuditLogEndpoint:
    """GET /api/operator/health-rules/{rule_name}/audit-log endpoint tests"""
    
    def test_audit_log_endpoint_returns_list(self, operator_client):
        """GET /api/operator/health-rules/low_battery/audit-log returns a list"""
        response = operator_client.get(f"{BASE_URL}/api/operator/health-rules/low_battery/audit-log")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        audit_entries = response.json()
        assert isinstance(audit_entries, list), "Response should be a list"
        
        print(f"✓ GET /api/operator/health-rules/low_battery/audit-log returned {len(audit_entries)} entries")
    
    def test_audit_log_entry_has_required_fields(self, operator_client):
        """Each audit entry has required fields: rule_name, changed_by_name, change_type, old_config, new_config, ip_address, created_at"""
        response = operator_client.get(f"{BASE_URL}/api/operator/health-rules/low_battery/audit-log")
        assert response.status_code == 200
        
        audit_entries = response.json()
        if not audit_entries:
            pytest.skip("No audit entries found - need to create one first")
        
        required_fields = {"rule_name", "changed_by_name", "change_type", "old_config", "new_config", "ip_address", "created_at"}
        
        for entry in audit_entries:
            actual_fields = set(entry.keys())
            assert required_fields == actual_fields, \
                f"Audit entry has fields {actual_fields}, expected exactly {required_fields}"
        
        print("✓ Audit entries have exactly the required fields (no extra fields)")
    
    def test_audit_log_no_id_fields_in_response(self, operator_client):
        """Audit log response should NOT contain 'id' or 'changed_by' UUID fields"""
        response = operator_client.get(f"{BASE_URL}/api/operator/health-rules/low_battery/audit-log")
        assert response.status_code == 200
        
        audit_entries = response.json()
        if not audit_entries:
            pytest.skip("No audit entries found - need to create one first")
        
        for entry in audit_entries:
            assert "id" not in entry, "Audit entry should NOT contain 'id' field"
            assert "changed_by" not in entry, "Audit entry should NOT contain 'changed_by' UUID field"
        
        print("✓ No 'id' or 'changed_by' UUID fields in audit log response")
    
    def test_audit_log_fake_rule_returns_404(self, operator_client):
        """GET /api/operator/health-rules/fake_rule/audit-log returns 404"""
        response = operator_client.get(f"{BASE_URL}/api/operator/health-rules/fake_rule/audit-log")
        assert response.status_code == 404, f"Expected 404 for fake_rule, got {response.status_code}"
        print("✓ GET /api/operator/health-rules/fake_rule/audit-log returns 404")
    
    def test_audit_log_guardian_forbidden(self, guardian_client):
        """GET /api/operator/health-rules/low_battery/audit-log with guardian token returns 403"""
        response = guardian_client.get(f"{BASE_URL}/api/operator/health-rules/low_battery/audit-log")
        assert response.status_code == 403, f"Expected 403 for guardian, got {response.status_code}"
        print("✓ GET audit-log with guardian token returns 403")
    
    def test_audit_log_requires_authentication(self):
        """GET /api/operator/health-rules/low_battery/audit-log without token returns 401"""
        response = requests.get(f"{BASE_URL}/api/operator/health-rules/low_battery/audit-log")
        assert response.status_code == 401, f"Expected 401 without auth, got {response.status_code}"
        print("✓ GET audit-log returns 401 without token")
    
    def test_audit_log_descending_order(self, operator_client):
        """Audit log entries are returned in descending order (most recent first)"""
        response = operator_client.get(f"{BASE_URL}/api/operator/health-rules/low_battery/audit-log")
        assert response.status_code == 200
        
        audit_entries = response.json()
        if len(audit_entries) < 2:
            pytest.skip("Need at least 2 audit entries to verify ordering")
        
        # Verify descending order by created_at
        for i in range(len(audit_entries) - 1):
            current_time = audit_entries[i]["created_at"]
            next_time = audit_entries[i + 1]["created_at"]
            assert current_time >= next_time, \
                f"Entries not in descending order: {current_time} should be >= {next_time}"
        
        print(f"✓ Audit log entries in descending order (most recent first)")


# ────────────────────────────────────────────────────────────────────────────────
# Test PUT creates audit log with change_type='update'
# ────────────────────────────────────────────────────────────────────────────────

class TestPutCreatesAuditLog:
    """PUT /api/operator/health-rules/{rule_name} creates audit log with change_type='update'"""
    
    def test_put_creates_audit_entry_with_update_type(self, operator_client):
        """PUT creates an audit entry with change_type='update'"""
        # Get current audit count
        initial_audit_resp = operator_client.get(f"{BASE_URL}/api/operator/health-rules/low_battery/audit-log")
        initial_count = len(initial_audit_resp.json())
        
        # Make PUT request to update rule
        update_payload = {
            "threshold_json": {"battery_percent": 25, "sustain_minutes": 15, "recovery_buffer": 8},
            "cooldown_minutes": 90,
            "severity": "medium"
        }
        
        put_response = operator_client.put(
            f"{BASE_URL}/api/operator/health-rules/low_battery",
            json=update_payload
        )
        assert put_response.status_code == 200, f"PUT failed: {put_response.text}"
        
        # Verify new audit entry was created
        audit_resp = operator_client.get(f"{BASE_URL}/api/operator/health-rules/low_battery/audit-log")
        assert audit_resp.status_code == 200
        
        audit_entries = audit_resp.json()
        assert len(audit_entries) > initial_count, "No new audit entry was created"
        
        # Check the most recent entry (first in list due to descending order)
        latest_entry = audit_entries[0]
        assert latest_entry["change_type"] == "update", \
            f"Expected change_type='update', got '{latest_entry['change_type']}'"
        assert latest_entry["rule_name"] == "low_battery"
        
        print(f"✓ PUT creates audit entry with change_type='update'")
        
        # Restore original values
        restore_rule(operator_client, "low_battery", ORIGINAL_LOW_BATTERY)
    
    def test_put_audit_old_config_is_before_state(self, operator_client):
        """PUT audit old_config reflects the state BEFORE the mutation"""
        # Get current state first
        get_resp = operator_client.get(f"{BASE_URL}/api/operator/health-rules")
        rules = get_resp.json()
        low_battery_rule = next((r for r in rules if r["rule_name"] == "low_battery"), None)
        
        # Capture expected old config
        expected_old_config = {
            "enabled": low_battery_rule["enabled"],
            "threshold_json": low_battery_rule["threshold_json"],
            "cooldown_minutes": low_battery_rule["cooldown_minutes"],
            "severity": low_battery_rule["severity"]
        }
        
        # Make PUT request with different values
        update_payload = {
            "threshold_json": {"battery_percent": 30, "sustain_minutes": 20, "recovery_buffer": 10},
            "cooldown_minutes": 120,
            "severity": "high"
        }
        
        put_response = operator_client.put(
            f"{BASE_URL}/api/operator/health-rules/low_battery",
            json=update_payload
        )
        assert put_response.status_code == 200
        
        # Get latest audit entry
        audit_resp = operator_client.get(f"{BASE_URL}/api/operator/health-rules/low_battery/audit-log")
        latest_entry = audit_resp.json()[0]
        
        # Verify old_config matches state BEFORE mutation
        assert latest_entry["old_config"]["enabled"] == expected_old_config["enabled"]
        assert latest_entry["old_config"]["threshold_json"] == expected_old_config["threshold_json"]
        assert latest_entry["old_config"]["cooldown_minutes"] == expected_old_config["cooldown_minutes"]
        assert latest_entry["old_config"]["severity"] == expected_old_config["severity"]
        
        print("✓ old_config reflects state BEFORE mutation")
        
        # Restore
        restore_rule(operator_client, "low_battery", ORIGINAL_LOW_BATTERY)
    
    def test_put_audit_new_config_is_after_state(self, operator_client):
        """PUT audit new_config reflects the state AFTER the mutation"""
        # Make PUT request
        update_payload = {
            "threshold_json": {"battery_percent": 35, "sustain_minutes": 25, "recovery_buffer": 12},
            "cooldown_minutes": 150,
            "severity": "high",
            "enabled": False
        }
        
        put_response = operator_client.put(
            f"{BASE_URL}/api/operator/health-rules/low_battery",
            json=update_payload
        )
        assert put_response.status_code == 200
        
        # Get latest audit entry
        audit_resp = operator_client.get(f"{BASE_URL}/api/operator/health-rules/low_battery/audit-log")
        latest_entry = audit_resp.json()[0]
        
        # Verify new_config matches what was set
        assert latest_entry["new_config"]["enabled"] == update_payload["enabled"]
        assert latest_entry["new_config"]["threshold_json"] == update_payload["threshold_json"]
        assert latest_entry["new_config"]["cooldown_minutes"] == update_payload["cooldown_minutes"]
        assert latest_entry["new_config"]["severity"] == update_payload["severity"]
        
        print("✓ new_config reflects state AFTER mutation")
        
        # Restore
        restore_rule(operator_client, "low_battery", ORIGINAL_LOW_BATTERY)
    
    def test_put_audit_config_has_full_snapshot(self, operator_client):
        """Audit old_config and new_config contain full snapshots (enabled, threshold_json, cooldown_minutes, severity)"""
        # Make PUT request
        update_payload = {
            "severity": "medium"  # Only update severity - partial update
        }
        
        put_response = operator_client.put(
            f"{BASE_URL}/api/operator/health-rules/low_battery",
            json=update_payload
        )
        assert put_response.status_code == 200
        
        # Get latest audit entry
        audit_resp = operator_client.get(f"{BASE_URL}/api/operator/health-rules/low_battery/audit-log")
        latest_entry = audit_resp.json()[0]
        
        # Verify both old_config and new_config have full snapshots
        for config_name in ["old_config", "new_config"]:
            config = latest_entry[config_name]
            assert set(config.keys()) == CONFIG_SNAPSHOT_KEYS, \
                f"{config_name} missing keys: expected {CONFIG_SNAPSHOT_KEYS}, got {set(config.keys())}"
            
            # Verify types
            assert isinstance(config["enabled"], bool)
            assert isinstance(config["threshold_json"], dict)
            assert isinstance(config["cooldown_minutes"], int)
            assert isinstance(config["severity"], str)
        
        print("✓ old_config and new_config contain full snapshots")
        
        # Restore
        restore_rule(operator_client, "low_battery", ORIGINAL_LOW_BATTERY)


# ────────────────────────────────────────────────────────────────────────────────
# Test PATCH toggle creates audit log with change_type='toggle'
# ────────────────────────────────────────────────────────────────────────────────

class TestPatchToggleCreatesAuditLog:
    """PATCH /api/operator/health-rules/{rule_name}/toggle creates audit log with change_type='toggle'"""
    
    def test_toggle_creates_audit_entry_with_toggle_type(self, operator_client):
        """PATCH toggle creates an audit entry with change_type='toggle'"""
        # Get current audit count
        initial_audit_resp = operator_client.get(f"{BASE_URL}/api/operator/health-rules/low_battery/audit-log")
        initial_count = len(initial_audit_resp.json())
        
        # Make PATCH toggle request
        toggle_response = operator_client.patch(
            f"{BASE_URL}/api/operator/health-rules/low_battery/toggle",
            json={"enabled": False}
        )
        assert toggle_response.status_code == 200, f"PATCH toggle failed: {toggle_response.text}"
        
        # Verify new audit entry was created
        audit_resp = operator_client.get(f"{BASE_URL}/api/operator/health-rules/low_battery/audit-log")
        assert audit_resp.status_code == 200
        
        audit_entries = audit_resp.json()
        assert len(audit_entries) > initial_count, "No new audit entry was created by toggle"
        
        # Check the most recent entry
        latest_entry = audit_entries[0]
        assert latest_entry["change_type"] == "toggle", \
            f"Expected change_type='toggle', got '{latest_entry['change_type']}'"
        assert latest_entry["rule_name"] == "low_battery"
        
        print(f"✓ PATCH toggle creates audit entry with change_type='toggle'")
        
        # Restore
        operator_client.patch(
            f"{BASE_URL}/api/operator/health-rules/low_battery/toggle",
            json={"enabled": True}
        )
    
    def test_toggle_audit_old_config_shows_previous_enabled_state(self, operator_client):
        """Toggle audit old_config shows the previous enabled state"""
        # First ensure rule is enabled
        operator_client.patch(
            f"{BASE_URL}/api/operator/health-rules/low_battery/toggle",
            json={"enabled": True}
        )
        
        # Now toggle to disabled
        toggle_response = operator_client.patch(
            f"{BASE_URL}/api/operator/health-rules/low_battery/toggle",
            json={"enabled": False}
        )
        assert toggle_response.status_code == 200
        
        # Get latest audit entry
        audit_resp = operator_client.get(f"{BASE_URL}/api/operator/health-rules/low_battery/audit-log")
        latest_entry = audit_resp.json()[0]
        
        # old_config should show enabled=true (the state before toggle)
        assert latest_entry["old_config"]["enabled"] == True, \
            f"old_config should have enabled=true, got {latest_entry['old_config']['enabled']}"
        # new_config should show enabled=false (the state after toggle)
        assert latest_entry["new_config"]["enabled"] == False, \
            f"new_config should have enabled=false, got {latest_entry['new_config']['enabled']}"
        
        print("✓ Toggle audit correctly captures enabled state change")
        
        # Restore
        operator_client.patch(
            f"{BASE_URL}/api/operator/health-rules/low_battery/toggle",
            json={"enabled": True}
        )
    
    def test_toggle_audit_preserves_other_config_values(self, operator_client):
        """Toggle audit old_config and new_config have same non-enabled values"""
        # Toggle to disabled
        toggle_response = operator_client.patch(
            f"{BASE_URL}/api/operator/health-rules/low_battery/toggle",
            json={"enabled": False}
        )
        assert toggle_response.status_code == 200
        
        # Get latest audit entry
        audit_resp = operator_client.get(f"{BASE_URL}/api/operator/health-rules/low_battery/audit-log")
        latest_entry = audit_resp.json()[0]
        
        # All fields except 'enabled' should be the same in old and new config
        assert latest_entry["old_config"]["threshold_json"] == latest_entry["new_config"]["threshold_json"]
        assert latest_entry["old_config"]["cooldown_minutes"] == latest_entry["new_config"]["cooldown_minutes"]
        assert latest_entry["old_config"]["severity"] == latest_entry["new_config"]["severity"]
        
        print("✓ Toggle audit preserves non-enabled config values")
        
        # Restore
        operator_client.patch(
            f"{BASE_URL}/api/operator/health-rules/low_battery/toggle",
            json={"enabled": True}
        )


# ────────────────────────────────────────────────────────────────────────────────
# Test Audit Entry Metadata
# ────────────────────────────────────────────────────────────────────────────────

class TestAuditMetadata:
    """Test audit entry metadata: changed_by_name, ip_address, created_at"""
    
    def test_audit_entry_has_changed_by_name(self, operator_client):
        """Audit entry changed_by_name shows operator email or full_name"""
        # Make a change
        operator_client.put(
            f"{BASE_URL}/api/operator/health-rules/low_battery",
            json={"severity": "medium"}
        )
        
        # Get latest audit entry
        audit_resp = operator_client.get(f"{BASE_URL}/api/operator/health-rules/low_battery/audit-log")
        latest_entry = audit_resp.json()[0]
        
        # changed_by_name should be non-empty and contain the operator identifier
        assert latest_entry["changed_by_name"] is not None
        assert len(latest_entry["changed_by_name"]) > 0
        # Should be either email or name containing 'operator'
        assert "operator" in latest_entry["changed_by_name"].lower() or "@" in latest_entry["changed_by_name"]
        
        print(f"✓ changed_by_name = '{latest_entry['changed_by_name']}'")
        
        # Restore
        restore_rule(operator_client, "low_battery", ORIGINAL_LOW_BATTERY)
    
    def test_audit_entry_has_ip_address(self, operator_client):
        """Audit entry ip_address is captured (non-null string)"""
        # Make a change
        operator_client.put(
            f"{BASE_URL}/api/operator/health-rules/low_battery",
            json={"severity": "high"}
        )
        
        # Get latest audit entry
        audit_resp = operator_client.get(f"{BASE_URL}/api/operator/health-rules/low_battery/audit-log")
        latest_entry = audit_resp.json()[0]
        
        # ip_address should be captured (might be internal IP in container)
        assert latest_entry["ip_address"] is not None, "ip_address should not be null"
        assert isinstance(latest_entry["ip_address"], str)
        
        print(f"✓ ip_address captured: '{latest_entry['ip_address']}'")
        
        # Restore
        restore_rule(operator_client, "low_battery", ORIGINAL_LOW_BATTERY)
    
    def test_audit_entry_has_created_at_timestamp(self, operator_client):
        """Audit entry created_at is an ISO timestamp"""
        # Make a change
        operator_client.put(
            f"{BASE_URL}/api/operator/health-rules/low_battery",
            json={"severity": "low"}
        )
        
        # Get latest audit entry
        audit_resp = operator_client.get(f"{BASE_URL}/api/operator/health-rules/low_battery/audit-log")
        latest_entry = audit_resp.json()[0]
        
        # created_at should be an ISO timestamp
        assert latest_entry["created_at"] is not None
        assert isinstance(latest_entry["created_at"], str)
        # Should contain timestamp-like characters
        assert "T" in latest_entry["created_at"] or "-" in latest_entry["created_at"]
        
        print(f"✓ created_at timestamp: '{latest_entry['created_at']}'")
        
        # Restore
        restore_rule(operator_client, "low_battery", ORIGINAL_LOW_BATTERY)


# ────────────────────────────────────────────────────────────────────────────────
# Test Atomicity
# ────────────────────────────────────────────────────────────────────────────────

class TestAtomicity:
    """Test atomicity: if endpoint returns success, audit entry exists"""
    
    def test_put_success_means_audit_exists(self, operator_client):
        """If PUT returns success, audit entry exists (atomicity check)"""
        # Get initial audit count
        initial_audit_resp = operator_client.get(f"{BASE_URL}/api/operator/health-rules/low_battery/audit-log")
        initial_count = len(initial_audit_resp.json())
        
        # Make PUT request
        put_response = operator_client.put(
            f"{BASE_URL}/api/operator/health-rules/low_battery",
            json={"severity": "medium"}
        )
        
        # If PUT succeeded, audit must exist
        if put_response.status_code == 200:
            audit_resp = operator_client.get(f"{BASE_URL}/api/operator/health-rules/low_battery/audit-log")
            new_count = len(audit_resp.json())
            
            assert new_count > initial_count, \
                "PUT succeeded but no audit entry was created - atomicity violation"
            
            print("✓ Atomicity verified: PUT success → audit entry exists")
        else:
            pytest.fail(f"PUT failed unexpectedly: {put_response.status_code}")
        
        # Restore
        restore_rule(operator_client, "low_battery", ORIGINAL_LOW_BATTERY)
    
    def test_toggle_success_means_audit_exists(self, operator_client):
        """If PATCH toggle returns success, audit entry exists (atomicity check)"""
        # Get initial audit count
        initial_audit_resp = operator_client.get(f"{BASE_URL}/api/operator/health-rules/low_battery/audit-log")
        initial_count = len(initial_audit_resp.json())
        
        # Make PATCH toggle request
        toggle_response = operator_client.patch(
            f"{BASE_URL}/api/operator/health-rules/low_battery/toggle",
            json={"enabled": False}
        )
        
        # If toggle succeeded, audit must exist
        if toggle_response.status_code == 200:
            audit_resp = operator_client.get(f"{BASE_URL}/api/operator/health-rules/low_battery/audit-log")
            new_count = len(audit_resp.json())
            
            assert new_count > initial_count, \
                "Toggle succeeded but no audit entry was created - atomicity violation"
            
            print("✓ Atomicity verified: Toggle success → audit entry exists")
        else:
            pytest.fail(f"Toggle failed unexpectedly: {toggle_response.status_code}")
        
        # Restore
        operator_client.patch(
            f"{BASE_URL}/api/operator/health-rules/low_battery/toggle",
            json={"enabled": True}
        )


# ────────────────────────────────────────────────────────────────────────────────
# Test Multiple Operations Audit Trail
# ────────────────────────────────────────────────────────────────────────────────

class TestMultipleOperationsAuditTrail:
    """After multiple PUT/PATCH operations, audit log shows all changes in order"""
    
    def test_multiple_operations_create_sequential_audit_entries(self, operator_client):
        """Multiple operations create sequential audit entries visible in log"""
        # Get initial audit count
        initial_audit_resp = operator_client.get(f"{BASE_URL}/api/operator/health-rules/low_battery/audit-log")
        initial_count = len(initial_audit_resp.json())
        
        # Perform 3 operations with small delays to ensure different timestamps
        operations_data = [
            ("PUT", {"severity": "medium"}),
            ("TOGGLE", {"enabled": False}),
            ("PUT", {"cooldown_minutes": 90}),
        ]
        
        for op_type, payload in operations_data:
            if op_type == "PUT":
                resp = operator_client.put(
                    f"{BASE_URL}/api/operator/health-rules/low_battery",
                    json=payload
                )
            else:  # TOGGLE
                resp = operator_client.patch(
                    f"{BASE_URL}/api/operator/health-rules/low_battery/toggle",
                    json=payload
                )
            assert resp.status_code == 200, f"{op_type} failed: {resp.text}"
            time.sleep(0.1)  # Small delay to ensure different timestamps
        
        # Get audit log
        audit_resp = operator_client.get(f"{BASE_URL}/api/operator/health-rules/low_battery/audit-log")
        audit_entries = audit_resp.json()
        
        # Should have 3 more entries
        assert len(audit_entries) >= initial_count + 3, \
            f"Expected at least {initial_count + 3} entries, got {len(audit_entries)}"
        
        # Get the 3 most recent entries
        recent_entries = audit_entries[:3]
        
        # Most recent should be the last PUT (cooldown_minutes change)
        assert recent_entries[0]["change_type"] == "update"
        # Second most recent should be toggle
        assert recent_entries[1]["change_type"] == "toggle"
        # Third most recent should be first PUT (severity change)
        assert recent_entries[2]["change_type"] == "update"
        
        print(f"✓ Multiple operations created {3} audit entries in correct order")
        
        # Restore
        restore_rule(operator_client, "low_battery", ORIGINAL_LOW_BATTERY)


# ────────────────────────────────────────────────────────────────────────────────
# Test Other Rules (signal_degradation, reboot_anomaly)
# ────────────────────────────────────────────────────────────────────────────────

class TestOtherRulesAuditLog:
    """Test audit log works for other rules (not just low_battery)"""
    
    def test_signal_degradation_audit_log_works(self, operator_client):
        """PUT to signal_degradation creates audit entry"""
        # Get initial count
        initial_resp = operator_client.get(f"{BASE_URL}/api/operator/health-rules/signal_degradation/audit-log")
        initial_count = len(initial_resp.json())
        
        # Make PUT request
        put_resp = operator_client.put(
            f"{BASE_URL}/api/operator/health-rules/signal_degradation",
            json={"severity": "high"}
        )
        assert put_resp.status_code == 200
        
        # Verify audit entry created
        audit_resp = operator_client.get(f"{BASE_URL}/api/operator/health-rules/signal_degradation/audit-log")
        assert len(audit_resp.json()) > initial_count
        
        latest = audit_resp.json()[0]
        assert latest["rule_name"] == "signal_degradation"
        assert latest["change_type"] == "update"
        
        print("✓ signal_degradation audit log works")
        
        # Restore
        original = {
            "threshold_json": {"signal_threshold": -80, "sustain_minutes": 10, "recovery_buffer_dbm": 5},
            "cooldown_minutes": 60,
            "severity": "low",
            "enabled": True
        }
        restore_rule(operator_client, "signal_degradation", original)
    
    def test_reboot_anomaly_audit_log_works(self, operator_client):
        """Toggle reboot_anomaly creates audit entry"""
        # Get initial count
        initial_resp = operator_client.get(f"{BASE_URL}/api/operator/health-rules/reboot_anomaly/audit-log")
        initial_count = len(initial_resp.json())
        
        # Make toggle request
        toggle_resp = operator_client.patch(
            f"{BASE_URL}/api/operator/health-rules/reboot_anomaly/toggle",
            json={"enabled": False}
        )
        assert toggle_resp.status_code == 200
        
        # Verify audit entry created
        audit_resp = operator_client.get(f"{BASE_URL}/api/operator/health-rules/reboot_anomaly/audit-log")
        assert len(audit_resp.json()) > initial_count
        
        latest = audit_resp.json()[0]
        assert latest["rule_name"] == "reboot_anomaly"
        assert latest["change_type"] == "toggle"
        
        print("✓ reboot_anomaly audit log works")
        
        # Restore
        operator_client.patch(
            f"{BASE_URL}/api/operator/health-rules/reboot_anomaly/toggle",
            json={"enabled": True}
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
