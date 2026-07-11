"""
Test Suite for Phase 3: Behavioral Pattern AI Simulation Lab Extension

Tests POST /api/operator/simulate/behavior endpoint:
- BehaviorSimRequest with scenarios array
- BehaviorSimResponse with escalation timeline
- 5 valid scenario types validation
- ramp_minutes <= duration_minutes validation
- Device identifier validation (404 for unknown)
- behavior_anomalies generation with is_simulated=true
- Timeline steps with behavior_score ramping (sigmoid)
- Combined risk score calculation
- Simulation history retrieval
"""

import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

VALID_SCENARIO_TYPES = [
    "prolonged_inactivity",
    "movement_drop", 
    "routine_disruption",
    "location_wandering",
    "route_deviation",
]


@pytest.fixture(scope="module")
def auth_token():
    """Get operator authentication token"""
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": "operator@nischint.com", "password": "operator123"}
    )
    assert response.status_code == 200, f"Login failed: {response.text}"
    return response.json()["access_token"]


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Auth headers for operator requests"""
    return {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json"
    }


class TestBehaviorSimulationValidation:
    """Validation tests for POST /api/operator/simulate/behavior"""

    def test_requires_authentication(self):
        """Test endpoint returns 401 without auth"""
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/behavior",
            json={
                "scenarios": [{"scenario_type": "prolonged_inactivity", "device_identifier": "DEV-001"}]
            }
        )
        assert response.status_code == 401, f"Expected 401 without auth, got {response.status_code}"
        print("PASS: Endpoint requires authentication")

    def test_invalid_scenario_type_rejected(self, auth_headers):
        """Test that invalid scenario_type returns 422"""
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/behavior",
            headers=auth_headers,
            json={
                "scenarios": [{
                    "scenario_type": "invalid_type",
                    "device_identifier": "DEV-001",
                    "duration_minutes": 60,
                    "intensity": 0.7,
                    "ramp_minutes": 15
                }]
            }
        )
        assert response.status_code == 422, f"Expected 422 for invalid scenario type, got {response.status_code}"
        data = response.json()
        assert "detail" in data
        print(f"PASS: Invalid scenario_type rejected with: {data['detail']}")

    def test_ramp_minutes_exceeds_duration_rejected(self, auth_headers):
        """Test that ramp_minutes > duration_minutes returns 422"""
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/behavior",
            headers=auth_headers,
            json={
                "scenarios": [{
                    "scenario_type": "prolonged_inactivity",
                    "device_identifier": "DEV-001",
                    "duration_minutes": 30,  # short duration
                    "intensity": 0.7,
                    "ramp_minutes": 60  # ramp exceeds duration
                }]
            }
        )
        assert response.status_code == 422, f"Expected 422 for ramp > duration, got {response.status_code}"
        data = response.json()
        assert "ramp_minutes" in str(data).lower() or "duration_minutes" in str(data).lower()
        print(f"PASS: ramp_minutes > duration_minutes rejected: {data['detail']}")

    def test_unknown_device_returns_404(self, auth_headers):
        """Test that unknown device_identifier returns 404"""
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/behavior",
            headers=auth_headers,
            json={
                "scenarios": [{
                    "scenario_type": "prolonged_inactivity",
                    "device_identifier": "UNKNOWN-DEVICE-XYZ",
                    "duration_minutes": 60,
                    "intensity": 0.7,
                    "ramp_minutes": 15
                }]
            }
        )
        assert response.status_code == 404, f"Expected 404 for unknown device, got {response.status_code}"
        data = response.json()
        assert "not found" in data.get("detail", "").lower()
        print(f"PASS: Unknown device returns 404: {data['detail']}")

    def test_empty_scenarios_rejected(self, auth_headers):
        """Test that empty scenarios array is rejected"""
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/behavior",
            headers=auth_headers,
            json={"scenarios": []}
        )
        assert response.status_code == 422, f"Expected 422 for empty scenarios, got {response.status_code}"
        print("PASS: Empty scenarios array rejected")


class TestBehaviorSimulationSuccess:
    """Success path tests for behavior simulation"""

    def test_single_scenario_success(self, auth_headers):
        """Test successful single scenario simulation"""
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/behavior",
            headers=auth_headers,
            json={
                "scenarios": [{
                    "scenario_type": "prolonged_inactivity",
                    "device_identifier": "DEV-001",
                    "duration_minutes": 60,
                    "intensity": 0.8,
                    "ramp_minutes": 20
                }],
                "trigger_escalation": True,
                "step_interval_minutes": 10
            }
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Verify response structure
        assert "simulation_run_id" in data
        assert data["simulation_run_id"].startswith("behavior-")
        assert "total_scenarios" in data
        assert data["total_scenarios"] == 1
        assert "total_behavior_anomalies" in data
        assert "total_escalations" in data
        assert "scenario_results" in data
        assert data.get("is_simulated") == True
        
        print(f"PASS: Single scenario simulation successful, run_id={data['simulation_run_id']}")
        print(f"  - anomalies={data['total_behavior_anomalies']}, escalations={data['total_escalations']}")
        
        return data

    def test_response_contains_scenario_result_fields(self, auth_headers):
        """Test scenario_results contains required fields"""
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/behavior",
            headers=auth_headers,
            json={
                "scenarios": [{
                    "scenario_type": "movement_drop",
                    "device_identifier": "DEV-001",
                    "duration_minutes": 30,
                    "intensity": 0.7,
                    "ramp_minutes": 10
                }],
                "trigger_escalation": True,
                "step_interval_minutes": 5
            }
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        # Check scenario_results structure
        assert len(data["scenario_results"]) == 1
        sr = data["scenario_results"][0]
        
        required_fields = [
            "device_identifier", "scenario_type", "scenario_description",
            "duration_minutes", "intensity", "behavior_anomalies_created",
            "timeline", "peak_behavior_score", "peak_combined_score",
            "final_escalation_tier", "time_to_first_escalation_minutes"
        ]
        for field in required_fields:
            assert field in sr, f"Missing field: {field}"
        
        assert sr["device_identifier"] == "DEV-001"
        assert sr["scenario_type"] == "movement_drop"
        assert sr["duration_minutes"] == 30
        assert sr["intensity"] == 0.7
        assert sr["behavior_anomalies_created"] > 0
        
        print("PASS: scenario_results contains all required fields")
        print(f"  - peak_behavior_score={sr['peak_behavior_score']}")
        print(f"  - peak_combined_score={sr['peak_combined_score']}")
        print(f"  - final_tier={sr['final_escalation_tier']}")

    def test_timeline_steps_structure(self, auth_headers):
        """Test timeline steps have correct structure and ramping behavior"""
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/behavior",
            headers=auth_headers,
            json={
                "scenarios": [{
                    "scenario_type": "routine_disruption",
                    "device_identifier": "DEV-001",
                    "duration_minutes": 40,
                    "intensity": 0.6,
                    "ramp_minutes": 20
                }],
                "trigger_escalation": True,
                "step_interval_minutes": 5
            }
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        timeline = data["scenario_results"][0]["timeline"]
        assert len(timeline) > 0, "Timeline should not be empty"
        
        # Check timeline step structure
        step = timeline[0]
        required_step_fields = [
            "minute", "behavior_score", "anomaly_type",
            "combined_risk_score", "escalation_tier", "escalation_reason"
        ]
        for field in required_step_fields:
            assert field in step, f"Missing timeline field: {field}"
        
        # Verify behavior score ramping (should start low and increase)
        first_score = timeline[0]["behavior_score"]
        last_score = timeline[-1]["behavior_score"]
        
        assert first_score < last_score, f"Behavior score should ramp up: first={first_score}, last={last_score}"
        assert first_score <= 0.2, "First score should be near baseline (~0.15)"
        assert last_score >= 0.5, f"Last score should approach intensity: {last_score}"
        
        print("PASS: Timeline steps have correct structure")
        print(f"  - {len(timeline)} steps from minute {timeline[0]['minute']} to {timeline[-1]['minute']}")
        print(f"  - Behavior score ramps from {first_score:.3f} to {last_score:.3f}")


class TestAllScenarioTypes:
    """Test all 5 scenario types work correctly"""

    @pytest.mark.parametrize("scenario_type", VALID_SCENARIO_TYPES)
    def test_scenario_type_accepted(self, auth_headers, scenario_type):
        """Test each valid scenario type is accepted and returns results"""
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/behavior",
            headers=auth_headers,
            json={
                "scenarios": [{
                    "scenario_type": scenario_type,
                    "device_identifier": "DEV-001",
                    "duration_minutes": 30,
                    "intensity": 0.7,
                    "ramp_minutes": 10
                }],
                "trigger_escalation": True,
                "step_interval_minutes": 10
            }
        )
        assert response.status_code == 200, f"Scenario type '{scenario_type}' failed: {response.text}"
        data = response.json()
        
        assert data["total_scenarios"] == 1
        assert data["scenario_results"][0]["scenario_type"] == scenario_type
        assert data["scenario_results"][0]["scenario_description"] != ""
        
        print(f"PASS: Scenario type '{scenario_type}' accepted")
        print(f"  - description: {data['scenario_results'][0]['scenario_description'][:50]}...")


class TestMultipleScenarios:
    """Test running multiple scenarios simultaneously"""

    def test_multiple_scenarios_same_device(self, auth_headers):
        """Test multiple scenarios on same device"""
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/behavior",
            headers=auth_headers,
            json={
                "scenarios": [
                    {"scenario_type": "prolonged_inactivity", "device_identifier": "DEV-001", "duration_minutes": 30, "intensity": 0.8, "ramp_minutes": 10},
                    {"scenario_type": "movement_drop", "device_identifier": "DEV-001", "duration_minutes": 30, "intensity": 0.6, "ramp_minutes": 15}
                ],
                "trigger_escalation": True,
                "step_interval_minutes": 10
            }
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        assert data["total_scenarios"] == 2
        assert len(data["scenario_results"]) == 2
        
        # Both results should have DEV-001
        devices = [sr["device_identifier"] for sr in data["scenario_results"]]
        assert devices == ["DEV-001", "DEV-001"]
        
        # Check anomalies created is sum of both scenarios
        total_anom = sum(sr["behavior_anomalies_created"] for sr in data["scenario_results"])
        assert total_anom == data["total_behavior_anomalies"]
        
        print(f"PASS: Multiple scenarios on same device: {data['total_scenarios']} scenarios")
        print(f"  - Total anomalies: {data['total_behavior_anomalies']}")


class TestCombinedRiskScoreCalculation:
    """Test combined risk score calculation in timeline"""

    def test_combined_score_calculation(self, auth_headers):
        """Test that combined_risk_score is calculated correctly"""
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/behavior",
            headers=auth_headers,
            json={
                "scenarios": [{
                    "scenario_type": "location_wandering",
                    "device_identifier": "DEV-001",
                    "duration_minutes": 60,
                    "intensity": 0.8,
                    "ramp_minutes": 20
                }],
                "trigger_escalation": True,
                "step_interval_minutes": 5
            }
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        timeline = data["scenario_results"][0]["timeline"]
        
        # Check combined scores are calculated
        combined_scores = [t["combined_risk_score"] for t in timeline if t["combined_risk_score"] is not None]
        assert len(combined_scores) > 0, "Should have combined risk scores"
        
        # Combined score should be within 0-100 range
        for score in combined_scores:
            assert 0 <= score <= 100, f"Combined score out of range: {score}"
        
        # With weight_behavior=0.2, a behavior at 0.8 intensity gives ~16 points
        # Unless battery/signal anomalies exist, total should be low
        print("PASS: Combined risk scores calculated correctly")
        print(f"  - Combined scores: min={min(combined_scores):.1f}, max={max(combined_scores):.1f}")


class TestSimulationHistoryPersistence:
    """Test simulation runs are saved to history"""

    def test_behavior_sim_saved_to_history(self, auth_headers):
        """Test that behavior simulation is saved in simulation_runs with run_type='behavior'"""
        # Run a simulation
        sim_response = requests.post(
            f"{BASE_URL}/api/operator/simulate/behavior",
            headers=auth_headers,
            json={
                "scenarios": [{
                    "scenario_type": "route_deviation",
                    "device_identifier": "DEV-001",
                    "duration_minutes": 30,
                    "intensity": 0.65,
                    "ramp_minutes": 10
                }],
                "trigger_escalation": True,
                "step_interval_minutes": 10
            }
        )
        assert sim_response.status_code == 200, f"Simulation failed: {sim_response.text}"
        run_id = sim_response.json()["simulation_run_id"]
        
        # Check history contains this run
        time.sleep(0.5)  # Allow DB commit
        hist_response = requests.get(
            f"{BASE_URL}/api/operator/simulations?run_type=behavior&limit=10",
            headers=auth_headers
        )
        assert hist_response.status_code == 200, f"History fetch failed: {hist_response.text}"
        history = hist_response.json()
        
        assert "items" in history
        run_ids = [item["simulation_run_id"] for item in history["items"]]
        assert run_id in run_ids, f"Run {run_id} not found in history"
        
        # Verify run_type is 'behavior'
        run_item = next(item for item in history["items"] if item["simulation_run_id"] == run_id)
        assert run_item["run_type"] == "behavior"
        
        print(f"PASS: Behavior simulation saved to history with run_type='behavior'")
        print(f"  - run_id: {run_id}")

    def test_get_simulation_detail(self, auth_headers):
        """Test retrieving detailed simulation results by run_id"""
        # Create a simulation first
        sim_response = requests.post(
            f"{BASE_URL}/api/operator/simulate/behavior",
            headers=auth_headers,
            json={
                "scenarios": [{
                    "scenario_type": "prolonged_inactivity",
                    "device_identifier": "DEV-001",
                    "duration_minutes": 20,
                    "intensity": 0.7,
                    "ramp_minutes": 5
                }],
                "trigger_escalation": True,
                "step_interval_minutes": 5
            }
        )
        assert sim_response.status_code == 200
        run_id = sim_response.json()["simulation_run_id"]
        
        # Fetch detail
        detail_response = requests.get(
            f"{BASE_URL}/api/operator/simulations/{run_id}",
            headers=auth_headers
        )
        assert detail_response.status_code == 200, f"Detail fetch failed: {detail_response.text}"
        detail = detail_response.json()
        
        assert detail["simulation_run_id"] == run_id
        assert detail["run_type"] == "behavior"
        assert "config_json" in detail
        assert "summary_json" in detail
        assert detail["config_json"]["scenarios"][0]["scenario_type"] == "prolonged_inactivity"
        
        print("PASS: Simulation detail retrieval works")
        print(f"  - run_type: {detail['run_type']}")
        print(f"  - anomalies_triggered: {detail['anomalies_triggered']}")


class TestNoEscalationMode:
    """Test running without escalation evaluation"""

    def test_no_escalation_mode(self, auth_headers):
        """Test with trigger_escalation=False"""
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/behavior",
            headers=auth_headers,
            json={
                "scenarios": [{
                    "scenario_type": "prolonged_inactivity",
                    "device_identifier": "DEV-001",
                    "duration_minutes": 30,
                    "intensity": 0.9,
                    "ramp_minutes": 10
                }],
                "trigger_escalation": False,
                "step_interval_minutes": 10
            }
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        sr = data["scenario_results"][0]
        timeline = sr["timeline"]
        
        # With trigger_escalation=False, combined scores should be None
        for step in timeline:
            assert step["combined_risk_score"] is None or step["combined_risk_score"] == 0
            assert step["escalation_tier"] is None
        
        assert sr["final_escalation_tier"] is None
        assert data["total_escalations"] == 0
        
        print("PASS: No escalation mode works - combined scores not evaluated")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
