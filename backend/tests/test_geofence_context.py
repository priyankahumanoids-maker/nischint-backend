"""
Test Geofence Context Intelligence Layer
Tests: GET /api/location/track/{token}/context endpoint
- Zone visualization data
- Timeline events with severity levels
- AI context interpretation
- WebSocket event whitelist for zone events
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test token with seeded trail data + zones
TEST_TOKEN = "Pc3JzZzedIRGLUSTJYR_S388AeVVQMMBWg6mkOqG50k"
INVALID_TOKEN = "invalid_token_for_testing_404"


class TestContextEndpoint:
    """Test GET /api/location/track/{token}/context"""

    def test_context_endpoint_returns_200_for_valid_token(self):
        """Context endpoint returns 200 for valid share token"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN}/context")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASSED: Context endpoint returns 200 for valid token")

    def test_context_endpoint_returns_404_for_invalid_token(self):
        """Context endpoint returns 404 for invalid token"""
        response = requests.get(f"{BASE_URL}/api/location/track/{INVALID_TOKEN}/context")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        data = response.json()
        assert "detail" in data or "error" in data
        print("PASSED: Context endpoint returns 404 for invalid token")

    def test_context_response_has_required_fields(self):
        """Context response has zones, current_zone, timeline, ai_context"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN}/context")
        assert response.status_code == 200
        data = response.json()
        
        required_fields = ["zones", "current_zone", "timeline", "ai_context"]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        
        print("PASSED: Context response has all required fields")


class TestZoneData:
    """Test zone array fields and structure"""

    def test_zones_is_array(self):
        """Zones field is an array"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN}/context")
        data = response.json()
        assert isinstance(data["zones"], list), "zones should be a list"
        print("PASSED: zones is an array")

    def test_zone_has_required_fields(self):
        """Each zone has id, name, lat, lng, radius_metres, type, child_currently_inside"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN}/context")
        data = response.json()
        
        if not data["zones"]:
            pytest.skip("No zones in response")
        
        zone = data["zones"][0]
        required_fields = ["id", "name", "lat", "lng", "radius_metres", "type", 
                          "child_currently_inside", "distance_m"]
        
        for field in required_fields:
            assert field in zone, f"Zone missing required field: {field}"
        
        print("PASSED: Zone has all required fields")

    def test_zone_type_is_valid(self):
        """Zone type is one of: home, school, frequent, danger"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN}/context")
        data = response.json()
        
        valid_types = ["home", "school", "frequent", "danger"]
        for zone in data["zones"]:
            assert zone["type"] in valid_types, f"Invalid zone type: {zone['type']}"
        
        print("PASSED: All zone types are valid")

    def test_zone_has_entry_exit_times(self):
        """Zone has child_entered_at_ist and child_exited_at_ist fields"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN}/context")
        data = response.json()
        
        if not data["zones"]:
            pytest.skip("No zones in response")
        
        zone = data["zones"][0]
        assert "child_entered_at_ist" in zone, "Missing child_entered_at_ist field"
        assert "child_exited_at_ist" in zone, "Missing child_exited_at_ist field"
        
        print("PASSED: Zone has entry/exit time fields")

    def test_zone_coordinates_are_floats(self):
        """Zone lat and lng are floats"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN}/context")
        data = response.json()
        
        for zone in data["zones"]:
            assert isinstance(zone["lat"], float), f"lat should be float, got {type(zone['lat'])}"
            assert isinstance(zone["lng"], float), f"lng should be float, got {type(zone['lng'])}"
        
        print("PASSED: Zone coordinates are floats")

    def test_zone_distance_is_number(self):
        """Zone distance_m is a number"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN}/context")
        data = response.json()
        
        for zone in data["zones"]:
            assert isinstance(zone["distance_m"], (int, float)), f"distance_m should be number"
        
        print("PASSED: Zone distance_m is a number")


class TestCurrentZone:
    """Test current_zone field"""

    def test_current_zone_structure(self):
        """Current zone has name and type when child is inside a zone"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN}/context")
        data = response.json()
        
        if data["current_zone"] is None:
            print("SKIPPED: Child not currently inside any zone")
            return
        
        assert "name" in data["current_zone"], "current_zone missing name"
        assert "type" in data["current_zone"], "current_zone missing type"
        
        print(f"PASSED: current_zone has name='{data['current_zone']['name']}', type='{data['current_zone']['type']}'")


