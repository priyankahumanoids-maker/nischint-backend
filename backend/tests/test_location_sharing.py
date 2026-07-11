# Location Sharing Feature Tests - Live Tracking Link System
# Tests for POST /share, GET /track/{token}, DELETE /share/{token}

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
CHILD_EMAIL = "kidnischint@gmail.com"
CHILD_PASSWORD = "nischint123"
MOTHER_EMAIL = "mothernischint@gmail.com"
MOTHER_PASSWORD = "nischint123"

# Existing test token for GET /track testing
EXISTING_TOKEN = "W-6TBGybbHfluAhTP65ijEW3xtGdreprHCBee5Wab7k"


class TestPublicTrackingEndpoint:
    """Tests for GET /api/location/track/{token} - Public endpoint (no auth required)"""

    def test_track_valid_token_returns_live_data(self):
        """Test that a valid token returns live tracking data"""
        response = requests.get(f"{BASE_URL}/api/location/track/{EXISTING_TOKEN}")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        # Validate response structure
        assert "status" in data, "Response should contain 'status'"
        assert "share_name" in data, "Response should contain 'share_name'"
        assert "user_name" in data, "Response should contain 'user_name'"
        assert "expires_at" in data, "Response should contain 'expires_at'"
        assert "risk_level" in data, "Response should contain 'risk_level'"
        
        # Validate data values
        assert data["status"] in ["live", "expired", "inactive"], f"Invalid status: {data['status']}"
        assert isinstance(data["share_name"], str) and len(data["share_name"]) > 0
        print(f"✓ Valid token returns live data: share_name={data['share_name']}, status={data['status']}")

    def test_track_valid_token_location_fields(self):
        """Test that valid token response contains location fields"""
        response = requests.get(f"{BASE_URL}/api/location/track/{EXISTING_TOKEN}")
        
        assert response.status_code == 200
        data = response.json()
        
        # Location fields should exist (may be null if no active session)
        assert "lat" in data
        assert "lng" in data
        assert "accuracy_m" in data
        assert "heading" in data
        assert "speed_mps" in data
        
        # Session-related fields
        assert "session_active" in data
        assert "total_distance_m" in data
        assert "session_duration_s" in data
        print(f"✓ Location fields present: lat={data['lat']}, lng={data['lng']}, session_active={data['session_active']}")

    def test_track_invalid_token_returns_404(self):
        """Test that an invalid token returns 404"""
        response = requests.get(f"{BASE_URL}/api/location/track/invalid_token_xyz123")
        
        assert response.status_code == 404, f"Expected 404, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "detail" in data or "message" in data or "error" in data
        print(f"✓ Invalid token correctly returns 404")

    def test_track_empty_token_returns_error(self):
        """Test that an empty token returns error"""
        response = requests.get(f"{BASE_URL}/api/location/track/")
        
        # Should return 404 or 405 (method not allowed for the route without token)
        assert response.status_code in [404, 405, 422], f"Expected 404/405/422, got {response.status_code}"
        print(f"✓ Empty token correctly returns {response.status_code}")


