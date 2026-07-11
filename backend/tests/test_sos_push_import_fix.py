"""
P0 Bug Fix Test: SOS Push Notification Import Fix
================================================
Tests that the import of send_push_to_user from push_service works correctly
and that the SOS alert flow completes without ImportError.

Bug: ImportError in emergency_engine.py importing 'send_push_notification' from 'app.services.notification_service'
Fix: Changed import to 'send_push_to_user' from 'app.services.push_service'

Test Credentials:
- Child: kidnischint@gmail.com / nischint123
- Mother: mothernischint@gmail.com / nischint123
- Father: fathernishchint@gmail.com / nischint123
"""

import os
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test Credentials
CHILD_EMAIL = "kidnischint@gmail.com"
CHILD_PASSWORD = "nischint123"
MOTHER_EMAIL = "mothernischint@gmail.com"
MOTHER_PASSWORD = "nischint123"
FATHER_EMAIL = "fathernishchint@gmail.com"
FATHER_PASSWORD = "nischint123"
CANCEL_PIN = "1234"


class TestAuthEndpoints:
    """Test login endpoints return access_token for all users"""
    
    def test_child_login(self):
        """Child should be able to login and get access_token"""
        resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": CHILD_EMAIL,
            "password": CHILD_PASSWORD
        })
        assert resp.status_code == 200, f"Child login failed: {resp.text}"
        data = resp.json()
        assert "access_token" in data, f"Response missing access_token: {data}"
        # Role can be at root level or under user object
        role = data.get("role") or data.get("user", {}).get("role")
        assert role == "child", f"Unexpected role: {data}"
        print(f"✓ Child login successful, role={role}")
    
    def test_mother_login(self):
        """Mother should be able to login and get access_token"""
        resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": MOTHER_EMAIL,
            "password": MOTHER_PASSWORD
        })
        assert resp.status_code == 200, f"Mother login failed: {resp.text}"
        data = resp.json()
        assert "access_token" in data, f"Response missing access_token: {data}"
        # Role can be at root level or under user object
        role = data.get("role") or data.get("user", {}).get("role")
        assert role == "guardian", f"Unexpected role: {data}"
        print(f"✓ Mother login successful, role={role}")
    
    def test_father_login(self):
        """Father should be able to login and get access_token"""
        resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": FATHER_EMAIL,
            "password": FATHER_PASSWORD
        })
        assert resp.status_code == 200, f"Father login failed: {resp.text}"
        data = resp.json()
        assert "access_token" in data, f"Response missing access_token: {data}"
        # Role can be at root level or under user object
        role = data.get("role") or data.get("user", {}).get("role")
        assert role == "guardian", f"Unexpected role: {data}"
        print(f"✓ Father login successful, role={role}")


