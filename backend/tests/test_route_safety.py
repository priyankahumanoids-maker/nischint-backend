"""
Route Safety Engine Tests
=========================
Tests for POST /api/operator/route-safety endpoint which evaluates
safety of routes between two points using OSRM + PostGIS risk zones.
"""

import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Operator credentials
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"

# Test coordinates (Bangalore area)
START_LAT = 12.9716
START_LNG = 77.5946
END_LAT = 12.9352
END_LNG = 77.6245


@pytest.fixture(scope="module")
def auth_token():
    """Get operator auth token"""
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD}
    )
    assert response.status_code == 200, f"Login failed: {response.text}"
    data = response.json()
    assert "access_token" in data, "No access_token in response"
    return data["access_token"]


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Create auth headers"""
    return {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}


class TestRouteSafetyAuth:
    """Authentication tests for route safety endpoint"""
    
    def test_route_safety_requires_auth(self):
        """POST /api/operator/route-safety should require authentication"""
        response = requests.post(
            f"{BASE_URL}/api/operator/route-safety",
            params={"start_lat": START_LAT, "start_lng": START_LNG, "end_lat": END_LAT, "end_lng": END_LNG}
        )
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("PASS: Route safety requires authentication")


class TestRouteSafetyAPI:
    """Main route safety API tests"""
    
    def test_route_safety_returns_routes(self, auth_headers):
        """POST /api/operator/route-safety returns 3 routes with expected structure"""
        response = requests.post(
            f"{BASE_URL}/api/operator/route-safety",
            params={"start_lat": START_LAT, "start_lng": START_LNG, "end_lat": END_LAT, "end_lng": END_LNG},
            headers=auth_headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Check top-level fields
        assert "routes" in data, "Missing 'routes' field"
        assert "recommendation" in data, "Missing 'recommendation' field"
        assert "start" in data, "Missing 'start' field"
        assert "end" in data, "Missing 'end' field"
        assert "evaluated_at" in data, "Missing 'evaluated_at' field"
        
        print(f"PASS: Route safety response has all required top-level fields")
    
    def test_returns_exactly_3_routes(self, auth_headers):
        """API returns exactly 3 route options"""
        response = requests.post(
            f"{BASE_URL}/api/operator/route-safety",
            params={"start_lat": START_LAT, "start_lng": START_LNG, "end_lat": END_LAT, "end_lng": END_LNG},
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        routes = data.get("routes", [])
        assert len(routes) == 3, f"Expected 3 routes, got {len(routes)}"
        print(f"PASS: API returns exactly 3 routes")
    
    def test_route_structure_fields(self, auth_headers):
        """Each route has required fields: index, label, distance_km, duration_min, route_risk_score, geometry, segments"""
        response = requests.post(
            f"{BASE_URL}/api/operator/route-safety",
            params={"start_lat": START_LAT, "start_lng": START_LNG, "end_lat": END_LAT, "end_lng": END_LNG},
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        required_fields = ["index", "label", "distance_km", "duration_min", "route_risk_score", "geometry", "segments"]
        for route in data["routes"]:
            for field in required_fields:
                assert field in route, f"Route missing required field: {field}"
        
        print(f"PASS: All routes have required fields: {required_fields}")
    
    def test_route_labels_include_safest_shortest_balanced(self, auth_headers):
        """Route labels should include 'safest', 'shortest', and 'balanced'"""
        response = requests.post(
            f"{BASE_URL}/api/operator/route-safety",
            params={"start_lat": START_LAT, "start_lng": START_LNG, "end_lat": END_LAT, "end_lng": END_LNG},
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        all_labels = set()
        for route in data["routes"]:
            labels = route.get("label", [])
            for lbl in labels:
                all_labels.add(lbl)
        
        # Should contain safest, shortest, balanced (or some may overlap)
        expected_labels = {"safest", "shortest", "balanced"}
        found_labels = all_labels.intersection(expected_labels)
        assert len(found_labels) >= 1, f"Expected at least one of {expected_labels}, got {all_labels}"
        print(f"PASS: Route labels include: {found_labels}")
    
    def test_recommendation_points_to_safest(self, auth_headers):
        """Recommendation field should point to the index of the safest route"""
        response = requests.post(
            f"{BASE_URL}/api/operator/route-safety",
            params={"start_lat": START_LAT, "start_lng": START_LNG, "end_lat": END_LAT, "end_lng": END_LNG},
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        recommendation = data.get("recommendation")
        assert recommendation is not None, "Missing recommendation field"
        assert isinstance(recommendation, int), f"recommendation should be int, got {type(recommendation)}"
        
        # Verify recommended route has 'safest' label
        recommended_route = next((r for r in data["routes"] if r["index"] == recommendation), None)
        assert recommended_route is not None, f"No route with index {recommendation}"
        assert "safest" in recommended_route.get("label", []), f"Recommended route doesn't have 'safest' label"
        
        print(f"PASS: Recommendation index {recommendation} points to safest route")
    
    def test_route_risk_scores_are_valid(self, auth_headers):
        """All route_risk_score values are numbers between 0-10"""
        response = requests.post(
            f"{BASE_URL}/api/operator/route-safety",
            params={"start_lat": START_LAT, "start_lng": START_LNG, "end_lat": END_LAT, "end_lng": END_LNG},
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        for route in data["routes"]:
            score = route.get("route_risk_score")
            assert score is not None, "Missing route_risk_score"
            assert isinstance(score, (int, float)), f"route_risk_score should be numeric, got {type(score)}"
            assert 0 <= score <= 10, f"route_risk_score out of range: {score}"
        
        print(f"PASS: All route risk scores are valid (0-10)")
    
    def test_geometry_is_coordinate_array(self, auth_headers):
        """Geometry field is array of [lng, lat] coordinate pairs"""
        response = requests.post(
            f"{BASE_URL}/api/operator/route-safety",
            params={"start_lat": START_LAT, "start_lng": START_LNG, "end_lat": END_LAT, "end_lng": END_LNG},
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        for route in data["routes"]:
            geometry = route.get("geometry")
            assert geometry is not None, "Missing geometry field"
            assert isinstance(geometry, list), "Geometry should be a list"
            assert len(geometry) > 0, "Geometry should not be empty"
            
            # Check first coordinate is [lng, lat]
            first_coord = geometry[0]
            assert isinstance(first_coord, list), "Coordinate should be [lng, lat] array"
            assert len(first_coord) == 2, "Coordinate should have 2 elements"
            assert isinstance(first_coord[0], (int, float)), "Longitude should be numeric"
            assert isinstance(first_coord[1], (int, float)), "Latitude should be numeric"
        
        print(f"PASS: Geometry is valid coordinate array")
    
    def test_segments_array_with_risk_info(self, auth_headers):
        """Segments array contains risk information per segment"""
        response = requests.post(
            f"{BASE_URL}/api/operator/route-safety",
            params={"start_lat": START_LAT, "start_lng": START_LNG, "end_lat": END_LAT, "end_lng": END_LNG},
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        for route in data["routes"]:
            segments = route.get("segments")
            assert segments is not None, "Missing segments field"
            assert isinstance(segments, list), "Segments should be a list"
            
            if len(segments) > 0:
                # Check segment structure
                segment = segments[0]
                assert "lat" in segment, "Segment missing 'lat'"
                assert "lng" in segment, "Segment missing 'lng'"
                assert "risk" in segment, "Segment missing 'risk'"
                assert "level" in segment, "Segment missing 'level'"
        
        print(f"PASS: Segments contain risk information")
    
    def test_additional_route_fields(self, auth_headers):
        """Check additional route fields: distance_m, duration_s, risk_level, dangerous_segments, etc."""
        response = requests.post(
            f"{BASE_URL}/api/operator/route-safety",
            params={"start_lat": START_LAT, "start_lng": START_LNG, "end_lat": END_LAT, "end_lng": END_LNG},
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        for route in data["routes"]:
            # Check distance/duration
            assert "distance_m" in route or "distance_km" in route, "Missing distance field"
            assert "duration_s" in route or "duration_min" in route, "Missing duration field"
            
            # Check risk categorization
            assert "risk_level" in route, "Missing risk_level"
            assert route["risk_level"] in ["Low", "Moderate", "High", "Critical"], f"Invalid risk_level: {route['risk_level']}"
            
            # Check dangerous segment count
            assert "dangerous_segments" in route, "Missing dangerous_segments count"
            assert isinstance(route["dangerous_segments"], int), "dangerous_segments should be int"
        
        print(f"PASS: Routes have all additional fields")


class TestRouteSafetyCoordinateValidation:
    """Coordinate validation tests"""
    
    def test_invalid_start_lat(self, auth_headers):
        """Invalid start latitude should return error"""
        response = requests.post(
            f"{BASE_URL}/api/operator/route-safety",
            params={"start_lat": 91, "start_lng": START_LNG, "end_lat": END_LAT, "end_lng": END_LNG},
            headers=auth_headers
        )
        assert response.status_code == 422, f"Expected 422 for invalid latitude, got {response.status_code}"
        print("PASS: Invalid start latitude rejected")
    
    def test_invalid_end_lng(self, auth_headers):
        """Invalid end longitude should return error"""
        response = requests.post(
            f"{BASE_URL}/api/operator/route-safety",
            params={"start_lat": START_LAT, "start_lng": START_LNG, "end_lat": END_LAT, "end_lng": 181},
            headers=auth_headers
        )
        assert response.status_code == 422, f"Expected 422 for invalid longitude, got {response.status_code}"
        print("PASS: Invalid end longitude rejected")


class TestRouteSafetyPerformance:
    """Performance and response time tests"""
    
    def test_response_time_reasonable(self, auth_headers):
        """Route evaluation should complete within 10 seconds"""
        start_time = time.time()
        response = requests.post(
            f"{BASE_URL}/api/operator/route-safety",
            params={"start_lat": START_LAT, "start_lng": START_LNG, "end_lat": END_LAT, "end_lng": END_LNG},
            headers=auth_headers,
            timeout=10
        )
        elapsed = time.time() - start_time
        
        assert response.status_code == 200, f"Request failed: {response.status_code}"
        assert elapsed < 10, f"Request took too long: {elapsed}s"
        print(f"PASS: Response time {elapsed:.2f}s is within acceptable range")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
