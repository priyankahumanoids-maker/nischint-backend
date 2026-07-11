"""
AI Services Mobile API Tests
Tests 8 mobile-facing AI endpoints exposed under /api/ai/*:
1. GET /api/ai/life-pattern - Life pattern for family device
2. GET /api/ai/digital-twin - Digital twin behavioural profile
3. GET /api/ai/risk-forecast - Predicted risk forecast
4. GET /api/ai/environment-risk - Environmental risk assessment (requires lat/lng)
5. GET /api/ai/behavior-analysis - Anomaly data and baselines
6. GET /api/ai/twin-evolution - Twin evolution history
7. GET /api/ai/hotspot-trends - Hotspot trends (requires lat/lng)
8. GET /api/ai/family-summary - Risk/anomaly/twin summary for all family members
"""

import os
import pytest
import requests
from datetime import datetime

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

# Test credentials
ADMIN_EMAIL = "nischint4parents@gmail.com"
ADMIN_PASSWORD = "secret123"

# Location params for geo-based endpoints
TEST_LAT = 19.076
TEST_LNG = 72.877


class TestAIServicesAuthentication:
    """All endpoints should return 401 without auth token"""

    def test_life_pattern_requires_auth(self):
        """GET /api/ai/life-pattern should return 401 without token"""
        response = requests.get(f"{BASE_URL}/api/ai/life-pattern")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"
        print(f"✓ life-pattern returns 401 without auth: {response.status_code}")

    def test_digital_twin_requires_auth(self):
        """GET /api/ai/digital-twin should return 401 without token"""
        response = requests.get(f"{BASE_URL}/api/ai/digital-twin")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"
        print(f"✓ digital-twin returns 401 without auth: {response.status_code}")

    def test_risk_forecast_requires_auth(self):
        """GET /api/ai/risk-forecast should return 401 without token"""
        response = requests.get(f"{BASE_URL}/api/ai/risk-forecast")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"
        print(f"✓ risk-forecast returns 401 without auth: {response.status_code}")

    def test_environment_risk_requires_auth(self):
        """GET /api/ai/environment-risk should return 401 without token"""
        response = requests.get(f"{BASE_URL}/api/ai/environment-risk", params={"lat": TEST_LAT, "lng": TEST_LNG})
        assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"
        print(f"✓ environment-risk returns 401 without auth: {response.status_code}")

    def test_behavior_analysis_requires_auth(self):
        """GET /api/ai/behavior-analysis should return 401 without token"""
        response = requests.get(f"{BASE_URL}/api/ai/behavior-analysis")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"
        print(f"✓ behavior-analysis returns 401 without auth: {response.status_code}")

    def test_twin_evolution_requires_auth(self):
        """GET /api/ai/twin-evolution should return 401 without token"""
        response = requests.get(f"{BASE_URL}/api/ai/twin-evolution")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"
        print(f"✓ twin-evolution returns 401 without auth: {response.status_code}")

    def test_hotspot_trends_requires_auth(self):
        """GET /api/ai/hotspot-trends should return 401 without token"""
        response = requests.get(f"{BASE_URL}/api/ai/hotspot-trends", params={"lat": TEST_LAT, "lng": TEST_LNG})
        assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"
        print(f"✓ hotspot-trends returns 401 without auth: {response.status_code}")

    def test_family_summary_requires_auth(self):
        """GET /api/ai/family-summary should return 401 without token"""
        response = requests.get(f"{BASE_URL}/api/ai/family-summary")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"
        print(f"✓ family-summary returns 401 without auth: {response.status_code}")