class TestAuthenticatedShareEndpoints:
    """Tests for POST /api/location/share and DELETE /api/location/share/{token}"""

    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get authentication token for child user"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": CHILD_EMAIL,
            "password": CHILD_PASSWORD
        })
        
        if response.status_code != 200:
            pytest.skip(f"Authentication failed: {response.status_code} - {response.text}")
        
        data = response.json()
        token = data.get("access_token") or data.get("token")
        if not token:
            pytest.skip(f"No token in response: {data}")
        
        return token

    @pytest.fixture(scope="class")
    def auth_headers(self, auth_token):
        """Return headers with auth token"""
        return {
            "Authorization": f"Bearer {auth_token}",
            "Content-Type": "application/json"
        }

    def test_create_share_link_default_duration(self, auth_headers):
        """Test creating a share link with default duration"""
        response = requests.post(
            f"{BASE_URL}/api/location/share",
            headers=auth_headers,
            json={}
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        # Validate response structure
        assert "token" in data, "Response should contain 'token'"
        assert "tracking_url" in data, "Response should contain 'tracking_url'"
        assert "expires_at" in data, "Response should contain 'expires_at'"
        assert "share_name" in data, "Response should contain 'share_name'"
        
        # Validate token format (base64url safe, ~43 chars)
        assert len(data["token"]) >= 40, f"Token too short: {len(data['token'])}"
        assert data["tracking_url"].startswith("/track/"), f"Invalid tracking_url: {data['tracking_url']}"
        
        print(f"✓ Created share link: token={data['token'][:20]}..., tracking_url={data['tracking_url']}")
        return data

    def test_create_share_link_custom_duration(self, auth_headers):
        """Test creating a share link with custom 2-hour duration"""
        response = requests.post(
            f"{BASE_URL}/api/location/share",
            headers=auth_headers,
            json={"duration_hours": 2}
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "token" in data
        assert "expires_at" in data
        print(f"✓ Created share link with 2h duration, expires_at={data['expires_at']}")

    def test_create_share_link_custom_name(self, auth_headers):
        """Test creating a share link with custom share name"""
        response = requests.post(
            f"{BASE_URL}/api/location/share",
            headers=auth_headers,
            json={"duration_hours": 4, "share_name": "My Test Tracking"}
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["share_name"] == "My Test Tracking", f"Expected custom name, got: {data['share_name']}"
        print(f"✓ Created share link with custom name: {data['share_name']}")

    def test_create_share_link_max_duration(self, auth_headers):
        """Test creating a share link with max 24-hour duration"""
        response = requests.post(
            f"{BASE_URL}/api/location/share",
            headers=auth_headers,
            json={"duration_hours": 24}
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "token" in data
        print(f"✓ Created share link with max 24h duration")

    def test_create_share_link_exceeds_max_duration(self, auth_headers):
        """Test that duration > 24 hours is rejected"""
        response = requests.post(
            f"{BASE_URL}/api/location/share",
            headers=auth_headers,
            json={"duration_hours": 48}
        )
        
        # Should return 422 validation error
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        print(f"✓ Duration > 24h correctly rejected with 422")

    def test_create_share_link_zero_duration(self, auth_headers):
        """Test that duration = 0 is rejected"""
        response = requests.post(
            f"{BASE_URL}/api/location/share",
            headers=auth_headers,
            json={"duration_hours": 0}
        )
        
        # Should return 422 validation error
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        print(f"✓ Duration = 0 correctly rejected with 422")

    def test_create_share_without_auth_fails(self):
        """Test that creating share without auth fails"""
        response = requests.post(
            f"{BASE_URL}/api/location/share",
            json={"duration_hours": 4}
        )
        
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}: {response.text}"
        print(f"✓ Create share without auth correctly returns {response.status_code}")

    def test_create_and_verify_share_link(self, auth_headers):
        """Test full flow: create share → verify via public endpoint"""
        # Step 1: Create share link
        create_response = requests.post(
            f"{BASE_URL}/api/location/share",
            headers=auth_headers,
            json={"duration_hours": 4, "share_name": "Verification Test"}
        )
        
        assert create_response.status_code == 200, f"Create failed: {create_response.text}"
        created_data = create_response.json()
        token = created_data["token"]
        
        # Step 2: Verify via public endpoint (no auth)
        track_response = requests.get(f"{BASE_URL}/api/location/track/{token}")
        
        assert track_response.status_code == 200, f"Track failed: {track_response.text}"
        
        track_data = track_response.json()
        assert track_data["status"] == "live", f"Expected live status, got: {track_data['status']}"
        assert track_data["share_name"] == "Verification Test", f"Share name mismatch: {track_data['share_name']}"
        
        print(f"✓ Full flow verified: create → track works correctly")
        return token

    def test_deactivate_share_link(self, auth_headers):
        """Test deactivating a share link"""
        # Create a new share link to deactivate
        create_response = requests.post(
            f"{BASE_URL}/api/location/share",
            headers=auth_headers,
            json={"duration_hours": 4, "share_name": "To Deactivate"}
        )
        
        assert create_response.status_code == 200
        token = create_response.json()["token"]
        
        # Deactivate the link
        delete_response = requests.delete(
            f"{BASE_URL}/api/location/share/{token}",
            headers=auth_headers
        )
        
        assert delete_response.status_code == 200, f"Expected 200, got {delete_response.status_code}: {delete_response.text}"
        
        delete_data = delete_response.json()
        assert delete_data.get("status") == "deactivated", f"Expected deactivated status: {delete_data}"
        assert delete_data.get("token") == token
        
        # Verify the link now returns "inactive" status
        track_response = requests.get(f"{BASE_URL}/api/location/track/{token}")
        assert track_response.status_code == 200
        
        track_data = track_response.json()
        assert track_data["status"] == "inactive", f"Expected inactive status, got: {track_data['status']}"
        
        print(f"✓ Share link deactivated successfully")

    def test_deactivate_invalid_token(self, auth_headers):
        """Test deactivating a non-existent token"""
        response = requests.delete(
            f"{BASE_URL}/api/location/share/invalid_token_xyz",
            headers=auth_headers
        )
        
        assert response.status_code == 404, f"Expected 404, got {response.status_code}: {response.text}"
        print(f"✓ Deactivating invalid token correctly returns 404")

    def test_deactivate_without_auth_fails(self):
        """Test that deactivating without auth fails"""
        response = requests.delete(
            f"{BASE_URL}/api/location/share/{EXISTING_TOKEN}"
        )
        
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print(f"✓ Deactivate without auth correctly returns {response.status_code}")


class TestTrackingDataFields:
    """Tests for validating tracking data field values"""

    def test_risk_level_values(self):
        """Test that risk_level is a valid value"""
        response = requests.get(f"{BASE_URL}/api/location/track/{EXISTING_TOKEN}")
        
        assert response.status_code == 200
        data = response.json()
        
        valid_risk_levels = ["SAFE", "LOW", "MODERATE", "HIGH", "CRITICAL"]
        assert data["risk_level"] in valid_risk_levels, f"Invalid risk_level: {data['risk_level']}"
        print(f"✓ Risk level is valid: {data['risk_level']}")

    def test_expires_at_is_iso_format(self):
        """Test that expires_at is in ISO format"""
        response = requests.get(f"{BASE_URL}/api/location/track/{EXISTING_TOKEN}")
        
        assert response.status_code == 200
        data = response.json()
        
        from datetime import datetime
        try:
            # Parse ISO format datetime
            datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
            print(f"✓ expires_at is valid ISO format: {data['expires_at']}")
        except ValueError as e:
            pytest.fail(f"Invalid ISO format for expires_at: {data['expires_at']} - {e}")

    def test_numeric_fields_are_correct_type(self):
        """Test that numeric fields are correct types"""
        response = requests.get(f"{BASE_URL}/api/location/track/{EXISTING_TOKEN}")
        
        assert response.status_code == 200
        data = response.json()
        
        # These fields should be numbers or null
        if data["lat"] is not None:
            assert isinstance(data["lat"], (int, float)), f"lat should be number: {type(data['lat'])}"
        if data["lng"] is not None:
            assert isinstance(data["lng"], (int, float)), f"lng should be number: {type(data['lng'])}"
        if data["risk_score"] is not None:
            assert isinstance(data["risk_score"], (int, float)), f"risk_score should be number: {type(data['risk_score'])}"
        if data["total_distance_m"] is not None:
            assert isinstance(data["total_distance_m"], (int, float)), f"total_distance_m should be number: {type(data['total_distance_m'])}"
        
        assert isinstance(data["session_active"], bool), f"session_active should be bool: {type(data['session_active'])}"
        
        print(f"✓ All numeric fields have correct types")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
