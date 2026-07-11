"""
AI Adaptive Risk Learning API Tests
Tests the risk learning endpoints:
- GET /api/operator/risk-learning/stats - Learning statistics
- GET /api/operator/risk-learning/hotspots - Hotspot zones list
- POST /api/operator/risk-learning/recalculate - Trigger recalculation
"""

import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

# Test credentials
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token for operator."""
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD}
    )
    if response.status_code != 200:
        pytest.skip(f"Authentication failed: {response.status_code}")
    return response.json().get("access_token")


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Get auth headers with Bearer token."""
    return {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json"
    }


class TestRiskLearningStats:
    """Test GET /api/operator/risk-learning/stats endpoint."""
    
    def test_stats_endpoint_returns_200(self, auth_headers):
        """Test that stats endpoint returns 200 OK."""
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/stats",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print(f"PASS: Stats endpoint returns 200")
    
    def test_stats_response_structure(self, auth_headers):
        """Test that stats response has expected structure."""
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/stats",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        # Required fields in stats response
        required_fields = [
            "learned_zones_count",
            "manual_zones_count",
            "total_zones",
            "incidents_in_window",
            "geolocated_incidents",
            "lookback_days",
            "cluster_radius_m",
            "min_incidents_for_hotspot",
            "decay_half_life_days",
            "learned_zones"
        ]
        
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        
        print(f"PASS: Stats response has all required fields")
        print(f"  - learned_zones_count: {data['learned_zones_count']}")
        print(f"  - manual_zones_count: {data['manual_zones_count']}")
        print(f"  - incidents_in_window: {data['incidents_in_window']}")
        print(f"  - geolocated_incidents: {data['geolocated_incidents']}")
        print(f"  - lookback_days: {data['lookback_days']}")
    
    def test_stats_data_types(self, auth_headers):
        """Test that stats response has correct data types."""
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/stats",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        # Validate data types
        assert isinstance(data["learned_zones_count"], int), "learned_zones_count should be int"
        assert isinstance(data["manual_zones_count"], int), "manual_zones_count should be int"
        assert isinstance(data["total_zones"], int), "total_zones should be int"
        assert isinstance(data["incidents_in_window"], int), "incidents_in_window should be int"
        assert isinstance(data["geolocated_incidents"], int), "geolocated_incidents should be int"
        assert isinstance(data["lookback_days"], int), "lookback_days should be int"
        assert isinstance(data["cluster_radius_m"], int), "cluster_radius_m should be int"
        assert isinstance(data["min_incidents_for_hotspot"], int), "min_incidents_for_hotspot should be int"
        assert isinstance(data["decay_half_life_days"], int), "decay_half_life_days should be int"
        assert isinstance(data["learned_zones"], list), "learned_zones should be list"
        
        print(f"PASS: Stats response has correct data types")
    
    def test_stats_learned_zones_structure(self, auth_headers):
        """Test that learned_zones array has correct structure."""
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/stats",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        learned_zones = data["learned_zones"]
        
        if len(learned_zones) > 0:
            zone = learned_zones[0]
            expected_zone_fields = [
                "zone_name",
                "risk_score",
                "risk_level",
                "incident_count",
                "factors",
                "lat",
                "lng",
                "radius_meters",
                "last_updated"
            ]
            
            for field in expected_zone_fields:
                assert field in zone, f"Missing zone field: {field}"
            
            # Validate zone data types
            assert isinstance(zone["zone_name"], str), "zone_name should be str"
            assert isinstance(zone["risk_score"], (int, float)), "risk_score should be numeric"
            assert isinstance(zone["risk_level"], str), "risk_level should be str"
            assert isinstance(zone["incident_count"], int), "incident_count should be int"
            assert isinstance(zone["factors"], list), "factors should be list"
            assert isinstance(zone["lat"], (int, float)), "lat should be numeric"
            assert isinstance(zone["lng"], (int, float)), "lng should be numeric"
            assert isinstance(zone["radius_meters"], (int, float)), "radius_meters should be numeric"
            
            print(f"PASS: Learned zones have correct structure")
            print(f"  - Zone: {zone['zone_name']}")
            print(f"  - Risk score: {zone['risk_score']}")
            print(f"  - Risk level: {zone['risk_level']}")
            print(f"  - Incident count: {zone['incident_count']}")
        else:
            print(f"SKIP: No learned zones to validate structure")
    
    def test_stats_requires_auth(self):
        """Test that stats endpoint requires authentication."""
        response = requests.get(f"{BASE_URL}/api/operator/risk-learning/stats")
        assert response.status_code == 401 or response.status_code == 403, \
            f"Expected 401/403 without auth, got {response.status_code}"
        print(f"PASS: Stats endpoint requires authentication")


