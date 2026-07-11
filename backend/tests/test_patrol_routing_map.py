# Tests for Phase 30A: Patrol Route Map Visualization
# Focus on route_geometry field and map-related API response structure

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

@pytest.fixture(scope="module")
def operator_token():
    """Get operator authentication token."""
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": "operator@nischint.com", "password": "operator123"}
    )
    if response.status_code == 200:
        return response.json().get("access_token")
    pytest.skip("Operator authentication failed")

@pytest.fixture
def auth_headers(operator_token):
    """Headers with operator token."""
    return {"Authorization": f"Bearer {operator_token}"}


class TestPatrolRouteGeometry:
    """Tests for route_geometry field in patrol/generate response (Phase 30A)."""

    def test_route_geometry_exists_in_response(self, auth_headers):
        """Verify route_geometry field is present in generate response."""
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "morning", "max_zones": 5},
            headers=auth_headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        # Verify route_geometry exists
        assert "route_geometry" in data, "route_geometry field missing from response"
        
    def test_route_geometry_structure(self, auth_headers):
        """Verify route_geometry contains waypoints, segments, polyline, and total_waypoints."""
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "morning", "max_zones": 5},
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        route_geometry = data.get("route_geometry", {})
        
        # Check all required fields
        assert "waypoints" in route_geometry, "waypoints field missing"
        assert "segments" in route_geometry, "segments field missing"
        assert "polyline" in route_geometry, "polyline field missing"
        assert "total_waypoints" in route_geometry, "total_waypoints field missing"
        
    def test_waypoints_structure_and_count(self, auth_headers):
        """Verify waypoints array has start + max_zones entries with correct structure."""
        max_zones = 5
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "morning", "max_zones": max_zones},
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        route_geometry = data.get("route_geometry", {})
        waypoints = route_geometry.get("waypoints", [])
        
        # Should have start point + max_zones (or less if fewer zones available)
        route_count = len(data.get("route", []))
        expected_waypoints = route_count + 1  # +1 for start point
        
        assert len(waypoints) == expected_waypoints, f"Expected {expected_waypoints} waypoints, got {len(waypoints)}"
        assert route_geometry["total_waypoints"] == expected_waypoints
        
        # First waypoint should be start
        if waypoints:
            start = waypoints[0]
            assert start.get("type") == "start", "First waypoint should be type='start'"
            assert "lat" in start, "Start waypoint missing lat"
            assert "lng" in start, "Start waypoint missing lng"
            assert start.get("label") == "Start", "Start waypoint should have label='Start'"
        
        # Subsequent waypoints should be stops
        for i, wp in enumerate(waypoints[1:], start=1):
            assert wp.get("type") == "stop", f"Waypoint {i} should be type='stop'"
            assert "lat" in wp, f"Waypoint {i} missing lat"
            assert "lng" in wp, f"Waypoint {i} missing lng"
            assert "zone_id" in wp, f"Waypoint {i} missing zone_id"
            assert "priority" in wp, f"Waypoint {i} missing priority"
            assert wp.get("priority") in ["critical", "high", "medium", "low"], f"Invalid priority at waypoint {i}"
            
    def test_polyline_is_array_of_lat_lng_pairs(self, auth_headers):
        """Verify polyline is an array of [lat, lng] pairs."""
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "morning", "max_zones": 5},
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        route_geometry = data.get("route_geometry", {})
        polyline = route_geometry.get("polyline", [])
        
        assert isinstance(polyline, list), "polyline should be an array"
        
        # Each point should be [lat, lng]
        for i, point in enumerate(polyline):
            assert isinstance(point, list), f"Polyline point {i} should be a list"
            assert len(point) == 2, f"Polyline point {i} should have 2 elements [lat, lng]"
            assert isinstance(point[0], (int, float)), f"Polyline point {i} lat should be numeric"
            assert isinstance(point[1], (int, float)), f"Polyline point {i} lng should be numeric"
            
    def test_segments_structure(self, auth_headers):
        """Verify segments array has correct structure for route connections."""
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "morning", "max_zones": 5},
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        route_geometry = data.get("route_geometry", {})
        segments = route_geometry.get("segments", [])
        waypoints = route_geometry.get("waypoints", [])
        
        # Should have n-1 segments for n waypoints
        if len(waypoints) > 1:
            expected_segments = len(waypoints) - 1
            assert len(segments) == expected_segments, f"Expected {expected_segments} segments, got {len(segments)}"
            
            # Each segment should have from, to, segment_index
            for i, seg in enumerate(segments):
                assert "from" in seg, f"Segment {i} missing 'from'"
                assert "to" in seg, f"Segment {i} missing 'to'"
                assert "segment_index" in seg, f"Segment {i} missing 'segment_index'"
                assert seg["segment_index"] == i, f"Segment {i} has wrong index"
                
                # from and to should be [lat, lng] arrays
                assert isinstance(seg["from"], list), f"Segment {i} 'from' should be array"
                assert isinstance(seg["to"], list), f"Segment {i} 'to' should be array"
                assert len(seg["from"]) == 2, f"Segment {i} 'from' should have 2 elements"
                assert len(seg["to"]) == 2, f"Segment {i} 'to' should have 2 elements"


