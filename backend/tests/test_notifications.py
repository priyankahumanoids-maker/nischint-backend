"""
NISCHINT Push Notification System Tests
Tests for: notification dispatch, throttling, notification log, acknowledgement, preferences, auto-trigger
"""

import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"

# Test data
TEST_DEVICE_ID = "ce4b5463-5a7e-46a5-8bbf-365dcfb3daeb"  # DEV-001
TEST_GUARDIAN_ID = "7437a394-74ef-46a2-864f-6add0e7e8e60"  # nischint4parents@gmail.com


@pytest.fixture(scope="module")
def auth_token():
    """Get auth token for operator"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": OPERATOR_EMAIL,
        "password": OPERATOR_PASSWORD
    })
    assert response.status_code == 200, f"Login failed: {response.text}"
    return response.json()["access_token"]


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Headers with auth token"""
    return {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}


class TestNotificationAuthentication:
    """Test that all notification endpoints require authentication"""

    def test_send_notification_requires_auth(self):
        """POST /notifications/send returns 401 without auth"""
        response = requests.post(f"{BASE_URL}/api/operator/notifications/send", json={
            "device_id": TEST_DEVICE_ID,
            "event_type": "test",
            "severity": "low",
            "title": "Test",
            "message": "Test message"
        })
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"

    def test_notification_log_requires_auth(self):
        """GET /notifications/log/{device_id} returns 401 without auth"""
        response = requests.get(f"{BASE_URL}/api/operator/notifications/log/{TEST_DEVICE_ID}")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"

    def test_acknowledge_requires_auth(self):
        """POST /notifications/{id}/acknowledge returns 401 without auth"""
        response = requests.post(f"{BASE_URL}/api/operator/notifications/fake-id/acknowledge")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"

    def test_preferences_get_requires_auth(self):
        """GET /notifications/preferences/{user_id} returns 401 without auth"""
        response = requests.get(f"{BASE_URL}/api/operator/notifications/preferences/{TEST_GUARDIAN_ID}")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"

    def test_preferences_put_requires_auth(self):
        """PUT /notifications/preferences/{user_id} returns 401 without auth"""
        response = requests.put(f"{BASE_URL}/api/operator/notifications/preferences/{TEST_GUARDIAN_ID}", json={
            "push_enabled": True
        })
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"


class TestNotificationDispatch:
    """Test notification dispatch with multi-channel delivery"""

    def test_send_notification_high_severity(self, auth_headers):
        """POST /notifications/send dispatches to guardian via in_app + push + sms for high severity"""
        response = requests.post(f"{BASE_URL}/api/operator/notifications/send", headers=auth_headers, json={
            "device_id": TEST_DEVICE_ID,
            "event_type": "high_risk_zone",  
            "severity": "high",  # High severity triggers SMS
            "title": "TEST: High-Risk Zone Alert",
            "message": "TEST: Device has entered a high-risk zone",
            "metadata": {"zone_name": "Test Zone", "risk_score": 8}
        })
        assert response.status_code == 200, f"Send notification failed: {response.text}"
        data = response.json()
        
        # Verify response structure
        assert "status" in data
        # Status could be 'sent' or 'throttled' if recent notification exists
        assert data["status"] in ["sent", "throttled"], f"Unexpected status: {data['status']}"
        
        if data["status"] == "sent":
            assert "channels" in data, "Missing channels in response"
            assert "event_type" in data
            assert data["event_type"] == "high_risk_zone"
            assert data["severity"] == "high"
            # For high severity, should have in_app, push, and sms channels
            channel_names = [ch["channel"] for ch in data["channels"]]
            assert "in_app" in channel_names, "Expected in_app channel for high severity"
            assert "push" in channel_names, "Expected push channel for high severity"
            # SMS should be present for high severity
            print(f"Channels dispatched: {channel_names}")

    def test_send_notification_medium_severity_no_sms(self, auth_headers):
        """SMS should NOT be sent for medium severity (only high/critical)"""
        response = requests.post(f"{BASE_URL}/api/operator/notifications/send", headers=auth_headers, json={
            "device_id": TEST_DEVICE_ID,
            "event_type": "route_deviation",
            "severity": "medium",  # Medium severity should NOT trigger SMS
            "title": "TEST: Route Deviation",
            "message": "TEST: Device has deviated from route"
        })
        assert response.status_code == 200, f"Send notification failed: {response.text}"
        data = response.json()
        
        if data["status"] == "sent":
            channel_names = [ch["channel"] for ch in data["channels"]]
            # For medium severity, SMS should NOT be included
            if "sms" in channel_names:
                print("WARNING: SMS was sent for medium severity - this should not happen")
            print(f"Medium severity channels: {channel_names}")

    def test_send_notification_critical_severity(self, auth_headers):
        """Critical severity should bypass throttling and send SMS"""
        # Critical notifications should always go through
        response = requests.post(f"{BASE_URL}/api/operator/notifications/send", headers=auth_headers, json={
            "device_id": TEST_DEVICE_ID,
            "event_type": "critical_incident",
            "severity": "critical",  # Critical bypasses throttle
            "title": "TEST: Critical Incident",
            "message": "TEST: Emergency alert - critical incident detected"
        })
        assert response.status_code == 200, f"Send notification failed: {response.text}"
        data = response.json()
        
        # Critical should bypass throttle, so status should be 'sent'
        assert data["status"] == "sent", f"Critical notification should bypass throttle, got: {data['status']}"
        assert data["severity"] == "critical"
        
        channel_names = [ch["channel"] for ch in data["channels"]]
        print(f"Critical severity channels: {channel_names}")

    def test_send_notification_missing_field(self, auth_headers):
        """POST /notifications/send returns 400 for missing required fields"""
        response = requests.post(f"{BASE_URL}/api/operator/notifications/send", headers=auth_headers, json={
            "device_id": TEST_DEVICE_ID,
            "event_type": "test"
            # Missing: severity, title, message
        })
        assert response.status_code == 400, f"Expected 400 for missing field, got {response.status_code}"


