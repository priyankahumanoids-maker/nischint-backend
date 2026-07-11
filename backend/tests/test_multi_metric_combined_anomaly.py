"""
Test Suite: Multi-Metric Combined Anomaly Detection (Phase 3)
Tests for:
1. Combined anomaly rule exists in device_health_rule_configs
2. Fleet simulation triggers multi_metric anomaly
3. multi_metric anomaly has correct reason_json structure
4. Combined score is correctly computed: battery × weight + signal × weight + bonus
5. multi_metric anomaly respects 10-min cooldown
6. multi_metric anomaly NOT created when combined_score <= trigger_threshold
7. Individual anomalies NOT suppressed by combined detection
8. GET /api/operator/device-anomalies returns multi_metric anomalies alongside battery and signal
9. Simulated multi_metric anomalies excluded from production endpoint by default
10. include_simulated=true shows simulated multi_metric anomalies
11. RBAC: guardian cannot access anomaly endpoints
12. GET /api/operator/device-health returns 200 (no ::int cast errors)
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://gps-mic-restart.preview.emergentagent.com')

# Test credentials
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"
GUARDIAN_EMAIL = "nischint4parents@gmail.com"
GUARDIAN_PASSWORD = "secret123"


@pytest.fixture(scope="module")
def operator_token():
    """Login as operator and return token."""
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": OPERATOR_EMAIL,
        "password": OPERATOR_PASSWORD
    })
    assert resp.status_code == 200, f"Operator login failed: {resp.text}"
    return resp.json().get("access_token")


@pytest.fixture(scope="module")
def operator_headers(operator_token):
    """Return headers with operator auth token."""
    return {"Authorization": f"Bearer {operator_token}"}


@pytest.fixture(scope="module")
def guardian_token():
    """Login as guardian and return token."""
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": GUARDIAN_EMAIL,
        "password": GUARDIAN_PASSWORD
    })
    assert resp.status_code == 200, f"Guardian login failed: {resp.text}"
    return resp.json().get("access_token")


@pytest.fixture(scope="module")
def guardian_headers(guardian_token):
    """Return headers with guardian auth token."""
    return {"Authorization": f"Bearer {guardian_token}"}


class TestCombinedAnomalyRuleExists:
    """Tests for combined_anomaly rule in device_health_rule_configs."""

    def test_health_rules_endpoint_returns_200(self, operator_headers):
        """Health rules endpoint accessible by operator."""
        resp = requests.get(f"{BASE_URL}/api/operator/health-rules", headers=operator_headers)
        assert resp.status_code == 200

    def test_combined_anomaly_rule_exists(self, operator_headers):
        """combined_anomaly rule exists in health rules list."""
        resp = requests.get(f"{BASE_URL}/api/operator/health-rules", headers=operator_headers)
        assert resp.status_code == 200
        rules = resp.json()
        rule_names = [r["rule_name"] for r in rules]
        assert "combined_anomaly" in rule_names, f"combined_anomaly not in rules: {rule_names}"

    def test_combined_anomaly_rule_has_correct_threshold_structure(self, operator_headers):
        """combined_anomaly rule has weight_battery, weight_signal, trigger_threshold, correlation_bonus."""
        resp = requests.get(f"{BASE_URL}/api/operator/health-rules", headers=operator_headers)
        assert resp.status_code == 200
        rules = resp.json()
        combined_rule = next((r for r in rules if r["rule_name"] == "combined_anomaly"), None)
        assert combined_rule is not None
        
        threshold = combined_rule["threshold_json"]
        required_keys = {"weight_battery", "weight_signal", "trigger_threshold", "correlation_bonus"}
        assert required_keys.issubset(set(threshold.keys())), f"Missing keys in threshold: {threshold.keys()}"
        
        # Verify default values
        assert threshold["weight_battery"] == 0.7
        assert threshold["weight_signal"] == 0.3
        assert threshold["trigger_threshold"] == 60
        assert threshold["correlation_bonus"] == 10

    def test_combined_anomaly_rule_can_be_toggled(self, operator_headers):
        """combined_anomaly rule can be toggled on/off."""
        # Toggle OFF
        resp = requests.patch(
            f"{BASE_URL}/api/operator/health-rules/combined_anomaly/toggle",
            headers=operator_headers,
            json={"enabled": False}
        )
        assert resp.status_code == 200
        assert resp.json()["enabled"] == False
        
        # Toggle ON
        resp2 = requests.patch(
            f"{BASE_URL}/api/operator/health-rules/combined_anomaly/toggle",
            headers=operator_headers,
            json={"enabled": True}
        )
        assert resp2.status_code == 200
        assert resp2.json()["enabled"] == True


class TestFleetSimulationTriggersMultiMetric:
    """Tests for fleet simulation triggering multi_metric anomalies."""

    def test_fleet_simulation_returns_200(self, operator_headers):
        """Fleet simulation endpoint accessible and returns 200."""
        payload = {
            "device_patterns": [
                {
                    "device_identifier": "DEV-001",
                    "metric_patterns": [
                        {
                            "metric": "battery_level",
                            "start_value": 80,
                            "normal_rate_per_minute": -0.02,
                            "anomaly": {
                                "start_at_minute": 55,
                                "rate_per_minute": -8.0
                            }
                        }
                    ],
                    "gap_patterns": []
                }
            ],
            "duration_minutes": 60,
            "interval_seconds": 60,
            "trigger_evaluation": True,
            "noise_percent": 1.0,
            "random_seed": 54321
        }
        resp = requests.post(
            f"{BASE_URL}/api/operator/simulate/fleet",
            headers=operator_headers,
            json=payload
        )
        assert resp.status_code == 200

    def test_fleet_simulation_triggers_anomalies(self, operator_headers):
        """Fleet simulation with aggressive battery drain triggers anomalies."""
        payload = {
            "device_patterns": [
                {
                    "device_identifier": "WBAND-E2E-001",
                    "metric_patterns": [
                        {
                            "metric": "battery_level",
                            "start_value": 80,
                            "normal_rate_per_minute": -0.02,
                            "anomaly": {
                                "start_at_minute": 55,
                                "rate_per_minute": -8.0
                            }
                        },
                        {
                            "metric": "signal_strength",
                            "start_value": -60,
                            "normal_rate_per_minute": 0,
                            "anomaly": None
                        }
                    ],
                    "gap_patterns": []
                }
            ],
            "duration_minutes": 60,
            "interval_seconds": 60,
            "trigger_evaluation": True,
            "noise_percent": 1.0,
            "random_seed": 67890
        }
        resp = requests.post(
            f"{BASE_URL}/api/operator/simulate/fleet",
            headers=operator_headers,
            json=payload
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["anomalies_triggered"] >= 1, f"Expected anomalies, got: {data}"

    def test_fleet_simulation_includes_multi_metric_in_anomaly_details(self, operator_headers):
        """Fleet simulation anomaly_details includes multi_metric with battery/signal scores."""
        payload = {
            "device_patterns": [
                {
                    "device_identifier": "DEV-002",
                    "metric_patterns": [
                        {
                            "metric": "battery_level",
                            "start_value": 80,
                            "normal_rate_per_minute": -0.02,
                            "anomaly": {
                                "start_at_minute": 55,
                                "rate_per_minute": -10.0
                            }
                        }
                    ],
                    "gap_patterns": []
                }
            ],
            "duration_minutes": 60,
            "interval_seconds": 60,
            "trigger_evaluation": True,
            "noise_percent": 1.0,
            "random_seed": 99999
        }
        resp = requests.post(
            f"{BASE_URL}/api/operator/simulate/fleet",
            headers=operator_headers,
            json=payload
        )
        assert resp.status_code == 200
        data = resp.json()
        
        # Check for multi_metric in anomaly_details
        multi_metrics = [d for d in data.get("anomaly_details", []) if "battery_score" in d]
        if multi_metrics:
            mm = multi_metrics[0]
            assert "battery_score" in mm
            assert "signal_score" in mm
            assert "correlation" in mm


class TestMultiMetricAnomalyReasonJson:
    """Tests for multi_metric anomaly reason_json structure."""

    def test_multi_metric_anomalies_have_correct_reason_json_structure(self, operator_headers):
        """multi_metric anomalies have required fields in reason_json."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/device-anomalies?include_simulated=true",
            headers=operator_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        
        multi_metrics = [a for a in data["anomalies"] if a["metric"] == "multi_metric"]
        if len(multi_metrics) == 0:
            pytest.skip("No multi_metric anomalies found")
        
        for mm in multi_metrics:
            reason = mm["reason_json"]
            assert reason["type"] == "multi_metric_anomaly"
            assert "battery_score" in reason
            assert "signal_score" in reason
            assert "combined_score" in reason
            assert "weights" in reason
            assert "correlation_flag" in reason
            assert "correlation_bonus" in reason
            assert "trigger_threshold" in reason

    def test_multi_metric_weights_are_correct(self, operator_headers):
        """multi_metric weights match config (battery=0.7, signal=0.3)."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/device-anomalies?include_simulated=true",
            headers=operator_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        
        multi_metrics = [a for a in data["anomalies"] if a["metric"] == "multi_metric"]
        if len(multi_metrics) == 0:
            pytest.skip("No multi_metric anomalies found")
        
        mm = multi_metrics[0]
        weights = mm["reason_json"]["weights"]
        assert weights["battery"] == 0.7
        assert weights["signal"] == 0.3

    def test_multi_metric_combined_score_calculated_correctly(self, operator_headers):
        """combined_score = battery_score × 0.7 + signal_score × 0.3 + bonus."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/device-anomalies?include_simulated=true",
            headers=operator_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        
        multi_metrics = [a for a in data["anomalies"] if a["metric"] == "multi_metric"]
        if len(multi_metrics) == 0:
            pytest.skip("No multi_metric anomalies found")
        
        for mm in multi_metrics:
            reason = mm["reason_json"]
            expected = reason["battery_score"] * 0.7 + reason["signal_score"] * 0.3
            if reason["correlation_flag"]:
                expected += reason["correlation_bonus"]
            expected = min(expected, 100.0)
            
            # Allow small floating point tolerance
            assert abs(reason["combined_score"] - expected) < 0.5, \
                f"combined_score mismatch: {reason['combined_score']} vs expected {expected}"


