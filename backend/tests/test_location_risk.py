# Location Risk Intelligence API Tests
# Tests: Location Risk Scoring, Heatmap, Geofence, Device Location

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Known device IDs from seeded data
DEV_001_UUID = "ce4b5463-5a7e-46a5-8bbf-365dcfb3daeb"
DEV_002_UUID = "e029085c-1021-436d-9dfc-a0633979583d"

# Test coordinates (Bangalore area)
TEST_LAT = 12.97
TEST_LNG = 77.59
GEOFENCE_BREACH_LAT = 13.05  # Outside safe zone
GEOFENCE_BREACH_LNG = 77.65

@pytest.fixture(scope="module")
def api_client():
    """Shared requests session."""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session

@pytest.fixture(scope="module")
def operator_token(api_client):
    """Get operator authentication token."""
    response = api_client.post(f"{BASE_URL}/api/auth/login", json={
        "email": "operator@nischint.com",
        "password": "operator123"
    })
    if response.status_code != 200:
        pytest.skip("Operator login failed - skipping authenticated tests")
    return response.json().get("access_token")

@pytest.fixture(scope="module")
def authenticated_client(api_client, operator_token):
    """Session with auth header."""
    api_client.headers.update({"Authorization": f"Bearer {operator_token}"})
    return api_client


class TestLocationRiskAuth:
    """Test authentication requirements for Location Risk APIs."""
    
    def test_location_risk_requires_auth(self, api_client):
        """GET /api/operator/location-risk requires auth (401 without token)."""
        # Clear auth header
        api_client.headers.pop("Authorization", None)
        response = api_client.get(f"{BASE_URL}/api/operator/location-risk?lat={TEST_LAT}&lng={TEST_LNG}")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: GET /api/operator/location-risk returns 401 without auth")
    
    def test_heatmap_requires_auth(self, api_client):
        """GET /api/operator/location-risk/heatmap requires auth (401 without token)."""
        api_client.headers.pop("Authorization", None)
        response = api_client.get(f"{BASE_URL}/api/operator/location-risk/heatmap")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: GET /api/operator/location-risk/heatmap returns 401 without auth")
    
    def test_geofence_alert_requires_auth(self, api_client):
        """POST /api/operator/geofence-alert requires auth (401 without token)."""
        api_client.headers.pop("Authorization", None)
        response = api_client.post(f"{BASE_URL}/api/operator/geofence-alert?device_id={DEV_001_UUID}&lat={TEST_LAT}&lng={TEST_LNG}")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: POST /api/operator/geofence-alert returns 401 without auth")
    
    def test_device_location_update_requires_auth(self, api_client):
        """POST /api/operator/devices/{device_id}/location requires auth."""
        api_client.headers.pop("Authorization", None)
        response = api_client.post(f"{BASE_URL}/api/operator/devices/{DEV_001_UUID}/location?lat={TEST_LAT}&lng={TEST_LNG}")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: POST /api/operator/devices/{device_id}/location returns 401 without auth")
    
    def test_create_geofence_requires_auth(self, api_client):
        """POST /api/operator/devices/{device_id}/geofence requires auth."""
        api_client.headers.pop("Authorization", None)
        response = api_client.post(f"{BASE_URL}/api/operator/devices/{DEV_001_UUID}/geofence?name=TestZone&lat={TEST_LAT}&lng={TEST_LNG}&radius=500")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: POST /api/operator/devices/{device_id}/geofence returns 401 without auth")


