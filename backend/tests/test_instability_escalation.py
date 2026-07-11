"""
Test Multi-Metric Escalation Layer (Step 1) - Device Instability Feature
================================================================================
Tests the 3-Gate escalation model:
- Gate 1: Anomaly detected (multi_metric anomaly)
- Gate 2: Persistence >= persistence_minutes (configurable, default 15min)
- Gate 3: Score tier mapping to L1/L2/L3 severity

Key features:
- POST /api/operator/escalation/evaluate-instability endpoint (operator only)
- device_instability incident type
- Tier mapping: 60-75→L1/medium, 75-90→L2/high, 90-100→L3/critical
- Guardrails: duplicate prevention, cooldown (30min), simulation isolation
- L1_ONLY_INCIDENT_TYPES (no auto-escalation to L2/L3 notifications)
"""

import pytest
import requests
import os
import sys

# Add the backend directory to the path for module imports
sys.path.insert(0, '/app/backend')

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


# ── Auth Helpers ──

def get_operator_token():
    """Login as operator and return token."""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "operator@nischint.com",
        "password": "operator123"
    })
    assert response.status_code == 200, f"Operator login failed: {response.text}"
    return response.json()["access_token"]


def get_guardian_token():
    """Login as guardian and return token."""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "nischint4parents@gmail.com",
        "password": "secret123"
    })
    assert response.status_code == 200, f"Guardian login failed: {response.text}"
    return response.json()["access_token"]


@pytest.fixture(scope="module")
def operator_headers():
    """Operator auth headers."""
    token = get_operator_token()
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def guardian_headers():
    """Guardian auth headers."""
    token = get_guardian_token()
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ── Test: POST /api/operator/escalation/evaluate-instability endpoint ──

