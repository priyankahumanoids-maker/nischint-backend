# Test Device Health Rule Management Endpoints
# Iteration 10: Operator-only endpoints for listing, updating, and toggling health rules
# Rules: low_battery, signal_degradation, reboot_anomaly
# RBAC: operator/admin only (guardian gets 403)

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
OPERATOR_CREDS = {"email": "operator@nischint.com", "password": "operator123"}
GUARDIAN_CREDS = {"email": "nischint4parents@gmail.com", "password": "secret123"}

# Original rule values (for restoration after tests)
ORIGINAL_LOW_BATTERY = {
    "threshold_json": {"battery_percent": 20, "sustain_minutes": 10, "recovery_buffer": 5},
    "cooldown_minutes": 60,
    "severity": "low",
    "enabled": True
}
ORIGINAL_SIGNAL_DEGRADATION = {
    "threshold_json": {"signal_threshold": -80, "sustain_minutes": 10, "recovery_buffer_dbm": 5},
    "cooldown_minutes": 60,
    "severity": "low",
    "enabled": True
}
ORIGINAL_REBOOT_ANOMALY = {
    "threshold_json": {"gap_minutes": 3, "gap_count": 3, "window_minutes": 60},
    "cooldown_minutes": 120,
    "severity": "medium",
    "enabled": True
}


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
# Test GET /api/operator/health-rules - List all rules
# ────────────────────────────────────────────────────────────────────────────────

class TestListHealthRules:
    """GET /api/operator/health-rules endpoint tests"""
    
    def test_list_rules_returns_all_three_rules(self, operator_client):
        """GET /api/operator/health-rules returns all 3 rules with canonical response"""
        response = operator_client.get(f"{BASE_URL}/api/operator/health-rules")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        rules = response.json()
        assert isinstance(rules, list), "Response should be a list"
        assert len(rules) == 3, f"Expected 3 rules, got {len(rules)}"
        
        rule_names = {r["rule_name"] for r in rules}
        assert rule_names == {"low_battery", "signal_degradation", "reboot_anomaly"}, \
            f"Expected 3 specific rules, got {rule_names}"
        
        print(f"✓ GET /api/operator/health-rules returned {len(rules)} rules: {rule_names}")
    
    def test_list_rules_canonical_response_format(self, operator_client):
        """Each rule has canonical fields: rule_name, enabled, threshold_json, cooldown_minutes, severity, updated_at"""
        response = operator_client.get(f"{BASE_URL}/api/operator/health-rules")
        assert response.status_code == 200
        
        rules = response.json()
        required_fields = {"rule_name", "enabled", "threshold_json", "cooldown_minutes", "severity", "updated_at"}
        
        for rule in rules:
            actual_fields = set(rule.keys())
            assert required_fields == actual_fields, \
                f"Rule {rule.get('rule_name')} has fields {actual_fields}, expected exactly {required_fields}"
            
            # Validate types
            assert isinstance(rule["rule_name"], str)
            assert isinstance(rule["enabled"], bool)
            assert isinstance(rule["threshold_json"], dict)
            assert isinstance(rule["cooldown_minutes"], int)
            assert isinstance(rule["severity"], str)
            assert rule["updated_at"] is None or isinstance(rule["updated_at"], str)
        
        print("✓ All rules have canonical response format (no extra fields, no 'id')")
    
    def test_list_rules_no_internal_id_leaked(self, operator_client):
        """Response should never contain 'id' field (no internal IDs leaked)"""
        response = operator_client.get(f"{BASE_URL}/api/operator/health-rules")
        assert response.status_code == 200
        
        rules = response.json()
        for rule in rules:
            assert "id" not in rule, f"Rule {rule.get('rule_name')} contains 'id' field which should not be exposed"
        
        print("✓ No 'id' field in response (internal IDs not leaked)")
    
    def test_list_rules_requires_authentication(self):
        """GET /api/operator/health-rules without token returns 401"""
        response = requests.get(f"{BASE_URL}/api/operator/health-rules")
        assert response.status_code == 401, f"Expected 401 without auth, got {response.status_code}"
        print("✓ GET /api/operator/health-rules returns 401 without token")
    
    def test_list_rules_guardian_forbidden(self, guardian_client):
        """GET /api/operator/health-rules with guardian token returns 403"""
        response = guardian_client.get(f"{BASE_URL}/api/operator/health-rules")
        assert response.status_code == 403, f"Expected 403 for guardian, got {response.status_code}"
        print("✓ GET /api/operator/health-rules returns 403 for guardian")


# ────────────────────────────────────────────────────────────────────────────────
# Test PUT /api/operator/health-rules/{rule_name} - Update rule
# ────────────────────────────────────────────────────────────────────────────────