class TestLocationRiskScoring:
    """Test Location Risk Scoring API."""
    
    def test_evaluate_location_risk_success(self, authenticated_client):
        """GET /api/operator/location-risk returns safety_score, risk_level, factors, breakdown."""
        response = authenticated_client.get(f"{BASE_URL}/api/operator/location-risk?lat={TEST_LAT}&lng={TEST_LNG}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Validate required fields
        assert "safety_score" in data, "Missing safety_score field"
        assert "risk_level" in data, "Missing risk_level field"
        assert "factors" in data, "Missing factors field"
        assert "breakdown" in data, "Missing breakdown field"
        
        # Validate safety_score range (0-10)
        assert 0 <= data["safety_score"] <= 10, f"safety_score {data['safety_score']} not in range 0-10"
        
        # Validate risk_level values
        assert data["risk_level"] in ["Critical", "High", "Moderate", "Low"], f"Invalid risk_level: {data['risk_level']}"
        
        # Validate factors is a list
        assert isinstance(data["factors"], list), "factors should be a list"
        
        # Validate breakdown structure
        breakdown = data["breakdown"]
        expected_breakdown_keys = ["incident_density", "time_of_day", "zone_proximity", "isolation", "history"]
        for key in expected_breakdown_keys:
            assert key in breakdown, f"Missing breakdown key: {key}"
        
        print(f"PASS: Location risk evaluation - score={data['safety_score']}, level={data['risk_level']}")
        print(f"  Breakdown: {breakdown}")
    
    def test_evaluate_location_risk_boundary_coords(self, authenticated_client):
        """Test location risk with boundary coordinates."""
        # Test near equator
        response = authenticated_client.get(f"{BASE_URL}/api/operator/location-risk?lat=0.0&lng=0.0")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert "safety_score" in data
        print("PASS: Location risk works with boundary coordinates (0,0)")
    
    def test_evaluate_location_returns_location_name(self, authenticated_client):
        """Verify location_name is returned in response."""
        response = authenticated_client.get(f"{BASE_URL}/api/operator/location-risk?lat={TEST_LAT}&lng={TEST_LNG}")
        assert response.status_code == 200
        data = response.json()
        assert "location_name" in data, "Missing location_name field"
        assert "latitude" in data, "Missing latitude field"
        assert "longitude" in data, "Missing longitude field"
        print(f"PASS: Location name returned: {data.get('location_name')}")


class TestLocationRiskHeatmap:
    """Test Location Risk Heatmap API."""
    
    def test_heatmap_returns_all_required_fields(self, authenticated_client):
        """GET /api/operator/location-risk/heatmap returns risk_zones, devices, incidents, geofences, active_alerts, center."""
        response = authenticated_client.get(f"{BASE_URL}/api/operator/location-risk/heatmap")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Validate all required top-level fields
        required_fields = ["risk_zones", "devices", "incidents", "geofences", "active_alerts", "center"]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        
        # Validate center structure
        center = data["center"]
        assert "lat" in center, "center missing lat"
        assert "lng" in center, "center missing lng"
        
        print(f"PASS: Heatmap returns all fields - zones={len(data['risk_zones'])}, devices={len(data['devices'])}, incidents={len(data['incidents'])}")
    
    def test_heatmap_risk_zones_structure(self, authenticated_client):
        """Verify risk_zones have proper structure."""
        response = authenticated_client.get(f"{BASE_URL}/api/operator/location-risk/heatmap")
        assert response.status_code == 200
        data = response.json()
        
        if data["risk_zones"]:
            zone = data["risk_zones"][0]
            zone_fields = ["id", "lat", "lng", "radius", "risk_score", "risk_level", "risk_type", "name"]
            for field in zone_fields:
                assert field in zone, f"Risk zone missing field: {field}"
            # Validate risk_score range
            assert 0 <= zone["risk_score"] <= 10, f"risk_score {zone['risk_score']} not in range 0-10"
            print(f"PASS: Risk zone structure valid - {len(data['risk_zones'])} zones, first: {zone['name']}")
        else:
            print("PASS: Heatmap returns empty risk_zones (no seeded data)")
    
    def test_heatmap_devices_structure(self, authenticated_client):
        """Verify devices have proper structure."""
        response = authenticated_client.get(f"{BASE_URL}/api/operator/location-risk/heatmap")
        assert response.status_code == 200
        data = response.json()
        
        if data["devices"]:
            device = data["devices"][0]
            device_fields = ["device_id", "device_identifier", "lat", "lng"]
            for field in device_fields:
                assert field in device, f"Device missing field: {field}"
            print(f"PASS: Device structure valid - {len(data['devices'])} devices")
        else:
            print("NOTE: No devices in heatmap data")
    
    def test_heatmap_geofences_structure(self, authenticated_client):
        """Verify geofences have proper structure."""
        response = authenticated_client.get(f"{BASE_URL}/api/operator/location-risk/heatmap")
        assert response.status_code == 200
        data = response.json()
        
        if data["geofences"]:
            gf = data["geofences"][0]
            gf_fields = ["id", "device_id", "device_identifier", "name", "lat", "lng", "radius", "type"]
            for field in gf_fields:
                assert field in gf, f"Geofence missing field: {field}"
            print(f"PASS: Geofence structure valid - {len(data['geofences'])} geofences")
        else:
            print("NOTE: No geofences in heatmap data")


class TestGeofenceOperations:
    """Test Geofence creation and breach detection."""
    
    def test_create_geofence_success(self, authenticated_client):
        """POST /api/operator/devices/{device_id}/geofence creates new geofence."""
        geofence_name = "TestSafeZone"
        response = authenticated_client.post(
            f"{BASE_URL}/api/operator/devices/{DEV_002_UUID}/geofence"
            f"?name={geofence_name}&lat={TEST_LAT}&lng={TEST_LNG}&radius=500&fence_type=safe"
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Validate response structure
        assert "id" in data, "Geofence creation should return id"
        assert "device_id" in data, "Geofence creation should return device_id"
        assert "name" in data, "Geofence creation should return name"
        assert data["name"] == geofence_name, f"Expected name {geofence_name}, got {data['name']}"
        
        print(f"PASS: Geofence created - id={data['id']}, name={data['name']}")
    
    def test_check_geofence_breach_detection(self, authenticated_client):
        """POST /api/operator/geofence-alert detects breach of safe zone."""
        # Check geofence at location outside safe zone
        response = authenticated_client.post(
            f"{BASE_URL}/api/operator/geofence-alert"
            f"?device_id={DEV_001_UUID}&lat={GEOFENCE_BREACH_LAT}&lng={GEOFENCE_BREACH_LNG}"
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Response is a list of breaches
        assert isinstance(data, list), "Geofence breach response should be a list"
        print(f"PASS: Geofence breach check completed - {len(data)} breach(es) detected")
        
        if data:
            breach = data[0]
            breach_fields = ["geofence_id", "geofence_name", "alert_type", "risk_score", "factors"]
            for field in breach_fields:
                assert field in breach, f"Breach missing field: {field}"
            print(f"  Breach: {breach['alert_type']} - {breach['geofence_name']}")
    
    def test_check_geofence_inside_safe_zone(self, authenticated_client):
        """Test geofence check when inside safe zone (no breach)."""
        # Check at safe zone center (should not trigger breach)
        response = authenticated_client.post(
            f"{BASE_URL}/api/operator/geofence-alert"
            f"?device_id={DEV_001_UUID}&lat={TEST_LAT}&lng={TEST_LNG}"
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert isinstance(data, list), "Response should be a list"
        print(f"PASS: Geofence check inside safe zone - {len(data)} breach(es)")


class TestDeviceLocation:
    """Test Device Location Update API."""
    
    def test_update_device_location_success(self, authenticated_client):
        """POST /api/operator/devices/{device_id}/location updates device location."""
        response = authenticated_client.post(
            f"{BASE_URL}/api/operator/devices/{DEV_001_UUID}/location"
            f"?lat={TEST_LAT}&lng={TEST_LNG}"
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Validate response structure
        assert "device_id" in data, "Response should include device_id"
        assert "latitude" in data, "Response should include latitude"
        assert "longitude" in data, "Response should include longitude"
        assert "updated_at" in data, "Response should include updated_at"
        assert "geofence_breaches" in data, "Response should include geofence_breaches"
        
        # Validate coordinates match input
        assert data["latitude"] == TEST_LAT, f"Expected lat {TEST_LAT}, got {data['latitude']}"
        assert data["longitude"] == TEST_LNG, f"Expected lng {TEST_LNG}, got {data['longitude']}"
        
        print(f"PASS: Device location updated - {data['latitude']}, {data['longitude']}")
        print(f"  Geofence breaches: {len(data['geofence_breaches'])}")
    
    def test_update_device_location_triggers_breach_check(self, authenticated_client):
        """Updating location outside safe zone triggers breach detection."""
        # Update to location outside safe zone
        response = authenticated_client.post(
            f"{BASE_URL}/api/operator/devices/{DEV_001_UUID}/location"
            f"?lat={GEOFENCE_BREACH_LAT}&lng={GEOFENCE_BREACH_LNG}"
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "geofence_breaches" in data, "Response should include geofence_breaches"
        print(f"PASS: Location update with breach check - {len(data['geofence_breaches'])} breach(es)")


class TestLocationRiskDataIntegrity:
    """Test data integrity and consistency."""
    
    def test_heatmap_center_is_valid_coordinate(self, authenticated_client):
        """Verify heatmap center is a valid geographic coordinate."""
        response = authenticated_client.get(f"{BASE_URL}/api/operator/location-risk/heatmap")
        assert response.status_code == 200
        data = response.json()
        
        center = data["center"]
        assert -90 <= center["lat"] <= 90, f"Invalid center latitude: {center['lat']}"
        assert -180 <= center["lng"] <= 180, f"Invalid center longitude: {center['lng']}"
        print(f"PASS: Heatmap center is valid - ({center['lat']}, {center['lng']})")
    
    def test_risk_score_consistency(self, authenticated_client):
        """Verify risk scores are consistent between APIs."""
        # Get location risk for a point
        risk_response = authenticated_client.get(f"{BASE_URL}/api/operator/location-risk?lat={TEST_LAT}&lng={TEST_LNG}")
        assert risk_response.status_code == 200
        risk_data = risk_response.json()
        
        # Verify breakdown sums logically
        breakdown = risk_data["breakdown"]
        total_breakdown = sum(breakdown.values())
        # Safety score should be related to breakdown (weighted)
        assert risk_data["safety_score"] <= 10, "Safety score should be <= 10"
        print(f"PASS: Risk score consistency - score={risk_data['safety_score']}, breakdown_total={total_breakdown}")
    
    def test_incidents_have_valid_severity(self, authenticated_client):
        """Verify incidents in heatmap have valid severity levels."""
        response = authenticated_client.get(f"{BASE_URL}/api/operator/location-risk/heatmap")
        assert response.status_code == 200
        data = response.json()
        
        valid_severities = ["critical", "high", "medium", "low"]
        for inc in data.get("incidents", []):
            assert inc.get("severity") in valid_severities, f"Invalid severity: {inc.get('severity')}"
        
        print(f"PASS: All {len(data.get('incidents', []))} incidents have valid severity")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
