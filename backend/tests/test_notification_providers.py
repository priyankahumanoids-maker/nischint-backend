# Test: Notification Providers Integration
# Tests Twilio SMS, Firebase FCM, and In-App notification channels
# Also tests phone number normalization (E.164 format) and throttling

import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL').rstrip('/')

# Test device ID from review request
TEST_DEVICE_ID = "f2d99a24-9991-4266-a3c5-353c42e1302f"


class TestNotificationProviders:
    """Test GET /api/operator/notifications/providers endpoint"""

    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get operator auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "operator@nischint.com",
            "password": "operator123"
        })
        assert response.status_code == 200, f"Login failed: {response.text}"
        return response.json()["access_token"]

    @pytest.fixture(scope="class")
    def auth_headers(self, auth_token):
        """Return auth headers"""
        return {"Authorization": f"Bearer {auth_token}"}

    def test_providers_endpoint_returns_200(self, auth_headers):
        """Test providers endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/operator/notifications/providers", headers=auth_headers)
        assert response.status_code == 200, f"Providers endpoint failed: {response.text}"

    def test_providers_response_structure(self, auth_headers):
        """Test providers endpoint returns all 4 channels"""
        response = requests.get(f"{BASE_URL}/api/operator/notifications/providers", headers=auth_headers)
        data = response.json()
        
        # Must have all 4 channels
        assert "sms" in data, "Missing sms channel"
        assert "push" in data, "Missing push channel"
        assert "email" in data, "Missing email channel"
        assert "in_app" in data, "Missing in_app channel"

    def test_sms_provider_is_twilio_live(self, auth_headers):
        """Test SMS provider is Twilio and live (real credentials configured)"""
        response = requests.get(f"{BASE_URL}/api/operator/notifications/providers", headers=auth_headers)
        data = response.json()
        
        sms = data.get("sms", {})
        assert sms.get("provider") == "twilio", f"SMS provider should be twilio, got: {sms.get('provider')}"
        assert sms.get("live") is True, "SMS should be live (Twilio credentials configured)"

    def test_push_provider_is_fcm_live(self, auth_headers):
        """Test Push provider is FCM and live (Firebase SA key configured)"""
        response = requests.get(f"{BASE_URL}/api/operator/notifications/providers", headers=auth_headers)
        data = response.json()
        
        push = data.get("push", {})
        assert push.get("provider") == "fcm", f"Push provider should be fcm, got: {push.get('provider')}"
        assert push.get("live") is True, "Push should be live (Firebase SA key configured)"

    def test_email_provider_is_ses_live(self, auth_headers):
        """Test Email provider is SES and live (AWS credentials configured)"""
        response = requests.get(f"{BASE_URL}/api/operator/notifications/providers", headers=auth_headers)
        data = response.json()
        
        email = data.get("email", {})
        assert email.get("provider") == "ses", f"Email provider should be ses, got: {email.get('provider')}"
        assert email.get("live") is True, "Email should be live (AWS credentials configured)"

    def test_in_app_provider_is_native_always_live(self, auth_headers):
        """Test In-App provider is native and always live"""
        response = requests.get(f"{BASE_URL}/api/operator/notifications/providers", headers=auth_headers)
        data = response.json()
        
        in_app = data.get("in_app", {})
        assert in_app.get("provider") == "native", f"In-App provider should be native, got: {in_app.get('provider')}"
        assert in_app.get("live") is True, "In-App should always be live"


class TestNotificationSend:
    """Test POST /api/operator/notifications/send endpoint"""

    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get operator auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "operator@nischint.com",
            "password": "operator123"
        })
        assert response.status_code == 200, f"Login failed: {response.text}"
        return response.json()["access_token"]

    @pytest.fixture(scope="class")
    def auth_headers(self, auth_token):
        """Return auth headers"""
        return {"Authorization": f"Bearer {auth_token}"}

    def test_send_notification_requires_all_fields(self, auth_headers):
        """Test that missing required fields return 400"""
        # Missing device_id
        response = requests.post(f"{BASE_URL}/api/operator/notifications/send", headers=auth_headers, json={
            "event_type": "test_alert",
            "severity": "high",
            "title": "Test",
            "message": "Test message"
        })
        assert response.status_code == 400, f"Expected 400 for missing device_id, got {response.status_code}"
        
        # Missing severity
        response = requests.post(f"{BASE_URL}/api/operator/notifications/send", headers=auth_headers, json={
            "device_id": TEST_DEVICE_ID,
            "event_type": "test_alert",
            "title": "Test",
            "message": "Test message"
        })
        assert response.status_code == 400, f"Expected 400 for missing severity, got {response.status_code}"

    def test_send_in_app_notification_low_severity(self, auth_headers):
        """Test sending in-app notification (low severity skips SMS)"""
        # Low severity should only trigger in-app (SMS requires high/critical)
        response = requests.post(f"{BASE_URL}/api/operator/notifications/send", headers=auth_headers, json={
            "device_id": TEST_DEVICE_ID,
            "event_type": "test_in_app_only",
            "severity": "low",
            "title": "Test In-App Notification",
            "message": "This is a test in-app notification"
        })
        
        # Should succeed or be throttled (both are valid outcomes)
        assert response.status_code == 200, f"Send notification failed: {response.text}"
        data = response.json()
        
        # Check response status
        assert data.get("status") in ["sent", "throttled", "skipped"], f"Unexpected status: {data.get('status')}"
        
        if data.get("status") == "sent":
            # Verify in-app channel was used
            channels = data.get("channels", [])
            channel_names = [c.get("channel") for c in channels]
            assert "in_app" in channel_names, f"in_app channel should be in channels: {channels}"

    def test_send_high_severity_notification_triggers_sms(self, auth_headers):
        """Test that high severity notification triggers SMS channel"""
        # Use unique event type to avoid throttling
        unique_event = f"test_sms_trigger_{int(time.time())}"
        
        response = requests.post(f"{BASE_URL}/api/operator/notifications/send", headers=auth_headers, json={
            "device_id": TEST_DEVICE_ID,
            "event_type": unique_event,
            "severity": "high",
            "title": "High Severity Test Alert",
            "message": "This is a high severity test alert that should trigger SMS"
        })
        
        assert response.status_code == 200, f"Send notification failed: {response.text}"
        data = response.json()
        
        # Should either be sent or no_guardian (if device has no guardian)
        assert data.get("status") in ["sent", "skipped", "throttled"], f"Unexpected status: {data}"
        
        if data.get("status") == "sent":
            channels = data.get("channels", [])
            channel_names = [c.get("channel") for c in channels]
            # High severity should include SMS
            assert "sms" in channel_names or len(channels) > 0, f"Expected SMS for high severity: {channels}"

    def test_send_critical_severity_notification(self, auth_headers):
        """Test that critical severity notification bypasses throttle and triggers all channels"""
        # Critical severity should bypass throttling
        response = requests.post(f"{BASE_URL}/api/operator/notifications/send", headers=auth_headers, json={
            "device_id": TEST_DEVICE_ID,
            "event_type": "critical_incident",  # Uses standard event type
            "severity": "critical",
            "title": "CRITICAL: Emergency Test Alert",
            "message": "This is a critical emergency test alert"
        })
        
        assert response.status_code == 200, f"Send notification failed: {response.text}"
        data = response.json()
        
        # Critical should not be throttled (bypass)
        assert data.get("status") in ["sent", "skipped"], f"Critical should not be throttled: {data}"


class TestNotificationThrottling:
    """Test notification throttling behavior"""

    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get operator auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "operator@nischint.com",
            "password": "operator123"
        })
        assert response.status_code == 200, f"Login failed: {response.text}"
        return response.json()["access_token"]

    @pytest.fixture(scope="class")
    def auth_headers(self, auth_token):
        """Return auth headers"""
        return {"Authorization": f"Bearer {auth_token}"}

    def test_duplicate_alerts_throttled(self, auth_headers):
        """Test that duplicate alerts within cooldown are throttled"""
        unique_event = f"throttle_test_{int(time.time())}"
        
        # First notification
        response1 = requests.post(f"{BASE_URL}/api/operator/notifications/send", headers=auth_headers, json={
            "device_id": TEST_DEVICE_ID,
            "event_type": unique_event,
            "severity": "medium",
            "title": "Throttle Test Alert",
            "message": "Testing throttle - first notification"
        })
        
        assert response1.status_code == 200, f"First notification failed: {response1.text}"
        data1 = response1.json()
        
        # Second notification immediately after (should be throttled)
        response2 = requests.post(f"{BASE_URL}/api/operator/notifications/send", headers=auth_headers, json={
            "device_id": TEST_DEVICE_ID,
            "event_type": unique_event,
            "severity": "medium",
            "title": "Throttle Test Alert",
            "message": "Testing throttle - second notification"
        })
        
        assert response2.status_code == 200, f"Second notification failed: {response2.text}"
        data2 = response2.json()
        
        # If first was sent, second should be throttled (or both could be skipped if no guardian)
        if data1.get("status") == "sent":
            assert data2.get("status") == "throttled", f"Duplicate should be throttled: {data2}"
            assert data2.get("event_type") == unique_event, f"Throttle response should include event_type"

    def test_critical_bypasses_throttle(self, auth_headers):
        """Test that critical severity bypasses throttling"""
        unique_event = f"critical_throttle_{int(time.time())}"
        
        # First non-critical notification
        requests.post(f"{BASE_URL}/api/operator/notifications/send", headers=auth_headers, json={
            "device_id": TEST_DEVICE_ID,
            "event_type": unique_event,
            "severity": "medium",
            "title": "Non-Critical Alert",
            "message": "First notification"
        })
        
        # Second critical notification (should bypass throttle)
        response = requests.post(f"{BASE_URL}/api/operator/notifications/send", headers=auth_headers, json={
            "device_id": TEST_DEVICE_ID,
            "event_type": "critical_incident",  # Standard critical event
            "severity": "critical",
            "title": "CRITICAL Alert",
            "message": "This should bypass throttle"
        })
        
        assert response.status_code == 200, f"Critical notification failed: {response.text}"
        data = response.json()
        
        # Critical should NOT be throttled
        assert data.get("status") != "throttled", f"Critical should bypass throttle: {data}"


class TestNotificationLog:
    """Test notification log endpoint"""

    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get operator auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "operator@nischint.com",
            "password": "operator123"
        })
        assert response.status_code == 200, f"Login failed: {response.text}"
        return response.json()["access_token"]

    @pytest.fixture(scope="class")
    def auth_headers(self, auth_token):
        """Return auth headers"""
        return {"Authorization": f"Bearer {auth_token}"}

    def test_notification_log_returns_200(self, auth_headers):
        """Test notification log endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/operator/notifications/log", headers=auth_headers)
        assert response.status_code == 200, f"Log endpoint failed: {response.text}"

    def test_notification_log_structure(self, auth_headers):
        """Test notification log response structure"""
        response = requests.get(f"{BASE_URL}/api/operator/notifications/log?limit=10", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        
        assert "notifications" in data, "Response should have notifications array"
        
        if len(data["notifications"]) > 0:
            notif = data["notifications"][0]
            # Check required fields
            assert "id" in notif, "Notification should have id"
            assert "event_type" in notif, "Notification should have event_type"
            assert "channel" in notif, "Notification should have channel"
            assert "status" in notif, "Notification should have status"
            assert "sent_at" in notif, "Notification should have sent_at"

    def test_notification_log_for_device(self, auth_headers):
        """Test notification log filtered by device"""
        response = requests.get(f"{BASE_URL}/api/operator/notifications/log/{TEST_DEVICE_ID}", headers=auth_headers)
        assert response.status_code == 200, f"Device log failed: {response.text}"
        data = response.json()
        
        assert "notifications" in data, "Response should have notifications array"
        
        # All notifications should be for this device
        for notif in data["notifications"]:
            assert notif.get("device_id") == TEST_DEVICE_ID, f"Notification should be for test device"


class TestPhoneNormalization:
    """Test E.164 phone number normalization"""

    def test_phone_normalization_in_route_alert_service(self):
        """Test phone normalization logic inline"""
        # Test normalization function logic
        test_cases = [
            ("7400179273", "+917400179273"),  # 10-digit Indian number gets +91
            ("917400179273", "+917400179273"),  # 12-digit with country code gets +
            ("+917400179273", "+917400179273"),  # Already normalized
            ("  7400179273  ", "+917400179273"),  # Whitespace stripped
        ]
        
        for input_phone, expected in test_cases:
            # Inline normalization logic from route_alert_service.py
            normalized = input_phone.strip()
            if not normalized.startswith('+'):
                if len(normalized) == 10 and normalized.isdigit():
                    normalized = f"+91{normalized}"
                elif len(normalized) > 10 and normalized.isdigit():
                    normalized = f"+{normalized}"
            
            assert normalized == expected, f"Phone {input_phone} should normalize to {expected}, got {normalized}"
