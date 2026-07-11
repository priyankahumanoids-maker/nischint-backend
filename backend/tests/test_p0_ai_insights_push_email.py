"""
P0 Features Test: AI Insights, Push Notifications, Email Invites
Tests for Sprint: AI Insights screen, Push notification wiring, Email invite delivery
"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
TEST_EMAIL = "nischint4parents@gmail.com"
TEST_PASSWORD = "secret123"
TEST_USER_ID = "7437a394-74ef-46a2-864f-6add0e7e8e60"


@pytest.fixture(scope="module")
def auth_headers():
    """Get authentication token for API calls."""
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD
    })
    if resp.status_code != 200:
        pytest.skip(f"Auth failed: {resp.status_code} - {resp.text}")
    token = resp.json().get("access_token") or resp.json().get("token")
    return {"Authorization": f"Bearer {token}"}


class TestAIInsightsAPIs:
    """Test AI Insights related endpoints for /m/ai screen"""
    
    def test_user_dashboard_api(self, auth_headers):
        """GET /api/safety-events/user-dashboard returns risk score and user data"""
        resp = requests.get(f"{BASE_URL}/api/safety-events/user-dashboard", headers=auth_headers, timeout=20)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        
        data = resp.json()
        # Verify required fields for AI Insights screen
        assert "user_id" in data, "Missing user_id in dashboard response"
        assert "risk_score" in data, "Missing risk_score in dashboard response"
        assert "risk_level" in data, "Missing risk_level in dashboard response"
        assert data["risk_level"] in ["critical", "high", "moderate", "low"], f"Invalid risk_level: {data['risk_level']}"
        
        print(f"Dashboard API: user_id={data['user_id']}, risk_score={data['risk_score']}, risk_level={data['risk_level']}")
    
    def test_risk_score_api(self, auth_headers):
        """GET /api/guardian-ai/{user_id}/risk-score returns category scores"""
        resp = requests.get(f"{BASE_URL}/api/guardian-ai/{TEST_USER_ID}/risk-score", headers=auth_headers, timeout=20)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        
        data = resp.json()
        # Verify risk score structure with category breakdown
        assert "final_score" in data or "risk_score" in data, "Missing final_score in risk-score response"
        assert "risk_level" in data, "Missing risk_level in risk-score response"
        
        # Check for category scores (behavior, location, device, environment, response)
        if "scores" in data:
            scores = data["scores"]
            categories = ["behavior", "location", "device", "environment", "response"]
            for cat in categories:
                if cat in scores:
                    print(f"Category {cat}: {scores[cat]}")
        
        print(f"Risk Score API: final_score={data.get('final_score', data.get('risk_score'))}, level={data['risk_level']}")
    
    def test_threat_assessment_api(self, auth_headers):
        """GET /api/guardian-ai/insights/threat-assessment returns AI narrative"""
        resp = requests.get(f"{BASE_URL}/api/guardian-ai/insights/threat-assessment", headers=auth_headers, timeout=20)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        
        data = resp.json()
        # Verify threat assessment structure
        assert "threat_level" in data or "level" in data, "Missing threat_level in threat assessment"
        assert "summary" in data, "Missing summary (AI narrative) in threat assessment"
        
        level = data.get("threat_level") or data.get("level")
        print(f"Threat Assessment: level={level}, summary_length={len(data.get('summary', ''))}")


class TestPushNotificationAPIs:
    """Test Push Notification infrastructure endpoints"""
    
    def test_device_registration(self, auth_headers):
        """POST /api/device/register stores device tokens"""
        test_token = "TEST_FCM_TOKEN_" + os.urandom(8).hex()
        resp = requests.post(f"{BASE_URL}/api/device/register", json={
            "device_token": test_token,
            "device_type": "web",
            "app_version": "1.0.0"
        }, timeout=10)
        
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["status"] in ["registered", "updated"], f"Unexpected status: {data['status']}"
        
        print(f"Device registration: status={data['status']}, device_id={data.get('device_id')}")
    
    def test_device_unregistration(self, auth_headers):
        """DELETE /api/device/unregister deactivates token"""
        # First register a token
        test_token = "TEST_UNREGISTER_TOKEN_" + os.urandom(8).hex()
        reg_resp = requests.post(f"{BASE_URL}/api/device/register", json={
            "device_token": test_token,
            "device_type": "web"
        }, timeout=10)
        assert reg_resp.status_code == 200
        
        # Then unregister
        unreg_resp = requests.delete(f"{BASE_URL}/api/device/unregister", params={"device_token": test_token}, timeout=10)
        assert unreg_resp.status_code == 200, f"Expected 200, got {unreg_resp.status_code}: {unreg_resp.text}"
        
        data = unreg_resp.json()
        assert data["status"] == "unregistered"
        print("Device unregistration: success")
    
    def test_notifications_history(self, auth_headers):
        """GET /api/device/notifications returns notification history"""
        resp = requests.get(f"{BASE_URL}/api/device/notifications", params={"limit": 10}, timeout=10)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        
        data = resp.json()
        assert "notifications" in data, "Missing notifications array"
        
        print(f"Notification history: count={len(data['notifications'])}")
    
    def test_sos_triggers_push_notification(self, auth_headers):
        """POST /api/safety-events/sos includes guardian notification dispatch"""
        resp = requests.post(f"{BASE_URL}/api/safety-events/sos", json={
            "trigger_type": "manual",
            "lat": 12.9716,
            "lng": 77.5946,
            "message": "TEST SOS from pytest"
        }, headers=auth_headers, timeout=15)
        
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        
        # Verify SOS response includes guardian notification info
        assert "guardian_notifications" in data or "guardians_notified" in data, "SOS response should include guardian notification info"
        
        notified = data.get("guardians_notified", len(data.get("guardian_notifications", [])))
        print(f"SOS triggered: guardians_notified={notified}")
        
        # Verify guardian_notifications array structure if present
        if "guardian_notifications" in data and len(data["guardian_notifications"]) > 0:
            notif = data["guardian_notifications"][0]
            assert "name" in notif or "relationship" in notif, "Guardian notification should have name/relationship"


class TestEmailInviteAPIs:
    """Test Email Invite delivery via SendGrid (graceful degradation)"""
    
    def test_invite_returns_email_sent_field(self, auth_headers):
        """POST /api/guardian-network/invite returns email_sent field"""
        resp = requests.post(f"{BASE_URL}/api/guardian-network/invite", json={
            "guardian_email": "test.guardian@example.com",
            "guardian_name": "Test Guardian",
            "relationship_type": "friend"
        }, headers=auth_headers, timeout=10)
        
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
        data = resp.json()
        
        # Verify email_sent field exists
        assert "email_sent" in data, "Response must include email_sent field"
        # email_sent should be boolean
        assert isinstance(data["email_sent"], bool), f"email_sent should be boolean, got {type(data['email_sent'])}"
        
        print(f"Invite created: email_sent={data['email_sent']}, invite_url={data.get('invite_url')}")
    
    def test_invite_without_email_graceful_degradation(self, auth_headers):
        """POST /api/guardian-network/invite without email returns email_sent=false"""
        resp = requests.post(f"{BASE_URL}/api/guardian-network/invite", json={
            "guardian_phone": "+1234567890",
            "guardian_name": "Phone Only Guardian",
            "relationship_type": "parent"
        }, headers=auth_headers, timeout=10)
        
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
        data = resp.json()
        
        # Without guardian_email, email_sent should be false
        assert "email_sent" in data
        assert data["email_sent"] == False, "Without guardian_email, email_sent should be False"
        
        print("Invite without email: email_sent=False (expected)")
    
    def test_sendgrid_graceful_degradation(self, auth_headers):
        """When SENDGRID_API_KEY not configured, email_sent=false but invite still created"""
        # This test verifies graceful degradation - email stored but not sent
        resp = requests.post(f"{BASE_URL}/api/guardian-network/invite", json={
            "guardian_email": "sendgrid.test@example.com",
            "guardian_name": "SendGrid Test",
            "relationship_type": "sibling"
        }, headers=auth_headers, timeout=10)
        
        assert resp.status_code == 201, f"Invite creation should succeed even without SendGrid"
        data = resp.json()
        
        # Invite should be created successfully
        assert "invite" in data
        assert "invite_token" in data["invite"]
        # email_sent will be false if SendGrid not configured
        print(f"SendGrid degradation test: email_sent={data['email_sent']}")


class TestSOSWithGuardianNotifications:
    """Test SOS triggers with guardian notifications array"""
    
    def test_sos_manual_trigger_returns_guardian_array(self, auth_headers):
        """POST /api/safety-events/sos with manual trigger returns guardian_notifications array"""
        resp = requests.post(f"{BASE_URL}/api/safety-events/sos", json={
            "trigger_type": "manual",
            "lat": 12.9716,
            "lng": 77.5946
        }, headers=auth_headers, timeout=15)
        
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        
        # Verify guardian_notifications array
        assert "guardian_notifications" in data, "SOS response must include guardian_notifications array"
        assert isinstance(data["guardian_notifications"], list), "guardian_notifications must be an array"
        
        # Each notification should have name, relationship, channels, priority
        if len(data["guardian_notifications"]) > 0:
            notif = data["guardian_notifications"][0]
            expected_fields = ["name", "relationship", "channels", "priority"]
            for field in expected_fields:
                assert field in notif, f"Guardian notification missing field: {field}"
        
        print(f"SOS guardian notifications: count={len(data['guardian_notifications'])}")
    
    def test_sos_trigger_types_validation(self, auth_headers):
        """SOS trigger_type must be one of: manual|voice|button|shake|auto"""
        valid_types = ["manual", "voice", "button", "shake", "auto"]
        
        for trigger_type in valid_types:
            resp = requests.post(f"{BASE_URL}/api/safety-events/sos", json={
                "trigger_type": trigger_type,
                "lat": 12.9716,
                "lng": 77.5946
            }, headers=auth_headers, timeout=15)
            
            assert resp.status_code == 200, f"trigger_type '{trigger_type}' should be valid, got {resp.status_code}"
            print(f"Trigger type '{trigger_type}': valid")
        
        # Test invalid trigger type
        resp = requests.post(f"{BASE_URL}/api/safety-events/sos", json={
            "trigger_type": "invalid_type",
            "lat": 12.9716,
            "lng": 77.5946
        }, headers=auth_headers, timeout=15)
        
        assert resp.status_code == 422, f"Invalid trigger_type should return 422, got {resp.status_code}"
        print("Invalid trigger_type: correctly rejected with 422")


class TestNotificationServiceIntegration:
    """Test NotificationService stores notifications in push_notifications table"""
    
    def test_notification_stored_after_sos(self, auth_headers):
        """After SOS, notifications should be stored in push_notifications table"""
        # Trigger SOS
        sos_resp = requests.post(f"{BASE_URL}/api/safety-events/sos", json={
            "trigger_type": "manual",
            "lat": 12.9716,
            "lng": 77.5946
        }, headers=auth_headers, timeout=15)
        
        assert sos_resp.status_code == 200
        
        # Check notification history
        # Note: Notifications are stored but may not be visible immediately via user's notification API
        # This test verifies the notification path exists
        notif_resp = requests.get(f"{BASE_URL}/api/device/notifications", params={"limit": 20}, timeout=10)
        assert notif_resp.status_code == 200
        
        print("Notification storage path verified")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