class TestUpdateHealthRule:
    """PUT /api/operator/health-rules/{rule_name} endpoint tests"""
    
    def test_update_low_battery_valid_payload(self, operator_client):
        """PUT /api/operator/health-rules/low_battery with valid payload updates and returns canonical response"""
        update_payload = {
            "enabled": True,
            "threshold_json": {"battery_percent": 25, "sustain_minutes": 15, "recovery_buffer": 8},
            "cooldown_minutes": 90,
            "severity": "medium"
        }
        
        response = operator_client.put(
            f"{BASE_URL}/api/operator/health-rules/low_battery",
            json=update_payload
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Verify canonical response fields
        assert data["rule_name"] == "low_battery"
        assert data["enabled"] == True
        assert data["threshold_json"] == update_payload["threshold_json"]
        assert data["cooldown_minutes"] == 90
        assert data["severity"] == "medium"
        assert "updated_at" in data
        assert "id" not in data, "Response should not contain 'id' field"
        
        print(f"✓ PUT /api/operator/health-rules/low_battery updated successfully, updated_at={data['updated_at']}")
        
        # Restore original values
        restore_rule(operator_client, "low_battery", ORIGINAL_LOW_BATTERY)
    
    def test_update_low_battery_invalid_severity(self, operator_client):
        """PUT with invalid severity (e.g. 'critical') returns 422"""
        payload = {
            "severity": "critical"  # Invalid - must be low, medium, high
        }
        
        response = operator_client.put(
            f"{BASE_URL}/api/operator/health-rules/low_battery",
            json=payload
        )
        assert response.status_code == 422, f"Expected 422 for invalid severity, got {response.status_code}: {response.text}"
        print("✓ PUT with invalid severity='critical' returns 422")
    
    def test_update_low_battery_unknown_threshold_key(self, operator_client):
        """PUT with unknown threshold key returns 422"""
        payload = {
            "threshold_json": {
                "battery_percent": 20,
                "sustain_minutes": 10,
                "recovery_buffer": 5,
                "unknown_key": 100  # Extra unknown key
            }
        }
        
        response = operator_client.put(
            f"{BASE_URL}/api/operator/health-rules/low_battery",
            json=payload
        )
        assert response.status_code == 422, f"Expected 422 for unknown threshold key, got {response.status_code}: {response.text}"
        print("✓ PUT with unknown threshold key returns 422")
    
    def test_update_low_battery_missing_required_threshold_key(self, operator_client):
        """PUT with missing required threshold key returns 422"""
        payload = {
            "threshold_json": {
                "battery_percent": 20,
                "sustain_minutes": 10
                # Missing: recovery_buffer
            }
        }
        
        response = operator_client.put(
            f"{BASE_URL}/api/operator/health-rules/low_battery",
            json=payload
        )
        assert response.status_code == 422, f"Expected 422 for missing threshold key, got {response.status_code}: {response.text}"
        print("✓ PUT with missing required threshold key returns 422")
    
    def test_update_nonexistent_rule_returns_404(self, operator_client):
        """PUT /api/operator/health-rules/nonexistent_rule returns 404"""
        payload = {"severity": "low"}
        
        response = operator_client.put(
            f"{BASE_URL}/api/operator/health-rules/nonexistent_rule",
            json=payload
        )
        assert response.status_code == 404, f"Expected 404 for nonexistent rule, got {response.status_code}: {response.text}"
        print("✓ PUT to nonexistent rule returns 404")
    
    def test_update_rule_guardian_forbidden(self, guardian_client):
        """PUT /api/operator/health-rules/low_battery with guardian token returns 403"""
        payload = {"severity": "high"}
        
        response = guardian_client.put(
            f"{BASE_URL}/api/operator/health-rules/low_battery",
            json=payload
        )
        assert response.status_code == 403, f"Expected 403 for guardian, got {response.status_code}"
        print("✓ PUT with guardian token returns 403")
    
    def test_update_signal_degradation_valid_threshold(self, operator_client):
        """PUT /api/operator/health-rules/signal_degradation with valid threshold_json updates correctly"""
        payload = {
            "threshold_json": {"signal_threshold": -85, "sustain_minutes": 15, "recovery_buffer_dbm": 8}
        }
        
        response = operator_client.put(
            f"{BASE_URL}/api/operator/health-rules/signal_degradation",
            json=payload
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["rule_name"] == "signal_degradation"
        assert data["threshold_json"]["signal_threshold"] == -85
        assert data["threshold_json"]["sustain_minutes"] == 15
        assert data["threshold_json"]["recovery_buffer_dbm"] == 8
        
        print("✓ PUT /api/operator/health-rules/signal_degradation updated correctly")
        
        # Restore original values
        restore_rule(operator_client, "signal_degradation", ORIGINAL_SIGNAL_DEGRADATION)
    
    def test_update_reboot_anomaly_valid_threshold(self, operator_client):
        """PUT /api/operator/health-rules/reboot_anomaly with valid threshold_json updates correctly"""
        payload = {
            "threshold_json": {"gap_minutes": 5, "gap_count": 5, "window_minutes": 90}
        }
        
        response = operator_client.put(
            f"{BASE_URL}/api/operator/health-rules/reboot_anomaly",
            json=payload
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["rule_name"] == "reboot_anomaly"
        assert data["threshold_json"]["gap_minutes"] == 5
        assert data["threshold_json"]["gap_count"] == 5
        assert data["threshold_json"]["window_minutes"] == 90
        
        print("✓ PUT /api/operator/health-rules/reboot_anomaly updated correctly")
        
        # Restore original values
        restore_rule(operator_client, "reboot_anomaly", ORIGINAL_REBOOT_ANOMALY)


# ────────────────────────────────────────────────────────────────────────────────
# Test PATCH /api/operator/health-rules/{rule_name}/toggle - Toggle rule
# ────────────────────────────────────────────────────────────────────────────────

class TestToggleHealthRule:
    """PATCH /api/operator/health-rules/{rule_name}/toggle endpoint tests"""
    
    def test_toggle_disable_rule(self, operator_client):
        """PATCH /api/operator/health-rules/low_battery/toggle with {enabled: false} disables rule"""
        response = operator_client.patch(
            f"{BASE_URL}/api/operator/health-rules/low_battery/toggle",
            json={"enabled": False}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["rule_name"] == "low_battery"
        assert data["enabled"] == False
        assert "id" not in data, "Response should not contain 'id' field"
        
        print("✓ PATCH toggle with enabled=false disables rule successfully")
        
        # Restore
        operator_client.patch(
            f"{BASE_URL}/api/operator/health-rules/low_battery/toggle",
            json={"enabled": True}
        )
    
    def test_toggle_enable_rule(self, operator_client):
        """PATCH /api/operator/health-rules/low_battery/toggle with {enabled: true} enables rule"""
        # First disable
        operator_client.patch(
            f"{BASE_URL}/api/operator/health-rules/low_battery/toggle",
            json={"enabled": False}
        )
        
        # Then enable
        response = operator_client.patch(
            f"{BASE_URL}/api/operator/health-rules/low_battery/toggle",
            json={"enabled": True}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["rule_name"] == "low_battery"
        assert data["enabled"] == True
        
        print("✓ PATCH toggle with enabled=true enables rule successfully")
    
    def test_toggle_nonexistent_rule_returns_404(self, operator_client):
        """PATCH /api/operator/health-rules/fake_rule/toggle returns 404"""
        response = operator_client.patch(
            f"{BASE_URL}/api/operator/health-rules/fake_rule/toggle",
            json={"enabled": True}
        )
        assert response.status_code == 404, f"Expected 404 for fake rule, got {response.status_code}"
        print("✓ PATCH toggle on nonexistent rule returns 404")
    
    def test_toggle_guardian_forbidden(self, guardian_client):
        """PATCH /api/operator/health-rules/low_battery/toggle with guardian token returns 403"""
        response = guardian_client.patch(
            f"{BASE_URL}/api/operator/health-rules/low_battery/toggle",
            json={"enabled": False}
        )
        assert response.status_code == 403, f"Expected 403 for guardian, got {response.status_code}"
        print("✓ PATCH toggle with guardian token returns 403")


# ────────────────────────────────────────────────────────────────────────────────
# Test Cache Invalidation - Changes reflected in GET after PUT/PATCH
# ────────────────────────────────────────────────────────────────────────────────

class TestCacheInvalidation:
    """Verify cache is invalidated after updates"""
    
    def test_cache_invalidation_after_put(self, operator_client):
        """After PUT update, GET /api/operator/health-rules reflects the change"""
        # Update rule
        update_payload = {
            "threshold_json": {"battery_percent": 35, "sustain_minutes": 20, "recovery_buffer": 10},
            "severity": "high"
        }
        
        put_response = operator_client.put(
            f"{BASE_URL}/api/operator/health-rules/low_battery",
            json=update_payload
        )
        assert put_response.status_code == 200
        
        # GET should show updated values (cache invalidated)
        get_response = operator_client.get(f"{BASE_URL}/api/operator/health-rules")
        assert get_response.status_code == 200
        
        rules = get_response.json()
        low_battery_rule = next((r for r in rules if r["rule_name"] == "low_battery"), None)
        
        assert low_battery_rule is not None
        assert low_battery_rule["threshold_json"]["battery_percent"] == 35
        assert low_battery_rule["severity"] == "high"
        
        print("✓ Cache invalidation works - GET reflects PUT changes immediately")
        
        # Restore
        restore_rule(operator_client, "low_battery", ORIGINAL_LOW_BATTERY)
    
    def test_cache_invalidation_after_toggle(self, operator_client):
        """After PATCH toggle, GET reflects the change"""
        # Toggle off
        operator_client.patch(
            f"{BASE_URL}/api/operator/health-rules/signal_degradation/toggle",
            json={"enabled": False}
        )
        
        # GET should show disabled
        get_response = operator_client.get(f"{BASE_URL}/api/operator/health-rules")
        rules = get_response.json()
        signal_rule = next((r for r in rules if r["rule_name"] == "signal_degradation"), None)
        
        assert signal_rule["enabled"] == False, "Rule should be disabled after toggle"
        
        print("✓ Cache invalidation works - GET reflects PATCH toggle changes immediately")
        
        # Restore
        operator_client.patch(
            f"{BASE_URL}/api/operator/health-rules/signal_degradation/toggle",
            json={"enabled": True}
        )


# ────────────────────────────────────────────────────────────────────────────────
# Additional Validation Tests
# ────────────────────────────────────────────────────────────────────────────────

class TestAdditionalValidations:
    """Additional edge case validations"""
    
    def test_partial_update_preserves_other_fields(self, operator_client):
        """PUT with only severity preserves other fields"""
        # Get current state
        get_resp = operator_client.get(f"{BASE_URL}/api/operator/health-rules")
        rules = get_resp.json()
        reboot_rule = next((r for r in rules if r["rule_name"] == "reboot_anomaly"), None)
        original_threshold = reboot_rule["threshold_json"].copy()
        original_cooldown = reboot_rule["cooldown_minutes"]
        
        # Update only severity
        put_resp = operator_client.put(
            f"{BASE_URL}/api/operator/health-rules/reboot_anomaly",
            json={"severity": "high"}
        )
        assert put_resp.status_code == 200
        
        data = put_resp.json()
        # threshold_json and cooldown_minutes should be unchanged
        assert data["threshold_json"] == original_threshold
        assert data["cooldown_minutes"] == original_cooldown
        assert data["severity"] == "high"
        
        print("✓ Partial update preserves unspecified fields")
        
        # Restore
        restore_rule(operator_client, "reboot_anomaly", ORIGINAL_REBOOT_ANOMALY)
    
    def test_severity_valid_values(self, operator_client):
        """Severity accepts only low, medium, high"""
        valid_severities = ["low", "medium", "high"]
        
        for sev in valid_severities:
            response = operator_client.put(
                f"{BASE_URL}/api/operator/health-rules/low_battery",
                json={"severity": sev}
            )
            assert response.status_code == 200, f"Severity '{sev}' should be valid"
        
        print("✓ All valid severities (low, medium, high) accepted")
        
        # Restore
        restore_rule(operator_client, "low_battery", ORIGINAL_LOW_BATTERY)
    
    def test_signal_degradation_threshold_wrong_keys(self, operator_client):
        """signal_degradation with wrong threshold keys returns 422"""
        # Using low_battery keys instead of signal_degradation keys
        payload = {
            "threshold_json": {
                "battery_percent": 20,  # Wrong key for signal_degradation
                "sustain_minutes": 10,
                "recovery_buffer": 5    # Wrong key (should be recovery_buffer_dbm)
            }
        }
        
        response = operator_client.put(
            f"{BASE_URL}/api/operator/health-rules/signal_degradation",
            json=payload
        )
        assert response.status_code == 422, f"Expected 422 for wrong keys, got {response.status_code}"
        print("✓ signal_degradation rejects wrong threshold keys")
    
    def test_reboot_anomaly_threshold_wrong_keys(self, operator_client):
        """reboot_anomaly with wrong threshold keys returns 422"""
        payload = {
            "threshold_json": {
                "battery_percent": 20,  # Wrong key
                "sustain_minutes": 10,
                "recovery_buffer": 5
            }
        }
        
        response = operator_client.put(
            f"{BASE_URL}/api/operator/health-rules/reboot_anomaly",
            json=payload
        )
        assert response.status_code == 422, f"Expected 422 for wrong keys, got {response.status_code}"
        print("✓ reboot_anomaly rejects wrong threshold keys")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