class TestRiskLearningHotspots:
    """Test GET /api/operator/risk-learning/hotspots endpoint."""
    
    def test_hotspots_endpoint_returns_200(self, auth_headers):
        """Test that hotspots endpoint returns 200 OK."""
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/hotspots",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print(f"PASS: Hotspots endpoint returns 200")
    
    def test_hotspots_response_structure(self, auth_headers):
        """Test that hotspots response has expected structure."""
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/hotspots",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        # Required fields
        assert "hotspots" in data, "Missing 'hotspots' field"
        assert "count" in data, "Missing 'count' field"
        
        assert isinstance(data["hotspots"], list), "hotspots should be list"
        assert isinstance(data["count"], int), "count should be int"
        
        # Count should match list length
        assert data["count"] == len(data["hotspots"]), \
            f"Count mismatch: count={data['count']}, actual={len(data['hotspots'])}"
        
        print(f"PASS: Hotspots response has correct structure")
        print(f"  - Count: {data['count']}")
        print(f"  - Hotspots array length: {len(data['hotspots'])}")
    
    def test_hotspots_requires_auth(self):
        """Test that hotspots endpoint requires authentication."""
        response = requests.get(f"{BASE_URL}/api/operator/risk-learning/hotspots")
        assert response.status_code == 401 or response.status_code == 403, \
            f"Expected 401/403 without auth, got {response.status_code}"
        print(f"PASS: Hotspots endpoint requires authentication")