class TestAIServicesWithAuth:
    """All endpoints should return valid JSON with generated_at timestamp"""

    @pytest.fixture(scope="class")
    def auth_token(self):
        """Authenticate and get access token"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
        )
        assert response.status_code == 200, f"Login failed: {response.status_code} - {response.text}"
        data = response.json()
        # API returns 'access_token' not 'token'
        token = data.get("access_token") or data.get("token")
        assert token, f"No token in response: {data}"
        print(f"✓ Login successful, got access_token")
        return token

    @pytest.fixture(scope="class")
    def auth_headers(self, auth_token):
        """Return headers with auth token"""
        return {"Authorization": f"Bearer {auth_token}"}

    def _validate_generated_at(self, data: dict, endpoint: str):
        """Verify generated_at field is a valid ISO timestamp"""
        assert "generated_at" in data, f"{endpoint} missing 'generated_at' field"
        generated_at = data["generated_at"]
        # Parse to verify it's a valid ISO timestamp
        try:
            datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        except ValueError:
            pytest.fail(f"{endpoint} 'generated_at' is not a valid ISO timestamp: {generated_at}")
        print(f"  ✓ generated_at is valid ISO timestamp: {generated_at}")

    # 1. Life Pattern endpoint
    def test_life_pattern_returns_valid_json(self, auth_headers):
        """GET /api/ai/life-pattern should return valid JSON with life pattern data"""
        response = requests.get(f"{BASE_URL}/api/ai/life-pattern", headers=auth_headers)
        
        # May return 404 if no devices linked to family
        if response.status_code == 404:
            data = response.json()
            print(f"✓ life-pattern returns 404 (no linked devices): {data}")
            return
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Validate response shape
        assert isinstance(data, dict), "Response should be a dict"
        assert "device_id" in data, "Missing 'device_id' field"
        assert "life_pattern" in data, "Missing 'life_pattern' field"
        self._validate_generated_at(data, "life-pattern")
        
        print(f"✓ life-pattern returns valid JSON: device_id={data.get('device_id')}, name={data.get('name')}")
        print(f"  life_pattern keys: {list(data.get('life_pattern', {}).keys()) if isinstance(data.get('life_pattern'), dict) else 'N/A'}")

    # 2. Digital Twin endpoint
    def test_digital_twin_returns_valid_json(self, auth_headers):
        """GET /api/ai/digital-twin should return valid JSON with twin profile"""
        response = requests.get(f"{BASE_URL}/api/ai/digital-twin", headers=auth_headers)
        
        if response.status_code == 404:
            data = response.json()
            print(f"✓ digital-twin returns 404 (no linked devices): {data}")
            return
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert isinstance(data, dict), "Response should be a dict"
        assert "device_id" in data, "Missing 'device_id' field"
        assert "name" in data, "Missing 'name' field"
        
        # twin_exists indicates if twin has been built
        if data.get("twin_exists") is False:
            print(f"✓ digital-twin returns valid JSON (twin not built yet): {data.get('message')}")
            return
        
        # If twin exists, validate additional fields
        self._validate_generated_at(data, "digital-twin")
        print(f"✓ digital-twin returns valid JSON: twin_exists={data.get('twin_exists')}, confidence={data.get('confidence')}")

    # 3. Risk Forecast endpoint
    def test_risk_forecast_returns_valid_json(self, auth_headers):
        """GET /api/ai/risk-forecast should return valid JSON with forecast data"""
        response = requests.get(f"{BASE_URL}/api/ai/risk-forecast", headers=auth_headers)
        
        if response.status_code == 404:
            data = response.json()
            print(f"✓ risk-forecast returns 404 (no linked devices): {data}")
            return
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert isinstance(data, dict), "Response should be a dict"
        assert "device_id" in data, "Missing 'device_id' field"
        assert "forecast" in data, "Missing 'forecast' field"
        self._validate_generated_at(data, "risk-forecast")
        
        print(f"✓ risk-forecast returns valid JSON: device_id={data.get('device_id')}, name={data.get('name')}")

    # 4. Environment Risk endpoint (requires lat/lng)
    def test_environment_risk_returns_valid_json(self, auth_headers):
        """GET /api/ai/environment-risk should return valid JSON with environmental data"""
        response = requests.get(
            f"{BASE_URL}/api/ai/environment-risk",
            headers=auth_headers,
            params={"lat": TEST_LAT, "lng": TEST_LNG}
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert isinstance(data, dict), "Response should be a dict"
        assert "lat" in data, "Missing 'lat' field"
        assert "lng" in data, "Missing 'lng' field"
        assert "environment_risk" in data, "Missing 'environment_risk' field"
        self._validate_generated_at(data, "environment-risk")
        
        assert data["lat"] == TEST_LAT, f"lat mismatch: {data['lat']} != {TEST_LAT}"
        assert data["lng"] == TEST_LNG, f"lng mismatch: {data['lng']} != {TEST_LNG}"
        
        print(f"✓ environment-risk returns valid JSON for ({TEST_LAT}, {TEST_LNG})")
        print(f"  environment_risk keys: {list(data.get('environment_risk', {}).keys()) if isinstance(data.get('environment_risk'), dict) else 'N/A'}")

    def test_environment_risk_missing_params(self, auth_headers):
        """GET /api/ai/environment-risk should return 422 without lat/lng params"""
        response = requests.get(f"{BASE_URL}/api/ai/environment-risk", headers=auth_headers)
        assert response.status_code == 422, f"Expected 422 for missing params, got {response.status_code}"
        print(f"✓ environment-risk returns 422 when lat/lng missing")

    # 5. Behavior Analysis endpoint
    def test_behavior_analysis_returns_valid_json(self, auth_headers):
        """GET /api/ai/behavior-analysis should return valid JSON with anomaly data"""
        response = requests.get(f"{BASE_URL}/api/ai/behavior-analysis", headers=auth_headers)
        
        if response.status_code == 404:
            data = response.json()
            print(f"✓ behavior-analysis returns 404 (no linked devices): {data}")
            return
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert isinstance(data, dict), "Response should be a dict"
        assert "device_id" in data, "Missing 'device_id' field"
        assert "anomalies" in data, "Missing 'anomalies' field"
        assert "baselines" in data, "Missing 'baselines' field"
        self._validate_generated_at(data, "behavior-analysis")
        
        print(f"✓ behavior-analysis returns valid JSON: anomalies={len(data.get('anomalies', []))}, baselines={len(data.get('baselines', {}))}")

    # 6. Twin Evolution endpoint
    def test_twin_evolution_returns_valid_json(self, auth_headers):
        """GET /api/ai/twin-evolution should return valid JSON with evolution history"""
        response = requests.get(f"{BASE_URL}/api/ai/twin-evolution", headers=auth_headers)
        
        if response.status_code == 404:
            data = response.json()
            print(f"✓ twin-evolution returns 404 (no linked devices): {data}")
            return
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert isinstance(data, dict), "Response should be a dict"
        assert "device_id" in data, "Missing 'device_id' field"
        assert "evolution" in data, "Missing 'evolution' field"
        self._validate_generated_at(data, "twin-evolution")
        
        print(f"✓ twin-evolution returns valid JSON: device_id={data.get('device_id')}")

    # 7. Hotspot Trends endpoint (requires lat/lng)
    def test_hotspot_trends_returns_valid_json(self, auth_headers):
        """GET /api/ai/hotspot-trends should return valid JSON with trend data"""
        response = requests.get(
            f"{BASE_URL}/api/ai/hotspot-trends",
            headers=auth_headers,
            params={"lat": TEST_LAT, "lng": TEST_LNG}
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert isinstance(data, dict), "Response should be a dict"
        assert "lat" in data, "Missing 'lat' field"
        assert "lng" in data, "Missing 'lng' field"
        assert "trends" in data, "Missing 'trends' field"
        assert "radius_km" in data, "Missing 'radius_km' field"
        self._validate_generated_at(data, "hotspot-trends")
        
        print(f"✓ hotspot-trends returns valid JSON for ({TEST_LAT}, {TEST_LNG}), radius={data.get('radius_km')}km")

    def test_hotspot_trends_missing_params(self, auth_headers):
        """GET /api/ai/hotspot-trends should return 422 without lat/lng params"""
        response = requests.get(f"{BASE_URL}/api/ai/hotspot-trends", headers=auth_headers)
        assert response.status_code == 422, f"Expected 422 for missing params, got {response.status_code}"
        print(f"✓ hotspot-trends returns 422 when lat/lng missing")

    def test_hotspot_trends_custom_radius(self, auth_headers):
        """GET /api/ai/hotspot-trends should accept custom radius_km param"""
        response = requests.get(
            f"{BASE_URL}/api/ai/hotspot-trends",
            headers=auth_headers,
            params={"lat": TEST_LAT, "lng": TEST_LNG, "radius_km": 10.0}
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data.get("radius_km") == 10.0, f"radius_km should be 10.0, got {data.get('radius_km')}"
        print(f"✓ hotspot-trends accepts custom radius_km=10.0")

    # 8. Family Summary endpoint
    def test_family_summary_returns_valid_json(self, auth_headers):
        """GET /api/ai/family-summary should return valid JSON with family data"""
        response = requests.get(f"{BASE_URL}/api/ai/family-summary", headers=auth_headers)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert isinstance(data, dict), "Response should be a dict"
        
        # If no devices, response may have message instead of members
        if "message" in data and data.get("members") == []:
            print(f"✓ family-summary returns valid JSON (no linked devices): {data.get('message')}")
            return
        
        assert "members" in data, "Missing 'members' field"
        assert "family_member_count" in data, "Missing 'family_member_count' field"
        self._validate_generated_at(data, "family-summary")
        
        # Validate members structure
        members = data.get("members", [])
        assert isinstance(members, list), "'members' should be a list"
        
        if members:
            member = members[0]
            expected_fields = ["device_id", "name", "risk_score", "anomalies_24h", "twin_confidence"]
            for field in expected_fields:
                assert field in member, f"Member missing '{field}' field"
        
        print(f"✓ family-summary returns valid JSON: {data.get('family_member_count')} members")
        for m in members:
            print(f"  - {m.get('name')}: risk={m.get('risk_score')}, anomalies_24h={m.get('anomalies_24h')}, twin_conf={m.get('twin_confidence')}")


class TestAIServicesEdgeCases:
    """Edge case tests for AI endpoints"""

    @pytest.fixture(scope="class")
    def auth_token(self):
        """Authenticate and get access token"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
        )
        assert response.status_code == 200, f"Login failed: {response.status_code} - {response.text}"
        data = response.json()
        return data.get("access_token") or data.get("token")

    @pytest.fixture(scope="class")
    def auth_headers(self, auth_token):
        return {"Authorization": f"Bearer {auth_token}"}

    def test_invalid_device_id_returns_403(self, auth_headers):
        """Passing device_id not in family scope should return 403"""
        fake_device_id = "00000000-0000-0000-0000-000000000000"
        response = requests.get(
            f"{BASE_URL}/api/ai/life-pattern",
            headers=auth_headers,
            params={"device_id": fake_device_id}
        )
        # Should be 403 (forbidden) or 404 (not found)
        assert response.status_code in [403, 404], f"Expected 403 or 404 for invalid device_id, got {response.status_code}"
        print(f"✓ life-pattern returns {response.status_code} for invalid device_id")

    def test_invalid_coordinates(self, auth_headers):
        """Test environment-risk with edge case coordinates"""
        # Test with extreme but valid coordinates
        response = requests.get(
            f"{BASE_URL}/api/ai/environment-risk",
            headers=auth_headers,
            params={"lat": 0.0, "lng": 0.0}  # Null Island
        )
        assert response.status_code == 200, f"Expected 200 for (0,0), got {response.status_code}"
        print(f"✓ environment-risk handles (0,0) coordinates")

    def test_hotspot_trends_boundary_radius(self, auth_headers):
        """Test hotspot-trends with min/max radius values"""
        # Test min radius (0.5km)
        response = requests.get(
            f"{BASE_URL}/api/ai/hotspot-trends",
            headers=auth_headers,
            params={"lat": TEST_LAT, "lng": TEST_LNG, "radius_km": 0.5}
        )
        assert response.status_code == 200, f"Expected 200 for min radius, got {response.status_code}"
        
        # Test max radius (50km)
        response = requests.get(
            f"{BASE_URL}/api/ai/hotspot-trends",
            headers=auth_headers,
            params={"lat": TEST_LAT, "lng": TEST_LNG, "radius_km": 50}
        )
        assert response.status_code == 200, f"Expected 200 for max radius, got {response.status_code}"
        
        # Test over max radius (should fail with 422)
        response = requests.get(
            f"{BASE_URL}/api/ai/hotspot-trends",
            headers=auth_headers,
            params={"lat": TEST_LAT, "lng": TEST_LNG, "radius_km": 51}
        )
        assert response.status_code == 422, f"Expected 422 for radius > 50, got {response.status_code}"
        
        print(f"✓ hotspot-trends validates radius_km boundaries (0.5-50km)")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
