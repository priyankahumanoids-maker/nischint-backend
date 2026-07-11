"""
Mobile PWA API Tests - Sprint 1 MVP
Tests all mobile-ready endpoints for the Nischint Mobile App

Endpoints tested:
- GET /api/safety-events/user-dashboard - Home screen data
- POST /api/safety-events/sos - SOS trigger
- POST /api/safety-events/fake-call - Fake call trigger
- POST /api/safety-events/start-session - Start tracking session
- GET /api/safety-events/session-status - Session status
- POST /api/safety-events/end-session - End session
- POST /api/safety-events/safe-route - Route safety analysis
- GET /api/safety-events/guardian-alerts - Alerts feed
- GET /api/guardian-network/ - Guardian list
- GET /api/guardian-network/emergency-contacts - Emergency contacts
"""

import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestMobilePWAAuth:
    """Test login and token retrieval"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get auth token for subsequent tests"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "nischint4parents@gmail.com", "password": "secret123"}
        )
        assert response.status_code == 200, f"Login failed: {response.text}"
        data = response.json()
        assert "access_token" in data, "No access_token in response"
        return data["access_token"]
    
    def test_login_success(self):
        """Test login returns 200 and token"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "nischint4parents@gmail.com", "password": "secret123"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        print(f"PASS: Login successful, token received")


