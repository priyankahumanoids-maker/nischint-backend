"""
Test file for Shake-to-SOS feature
Tests the backend SOS endpoint with trigger_type='shake'
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestShakeSOSAPI:
    """Test SOS endpoint with shake trigger type"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup auth token for all tests"""
        self.token = None
        login_response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "nischint4parents@gmail.com", "password": "secret123"}
        )
        if login_response.status_code == 200:
            self.token = login_response.json().get("access_token")
        yield
    
    def get_auth_headers(self):
        """Return auth headers"""
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
    
    def test_sos_shake_trigger_success(self):
        """Test SOS endpoint accepts trigger_type='shake' and returns guardian notifications"""
        if not self.token:
            pytest.skip("Authentication failed")
        
        response = requests.post(
            f"{BASE_URL}/api/safety-events/sos",
            headers=self.get_auth_headers(),
            json={
                "trigger_type": "shake",
                "lat": 12.9716,
                "lng": 77.5946,
                "message": "Shake-triggered Emergency SOS"
            }
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Verify required fields
        assert "sos_id" in data, "Response should contain sos_id"
        assert "trigger_type" in data, "Response should contain trigger_type"
        assert data["trigger_type"] == "shake", f"Expected trigger_type='shake', got '{data['trigger_type']}'"
        assert "guardian_notifications" in data, "Response should contain guardian_notifications"
        assert "guardians_notified" in data, "Response should contain guardians_notified"
        
        print(f"SOS triggered successfully with ID: {data['sos_id']}")
        print(f"Guardians notified: {data['guardians_notified']}")
    
    def test_sos_shake_trigger_with_coordinates(self):
        """Test SOS shake trigger includes location data correctly"""
        if not self.token:
            pytest.skip("Authentication failed")
        
        lat = 28.6139
        lng = 77.2090
        
        response = requests.post(
            f"{BASE_URL}/api/safety-events/sos",
            headers=self.get_auth_headers(),
            json={
                "trigger_type": "shake",
                "lat": lat,
                "lng": lng
            }
        )
        
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("lat") == lat, "Latitude should match input"
        assert data.get("lng") == lng, "Longitude should match input"
    
    def test_sos_trigger_types_validation(self):
        """Test that all valid trigger types are accepted"""
        if not self.token:
            pytest.skip("Authentication failed")
        
        valid_types = ["manual", "voice", "button", "shake", "auto"]
        
        for trigger_type in valid_types:
            response = requests.post(
                f"{BASE_URL}/api/safety-events/sos",
                headers=self.get_auth_headers(),
                json={
                    "trigger_type": trigger_type,
                    "lat": 12.9716,
                    "lng": 77.5946
                }
            )
            
            assert response.status_code == 200, f"trigger_type='{trigger_type}' should be accepted, got {response.status_code}"
            data = response.json()
            assert data["trigger_type"] == trigger_type
            print(f"✓ trigger_type='{trigger_type}' accepted")
    
    def test_sos_invalid_trigger_type_rejected(self):
        """Test that invalid trigger types are rejected"""
        if not self.token:
            pytest.skip("Authentication failed")
        
        response = requests.post(
            f"{BASE_URL}/api/safety-events/sos",
            headers=self.get_auth_headers(),
            json={
                "trigger_type": "invalid_type",
                "lat": 12.9716,
                "lng": 77.5946
            }
        )
        
        # Should return validation error (422)
        assert response.status_code == 422, f"Invalid trigger_type should return 422, got {response.status_code}"
    
    def test_sos_shake_returns_guardian_details(self):
        """Test that shake SOS returns guardian notification details"""
        if not self.token:
            pytest.skip("Authentication failed")
        
        response = requests.post(
            f"{BASE_URL}/api/safety-events/sos",
            headers=self.get_auth_headers(),
            json={
                "trigger_type": "shake",
                "message": "Test shake SOS for guardian notification test"
            }
        )
        
        assert response.status_code == 200
        
        data = response.json()
        guardian_notifications = data.get("guardian_notifications", [])
        
        # If guardians are configured, verify notification structure
        if guardian_notifications:
            for notification in guardian_notifications:
                assert "name" in notification, "Guardian notification should have name"
                assert "relationship" in notification, "Guardian notification should have relationship"
                assert "channels" in notification, "Guardian notification should have channels"
                print(f"✓ Guardian '{notification['name']}' ({notification['relationship']}) will be notified via {notification['channels']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
