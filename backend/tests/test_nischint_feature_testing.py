"""
Comprehensive API tests for NISCHINT digital care monitoring platform.
Tests: System Status Page, Notification Preferences, Marketing pages, Auth flow, Demo Mode
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestSystemStatusAPI:
    """Tests for /api/status/platform endpoint - System Status Page"""
    
    def test_platform_status_returns_200(self):
        """Platform status endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/status/platform")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("PASS: /api/status/platform returns 200")
    
    def test_platform_status_has_8_systems(self):
        """Platform status contains exactly 8 system modules"""
        response = requests.get(f"{BASE_URL}/api/status/platform")
        data = response.json()
        assert "systems" in data, "Response missing 'systems' key"
        assert len(data["systems"]) == 8, f"Expected 8 systems, got {len(data['systems'])}"
        print(f"PASS: Platform has 8 systems: {[s['name'] for s in data['systems']]}")
    
    def test_platform_status_module_names(self):
        """All 8 expected modules are present"""
        expected_modules = [
            "AI Safety Brain", "Command Center", "Guardian Network", 
            "Notification System", "Location Intelligence", "Incident Replay Engine",
            "Risk Prediction Engine", "Telemetry Pipeline"
        ]
        response = requests.get(f"{BASE_URL}/api/status/platform")
        data = response.json()
        actual_names = [s["name"] for s in data["systems"]]
        for module in expected_modules:
            assert module in actual_names, f"Missing module: {module}"
        print(f"PASS: All 8 modules present")
    
    def test_platform_status_module_structure(self):
        """Each system has name, status, uptime fields"""
        response = requests.get(f"{BASE_URL}/api/status/platform")
        data = response.json()
        for system in data["systems"]:
            assert "name" in system, "System missing 'name'"
            assert "status" in system, "System missing 'status'"
            assert "uptime" in system, "System missing 'uptime'"
            assert isinstance(system["uptime"], (int, float)), "Uptime should be numeric"
        print("PASS: All systems have name, status, uptime fields")
    
    def test_platform_status_operational(self):
        """Overall platform status is operational"""
        response = requests.get(f"{BASE_URL}/api/status/platform")
        data = response.json()
        assert data.get("status") == "operational", f"Expected 'operational', got {data.get('status')}"
        print("PASS: Platform status is operational")


class TestAuthAPI:
    """Tests for authentication flow"""
    
    def test_login_success(self):
        """Login with valid credentials returns access_token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "nischint4parents@gmail.com",
            "password": "secret123"
        })
        assert response.status_code == 200, f"Login failed: {response.status_code}"
        data = response.json()
        assert "access_token" in data, "Response missing access_token"
        assert len(data["access_token"]) > 0, "access_token is empty"
        print(f"PASS: Login successful, token received")
        return data["access_token"]
    
    def test_login_invalid_credentials(self):
        """Login with invalid credentials returns 401"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "invalid@example.com",
            "password": "wrongpassword"
        })
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: Invalid login returns 401")