class TestMobileUserDashboard:
    """Test /api/safety-events/user-dashboard endpoint"""
    
    @pytest.fixture(scope="class")
    def auth_header(self):
        """Get auth header"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "nischint4parents@gmail.com", "password": "secret123"}
        )
        return {"Authorization": f"Bearer {response.json()['access_token']}"}
    
    def test_user_dashboard_returns_200(self, auth_header):
        """Test user-dashboard endpoint returns 200"""
        response = requests.get(
            f"{BASE_URL}/api/safety-events/user-dashboard",
            headers=auth_header
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print(f"PASS: user-dashboard returns 200")
    
    def test_user_dashboard_has_required_fields(self, auth_header):
        """Test user-dashboard returns all required fields for Mobile Home"""
        response = requests.get(
            f"{BASE_URL}/api/safety-events/user-dashboard",
            headers=auth_header
        )
        data = response.json()
        
        # Required fields for Mobile Home screen
        required_fields = [
            "user_id", "risk_score", "risk_level", "session_active",
            "guardian_count", "emergency_contact_count"
        ]
        
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        
        # Type validations
        assert isinstance(data["risk_score"], (int, float)), "risk_score should be numeric"
        assert data["risk_level"] in ["low", "moderate", "high", "critical"], f"Invalid risk_level: {data['risk_level']}"
        assert isinstance(data["session_active"], bool), "session_active should be boolean"
        assert isinstance(data["guardian_count"], int), "guardian_count should be int"
        
        print(f"PASS: user-dashboard has all required fields")
        print(f"  risk_score={data['risk_score']}, risk_level={data['risk_level']}")
        print(f"  guardian_count={data['guardian_count']}, session_active={data['session_active']}")


class TestMobileSOS:
    """Test /api/safety-events/sos endpoint"""
    
    @pytest.fixture(scope="class")
    def auth_header(self):
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "nischint4parents@gmail.com", "password": "secret123"}
        )
        return {"Authorization": f"Bearer {response.json()['access_token']}"}
    
    def test_sos_manual_trigger(self, auth_header):
        """Test SOS manual trigger returns 200"""
        response = requests.post(
            f"{BASE_URL}/api/safety-events/sos",
            headers=auth_header,
            json={
                "trigger_type": "manual",
                "lat": 28.6139,
                "lng": 77.2090,
                "message": "TEST SOS - Please ignore"
            }
        )
        assert response.status_code == 200, f"SOS failed: {response.text}"
        data = response.json()
        
        # Check response structure
        assert "guardian_notifications" in data, "Missing guardian_notifications"
        assert "guardians_notified" in data, "Missing guardians_notified count"
        assert isinstance(data["guardians_notified"], int)
        
        print(f"PASS: SOS trigger successful, notified {data['guardians_notified']} guardians")


class TestMobileFakeCall:
    """Test /api/safety-events/fake-call endpoint"""
    
    @pytest.fixture(scope="class")
    def auth_header(self):
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "nischint4parents@gmail.com", "password": "secret123"}
        )
        return {"Authorization": f"Bearer {response.json()['access_token']}"}
    
    def test_fake_call_trigger(self, auth_header):
        """Test fake-call trigger returns 200"""
        response = requests.post(
            f"{BASE_URL}/api/safety-events/fake-call",
            headers=auth_header,
            json={
                "caller_name": "Mom",
                "delay_seconds": 3
            }
        )
        assert response.status_code == 200, f"Fake call failed: {response.text}"
        print(f"PASS: Fake call trigger successful")
    
    def test_fake_call_presets(self, auth_header):
        """Test fake-call with different presets"""
        presets = ["Mom", "Dad", "Boss", "Partner", "Friend"]
        for preset in presets:
            response = requests.post(
                f"{BASE_URL}/api/safety-events/fake-call",
                headers=auth_header,
                json={"caller_name": preset, "delay_seconds": 0}
            )
            assert response.status_code == 200, f"Failed for preset {preset}"
        print(f"PASS: All 5 presets work (Mom, Dad, Boss, Partner, Friend)")


class TestMobileSession:
    """Test session lifecycle endpoints"""
    
    @pytest.fixture(scope="class")
    def auth_header(self):
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "nischint4parents@gmail.com", "password": "secret123"}
        )
        return {"Authorization": f"Bearer {response.json()['access_token']}"}
    
    def test_start_session(self, auth_header):
        """Test starting a tracking session"""
        # First end any existing session
        requests.post(
            f"{BASE_URL}/api/safety-events/end-session",
            headers=auth_header,
            json={"reason": "cancelled"}
        )
        time.sleep(0.5)
        
        # Start new session
        response = requests.post(
            f"{BASE_URL}/api/safety-events/start-session",
            headers=auth_header,
            json={
                "destination": {"name": "Test Destination", "lat": 28.6139, "lng": 77.2090},
                "mode": "walking"
            }
        )
        assert response.status_code == 200, f"Start session failed: {response.text}"
        data = response.json()
        
        assert data["status"] in ["started", "already_active"]
        assert "session_id" in data
        print(f"PASS: Session started, status={data['status']}")
    
    def test_session_status(self, auth_header):
        """Test getting session status"""
        response = requests.get(
            f"{BASE_URL}/api/safety-events/session-status",
            headers=auth_header
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "tracking_active" in data
        assert "session_id" in data
        assert "risk_level" in data
        print(f"PASS: Session status retrieved, active={data['tracking_active']}")
    
    def test_end_session(self, auth_header):
        """Test ending a session"""
        # First ensure we have an active session
        requests.post(
            f"{BASE_URL}/api/safety-events/start-session",
            headers=auth_header,
            json={"mode": "walking"}
        )
        time.sleep(0.5)
        
        response = requests.post(
            f"{BASE_URL}/api/safety-events/end-session",
            headers=auth_header,
            json={"reason": "arrived"}
        )
        # Can be 200 (ended) or 404 (no active session)
        assert response.status_code in [200, 404]
        if response.status_code == 200:
            data = response.json()
            assert data["status"] == "ended"
            print(f"PASS: Session ended successfully")
        else:
            print(f"PASS: No active session to end (expected)")


class TestMobileSafeRoute:
    """Test /api/safety-events/safe-route endpoint"""
    
    @pytest.fixture(scope="class")
    def auth_header(self):
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "nischint4parents@gmail.com", "password": "secret123"}
        )
        return {"Authorization": f"Bearer {response.json()['access_token']}"}
    
    def test_safe_route_analysis(self, auth_header):
        """Test safe-route analysis returns safety data"""
        response = requests.post(
            f"{BASE_URL}/api/safety-events/safe-route",
            headers=auth_header,
            json={
                "origin_lat": 28.6139,
                "origin_lng": 77.2090,
                "dest_lat": 28.6500,
                "dest_lng": 77.2300
            }
        )
        assert response.status_code == 200, f"Safe route failed: {response.text}"
        data = response.json()
        
        # Should have routes array
        assert "routes" in data or "safety_score" in data
        print(f"PASS: Safe route analysis returned data")


class TestMobileAlerts:
    """Test /api/safety-events/guardian-alerts endpoint"""
    
    @pytest.fixture(scope="class")
    def auth_header(self):
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "nischint4parents@gmail.com", "password": "secret123"}
        )
        return {"Authorization": f"Bearer {response.json()['access_token']}"}
    
    def test_guardian_alerts(self, auth_header):
        """Test guardian alerts returns 200"""
        response = requests.get(
            f"{BASE_URL}/api/safety-events/guardian-alerts?limit=30",
            headers=auth_header
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "alerts" in data
        assert "total" in data
        assert isinstance(data["alerts"], list)
        
        print(f"PASS: Guardian alerts returned {data['total']} alerts")


class TestMobileGuardianNetwork:
    """Test guardian network endpoints for Profile screen"""
    
    @pytest.fixture(scope="class")
    def auth_header(self):
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "nischint4parents@gmail.com", "password": "secret123"}
        )
        return {"Authorization": f"Bearer {response.json()['access_token']}"}
    
    def test_list_guardians(self, auth_header):
        """Test guardian list returns 200"""
        response = requests.get(
            f"{BASE_URL}/api/guardian-network/",
            headers=auth_header
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "guardians" in data
        print(f"PASS: Guardian list returned {len(data['guardians'])} guardians")
    
    def test_list_emergency_contacts(self, auth_header):
        """Test emergency contacts list returns 200"""
        response = requests.get(
            f"{BASE_URL}/api/guardian-network/emergency-contacts",
            headers=auth_header
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "contacts" in data
        print(f"PASS: Emergency contacts returned {len(data['contacts'])} contacts")


class TestTravelModes:
    """Test all travel modes work for session start"""
    
    @pytest.fixture(scope="class")
    def auth_header(self):
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "nischint4parents@gmail.com", "password": "secret123"}
        )
        return {"Authorization": f"Bearer {response.json()['access_token']}"}
    
    def test_all_travel_modes(self, auth_header):
        """Test walking, driving, transit modes"""
        modes = ["walking", "driving", "transit"]
        for mode in modes:
            # End any existing session
            requests.post(
                f"{BASE_URL}/api/safety-events/end-session",
                headers=auth_header,
                json={"reason": "cancelled"}
            )
            time.sleep(0.3)
            
            # Start with mode
            response = requests.post(
                f"{BASE_URL}/api/safety-events/start-session",
                headers=auth_header,
                json={"mode": mode}
            )
            assert response.status_code == 200, f"Failed for mode {mode}"
        
        print(f"PASS: All 3 travel modes work (walking, driving, transit)")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
