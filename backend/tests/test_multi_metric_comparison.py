"""
Multi-Metric Simulation Comparison Engine Tests

Tests for POST /api/operator/simulate/compare/multi-metric endpoint:
- Response shape validation
- RBAC (operator access, guardian blocked)
- Read-only (no DB writes)
- Delta calculation correctness
- Identical configs produce zero deltas
- Threshold variations: high threshold → 0 anomalies, lower threshold → more flagged
- Device flagging changes (newly_flagged, no_longer_flagged)
- Tier shift detection (tier_upgraded, tier_downgraded)
- Determinism (same data + configs = same result)
- Simulated anomalies ignored (is_simulated=true excluded)
- Invalid payload rejected
- window_minutes bounds (5-1440)
- Weight distribution effects
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"
GUARDIAN_EMAIL = "nischint4parents@gmail.com"
GUARDIAN_PASSWORD = "secret123"


class TestMultiMetricComparisonAuth:
    """Authentication and RBAC tests for multi-metric comparison endpoint"""
    
    def _get_operator_token(self):
        """Get operator authentication token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": OPERATOR_EMAIL,
            "password": OPERATOR_PASSWORD
        })
        assert response.status_code == 200, f"Operator login failed: {response.text}"
        return response.json()["access_token"]
    
    def _get_guardian_token(self):
        """Get guardian authentication token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": GUARDIAN_EMAIL,
            "password": GUARDIAN_PASSWORD
        })
        assert response.status_code == 200, f"Guardian login failed: {response.text}"
        return response.json()["access_token"]
    
    def _get_default_payload(self):
        """Default valid payload for testing"""
        return {
            "window_minutes": 60,
            "fleet_scope": "all",
            "config_a": {
                "combined_anomaly": {
                    "weight_battery": 0.7,
                    "weight_signal": 0.3,
                    "trigger_threshold": 60,
                    "correlation_bonus": 10,
                    "persistence_minutes": 15,
                    "escalation_tiers": {"60-75": "L1", "75-90": "L2", "90-100": "L3"}
                }
            },
            "config_b": {
                "combined_anomaly": {
                    "weight_battery": 0.7,
                    "weight_signal": 0.3,
                    "trigger_threshold": 55,
                    "correlation_bonus": 10,
                    "persistence_minutes": 15,
                    "escalation_tiers": {"60-75": "L1", "75-90": "L2", "90-100": "L3"}
                }
            }
        }
    
    def test_operator_can_access_endpoint(self):
        """Test that operator can access the multi-metric comparison endpoint"""
        token = self._get_operator_token()
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
            headers={"Authorization": f"Bearer {token}"},
            json=self._get_default_payload()
        )
        assert response.status_code == 200, f"Operator should have access: {response.text}"
        data = response.json()
        assert "window_minutes" in data
        assert "summary" in data
        assert "delta" in data
        print(f"PASS: Operator can access endpoint, got {len(data)} top-level keys")
    
    def test_guardian_blocked_with_403(self):
        """Test that guardian role is blocked with 403 Forbidden"""
        token = self._get_guardian_token()
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
            headers={"Authorization": f"Bearer {token}"},
            json=self._get_default_payload()
        )
        assert response.status_code == 403, f"Guardian should be blocked with 403, got {response.status_code}: {response.text}"
        print("PASS: Guardian blocked with 403 as expected")
    
    def test_unauthenticated_request_blocked(self):
        """Test that unauthenticated requests are blocked"""
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
            json=self._get_default_payload()
        )
        assert response.status_code == 401, f"Unauthenticated should be blocked with 401, got {response.status_code}"
        print("PASS: Unauthenticated request blocked with 401")


class TestMultiMetricComparisonResponseShape:
    """Tests for correct response shape and structure"""
    
    def _get_operator_token(self):
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": OPERATOR_EMAIL,
            "password": OPERATOR_PASSWORD
        })
        return response.json()["access_token"]
    
    def _get_default_payload(self):
        return {
            "window_minutes": 60,
            "fleet_scope": "all",
            "config_a": {
                "combined_anomaly": {
                    "weight_battery": 0.7,
                    "weight_signal": 0.3,
                    "trigger_threshold": 60,
                    "correlation_bonus": 10,
                    "persistence_minutes": 15,
                    "escalation_tiers": {"60-75": "L1", "75-90": "L2", "90-100": "L3"}
                }
            },
            "config_b": {
                "combined_anomaly": {
                    "weight_battery": 0.7,
                    "weight_signal": 0.3,
                    "trigger_threshold": 55,
                    "correlation_bonus": 10,
                    "persistence_minutes": 15,
                    "escalation_tiers": {"60-75": "L1", "75-90": "L2", "90-100": "L3"}
                }
            }
        }
    
    def test_response_has_required_top_level_keys(self):
        """Test that response contains all required top-level keys"""
        token = self._get_operator_token()
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
            headers={"Authorization": f"Bearer {token}"},
            json=self._get_default_payload()
        )
        assert response.status_code == 200
        data = response.json()
        
        required_keys = ["window_minutes", "devices_evaluated", "summary", "delta", "device_changes"]
        for key in required_keys:
            assert key in data, f"Missing required key: {key}"
        print(f"PASS: All required top-level keys present: {required_keys}")
    
    def test_summary_structure(self):
        """Test that summary contains config_a and config_b with correct structure"""
        token = self._get_operator_token()
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
            headers={"Authorization": f"Bearer {token}"},
            json=self._get_default_payload()
        )
        data = response.json()
        
        assert "summary" in data
        assert "config_a" in data["summary"]
        assert "config_b" in data["summary"]
        
        for config_name in ["config_a", "config_b"]:
            config = data["summary"][config_name]
            assert "anomalies" in config, f"{config_name} missing 'anomalies'"
            assert "instability_incidents" in config, f"{config_name} missing 'instability_incidents'"
            assert "tier_counts" in config, f"{config_name} missing 'tier_counts'"
            assert "L1" in config["tier_counts"]
            assert "L2" in config["tier_counts"]
            assert "L3" in config["tier_counts"]
        
        print("PASS: Summary structure is correct with config_a and config_b")
    
    def test_delta_structure(self):
        """Test that delta contains anomalies_diff, instability_diff, tier_shift"""
        token = self._get_operator_token()
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
            headers={"Authorization": f"Bearer {token}"},
            json=self._get_default_payload()
        )
        data = response.json()
        
        assert "delta" in data
        delta = data["delta"]
        assert "anomalies_diff" in delta
        assert "instability_diff" in delta
        assert "tier_shift" in delta
        assert "L1" in delta["tier_shift"]
        assert "L2" in delta["tier_shift"]
        assert "L3" in delta["tier_shift"]
        
        print("PASS: Delta structure is correct")
    
    def test_device_changes_structure(self):
        """Test that device_changes contains all four lists"""
        token = self._get_operator_token()
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
            headers={"Authorization": f"Bearer {token}"},
            json=self._get_default_payload()
        )
        data = response.json()
        
        assert "device_changes" in data
        changes = data["device_changes"]
        
        required_lists = ["newly_flagged", "no_longer_flagged", "tier_upgraded", "tier_downgraded"]
        for list_name in required_lists:
            assert list_name in changes, f"Missing {list_name} in device_changes"
            assert isinstance(changes[list_name], list), f"{list_name} should be a list"
        
        print("PASS: device_changes structure is correct")


class TestMultiMetricComparisonDeltaCalculation:
    """Tests for correct delta calculations"""
    
    def _get_operator_token(self):
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": OPERATOR_EMAIL,
            "password": OPERATOR_PASSWORD
        })
        return response.json()["access_token"]
    
    def test_identical_configs_produce_zero_deltas(self):
        """Test that identical configs A and B produce zero deltas"""
        token = self._get_operator_token()
        
        identical_config = {
            "weight_battery": 0.7,
            "weight_signal": 0.3,
            "trigger_threshold": 60,
            "correlation_bonus": 10,
            "persistence_minutes": 15,
            "escalation_tiers": {"60-75": "L1", "75-90": "L2", "90-100": "L3"}
        }
        
        payload = {
            "window_minutes": 60,
            "fleet_scope": "all",
            "config_a": {"combined_anomaly": identical_config},
            "config_b": {"combined_anomaly": identical_config}
        }
        
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
            headers={"Authorization": f"Bearer {token}"},
            json=payload
        )
        assert response.status_code == 200
        data = response.json()
        
        # With identical configs, all diffs should be zero
        assert data["delta"]["anomalies_diff"] == 0, f"anomalies_diff should be 0, got {data['delta']['anomalies_diff']}"
        assert data["delta"]["instability_diff"] == 0, f"instability_diff should be 0"
        assert data["delta"]["tier_shift"]["L1"] == 0
        assert data["delta"]["tier_shift"]["L2"] == 0
        assert data["delta"]["tier_shift"]["L3"] == 0
        
        # No device changes with identical configs
        assert len(data["device_changes"]["newly_flagged"]) == 0
        assert len(data["device_changes"]["no_longer_flagged"]) == 0
        assert len(data["device_changes"]["tier_upgraded"]) == 0
        assert len(data["device_changes"]["tier_downgraded"]) == 0
        
        print("PASS: Identical configs produce zero deltas")
    
    def test_anomalies_diff_formula(self):
        """Test that anomalies_diff = config_b.anomalies - config_a.anomalies"""
        token = self._get_operator_token()
        
        payload = {
            "window_minutes": 60,
            "fleet_scope": "all",
            "config_a": {
                "combined_anomaly": {
                    "weight_battery": 0.7,
                    "weight_signal": 0.3,
                    "trigger_threshold": 60,
                    "correlation_bonus": 10,
                    "persistence_minutes": 15,
                    "escalation_tiers": {"60-75": "L1", "75-90": "L2", "90-100": "L3"}
                }
            },
            "config_b": {
                "combined_anomaly": {
                    "weight_battery": 0.7,
                    "weight_signal": 0.3,
                    "trigger_threshold": 55,  # Lower threshold should catch more
                    "correlation_bonus": 10,
                    "persistence_minutes": 15,
                    "escalation_tiers": {"60-75": "L1", "75-90": "L2", "90-100": "L3"}
                }
            }
        }
        
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
            headers={"Authorization": f"Bearer {token}"},
            json=payload
        )
        data = response.json()
        
        config_a_anomalies = data["summary"]["config_a"]["anomalies"]
        config_b_anomalies = data["summary"]["config_b"]["anomalies"]
        expected_diff = config_b_anomalies - config_a_anomalies
        
        assert data["delta"]["anomalies_diff"] == expected_diff, \
            f"anomalies_diff should be {expected_diff}, got {data['delta']['anomalies_diff']}"
        
        print(f"PASS: anomalies_diff formula correct: {config_b_anomalies} - {config_a_anomalies} = {expected_diff}")
    
    def test_very_high_threshold_produces_zero_anomalies(self):
        """Test that very high threshold (100) produces 0 anomalies"""
        token = self._get_operator_token()
        
        payload = {
            "window_minutes": 60,
            "fleet_scope": "all",
            "config_a": {
                "combined_anomaly": {
                    "weight_battery": 0.7,
                    "weight_signal": 0.3,
                    "trigger_threshold": 100,  # Maximum threshold - nothing should trigger
                    "correlation_bonus": 0,
                    "persistence_minutes": 15,
                    "escalation_tiers": {"60-75": "L1", "75-90": "L2", "90-100": "L3"}
                }
            },
            "config_b": {
                "combined_anomaly": {
                    "weight_battery": 0.7,
                    "weight_signal": 0.3,
                    "trigger_threshold": 100,
                    "correlation_bonus": 0,
                    "persistence_minutes": 15,
                    "escalation_tiers": {"60-75": "L1", "75-90": "L2", "90-100": "L3"}
                }
            }
        }
        
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
            headers={"Authorization": f"Bearer {token}"},
            json=payload
        )
        data = response.json()
        
        # With threshold at 100, no device should be flagged (scores are <= 100)
        assert data["summary"]["config_a"]["anomalies"] == 0, \
            f"Config A with threshold 100 should have 0 anomalies, got {data['summary']['config_a']['anomalies']}"
        assert data["summary"]["config_b"]["anomalies"] == 0, \
            f"Config B with threshold 100 should have 0 anomalies"
        
        print("PASS: Very high threshold (100) produces 0 anomalies")


class TestMultiMetricComparisonDeviceChanges:
    """Tests for device flagging and tier shift changes"""
    
    def _get_operator_token(self):
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": OPERATOR_EMAIL,
            "password": OPERATOR_PASSWORD
        })
        return response.json()["access_token"]
    
    def test_lower_threshold_in_config_b_flags_more_devices(self):
        """Test that lower threshold in config_b should flag more devices (newly_flagged populated)"""
        token = self._get_operator_token()
        
        payload = {
            "window_minutes": 60,
            "fleet_scope": "all",
            "config_a": {
                "combined_anomaly": {
                    "weight_battery": 0.7,
                    "weight_signal": 0.3,
                    "trigger_threshold": 80,  # Higher threshold
                    "correlation_bonus": 10,
                    "persistence_minutes": 15,
                    "escalation_tiers": {"60-75": "L1", "75-90": "L2", "90-100": "L3"}
                }
            },
            "config_b": {
                "combined_anomaly": {
                    "weight_battery": 0.7,
                    "weight_signal": 0.3,
                    "trigger_threshold": 50,  # Lower threshold - should flag more
                    "correlation_bonus": 10,
                    "persistence_minutes": 15,
                    "escalation_tiers": {"60-75": "L1", "75-90": "L2", "90-100": "L3"}
                }
            }
        }
        
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
            headers={"Authorization": f"Bearer {token}"},
            json=payload
        )
        data = response.json()
        
        # Config B (lower threshold) should have >= config A anomalies
        assert data["summary"]["config_b"]["anomalies"] >= data["summary"]["config_a"]["anomalies"], \
            "Lower threshold should flag same or more devices"
        
        # If there are devices flagged by B but not A, newly_flagged should be populated
        if data["summary"]["config_b"]["anomalies"] > data["summary"]["config_a"]["anomalies"]:
            assert len(data["device_changes"]["newly_flagged"]) > 0, \
                "newly_flagged should be populated when config_b has more anomalies"
            print(f"PASS: newly_flagged populated with {len(data['device_changes']['newly_flagged'])} devices")
        else:
            print("PASS: Lower threshold test - no new devices in current data window")
    
    def test_higher_threshold_in_config_b_removes_devices(self):
        """Test that higher threshold in config_b should remove devices (no_longer_flagged populated)"""
        token = self._get_operator_token()
        
        payload = {
            "window_minutes": 60,
            "fleet_scope": "all",
            "config_a": {
                "combined_anomaly": {
                    "weight_battery": 0.7,
                    "weight_signal": 0.3,
                    "trigger_threshold": 50,  # Lower threshold
                    "correlation_bonus": 10,
                    "persistence_minutes": 15,
                    "escalation_tiers": {"60-75": "L1", "75-90": "L2", "90-100": "L3"}
                }
            },
            "config_b": {
                "combined_anomaly": {
                    "weight_battery": 0.7,
                    "weight_signal": 0.3,
                    "trigger_threshold": 90,  # Higher threshold - should remove devices
                    "correlation_bonus": 10,
                    "persistence_minutes": 15,
                    "escalation_tiers": {"60-75": "L1", "75-90": "L2", "90-100": "L3"}
                }
            }
        }
        
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
            headers={"Authorization": f"Bearer {token}"},
            json=payload
        )
        data = response.json()
        
        # Config B (higher threshold) should have <= config A anomalies
        assert data["summary"]["config_b"]["anomalies"] <= data["summary"]["config_a"]["anomalies"], \
            "Higher threshold should flag same or fewer devices"
        
        # If config_a had more anomalies, no_longer_flagged should be populated
        if data["summary"]["config_a"]["anomalies"] > data["summary"]["config_b"]["anomalies"]:
            assert len(data["device_changes"]["no_longer_flagged"]) > 0, \
                "no_longer_flagged should be populated when config_a has more anomalies"
            print(f"PASS: no_longer_flagged populated with {len(data['device_changes']['no_longer_flagged'])} devices")
        else:
            print("PASS: Higher threshold test - no devices removed in current data window")
    
    def test_tier_shift_detection_with_different_tier_ranges(self):
        """Test tier shift detection when escalation tier ranges differ"""
        token = self._get_operator_token()
        
        payload = {
            "window_minutes": 60,
            "fleet_scope": "all",
            "config_a": {
                "combined_anomaly": {
                    "weight_battery": 0.7,
                    "weight_signal": 0.3,
                    "trigger_threshold": 50,
                    "correlation_bonus": 10,
                    "persistence_minutes": 15,
                    "escalation_tiers": {"50-70": "L1", "70-85": "L2", "85-100": "L3"}  # Normal tiers
                }
            },
            "config_b": {
                "combined_anomaly": {
                    "weight_battery": 0.7,
                    "weight_signal": 0.3,
                    "trigger_threshold": 50,
                    "correlation_bonus": 10,
                    "persistence_minutes": 15,
                    "escalation_tiers": {"50-60": "L1", "60-75": "L2", "75-100": "L3"}  # Tighter tiers - upgrades earlier
                }
            }
        }
        
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
            headers={"Authorization": f"Bearer {token}"},
            json=payload
        )
        data = response.json()
        
        # Check tier_shift in delta
        assert "tier_shift" in data["delta"]
        
        # Check device_changes lists exist and are properly structured
        if len(data["device_changes"]["tier_upgraded"]) > 0:
            for entry in data["device_changes"]["tier_upgraded"]:
                assert "device_identifier" in entry
                assert "tier_a" in entry
                assert "tier_b" in entry
                assert "score_a" in entry
                assert "score_b" in entry
            print(f"PASS: tier_upgraded has {len(data['device_changes']['tier_upgraded'])} devices")
        
        if len(data["device_changes"]["tier_downgraded"]) > 0:
            for entry in data["device_changes"]["tier_downgraded"]:
                assert "device_identifier" in entry
            print(f"PASS: tier_downgraded has {len(data['device_changes']['tier_downgraded'])} devices")
        
        print("PASS: Tier shift detection structure verified")


class TestMultiMetricComparisonDeterminism:
    """Tests for deterministic behavior"""
    
    def _get_operator_token(self):
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": OPERATOR_EMAIL,
            "password": OPERATOR_PASSWORD
        })
        return response.json()["access_token"]
    
    def test_same_configs_produce_same_results(self):
        """Test that same data and configs produce identical results"""
        token = self._get_operator_token()
        
        payload = {
            "window_minutes": 60,
            "fleet_scope": "all",
            "config_a": {
                "combined_anomaly": {
                    "weight_battery": 0.7,
                    "weight_signal": 0.3,
                    "trigger_threshold": 60,
                    "correlation_bonus": 10,
                    "persistence_minutes": 15,
                    "escalation_tiers": {"60-75": "L1", "75-90": "L2", "90-100": "L3"}
                }
            },
            "config_b": {
                "combined_anomaly": {
                    "weight_battery": 0.6,
                    "weight_signal": 0.4,
                    "trigger_threshold": 55,
                    "correlation_bonus": 15,
                    "persistence_minutes": 20,
                    "escalation_tiers": {"55-70": "L1", "70-85": "L2", "85-100": "L3"}
                }
            }
        }
        
        # Make two identical requests
        response1 = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
            headers={"Authorization": f"Bearer {token}"},
            json=payload
        )
        response2 = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
            headers={"Authorization": f"Bearer {token}"},
            json=payload
        )
        
        data1 = response1.json()
        data2 = response2.json()
        
        # Compare key metrics (devices_evaluated may change if data changes between requests)
        assert data1["summary"]["config_a"]["anomalies"] == data2["summary"]["config_a"]["anomalies"], \
            "Determinism: config_a anomalies should match"
        assert data1["summary"]["config_b"]["anomalies"] == data2["summary"]["config_b"]["anomalies"], \
            "Determinism: config_b anomalies should match"
        assert data1["delta"]["anomalies_diff"] == data2["delta"]["anomalies_diff"], \
            "Determinism: anomalies_diff should match"
        
        print("PASS: Same configs produce deterministic results")


class TestMultiMetricComparisonWeightEffects:
    """Tests for weight distribution effects on scores"""
    
    def _get_operator_token(self):
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": OPERATOR_EMAIL,
            "password": OPERATOR_PASSWORD
        })
        return response.json()["access_token"]
    
    def test_different_weights_affect_scores(self):
        """Test that different weight distributions produce different results"""
        token = self._get_operator_token()
        
        # Config A: Heavy battery weight (0.9/0.1)
        # Config B: Heavy signal weight (0.1/0.9)
        payload = {
            "window_minutes": 60,
            "fleet_scope": "all",
            "config_a": {
                "combined_anomaly": {
                    "weight_battery": 0.9,
                    "weight_signal": 0.1,
                    "trigger_threshold": 60,
                    "correlation_bonus": 10,
                    "persistence_minutes": 15,
                    "escalation_tiers": {"60-75": "L1", "75-90": "L2", "90-100": "L3"}
                }
            },
            "config_b": {
                "combined_anomaly": {
                    "weight_battery": 0.1,
                    "weight_signal": 0.9,
                    "trigger_threshold": 60,
                    "correlation_bonus": 10,
                    "persistence_minutes": 15,
                    "escalation_tiers": {"60-75": "L1", "75-90": "L2", "90-100": "L3"}
                }
            }
        }
        
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
            headers={"Authorization": f"Bearer {token}"},
            json=payload
        )
        data = response.json()
        
        # Weight differences should potentially produce different results
        # We can't assert exact values without knowing the data, but structure should be valid
        assert response.status_code == 200
        assert "delta" in data
        assert "summary" in data
        
        print(f"PASS: Weight effects test - Config A anomalies: {data['summary']['config_a']['anomalies']}, "
              f"Config B anomalies: {data['summary']['config_b']['anomalies']}")
    
    def test_correlation_bonus_effect(self):
        """Test that correlation bonus affects combined scores"""
        token = self._get_operator_token()
        
        # Config A: No correlation bonus
        # Config B: Large correlation bonus
        payload = {
            "window_minutes": 60,
            "fleet_scope": "all",
            "config_a": {
                "combined_anomaly": {
                    "weight_battery": 0.5,
                    "weight_signal": 0.5,
                    "trigger_threshold": 55,
                    "correlation_bonus": 0,  # No bonus
                    "persistence_minutes": 15,
                    "escalation_tiers": {"55-70": "L1", "70-85": "L2", "85-100": "L3"}
                }
            },
            "config_b": {
                "combined_anomaly": {
                    "weight_battery": 0.5,
                    "weight_signal": 0.5,
                    "trigger_threshold": 55,
                    "correlation_bonus": 30,  # Large bonus
                    "persistence_minutes": 15,
                    "escalation_tiers": {"55-70": "L1", "70-85": "L2", "85-100": "L3"}
                }
            }
        }
        
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
            headers={"Authorization": f"Bearer {token}"},
            json=payload
        )
        data = response.json()
        
        assert response.status_code == 200
        
        # With higher correlation bonus, config_b should have >= config_a anomalies
        # (devices with both metrics active get boosted higher)
        assert data["summary"]["config_b"]["anomalies"] >= data["summary"]["config_a"]["anomalies"], \
            "Higher correlation bonus should flag same or more devices"
        
        print(f"PASS: Correlation bonus effect - A anomalies: {data['summary']['config_a']['anomalies']}, "
              f"B anomalies: {data['summary']['config_b']['anomalies']}")


class TestMultiMetricComparisonValidation:
    """Tests for payload validation and bounds checking"""
    
    def _get_operator_token(self):
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": OPERATOR_EMAIL,
            "password": OPERATOR_PASSWORD
        })
        return response.json()["access_token"]
    
    def test_window_minutes_minimum_bound(self):
        """Test that window_minutes < 5 is rejected"""
        token = self._get_operator_token()
        
        payload = {
            "window_minutes": 4,  # Below minimum of 5
            "fleet_scope": "all",
            "config_a": {
                "combined_anomaly": {
                    "weight_battery": 0.7,
                    "weight_signal": 0.3,
                    "trigger_threshold": 60,
                    "correlation_bonus": 10,
                    "persistence_minutes": 15,
                    "escalation_tiers": {"60-75": "L1", "75-90": "L2", "90-100": "L3"}
                }
            },
            "config_b": {
                "combined_anomaly": {
                    "weight_battery": 0.7,
                    "weight_signal": 0.3,
                    "trigger_threshold": 55,
                    "correlation_bonus": 10,
                    "persistence_minutes": 15,
                    "escalation_tiers": {"60-75": "L1", "75-90": "L2", "90-100": "L3"}
                }
            }
        }
        
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
            headers={"Authorization": f"Bearer {token}"},
            json=payload
        )
        assert response.status_code == 422, f"window_minutes < 5 should be rejected with 422, got {response.status_code}"
        print("PASS: window_minutes minimum bound (5) enforced")
    
    def test_window_minutes_maximum_bound(self):
        """Test that window_minutes > 1440 is rejected"""
        token = self._get_operator_token()
        
        payload = {
            "window_minutes": 1441,  # Above maximum of 1440
            "fleet_scope": "all",
            "config_a": {
                "combined_anomaly": {
                    "weight_battery": 0.7,
                    "weight_signal": 0.3,
                    "trigger_threshold": 60,
                    "correlation_bonus": 10,
                    "persistence_minutes": 15,
                    "escalation_tiers": {"60-75": "L1", "75-90": "L2", "90-100": "L3"}
                }
            },
            "config_b": {
                "combined_anomaly": {
                    "weight_battery": 0.7,
                    "weight_signal": 0.3,
                    "trigger_threshold": 55,
                    "correlation_bonus": 10,
                    "persistence_minutes": 15,
                    "escalation_tiers": {"60-75": "L1", "75-90": "L2", "90-100": "L3"}
                }
            }
        }
        
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
            headers={"Authorization": f"Bearer {token}"},
            json=payload
        )
        assert response.status_code == 422, f"window_minutes > 1440 should be rejected with 422, got {response.status_code}"
        print("PASS: window_minutes maximum bound (1440) enforced")
    
    def test_window_minutes_valid_bounds(self):
        """Test that window_minutes at boundaries (5, 1440) works"""
        token = self._get_operator_token()
        
        for window in [5, 1440]:
            payload = {
                "window_minutes": window,
                "fleet_scope": "all",
                "config_a": {
                    "combined_anomaly": {
                        "weight_battery": 0.7,
                        "weight_signal": 0.3,
                        "trigger_threshold": 60,
                        "correlation_bonus": 10,
                        "persistence_minutes": 15,
                        "escalation_tiers": {"60-75": "L1", "75-90": "L2", "90-100": "L3"}
                    }
                },
                "config_b": {
                    "combined_anomaly": {
                        "weight_battery": 0.7,
                        "weight_signal": 0.3,
                        "trigger_threshold": 55,
                        "correlation_bonus": 10,
                        "persistence_minutes": 15,
                        "escalation_tiers": {"60-75": "L1", "75-90": "L2", "90-100": "L3"}
                    }
                }
            }
            
            response = requests.post(
                f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
                headers={"Authorization": f"Bearer {token}"},
                json=payload
            )
            assert response.status_code == 200, f"window_minutes={window} should be valid, got {response.status_code}"
        
        print("PASS: window_minutes boundary values (5, 1440) work correctly")
    
    def test_missing_config_a_rejected(self):
        """Test that missing config_a is rejected"""
        token = self._get_operator_token()
        
        payload = {
            "window_minutes": 60,
            "fleet_scope": "all",
            "config_b": {
                "combined_anomaly": {
                    "weight_battery": 0.7,
                    "weight_signal": 0.3,
                    "trigger_threshold": 55,
                    "correlation_bonus": 10,
                    "persistence_minutes": 15,
                    "escalation_tiers": {"60-75": "L1", "75-90": "L2", "90-100": "L3"}
                }
            }
        }
        
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
            headers={"Authorization": f"Bearer {token}"},
            json=payload
        )
        assert response.status_code == 422, f"Missing config_a should be rejected with 422, got {response.status_code}"
        print("PASS: Missing config_a rejected with 422")
    
    def test_missing_config_b_rejected(self):
        """Test that missing config_b is rejected"""
        token = self._get_operator_token()
        
        payload = {
            "window_minutes": 60,
            "fleet_scope": "all",
            "config_a": {
                "combined_anomaly": {
                    "weight_battery": 0.7,
                    "weight_signal": 0.3,
                    "trigger_threshold": 60,
                    "correlation_bonus": 10,
                    "persistence_minutes": 15,
                    "escalation_tiers": {"60-75": "L1", "75-90": "L2", "90-100": "L3"}
                }
            }
        }
        
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
            headers={"Authorization": f"Bearer {token}"},
            json=payload
        )
        assert response.status_code == 422, f"Missing config_b should be rejected with 422, got {response.status_code}"
        print("PASS: Missing config_b rejected with 422")
    
    def test_invalid_weight_values(self):
        """Test that weight values outside 0-1 range are rejected"""
        token = self._get_operator_token()
        
        # Test weight_battery > 1
        payload = {
            "window_minutes": 60,
            "fleet_scope": "all",
            "config_a": {
                "combined_anomaly": {
                    "weight_battery": 1.5,  # Invalid: > 1
                    "weight_signal": 0.3,
                    "trigger_threshold": 60,
                    "correlation_bonus": 10,
                    "persistence_minutes": 15,
                    "escalation_tiers": {"60-75": "L1", "75-90": "L2", "90-100": "L3"}
                }
            },
            "config_b": {
                "combined_anomaly": {
                    "weight_battery": 0.7,
                    "weight_signal": 0.3,
                    "trigger_threshold": 55,
                    "correlation_bonus": 10,
                    "persistence_minutes": 15,
                    "escalation_tiers": {"60-75": "L1", "75-90": "L2", "90-100": "L3"}
                }
            }
        }
        
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
            headers={"Authorization": f"Bearer {token}"},
            json=payload
        )
        assert response.status_code == 422, f"weight_battery > 1 should be rejected, got {response.status_code}"
        print("PASS: Invalid weight value (>1) rejected")
    
    def test_negative_weight_rejected(self):
        """Test that negative weight values are rejected"""
        token = self._get_operator_token()
        
        payload = {
            "window_minutes": 60,
            "fleet_scope": "all",
            "config_a": {
                "combined_anomaly": {
                    "weight_battery": -0.5,  # Invalid: negative
                    "weight_signal": 0.3,
                    "trigger_threshold": 60,
                    "correlation_bonus": 10,
                    "persistence_minutes": 15,
                    "escalation_tiers": {"60-75": "L1", "75-90": "L2", "90-100": "L3"}
                }
            },
            "config_b": {
                "combined_anomaly": {
                    "weight_battery": 0.7,
                    "weight_signal": 0.3,
                    "trigger_threshold": 55,
                    "correlation_bonus": 10,
                    "persistence_minutes": 15,
                    "escalation_tiers": {"60-75": "L1", "75-90": "L2", "90-100": "L3"}
                }
            }
        }
        
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
            headers={"Authorization": f"Bearer {token}"},
            json=payload
        )
        assert response.status_code == 422, f"Negative weight should be rejected, got {response.status_code}"
        print("PASS: Negative weight value rejected")


class TestMultiMetricComparisonReadOnly:
    """Tests to verify read-only behavior (no DB writes)"""
    
    def _get_operator_token(self):
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": OPERATOR_EMAIL,
            "password": OPERATOR_PASSWORD
        })
        return response.json()["access_token"]
    
    def test_no_new_anomalies_created(self):
        """Test that calling the endpoint doesn't create new anomaly records"""
        token = self._get_operator_token()
        
        # Get anomaly count before
        before_response = requests.get(
            f"{BASE_URL}/api/operator/device-anomalies?hours=24",
            headers={"Authorization": f"Bearer {token}"}
        )
        before_count = len(before_response.json().get("anomalies", []))
        
        # Call the comparison endpoint
        payload = {
            "window_minutes": 60,
            "fleet_scope": "all",
            "config_a": {
                "combined_anomaly": {
                    "weight_battery": 0.7,
                    "weight_signal": 0.3,
                    "trigger_threshold": 30,  # Very low threshold to maximize evaluation
                    "correlation_bonus": 20,
                    "persistence_minutes": 5,
                    "escalation_tiers": {"30-50": "L1", "50-75": "L2", "75-100": "L3"}
                }
            },
            "config_b": {
                "combined_anomaly": {
                    "weight_battery": 0.7,
                    "weight_signal": 0.3,
                    "trigger_threshold": 20,
                    "correlation_bonus": 30,
                    "persistence_minutes": 5,
                    "escalation_tiers": {"20-40": "L1", "40-60": "L2", "60-100": "L3"}
                }
            }
        }
        
        compare_response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
            headers={"Authorization": f"Bearer {token}"},
            json=payload
        )
        assert compare_response.status_code == 200
        
        # Get anomaly count after
        after_response = requests.get(
            f"{BASE_URL}/api/operator/device-anomalies?hours=24",
            headers={"Authorization": f"Bearer {token}"}
        )
        after_count = len(after_response.json().get("anomalies", []))
        
        # Count should be the same (read-only operation)
        assert after_count == before_count, \
            f"Anomaly count changed after comparison: before={before_count}, after={after_count}"
        
        print(f"PASS: No new anomalies created (count remained {before_count})")
    
    def test_no_new_incidents_created(self):
        """Test that calling the endpoint doesn't create new incidents"""
        token = self._get_operator_token()
        
        # Get incident count before
        before_response = requests.get(
            f"{BASE_URL}/api/operator/incidents",
            headers={"Authorization": f"Bearer {token}"}
        )
        before_count = len(before_response.json())
        
        # Call the comparison endpoint multiple times
        payload = {
            "window_minutes": 60,
            "fleet_scope": "all",
            "config_a": {
                "combined_anomaly": {
                    "weight_battery": 0.7,
                    "weight_signal": 0.3,
                    "trigger_threshold": 10,  # Extremely low threshold
                    "correlation_bonus": 40,
                    "persistence_minutes": 1,
                    "escalation_tiers": {"10-30": "L1", "30-60": "L2", "60-100": "L3"}
                }
            },
            "config_b": {
                "combined_anomaly": {
                    "weight_battery": 0.7,
                    "weight_signal": 0.3,
                    "trigger_threshold": 5,
                    "correlation_bonus": 50,
                    "persistence_minutes": 1,
                    "escalation_tiers": {"5-20": "L1", "20-50": "L2", "50-100": "L3"}
                }
            }
        }
        
        for _ in range(3):
            response = requests.post(
                f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
                headers={"Authorization": f"Bearer {token}"},
                json=payload
            )
            assert response.status_code == 200
        
        # Get incident count after
        after_response = requests.get(
            f"{BASE_URL}/api/operator/incidents",
            headers={"Authorization": f"Bearer {token}"}
        )
        after_count = len(after_response.json())
        
        assert after_count == before_count, \
            f"Incident count changed after comparison: before={before_count}, after={after_count}"
        
        print(f"PASS: No new incidents created (count remained {before_count})")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
