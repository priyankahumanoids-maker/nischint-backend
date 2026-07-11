# Test Command Center Split Endpoints - Performance Optimization
# Tests for the 4 parallel endpoints: fleet, risk, incidents, environment
# Previously monolithic endpoint (~20s) now split for parallel loading (~8s)

import os
import pytest
import requests
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestCommandCenterSplitEndpoints:
    """Test the 4 split Command Center endpoints for parallel loading."""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get operator authentication token."""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "operator@nischint.com",
            "password": "operator123"
        })
        assert response.status_code == 200, f"Login failed: {response.text}"
        return response.json().get("access_token")
    
    @pytest.fixture(scope="class")
    def auth_headers(self, auth_token):
        """Auth headers for operator requests."""
        return {"Authorization": f"Bearer {auth_token}"}
    
    # ── Auth tests ──
    
    def test_fleet_endpoint_requires_auth(self):
        """Fleet endpoint should return 401 without auth."""
        response = requests.get(f"{BASE_URL}/api/operator/command-center/fleet")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: /fleet returns 401 without auth")
    
    def test_risk_endpoint_requires_auth(self):
        """Risk endpoint should return 401 without auth."""
        response = requests.get(f"{BASE_URL}/api/operator/command-center/risk")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: /risk returns 401 without auth")
    
    def test_incidents_endpoint_requires_auth(self):
        """Incidents endpoint should return 401 without auth."""
        response = requests.get(f"{BASE_URL}/api/operator/command-center/incidents")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: /incidents returns 401 without auth")
    
    def test_environment_endpoint_requires_auth(self):
        """Environment endpoint should return 401 without auth."""
        response = requests.get(f"{BASE_URL}/api/operator/command-center/environment")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: /environment returns 401 without auth")
    
    # ── Fleet endpoint tests ──
    
    def test_fleet_endpoint_returns_fleet_safety(self, auth_headers):
        """Fleet endpoint should return fleet_safety object."""
        response = requests.get(
            f"{BASE_URL}/api/operator/command-center/fleet",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Fleet endpoint failed: {response.text}"
        data = response.json()
        
        # Verify fleet_safety structure
        assert "fleet_safety" in data, "Missing fleet_safety in response"
        fs = data["fleet_safety"]
        
        assert "fleet_score" in fs, "Missing fleet_score"
        assert isinstance(fs["fleet_score"], (int, float)), "fleet_score should be numeric"
        assert 0 <= fs["fleet_score"] <= 100, f"fleet_score out of range: {fs['fleet_score']}"
        
        assert "fleet_status" in fs, "Missing fleet_status"
        assert fs["fleet_status"] in ["EXCELLENT", "STABLE", "MONITOR", "ATTENTION", "CRITICAL"]
        
        assert "device_count" in fs, "Missing device_count"
        assert isinstance(fs["device_count"], int), "device_count should be int"
        
        assert "status_breakdown" in fs, "Missing status_breakdown"
        breakdown = fs["status_breakdown"]
        for key in ["excellent", "stable", "monitor", "attention", "critical"]:
            assert key in breakdown, f"Missing {key} in status_breakdown"
        
        assert "devices" in fs, "Missing devices array"
        assert isinstance(fs["devices"], list), "devices should be list"
        
        if fs["devices"]:
            device = fs["devices"][0]
            assert "device_id" in device, "Device missing device_id"
            assert "device_identifier" in device, "Device missing device_identifier"
            assert "safety_score" in device, "Device missing safety_score"
            assert "status" in device, "Device missing status"
        
        print(f"PASS: Fleet endpoint returns fleet_safety (score={fs['fleet_score']}, devices={fs['device_count']})")
    
    def test_fleet_endpoint_returns_evolution_shifts(self, auth_headers):
        """Fleet endpoint should return evolution_shifts array."""
        response = requests.get(
            f"{BASE_URL}/api/operator/command-center/fleet",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "evolution_shifts" in data, "Missing evolution_shifts in response"
        assert isinstance(data["evolution_shifts"], list), "evolution_shifts should be list"
        
        if data["evolution_shifts"]:
            shift = data["evolution_shifts"][0]
            required_fields = ["device_id", "device_identifier", "metric", "label", 
                            "change_percent", "from_value", "to_value", "weeks_span", "severity"]
            for field in required_fields:
                assert field in shift, f"Shift missing {field}"
        
        print(f"PASS: Fleet endpoint returns evolution_shifts (count={len(data['evolution_shifts'])})")
    
    def test_fleet_endpoint_performance(self, auth_headers):
        """Fleet endpoint should respond in <10s (was 19s before optimization)."""
        start = time.time()
        response = requests.get(
            f"{BASE_URL}/api/operator/command-center/fleet",
            headers=auth_headers,
            timeout=15
        )
        elapsed = time.time() - start
        
        assert response.status_code == 200, f"Fleet endpoint failed: {response.text}"
        assert elapsed < 10, f"Fleet endpoint too slow: {elapsed:.2f}s (should be <10s)"
        print(f"PASS: Fleet endpoint responded in {elapsed:.2f}s (target <10s)")
    
    # ── Risk endpoint tests ──
    
    def test_risk_endpoint_returns_predictive_alerts(self, auth_headers):
        """Risk endpoint should return predictive_alerts array."""
        response = requests.get(
            f"{BASE_URL}/api/operator/command-center/risk",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Risk endpoint failed: {response.text}"
        data = response.json()
        
        assert "predictive_alerts" in data, "Missing predictive_alerts"
        assert isinstance(data["predictive_alerts"], list), "predictive_alerts should be list"
        
        if data["predictive_alerts"]:
            alert = data["predictive_alerts"][0]
            required_fields = ["device_id", "device_identifier", "prediction_type", 
                            "score", "confidence", "explanation"]
            for field in required_fields:
                assert field in alert, f"Alert missing {field}"
            assert 0 <= alert["score"] <= 1, f"Score out of range: {alert['score']}"
        
        print(f"PASS: Risk endpoint returns predictive_alerts (count={len(data['predictive_alerts'])})")
    
    def test_risk_endpoint_returns_forecast_highlights(self, auth_headers):
        """Risk endpoint should return forecast_highlights array."""
        response = requests.get(
            f"{BASE_URL}/api/operator/command-center/risk",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "forecast_highlights" in data, "Missing forecast_highlights"
        assert isinstance(data["forecast_highlights"], list), "forecast_highlights should be list"
        
        if data["forecast_highlights"]:
            highlight = data["forecast_highlights"][0]
            required_fields = ["device_id", "device_identifier", "bucket", 
                            "start_hour", "end_hour", "risk_score", "risk_level"]
            for field in required_fields:
                assert field in highlight, f"Highlight missing {field}"
            assert highlight["risk_level"] in ["HIGH", "MEDIUM", "LOW"]
        
        print(f"PASS: Risk endpoint returns forecast_highlights (count={len(data['forecast_highlights'])})")
    
    # ── Incidents endpoint tests ──
    
    def test_incidents_endpoint_returns_active_incidents(self, auth_headers):
        """Incidents endpoint should return active_incidents array."""
        response = requests.get(
            f"{BASE_URL}/api/operator/command-center/incidents",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Incidents endpoint failed: {response.text}"
        data = response.json()
        
        assert "active_incidents" in data, "Missing active_incidents"
        assert isinstance(data["active_incidents"], list), "active_incidents should be list"
        
        if data["active_incidents"]:
            incident = data["active_incidents"][0]
            required_fields = ["id", "device_id", "device_identifier", "senior_name",
                            "incident_type", "severity", "status", "escalation_level", "created_at"]
            for field in required_fields:
                assert field in incident, f"Incident missing {field}"
            assert incident["severity"] in ["critical", "high", "medium", "low"]
            assert incident["status"] not in ["resolved", "false_alarm"], "Should not return resolved/false_alarm"
        
        print(f"PASS: Incidents endpoint returns active_incidents (count={len(data['active_incidents'])})")
    
    # ── Environment endpoint tests ──
    
    def test_environment_endpoint_returns_life_pattern_alerts(self, auth_headers):
        """Environment endpoint should return life_pattern_alerts array."""
        response = requests.get(
            f"{BASE_URL}/api/operator/command-center/environment",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Environment endpoint failed: {response.text}"
        data = response.json()
        
        assert "life_pattern_alerts" in data, "Missing life_pattern_alerts"
        assert isinstance(data["life_pattern_alerts"], list), "life_pattern_alerts should be list"
        
        print(f"PASS: Environment endpoint returns life_pattern_alerts (count={len(data['life_pattern_alerts'])})")
    
    def test_environment_endpoint_returns_environment_status(self, auth_headers):
        """Environment endpoint should return environment_status array."""
        response = requests.get(
            f"{BASE_URL}/api/operator/command-center/environment",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "environment_status" in data, "Missing environment_status"
        assert isinstance(data["environment_status"], list), "environment_status should be list"
        
        if data["environment_status"]:
            status = data["environment_status"][0]
            assert "device_identifier" in status, "Status missing device_identifier"
            assert "environment_score" in status, "Status missing environment_score"
        
        print(f"PASS: Environment endpoint returns environment_status (count={len(data['environment_status'])})")
    
    # ── Old endpoint backward compatibility ──
    
    def test_old_command_center_still_works(self, auth_headers):
        """Old monolithic command-center endpoint should still work (backward compat)."""
        response = requests.get(
            f"{BASE_URL}/api/operator/command-center",
            headers=auth_headers,
            timeout=30  # May take longer as it's the old monolithic endpoint
        )
        assert response.status_code == 200, f"Old command-center failed: {response.text}"
        data = response.json()
        
        # Should have all the combined data
        assert "fleet_safety" in data or "active_incidents" in data, "Old endpoint should return combined data"
        print("PASS: Old /command-center endpoint still works (backward compat)")
    
    # ── Parallel loading performance test ──
    
    def test_parallel_load_performance(self, auth_headers):
        """All 4 endpoints should complete in parallel faster than sequential."""
        import concurrent.futures
        
        endpoints = [
            "/api/operator/command-center/fleet",
            "/api/operator/command-center/risk",
            "/api/operator/command-center/incidents",
            "/api/operator/command-center/environment",
        ]
        
        def fetch(endpoint):
            start = time.time()
            response = requests.get(f"{BASE_URL}{endpoint}", headers=auth_headers, timeout=15)
            return endpoint, response.status_code, time.time() - start
        
        start = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(fetch, endpoints))
        total_parallel = time.time() - start
        
        # Verify all succeeded
        for endpoint, status, elapsed in results:
            assert status == 200, f"{endpoint} failed with status {status}"
            print(f"  {endpoint.split('/')[-1]}: {elapsed:.2f}s")
        
        # Calculate what sequential would have been
        total_sequential = sum(r[2] for r in results)
        
        print(f"PASS: Parallel load completed in {total_parallel:.2f}s (sequential would be ~{total_sequential:.2f}s)")
        
        # Parallel should be faster than sequential
        assert total_parallel < total_sequential * 0.8, f"Parallel should be faster than 80% of sequential"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
