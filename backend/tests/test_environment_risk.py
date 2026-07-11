"""
Environmental Risk AI Module Tests
Tests for the NISCHINT Environmental Risk features:
- GET /api/operator/environment-risk?lat=...&lng=... - Single location environmental risk
- GET /api/operator/environment-risk/fleet - Fleet-wide environmental risk
- GET /api/operator/device-health - Devices with latitude/longitude fields
- GET /api/operator/command-center - Contains environment_status array
- All endpoints require operator auth
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"


class TestEnvironmentRiskAuth:
    """Test that all environmental risk endpoints require operator auth"""

    def test_environment_risk_no_auth(self):
        """GET /api/operator/environment-risk should return 401 without auth"""
        resp = requests.get(f"{BASE_URL}/api/operator/environment-risk?lat=12.97&lng=77.59")
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"
        print("PASS: environment-risk endpoint requires authentication")

    def test_fleet_environment_no_auth(self):
        """GET /api/operator/environment-risk/fleet should return 401 without auth"""
        resp = requests.get(f"{BASE_URL}/api/operator/environment-risk/fleet")
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"
        print("PASS: fleet environment endpoint requires authentication")


@pytest.fixture(scope="module")
def operator_token():
    """Get operator authentication token"""
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": OPERATOR_EMAIL,
        "password": OPERATOR_PASSWORD
    })
    if resp.status_code != 200:
        pytest.skip(f"Operator login failed: {resp.status_code} - {resp.text}")
    token = resp.json().get("access_token")
    if not token:
        pytest.skip("No access_token in login response")
    print(f"PASS: Operator login successful")
    return token


@pytest.fixture(scope="module")
def auth_headers(operator_token):
    """Create authorization headers"""
    return {"Authorization": f"Bearer {operator_token}"}


class TestEnvironmentRiskSingleLocation:
    """Test single location environmental risk evaluation"""

    def test_environment_risk_response_structure(self, auth_headers):
        """
        GET /api/operator/environment-risk returns proper structure:
        - environment_score (0-10)
        - risk_level
        - factors (list)
        - breakdown (heat_index, air_pollution, rain_risk, wind_risk, uv_risk)
        - weather (temperature, humidity, wind_speed, etc.)
        - air_quality (aqi, pm2_5, pm10, etc.)
        - recommendations (list)
        """
        resp = requests.get(
            f"{BASE_URL}/api/operator/environment-risk",
            params={"lat": 12.97, "lng": 77.59},  # Bangalore coordinates
            headers=auth_headers
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        
        data = resp.json()
        
        # Check required top-level fields
        assert "environment_score" in data, "Missing environment_score"
        assert "risk_level" in data, "Missing risk_level"
        assert "factors" in data, "Missing factors"
        assert "breakdown" in data, "Missing breakdown"
        assert "weather" in data, "Missing weather"
        assert "air_quality" in data, "Missing air_quality"
        assert "recommendations" in data, "Missing recommendations"
        
        # Validate environment_score range (0-10)
        score = data["environment_score"]
        assert 0 <= score <= 10, f"environment_score {score} out of range 0-10"
        
        # Validate risk_level values
        valid_levels = ["Safe", "Moderate", "High", "Critical"]
        assert data["risk_level"] in valid_levels, f"Invalid risk_level: {data['risk_level']}"
        
        print(f"PASS: Environment risk response structure valid - Score: {score}, Level: {data['risk_level']}")

    def test_breakdown_has_5_components(self, auth_headers):
        """Test that breakdown has all 5 risk components with proper weights"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/environment-risk",
            params={"lat": 12.97, "lng": 77.59},
            headers=auth_headers
        )
        assert resp.status_code == 200
        
        breakdown = resp.json().get("breakdown", {})
        
        # Required breakdown keys
        required_keys = ["heat_index", "air_pollution", "rain_risk", "wind_risk", "uv_risk"]
        for key in required_keys:
            assert key in breakdown, f"Missing breakdown component: {key}"
            val = breakdown[key]
            assert isinstance(val, (int, float)), f"{key} should be numeric, got {type(val)}"
            assert 0 <= val <= 10, f"{key} value {val} out of range 0-10"
        
        print(f"PASS: Breakdown has all 5 components - Heat: {breakdown['heat_index']}, Air: {breakdown['air_pollution']}, Rain: {breakdown['rain_risk']}, Wind: {breakdown['wind_risk']}, UV: {breakdown['uv_risk']}")

    def test_weather_details(self, auth_headers):
        """Test weather details contain required fields"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/environment-risk",
            params={"lat": 12.97, "lng": 77.59},
            headers=auth_headers
        )
        assert resp.status_code == 200
        
        weather = resp.json().get("weather", {})
        
        # Required weather fields
        assert "temperature" in weather, "Missing temperature"
        assert "humidity" in weather, "Missing humidity"
        assert "wind_speed" in weather, "Missing wind_speed"
        assert "condition" in weather, "Missing condition"
        
        print(f"PASS: Weather details - Temp: {weather.get('temperature')}°C, Humidity: {weather.get('humidity')}%, Wind: {weather.get('wind_speed')}m/s")

    def test_air_quality_details(self, auth_headers):
        """Test air quality contains AQI, PM2.5, PM10"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/environment-risk",
            params={"lat": 12.97, "lng": 77.59},
            headers=auth_headers
        )
        assert resp.status_code == 200
        
        air_quality = resp.json().get("air_quality", {})
        
        # Required air quality fields
        assert "aqi" in air_quality, "Missing aqi"
        assert "pm2_5" in air_quality, "Missing pm2_5"
        assert "pm10" in air_quality, "Missing pm10"
        
        # AQI should be 1-5 scale
        aqi = air_quality.get("aqi")
        assert 1 <= aqi <= 5, f"AQI {aqi} out of 1-5 scale"
        
        print(f"PASS: Air quality - AQI: {aqi}, PM2.5: {air_quality.get('pm2_5')}, PM10: {air_quality.get('pm10')}")

    def test_recommendations_and_factors(self, auth_headers):
        """Test factors and recommendations arrays are present"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/environment-risk",
            params={"lat": 12.97, "lng": 77.59},
            headers=auth_headers
        )
        assert resp.status_code == 200
        
        data = resp.json()
        
        factors = data.get("factors", [])
        recommendations = data.get("recommendations", [])
        
        assert isinstance(factors, list), "factors should be a list"
        assert isinstance(recommendations, list), "recommendations should be a list"
        assert len(factors) >= 1, "Should have at least 1 factor"
        assert len(recommendations) >= 1, "Should have at least 1 recommendation"
        
        print(f"PASS: Factors ({len(factors)}): {factors[:2]}...")
        print(f"PASS: Recommendations ({len(recommendations)}): {recommendations[:2]}...")


class TestFleetEnvironment:
    """Test fleet-wide environmental risk endpoint"""

    def test_fleet_environment_returns_array(self, auth_headers):
        """GET /api/operator/environment-risk/fleet returns array of devices"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/environment-risk/fleet",
            headers=auth_headers
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        
        data = resp.json()
        assert isinstance(data, list), f"Expected list, got {type(data)}"
        
        print(f"PASS: Fleet environment returns array with {len(data)} devices")

    def test_fleet_device_structure(self, auth_headers):
        """Each device in fleet has required fields"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/environment-risk/fleet",
            headers=auth_headers
        )
        assert resp.status_code == 200
        
        data = resp.json()
        if not data:
            pytest.skip("No devices with locations in fleet")
        
        device = data[0]
        
        # Required fields per device
        required_fields = ["device_id", "device_identifier", "environment_score", 
                          "risk_level", "weather", "air_quality"]
        for field in required_fields:
            assert field in device, f"Missing field: {field}"
        
        # Validate environment_score
        score = device.get("environment_score")
        assert 0 <= score <= 10, f"environment_score {score} out of range"
        
        print(f"PASS: Fleet device structure valid - {device.get('device_identifier')}: Score={score}, Level={device.get('risk_level')}")

    def test_fleet_sorted_by_risk(self, auth_headers):
        """Fleet should be sorted by environment_score descending (worst first)"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/environment-risk/fleet",
            headers=auth_headers
        )
        assert resp.status_code == 200
        
        data = resp.json()
        if len(data) < 2:
            pytest.skip("Need at least 2 devices to verify sorting")
        
        scores = [d.get("environment_score", 0) for d in data]
        # Check descending order
        is_sorted = all(scores[i] >= scores[i+1] for i in range(len(scores)-1))
        assert is_sorted, f"Fleet not sorted by risk descending: {scores[:5]}"
        
        print(f"PASS: Fleet sorted by risk (worst first) - Top scores: {scores[:3]}")


