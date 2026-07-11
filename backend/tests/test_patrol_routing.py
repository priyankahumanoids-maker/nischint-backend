# Test Patrol Routing AI Feature
# Tests: patrol/generate, patrol/summary, patrol/shifts endpoints
# Features: Composite scoring, TSP route optimization, shift-based routing

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestPatrolRoutingAPI:
    """Test suite for Automated Patrol Routing AI endpoints"""
    
    @pytest.fixture(scope="class")
    def operator_token(self):
        """Get operator authentication token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "operator@nischint.com",
            "password": "operator123"
        })
        if response.status_code == 200:
            data = response.json()
            return data.get("access_token")
        pytest.skip("Operator authentication failed - skipping patrol tests")
    
    @pytest.fixture(scope="class")
    def guardian_token(self):
        """Get guardian authentication token (for RBAC tests)"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "nischint4parents@gmail.com",
            "password": "secret123"
        })
        if response.status_code == 200:
            data = response.json()
            return data.get("access_token")
        return None
    
    @pytest.fixture
    def auth_headers(self, operator_token):
        """Headers with operator auth"""
        return {"Authorization": f"Bearer {operator_token}"}
    
    # ─── Health Check ───
    
    def test_api_health(self):
        """Verify API is accessible"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        print("✓ API health check passed")
    
    # ─── Patrol Shifts Endpoint ───
    
    def test_patrol_shifts_returns_shift_definitions(self, auth_headers):
        """GET /api/operator/patrol/shifts returns shift definitions"""
        response = requests.get(f"{BASE_URL}/api/operator/patrol/shifts", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        
        # Verify shifts array
        assert "shifts" in data
        assert isinstance(data["shifts"], list)
        assert len(data["shifts"]) >= 3  # morning, afternoon, night
        
        # Verify shift structure
        for shift in data["shifts"]:
            assert "id" in shift
            assert "label" in shift
            assert "start_hour" in shift
            assert "end_hour" in shift
        
        # Verify expected shift IDs
        shift_ids = [s["id"] for s in data["shifts"]]
        assert "morning" in shift_ids
        assert "afternoon" in shift_ids
        assert "night" in shift_ids
        
        print(f"✓ Shifts endpoint returns {len(data['shifts'])} shifts: {shift_ids}")
    
    def test_patrol_shifts_returns_weights(self, auth_headers):
        """GET /api/operator/patrol/shifts returns scoring weights"""
        response = requests.get(f"{BASE_URL}/api/operator/patrol/shifts", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        
        # Verify weights dict
        assert "weights" in data
        weights = data["weights"]
        
        # Verify all weight components
        expected_weights = ["forecast", "trend", "activity", "learning", "temporal"]
        for w in expected_weights:
            assert w in weights
            assert isinstance(weights[w], (int, float))
            assert 0 <= weights[w] <= 1
        
        # Weights should sum to 1.0
        total = sum(weights.values())
        assert 0.99 <= total <= 1.01, f"Weights sum to {total}, expected ~1.0"
        
        print(f"✓ Weights returned: {weights}, sum={total}")
    
    # ─── Patrol Summary Endpoint ───
    
    def test_patrol_summary_returns_data(self, auth_headers):
        """GET /api/operator/patrol/summary returns lightweight summary"""
        response = requests.get(f"{BASE_URL}/api/operator/patrol/summary", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        
        # Verify required fields
        assert "total_patrol_zones" in data
        assert "critical_zones" in data
        assert "high_zones" in data
        assert "current_shift" in data
        assert "shift_label" in data
        assert "analyzed_at" in data
        
        # Verify types
        assert isinstance(data["total_patrol_zones"], int)
        assert isinstance(data["critical_zones"], int)
        assert isinstance(data["high_zones"], int)
        assert data["current_shift"] in ["morning", "afternoon", "night"]
        
        print(f"✓ Summary: {data['total_patrol_zones']} zones, {data['critical_zones']} critical, {data['high_zones']} high, shift={data['current_shift']}")
    
    # ─── Patrol Generate Endpoint - Basic ───
    
    def test_patrol_generate_morning_shift(self, auth_headers):
        """GET /api/operator/patrol/generate with morning shift"""
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "morning", "max_zones": 5, "dwell_minutes": 10},
            headers=auth_headers,
            timeout=20  # Allow extra time for composite scoring
        )
        assert response.status_code == 200
        data = response.json()
        
        # Verify response structure
        assert "route" in data
        assert "summary" in data
        assert "shift" in data
        assert "shift_label" in data
        assert "generated_at" in data
        assert "priority_breakdown" in data
        assert "weights" in data
        
        # Verify shift info
        assert data["shift"] == "morning"
        assert "Morning" in data["shift_label"]
        
        print(f"✓ Morning route generated: {len(data['route'])} zones")
    
    def test_patrol_generate_afternoon_shift(self, auth_headers):
        """GET /api/operator/patrol/generate with afternoon shift"""
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "afternoon", "max_zones": 5},
            headers=auth_headers,
            timeout=20
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["shift"] == "afternoon"
        assert "Afternoon" in data["shift_label"]
        print(f"✓ Afternoon route generated: {len(data['route'])} zones")
    
    def test_patrol_generate_night_shift(self, auth_headers):
        """GET /api/operator/patrol/generate with night shift"""
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "night", "max_zones": 5},
            headers=auth_headers,
            timeout=20
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["shift"] == "night"
        assert "Night" in data["shift_label"]
        print(f"✓ Night route generated: {len(data['route'])} zones")
    
    def test_patrol_generate_invalid_shift(self, auth_headers):
        """GET /api/operator/patrol/generate with invalid shift returns 422"""
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "invalid"},
            headers=auth_headers,
            timeout=10
        )
        assert response.status_code == 422
        print("✓ Invalid shift correctly returns 422")
    
    # ─── Patrol Generate - Route Structure Validation ───
    
    def test_patrol_generate_route_structure(self, auth_headers):
        """Verify route response includes all required zone fields"""
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "morning", "max_zones": 5},
            headers=auth_headers,
            timeout=20
        )
        assert response.status_code == 200
        data = response.json()
        
        route = data.get("route", [])
        if len(route) > 0:
            # Verify first zone has all required fields
            zone = route[0]
            
            # Core fields
            assert "zone_id" in zone
            assert "zone_name" in zone
            assert "stop_number" in zone
            assert "composite_score" in zone
            assert "patrol_priority" in zone
            
            # Verify stop_number starts at 1
            assert zone["stop_number"] == 1
            
            # Verify score is in valid range
            assert 0 <= zone["composite_score"] <= 10
            
            # Verify priority classification
            assert zone["patrol_priority"] in ["critical", "high", "medium", "low"]
            
            # Verify score_breakdown exists
            assert "score_breakdown" in zone
            breakdown = zone["score_breakdown"]
            expected_components = ["forecast", "trend", "activity", "learning", "temporal"]
            for comp in expected_components:
                assert comp in breakdown
                assert f"{comp}_weighted" in breakdown
            
            print(f"✓ Zone structure verified: {zone['zone_name']} (score={zone['composite_score']}, priority={zone['patrol_priority']})")
        else:
            print("✓ No hotspot zones available (empty route is valid)")
    
    def test_patrol_generate_summary_structure(self, auth_headers):
        """Verify summary includes distance, time, zone counts"""
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "morning", "max_zones": 5, "dwell_minutes": 10},
            headers=auth_headers,
            timeout=20
        )
        assert response.status_code == 200
        data = response.json()
        
        summary = data.get("summary", {})
        
        # Verify required summary fields
        assert "total_distance_km" in summary
        assert "total_estimated_minutes" in summary
        assert "total_zones" in summary
        
        # Verify score statistics
        if data.get("route"):
            assert "avg_composite_score" in summary
            assert "max_composite_score" in summary
            assert "min_composite_score" in summary
        
        print(f"✓ Summary: {summary.get('total_distance_km', 0)} km, {summary.get('total_estimated_minutes', 0)} min, {summary.get('total_zones', 0)} zones")
    
    def test_patrol_generate_priority_breakdown(self, auth_headers):
        """Verify priority_breakdown counts zones by priority"""
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "morning", "max_zones": 10},
            headers=auth_headers,
            timeout=20
        )
        assert response.status_code == 200
        data = response.json()
        
        pb = data.get("priority_breakdown", {})
        # Priority breakdown should be a dict with priority levels
        assert isinstance(pb, dict)
        
        # Count should match route length
        route = data.get("route", [])
        if route:
            total_from_pb = sum(pb.values())
            assert total_from_pb == len(route), f"Priority breakdown sum ({total_from_pb}) != route length ({len(route)})"
            print(f"✓ Priority breakdown: {pb}")
        else:
            print("✓ Empty route - priority breakdown check skipped")
    
    def test_patrol_generate_weights_returned(self, auth_headers):
        """Verify weights are included in generate response"""
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "morning"},
            headers=auth_headers,
            timeout=20
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "weights" in data
        weights = data["weights"]
        
        expected = ["forecast", "trend", "activity", "learning", "temporal"]
        for w in expected:
            assert w in weights
            assert isinstance(weights[w], (int, float))
        
        print(f"✓ Weights in response: {weights}")
    
    # ─── RBAC Tests ───
    
    def test_patrol_generate_requires_auth(self):
        """Patrol generate requires authentication"""
        response = requests.get(f"{BASE_URL}/api/operator/patrol/generate")
        assert response.status_code == 401 or response.status_code == 403
        print("✓ Patrol generate requires authentication")
    
    def test_patrol_summary_requires_auth(self):
        """Patrol summary requires authentication"""
        response = requests.get(f"{BASE_URL}/api/operator/patrol/summary")
        assert response.status_code == 401 or response.status_code == 403
        print("✓ Patrol summary requires authentication")
    
    def test_patrol_shifts_requires_auth(self):
        """Patrol shifts requires authentication"""
        response = requests.get(f"{BASE_URL}/api/operator/patrol/shifts")
        assert response.status_code == 401 or response.status_code == 403
        print("✓ Patrol shifts requires authentication")
    
    def test_patrol_generate_guardian_forbidden(self, guardian_token):
        """Guardian role cannot access patrol generate (operator only)"""
        if not guardian_token:
            pytest.skip("Guardian token not available")
        
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            headers={"Authorization": f"Bearer {guardian_token}"}
        )
        assert response.status_code == 403
        print("✓ Guardian correctly gets 403 on patrol generate")
    
    # ─── Parameter Validation ───
    
    def test_patrol_generate_max_zones_bounds(self, auth_headers):
        """Verify max_zones parameter bounds"""
        # Test lower bound
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "morning", "max_zones": 1},
            headers=auth_headers,
            timeout=15
        )
        assert response.status_code == 200
        
        # Test upper bound
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "morning", "max_zones": 30},
            headers=auth_headers,
            timeout=20
        )
        assert response.status_code == 200
        
        print("✓ max_zones bounds validated (1-30)")
    
    def test_patrol_generate_dwell_minutes_bounds(self, auth_headers):
        """Verify dwell_minutes parameter bounds"""
        # Test lower bound
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "morning", "dwell_minutes": 5},
            headers=auth_headers,
            timeout=15
        )
        assert response.status_code == 200
        
        # Test upper bound
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "morning", "dwell_minutes": 30},
            headers=auth_headers,
            timeout=15
        )
        assert response.status_code == 200
        
        print("✓ dwell_minutes bounds validated (5-30)")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