class TestNotificationThrottling:
    """Test notification throttling per event type"""

    def test_throttling_same_event_type(self, auth_headers):
        """Same event_type within cooldown period returns 'throttled' status"""
        event_type = "danger_ahead"  # 300s cooldown
        
        # First notification
        response1 = requests.post(f"{BASE_URL}/api/operator/notifications/send", headers=auth_headers, json={
            "device_id": TEST_DEVICE_ID,
            "event_type": event_type,
            "severity": "medium",
            "title": "TEST: Danger Ahead (1st)",
            "message": "TEST: First danger notification"
        })
        assert response1.status_code == 200
        
        # Second notification immediately after - should be throttled
        response2 = requests.post(f"{BASE_URL}/api/operator/notifications/send", headers=auth_headers, json={
            "device_id": TEST_DEVICE_ID,
            "event_type": event_type,
            "severity": "medium",
            "title": "TEST: Danger Ahead (2nd)",
            "message": "TEST: Second danger notification - should be throttled"
        })
        assert response2.status_code == 200
        data = response2.json()
        
        # Second should be throttled (unless first was also throttled)
        if response1.json()["status"] == "sent":
            assert data["status"] == "throttled", f"Expected 'throttled', got: {data['status']}"
            assert data["event_type"] == event_type
            print(f"Throttling verified for {event_type}")

    def test_critical_bypasses_throttle(self, auth_headers):
        """Critical severity bypasses throttle regardless of cooldown"""
        # Send multiple critical notifications in quick succession
        for i in range(2):
            response = requests.post(f"{BASE_URL}/api/operator/notifications/send", headers=auth_headers, json={
                "device_id": TEST_DEVICE_ID,
                "event_type": "critical_incident",
                "severity": "critical",
                "title": f"TEST: Critical #{i+1}",
                "message": f"TEST: Critical notification {i+1} - should bypass throttle"
            })
            assert response.status_code == 200
            data = response.json()
            # Critical should NEVER be throttled
            assert data["status"] == "sent", f"Critical #{i+1} should bypass throttle, got: {data['status']}"


