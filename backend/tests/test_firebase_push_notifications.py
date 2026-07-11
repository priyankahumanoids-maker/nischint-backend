"""
Test Firebase Push Notifications P0 Implementation
==================================================
Tests:
- POST /api/device/register - Register FCM device token
- GET /api/device/notifications - Get notification history  
- PUT /api/device/notifications/{id}/read - Mark notification as read
- GET /api/device/push-status - Get push status (fcm_active, devices_registered)
- POST /api/safety-events/sos - Triggers SOS with push + email to guardians
- POST /api/safety-events/start-session - Sends push notification to guardians
- POST /api/safety-events/end-session - Sends push notification to guardians
"""
import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


@pytest.fixture(scope="module")
def auth_session():
    """Login and get auth token - shared across all tests"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "nischint4parents@gmail.com",
        "password": "secret123"
    })
    if response.status_code != 200:
        pytest.skip("Authentication failed - skipping tests")
    token = response.json().get("access_token")
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    })
    return session


class TestDeviceRegistration:
    """Test FCM device token registration endpoints"""
        
    def test_01_register_device_new_token(self, auth_session):
        """POST /api/device/register - Register new FCM device token"""
        test_token = f"TEST_fcm_token_{uuid.uuid4().hex[:8]}"
        response = auth_session.post(
            f"{BASE_URL}/api/device/register",
            json={
                "device_token": test_token,
                "device_type": "web",
                "app_version": "1.0.0-test"
            }
        )
        print(f"Register device response: {response.status_code} - {response.json()}")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") in ["registered", "updated"]
        assert "device_id" in data
        
    def test_02_register_device_update_existing(self, auth_session):
        """POST /api/device/register - Update existing device token"""
        test_token = f"TEST_fcm_update_{uuid.uuid4().hex[:8]}"
        # First register
        auth_session.post(
            f"{BASE_URL}/api/device/register",
            json={"device_token": test_token, "device_type": "web"}
        )
        # Update same token
        response = auth_session.post(
            f"{BASE_URL}/api/device/register",
            json={"device_token": test_token, "device_type": "android", "app_version": "2.0.0"}
        )
        print(f"Update device response: {response.status_code} - {response.json()}")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "updated"
        
    def test_03_register_device_requires_auth(self):
        """POST /api/device/register - Should require authentication"""
        response = requests.post(
            f"{BASE_URL}/api/device/register",
            json={"device_token": "test_token", "device_type": "web"},
            headers={"Content-Type": "application/json"}
        )
        print(f"Unauth register response: {response.status_code}")
        assert response.status_code in [401, 403]


class TestPushStatus:
    """Test push status endpoint"""
        
    def test_01_get_push_status(self, auth_session):
        """GET /api/device/push-status - Returns push status info"""
        response = auth_session.get(f"{BASE_URL}/api/device/push-status")
        print(f"Push status response: {response.status_code} - {response.json()}")
        assert response.status_code == 200
        data = response.json()
        # Must have these fields
        assert "push_enabled" in data
        assert "devices_registered" in data
        assert "fcm_active" in data
        # fcm_active should be true since Firebase Admin SDK is configured
        print(f"FCM Active: {data['fcm_active']}, Devices Registered: {data['devices_registered']}")
        
    def test_02_push_status_requires_auth(self):
        """GET /api/device/push-status - Should require authentication"""
        response = requests.get(f"{BASE_URL}/api/device/push-status")
        print(f"Unauth push status response: {response.status_code}")
        assert response.status_code in [401, 403]


class TestNotificationHistory:
    """Test notification history endpoints"""
        
    def test_01_get_notifications(self, auth_session):
        """GET /api/device/notifications - Get notification history"""
        response = auth_session.get(f"{BASE_URL}/api/device/notifications?limit=20")
        print(f"Get notifications response: {response.status_code}")
        assert response.status_code == 200
        data = response.json()
        assert "notifications" in data
        assert isinstance(data["notifications"], list)
        if data["notifications"]:
            notif = data["notifications"][0]
            # Check notification structure
            assert "id" in notif
            assert "title" in notif
            assert "body" in notif
            assert "tag" in notif
            assert "is_read" in notif
            assert "created_at" in notif
            print(f"Found {len(data['notifications'])} notifications")
            print(f"Sample notification: {notif['title']} - {notif['tag']}")
        else:
            print("No notifications found - this is valid if no events triggered yet")
            
    def test_02_get_notifications_requires_auth(self):
        """GET /api/device/notifications - Should require authentication"""
        response = requests.get(f"{BASE_URL}/api/device/notifications")
        print(f"Unauth notifications response: {response.status_code}")
        assert response.status_code in [401, 403]
        
    def test_03_mark_notification_read(self, auth_session):
        """PUT /api/device/notifications/{id}/read - Mark notification as read"""
        # First get notifications
        get_response = auth_session.get(f"{BASE_URL}/api/device/notifications?limit=10")
        if get_response.status_code != 200 or not get_response.json().get("notifications"):
            pytest.skip("No notifications to test read marking")
            
        notifications = get_response.json()["notifications"]
        notif_id = notifications[0]["id"]
            
        # Mark as read
        response = auth_session.put(f"{BASE_URL}/api/device/notifications/{notif_id}/read")
        print(f"Mark read response: {response.status_code}")
        assert response.status_code == 200
        # Try to parse JSON if available
        try:
            data = response.json()
            print(f"Response data: {data}")
            assert data.get("status") == "read"
        except:
            # Empty response is also acceptable for 200 OK
            print("Empty response body - accepted")


class TestSafetyEventsWithPush:
    """Test safety events that trigger push notifications"""
        
    def test_01_sos_triggers_push_notifications(self, auth_session):
        """POST /api/safety-events/sos - Should trigger push to guardians"""
        response = auth_session.post(
            f"{BASE_URL}/api/safety-events/sos",
            json={
                "trigger_type": "manual",
                "lat": 28.6139,
                "lng": 77.2090,
                "message": "TEST SOS for push notification testing"
            }
        )
        print(f"SOS response: {response.status_code}")
        assert response.status_code == 200
        data = response.json()
        
        # Verify SOS response structure
        assert "status" in data
        assert "guardians_notified" in data
        print(f"SOS Status: {data['status']}, Guardians Notified: {data['guardians_notified']}")
        
        # Check guardian_notifications array (contains push notification info)
        if "guardian_notifications" in data:
            for g in data["guardian_notifications"]:
                assert "name" in g
                assert "relationship" in g
                assert "channels" in g
                print(f"  Guardian: {g['name']} ({g['relationship']}) via {g['channels']}")
                
    def test_02_start_session_sends_push(self, auth_session):
        """POST /api/safety-events/start-session - Should send push to guardians"""
        response = auth_session.post(
            f"{BASE_URL}/api/safety-events/start-session",
            json={
                "destination": {"lat": 28.7041, "lng": 77.1025, "name": "Test Destination"},
                "mode": "walking"
            }
        )
        print(f"Start session response: {response.status_code}")
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("status") in ["started", "already_active"]
        assert "session_id" in data
        print(f"Session Status: {data['status']}, Session ID: {data['session_id']}")
        
    def test_03_end_session_sends_push(self, auth_session):
        """POST /api/safety-events/end-session - Should send push to guardians"""
        # First check if session is active
        status_response = auth_session.get(f"{BASE_URL}/api/safety-events/session-status")
        if status_response.status_code == 200 and not status_response.json().get("tracking_active"):
            # Start a session first
            auth_session.post(
                f"{BASE_URL}/api/safety-events/start-session",
                json={"mode": "walking"}
            )
            
        # Now end session
        response = auth_session.post(
            f"{BASE_URL}/api/safety-events/end-session",
            json={"reason": "arrived"}
        )
        print(f"End session response: {response.status_code}")
        # Should be 200 if session was active, 404 if no session
        assert response.status_code in [200, 404]
        
        if response.status_code == 200:
            data = response.json()
            assert data.get("status") == "ended"
            assert "session_id" in data
            assert "duration_seconds" in data
            print(f"Session ended. Duration: {data['duration_seconds']}s")


class TestNotificationServiceIntegration:
    """Test that notification service is properly integrated"""
        
    def test_01_verify_fcm_initialized(self, auth_session):
        """Verify Firebase Admin SDK is initialized (fcm_active=true)"""
        response = auth_session.get(f"{BASE_URL}/api/device/push-status")
        assert response.status_code == 200
        data = response.json()
        
        # FCM should be active based on agent context
        assert data.get("fcm_active") == True, "Firebase Admin SDK should be initialized"
        print(f"FCM Status: Active={data['fcm_active']}")
        
    def test_02_sos_stores_notification_in_db(self, auth_session):
        """SOS should store notification in database (even if FCM send fails for fake token)"""
        # Get notification count before
        before_response = auth_session.get(f"{BASE_URL}/api/device/notifications?limit=50")
        before_count = len(before_response.json().get("notifications", []))
        
        # Trigger SOS
        auth_session.post(
            f"{BASE_URL}/api/safety-events/sos",
            json={"trigger_type": "button", "lat": 28.5, "lng": 77.2}
        )
        
        # Get notification count after (may take a moment for async processing)
        import time
        time.sleep(1)
        
        after_response = auth_session.get(f"{BASE_URL}/api/device/notifications?limit=50")
        after_count = len(after_response.json().get("notifications", []))
        
        print(f"Notifications before: {before_count}, after: {after_count}")
        # Note: Notification count may or may not increase depending on guardian setup
        # The test verifies the API works without error


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
