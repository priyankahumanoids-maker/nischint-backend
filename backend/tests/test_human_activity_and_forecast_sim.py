# Human Activity Risk AI + Forecast Simulation Engine Tests
# Tests for:
# 1. GET /api/operator/human-activity-risk/assess - Point activity risk assessment
# 2. GET /api/operator/human-activity-risk/fleet - Fleet device activity risk
# 3. GET /api/operator/human-activity-risk/hotspots - Zone activity hotspots
# 4. GET /api/operator/simulate/forecast-scenarios - Available scenarios
# 5. POST /api/operator/simulate/forecast-scenario - Run what-if scenarios

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestAuthentication:
    """Verify endpoints require operator role"""
    
    def test_activity_assess_requires_auth(self):
        """Activity assess endpoint should require authentication"""
        response = requests.get(f"{BASE_URL}/api/operator/human-activity-risk/assess?lat=12.971&lng=77.594")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: Activity assess requires auth")
    
    def test_fleet_activity_requires_auth(self):
        """Fleet activity endpoint should require authentication"""
        response = requests.get(f"{BASE_URL}/api/operator/human-activity-risk/fleet")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: Fleet activity requires auth")
    
    def test_hotspots_activity_requires_auth(self):
        """Activity hotspots endpoint should require authentication"""
        response = requests.get(f"{BASE_URL}/api/operator/human-activity-risk/hotspots")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: Activity hotspots requires auth")
    
    def test_forecast_scenarios_requires_auth(self):
        """Forecast scenarios list should require authentication"""
        response = requests.get(f"{BASE_URL}/api/operator/simulate/forecast-scenarios")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: Forecast scenarios requires auth")
    
    def test_run_forecast_scenario_requires_auth(self):
        """Run forecast scenario should require authentication"""
        response = requests.post(f"{BASE_URL}/api/operator/simulate/forecast-scenario", json={})
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: Run forecast scenario requires auth")