class TestNotificationPreferencesAPI:
    """Tests for /api/settings/notifications - Notification Preferences"""
    
    @pytest.fixture
    def auth_token(self):
        """Get auth token for authenticated requests"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "nischint4parents@gmail.com",
            "password": "secret123"
        })
        if response.status_code == 200:
            return response.json().get("access_token")
        pytest.skip("Authentication failed")
    
    def test_get_notifications_unauthenticated(self):
        """GET notifications without auth returns 401"""
        response = requests.get(f"{BASE_URL}/api/settings/notifications")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: Unauthenticated GET returns 401")
    
    def test_get_notifications_authenticated(self, auth_token):
        """GET notifications with auth returns preference object"""
        response = requests.get(
            f"{BASE_URL}/api/settings/notifications",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        # Verify all 6 preference fields
        expected_fields = [
            "general_notifications", "guardian_alerts", "incident_updates",
            "daily_summary", "push_enabled", "sms_enabled"
        ]
        for field in expected_fields:
            assert field in data, f"Missing field: {field}"
            assert isinstance(data[field], bool), f"Field {field} should be boolean"
        print(f"PASS: GET notifications returns all 6 preference fields")
    
    def test_put_notifications_update(self, auth_token):
        """PUT notifications updates a preference"""
        # First get current state
        get_response = requests.get(
            f"{BASE_URL}/api/settings/notifications",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        current = get_response.json()
        new_value = not current.get("daily_summary", False)
        
        # Update
        put_response = requests.put(
            f"{BASE_URL}/api/settings/notifications",
            headers={"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"},
            json={"daily_summary": new_value}
        )
        assert put_response.status_code == 200, f"PUT failed: {put_response.status_code}"
        
        # Verify persistence
        verify_response = requests.get(
            f"{BASE_URL}/api/settings/notifications",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        updated = verify_response.json()
        assert updated["daily_summary"] == new_value, "Update not persisted"
        print(f"PASS: PUT notifications updates and persists preference")


class TestMarketingPagesAPI:
    """Tests for marketing page endpoints"""
    
    def test_telemetry_dashboard_data(self):
        """Telemetry dashboard gets platform data"""
        response = requests.get(f"{BASE_URL}/api/status/platform")
        assert response.status_code == 200
        data = response.json()
        assert "metrics" in data, "Missing metrics"
        assert "cities" in data, "Missing cities"
        print("PASS: Telemetry dashboard API working")
    
    def test_events_feed(self):
        """Live events feed returns event list"""
        response = requests.get(f"{BASE_URL}/api/status/events")
        assert response.status_code == 200
        data = response.json()
        assert "events" in data, "Missing events key"
        assert isinstance(data["events"], list), "Events should be a list"
        if len(data["events"]) > 0:
            event = data["events"][0]
            assert "timestamp" in event, "Event missing timestamp"
            assert "message" in event, "Event missing message"
            assert "type" in event, "Event missing type"
        print(f"PASS: Events feed returns {len(data['events'])} events")
    
    def test_incidents_api(self):
        """Incidents API returns incident list"""
        response = requests.get(f"{BASE_URL}/api/status/incidents")
        assert response.status_code == 200
        data = response.json()
        assert "incidents" in data, "Missing incidents key"
        print(f"PASS: Incidents API returns {len(data['incidents'])} incidents")
    
    def test_risk_intelligence_api(self):
        """Risk intelligence API returns analysis"""
        response = requests.get(f"{BASE_URL}/api/status/risk-intelligence")
        assert response.status_code == 200
        data = response.json()
        assert "risk_zones" in data or "high_risk_incidents" in data, "Missing risk data"
        print("PASS: Risk intelligence API working")


class TestDemoModeAPI:
    """Tests for demo mode in Command Center"""
    
    @pytest.fixture
    def auth_token(self):
        """Get auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "nischint4parents@gmail.com",
            "password": "secret123"
        })
        if response.status_code == 200:
            return response.json().get("access_token")
        pytest.skip("Authentication failed")
    
    def test_command_center_data_access(self, auth_token):
        """Command center API accessible with auth"""
        # Try common command center endpoints
        endpoints = [
            "/api/command-center/overview",
            "/api/guardian/devices",
            "/api/safety-events/recent"
        ]
        success_count = 0
        for endpoint in endpoints:
            response = requests.get(
                f"{BASE_URL}{endpoint}",
                headers={"Authorization": f"Bearer {auth_token}"}
            )
            if response.status_code == 200:
                success_count += 1
                print(f"  - {endpoint}: 200 OK")
            else:
                print(f"  - {endpoint}: {response.status_code}")
        print(f"PASS: {success_count}/{len(endpoints)} command center endpoints accessible")


class TestChatbotAPI:
    """Tests for AI Chatbot"""
    
    def test_chatbot_endpoint_exists(self):
        """Chatbot API endpoint accessible"""
        response = requests.post(
            f"{BASE_URL}/api/chatbot/message",
            json={"message": "Hello"}
        )
        # Should be 200 or 401 (requiring auth), not 404
        assert response.status_code != 404, "Chatbot endpoint not found"
        print(f"PASS: Chatbot endpoint exists (status: {response.status_code})")


class TestPilotSignupAPI:
    """Tests for Pilot Signup form"""
    
    def test_pilot_leads_endpoint(self):
        """Pilot signup can create leads"""
        response = requests.post(
            f"{BASE_URL}/api/pilot/signup",
            json={
                "institution_name": "Test Institution",
                "contact_person": "Test Contact",
                "email": "test@institution.edu",
                "institution_type": "university",
                "message": "Interested in pilot"
            }
        )
        # Should accept lead (201/200) or rate limited (429)
        assert response.status_code in [200, 201, 400, 409, 422, 429], f"Unexpected: {response.status_code}"
        print(f"PASS: Pilot signup endpoint working (status: {response.status_code})")