class TestRiskLearningRecalculate:
    """Test POST /api/operator/risk-learning/recalculate endpoint."""
    
    def test_recalculate_endpoint_returns_200(self, auth_headers):
        """Test that recalculate endpoint returns 200 OK."""
        response = requests.post(
            f"{BASE_URL}/api/operator/risk-learning/recalculate",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print(f"PASS: Recalculate endpoint returns 200")
    
    def test_recalculate_response_structure(self, auth_headers):
        """Test that recalculate response has expected structure."""
        response = requests.post(
            f"{BASE_URL}/api/operator/risk-learning/recalculate",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        # Required fields in recalculate response
        required_fields = [
            "status",
            "incidents_analyzed",
            "clusters_found",
            "hotspots_created",
            "old_zones_removed",
            "last_updated"
        ]
        
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        
        # Status should be "completed"
        assert data["status"] == "completed", f"Expected status='completed', got '{data['status']}'"
        
        print(f"PASS: Recalculate response has correct structure")
        print(f"  - Status: {data['status']}")
        print(f"  - Incidents analyzed: {data['incidents_analyzed']}")
        print(f"  - Clusters found: {data['clusters_found']}")
        print(f"  - Hotspots created: {data['hotspots_created']}")
        print(f"  - Old zones removed: {data['old_zones_removed']}")
    
    def test_recalculate_data_types(self, auth_headers):
        """Test that recalculate response has correct data types."""
        response = requests.post(
            f"{BASE_URL}/api/operator/risk-learning/recalculate",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        assert isinstance(data["status"], str), "status should be str"
        assert isinstance(data["incidents_analyzed"], int), "incidents_analyzed should be int"
        assert isinstance(data["clusters_found"], int), "clusters_found should be int"
        assert isinstance(data["hotspots_created"], int), "hotspots_created should be int"
        assert isinstance(data["old_zones_removed"], int), "old_zones_removed should be int"
        
        print(f"PASS: Recalculate response has correct data types")
    
    def test_recalculate_top_hotspots(self, auth_headers):
        """Test that recalculate returns top hotspots."""
        response = requests.post(
            f"{BASE_URL}/api/operator/risk-learning/recalculate",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "top_hotspots" in data, "Missing 'top_hotspots' field"
        assert isinstance(data["top_hotspots"], list), "top_hotspots should be list"
        
        # Top hotspots should be max 5
        assert len(data["top_hotspots"]) <= 5, f"Top hotspots should be max 5, got {len(data['top_hotspots'])}"
        
        if len(data["top_hotspots"]) > 0:
            hotspot = data["top_hotspots"][0]
            assert "lat" in hotspot, "Hotspot missing lat"
            assert "lng" in hotspot, "Hotspot missing lng"
            assert "risk_score" in hotspot, "Hotspot missing risk_score"
            assert "incident_count" in hotspot, "Hotspot missing incident_count"
            
            print(f"PASS: Top hotspots returned ({len(data['top_hotspots'])} hotspots)")
            print(f"  - Top hotspot risk_score: {hotspot['risk_score']}")
            print(f"  - Top hotspot incident_count: {hotspot['incident_count']}")
        else:
            print(f"SKIP: No top hotspots to validate")
    
    def test_recalculate_requires_auth(self):
        """Test that recalculate endpoint requires authentication."""
        response = requests.post(f"{BASE_URL}/api/operator/risk-learning/recalculate")
        assert response.status_code == 401 or response.status_code == 403, \
            f"Expected 401/403 without auth, got {response.status_code}"
        print(f"PASS: Recalculate endpoint requires authentication")


class TestRiskLearningIntegration:
    """Integration tests for risk learning workflow."""
    
    def test_recalculate_then_verify_stats(self, auth_headers):
        """Test recalculate and verify stats are updated."""
        # Trigger recalculation
        recalc_response = requests.post(
            f"{BASE_URL}/api/operator/risk-learning/recalculate",
            headers=auth_headers
        )
        assert recalc_response.status_code == 200
        recalc_data = recalc_response.json()
        
        # Get stats
        stats_response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/stats",
            headers=auth_headers
        )
        assert stats_response.status_code == 200
        stats_data = stats_response.json()
        
        # Verify hotspots_created matches learned_zones_count
        assert recalc_data["hotspots_created"] == stats_data["learned_zones_count"], \
            f"Mismatch: recalc created {recalc_data['hotspots_created']}, stats shows {stats_data['learned_zones_count']}"
        
        print(f"PASS: Recalculate and stats are consistent")
        print(f"  - Hotspots created: {recalc_data['hotspots_created']}")
        print(f"  - Learned zones count: {stats_data['learned_zones_count']}")
    
    def test_hotspots_matches_stats_learned_zones(self, auth_headers):
        """Test that hotspots endpoint returns same data as stats learned_zones."""
        # Get stats
        stats_response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/stats",
            headers=auth_headers
        )
        assert stats_response.status_code == 200
        stats_data = stats_response.json()
        
        # Get hotspots
        hotspots_response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/hotspots",
            headers=auth_headers
        )
        assert hotspots_response.status_code == 200
        hotspots_data = hotspots_response.json()
        
        # Verify count matches
        assert stats_data["learned_zones_count"] == hotspots_data["count"], \
            f"Mismatch: stats shows {stats_data['learned_zones_count']}, hotspots shows {hotspots_data['count']}"
        
        # Verify array lengths match
        assert len(stats_data["learned_zones"]) == len(hotspots_data["hotspots"]), \
            f"Array length mismatch: stats has {len(stats_data['learned_zones'])}, hotspots has {len(hotspots_data['hotspots'])}"
        
        print(f"PASS: Hotspots and stats learned_zones are consistent")
        print(f"  - Count: {hotspots_data['count']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
