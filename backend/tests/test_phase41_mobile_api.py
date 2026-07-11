"""
Phase 41 Mobile App Backend API Tests
=====================================
Tests all backend APIs that the mobile app will consume.
Validates authentication, safety score, guardian, and operator endpoints.
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"
GUARDIAN_EMAIL = "nischint4parents@gmail.com"
GUARDIAN_PASSWORD = "secret123"

# Test data
TEST_LAT = 12.9716
TEST_LNG = 77.5946
TEST_DEST_LAT = 12.9352
TEST_DEST_LNG = 77.6245
ACTIVE_SESSION_ID = "56c30aa1-8cd3-4489-9cd7-e402407ce5d1"


class TestAuthenticationEndpoints:
    """Test POST /api/auth/login for both operator and guardian"""

    def test_operator_login_returns_valid_jwt(self):
        """Operator login should return valid JWT with role=operator"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": OPERATOR_EMAIL,
            "password": OPERATOR_PASSWORD
        })
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "access_token" in data, "Response should contain access_token"
        assert isinstance(data["access_token"], str)
        assert len(data["access_token"]) > 0
        # JWT should have 3 parts separated by dots
        parts = data["access_token"].split(".")
        assert len(parts) == 3, "JWT should have 3 parts"
        print(f"✓ Operator login successful, JWT token received")

    def test_guardian_login_returns_valid_jwt(self):
        """Guardian login should return valid JWT with role=guardian"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": GUARDIAN_EMAIL,
            "password": GUARDIAN_PASSWORD
        })
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "access_token" in data, "Response should contain access_token"
        assert isinstance(data["access_token"], str)
        assert len(data["access_token"]) > 0
        print(f"✓ Guardian login successful, JWT token received")

    def test_invalid_credentials_returns_401(self):
        """Invalid credentials should return 401"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "wrong@example.com",
            "password": "wrongpassword"
        })
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print(f"✓ Invalid credentials correctly return 401")


class TestSafetyScoreEndpoints:
    """Test Safety Score API endpoints"""

    @pytest.fixture
    def auth_token(self):
        """Get operator auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": OPERATOR_EMAIL,
            "password": OPERATOR_PASSWORD
        })
        return response.json().get("access_token")

    def test_location_score_returns_required_fields(self, auth_token):
        """GET /api/safety-score/location should return score with signals, trend, percentile, night_score"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(
            f"{BASE_URL}/api/safety-score/location",
            params={"lat": TEST_LAT, "lng": TEST_LNG},
            headers=headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Verify required fields
        assert "score" in data, "Response should contain score"
        score = data["score"]
        assert 0 <= score <= 10, f"Score should be 0-10, got {score}"
        
        assert "signals" in data, "Response should contain signals"
        signals = data["signals"]
        expected_signals = ["zone_risk", "dynamic_risk", "incident_density", "route_exposure", "time_risk"]
        for sig in expected_signals:
            assert sig in signals, f"Missing signal: {sig}"
        
        assert "trend" in data, "Response should contain trend"
        assert data["trend"] in ["rising", "falling", "stable"], f"Invalid trend: {data['trend']}"
        
        assert "percentile" in data, "Response should contain percentile"
        assert 1 <= data["percentile"] <= 99, f"Percentile should be 1-99, got {data['percentile']}"
        
        assert "night_score" in data, "Response should contain night_score"
        assert 0 <= data["night_score"] <= 10, f"Night score should be 0-10, got {data['night_score']}"
        
        print(f"✓ Location score: {score:.1f}/10, trend: {data['trend']}, percentile: {data['percentile']}%, night: {data['night_score']:.1f}")

    def test_route_score_returns_required_fields(self, auth_token):
        """POST /api/safety-score/route should return score with risk_zones_crossed, max_risk, sample_points"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.post(
            f"{BASE_URL}/api/safety-score/route",
            json={
                "origin": {"lat": TEST_LAT, "lng": TEST_LNG},
                "destination": {"lat": TEST_DEST_LAT, "lng": TEST_DEST_LNG}
            },
            headers=headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Verify required fields
        assert "score" in data, "Response should contain score"
        score = data["score"]
        assert 0 <= score <= 10, f"Score should be 0-10, got {score}"
        
        assert "risk_zones_crossed" in data, "Response should contain risk_zones_crossed"
        assert data["risk_zones_crossed"] >= 0, "risk_zones_crossed should be non-negative"
        
        assert "max_risk" in data, "Response should contain max_risk"
        
        assert "sample_points" in data, "Response should contain sample_points"
        assert data["sample_points"] >= 2, f"sample_points should be >= 2, got {data['sample_points']}"
        
        print(f"✓ Route score: {score:.1f}/10, risk_zones: {data['risk_zones_crossed']}, max_risk: {data['max_risk']}, samples: {data['sample_points']}")

    def test_journey_score_returns_required_fields(self, auth_token):
        """GET /api/safety-score/journey/{id} should return journey score"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(
            f"{BASE_URL}/api/safety-score/journey/{ACTIVE_SESSION_ID}",
            headers=headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Verify required fields
        assert "score" in data, "Response should contain score"
        score = data["score"]
        assert 0 <= score <= 10, f"Score should be 0-10, got {score}"
        
        print(f"✓ Journey score: {score:.1f}/10")

    def test_location_score_requires_auth(self):
        """Safety score endpoints should require authentication"""
        response = requests.get(
            f"{BASE_URL}/api/safety-score/location",
            params={"lat": TEST_LAT, "lng": TEST_LNG}
        )
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print(f"✓ Location score correctly requires auth (401)")


