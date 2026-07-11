"""
P1: Route Safety ↔ Heatmap Integration + P2: Command Center Heatmap Widget Tests
Tests for route safety heatmap integration and city risk snapshot widget
"""
import os
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://gps-mic-restart.preview.emergentagent.com').rstrip('/')

# Test credentials
TEST_EMAIL = "operator@nischint.com"
TEST_PASSWORD = "operator123"

# Bangalore coordinates for testing
START_LAT = 12.975
START_LNG = 77.590
END_LAT = 12.955
END_LNG = 77.575


@pytest.fixture(scope="module")
def auth_token():
    """Get operator authentication token."""
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
    )
    if response.status_code != 200:
        pytest.skip(f"Auth failed: {response.status_code} - {response.text}")
    data = response.json()
    return data.get("access_token")


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Get headers with auth token."""
    return {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json"
    }


# ═══════════════════════════════════════════════════════════════════════════════
# P1: Route Safety Heatmap Integration Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestRouteSafetyHeatmapIntegration:
    """Tests for POST /api/operator/route-safety with heatmap integration."""
    
    def test_route_safety_returns_200(self, auth_headers):
        """Route safety endpoint returns 200 OK with valid coordinates."""
        response = requests.post(
            f"{BASE_URL}/api/operator/route-safety",
            params={
                "start_lat": START_LAT,
                "start_lng": START_LNG,
                "end_lat": END_LAT,
                "end_lng": END_LNG
            },
            headers=auth_headers,
            timeout=30
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "routes" in data, "Response must contain 'routes'"
        assert len(data["routes"]) >= 1, "Must have at least 1 route"
    
    def test_route_safety_heatmap_integrated_field(self, auth_headers):
        """Response includes heatmap_integrated flag."""
        response = requests.post(
            f"{BASE_URL}/api/operator/route-safety",
            params={
                "start_lat": START_LAT,
                "start_lng": START_LNG,
                "end_lat": END_LAT,
                "end_lng": END_LNG
            },
            headers=auth_headers,
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        assert "heatmap_integrated" in data, "Response must have 'heatmap_integrated' field"
        # heatmap_integrated should be True if heatmap cells exist
        print(f"heatmap_integrated: {data['heatmap_integrated']}")
    
    def test_route_has_base_risk_score(self, auth_headers):
        """Each route has base_risk_score field."""
        response = requests.post(
            f"{BASE_URL}/api/operator/route-safety",
            params={
                "start_lat": START_LAT,
                "start_lng": START_LNG,
                "end_lat": END_LAT,
                "end_lng": END_LNG
            },
            headers=auth_headers,
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        for route in data["routes"]:
            assert "base_risk_score" in route, f"Route {route.get('index')} missing 'base_risk_score'"
            assert isinstance(route["base_risk_score"], (int, float)), "base_risk_score should be numeric"
            print(f"Route {route['index']}: base_risk_score={route['base_risk_score']}")
    
    def test_route_has_heatmap_penalty(self, auth_headers):
        """Each route has heatmap_penalty field."""
        response = requests.post(
            f"{BASE_URL}/api/operator/route-safety",
            params={
                "start_lat": START_LAT,
                "start_lng": START_LNG,
                "end_lat": END_LAT,
                "end_lng": END_LNG
            },
            headers=auth_headers,
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        for route in data["routes"]:
            assert "heatmap_penalty" in route, f"Route {route.get('index')} missing 'heatmap_penalty'"
            assert isinstance(route["heatmap_penalty"], (int, float)), "heatmap_penalty should be numeric"
            print(f"Route {route['index']}: heatmap_penalty={route['heatmap_penalty']}")
    
    def test_route_risk_score_calculation(self, auth_headers):
        """route_risk_score = base_risk_score + heatmap_penalty (capped at 10.0)."""
        response = requests.post(
            f"{BASE_URL}/api/operator/route-safety",
            params={
                "start_lat": START_LAT,
                "start_lng": START_LNG,
                "end_lat": END_LAT,
                "end_lng": END_LNG
            },
            headers=auth_headers,
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        for route in data["routes"]:
            base_score = route["base_risk_score"]
            heatmap_penalty = route["heatmap_penalty"]
            route_risk = route["route_risk_score"]
            expected = min(10.0, base_score + heatmap_penalty)
            # Allow small floating point difference
            assert abs(route_risk - expected) <= 0.15, \
                f"Route {route['index']}: route_risk_score ({route_risk}) != min(10.0, {base_score} + {heatmap_penalty}) = {expected}"
            print(f"Route {route['index']}: {route_risk} = min(10.0, {base_score} + {heatmap_penalty})")
    
    def test_route_has_heatmap_risk_zones(self, auth_headers):
        """Each route has heatmap_risk_zones array."""
        response = requests.post(
            f"{BASE_URL}/api/operator/route-safety",
            params={
                "start_lat": START_LAT,
                "start_lng": START_LNG,
                "end_lat": END_LAT,
                "end_lng": END_LNG
            },
            headers=auth_headers,
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        for route in data["routes"]:
            assert "heatmap_risk_zones" in route, f"Route {route.get('index')} missing 'heatmap_risk_zones'"
            assert isinstance(route["heatmap_risk_zones"], list), "heatmap_risk_zones should be a list"
            print(f"Route {route['index']}: {len(route['heatmap_risk_zones'])} heatmap risk zones")
    
    def test_heatmap_risk_zone_structure(self, auth_headers):
        """heatmap_risk_zones contain required fields: grid_id, lat, lng, risk_level, composite_score."""
        response = requests.post(
            f"{BASE_URL}/api/operator/route-safety",
            params={
                "start_lat": START_LAT,
                "start_lng": START_LNG,
                "end_lat": END_LAT,
                "end_lng": END_LNG
            },
            headers=auth_headers,
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        
        # Find a route with risk zones
        routes_with_zones = [r for r in data["routes"] if len(r.get("heatmap_risk_zones", [])) > 0]
        if not routes_with_zones:
            print("No routes have heatmap_risk_zones - this may be expected if no dangerous cells are near the route")
            return  # Skip if no zones
        
        route = routes_with_zones[0]
        zone = route["heatmap_risk_zones"][0]
        required_fields = ["grid_id", "lat", "lng", "risk_level", "composite_score"]
        for field in required_fields:
            assert field in zone, f"Risk zone missing required field: {field}"
        
        # Validate risk_level values
        assert zone["risk_level"] in ["critical", "high", "moderate", "safe"], \
            f"Invalid risk_level: {zone['risk_level']}"
        
        print(f"Sample risk zone: grid_id={zone['grid_id']}, risk_level={zone['risk_level']}, score={zone['composite_score']}")
    
    def test_route_has_heatmap_warnings(self, auth_headers):
        """Each route has heatmap_warnings array."""
        response = requests.post(
            f"{BASE_URL}/api/operator/route-safety",
            params={
                "start_lat": START_LAT,
                "start_lng": START_LNG,
                "end_lat": END_LAT,
                "end_lng": END_LNG
            },
            headers=auth_headers,
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        for route in data["routes"]:
            assert "heatmap_warnings" in route, f"Route {route.get('index')} missing 'heatmap_warnings'"
            assert isinstance(route["heatmap_warnings"], list), "heatmap_warnings should be a list"
            if route["heatmap_warnings"]:
                print(f"Route {route['index']} warnings: {route['heatmap_warnings']}")
    
    def test_heatmap_warnings_content(self, auth_headers):
        """heatmap_warnings contain descriptive messages about crossings."""
        response = requests.post(
            f"{BASE_URL}/api/operator/route-safety",
            params={
                "start_lat": START_LAT,
                "start_lng": START_LNG,
                "end_lat": END_LAT,
                "end_lng": END_LNG
            },
            headers=auth_headers,
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        
        # Find a route with warnings
        routes_with_warnings = [r for r in data["routes"] if len(r.get("heatmap_warnings", [])) > 0]
        if not routes_with_warnings:
            print("No routes have heatmap_warnings - expected if route doesn't cross danger zones")
            return  # Skip if no warnings
        
        route = routes_with_warnings[0]
        warning = route["heatmap_warnings"][0]
        assert isinstance(warning, str), "Each warning should be a string"
        # Warnings should mention critical/high crossings or escalations
        valid_keywords = ["critical", "high", "zone", "area", "crosses", "passes", "escalating", "forecast"]
        has_keyword = any(kw in warning.lower() for kw in valid_keywords)
        assert has_keyword, f"Warning doesn't contain expected keywords: {warning}"
        print(f"Sample warning: {warning}")
    
    def test_route_has_heatmap_summary(self, auth_headers):
        """Each route has heatmap_summary with crossing counts."""
        response = requests.post(
            f"{BASE_URL}/api/operator/route-safety",
            params={
                "start_lat": START_LAT,
                "start_lng": START_LNG,
                "end_lat": END_LAT,
                "end_lng": END_LNG
            },
            headers=auth_headers,
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        for route in data["routes"]:
            assert "heatmap_summary" in route, f"Route {route.get('index')} missing 'heatmap_summary'"
            summary = route["heatmap_summary"]
            assert "critical_crossings" in summary, "heatmap_summary missing 'critical_crossings'"
            assert "high_crossings" in summary, "heatmap_summary missing 'high_crossings'"
            print(f"Route {route['index']} summary: critical={summary['critical_crossings']}, high={summary['high_crossings']}")
    
    def test_route_safety_requires_auth(self):
        """Route safety endpoint requires authentication."""
        response = requests.post(
            f"{BASE_URL}/api/operator/route-safety",
            params={
                "start_lat": START_LAT,
                "start_lng": START_LNG,
                "end_lat": END_LAT,
                "end_lng": END_LNG
            },
            timeout=10
        )
        assert response.status_code in [401, 403], f"Expected 401/403 without auth, got {response.status_code}"


# ═══════════════════════════════════════════════════════════════════════════════
# P2: City Heatmap Stats for Command Center Widget
# ═══════════════════════════════════════════════════════════════════════════════

class TestCityHeatmapStats:
    """Tests for GET /api/operator/city-heatmap/stats."""
    
    def test_heatmap_stats_returns_200(self, auth_headers):
        """Heatmap stats endpoint returns 200 OK."""
        response = requests.get(
            f"{BASE_URL}/api/operator/city-heatmap/stats",
            headers=auth_headers,
            timeout=15
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    
    def test_heatmap_stats_has_total_zones(self, auth_headers):
        """Response includes total_zones count."""
        response = requests.get(
            f"{BASE_URL}/api/operator/city-heatmap/stats",
            headers=auth_headers,
            timeout=15
        )
        assert response.status_code == 200
        data = response.json()
        assert "total_zones" in data, "Response missing 'total_zones'"
        assert isinstance(data["total_zones"], int), "total_zones should be integer"
        print(f"total_zones: {data['total_zones']}")
    
    def test_heatmap_stats_has_critical_zones(self, auth_headers):
        """Response includes critical_zones count."""
        response = requests.get(
            f"{BASE_URL}/api/operator/city-heatmap/stats",
            headers=auth_headers,
            timeout=15
        )
        assert response.status_code == 200
        data = response.json()
        assert "critical_zones" in data, "Response missing 'critical_zones'"
        assert isinstance(data["critical_zones"], int), "critical_zones should be integer"
        print(f"critical_zones: {data['critical_zones']}")
    
    def test_heatmap_stats_has_high_risk_zones(self, auth_headers):
        """Response includes high_risk_zones count."""
        response = requests.get(
            f"{BASE_URL}/api/operator/city-heatmap/stats",
            headers=auth_headers,
            timeout=15
        )
        assert response.status_code == 200
        data = response.json()
        assert "high_risk_zones" in data, "Response missing 'high_risk_zones'"
        assert isinstance(data["high_risk_zones"], int), "high_risk_zones should be integer"
        print(f"high_risk_zones: {data['high_risk_zones']}")
    
    def test_heatmap_stats_has_recent_incidents(self, auth_headers):
        """Response includes recent_incidents_7d count."""
        response = requests.get(
            f"{BASE_URL}/api/operator/city-heatmap/stats",
            headers=auth_headers,
            timeout=15
        )
        assert response.status_code == 200
        data = response.json()
        assert "recent_incidents_7d" in data, "Response missing 'recent_incidents_7d'"
        assert isinstance(data["recent_incidents_7d"], int), "recent_incidents_7d should be integer"
        print(f"recent_incidents_7d: {data['recent_incidents_7d']}")
    
    def test_heatmap_stats_requires_auth(self):
        """Heatmap stats endpoint requires authentication."""
        response = requests.get(
            f"{BASE_URL}/api/operator/city-heatmap/stats",
            timeout=10
        )
        assert response.status_code in [401, 403], f"Expected 401/403 without auth, got {response.status_code}"


# ═══════════════════════════════════════════════════════════════════════════════
# Route Safety Heatmap Penalty Validation
# ═══════════════════════════════════════════════════════════════════════════════

class TestHeatmapPenaltyCalculation:
    """Tests for heatmap penalty calculation formula."""
    
    def test_heatmap_penalty_capped_at_3(self, auth_headers):
        """Heatmap penalty is capped at 3.0 max."""
        response = requests.post(
            f"{BASE_URL}/api/operator/route-safety",
            params={
                "start_lat": START_LAT,
                "start_lng": START_LNG,
                "end_lat": END_LAT,
                "end_lng": END_LNG
            },
            headers=auth_headers,
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        for route in data["routes"]:
            penalty = route["heatmap_penalty"]
            assert penalty <= 3.0, f"Route {route['index']} penalty {penalty} exceeds cap of 3.0"
            print(f"Route {route['index']}: heatmap_penalty={penalty} (max 3.0)")
    
    def test_penalty_matches_crossings(self, auth_headers):
        """Heatmap penalty formula: critical*0.8 + high*0.4, capped at 3.0."""
        response = requests.post(
            f"{BASE_URL}/api/operator/route-safety",
            params={
                "start_lat": START_LAT,
                "start_lng": START_LNG,
                "end_lat": END_LAT,
                "end_lng": END_LNG
            },
            headers=auth_headers,
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        for route in data["routes"]:
            summary = route["heatmap_summary"]
            critical = summary["critical_crossings"]
            high = summary["high_crossings"]
            expected = min(3.0, critical * 0.8 + high * 0.4)
            actual = route["heatmap_penalty"]
            # Allow small floating point difference
            assert abs(actual - expected) <= 0.05, \
                f"Route {route['index']}: penalty {actual} != expected {expected} (critical={critical}, high={high})"
            print(f"Route {route['index']}: penalty={actual}, critical*0.8+high*0.4={expected}")


# ═══════════════════════════════════════════════════════════════════════════════
# Command Center Integration Test
# ═══════════════════════════════════════════════════════════════════════════════

class TestCommandCenterHeatmapWidget:
    """Tests verifying Command Center receives heatmap stats for widget."""
    
    def test_command_center_can_use_heatmap_stats(self, auth_headers):
        """Command Center can fetch heatmap stats for City Risk Snapshot widget."""
        # Verify heatmap stats endpoint is accessible from same auth context
        response = requests.get(
            f"{BASE_URL}/api/operator/city-heatmap/stats",
            headers=auth_headers,
            timeout=15
        )
        assert response.status_code == 200
        data = response.json()
        
        # Verify all fields needed for widget
        assert "total_zones" in data
        assert "critical_zones" in data
        assert "high_risk_zones" in data
        assert "recent_incidents_7d" in data
        
        # Calculate safe zones (as done in frontend)
        safe_zones = max(0, data["total_zones"] - data["critical_zones"] - data["high_risk_zones"])
        print(f"Widget data: critical={data['critical_zones']}, high={data['high_risk_zones']}, safe={safe_zones}, incidents(7d)={data['recent_incidents_7d']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
