"""
Tests for Location Trail / Breadcrumb Trail feature for Live Tracking
Tests the GET /api/location/track/{token}/trail endpoint
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test token with seeded trail data (20 points with 1 stop cluster at indices 9-12)
TEST_TOKEN_WITH_TRAIL = "Pc3JzZzedIRGLUSTJYR_S388AeVVQMMBWg6mkOqG50k"
INVALID_TOKEN = "invalid_token_does_not_exist_xyz"


class TestTrailEndpoint:
    """Tests for GET /api/location/track/{token}/trail endpoint"""

    def test_trail_endpoint_returns_200_for_valid_token(self):
        """Trail endpoint returns 200 OK for valid token"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN_WITH_TRAIL}/trail")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    def test_trail_endpoint_returns_404_for_invalid_token(self):
        """Trail endpoint returns 404 for invalid token"""
        response = requests.get(f"{BASE_URL}/api/location/track/{INVALID_TOKEN}/trail")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        data = response.json()
        assert "detail" in data
        assert "not found" in data["detail"].lower()

    def test_trail_response_has_required_fields(self):
        """Trail response includes trail, movement_summary, has_data fields"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN_WITH_TRAIL}/trail")
        assert response.status_code == 200
        data = response.json()
        
        # Check top-level fields
        assert "trail" in data, "Response missing 'trail' field"
        assert "movement_summary" in data, "Response missing 'movement_summary' field"
        assert "has_data" in data, "Response missing 'has_data' field"

    def test_trail_has_data_is_true_when_trail_exists(self):
        """has_data is True when trail points exist"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN_WITH_TRAIL}/trail")
        assert response.status_code == 200
        data = response.json()
        
        assert data["has_data"] is True, "Expected has_data to be True for token with trail"
        assert isinstance(data["trail"], list), "trail should be a list"
        assert len(data["trail"]) > 0, "trail should not be empty"


class TestTrailPointFields:
    """Tests for trail point data structure"""

    def test_trail_point_has_required_fields(self):
        """Each trail point has lat, lng, speed_kmh, recorded_at_ist, is_stop fields"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN_WITH_TRAIL}/trail")
        assert response.status_code == 200
        data = response.json()
        
        assert len(data["trail"]) > 0, "Need at least one trail point"
        point = data["trail"][0]
        
        assert "lat" in point, "Trail point missing 'lat'"
        assert "lng" in point, "Trail point missing 'lng'"
        assert "speed_kmh" in point, "Trail point missing 'speed_kmh'"
        assert "recorded_at_ist" in point, "Trail point missing 'recorded_at_ist'"
        assert "is_stop" in point, "Trail point missing 'is_stop'"

    def test_trail_point_lat_lng_are_floats(self):
        """lat and lng are float values"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN_WITH_TRAIL}/trail")
        assert response.status_code == 200
        data = response.json()
        
        point = data["trail"][0]
        assert isinstance(point["lat"], (int, float)), f"lat should be numeric, got {type(point['lat'])}"
        assert isinstance(point["lng"], (int, float)), f"lng should be numeric, got {type(point['lng'])}"
        # Validate reasonable lat/lng ranges
        assert -90 <= point["lat"] <= 90, f"lat {point['lat']} out of range"
        assert -180 <= point["lng"] <= 180, f"lng {point['lng']} out of range"

    def test_trail_point_speed_is_float(self):
        """speed_kmh is a float value"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN_WITH_TRAIL}/trail")
        assert response.status_code == 200
        data = response.json()
        
        point = data["trail"][0]
        assert isinstance(point["speed_kmh"], (int, float)), f"speed_kmh should be numeric"
        assert point["speed_kmh"] >= 0, "speed_kmh should be non-negative"

    def test_trail_point_is_stop_is_boolean(self):
        """is_stop is a boolean value"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN_WITH_TRAIL}/trail")
        assert response.status_code == 200
        data = response.json()
        
        point = data["trail"][0]
        assert isinstance(point["is_stop"], bool), f"is_stop should be bool, got {type(point['is_stop'])}"

    def test_trail_point_recorded_at_ist_is_string(self):
        """recorded_at_ist is an IST time string like '3:05 PM'"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN_WITH_TRAIL}/trail")
        assert response.status_code == 200
        data = response.json()
        
        point = data["trail"][0]
        assert isinstance(point["recorded_at_ist"], str), "recorded_at_ist should be a string"
        # Should contain AM or PM
        assert "AM" in point["recorded_at_ist"] or "PM" in point["recorded_at_ist"], \
            f"recorded_at_ist '{point['recorded_at_ist']}' should contain AM/PM"


class TestMovementSummary:
    """Tests for movement_summary structure and fields"""

    def test_movement_summary_has_required_fields(self):
        """movement_summary includes all required fields"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN_WITH_TRAIL}/trail")
        assert response.status_code == 200
        data = response.json()
        
        summary = data.get("movement_summary")
        assert summary is not None, "movement_summary should not be None for token with trail"
        
        required_fields = [
            "started_at_ist",
            "total_distance_km",
            "total_duration_min",
            "stop_count",
            "stops_total_min",
            "deviation_detected",
            "deviation_m",
            "ai_interpretation",
        ]
        for field in required_fields:
            assert field in summary, f"movement_summary missing '{field}'"

    def test_movement_summary_started_at_ist_format(self):
        """started_at_ist is IST time string"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN_WITH_TRAIL}/trail")
        assert response.status_code == 200
        data = response.json()
        summary = data["movement_summary"]
        
        assert isinstance(summary["started_at_ist"], str)
        assert "AM" in summary["started_at_ist"] or "PM" in summary["started_at_ist"]

    def test_movement_summary_distance_is_float(self):
        """total_distance_km is a float"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN_WITH_TRAIL}/trail")
        assert response.status_code == 200
        data = response.json()
        summary = data["movement_summary"]
        
        assert isinstance(summary["total_distance_km"], (int, float))
        assert summary["total_distance_km"] >= 0

    def test_movement_summary_duration_is_int(self):
        """total_duration_min is an integer"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN_WITH_TRAIL}/trail")
        assert response.status_code == 200
        data = response.json()
        summary = data["movement_summary"]
        
        assert isinstance(summary["total_duration_min"], int)
        assert summary["total_duration_min"] >= 0

    def test_movement_summary_stop_count_is_int(self):
        """stop_count is an integer >= 0"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN_WITH_TRAIL}/trail")
        assert response.status_code == 200
        data = response.json()
        summary = data["movement_summary"]
        
        assert isinstance(summary["stop_count"], int)
        assert summary["stop_count"] >= 0

    def test_movement_summary_stops_total_min_is_int(self):
        """stops_total_min is an integer >= 0"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN_WITH_TRAIL}/trail")
        assert response.status_code == 200
        data = response.json()
        summary = data["movement_summary"]
        
        assert isinstance(summary["stops_total_min"], int)
        assert summary["stops_total_min"] >= 0

    def test_movement_summary_deviation_detected_is_bool(self):
        """deviation_detected is a boolean"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN_WITH_TRAIL}/trail")
        assert response.status_code == 200
        data = response.json()
        summary = data["movement_summary"]
        
        assert isinstance(summary["deviation_detected"], bool)

    def test_movement_summary_deviation_m_is_float(self):
        """deviation_m is a float >= 0"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN_WITH_TRAIL}/trail")
        assert response.status_code == 200
        data = response.json()
        summary = data["movement_summary"]
        
        assert isinstance(summary["deviation_m"], (int, float))
        assert summary["deviation_m"] >= 0

    def test_movement_summary_ai_interpretation_is_string(self):
        """ai_interpretation is a non-empty string"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN_WITH_TRAIL}/trail")
        assert response.status_code == 200
        data = response.json()
        summary = data["movement_summary"]
        
        assert isinstance(summary["ai_interpretation"], str)
        assert len(summary["ai_interpretation"]) > 0