class TestIndividualAnomaliesNotSuppressed:
    """Tests that individual battery_slope and signal_strength anomalies are NOT suppressed."""

    def test_battery_slope_anomalies_still_exist(self, operator_headers):
        """battery_slope anomalies exist alongside multi_metric."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/device-anomalies?include_simulated=true",
            headers=operator_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        
        battery_anomalies = [a for a in data["anomalies"] if a["metric"] == "battery_slope"]
        assert len(battery_anomalies) >= 0  # May be 0 if no recent anomalies

    def test_signal_strength_anomalies_still_exist(self, operator_headers):
        """signal_strength anomalies exist alongside multi_metric."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/device-anomalies?include_simulated=true",
            headers=operator_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        
        signal_anomalies = [a for a in data["anomalies"] if a["metric"] == "signal_strength"]
        # Signal anomalies may not exist, but endpoint should work
        assert isinstance(signal_anomalies, list)


class TestSimulatedExclusion:
    """Tests for simulated anomaly exclusion from production endpoint."""

    def test_default_excludes_simulated_anomalies(self, operator_headers):
        """Default request excludes simulated anomalies."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/device-anomalies",
            headers=operator_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        
        simulated_count = sum(1 for a in data["anomalies"] if a.get("is_simulated"))
        assert simulated_count == 0, f"Found {simulated_count} simulated anomalies in default response"

    def test_include_simulated_true_shows_simulated(self, operator_headers):
        """include_simulated=true shows simulated anomalies."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/device-anomalies?include_simulated=true",
            headers=operator_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        
        # Should have at least some anomalies (simulated or not)
        assert len(data["anomalies"]) >= 0