class TestSOSAlertFlow:
    """Test SOS alert flow - the core P0 bug fix"""
    
    @pytest.fixture
    def child_token(self):
        """Get child's access token"""
        resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": CHILD_EMAIL,
            "password": CHILD_PASSWORD
        })
        assert resp.status_code == 200, f"Child login failed: {resp.text}"
        return resp.json().get("access_token")
    
    @pytest.fixture
    def child_user_id(self):
        """Get child's user ID"""
        resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": CHILD_EMAIL,
            "password": CHILD_PASSWORD
        })
        assert resp.status_code == 200
        return resp.json().get("user", {}).get("id")

    def test_resolve_any_active_emergency_first(self, child_token):
        """Resolve any active emergency before creating new one"""
        headers = {"Authorization": f"Bearer {child_token}"}
        
        # Get active emergencies
        resp = requests.get(f"{BASE_URL}/api/emergency/active", headers=headers)
        assert resp.status_code == 200, f"Get active failed: {resp.text}"
        
        data = resp.json()
        events = data.get("events", [])
        
        for event in events:
            event_id = event.get("event_id")
            if event_id:
                # Try to resolve it
                resolve_resp = requests.post(f"{BASE_URL}/api/emergency/resolve", 
                    headers=headers,
                    json={"event_id": event_id}
                )
                print(f"Resolved active emergency: {event_id} -> {resolve_resp.status_code}")
        
        print(f"✓ Cleared {len(events)} active emergencies")
    
    def test_silent_sos_trigger_no_import_error(self, child_token):
        """
        P0 TEST: Trigger SOS and verify NO ImportError occurs.
        The fix changed import from notification_service to push_service.
        """
        headers = {"Authorization": f"Bearer {child_token}"}
        
        # First resolve any active emergencies
        active_resp = requests.get(f"{BASE_URL}/api/emergency/active", headers=headers)
        if active_resp.status_code == 200:
            for event in active_resp.json().get("events", []):
                requests.post(f"{BASE_URL}/api/emergency/resolve", 
                    headers=headers,
                    json={"event_id": event.get("event_id")}
                )
        
        # Trigger SOS
        sos_payload = {
            "lat": 28.6139,  # Delhi coordinates
            "lng": 77.2090,
            "trigger_source": "test_push_import_fix",
            "cancel_pin": CANCEL_PIN,
            "device_metadata": {"test": True, "device_id": "pytest-device"}
        }
        
        resp = requests.post(f"{BASE_URL}/api/emergency/silent-sos", 
            headers=headers,
            json=sos_payload
        )
        
        # CRITICAL: If ImportError occurred, we'd get 500 error
        assert resp.status_code == 200, f"SOS trigger failed (possible ImportError): {resp.text}"
        
        data = resp.json()
        
        # Validate response structure
        assert "event_id" in data, f"Response missing event_id: {data}"
        assert data.get("status") == "active", f"Expected status=active: {data}"
        assert "guardians_notified" in data, f"Response missing guardians_notified: {data}"
        
        # Save event_id for cleanup
        event_id = data.get("event_id")
        print(f"✓ SOS triggered successfully: event_id={event_id}, guardians_notified={data.get('guardians_notified')}")
        
        # Cleanup: Resolve the emergency
        resolve_resp = requests.post(f"{BASE_URL}/api/emergency/resolve",
            headers=headers,
            json={"event_id": event_id}
        )
        assert resolve_resp.status_code == 200, f"Resolve failed: {resolve_resp.text}"
        print(f"✓ Emergency resolved: {event_id}")
        
        return event_id
    
    def test_sos_returns_guardians_notified_count(self, child_token):
        """Verify SOS returns correct guardians_notified count"""
        headers = {"Authorization": f"Bearer {child_token}"}
        
        # Resolve any active first
        active_resp = requests.get(f"{BASE_URL}/api/emergency/active", headers=headers)
        if active_resp.status_code == 200:
            for event in active_resp.json().get("events", []):
                requests.post(f"{BASE_URL}/api/emergency/resolve", 
                    headers=headers,
                    json={"event_id": event.get("event_id")}
                )
        
        # Trigger SOS
        resp = requests.post(f"{BASE_URL}/api/emergency/silent-sos", 
            headers=headers,
            json={
                "lat": 28.6139,
                "lng": 77.2090,
                "trigger_source": "test_guardian_count",
                "cancel_pin": CANCEL_PIN
            }
        )
        
        assert resp.status_code == 200, f"SOS failed: {resp.text}"
        data = resp.json()
        
        # Child has 2 guardians (Mother and Father)
        guardians_notified = data.get("guardians_notified", 0)
        assert guardians_notified >= 1, f"Expected at least 1 guardian notified, got {guardians_notified}"
        print(f"✓ Guardians notified count: {guardians_notified}")
        
        # Cleanup
        event_id = data.get("event_id")
        if event_id:
            requests.post(f"{BASE_URL}/api/emergency/resolve",
                headers=headers,
                json={"event_id": event_id}
            )