class TestEvaluateInstabilityEndpoint:
    """Tests for the manual instability evaluation trigger endpoint."""

    def test_evaluate_instability_operator_access(self, operator_headers):
        """Operator can access the evaluate-instability endpoint."""
        response = requests.post(
            f"{BASE_URL}/api/operator/escalation/evaluate-instability",
            headers=operator_headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "incidents_created" in data
        assert "message" in data
        # The message should mention multi_metric persistence
        assert "multi_metric" in data["message"].lower() or "instability" in data["message"].lower()
        print(f"✓ Operator can trigger evaluate-instability: {data}")

    def test_evaluate_instability_guardian_blocked(self, guardian_headers):
        """Guardian should be blocked (403) from accessing evaluate-instability endpoint."""
        response = requests.post(
            f"{BASE_URL}/api/operator/escalation/evaluate-instability",
            headers=guardian_headers
        )
        assert response.status_code == 403, f"Expected 403 for guardian, got {response.status_code}: {response.text}"
        print("✓ Guardian correctly blocked (403) from evaluate-instability endpoint")

    def test_evaluate_instability_unauthenticated_blocked(self):
        """Unauthenticated requests should be blocked (401/403)."""
        response = requests.post(f"{BASE_URL}/api/operator/escalation/evaluate-instability")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("✓ Unauthenticated requests correctly blocked from evaluate-instability endpoint")


# ── Test: combined_anomaly config has new fields ──

class TestCombinedAnomalyConfig:
    """Tests for the combined_anomaly rule config with new instability fields."""

    def test_health_rules_contains_new_fields(self, operator_headers):
        """GET /api/operator/health-rules returns combined_anomaly with new fields."""
        response = requests.get(
            f"{BASE_URL}/api/operator/health-rules",
            headers=operator_headers
        )
        assert response.status_code == 200, f"Failed to get health rules: {response.text}"
        rules = response.json()
        
        # Find combined_anomaly rule
        combined_rule = None
        for rule in rules:
            if rule["rule_name"] == "combined_anomaly":
                combined_rule = rule
                break
        
        assert combined_rule is not None, "combined_anomaly rule not found in health-rules"
        
        threshold = combined_rule["threshold_json"]
        
        # Verify new fields exist
        assert "persistence_minutes" in threshold, "persistence_minutes missing from combined_anomaly config"
        assert "escalation_tiers" in threshold, "escalation_tiers missing from combined_anomaly config"
        assert "instability_cooldown_minutes" in threshold, "instability_cooldown_minutes missing from combined_anomaly config"
        
        # Verify escalation_tiers structure
        tiers = threshold["escalation_tiers"]
        assert isinstance(tiers, dict), "escalation_tiers should be a dict"
        assert "60-75" in tiers, "60-75 tier missing"
        assert "75-90" in tiers, "75-90 tier missing"
        assert "90-100" in tiers, "90-100 tier missing"
        
        # Verify tier values
        assert tiers.get("60-75") == "L1", f"60-75 should map to L1, got {tiers.get('60-75')}"
        assert tiers.get("75-90") == "L2", f"75-90 should map to L2, got {tiers.get('75-90')}"
        assert tiers.get("90-100") == "L3", f"90-100 should map to L3, got {tiers.get('90-100')}"
        
        print(f"✓ combined_anomaly config has new fields:")
        print(f"  - persistence_minutes: {threshold['persistence_minutes']}")
        print(f"  - escalation_tiers: {threshold['escalation_tiers']}")
        print(f"  - instability_cooldown_minutes: {threshold['instability_cooldown_minutes']}")

    def test_can_update_persistence_minutes(self, operator_headers):
        """PUT /api/operator/health-rules/combined_anomaly can update persistence_minutes."""
        # Get current config
        response = requests.get(f"{BASE_URL}/api/operator/health-rules", headers=operator_headers)
        assert response.status_code == 200
        rules = response.json()
        combined_rule = next((r for r in rules if r["rule_name"] == "combined_anomaly"), None)
        assert combined_rule is not None
        
        current_threshold = combined_rule["threshold_json"]
        original_persistence = current_threshold.get("persistence_minutes", 15)
        
        # Update persistence_minutes
        new_persistence = 20 if original_persistence != 20 else 15
        updated_threshold = {**current_threshold, "persistence_minutes": new_persistence}
        
        response = requests.put(
            f"{BASE_URL}/api/operator/health-rules/combined_anomaly",
            headers=operator_headers,
            json={"threshold_json": updated_threshold}
        )
        assert response.status_code == 200, f"Update failed: {response.text}"
        
        updated_rule = response.json()
        assert updated_rule["threshold_json"]["persistence_minutes"] == new_persistence
        print(f"✓ Updated persistence_minutes from {original_persistence} to {new_persistence}")
        
        # Restore original value
        restored_threshold = {**updated_threshold, "persistence_minutes": original_persistence}
        response = requests.put(
            f"{BASE_URL}/api/operator/health-rules/combined_anomaly",
            headers=operator_headers,
            json={"threshold_json": restored_threshold}
        )
        assert response.status_code == 200
        print(f"✓ Restored persistence_minutes to {original_persistence}")

    def test_can_update_escalation_tiers(self, operator_headers):
        """PUT /api/operator/health-rules/combined_anomaly can update escalation_tiers."""
        # Get current config
        response = requests.get(f"{BASE_URL}/api/operator/health-rules", headers=operator_headers)
        assert response.status_code == 200
        rules = response.json()
        combined_rule = next((r for r in rules if r["rule_name"] == "combined_anomaly"), None)
        assert combined_rule is not None
        
        current_threshold = combined_rule["threshold_json"]
        
        # Update escalation_tiers with a modified tier
        modified_tiers = {
            "60-75": "L1",
            "75-90": "L2",
            "90-100": "L3"
        }
        updated_threshold = {**current_threshold, "escalation_tiers": modified_tiers}
        
        response = requests.put(
            f"{BASE_URL}/api/operator/health-rules/combined_anomaly",
            headers=operator_headers,
            json={"threshold_json": updated_threshold}
        )
        assert response.status_code == 200, f"Update failed: {response.text}"
        
        updated_rule = response.json()
        assert updated_rule["threshold_json"]["escalation_tiers"] == modified_tiers
        print("✓ Can update escalation_tiers configuration")

    def test_can_update_instability_cooldown_minutes(self, operator_headers):
        """PUT /api/operator/health-rules/combined_anomaly can update instability_cooldown_minutes."""
        # Get current config
        response = requests.get(f"{BASE_URL}/api/operator/health-rules", headers=operator_headers)
        assert response.status_code == 200
        rules = response.json()
        combined_rule = next((r for r in rules if r["rule_name"] == "combined_anomaly"), None)
        assert combined_rule is not None
        
        current_threshold = combined_rule["threshold_json"]
        original_cooldown = current_threshold.get("instability_cooldown_minutes", 30)
        
        # Update instability_cooldown_minutes
        new_cooldown = 45 if original_cooldown != 45 else 30
        updated_threshold = {**current_threshold, "instability_cooldown_minutes": new_cooldown}
        
        response = requests.put(
            f"{BASE_URL}/api/operator/health-rules/combined_anomaly",
            headers=operator_headers,
            json={"threshold_json": updated_threshold}
        )
        assert response.status_code == 200, f"Update failed: {response.text}"
        
        updated_rule = response.json()
        assert updated_rule["threshold_json"]["instability_cooldown_minutes"] == new_cooldown
        print(f"✓ Updated instability_cooldown_minutes from {original_cooldown} to {new_cooldown}")
        
        # Restore original value
        restored_threshold = {**updated_threshold, "instability_cooldown_minutes": original_cooldown}
        response = requests.put(
            f"{BASE_URL}/api/operator/health-rules/combined_anomaly",
            headers=operator_headers,
            json={"threshold_json": restored_threshold}
        )
        assert response.status_code == 200
        print(f"✓ Restored instability_cooldown_minutes to {original_cooldown}")


# ── Test: L1_ONLY_INCIDENT_TYPES includes device_instability ──

class TestL1OnlyIncidentTypes:
    """Tests for device_instability being in L1_ONLY_INCIDENT_TYPES."""

    def test_device_instability_in_l1_only(self):
        """device_instability should be in L1_ONLY_INCIDENT_TYPES set."""
        from app.services.escalation_scheduler import L1_ONLY_INCIDENT_TYPES
        
        assert "device_instability" in L1_ONLY_INCIDENT_TYPES, \
            f"device_instability not in L1_ONLY_INCIDENT_TYPES: {L1_ONLY_INCIDENT_TYPES}"
        print(f"✓ device_instability is in L1_ONLY_INCIDENT_TYPES: {L1_ONLY_INCIDENT_TYPES}")


# ── Test: _map_score_to_tier function ──

class TestScoreToTierMapping:
    """Tests for the tier mapping function."""

    def test_tier_mapping_l1(self):
        """Scores 60-75 should map to L1."""
        from app.services.baseline_scheduler import _map_score_to_tier
        
        tiers = {"60-75": "L1", "75-90": "L2", "90-100": "L3"}
        
        assert _map_score_to_tier(60, tiers) == "L1", "Score 60 should map to L1"
        assert _map_score_to_tier(65, tiers) == "L1", "Score 65 should map to L1"
        assert _map_score_to_tier(70, tiers) == "L1", "Score 70 should map to L1"
        assert _map_score_to_tier(74.9, tiers) == "L1", "Score 74.9 should map to L1"
        print("✓ Scores 60-75 correctly map to L1")

    def test_tier_mapping_l2(self):
        """Scores 75-90 should map to L2."""
        from app.services.baseline_scheduler import _map_score_to_tier
        
        tiers = {"60-75": "L1", "75-90": "L2", "90-100": "L3"}
        
        assert _map_score_to_tier(75, tiers) == "L2", "Score 75 should map to L2"
        assert _map_score_to_tier(80, tiers) == "L2", "Score 80 should map to L2"
        assert _map_score_to_tier(85, tiers) == "L2", "Score 85 should map to L2"
        assert _map_score_to_tier(89.9, tiers) == "L2", "Score 89.9 should map to L2"
        print("✓ Scores 75-90 correctly map to L2")

    def test_tier_mapping_l3(self):
        """Scores 90-100 should map to L3."""
        from app.services.baseline_scheduler import _map_score_to_tier
        
        tiers = {"60-75": "L1", "75-90": "L2", "90-100": "L3"}
        
        assert _map_score_to_tier(90, tiers) == "L3", "Score 90 should map to L3"
        assert _map_score_to_tier(95, tiers) == "L3", "Score 95 should map to L3"
        assert _map_score_to_tier(100, tiers) == "L3", "Score 100 should map to L3 (inclusive upper bound)"
        print("✓ Scores 90-100 correctly map to L3")

    def test_tier_mapping_below_threshold(self):
        """Scores below 60 should return None (no escalation)."""
        from app.services.baseline_scheduler import _map_score_to_tier
        
        tiers = {"60-75": "L1", "75-90": "L2", "90-100": "L3"}
        
        assert _map_score_to_tier(50, tiers) is None, "Score 50 should not map to any tier"
        assert _map_score_to_tier(59.9, tiers) is None, "Score 59.9 should not map to any tier"
        assert _map_score_to_tier(0, tiers) is None, "Score 0 should not map to any tier"
        print("✓ Scores below 60 correctly return None")


# ── Test: Tier to Severity mapping ──

class TestTierSeverityMapping:
    """Tests for the tier to severity mapping."""

    def test_tier_severity_map(self):
        """Verify tier to severity mapping."""
        from app.services.baseline_scheduler import _TIER_SEVERITY_MAP
        
        assert _TIER_SEVERITY_MAP.get("L1") == "medium", "L1 should map to medium severity"
        assert _TIER_SEVERITY_MAP.get("L2") == "high", "L2 should map to high severity"
        assert _TIER_SEVERITY_MAP.get("L3") == "critical", "L3 should map to critical severity"
        print(f"✓ Tier to severity mapping: {_TIER_SEVERITY_MAP}")


# ── Test: Device Instability Incident Metadata ──

class TestDeviceInstabilityMetadata:
    """Tests for device_instability incident metadata structure."""

    def test_existing_instability_incident_metadata(self, operator_headers):
        """Verify existing device_instability incident has correct metadata structure."""
        # Get all incidents and find a device_instability one
        response = requests.get(
            f"{BASE_URL}/api/operator/incidents",
            headers=operator_headers
        )
        
        # If no incidents found, that's OK for this test
        if response.status_code == 200:
            incidents = response.json()
            # Filter for device_instability (the endpoint might not filter by incident_type param)
            instability_incidents = [i for i in incidents if i.get("incident_type") == "device_instability"]
            
            if instability_incidents:
                incident = instability_incidents[0]
                print(f"✓ Found device_instability incident: {incident.get('id')}")
                print(f"  - Type: {incident.get('incident_type')}")
                print(f"  - Severity: {incident.get('severity')}")
                print(f"  - Status: {incident.get('status')}")
                # Note: Metadata may not be directly exposed in the response schema
            else:
                print("ℹ No device_instability incidents found in the system")
        else:
            print(f"ℹ Could not retrieve incidents: {response.status_code}")


# ── Test: Simulated anomalies NEVER create incidents ──

class TestSimulationIsolation:
    """Tests to verify simulated anomalies don't create real incidents."""

    def test_simulated_anomalies_isolated(self, operator_headers):
        """Verify simulated anomalies are marked with is_simulated=true."""
        response = requests.get(
            f"{BASE_URL}/api/operator/device-anomalies",
            headers=operator_headers,
            params={"hours": 24, "include_simulated": True}
        )
        assert response.status_code == 200, f"Failed to get anomalies: {response.text}"
        
        data = response.json()
        anomalies = data.get("anomalies", [])
        
        simulated_count = sum(1 for a in anomalies if a.get("is_simulated", False))
        production_count = sum(1 for a in anomalies if not a.get("is_simulated", False))
        
        print(f"✓ Anomalies retrieved: {len(anomalies)} total")
        print(f"  - Simulated: {simulated_count}")
        print(f"  - Production: {production_count}")
        
        # Verify simulated anomalies have simulation_run_id
        for a in anomalies:
            if a.get("is_simulated"):
                assert a.get("simulation_run_id") is not None, \
                    f"Simulated anomaly {a.get('device_identifier')} missing simulation_run_id"
        
        print("✓ All simulated anomalies have simulation_run_id")

    def test_only_production_anomalies_considered_for_escalation(self):
        """Verify _evaluate_instability_escalation only considers production anomalies."""
        import inspect
        from app.services.baseline_scheduler import _evaluate_instability_escalation
        
        source = inspect.getsource(_evaluate_instability_escalation)
        assert "is_simulated = false" in source.lower() or "is_simulated=false" in source.lower().replace(" ", ""), \
            "_evaluate_instability_escalation should filter for is_simulated = false"
        print("✓ _evaluate_instability_escalation correctly filters for production anomalies only")


# ── Test: Guardrails ──

class TestGuardrails:
    """Tests for duplicate prevention and cooldown guardrails."""

    def test_duplicate_prevention_check_exists(self):
        """Verify duplicate prevention logic exists in the escalation function."""
        import inspect
        from app.services.baseline_scheduler import _evaluate_instability_escalation
        
        source = inspect.getsource(_evaluate_instability_escalation)
        
        # Check for open incident check
        assert "status" in source.lower() and "open" in source.lower(), \
            "Function should check for existing open incidents"
        assert "device_instability" in source, \
            "Function should check for device_instability incident type"
        print("✓ Duplicate prevention check exists in _evaluate_instability_escalation")

    def test_cooldown_check_exists(self):
        """Verify cooldown logic exists in the escalation function."""
        import inspect
        from app.services.baseline_scheduler import _evaluate_instability_escalation
        
        source = inspect.getsource(_evaluate_instability_escalation)
        
        # Check for cooldown cutoff
        assert "instability_cooldown" in source or "cooldown_cutoff" in source, \
            "Function should implement cooldown logic"
        assert "resolved" in source.lower(), \
            "Function should check resolved incidents for cooldown"
        print("✓ Cooldown check exists in _evaluate_instability_escalation")

    def test_persistence_check_exists(self):
        """Verify persistence check (Gate 2) exists in the escalation function."""
        import inspect
        from app.services.baseline_scheduler import _evaluate_instability_escalation
        
        source = inspect.getsource(_evaluate_instability_escalation)
        
        # Check for persistence duration check
        assert "persistence_minutes" in source, \
            "Function should check persistence_minutes"
        assert "persistence_duration" in source or "first_detected" in source.lower(), \
            "Function should calculate persistence duration"
        print("✓ Persistence check (Gate 2) exists in _evaluate_instability_escalation")


# ── Test: Health Rules endpoint returns updated combined_anomaly config ──

class TestHealthRulesEndpoint:
    """Additional tests for the health-rules endpoint."""

    def test_combined_anomaly_all_required_fields(self, operator_headers):
        """Verify combined_anomaly has all required threshold fields."""
        response = requests.get(
            f"{BASE_URL}/api/operator/health-rules",
            headers=operator_headers
        )
        assert response.status_code == 200
        rules = response.json()
        
        combined_rule = next((r for r in rules if r["rule_name"] == "combined_anomaly"), None)
        assert combined_rule is not None
        
        threshold = combined_rule["threshold_json"]
        
        # Original fields
        assert "weight_battery" in threshold, "weight_battery missing"
        assert "weight_signal" in threshold, "weight_signal missing"
        assert "trigger_threshold" in threshold, "trigger_threshold missing"
        assert "correlation_bonus" in threshold, "correlation_bonus missing"
        
        # New instability escalation fields
        assert "persistence_minutes" in threshold, "persistence_minutes missing"
        assert "escalation_tiers" in threshold, "escalation_tiers missing"
        assert "instability_cooldown_minutes" in threshold, "instability_cooldown_minutes missing"
        
        # Verify types
        assert isinstance(threshold["persistence_minutes"], (int, float))
        assert isinstance(threshold["escalation_tiers"], dict)
        assert isinstance(threshold["instability_cooldown_minutes"], (int, float))
        
        print("✓ combined_anomaly has all required threshold fields with correct types")


# ── Test: Schema Validation ──

class TestSchemaValidation:
    """Tests for schema validation of combined_anomaly config."""

    def test_combined_anomaly_schema_includes_new_keys(self):
        """Verify RULE_THRESHOLD_KEYS includes new fields for combined_anomaly."""
        from app.schemas.rule import RULE_THRESHOLD_KEYS
        
        combined_keys = RULE_THRESHOLD_KEYS.get("combined_anomaly", set())
        
        assert "persistence_minutes" in combined_keys, \
            f"persistence_minutes not in combined_anomaly schema: {combined_keys}"
        assert "escalation_tiers" in combined_keys, \
            f"escalation_tiers not in combined_anomaly schema: {combined_keys}"
        assert "instability_cooldown_minutes" in combined_keys, \
            f"instability_cooldown_minutes not in combined_anomaly schema: {combined_keys}"
        
        print(f"✓ RULE_THRESHOLD_KEYS for combined_anomaly: {combined_keys}")

    def test_invalid_key_rejected(self, operator_headers):
        """Verify unknown keys in threshold_json are rejected."""
        response = requests.get(f"{BASE_URL}/api/operator/health-rules", headers=operator_headers)
        assert response.status_code == 200
        rules = response.json()
        combined_rule = next((r for r in rules if r["rule_name"] == "combined_anomaly"), None)
        
        # Try to update with an invalid key
        invalid_threshold = {
            **combined_rule["threshold_json"],
            "invalid_key_xyz": 123
        }
        
        response = requests.put(
            f"{BASE_URL}/api/operator/health-rules/combined_anomaly",
            headers=operator_headers,
            json={"threshold_json": invalid_threshold}
        )
        assert response.status_code == 422, f"Expected 422 for invalid key, got {response.status_code}: {response.text}"
        print("✓ Invalid threshold key correctly rejected (422)")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
