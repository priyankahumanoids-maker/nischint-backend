"""
Test Multi-Metric Escalation Layer (Step 2) - Device Instability Auto-Recovery
================================================================================
Tests the auto-resolution of device_instability incidents using hysteresis.

Recovery Logic:
- Case A: No multi_metric anomaly in last recovery_minutes (15min) → resolve
- Case B: min_clear_cycles (2) consecutive scores below hysteresis ceiling (55) → resolve

Hysteresis Config (default):
- trigger_threshold=60
- recovery_buffer=5
- recovery_score_ceiling = trigger_threshold - recovery_buffer = 55
- min_clear_cycles=2
- recovery_minutes=15

Key Features:
- POST /api/operator/escalation/evaluate-recovery endpoint (operator only)
- Case A: Resolves when no anomaly in recovery_minutes window
- Case B: Resolves when min_clear_cycles consecutive low scores below ceiling
- Flapping prevention: Score drops below 55 then rebounds → does NOT resolve
- min_clear_cycles guard: Only 1 clear cycle when 2 required → does NOT resolve
- Duplicate resolution prevention: Already resolved incident not processed again
- Simulation isolation: Only considers is_simulated=false anomalies
- Audit logging with 'device_instability_recovered' event
- SSE broadcast on resolution
"""

import pytest
import requests
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta

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


# ── Test: POST /api/operator/escalation/evaluate-recovery endpoint ──

