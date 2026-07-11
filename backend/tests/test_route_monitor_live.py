# Route Monitor Live Testing - Corridor Generation, Deviation Detection, Escalation
# Tests all route-monitor endpoints: /start, /session, /location, /stop
# Validates corridor polygon, on-route/off-route detection, escalation levels

import os
import pytest
import requests
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
GUARDIAN_EMAIL = "nischint4parents@gmail.com"
GUARDIAN_PASSWORD = "secret123"

# Demo route coordinates (Mumbai)
DEMO_ROUTE = [
    [72.8300, 19.0760], [72.8340, 19.0770], [72.8380, 19.0780],
    [72.8420, 19.0790], [72.8460, 19.0795], [72.8500, 19.0800],
    [72.8540, 19.0810], [72.8580, 19.0825], [72.8620, 19.0840],
    [72.8660, 19.0855], [72.8700, 19.0870], [72.8740, 19.0885],
    [72.8777, 19.0900],
]


@pytest.fixture(scope="module")
def auth_token():
    """Get guardian auth token"""
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": GUARDIAN_EMAIL,
        "password": GUARDIAN_PASSWORD,
    })
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["access_token"]


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Auth headers for authenticated requests"""
    return {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}


class TestRouteMonitorStart:
    """Tests for POST /api/route-monitor/start"""
    
    def test_start_monitoring_success(self, auth_headers):
        """Start route monitoring with valid route coords"""
        # First stop any existing session
        requests.post(f"{BASE_URL}/api/route-monitor/stop", headers=auth_headers)
        
        resp = requests.post(f"{BASE_URL}/api/route-monitor/start", headers=auth_headers, json={
            "route_coords": DEMO_ROUTE,
            "mode": "balanced",
            "destination": {"lat": 19.09, "lng": 72.8777, "name": "Test Destination"},
            "route_risk_score": 4.5,
        })
        
        assert resp.status_code == 200, f"Start failed: {resp.text}"
        data = resp.json()
        
        # Verify response structure
        assert data.get("status") == "monitoring", "Status should be 'monitoring'"
        assert "user_id" in data, "Should return user_id"
        assert "corridor" in data, "Should return corridor polygon"
        assert "corridor_width_m" in data, "Should return corridor width"
        assert data.get("mode") == "balanced", "Mode should match request"
        
        # Verify corridor is valid GeoJSON polygon
        corridor = data.get("corridor")
        assert corridor.get("type") == "Polygon", "Corridor should be Polygon type"
        assert "coordinates" in corridor, "Corridor should have coordinates"
        assert len(corridor["coordinates"]) > 0, "Corridor should have coordinate ring"
        assert len(corridor["coordinates"][0]) > 4, "Corridor should have multiple vertices"
        
        # Verify corridor width for balanced mode (35m default)
        assert data.get("corridor_width_m") == 35, "Balanced mode should have 35m corridor"
    
    def test_start_with_different_modes(self, auth_headers):
        """Test corridor generation for all route modes"""
        modes_widths = {
            "fastest": 40,
            "balanced": 35,
            "safest": 30,
            "night_guardian": 25,
        }
        
        for mode, expected_width in modes_widths.items():
            # Stop existing session
            requests.post(f"{BASE_URL}/api/route-monitor/stop", headers=auth_headers)
            
            resp = requests.post(f"{BASE_URL}/api/route-monitor/start", headers=auth_headers, json={
                "route_coords": DEMO_ROUTE,
                "mode": mode,
                "destination": {"lat": 19.09, "lng": 72.8777, "name": "Test"},
                "route_risk_score": 5.0,
            })
            
            assert resp.status_code == 200, f"Start with mode={mode} failed: {resp.text}"
            data = resp.json()
            assert data.get("corridor_width_m") == expected_width, f"Mode {mode} should have {expected_width}m corridor"
    
    def test_start_with_invalid_mode(self, auth_headers):
        """Start with invalid mode should fail"""
        requests.post(f"{BASE_URL}/api/route-monitor/stop", headers=auth_headers)
        
        resp = requests.post(f"{BASE_URL}/api/route-monitor/start", headers=auth_headers, json={
            "route_coords": DEMO_ROUTE,
            "mode": "invalid_mode",
            "destination": {},
            "route_risk_score": 5.0,
        })
        
        assert resp.status_code == 400, "Invalid mode should return 400"
    
    def test_start_with_insufficient_coords(self, auth_headers):
        """Start with too few coordinates should fail"""
        requests.post(f"{BASE_URL}/api/route-monitor/stop", headers=auth_headers)
        
        resp = requests.post(f"{BASE_URL}/api/route-monitor/start", headers=auth_headers, json={
            "route_coords": [[72.8, 19.0]],  # Only 1 point
            "mode": "balanced",
            "destination": {},
            "route_risk_score": 5.0,
        })
        
        # Should fail validation (min_length=2)
        assert resp.status_code in [400, 422], "Insufficient coords should fail validation"
    
    def test_start_without_auth(self):
        """Start without authentication should fail"""
        resp = requests.post(f"{BASE_URL}/api/route-monitor/start", json={
            "route_coords": DEMO_ROUTE,
            "mode": "balanced",
            "destination": {},
            "route_risk_score": 5.0,
        })
        
        assert resp.status_code == 401, "No auth should return 401"


class TestRouteMonitorSession:
    """Tests for GET /api/route-monitor/session"""
    
    def test_session_when_active(self, auth_headers):
        """Get session status when monitoring is active"""
        # Start monitoring first
        requests.post(f"{BASE_URL}/api/route-monitor/stop", headers=auth_headers)
        requests.post(f"{BASE_URL}/api/route-monitor/start", headers=auth_headers, json={
            "route_coords": DEMO_ROUTE,
            "mode": "balanced",
            "destination": {"lat": 19.09, "lng": 72.8777, "name": "Test"},
            "route_risk_score": 4.5,
        })
        
        resp = requests.get(f"{BASE_URL}/api/route-monitor/session", headers=auth_headers)
        assert resp.status_code == 200, f"Session check failed: {resp.text}"
        
        data = resp.json()
        assert data.get("status") == "active", "Should return active status"
        assert data.get("mode") == "balanced", "Should return mode"
        assert data.get("corridor_width_m") == 35, "Should return corridor width"
        assert data.get("escalation_level") == 0, "Initial escalation should be 0"
        assert data.get("trail_length") == 0, "Initial trail should be empty"
        assert "started_at" in data, "Should have started_at timestamp"
    
    def test_session_when_inactive(self, auth_headers):
        """Get session status when no monitoring is active"""
        # Stop any existing session
        requests.post(f"{BASE_URL}/api/route-monitor/stop", headers=auth_headers)
        
        resp = requests.get(f"{BASE_URL}/api/route-monitor/session", headers=auth_headers)
        assert resp.status_code == 200, f"Session check failed: {resp.text}"
        
        data = resp.json()
        assert data.get("status") == "none", "Should return 'none' when inactive"


class TestRouteMonitorLocation:
    """Tests for POST /api/route-monitor/location - Core deviation detection"""
    
    def test_on_route_location(self, auth_headers):
        """Location on route should return inside_corridor=true"""
        # Start fresh session
        requests.post(f"{BASE_URL}/api/route-monitor/stop", headers=auth_headers)
        requests.post(f"{BASE_URL}/api/route-monitor/start", headers=auth_headers, json={
            "route_coords": DEMO_ROUTE,
            "mode": "balanced",
            "destination": {"lat": 19.09, "lng": 72.8777, "name": "Test"},
            "route_risk_score": 4.5,
        })
        
        # Send location exactly on route
        on_route_coord = DEMO_ROUTE[5]  # Middle of route
        resp = requests.post(f"{BASE_URL}/api/route-monitor/location", headers=auth_headers, json={
            "lat": on_route_coord[1],
            "lng": on_route_coord[0],
        })
        
        assert resp.status_code == 200, f"Location update failed: {resp.text}"
        data = resp.json()
        
        assert data.get("inside_corridor") == True, "On-route location should be inside corridor"
        assert data.get("distance_from_corridor_m") == 0, "On-route should have 0 distance"
        assert data.get("status") == "on_route", "Status should be 'on_route'"
        assert data.get("escalation_level") == 0, "On-route should have escalation 0"
        assert data.get("trail_length") == 1, "Trail should have 1 point"
    
    def test_off_route_location(self, auth_headers):
        """Location off route should return inside_corridor=false with distance"""
        # Start fresh session
        requests.post(f"{BASE_URL}/api/route-monitor/stop", headers=auth_headers)
        requests.post(f"{BASE_URL}/api/route-monitor/start", headers=auth_headers, json={
            "route_coords": DEMO_ROUTE,
            "mode": "balanced",
            "destination": {"lat": 19.09, "lng": 72.8777, "name": "Test"},
            "route_risk_score": 4.5,
        })
        
        # Send location ~300m off route (0.003 degrees ≈ 330m)
        off_route_coord = DEMO_ROUTE[5]
        resp = requests.post(f"{BASE_URL}/api/route-monitor/location", headers=auth_headers, json={
            "lat": off_route_coord[1] + 0.003,
            "lng": off_route_coord[0] + 0.003,
        })
        
        assert resp.status_code == 200, f"Location update failed: {resp.text}"
        data = resp.json()
        
        assert data.get("inside_corridor") == False, "Off-route location should be outside corridor"
        assert data.get("distance_from_corridor_m", 0) > 100, "Should have significant distance from corridor"
        assert data.get("distance_from_route_m", 0) > 100, "Should have significant distance from route"
        assert data.get("status") == "off_route", "Status should be 'off_route'"
    
    def test_location_without_session(self, auth_headers):
        """Location update without active session should fail"""
        # Stop any session
        requests.post(f"{BASE_URL}/api/route-monitor/stop", headers=auth_headers)
        
        resp = requests.post(f"{BASE_URL}/api/route-monitor/location", headers=auth_headers, json={
            "lat": 19.08,
            "lng": 72.85,
        })
        
        assert resp.status_code == 404, "Location without session should return 404"


class TestRouteMonitorEscalation:
    """Tests for escalation logic - L1/L2/L3"""
    
    def test_escalation_level_1(self, auth_headers):
        """Escalation L1: >30m off, >10s duration, 2+ consecutive off-route"""
        # Start fresh session
        requests.post(f"{BASE_URL}/api/route-monitor/stop", headers=auth_headers)
        requests.post(f"{BASE_URL}/api/route-monitor/start", headers=auth_headers, json={
            "route_coords": DEMO_ROUTE,
            "mode": "balanced",
            "destination": {"lat": 19.09, "lng": 72.8777, "name": "Test"},
            "route_risk_score": 4.5,
        })
        
        # Send off-route location (50m off > L1 threshold 30m)
        off_route_lat = DEMO_ROUTE[5][1] + 0.0005  # ~55m off
        off_route_lng = DEMO_ROUTE[5][0]
        
        # First off-route update (count=1, no escalation yet)
        resp1 = requests.post(f"{BASE_URL}/api/route-monitor/location", headers=auth_headers, json={
            "lat": off_route_lat, "lng": off_route_lng,
        })
        data1 = resp1.json()
        assert data1.get("escalation_level") == 0, "First off-route should not escalate yet"
        
        # Wait for L1 duration threshold (10s)
        time.sleep(11)
        
        # Second off-route update (count=2, should trigger L1)
        resp2 = requests.post(f"{BASE_URL}/api/route-monitor/location", headers=auth_headers, json={
            "lat": off_route_lat, "lng": off_route_lng,
        })
        data2 = resp2.json()
        
        # Check if escalation happened (may be L1 or higher depending on risk)
        escalation = data2.get("escalation_level", 0)
        assert escalation >= 1, f"Should escalate to at least L1 after 2 off-route checks and >10s, got L{escalation}"
        assert "off_route_duration_s" in data2, "Should include off-route duration"
    
    def test_back_on_track_resets_escalation(self, auth_headers):
        """Returning to corridor should reset escalation to 0"""
        # Start fresh and create deviation state
        requests.post(f"{BASE_URL}/api/route-monitor/stop", headers=auth_headers)
        requests.post(f"{BASE_URL}/api/route-monitor/start", headers=auth_headers, json={
            "route_coords": DEMO_ROUTE,
            "mode": "balanced",
            "destination": {"lat": 19.09, "lng": 72.8777, "name": "Test"},
            "route_risk_score": 4.5,
        })
        
        # Send off-route locations
        off_lat = DEMO_ROUTE[5][1] + 0.0005
        off_lng = DEMO_ROUTE[5][0]
        requests.post(f"{BASE_URL}/api/route-monitor/location", headers=auth_headers, json={"lat": off_lat, "lng": off_lng})
        time.sleep(2)
        requests.post(f"{BASE_URL}/api/route-monitor/location", headers=auth_headers, json={"lat": off_lat, "lng": off_lng})
        
        # Now return to route
        on_route_coord = DEMO_ROUTE[6]
        resp = requests.post(f"{BASE_URL}/api/route-monitor/location", headers=auth_headers, json={
            "lat": on_route_coord[1],
            "lng": on_route_coord[0],
        })
        
        data = resp.json()
        assert data.get("inside_corridor") == True, "Should be inside corridor"
        assert data.get("escalation_level") == 0, "Escalation should reset to 0 on return"
        assert data.get("status") == "on_route", "Status should be 'on_route'"


class TestRouteMonitorStop:
    """Tests for POST /api/route-monitor/stop"""
    
    def test_stop_returns_summary(self, auth_headers):
        """Stop monitoring should return journey summary"""
        # Start and add some trail points
        requests.post(f"{BASE_URL}/api/route-monitor/stop", headers=auth_headers)
        requests.post(f"{BASE_URL}/api/route-monitor/start", headers=auth_headers, json={
            "route_coords": DEMO_ROUTE,
            "mode": "balanced",
            "destination": {"lat": 19.09, "lng": 72.8777, "name": "Test"},
            "route_risk_score": 4.5,
        })
        
        # Add some location updates
        for i in range(3):
            coord = DEMO_ROUTE[i]
            requests.post(f"{BASE_URL}/api/route-monitor/location", headers=auth_headers, json={
                "lat": coord[1], "lng": coord[0],
            })
        
        # Stop monitoring
        resp = requests.post(f"{BASE_URL}/api/route-monitor/stop", headers=auth_headers)
        assert resp.status_code == 200, f"Stop failed: {resp.text}"
        
        data = resp.json()
        assert data.get("status") == "stopped", "Status should be 'stopped'"
        assert "total_trail_points" in data, "Should include trail point count"
        assert data.get("total_trail_points") == 3, "Should have 3 trail points"
        assert "max_escalation" in data, "Should include max escalation"
        assert "total_deviations" in data, "Should include total deviations"
        assert "max_distance_m" in data, "Should include max distance"
        assert "duration_s" in data, "Should include duration"
    
    def test_stop_without_session(self, auth_headers):
        """Stop without active session should return error"""
        # Ensure no session
        requests.post(f"{BASE_URL}/api/route-monitor/stop", headers=auth_headers)
        
        # Try to stop again
        resp = requests.post(f"{BASE_URL}/api/route-monitor/stop", headers=auth_headers)
        assert resp.status_code == 404, "Stop without session should return 404"


class TestRouteMonitorTrail:
    """Tests for trail tracking"""
    
    def test_trail_accumulates_points(self, auth_headers):
        """Trail should accumulate location points"""
        requests.post(f"{BASE_URL}/api/route-monitor/stop", headers=auth_headers)
        requests.post(f"{BASE_URL}/api/route-monitor/start", headers=auth_headers, json={
            "route_coords": DEMO_ROUTE,
            "mode": "balanced",
            "destination": {"lat": 19.09, "lng": 72.8777, "name": "Test"},
            "route_risk_score": 4.5,
        })
        
        # Add 5 location updates
        for i in range(5):
            coord = DEMO_ROUTE[i]
            resp = requests.post(f"{BASE_URL}/api/route-monitor/location", headers=auth_headers, json={
                "lat": coord[1], "lng": coord[0],
            })
            data = resp.json()
            assert data.get("trail_length") == i + 1, f"Trail should have {i+1} points"
        
        # Check session
        session_resp = requests.get(f"{BASE_URL}/api/route-monitor/session", headers=auth_headers)
        session = session_resp.json()
        assert session.get("trail_length") == 5, "Session should show 5 trail points"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