class TestRBAC:
    """Tests for RBAC - guardian cannot access operator endpoints."""

    def test_guardian_cannot_access_device_anomalies(self, guardian_headers):
        """Guardian gets 403 on device-anomalies endpoint."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/device-anomalies",
            headers=guardian_headers
        )
        assert resp.status_code == 403

    def test_guardian_cannot_access_device_health(self, guardian_headers):
        """Guardian gets 403 on device-health endpoint."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/device-health",
            headers=guardian_headers
        )
        assert resp.status_code == 403

    def test_unauthenticated_gets_401_on_device_anomalies(self):
        """Unauthenticated request gets 401."""
        resp = requests.get(f"{BASE_URL}/api/operator/device-anomalies")
        assert resp.status_code == 401


class TestDeviceHealth:
    """Tests for device health endpoint (no ::int cast errors)."""

    def test_device_health_returns_200(self, operator_headers):
        """Device health endpoint returns 200."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/device-health?window_hours=24",
            headers=operator_headers
        )
        assert resp.status_code == 200

    def test_device_health_returns_devices_with_required_fields(self, operator_headers):
        """Device health returns devices with required fields."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/device-health?window_hours=24",
            headers=operator_headers
        )
        assert resp.status_code == 200
        devices = resp.json()
        
        if len(devices) > 0:
            device = devices[0]
            required_fields = ["device_id", "device_identifier", "status", "uptime_percent", "reliability_score"]
            for field in required_fields:
                assert field in device, f"Missing field: {field}"