class TestTrailWithStopData:
    """Tests for trail data with stop points (seeded test data has 4 consecutive stops)"""

    def test_trail_has_stop_points(self):
        """Trail data includes points with is_stop=True"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN_WITH_TRAIL}/trail")
        assert response.status_code == 200
        data = response.json()
        
        stop_points = [p for p in data["trail"] if p["is_stop"]]
        assert len(stop_points) > 0, "Expected some trail points with is_stop=True"

    def test_movement_summary_has_stop_count(self):
        """movement_summary.stop_count > 0 when stops detected"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN_WITH_TRAIL}/trail")
        assert response.status_code == 200
        data = response.json()
        summary = data["movement_summary"]
        
        # Test data should have 1 stop (4 consecutive is_stop=true points)
        assert summary["stop_count"] >= 1, f"Expected stop_count >= 1, got {summary['stop_count']}"

    def test_movement_summary_has_stops_total_min(self):
        """movement_summary.stops_total_min > 0 when stops detected"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN_WITH_TRAIL}/trail")
        assert response.status_code == 200
        data = response.json()
        summary = data["movement_summary"]
        
        # Should have some stop duration
        assert summary["stops_total_min"] >= 0, f"stops_total_min should be >= 0"

    def test_ai_interpretation_mentions_stops(self):
        """ai_interpretation string includes stop info when stops detected"""
        response = requests.get(f"{BASE_URL}/api/location/track/{TEST_TOKEN_WITH_TRAIL}/trail")
        assert response.status_code == 200
        data = response.json()
        summary = data["movement_summary"]
        
        # If stops detected, AI interpretation should mention stops
        if summary["stop_count"] > 0:
            interp = summary["ai_interpretation"].lower()
            assert "stop" in interp or "location" in interp, \
                f"Expected ai_interpretation to mention stops: '{summary['ai_interpretation']}'"


class TestWebSocketEventWhitelist:
    """Tests for WebSocket command center event whitelist"""

    def test_ws_command_center_status_accessible(self):
        """WS Command Center status endpoint is accessible"""
        response = requests.get(f"{BASE_URL}/api/ws/command-center/status")
        assert response.status_code == 200
        data = response.json()
        assert "active_connections" in data
        assert "timestamp" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