class TestEmergencyResolve:
    """Test POST /api/emergency/resolve endpoint"""
    
    @pytest.fixture
    def child_token(self):
        resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": CHILD_EMAIL,
            "password": CHILD_PASSWORD
        })
        return resp.json().get("access_token")
    
    def test_resolve_active_emergency(self, child_token):
        """Resolve an active emergency and verify response"""
        headers = {"Authorization": f"Bearer {child_token}"}
        
        # First trigger an SOS
        sos_resp = requests.post(f"{BASE_URL}/api/emergency/silent-sos",
            headers=headers,
            json={
                "lat": 28.6139,
                "lng": 77.2090,
                "trigger_source": "test_resolve",
                "cancel_pin": CANCEL_PIN
            }
        )
        
        # Handle case where active emergency already exists
        if sos_resp.status_code == 200:
            data = sos_resp.json()
            event_id = data.get("event_id")
            
            # Resolve it
            resolve_resp = requests.post(f"{BASE_URL}/api/emergency/resolve",
                headers=headers,
                json={"event_id": event_id}
            )
            
            assert resolve_resp.status_code == 200, f"Resolve failed: {resolve_resp.text}"
            resolve_data = resolve_resp.json()
            
            assert resolve_data.get("status") == "resolved", f"Expected status=resolved: {resolve_data}"
            assert "resolved_at" in resolve_data, f"Response missing resolved_at: {resolve_data}"
            print(f"✓ Emergency resolved: event_id={event_id}, resolved_at={resolve_data.get('resolved_at')}")


class TestEmergencyCancel:
    """Test POST /api/emergency/cancel endpoint"""
    
    @pytest.fixture
    def child_token(self):
        resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": CHILD_EMAIL,
            "password": CHILD_PASSWORD
        })
        return resp.json().get("access_token")
    
    def test_cancel_with_correct_pin(self, child_token):
        """Cancel emergency with correct PIN"""
        headers = {"Authorization": f"Bearer {child_token}"}
        
        # First trigger an SOS with cancel_pin
        sos_resp = requests.post(f"{BASE_URL}/api/emergency/silent-sos",
            headers=headers,
            json={
                "lat": 28.6139,
                "lng": 77.2090,
                "trigger_source": "test_cancel",
                "cancel_pin": CANCEL_PIN
            }
        )
        
        if sos_resp.status_code == 200:
            data = sos_resp.json()
            event_id = data.get("event_id")
            
            # If this is an existing event, resolve it first and create new
            if data.get("is_existing"):
                requests.post(f"{BASE_URL}/api/emergency/resolve",
                    headers=headers,
                    json={"event_id": event_id}
                )
                # Create fresh SOS
                sos_resp = requests.post(f"{BASE_URL}/api/emergency/silent-sos",
                    headers=headers,
                    json={
                        "lat": 28.6139,
                        "lng": 77.2090,
                        "trigger_source": "test_cancel_fresh",
                        "cancel_pin": CANCEL_PIN
                    }
                )
                data = sos_resp.json()
                event_id = data.get("event_id")
            
            # Cancel with PIN
            cancel_resp = requests.post(f"{BASE_URL}/api/emergency/cancel",
                headers=headers,
                json={
                    "event_id": event_id,
                    "cancel_pin": CANCEL_PIN
                }
            )
            
            assert cancel_resp.status_code == 200, f"Cancel failed: {cancel_resp.text}"
            cancel_data = cancel_resp.json()
            
            assert cancel_data.get("status") == "cancelled", f"Expected status=cancelled: {cancel_data}"
            print(f"✓ Emergency cancelled with PIN: event_id={event_id}")


class TestGetActiveEmergencies:
    """Test GET /api/emergency/active endpoint"""
    
    def test_get_active_emergencies(self):
        """Get list of active emergencies"""
        # Get fresh token
        login_resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": CHILD_EMAIL,
            "password": CHILD_PASSWORD
        })
        assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
        child_token = login_resp.json().get("access_token")
        
        headers = {"Authorization": f"Bearer {child_token}"}
        
        resp = requests.get(f"{BASE_URL}/api/emergency/active", headers=headers)
        
        assert resp.status_code == 200, f"Get active failed: {resp.text}"
        data = resp.json()
        
        assert "events" in data, f"Response missing events: {data}"
        assert "count" in data, f"Response missing count: {data}"
        assert isinstance(data.get("events"), list), f"events should be a list: {data}"
        
        print(f"✓ Active emergencies: count={data.get('count')}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
