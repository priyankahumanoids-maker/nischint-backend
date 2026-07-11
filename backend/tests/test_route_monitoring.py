"""
Route Monitoring API Tests
Tests the Live Route Monitoring system:
- POST /api/operator/route-monitor - Assign route to device
- GET /api/operator/route-monitor/{device_id} - Get position tracking status
- GET /api/operator/route-monitors - List all active monitors
- DELETE /api/operator/route-monitor/{device_id} - Cancel monitoring
- Validates 200m sampling interval for route safety
- Tests OSRM resilience (retry logic)
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"
TEST_DEVICE_ID = "ce4b5463-5a7e-46a5-8bbf-365dcfb3daeb"  # DEV-001


@pytest.fixture(scope="module")
def auth_token():
    """Get operator authentication token."""
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
    """Create auth headers."""
    return {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def route_data(auth_headers):
    """Get route data from route safety endpoint for testing."""
    # Bangalore coordinates
    response = requests.post(
        f"{BASE_URL}/api/operator/route-safety",
        params={
            "start_lat": 12.9716, "start_lng": 77.5946,
            "end_lat": 12.9352, "end_lng": 77.6245
        },
        headers=auth_headers
    )
    assert response.status_code == 200, f"Route safety failed: {response.text}"
    data = response.json()
    assert "routes" in data, "No routes in response"
    assert len(data["routes"]) >= 1, "No routes returned"
    return data


class TestRouteMonitoringAuth:
    """Test authentication requirements for route monitoring endpoints."""
    
    def test_assign_route_monitor_requires_auth(self):
        """POST /api/operator/route-monitor returns 401 without auth."""
        response = requests.post(f"{BASE_URL}/api/operator/route-monitor")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
    
    def test_get_route_monitor_requires_auth(self):
        """GET /api/operator/route-monitor/{device_id} returns 401 without auth."""
        response = requests.get(f"{BASE_URL}/api/operator/route-monitor/{TEST_DEVICE_ID}")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
    
    def test_list_route_monitors_requires_auth(self):
        """GET /api/operator/route-monitors returns 401 without auth."""
        response = requests.get(f"{BASE_URL}/api/operator/route-monitors")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
    
    def test_cancel_route_monitor_requires_auth(self):
        """DELETE /api/operator/route-monitor/{device_id} returns 401 without auth."""
        response = requests.delete(f"{BASE_URL}/api/operator/route-monitor/{TEST_DEVICE_ID}")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"


class TestRouteSafetySampling:
    """Test that route safety uses 200m sampling interval."""
    
    def test_route_safety_returns_routes(self, auth_headers, route_data):
        """Verify route safety endpoint works and returns routes."""
        assert "routes" in route_data
        assert len(route_data["routes"]) >= 1
    
    def test_routes_have_sampled_points(self, route_data):
        """Verify routes have sampled_points field."""
        for route in route_data["routes"]:
            assert "sampled_points" in route, "Route missing sampled_points"
            assert route["sampled_points"] > 0, "No sampled points"
    
    def test_routes_have_segments(self, route_data):
        """Verify routes have segments with risk info."""
        for route in route_data["routes"]:
            assert "segments" in route, "Route missing segments"
            assert isinstance(route["segments"], list), "segments not a list"
            # Each segment should have lat, lng, risk, level
            if len(route["segments"]) > 0:
                seg = route["segments"][0]
                assert "lat" in seg, "Segment missing lat"
                assert "lng" in seg, "Segment missing lng"
                assert "risk" in seg, "Segment missing risk"
                assert "level" in seg, "Segment missing level"
    
    def test_sampling_produces_reasonable_points(self, route_data):
        """Verify 200m sampling produces reasonable number of points."""
        for route in route_data["routes"]:
            distance_km = route.get("distance_km", 0)
            sampled_points = route.get("sampled_points", 0)
            
            # With 200m sampling, we expect roughly distance_km * 1000 / 200 = distance_km * 5 points
            # Allow margin for start/end points
            if distance_km > 0:
                expected_min = int(distance_km * 3)  # Conservative minimum
                assert sampled_points >= expected_min, f"Expected at least {expected_min} points for {distance_km}km route, got {sampled_points}"


class TestRouteMonitorAssignment:
    """Test route monitor assignment endpoint."""
    
    def test_assign_route_requires_route_data(self, auth_headers):
        """POST /api/operator/route-monitor requires route_data in body."""
        response = requests.post(
            f"{BASE_URL}/api/operator/route-monitor",
            params={
                "device_id": TEST_DEVICE_ID,
                "route_index": 0,
                "start_lat": 12.9716, "start_lng": 77.5946,
                "end_lat": 12.9352, "end_lng": 77.6245
            },
            json={},  # Empty body - no route_data
            headers=auth_headers
        )
        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        assert "route_data" in response.text.lower()
    
    def test_assign_route_monitor_success(self, auth_headers, route_data):
        """POST /api/operator/route-monitor assigns route to device."""
        route = route_data["routes"][0]
        
        response = requests.post(
            f"{BASE_URL}/api/operator/route-monitor",
            params={
                "device_id": TEST_DEVICE_ID,
                "route_index": 0,
                "start_lat": 12.9716, "start_lng": 77.5946,
                "end_lat": 12.9352, "end_lng": 77.6245
            },
            json={"route_data": route},
            headers=auth_headers
        )
        assert response.status_code == 200, f"Assign failed: {response.text}"
        
        data = response.json()
        assert "monitor_id" in data, "Missing monitor_id"
        assert "device_id" in data, "Missing device_id"
        assert data["status"] == "active", f"Expected active status, got {data['status']}"
        assert "assigned_at" in data, "Missing assigned_at"


class TestRouteMonitorStatus:
    """Test getting route monitor status."""
    
    def test_get_route_monitor_status(self, auth_headers):
        """GET /api/operator/route-monitor/{device_id} returns tracking status."""
        response = requests.get(
            f"{BASE_URL}/api/operator/route-monitor/{TEST_DEVICE_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Get status failed: {response.text}"
        
        data = response.json()
        # Either we have an active monitor or status=none
        if data.get("status") == "none":
            assert "message" in data
        else:
            # Active monitor - check fields
            assert "monitor_id" in data, "Missing monitor_id"
            assert "status" in data, "Missing status"
            assert data["status"] in ["active", "completed"], f"Unexpected status: {data['status']}"
            
            # Position tracking fields
            if data.get("device_location"):
                assert "lat" in data["device_location"]
                assert "lng" in data["device_location"]
            
            assert "alert_level" in data, "Missing alert_level"
            assert data["alert_level"] in ["safe", "warning", "danger", "info"], f"Unexpected alert_level: {data['alert_level']}"
    
    def test_status_includes_tracking_fields(self, auth_headers):
        """Verify status includes progress tracking fields."""
        response = requests.get(
            f"{BASE_URL}/api/operator/route-monitor/{TEST_DEVICE_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        if data.get("status") != "none":
            # Check for expected tracking fields
            expected_fields = ["route_progress", "distance_from_route_m", "alert_level"]
            for field in expected_fields:
                assert field in data, f"Missing expected field: {field}"
            
            # Check upcoming_dangers field
            assert "upcoming_dangers" in data, "Missing upcoming_dangers"
            assert isinstance(data["upcoming_dangers"], list), "upcoming_dangers should be list"


class TestActiveRouteMonitorsList:
    """Test listing all active route monitors."""
    
    def test_list_active_monitors(self, auth_headers):
        """GET /api/operator/route-monitors returns all active monitors."""
        response = requests.get(
            f"{BASE_URL}/api/operator/route-monitors",
            headers=auth_headers
        )
        assert response.status_code == 200, f"List monitors failed: {response.text}"
        
        data = response.json()
        assert "monitors" in data, "Missing monitors array"
        assert isinstance(data["monitors"], list), "monitors should be a list"
    
    def test_monitors_have_required_fields(self, auth_headers):
        """Verify each monitor has required fields for Command Center."""
        response = requests.get(
            f"{BASE_URL}/api/operator/route-monitors",
            headers=auth_headers
        )
        data = response.json()
        
        for monitor in data.get("monitors", []):
            assert "monitor_id" in monitor, "Missing monitor_id"
            assert "device_id" in monitor, "Missing device_id"
            assert "device_identifier" in monitor, "Missing device_identifier"
            assert "alert_level" in monitor, "Missing alert_level"
            assert "route_progress" in monitor, "Missing route_progress"
            assert "assigned_at" in monitor, "Missing assigned_at"
            
            # Alert level should be valid
            assert monitor["alert_level"] in ["safe", "warning", "danger", "info"], f"Invalid alert_level: {monitor['alert_level']}"


class TestRouteMonitorCancel:
    """Test cancelling route monitors."""
    
    def test_cancel_nonexistent_monitor(self, auth_headers):
        """DELETE /api/operator/route-monitor/{device_id} handles no active monitor."""
        # Use a random UUID that won't have an active monitor
        fake_device_id = "00000000-0000-0000-0000-000000000000"
        response = requests.delete(
            f"{BASE_URL}/api/operator/route-monitor/{fake_device_id}",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Cancel failed: {response.text}"
        
        data = response.json()
        assert data.get("status") == "none", "Should return none status"
        assert "message" in data, "Should have message"


class TestRouteMonitorReplacement:
    """Test that new assignment replaces existing active monitor."""
    
    def test_new_assignment_replaces_existing(self, auth_headers, route_data):
        """Assigning new route replaces any existing active monitor."""
        route = route_data["routes"][0]
        
        # First assignment
        response1 = requests.post(
            f"{BASE_URL}/api/operator/route-monitor",
            params={
                "device_id": TEST_DEVICE_ID,
                "route_index": 0,
                "start_lat": 12.9716, "start_lng": 77.5946,
                "end_lat": 12.9352, "end_lng": 77.6245
            },
            json={"route_data": route},
            headers=auth_headers
        )
        assert response1.status_code == 200
        first_monitor_id = response1.json()["monitor_id"]
        
        # Second assignment (should replace)
        response2 = requests.post(
            f"{BASE_URL}/api/operator/route-monitor",
            params={
                "device_id": TEST_DEVICE_ID,
                "route_index": 1,  # Different route index
                "start_lat": 12.9716, "start_lng": 77.5946,
                "end_lat": 12.9352, "end_lng": 77.6245
            },
            json={"route_data": route},
            headers=auth_headers
        )
        assert response2.status_code == 200
        second_monitor_id = response2.json()["monitor_id"]
        
        # Should have different monitor IDs (new was created)
        assert first_monitor_id != second_monitor_id, "Should have created new monitor"
        
        # List monitors - should only have one active for this device
        response3 = requests.get(
            f"{BASE_URL}/api/operator/route-monitors",
            headers=auth_headers
        )
        monitors = response3.json().get("monitors", [])
        device_monitors = [m for m in monitors if m["device_id"] == TEST_DEVICE_ID]
        assert len(device_monitors) <= 1, f"Should have at most 1 active monitor, got {len(device_monitors)}"


class TestOSRMResilience:
    """Test OSRM retry logic via route-safety endpoint."""
    
    def test_route_safety_with_valid_coords(self, auth_headers):
        """Route safety endpoint returns valid response."""
        response = requests.post(
            f"{BASE_URL}/api/operator/route-safety",
            params={
                "start_lat": 12.9716, "start_lng": 77.5946,
                "end_lat": 12.9352, "end_lng": 77.6245
            },
            headers=auth_headers,
            timeout=30  # Allow time for retries
        )
        assert response.status_code == 200, f"Route safety failed: {response.text}"
        data = response.json()
        assert "routes" in data, "No routes in response"
        assert len(data["routes"]) >= 1, "Should return at least 1 route"
    
    def test_route_safety_handles_invalid_coords(self, auth_headers):
        """Route safety handles invalid coordinates gracefully."""
        response = requests.post(
            f"{BASE_URL}/api/operator/route-safety",
            params={
                "start_lat": 999, "start_lng": 999,  # Invalid coordinates
                "end_lat": 12.9352, "end_lng": 77.6245
            },
            headers=auth_headers,
            timeout=30
        )
        # Should handle gracefully (either error response or empty routes)
        assert response.status_code in [200, 400, 422], f"Unexpected status: {response.status_code}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