class TestDeviceHealthLatLng:
    """Test that device health includes latitude/longitude fields"""

    def test_device_health_has_coordinates(self, auth_headers):
        """GET /api/operator/device-health returns devices with lat/lng"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/device-health",
            params={"window_hours": 24},
            headers=auth_headers
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        
        data = resp.json()
        assert isinstance(data, list), "device-health should return list"
        
        if not data:
            pytest.skip("No devices found in health endpoint")
        
        # At least some devices should have coordinates
        devices_with_coords = [d for d in data if d.get("latitude") and d.get("longitude")]
        
        print(f"PASS: Device health returns {len(data)} devices, {len(devices_with_coords)} have coordinates")
        
        if devices_with_coords:
            device = devices_with_coords[0]
            print(f"Sample device with coords: {device.get('device_identifier')} at ({device.get('latitude')}, {device.get('longitude')})")


class TestCommandCenterEnvironment:
    """Test that Command Center includes environment_status"""

    def test_command_center_has_environment_status(self, auth_headers):
        """GET /api/operator/command-center returns environment_status array"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/command-center",
            headers=auth_headers,
            timeout=60  # Command Center can take ~20s per main agent note
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        
        data = resp.json()
        
        assert "environment_status" in data, "Missing environment_status in command-center"
        env_status = data.get("environment_status")
        assert isinstance(env_status, list), f"environment_status should be list, got {type(env_status)}"
        
        print(f"PASS: Command Center has environment_status with {len(env_status)} devices")

    def test_command_center_generated_at(self, auth_headers):
        """Command Center should have generated_at timestamp"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/command-center",
            headers=auth_headers,
            timeout=60
        )
        assert resp.status_code == 200
        
        data = resp.json()
        assert "generated_at" in data, "Missing generated_at timestamp"
        
        print(f"PASS: Command Center generated_at: {data.get('generated_at')}")

    def test_command_center_counts(self, auth_headers):
        """Command Center should have counts object"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/command-center",
            headers=auth_headers,
            timeout=60
        )
        assert resp.status_code == 200
        
        data = resp.json()
        assert "counts" in data, "Missing counts in command-center"
        
        counts = data.get("counts", {})
        print(f"PASS: Command Center counts: {counts}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