class TestPatrolRouteWithNightShift:
    """Test route_geometry with night shift and different max_zones."""
    
    def test_night_shift_route_geometry(self, auth_headers):
        """Verify route_geometry with night shift and max_zones=10."""
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "night", "max_zones": 10},
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        # Verify shift is night
        assert data.get("shift") == "night", "Shift should be night"
        assert "Night" in data.get("shift_label", ""), "Shift label should mention Night"
        
        # Verify route_geometry exists
        assert "route_geometry" in data, "route_geometry should exist"
        
        route_geometry = data.get("route_geometry", {})
        waypoints = route_geometry.get("waypoints", [])
        route = data.get("route", [])
        
        # Waypoints should be route + 1 (for start)
        assert len(waypoints) == len(route) + 1, "Waypoints count should be route + 1"
        
        # Verify total_waypoints matches
        assert route_geometry.get("total_waypoints") == len(waypoints)


class TestPatrolRouteZoneDetails:
    """Test zone details for map popup content."""
    
    def test_zone_has_all_popup_fields(self, auth_headers):
        """Verify each zone has fields needed for map popup display."""
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "morning", "max_zones": 5},
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        route = data.get("route", [])
        assert len(route) > 0, "Route should have at least one zone"
        
        for i, zone in enumerate(route):
            # Required fields for popup
            assert "zone_name" in zone, f"Zone {i} missing zone_name"
            assert "composite_score" in zone, f"Zone {i} missing composite_score"
            assert "patrol_priority" in zone, f"Zone {i} missing patrol_priority"
            assert "stop_number" in zone, f"Zone {i} missing stop_number"
            assert "incident_count" in zone, f"Zone {i} missing incident_count"
            
            # Score breakdown for detailed popup
            assert "score_breakdown" in zone, f"Zone {i} missing score_breakdown"
            bd = zone.get("score_breakdown", {})
            
            # Check breakdown has forecast, activity, trend_status
            assert "forecast" in bd, f"Zone {i} score_breakdown missing forecast"
            assert "activity" in bd, f"Zone {i} score_breakdown missing activity"
            assert "trend_status" in bd, f"Zone {i} score_breakdown missing trend_status"
            
            # Verify priority is valid
            assert zone["patrol_priority"] in ["critical", "high", "medium", "low"], f"Zone {i} has invalid priority"
            
            # Verify coordinates for map marker
            assert "lat" in zone, f"Zone {i} missing lat"
            assert "lng" in zone, f"Zone {i} missing lng"


class TestPatrolRouteSummary:
    """Test summary fields for map overlay."""
    
    def test_summary_has_map_overlay_fields(self, auth_headers):
        """Verify summary has distance, time, and stops count for map overlay."""
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "morning", "max_zones": 5},
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        summary = data.get("summary", {})
        
        # Required for map overlay
        assert "total_distance_km" in summary, "Summary missing total_distance_km"
        assert "total_estimated_minutes" in summary, "Summary missing total_estimated_minutes"
        assert "total_zones" in summary, "Summary missing total_zones"
        
        # Should be numeric
        assert isinstance(summary["total_distance_km"], (int, float))
        assert isinstance(summary["total_estimated_minutes"], (int, float))
        assert isinstance(summary["total_zones"], int)


class TestPatrolStartPosition:
    """Test start_position for map start marker."""
    
    def test_start_position_in_response(self, auth_headers):
        """Verify start_position is returned for placing start marker on map."""
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "morning", "max_zones": 5},
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "start_position" in data, "start_position field missing"
        start = data.get("start_position", {})
        
        assert "lat" in start, "start_position missing lat"
        assert "lng" in start, "start_position missing lng"
        assert isinstance(start["lat"], (int, float)), "start_position.lat should be numeric"
        assert isinstance(start["lng"], (int, float)), "start_position.lng should be numeric"


class TestPatrolPriorityBreakdown:
    """Test priority_breakdown for map legend correlation."""
    
    def test_priority_breakdown_in_response(self, auth_headers):
        """Verify priority_breakdown counts zones by priority level."""
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "morning", "max_zones": 10},
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "priority_breakdown" in data, "priority_breakdown field missing"
        breakdown = data.get("priority_breakdown", {})
        
        # Count should match route priorities
        route = data.get("route", [])
        
        # Verify counts are consistent
        total_from_breakdown = sum(breakdown.values())
        assert total_from_breakdown == len(route), f"Priority breakdown sum ({total_from_breakdown}) should equal route length ({len(route)})"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