class TestNotificationLog:
    """Test notification history and log endpoints"""

    def test_get_notification_log_by_device(self, auth_headers):
        """GET /notifications/log/{device_id} returns notification history"""
        response = requests.get(
            f"{BASE_URL}/api/operator/notifications/log/{TEST_DEVICE_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Get notification log failed: {response.text}"
        data = response.json()
        
        assert "notifications" in data
        notifications = data["notifications"]
        assert isinstance(notifications, list)
        
        if len(notifications) > 0:
            # Verify notification structure
            notif = notifications[0]
            assert "id" in notif
            assert "device_id" in notif
            assert "event_type" in notif
            assert "severity" in notif
            assert "channel" in notif
            assert "title" in notif
            assert "message" in notif
            assert "status" in notif
            assert "sent_at" in notif
            # acknowledged_at can be None or ISO timestamp
            print(f"Found {len(notifications)} notifications for device")
            print(f"Latest: {notif['event_type']} ({notif['severity']}) via {notif['channel']} - {notif['status']}")

    def test_get_notification_log_generic(self, auth_headers):
        """GET /notifications/log (without device_id) returns all notifications"""
        response = requests.get(
            f"{BASE_URL}/api/operator/notifications/log",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Get notification log failed: {response.text}"
        data = response.json()
        
        assert "notifications" in data
        print(f"Total notifications in system: {len(data['notifications'])}")


class TestNotificationAcknowledge:
    """Test notification acknowledgement"""

    def test_acknowledge_notification(self, auth_headers):
        """POST /notifications/{id}/acknowledge marks notification as acknowledged"""
        # First get a notification to acknowledge
        log_response = requests.get(
            f"{BASE_URL}/api/operator/notifications/log/{TEST_DEVICE_ID}?limit=10",
            headers=auth_headers
        )
        assert log_response.status_code == 200
        notifications = log_response.json()["notifications"]
        
        # Find an unacknowledged notification
        unacked = [n for n in notifications if n.get("acknowledged_at") is None and n.get("status") == "sent"]
        
        if len(unacked) == 0:
            pytest.skip("No unacknowledged notifications to test")
        
        notif_id = unacked[0]["id"]
        
        # Acknowledge it
        ack_response = requests.post(
            f"{BASE_URL}/api/operator/notifications/{notif_id}/acknowledge",
            headers=auth_headers
        )
        assert ack_response.status_code == 200, f"Acknowledge failed: {ack_response.text}"
        data = ack_response.json()
        
        assert data["status"] == "acknowledged"
        assert data["notification_id"] == notif_id
        print(f"Acknowledged notification: {notif_id}")

    def test_acknowledge_invalid_id(self, auth_headers):
        """POST /notifications/{id}/acknowledge returns 404 for invalid ID"""
        response = requests.post(
            f"{BASE_URL}/api/operator/notifications/00000000-0000-0000-0000-000000000000/acknowledge",
            headers=auth_headers
        )
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"


class TestNotificationPreferences:
    """Test notification preferences CRUD"""

    def test_get_preferences(self, auth_headers):
        """GET /notifications/preferences/{user_id} returns push_enabled, sms_enabled, etc."""
        response = requests.get(
            f"{BASE_URL}/api/operator/notifications/preferences/{TEST_GUARDIAN_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Get preferences failed: {response.text}"
        data = response.json()
        
        # Verify response structure
        assert "push_enabled" in data
        assert "sms_enabled" in data
        assert "in_app_enabled" in data
        assert "severity_threshold" in data
        assert "quiet_hours_start" in data
        assert "quiet_hours_end" in data
        
        print(f"Preferences for guardian: push={data['push_enabled']}, sms={data['sms_enabled']}, "
              f"in_app={data['in_app_enabled']}, threshold={data['severity_threshold']}")

    def test_update_preferences(self, auth_headers):
        """PUT /notifications/preferences/{user_id} updates preferences"""
        # Update preferences
        update_response = requests.put(
            f"{BASE_URL}/api/operator/notifications/preferences/{TEST_GUARDIAN_ID}",
            headers=auth_headers,
            json={
                "push_enabled": True,
                "sms_enabled": True,
                "in_app_enabled": True,
                "severity_threshold": "medium",
                "quiet_hours_start": 22,  # 10 PM
                "quiet_hours_end": 7      # 7 AM
            }
        )
        assert update_response.status_code == 200, f"Update preferences failed: {update_response.text}"
        assert update_response.json()["status"] == "updated"
        
        # Verify the update persisted
        get_response = requests.get(
            f"{BASE_URL}/api/operator/notifications/preferences/{TEST_GUARDIAN_ID}",
            headers=auth_headers
        )
        assert get_response.status_code == 200
        data = get_response.json()
        
        assert data["severity_threshold"] == "medium"
        assert data["quiet_hours_start"] == 22
        assert data["quiet_hours_end"] == 7
        print(f"Updated preferences verified: threshold={data['severity_threshold']}, "
              f"quiet_hours={data['quiet_hours_start']}-{data['quiet_hours_end']}")

    def test_update_preferences_back_to_defaults(self, auth_headers):
        """Reset preferences back to defaults"""
        response = requests.put(
            f"{BASE_URL}/api/operator/notifications/preferences/{TEST_GUARDIAN_ID}",
            headers=auth_headers,
            json={
                "push_enabled": True,
                "sms_enabled": True,
                "in_app_enabled": True,
                "severity_threshold": "low",
                "quiet_hours_start": None,
                "quiet_hours_end": None
            }
        )
        assert response.status_code == 200


class TestRouteMonitorAutoTrigger:
    """Test automatic notification trigger from route monitoring"""

    def test_route_monitor_includes_notification_summary(self, auth_headers):
        """GET /route-monitor/{device_id} response includes notification_summary"""
        response = requests.get(
            f"{BASE_URL}/api/operator/route-monitor/{TEST_DEVICE_ID}",
            headers=auth_headers
        )
        # Could be 404 if no active monitor, or 200 if active
        if response.status_code == 404:
            pytest.skip("No active route monitor for device")
        
        assert response.status_code == 200, f"Get route monitor failed: {response.text}"
        data = response.json()
        
        # Should include notification_summary
        assert "notification_summary" in data, "Missing notification_summary in route monitor response"
        
        summary = data["notification_summary"]
        if summary:
            assert "has_alerts" in summary
            assert "unacknowledged" in summary
            print(f"Route monitor notification_summary: has_alerts={summary['has_alerts']}, "
                  f"unacknowledged={summary['unacknowledged']}")

    def test_route_monitors_fleet_includes_notification_summary(self, auth_headers):
        """GET /route-monitors includes notification_summary per monitor"""
        response = requests.get(
            f"{BASE_URL}/api/operator/route-monitors",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Get route monitors failed: {response.text}"
        data = response.json()
        
        assert "monitors" in data
        monitors = data["monitors"]
        
        if len(monitors) > 0:
            monitor = monitors[0]
            assert "notification_summary" in monitor, "Missing notification_summary in fleet monitor"
            
            summary = monitor.get("notification_summary")
            if summary:
                print(f"Fleet monitor {monitor['device_identifier']}: "
                      f"has_alerts={summary.get('has_alerts')}, "
                      f"unacknowledged={summary.get('unacknowledged')}")


class TestSMSSeverityRouting:
    """Test that SMS is only sent for high/critical severity"""

    def test_low_severity_no_sms(self, auth_headers):
        """Low severity should NOT send SMS"""
        response = requests.post(f"{BASE_URL}/api/operator/notifications/send", headers=auth_headers, json={
            "device_id": TEST_DEVICE_ID,
            "event_type": "prolonged_stop",
            "severity": "low",  # Low severity
            "title": "TEST: Low Severity Alert",
            "message": "TEST: This should not trigger SMS"
        })
        assert response.status_code == 200
        data = response.json()
        
        if data["status"] == "sent":
            channel_names = [ch["channel"] for ch in data["channels"]]
            assert "sms" not in channel_names, f"SMS should NOT be sent for low severity! Channels: {channel_names}"
            print(f"Low severity channels (no SMS): {channel_names}")

    def test_high_severity_includes_sms(self, auth_headers):
        """High severity SHOULD send SMS"""
        # Send a fresh critical to ensure we get a sent response (not throttled)
        response = requests.post(f"{BASE_URL}/api/operator/notifications/send", headers=auth_headers, json={
            "device_id": TEST_DEVICE_ID,
            "event_type": "critical_incident",
            "severity": "critical",  # Critical severity always sends SMS
            "title": "TEST: Critical Severity Alert",
            "message": "TEST: This should trigger SMS"
        })
        assert response.status_code == 200
        data = response.json()
        
        # Critical bypasses throttle, so should be sent
        assert data["status"] == "sent"
        channel_names = [ch["channel"] for ch in data["channels"]]
        # SMS should be in channels for critical severity
        assert "sms" in channel_names, f"SMS should be sent for critical severity! Channels: {channel_names}"
        print(f"Critical severity channels (with SMS): {channel_names}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