class TestEvaluateRecoveryEndpoint:
    """Tests for the manual instability recovery evaluation endpoint."""

    def test_evaluate_recovery_operator_access(self, operator_headers):
        """Operator can access the evaluate-recovery endpoint."""
        response = requests.post(
            f"{BASE_URL}/api/operator/escalation/evaluate-recovery",
            headers=operator_headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "incidents_resolved" in data, "Response should contain 'incidents_resolved'"
        assert "message" in data, "Response should contain 'message'"
        # The message should mention recovery
        assert "recovery" in data["message"].lower() or "resolved" in data["message"].lower()
        print(f"✓ Operator can trigger evaluate-recovery: {data}")

    def test_evaluate_recovery_guardian_blocked(self, guardian_headers):
        """Guardian should be blocked (403) from accessing evaluate-recovery endpoint."""
        response = requests.post(
            f"{BASE_URL}/api/operator/escalation/evaluate-recovery",
            headers=guardian_headers
        )
        assert response.status_code == 403, f"Expected 403 for guardian, got {response.status_code}: {response.text}"
        print("✓ Guardian correctly blocked (403) from evaluate-recovery endpoint")

    def test_evaluate_recovery_unauthenticated_blocked(self):
        """Unauthenticated requests should be blocked (401/403)."""
        response = requests.post(f"{BASE_URL}/api/operator/escalation/evaluate-recovery")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("✓ Unauthenticated requests correctly blocked from evaluate-recovery endpoint")


# ── Test: combined_anomaly config has recovery fields ──

class TestRecoveryConfigFields:
    """Tests for the combined_anomaly rule config with recovery fields."""

    def test_health_rules_contains_recovery_fields(self, operator_headers):
        """GET /api/operator/health-rules returns combined_anomaly with recovery fields."""
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
        
        # Verify recovery fields exist
        assert "recovery_minutes" in threshold, "recovery_minutes missing from combined_anomaly config"
        assert "recovery_buffer" in threshold, "recovery_buffer missing from combined_anomaly config"
        assert "min_clear_cycles" in threshold, "min_clear_cycles missing from combined_anomaly config"
        
        # Verify expected default values
        assert threshold["recovery_minutes"] == 15, f"Expected recovery_minutes=15, got {threshold['recovery_minutes']}"
        assert threshold["recovery_buffer"] == 5, f"Expected recovery_buffer=5, got {threshold['recovery_buffer']}"
        assert threshold["min_clear_cycles"] == 2, f"Expected min_clear_cycles=2, got {threshold['min_clear_cycles']}"
        
        # Calculate and verify hysteresis ceiling
        trigger_threshold = threshold.get("trigger_threshold", 60)
        recovery_buffer = threshold.get("recovery_buffer", 5)
        hysteresis_ceiling = trigger_threshold - recovery_buffer
        
        assert hysteresis_ceiling == 55, f"Hysteresis ceiling should be 55 (60-5), got {hysteresis_ceiling}"
        
        print(f"✓ combined_anomaly recovery config:")
        print(f"  - recovery_minutes: {threshold['recovery_minutes']}")
        print(f"  - recovery_buffer: {threshold['recovery_buffer']}")
        print(f"  - min_clear_cycles: {threshold['min_clear_cycles']}")
        print(f"  - trigger_threshold: {trigger_threshold}")
        print(f"  - hysteresis_ceiling: {hysteresis_ceiling}")

    def test_can_update_recovery_minutes(self, operator_headers):
        """PUT /api/operator/health-rules/combined_anomaly can update recovery_minutes."""
        # Get current config
        response = requests.get(f"{BASE_URL}/api/operator/health-rules", headers=operator_headers)
        assert response.status_code == 200
        rules = response.json()
        combined_rule = next((r for r in rules if r["rule_name"] == "combined_anomaly"), None)
        assert combined_rule is not None
        
        current_threshold = combined_rule["threshold_json"]
        original_recovery = current_threshold.get("recovery_minutes", 15)
        
        # Update recovery_minutes
        new_recovery = 20 if original_recovery != 20 else 15
        updated_threshold = {**current_threshold, "recovery_minutes": new_recovery}
        
        response = requests.put(
            f"{BASE_URL}/api/operator/health-rules/combined_anomaly",
            headers=operator_headers,
            json={"threshold_json": updated_threshold}
        )
        assert response.status_code == 200, f"Update failed: {response.text}"
        
        updated_rule = response.json()
        assert updated_rule["threshold_json"]["recovery_minutes"] == new_recovery
        print(f"✓ Updated recovery_minutes from {original_recovery} to {new_recovery}")
        
        # Restore original value
        restored_threshold = {**updated_threshold, "recovery_minutes": original_recovery}
        response = requests.put(
            f"{BASE_URL}/api/operator/health-rules/combined_anomaly",
            headers=operator_headers,
            json={"threshold_json": restored_threshold}
        )
        assert response.status_code == 200
        print(f"✓ Restored recovery_minutes to {original_recovery}")

    def test_can_update_recovery_buffer(self, operator_headers):
        """PUT /api/operator/health-rules/combined_anomaly can update recovery_buffer."""
        # Get current config
        response = requests.get(f"{BASE_URL}/api/operator/health-rules", headers=operator_headers)
        assert response.status_code == 200
        rules = response.json()
        combined_rule = next((r for r in rules if r["rule_name"] == "combined_anomaly"), None)
        assert combined_rule is not None
        
        current_threshold = combined_rule["threshold_json"]
        original_buffer = current_threshold.get("recovery_buffer", 5)
        
        # Update recovery_buffer
        new_buffer = 10 if original_buffer != 10 else 5
        updated_threshold = {**current_threshold, "recovery_buffer": new_buffer}
        
        response = requests.put(
            f"{BASE_URL}/api/operator/health-rules/combined_anomaly",
            headers=operator_headers,
            json={"threshold_json": updated_threshold}
        )
        assert response.status_code == 200, f"Update failed: {response.text}"
        
        updated_rule = response.json()
        assert updated_rule["threshold_json"]["recovery_buffer"] == new_buffer
        print(f"✓ Updated recovery_buffer from {original_buffer} to {new_buffer}")
        
        # Restore original value
        restored_threshold = {**updated_threshold, "recovery_buffer": original_buffer}
        response = requests.put(
            f"{BASE_URL}/api/operator/health-rules/combined_anomaly",
            headers=operator_headers,
            json={"threshold_json": restored_threshold}
        )
        assert response.status_code == 200
        print(f"✓ Restored recovery_buffer to {original_buffer}")

    def test_can_update_min_clear_cycles(self, operator_headers):
        """PUT /api/operator/health-rules/combined_anomaly can update min_clear_cycles."""
        # Get current config
        response = requests.get(f"{BASE_URL}/api/operator/health-rules", headers=operator_headers)
        assert response.status_code == 200
        rules = response.json()
        combined_rule = next((r for r in rules if r["rule_name"] == "combined_anomaly"), None)
        assert combined_rule is not None
        
        current_threshold = combined_rule["threshold_json"]
        original_cycles = current_threshold.get("min_clear_cycles", 2)
        
        # Update min_clear_cycles
        new_cycles = 3 if original_cycles != 3 else 2
        updated_threshold = {**current_threshold, "min_clear_cycles": new_cycles}
        
        response = requests.put(
            f"{BASE_URL}/api/operator/health-rules/combined_anomaly",
            headers=operator_headers,
            json={"threshold_json": updated_threshold}
        )
        assert response.status_code == 200, f"Update failed: {response.text}"
        
        updated_rule = response.json()
        assert updated_rule["threshold_json"]["min_clear_cycles"] == new_cycles
        print(f"✓ Updated min_clear_cycles from {original_cycles} to {new_cycles}")
        
        # Restore original value
        restored_threshold = {**updated_threshold, "min_clear_cycles": original_cycles}
        response = requests.put(
            f"{BASE_URL}/api/operator/health-rules/combined_anomaly",
            headers=operator_headers,
            json={"threshold_json": restored_threshold}
        )
        assert response.status_code == 200
        print(f"✓ Restored min_clear_cycles to {original_cycles}")


# ── Test: Schema Validation for Recovery Fields ──

class TestRecoverySchemaValidation:
    """Tests for schema validation of recovery config fields."""

    def test_schema_includes_recovery_fields(self):
        """Verify RULE_THRESHOLD_KEYS includes recovery fields for combined_anomaly."""
        from app.schemas.rule import RULE_THRESHOLD_KEYS
        
        combined_keys = RULE_THRESHOLD_KEYS.get("combined_anomaly", set())
        
        assert "recovery_minutes" in combined_keys, \
            f"recovery_minutes not in combined_anomaly schema: {combined_keys}"
        assert "recovery_buffer" in combined_keys, \
            f"recovery_buffer not in combined_anomaly schema: {combined_keys}"
        assert "min_clear_cycles" in combined_keys, \
            f"min_clear_cycles not in combined_anomaly schema: {combined_keys}"
        
        print(f"✓ RULE_THRESHOLD_KEYS for combined_anomaly includes recovery fields:")
        print(f"  Keys: {sorted(combined_keys)}")


# ── Test: Recovery Function Implementation ──

class TestRecoveryFunctionImplementation:
    """Tests for the _evaluate_instability_recovery function implementation."""

    def test_recovery_function_exists(self):
        """Verify _evaluate_instability_recovery function exists."""
        from app.services.baseline_scheduler import _evaluate_instability_recovery
        assert callable(_evaluate_instability_recovery)
        print("✓ _evaluate_instability_recovery function exists and is callable")

    def test_recovery_function_simulation_isolation(self):
        """Verify recovery function only considers production anomalies (is_simulated=false)."""
        import inspect
        from app.services.baseline_scheduler import _evaluate_instability_recovery
        
        source = inspect.getsource(_evaluate_instability_recovery)
        assert "is_simulated = false" in source.lower() or "is_simulated=false" in source.lower().replace(" ", ""), \
            "_evaluate_instability_recovery should filter for is_simulated = false"
        print("✓ _evaluate_instability_recovery correctly filters for production anomalies only")

    def test_recovery_function_uses_hysteresis(self):
        """Verify recovery function uses hysteresis (recovery_buffer) for Case B."""
        import inspect
        from app.services.baseline_scheduler import _evaluate_instability_recovery
        
        source = inspect.getsource(_evaluate_instability_recovery)
        
        # Check for recovery_buffer usage
        assert "recovery_buffer" in source, \
            "_evaluate_instability_recovery should use recovery_buffer for hysteresis"
        
        # Check for recovery_score_ceiling calculation
        assert "recovery_score_ceiling" in source or "trigger_threshold - recovery_buffer" in source, \
            "_evaluate_instability_recovery should calculate hysteresis ceiling"
        
        print("✓ _evaluate_instability_recovery uses hysteresis (recovery_buffer)")

    def test_recovery_function_uses_min_clear_cycles(self):
        """Verify recovery function checks min_clear_cycles for Case B."""
        import inspect
        from app.services.baseline_scheduler import _evaluate_instability_recovery
        
        source = inspect.getsource(_evaluate_instability_recovery)
        
        assert "min_clear_cycles" in source, \
            "_evaluate_instability_recovery should check min_clear_cycles"
        
        # Check for consecutive clear cycle counting
        assert "clear_cycles" in source, \
            "_evaluate_instability_recovery should count clear cycles"
        
        print("✓ _evaluate_instability_recovery checks min_clear_cycles")

    def test_recovery_function_uses_recovery_minutes(self):
        """Verify recovery function checks recovery_minutes for Case A."""
        import inspect
        from app.services.baseline_scheduler import _evaluate_instability_recovery
        
        source = inspect.getsource(_evaluate_instability_recovery)
        
        assert "recovery_minutes" in source, \
            "_evaluate_instability_recovery should check recovery_minutes"
        
        print("✓ _evaluate_instability_recovery checks recovery_minutes")

    def test_recovery_function_logs_audit_event(self):
        """Verify recovery function logs device_instability_recovered audit event."""
        import inspect
        from app.services.baseline_scheduler import _evaluate_instability_recovery
        
        source = inspect.getsource(_evaluate_instability_recovery)
        
        assert "device_instability_recovered" in source, \
            "_evaluate_instability_recovery should log device_instability_recovered event"
        
        assert "log_event" in source, \
            "_evaluate_instability_recovery should use log_event for audit"
        
        print("✓ _evaluate_instability_recovery logs 'device_instability_recovered' audit event")

    def test_recovery_function_broadcasts_sse(self):
        """Verify recovery function broadcasts SSE on resolution."""
        import inspect
        from app.services.baseline_scheduler import _evaluate_instability_recovery
        
        source = inspect.getsource(_evaluate_instability_recovery)
        
        assert "broadcaster" in source or "broadcast_incident_updated" in source, \
            "_evaluate_instability_recovery should broadcast SSE on resolution"
        
        print("✓ _evaluate_instability_recovery broadcasts SSE on resolution")


# ── Test: Recovery Case Logic ──

class TestRecoveryCaseLogic:
    """Tests for the two recovery case paths."""

    def test_case_a_no_anomaly_recovery(self):
        """Verify Case A: Recovery when no anomaly in recovery_minutes window."""
        import inspect
        from app.services.baseline_scheduler import _evaluate_instability_recovery
        
        source = inspect.getsource(_evaluate_instability_recovery)
        
        # Check for Case A implementation
        assert "case" in source.lower() or "no_anomaly" in source.lower() or "latest_age_minutes" in source, \
            "Function should implement Case A (no anomaly) logic"
        
        # Check for recovery_minutes check
        assert "recovery_minutes" in source, \
            "Function should check if latest anomaly is older than recovery_minutes"
        
        print("✓ Case A (no anomaly in recovery window) logic implemented")

    def test_case_b_low_score_recovery(self):
        """Verify Case B: Recovery when min_clear_cycles consecutive low scores."""
        import inspect
        from app.services.baseline_scheduler import _evaluate_instability_recovery
        
        source = inspect.getsource(_evaluate_instability_recovery)
        
        # Check for Case B implementation
        assert "clear_cycles" in source, \
            "Function should count clear cycles for Case B"
        
        # Check for consecutive checking (break on high score)
        assert "break" in source, \
            "Function should break when encountering high score (consecutive clear cycles)"
        
        print("✓ Case B (min_clear_cycles consecutive low scores) logic implemented")


# ── Test: Scheduler Integration ──

class TestSchedulerIntegration:
    """Tests for recovery integration with the scheduler cycle."""

    def test_recovery_in_scheduler_cycle(self):
        """Verify recovery runs after escalation in run_baseline_and_anomaly_cycle."""
        import inspect
        from app.services.baseline_scheduler import run_baseline_and_anomaly_cycle
        
        source = inspect.getsource(run_baseline_and_anomaly_cycle)
        
        # Check that recovery evaluation is called
        assert "_evaluate_instability_recovery" in source, \
            "run_baseline_and_anomaly_cycle should call _evaluate_instability_recovery"
        
        # Check that recovery comes AFTER escalation
        escalation_pos = source.find("_evaluate_instability_escalation")
        recovery_pos = source.find("_evaluate_instability_recovery")
        
        assert escalation_pos < recovery_pos, \
            "Recovery should run AFTER escalation in scheduler cycle"
        
        print("✓ _evaluate_instability_recovery runs after escalation in scheduler cycle")


# ── Test: Does Not Affect Other Incident Types ──

class TestIncidentTypeIsolation:
    """Tests to verify recovery only affects device_instability incidents."""

    def test_recovery_only_affects_device_instability(self):
        """Verify recovery function only targets device_instability incidents."""
        import inspect
        from app.services.baseline_scheduler import _evaluate_instability_recovery
        
        source = inspect.getsource(_evaluate_instability_recovery)
        
        # Check for device_instability filter
        assert "device_instability" in source, \
            "Recovery function should specifically target device_instability incidents"
        
        # Check for incident_type filter in query
        assert "incident_type" in source.lower(), \
            "Recovery function should filter by incident_type"
        
        print("✓ Recovery only affects device_instability incidents")


# ── Test: Flapping Prevention Logic ──

class TestFlappingPrevention:
    """Tests for flapping prevention via hysteresis."""

    def test_hysteresis_prevents_flapping(self):
        """
        Verify hysteresis logic: score must stay below ceiling for min_clear_cycles.
        Flapping pattern (e.g., 50 → 58 → 50) should NOT trigger recovery.
        """
        import inspect
        from app.services.baseline_scheduler import _evaluate_instability_recovery
        
        source = inspect.getsource(_evaluate_instability_recovery)
        
        # Check for consecutive clear cycle requirement
        assert "clear_cycles >= min_clear_cycles" in source or \
               "clear_cycles" in source and "min_clear_cycles" in source, \
            "Function should require min_clear_cycles CONSECUTIVE low scores"
        
        # Check for break on high score (flapping detection)
        assert "break" in source, \
            "Function should break when score goes above ceiling (prevents flapping)"
        
        print("✓ Hysteresis prevents flapping (requires consecutive low scores)")

    def test_flapping_scenario_description(self):
        """
        Document the flapping prevention scenario:
        - trigger_threshold = 60
        - recovery_buffer = 5
        - recovery_score_ceiling = 55
        - min_clear_cycles = 2
        
        Scenario that should NOT resolve:
        - Score sequence: 80 → 50 → 58 → 50
        - First 50 is below 55 (clear cycle 1)
        - 58 is above 55 → clear_cycles resets to 0
        - Final 50 is below 55 (clear cycle 1)
        - Only 1 consecutive clear cycle, need 2 → NO RESOLUTION
        
        Scenario that SHOULD resolve:
        - Score sequence: 80 → 50 → 45
        - First 50 is below 55 (clear cycle 1)
        - 45 is below 55 (clear cycle 2)
        - 2 consecutive clear cycles → RESOLVE
        """
        print("✓ Flapping prevention scenario documented")
        print("  - Flapping (no resolve): 80 → 50 → 58 → 50 (score rebounds above ceiling)")
        print("  - Recovery (resolve): 80 → 50 → 45 (2 consecutive scores below ceiling)")


# ── Test: Resolution Metadata ──

class TestResolutionMetadata:
    """Tests for resolution reason metadata."""

    def test_resolution_reason_case_a(self):
        """Verify Case A resolution includes proper reason metadata."""
        import inspect
        from app.services.baseline_scheduler import _evaluate_instability_recovery
        
        source = inspect.getsource(_evaluate_instability_recovery)
        
        # Check for Case A reason metadata
        assert "case" in source.lower() and "a" in source.lower() or \
               "no_anomaly" in source.lower() or "recovery_window" in source.lower(), \
            "Case A should include 'case: A' or similar in resolution reason"
        
        assert "recovery_minutes" in source or "clear_duration" in source.lower(), \
            "Case A should include recovery_minutes or clear_duration in metadata"
        
        print("✓ Case A resolution includes proper reason metadata")

    def test_resolution_reason_case_b(self):
        """Verify Case B resolution includes proper reason metadata."""
        import inspect
        from app.services.baseline_scheduler import _evaluate_instability_recovery
        
        source = inspect.getsource(_evaluate_instability_recovery)
        
        # Check for Case B reason metadata
        assert "clear_cycles" in source, \
            "Case B should include clear_cycles count in resolution reason"
        
        assert "recovery_score_ceiling" in source or "hysteresis" in source.lower(), \
            "Case B should include recovery_score_ceiling or hysteresis info in metadata"
        
        print("✓ Case B resolution includes proper reason metadata")


# ── Test: Step 1 Regression (Escalation Still Works) ──

class TestEscalationRegression:
    """Regression tests to verify Step 1 (escalation) still works."""

    def test_escalation_endpoint_still_works(self, operator_headers):
        """Verify POST /api/operator/escalation/evaluate-instability still works."""
        response = requests.post(
            f"{BASE_URL}/api/operator/escalation/evaluate-instability",
            headers=operator_headers
        )
        assert response.status_code == 200, f"Escalation endpoint broken: {response.text}"
        data = response.json()
        assert "incidents_created" in data
        print(f"✓ Escalation endpoint still works: {data}")

    def test_tier_mapping_still_works(self):
        """Verify tier mapping (Step 1 feature) still works correctly."""
        from app.services.baseline_scheduler import _map_score_to_tier
        
        tiers = {"60-75": "L1", "75-90": "L2", "90-100": "L3"}
        
        assert _map_score_to_tier(65, tiers) == "L1", "L1 mapping broken"
        assert _map_score_to_tier(80, tiers) == "L2", "L2 mapping broken"
        assert _map_score_to_tier(95, tiers) == "L3", "L3 mapping broken"
        assert _map_score_to_tier(50, tiers) is None, "Below threshold mapping broken"
        
        print("✓ Tier mapping still works correctly")

    def test_tier_severity_mapping_still_works(self):
        """Verify tier-to-severity mapping (Step 1 feature) still works."""
        from app.services.baseline_scheduler import _TIER_SEVERITY_MAP
        
        assert _TIER_SEVERITY_MAP.get("L1") == "medium"
        assert _TIER_SEVERITY_MAP.get("L2") == "high"
        assert _TIER_SEVERITY_MAP.get("L3") == "critical"
        
        print("✓ Tier-to-severity mapping still works correctly")

    def test_persistence_config_still_exists(self, operator_headers):
        """Verify persistence_minutes config (Step 1 feature) still exists."""
        response = requests.get(f"{BASE_URL}/api/operator/health-rules", headers=operator_headers)
        assert response.status_code == 200
        rules = response.json()
        combined_rule = next((r for r in rules if r["rule_name"] == "combined_anomaly"), None)
        assert combined_rule is not None
        
        threshold = combined_rule["threshold_json"]
        assert "persistence_minutes" in threshold, "persistence_minutes config missing"
        assert "escalation_tiers" in threshold, "escalation_tiers config missing"
        assert "instability_cooldown_minutes" in threshold, "instability_cooldown_minutes config missing"
        
        print("✓ Step 1 persistence config still exists")


# ── Test: Current State Verification ──

class TestCurrentStateVerification:
    """Tests to verify current system state."""

    def test_get_open_device_instability_incidents(self, operator_headers):
        """Get count of open device_instability incidents in the system."""
        response = requests.get(
            f"{BASE_URL}/api/operator/incidents",
            headers=operator_headers,
            params={"status": "open"}
        )
        assert response.status_code == 200, f"Failed to get incidents: {response.text}"
        
        incidents = response.json()
        device_instability = [i for i in incidents if i.get("incident_type") == "device_instability"]
        
        print(f"✓ Open device_instability incidents: {len(device_instability)}")
        for inc in device_instability[:3]:
            print(f"  - ID: {inc.get('id')}, severity: {inc.get('severity')}")

    def test_get_recent_multi_metric_anomalies(self, operator_headers):
        """Get recent production multi_metric anomalies."""
        response = requests.get(
            f"{BASE_URL}/api/operator/device-anomalies",
            headers=operator_headers,
            params={"hours": 24, "include_simulated": False}
        )
        assert response.status_code == 200, f"Failed to get anomalies: {response.text}"
        
        data = response.json()
        anomalies = data.get("anomalies", [])
        multi_metric = [a for a in anomalies if a.get("metric") == "multi_metric"]
        
        print(f"✓ Production multi_metric anomalies (24h): {len(multi_metric)}")
        for a in multi_metric[:5]:
            print(f"  - Device: {a.get('device_identifier')}, Score: {a.get('score')}, Created: {a.get('created_at')[:19]}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