@pytest.fixture(scope="module")
def operator_token():
    """Get operator JWT token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "operator@nischint.com",
        "password": "operator123"
    })
    if response.status_code != 200:
        pytest.skip("Operator login failed - skipping authenticated tests")
    return response.json().get("access_token")


@pytest.fixture
def auth_headers(operator_token):
    """Auth headers with operator token"""
    return {"Authorization": f"Bearer {operator_token}"}


class TestHumanActivityRiskAssess:
    """Tests for GET /api/operator/human-activity-risk/assess"""
    
    def test_assess_returns_200(self, auth_headers):
        """Assess endpoint returns 200 with valid lat/lng"""
        response = requests.get(
            f"{BASE_URL}/api/operator/human-activity-risk/assess?lat=12.971&lng=77.594",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: Activity assess returns 200")
    
    def test_assess_response_structure(self, auth_headers):
        """Verify response has all required fields"""
        response = requests.get(
            f"{BASE_URL}/api/operator/human-activity-risk/assess?lat=12.971&lng=77.594",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        # Required top-level fields
        required_fields = ["lat", "lng", "risk_score", "risk_level", "factors", "signals", "incident_counts", "assessed_at"]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"
        
        print(f"PASS: Response has all required fields: {list(data.keys())}")
    
    def test_assess_risk_score_valid(self, auth_headers):
        """Risk score should be 0-10"""
        response = requests.get(
            f"{BASE_URL}/api/operator/human-activity-risk/assess?lat=12.971&lng=77.594",
            headers=auth_headers
        )
        data = response.json()
        assert 0 <= data["risk_score"] <= 10, f"Risk score out of range: {data['risk_score']}"
        print(f"PASS: Risk score {data['risk_score']} is valid (0-10)")
    
    def test_assess_risk_level_valid(self, auth_headers):
        """Risk level should be one of: critical, high, medium, low"""
        response = requests.get(
            f"{BASE_URL}/api/operator/human-activity-risk/assess?lat=12.971&lng=77.594",
            headers=auth_headers
        )
        data = response.json()
        valid_levels = ["critical", "high", "medium", "low"]
        assert data["risk_level"] in valid_levels, f"Invalid risk_level: {data['risk_level']}"
        print(f"PASS: Risk level '{data['risk_level']}' is valid")
    
    def test_assess_signals_structure(self, auth_headers):
        """Verify signals object structure"""
        response = requests.get(
            f"{BASE_URL}/api/operator/human-activity-risk/assess?lat=12.971&lng=77.594",
            headers=auth_headers
        )
        data = response.json()
        signals = data["signals"]
        
        required_signals = ["crowd_density", "temporal_spike", "hazard_zone", "emergency_cluster", "traffic_corridor", "acceleration", "hour_activity_level"]
        for sig in required_signals:
            assert sig in signals, f"Missing signal: {sig}"
        
        print(f"PASS: Signals structure valid: {list(signals.keys())}")
    
    def test_assess_incident_counts(self, auth_headers):
        """Verify incident_counts structure"""
        response = requests.get(
            f"{BASE_URL}/api/operator/human-activity-risk/assess?lat=12.971&lng=77.594",
            headers=auth_headers
        )
        data = response.json()
        counts = data["incident_counts"]
        
        assert "within_500m" in counts, "Missing within_500m count"
        assert "within_1km" in counts, "Missing within_1km count"
        assert isinstance(counts["within_500m"], int), "within_500m should be int"
        assert isinstance(counts["within_1km"], int), "within_1km should be int"
        
        print(f"PASS: Incident counts - 500m: {counts['within_500m']}, 1km: {counts['within_1km']}")


class TestHumanActivityFleet:
    """Tests for GET /api/operator/human-activity-risk/fleet"""
    
    def test_fleet_returns_200(self, auth_headers):
        """Fleet endpoint returns 200"""
        response = requests.get(
            f"{BASE_URL}/api/operator/human-activity-risk/fleet",
            headers=auth_headers,
            timeout=30  # Fleet can take ~5 seconds per agent note
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: Fleet activity returns 200")
    
    def test_fleet_response_structure(self, auth_headers):
        """Verify fleet response structure"""
        response = requests.get(
            f"{BASE_URL}/api/operator/human-activity-risk/fleet",
            headers=auth_headers,
            timeout=30
        )
        data = response.json()
        
        required_fields = ["total_devices", "high_risk_count", "assessments", "assessed_at"]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"
        
        print(f"PASS: Fleet response - {data['total_devices']} devices, {data['high_risk_count']} high risk")
    
    def test_fleet_assessments_structure(self, auth_headers):
        """Verify each device assessment structure"""
        response = requests.get(
            f"{BASE_URL}/api/operator/human-activity-risk/fleet",
            headers=auth_headers,
            timeout=30
        )
        data = response.json()
        
        if len(data["assessments"]) > 0:
            assessment = data["assessments"][0]
            required = ["device_id", "device_name", "senior_name", "risk_score", "risk_level", "factors", "signals"]
            for field in required:
                assert field in assessment, f"Missing assessment field: {field}"
            print(f"PASS: Device assessment structure valid for {assessment['device_name']}")
        else:
            print("SKIP: No devices to assess")


class TestHumanActivityHotspots:
    """Tests for GET /api/operator/human-activity-risk/hotspots"""
    
    def test_hotspots_returns_200(self, auth_headers):
        """Hotspots endpoint returns 200"""
        response = requests.get(
            f"{BASE_URL}/api/operator/human-activity-risk/hotspots",
            headers=auth_headers,
            timeout=60  # Can take ~10 seconds per agent note
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: Activity hotspots returns 200")
    
    def test_hotspots_response_structure(self, auth_headers):
        """Verify hotspots response structure"""
        response = requests.get(
            f"{BASE_URL}/api/operator/human-activity-risk/hotspots",
            headers=auth_headers,
            timeout=60
        )
        data = response.json()
        
        required_fields = ["total_zones", "high_activity_count", "crowd_zones_count", "hazard_zones_count", "hotspots", "analyzed_at"]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"
        
        print(f"PASS: Hotspots - {data['total_zones']} zones, {data['high_activity_count']} high activity, {data['crowd_zones_count']} crowd zones, {data['hazard_zones_count']} hazard zones")
    
    def test_hotspots_zone_structure(self, auth_headers):
        """Verify individual hotspot zone structure"""
        response = requests.get(
            f"{BASE_URL}/api/operator/human-activity-risk/hotspots",
            headers=auth_headers,
            timeout=60
        )
        data = response.json()
        
        if len(data["hotspots"]) > 0:
            zone = data["hotspots"][0]
            required = ["zone_id", "zone_name", "zone_risk_score", "activity_risk_score", "activity_risk_level", 
                       "activity_factors", "activity_signals", "incident_counts", "lat", "lng", "combined_risk"]
            for field in required:
                assert field in zone, f"Missing zone field: {field}"
            print(f"PASS: Zone structure valid - {zone['zone_name']}, combined_risk: {zone['combined_risk']}")
        else:
            print("SKIP: No zones to assess")


class TestForecastScenarios:
    """Tests for GET /api/operator/simulate/forecast-scenarios"""
    
    def test_scenarios_returns_200(self, auth_headers):
        """Scenarios endpoint returns 200"""
        response = requests.get(
            f"{BASE_URL}/api/operator/simulate/forecast-scenarios",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: Forecast scenarios returns 200")
    
    def test_scenarios_has_four_types(self, auth_headers):
        """Should return 4 scenario types"""
        response = requests.get(
            f"{BASE_URL}/api/operator/simulate/forecast-scenarios",
            headers=auth_headers
        )
        data = response.json()
        
        assert "scenarios" in data, "Missing scenarios field"
        scenarios = data["scenarios"]
        
        expected_types = ["incident_surge", "patrol_deployment", "new_hazard", "time_shift"]
        for stype in expected_types:
            assert stype in scenarios, f"Missing scenario type: {stype}"
        
        print(f"PASS: All 4 scenario types present: {list(scenarios.keys())}")
    
    def test_scenario_structure(self, auth_headers):
        """Verify each scenario has label, description, params"""
        response = requests.get(
            f"{BASE_URL}/api/operator/simulate/forecast-scenarios",
            headers=auth_headers
        )
        data = response.json()
        scenarios = data["scenarios"]
        
        for stype, sdata in scenarios.items():
            assert "label" in sdata, f"{stype} missing label"
            assert "description" in sdata, f"{stype} missing description"
            assert "params" in sdata, f"{stype} missing params"
            print(f"  {stype}: {sdata['label']} - params: {sdata['params']}")
        
        print("PASS: All scenario structures valid")


class TestRunForecastScenario:
    """Tests for POST /api/operator/simulate/forecast-scenario"""
    
    def test_patrol_deployment_scenario(self, auth_headers):
        """Run patrol_deployment scenario"""
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/forecast-scenario",
            headers=auth_headers,
            json={
                "type": "patrol_deployment",
                "params": {"reduction_pct": 50}
            },
            timeout=30  # Can take ~7 seconds
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Verify response structure
        assert "scenario_name" in data, "Missing scenario_name"
        assert "scenario_type" in data, "Missing scenario_type"
        assert data["scenario_type"] == "patrol_deployment"
        assert "total_zones" in data, "Missing total_zones"
        assert "summary" in data, "Missing summary"
        assert "comparisons" in data, "Missing comparisons"
        
        summary = data["summary"]
        assert "zones_worsened" in summary, "Missing zones_worsened"
        assert "zones_improved" in summary, "Missing zones_improved"
        assert "resolved_p1_zones" in summary, "Missing resolved_p1_zones"
        
        print(f"PASS: patrol_deployment - improved: {summary['zones_improved']}, worsened: {summary['zones_worsened']}, resolved P1: {summary['resolved_p1_zones']}")
    
    def test_incident_surge_scenario(self, auth_headers):
        """Run incident_surge scenario"""
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/forecast-scenario",
            headers=auth_headers,
            json={
                "type": "incident_surge",
                "params": {"multiplier": 3}
            },
            timeout=30
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert data["scenario_type"] == "incident_surge"
        assert "scenario_details" in data
        assert data["scenario_details"]["multiplier"] == 3
        
        summary = data["summary"]
        print(f"PASS: incident_surge - worsened: {summary['zones_worsened']}, new P1: {summary['new_p1_zones']}")
    
    def test_new_hazard_scenario(self, auth_headers):
        """Run new_hazard scenario"""
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/forecast-scenario",
            headers=auth_headers,
            json={
                "type": "new_hazard",
                "params": {
                    "lat": 12.97,
                    "lng": 77.59,
                    "severity": "critical",
                    "incident_rate": 10
                }
            },
            timeout=30
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert data["scenario_type"] == "new_hazard"
        assert "scenario_details" in data
        details = data["scenario_details"]
        assert details["lat"] == 12.97
        assert details["lng"] == 77.59
        assert details["severity"] == "critical"
        assert details["injected_incidents"] == 10
        
        print(f"PASS: new_hazard - injected {details['injected_incidents']} incidents at ({details['lat']}, {details['lng']})")
    
    def test_time_shift_scenario(self, auth_headers):
        """Run time_shift scenario"""
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/forecast-scenario",
            headers=auth_headers,
            json={
                "type": "time_shift",
                "params": {"target_hour": 2}  # Night time
            },
            timeout=30
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert data["scenario_type"] == "time_shift"
        assert data["scenario_details"]["target_hour"] == 2
        
        print(f"PASS: time_shift to hour {data['scenario_details']['target_hour']}")
    
    def test_comparison_structure(self, auth_headers):
        """Verify comparison objects in scenario result"""
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/forecast-scenario",
            headers=auth_headers,
            json={
                "type": "patrol_deployment",
                "params": {"reduction_pct": 40}
            },
            timeout=30
        )
        data = response.json()
        
        if len(data["comparisons"]) > 0:
            comp = data["comparisons"][0]
            required = ["zone_id", "zone_name", "risk_score", "affected", "baseline", "scenario", 
                       "delta_24h", "delta_48h", "delta_72h", "category_changed", "priority_changed"]
            for field in required:
                assert field in comp, f"Missing comparison field: {field}"
            
            # Verify baseline/scenario structure
            for key in ["baseline", "scenario"]:
                obj = comp[key]
                assert "predicted_24h" in obj
                assert "predicted_48h" in obj
                assert "predicted_72h" in obj
                assert "forecast_category" in obj
                assert "forecast_priority" in obj
            
            print(f"PASS: Comparison structure valid - zone: {comp['zone_name']}, delta_48h: {comp['delta_48h']}")
        else:
            print("SKIP: No comparisons returned")
    
    def test_invalid_scenario_type(self, auth_headers):
        """Invalid scenario type should return error"""
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/forecast-scenario",
            headers=auth_headers,
            json={
                "type": "invalid_type",
                "params": {}
            },
            timeout=30
        )
        # Should still return 200 but with error in response
        if response.status_code == 200:
            data = response.json()
            assert "error" in data, "Expected error for invalid scenario type"
            print(f"PASS: Invalid scenario returns error: {data['error']}")
        else:
            # Some implementations return 422/400
            assert response.status_code in [400, 422], f"Unexpected status: {response.status_code}"
            print("PASS: Invalid scenario returns 4xx error")


class TestRegressionExistingEndpoints:
    """Verify existing risk-learning endpoints still work"""
    
    def test_stats_endpoint(self, auth_headers):
        """GET /api/operator/risk-learning/stats"""
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/stats",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert "learned_zones" in data or "total_zones" in data
        print("PASS: risk-learning/stats still works")
    
    def test_hotspots_endpoint(self, auth_headers):
        """GET /api/operator/risk-learning/hotspots"""
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/hotspots",
            headers=auth_headers,
            timeout=30
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("PASS: risk-learning/hotspots still works")
    
    def test_recalculate_endpoint(self, auth_headers):
        """POST /api/operator/risk-learning/recalculate"""
        response = requests.post(
            f"{BASE_URL}/api/operator/risk-learning/recalculate",
            headers=auth_headers,
            timeout=60
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("PASS: risk-learning/recalculate still works")
    
    def test_trends_endpoint(self, auth_headers):
        """GET /api/operator/risk-learning/trends"""
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/trends",
            headers=auth_headers,
            timeout=60
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("PASS: risk-learning/trends still works")
    
    def test_forecast_endpoint(self, auth_headers):
        """GET /api/operator/risk-learning/forecast"""
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/forecast",
            headers=auth_headers,
            timeout=60
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("PASS: risk-learning/forecast still works")
    
    def test_forecast_stats_endpoint(self, auth_headers):
        """GET /api/operator/risk-learning/forecast-stats"""
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/forecast-stats",
            headers=auth_headers,
            timeout=30
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("PASS: risk-learning/forecast-stats still works")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