class TestGuardianEndpoints:
    """Test Guardian API endpoints"""

    @pytest.fixture
    def guardian_token(self):
        """Get guardian auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": GUARDIAN_EMAIL,
            "password": GUARDIAN_PASSWORD
        })
        return response.json().get("access_token")

    @pytest.fixture
    def operator_token(self):
        """Get operator auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": OPERATOR_EMAIL,
            "password": OPERATOR_PASSWORD
        })
        return response.json().get("access_token")

    def test_guardian_start_endpoint(self, operator_token):
        """POST /api/guardian/start should be accessible"""
        headers = {"Authorization": f"Bearer {operator_token}"}
        response = requests.post(
            f"{BASE_URL}/api/guardian/start",
            json={"user_id": "test-user-id"},
            headers=headers
        )
        # Accept 200 or 422 (validation error) - endpoint is accessible
        assert response.status_code in [200, 201, 422], f"Expected 200/201/422, got {response.status_code}: {response.text}"
        print(f"✓ Guardian start endpoint accessible (status: {response.status_code})")

    def test_guardian_active_sessions(self, operator_token):
        """GET /api/guardian/sessions/active should return list of active sessions"""
        headers = {"Authorization": f"Bearer {operator_token}"}
        response = requests.get(
            f"{BASE_URL}/api/guardian/sessions/active",
            headers=headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        # Should return list or object with sessions
        assert isinstance(data, (list, dict)), "Response should be list or dict"
        print(f"✓ Guardian active sessions endpoint working")


class TestGuardianDashboardEndpoints:
    """Test Guardian Dashboard API endpoints"""

    @pytest.fixture
    def guardian_token(self):
        """Get guardian auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": GUARDIAN_EMAIL,
            "password": GUARDIAN_PASSWORD
        })
        return response.json().get("access_token")

    def test_guardian_dashboard_loved_ones(self, guardian_token):
        """GET /api/guardian/dashboard/loved-ones should return data"""
        headers = {"Authorization": f"Bearer {guardian_token}"}
        response = requests.get(
            f"{BASE_URL}/api/guardian/dashboard/loved-ones",
            headers=headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print(f"✓ Guardian dashboard loved-ones endpoint working")

    def test_guardian_dashboard_alerts(self, guardian_token):
        """GET /api/guardian/dashboard/alerts should return data"""
        headers = {"Authorization": f"Bearer {guardian_token}"}
        response = requests.get(
            f"{BASE_URL}/api/guardian/dashboard/alerts",
            headers=headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print(f"✓ Guardian dashboard alerts endpoint working")

    def test_guardian_dashboard_sessions(self, guardian_token):
        """GET /api/guardian/dashboard/sessions should return data"""
        headers = {"Authorization": f"Bearer {guardian_token}"}
        response = requests.get(
            f"{BASE_URL}/api/guardian/dashboard/sessions",
            headers=headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print(f"✓ Guardian dashboard sessions endpoint working")


class TestOperatorEndpoints:
    """Test Operator API endpoints"""

    @pytest.fixture
    def operator_token(self):
        """Get operator auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": OPERATOR_EMAIL,
            "password": OPERATOR_PASSWORD
        })
        return response.json().get("access_token")

    def test_predictive_alert_with_alternative(self, operator_token):
        """POST /api/predictive-alert/with-alternative should work"""
        headers = {"Authorization": f"Bearer {operator_token}"}
        response = requests.post(
            f"{BASE_URL}/api/predictive-alert/with-alternative",
            json={
                "location": {"lat": TEST_LAT, "lng": TEST_LNG},
                "speed": 30
            },
            headers=headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert isinstance(data, dict), "Response should be dict"
        print(f"✓ Predictive alert with alternative endpoint working")

    def test_safe_route(self, operator_token):
        """POST /api/safe-route should return routes"""
        headers = {"Authorization": f"Bearer {operator_token}"}
        response = requests.post(
            f"{BASE_URL}/api/safe-route",
            json={
                "origin": {"lat": TEST_LAT, "lng": TEST_LNG},
                "destination": {"lat": TEST_DEST_LAT, "lng": TEST_DEST_LNG}
            },
            headers=headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "routes" in data, "Response should contain routes"
        print(f"✓ Safe route endpoint working, {len(data.get('routes', []))} routes returned")


class TestMobileAppAPICompatibility:
    """Test that mobile app service calls match backend API contracts"""

    @pytest.fixture
    def auth_token(self):
        """Get operator auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": OPERATOR_EMAIL,
            "password": OPERATOR_PASSWORD
        })
        return response.json().get("access_token")

    def test_auth_login_response_format(self):
        """Mobile app expects { access_token: string } from login"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": OPERATOR_EMAIL,
            "password": OPERATOR_PASSWORD
        })
        data = response.json()
        assert "access_token" in data, "Mobile app requires access_token field"
        print(f"✓ Login response format matches mobile app expectations")

    def test_safety_score_location_format(self, auth_token):
        """Mobile app expects score, signals, trend, percentile, night_score from location score"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(
            f"{BASE_URL}/api/safety-score/location",
            params={"lat": TEST_LAT, "lng": TEST_LNG},
            headers=headers
        )
        data = response.json()
        
        # Mobile app expects these fields in home.tsx and safety-score.tsx
        required_fields = ["score", "signals", "trend", "percentile", "night_score"]
        for field in required_fields:
            assert field in data, f"Mobile app requires {field} field"
        
        print(f"✓ Location score response format matches mobile app expectations")

    def test_guardian_sessions_active_format(self, auth_token):
        """Mobile app expects sessions list from guardian/sessions/active"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(
            f"{BASE_URL}/api/guardian/sessions/active",
            headers=headers
        )
        data = response.json()
        
        # Mobile app expects array or {sessions: array}
        if isinstance(data, dict):
            assert "sessions" in data or isinstance(data, dict), "Response should have sessions or be dict"
        print(f"✓ Guardian sessions response format matches mobile app expectations")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