class TestTimeline:
    """Test timeline array and event structure"""

    def test_timeline_is_array(self):
        """Timeline is an array"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN}/context")
        data = response.json()
        assert isinstance(data["timeline"], list), "timeline should be a list"
        print("PASSED: timeline is an array")

    def test_timeline_event_has_required_fields(self):
        """Each timeline event has time_ist, event, label, severity"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN}/context")
        data = response.json()
        
        if not data["timeline"]:
            pytest.skip("No timeline events")
        
        event = data["timeline"][0]
        required_fields = ["time_ist", "event", "label", "severity"]
        
        for field in required_fields:
            assert field in event, f"Timeline event missing required field: {field}"
        
        print("PASSED: Timeline event has all required fields")

    def test_timeline_severity_is_valid(self):
        """Timeline event severity is one of: info, safe, notice, warning, critical"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN}/context")
        data = response.json()
        
        valid_severities = ["info", "safe", "notice", "warning", "critical"]
        for event in data["timeline"]:
            assert event["severity"] in valid_severities, f"Invalid severity: {event['severity']}"
        
        print("PASSED: All timeline event severities are valid")

    def test_timeline_has_zone_events(self):
        """Timeline contains zone entry/exit events"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN}/context")
        data = response.json()
        
        zone_event_types = ["entered_school", "entered_home", "entered_zone", 
                          "exited_school", "exited_home", "exited_zone",
                          "entered_danger_zone"]
        
        has_zone_event = any(
            event["event"] in zone_event_types 
            for event in data["timeline"]
        )
        
        assert has_zone_event, "Timeline should contain zone entry/exit events"
        print("PASSED: Timeline contains zone events")


class TestAIContext:
    """Test AI context interpretation"""

    def test_ai_context_is_non_empty_string(self):
        """AI context is a non-empty string"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN}/context")
        data = response.json()
        
        assert isinstance(data["ai_context"], str), "ai_context should be string"
        assert len(data["ai_context"]) > 0, "ai_context should not be empty"
        
        print(f"PASSED: ai_context = '{data['ai_context']}'")

    def test_ai_context_is_geofence_aware(self):
        """AI context contains geofence-related interpretation"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN}/context")
        data = response.json()
        
        ai_text = data["ai_context"].lower()
        
        # Should mention location context like zone names, safety, journey, etc.
        geofence_keywords = [
            "zone", "home", "school", "location", "arrived", "left", 
            "safely", "concern", "expected", "moving", "transit",
            "stopped", "deviation", "route", "journey"
        ]
        
        has_geofence_context = any(kw in ai_text for kw in geofence_keywords)
        assert has_geofence_context, f"AI context should be geofence-aware: '{data['ai_context']}'"
        
        print("PASSED: AI context is geofence-aware")


class TestWebSocketZoneEvents:
    """Test WebSocket event whitelist for zone events"""

    def test_ws_command_center_status_accessible(self):
        """WebSocket command center status endpoint is accessible"""
        response = requests.get(f"{BASE_URL}/api/ws/command-center/status")
        assert response.status_code == 200
        data = response.json()
        assert "active_connections" in data
        print("PASSED: WebSocket command center status is accessible")


class TestZoneDetectionLogic:
    """Test zone type detection from database values"""

    def test_school_zone_detected(self):
        """School zone type is correctly detected"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN}/context")
        data = response.json()
        
        school_zones = [z for z in data["zones"] if z["type"] == "school"]
        assert len(school_zones) > 0, "Should have at least one school zone"
        
        # Check it's the DPS Bangalore zone
        school_zone = school_zones[0]
        assert "School" in school_zone["name"] or "school" in school_zone["name"].lower()
        
        print(f"PASSED: School zone detected: {school_zone['name']}")

    def test_home_zone_detected(self):
        """Home zone type is correctly detected"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN}/context")
        data = response.json()
        
        home_zones = [z for z in data["zones"] if z["type"] == "home"]
        assert len(home_zones) > 0, "Should have at least one home zone"
        
        print(f"PASSED: Home zone detected: {home_zones[0]['name']}")

    def test_max_3_zones_returned(self):
        """Context returns maximum 3 zones"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN}/context")
        data = response.json()
        
        assert len(data["zones"]) <= 3, f"Should return max 3 zones, got {len(data['zones'])}"
        print(f"PASSED: Returns {len(data['zones'])} zones (max 3)")


class TestIntegrationWithTrail:
    """Test context integration with trail data"""

    def test_context_and_trail_consistency(self):
        """Context zones are consistent with trail location"""
        ctx_response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN}/context")
        trail_response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN}/trail")
        
        ctx_data = ctx_response.json()
        trail_data = trail_response.json()
        
        # If we have trail data, context should have timeline events
        if trail_data.get("has_data") and len(trail_data.get("trail", [])) > 0:
            assert len(ctx_data["timeline"]) > 0, "Context should have timeline events when trail exists"
        
        print("PASSED: Context and trail data are consistent")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
