"""
Test suite for System Status Page and Notification Preferences API
Tests:
1. GET /api/status/platform - Platform status with systems
2. GET /api/settings/notifications - Get user notification prefs (authenticated)
3. PUT /api/settings/notifications - Update notification prefs (authenticated)
4. Verify prefs persist after update
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL').rstrip('/')


class TestPlatformStatus:
    """Platform status endpoint tests (public, no auth needed)"""
    
    def test_platform_status_returns_200(self):
        """GET /api/status/platform should return 200 OK"""
        response = requests.get(f"{BASE_URL}/api/status/platform")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("PASS: Platform status returns 200")
    
    def test_platform_status_contains_systems_array(self):
        """Response should contain systems array with 8 modules"""
        response = requests.get(f"{BASE_URL}/api/status/platform")
        data = response.json()
        
        assert "systems" in data, "Response should contain 'systems' key"
        assert isinstance(data["systems"], list), "systems should be a list"
        assert len(data["systems"]) == 8, f"Expected 8 systems, got {len(data['systems'])}"
        print(f"PASS: Platform status contains {len(data['systems'])} systems")
    
    def test_platform_status_module_names(self):
        """All 8 modules should be present with correct names"""
        expected_modules = [
            "AI Safety Brain",
            "Command Center",
            "Guardian Network",
            "Notification System",
            "Location Intelligence",
            "Incident Replay Engine",
            "Risk Prediction Engine",
            "Telemetry Pipeline"
        ]
        
        response = requests.get(f"{BASE_URL}/api/status/platform")
        data = response.json()
        
        module_names = [sys["name"] for sys in data["systems"]]
        
        for expected in expected_modules:
            assert expected in module_names, f"Module '{expected}' not found in response"
        
        print(f"PASS: All 8 expected modules found: {module_names}")
    
    def test_platform_status_module_structure(self):
        """Each system should have name, status, and uptime fields"""
        response = requests.get(f"{BASE_URL}/api/status/platform")
        data = response.json()
        
        for sys in data["systems"]:
            assert "name" in sys, f"System missing 'name': {sys}"
            assert "status" in sys, f"System missing 'status': {sys}"
            assert "uptime" in sys, f"System missing 'uptime': {sys}"
            assert sys["status"] in ["operational", "degraded", "incident", "maintenance"], \
                f"Invalid status: {sys['status']}"
        
        print("PASS: All systems have required fields (name, status, uptime)")
    
    def test_platform_status_operational(self):
        """Overall platform status should be 'operational'"""
        response = requests.get(f"{BASE_URL}/api/status/platform")
        data = response.json()
        
        assert "status" in data, "Response should have 'status' field"
        assert data["status"] == "operational", f"Expected 'operational', got {data['status']}"
        print("PASS: Platform status is operational")


class TestNotificationPreferences:
    """Notification preferences API tests (requires authentication)"""
    
    @pytest.fixture(autouse=True)
    def setup_auth(self):
        """Get auth token before each test"""
        login_response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "nischint4parents@gmail.com", "password": "secret123"}
        )
        if login_response.status_code != 200:
            pytest.skip("Could not authenticate - skipping notification tests")
        
        self.token = login_response.json().get("access_token")
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
    
    def test_get_notifications_unauthenticated_fails(self):
        """GET /api/settings/notifications without auth should return 401/403"""
        response = requests.get(f"{BASE_URL}/api/settings/notifications")
        assert response.status_code in [401, 403], \
            f"Expected 401 or 403, got {response.status_code}"
        print("PASS: Unauthenticated request properly rejected")
    
    def test_get_notifications_authenticated(self):
        """GET /api/settings/notifications with auth returns 200"""
        response = requests.get(
            f"{BASE_URL}/api/settings/notifications",
            headers=self.headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("PASS: Authenticated GET returns 200")
    
    def test_get_notifications_response_structure(self):
        """Response should contain all preference fields"""
        response = requests.get(
            f"{BASE_URL}/api/settings/notifications",
            headers=self.headers
        )
        data = response.json()
        
        expected_fields = [
            "general_notifications",
            "guardian_alerts",
            "incident_updates",
            "daily_summary",
            "push_enabled",
            "sms_enabled"
        ]
        
        for field in expected_fields:
            assert field in data, f"Missing field: {field}"
            assert isinstance(data[field], bool), f"Field {field} should be boolean"
        
        print(f"PASS: Response contains all expected fields: {list(data.keys())}")
    
    def test_put_notifications_update_single_pref(self):
        """PUT /api/settings/notifications should update a single preference"""
        # First, get current value of daily_summary
        get_response = requests.get(
            f"{BASE_URL}/api/settings/notifications",
            headers=self.headers
        )
        current_value = get_response.json().get("daily_summary")
        new_value = not current_value
        
        # Update the value
        put_response = requests.put(
            f"{BASE_URL}/api/settings/notifications",
            headers=self.headers,
            json={"daily_summary": new_value}
        )
        assert put_response.status_code == 200, f"Expected 200, got {put_response.status_code}"
        
        put_data = put_response.json()
        assert put_data.get("status") == "success", f"Expected success status, got {put_data}"
        
        print(f"PASS: PUT notification pref returns success (daily_summary: {current_value} -> {new_value})")
    
    def test_put_notifications_persists(self):
        """Updated preferences should persist on subsequent GET"""
        # Toggle push_enabled
        get_response = requests.get(
            f"{BASE_URL}/api/settings/notifications",
            headers=self.headers
        )
        current_push = get_response.json().get("push_enabled")
        new_push = not current_push
        
        # Update
        requests.put(
            f"{BASE_URL}/api/settings/notifications",
            headers=self.headers,
            json={"push_enabled": new_push}
        )
        
        # Verify persistence
        verify_response = requests.get(
            f"{BASE_URL}/api/settings/notifications",
            headers=self.headers
        )
        verify_data = verify_response.json()
        
        assert verify_data["push_enabled"] == new_push, \
            f"Expected push_enabled={new_push}, got {verify_data['push_enabled']}"
        
        # Restore original value
        requests.put(
            f"{BASE_URL}/api/settings/notifications",
            headers=self.headers,
            json={"push_enabled": current_push}
        )
        
        print(f"PASS: Preference persisted correctly (push_enabled toggled and verified)")
    
    def test_put_notifications_multiple_prefs(self):
        """PUT should update multiple preferences at once"""
        # Update multiple fields
        put_response = requests.put(
            f"{BASE_URL}/api/settings/notifications",
            headers=self.headers,
            json={
                "general_notifications": True,
                "guardian_alerts": True,
                "incident_updates": True
            }
        )
        assert put_response.status_code == 200, f"Expected 200, got {put_response.status_code}"
        
        # Verify all updated
        verify_response = requests.get(
            f"{BASE_URL}/api/settings/notifications",
            headers=self.headers
        )
        verify_data = verify_response.json()
        
        assert verify_data["general_notifications"] == True
        assert verify_data["guardian_alerts"] == True
        assert verify_data["incident_updates"] == True
        
        print("PASS: Multiple preferences updated and verified")
    
    def test_put_notifications_unauthenticated_fails(self):
        """PUT without auth should return 401/403"""
        response = requests.put(
            f"{BASE_URL}/api/settings/notifications",
            json={"daily_summary": True}
        )
        assert response.status_code in [401, 403], \
            f"Expected 401 or 403, got {response.status_code}"
        print("PASS: Unauthenticated PUT properly rejected")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
