# Fake Notification API Tests - Escape Notification Mechanism
# Tests for 7 endpoints: presets CRUD, trigger, complete, history

import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Guardian credentials
GUARDIAN_EMAIL = "nischint4parents@gmail.com"
GUARDIAN_PASSWORD = "secret123"


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token for guardian user"""
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": GUARDIAN_EMAIL, "password": GUARDIAN_PASSWORD}
    )
    assert response.status_code == 200, f"Login failed: {response.text}"
    token = response.json().get("access_token")
    assert token, "No access_token in response"
    return token


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Get auth headers for API calls"""
    return {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json"
    }


class TestAuthRequired:
    """Verify authentication is required for all endpoints"""
    
    def test_presets_requires_auth(self):
        response = requests.get(f"{BASE_URL}/api/fake-notification/presets")
        assert response.status_code == 401
    
    def test_trigger_requires_auth(self):
        response = requests.post(
            f"{BASE_URL}/api/fake-notification/trigger",
            json={"title": "Test"}
        )
        assert response.status_code == 401
    
    def test_complete_requires_auth(self):
        response = requests.post(
            f"{BASE_URL}/api/fake-notification/complete/00000000-0000-0000-0000-000000000000",
            json={"viewed": True}
        )
        assert response.status_code == 401
    
    def test_history_requires_auth(self):
        response = requests.get(f"{BASE_URL}/api/fake-notification/history")
        assert response.status_code == 401


class TestGetPresets:
    """GET /api/fake-notification/presets - List presets with auto-seeding"""
    
    def test_get_presets_returns_list(self, auth_headers):
        """Should return list of presets"""
        response = requests.get(
            f"{BASE_URL}/api/fake-notification/presets",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "presets" in data
        assert isinstance(data["presets"], list)
    
    def test_default_presets_seeded(self, auth_headers):
        """Should have 4 default presets: Work, Delivery, Security, Message"""
        response = requests.get(
            f"{BASE_URL}/api/fake-notification/presets",
            headers=auth_headers
        )
        assert response.status_code == 200
        presets = response.json()["presets"]
        
        # Check for default presets
        default_presets = [p for p in presets if p["is_default"]]
        assert len(default_presets) >= 4, "Should have at least 4 default presets"
        
        # Verify categories
        categories = {p["category"] for p in default_presets}
        assert "Work" in categories, "Missing Work category"
        assert "Delivery" in categories, "Missing Delivery category"
        assert "Security" in categories, "Missing Security category"
        assert "Message" in categories, "Missing Message category"
    
    def test_preset_structure(self, auth_headers):
        """Each preset should have required fields"""
        response = requests.get(
            f"{BASE_URL}/api/fake-notification/presets",
            headers=auth_headers
        )
        presets = response.json()["presets"]
        
        for preset in presets:
            assert "id" in preset
            assert "title" in preset
            assert "message" in preset
            assert "category" in preset
            assert "icon_style" in preset
            assert "is_default" in preset
            assert "created_at" in preset


class TestCreatePreset:
    """POST /api/fake-notification/presets - Create custom preset"""
    
    def test_create_custom_preset(self, auth_headers):
        """Should create a custom notification preset"""
        response = requests.post(
            f"{BASE_URL}/api/fake-notification/presets",
            headers=auth_headers,
            json={
                "title": "TEST_Doctor Appointment",
                "message": "Your appointment is in 15 minutes",
                "category": "Custom",
                "icon_style": "alert"
            }
        )
        assert response.status_code == 201
        
        data = response.json()
        assert data["title"] == "TEST_Doctor Appointment"
        assert data["message"] == "Your appointment is in 15 minutes"
        assert data["category"] == "Custom"
        assert data["icon_style"] == "alert"
        assert data["is_default"] is False
        assert "id" in data
        
        # Store for cleanup
        TestCreatePreset.created_preset_id = data["id"]
    
    def test_create_preset_with_auto_dismiss(self, auth_headers):
        """Should accept auto_dismiss_seconds parameter"""
        response = requests.post(
            f"{BASE_URL}/api/fake-notification/presets",
            headers=auth_headers,
            json={
                "title": "TEST_Quick Alert",
                "message": "Auto-dismiss test",
                "auto_dismiss_seconds": 10
            }
        )
        assert response.status_code == 201
        data = response.json()
        assert data["auto_dismiss_seconds"] == 10
        
        # Cleanup
        requests.delete(
            f"{BASE_URL}/api/fake-notification/presets/{data['id']}",
            headers=auth_headers
        )


class TestUpdatePreset:
    """PUT /api/fake-notification/presets/{id} - Update preset"""
    
    def test_update_preset_title(self, auth_headers):
        """Should update preset title"""
        # First create a preset
        create_response = requests.post(
            f"{BASE_URL}/api/fake-notification/presets",
            headers=auth_headers,
            json={"title": "TEST_Original Title", "message": "Test message"}
        )
        preset_id = create_response.json()["id"]
        
        # Update title
        response = requests.put(
            f"{BASE_URL}/api/fake-notification/presets/{preset_id}",
            headers=auth_headers,
            json={"title": "TEST_Updated Title"}
        )
        assert response.status_code == 200
        assert response.json()["title"] == "TEST_Updated Title"
        
        # Cleanup
        requests.delete(
            f"{BASE_URL}/api/fake-notification/presets/{preset_id}",
            headers=auth_headers
        )
    
    def test_update_nonexistent_preset(self, auth_headers):
        """Should return 404 for non-existent preset"""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = requests.put(
            f"{BASE_URL}/api/fake-notification/presets/{fake_id}",
            headers=auth_headers,
            json={"title": "New Title"}
        )
        assert response.status_code == 404


class TestDeletePreset:
    """DELETE /api/fake-notification/presets/{id} - Delete preset"""
    
    def test_delete_custom_preset(self, auth_headers):
        """Should delete non-default preset"""
        # Create a preset to delete
        create_response = requests.post(
            f"{BASE_URL}/api/fake-notification/presets",
            headers=auth_headers,
            json={"title": "TEST_To Delete", "message": "Will be deleted"}
        )
        preset_id = create_response.json()["id"]
        
        # Delete it
        response = requests.delete(
            f"{BASE_URL}/api/fake-notification/presets/{preset_id}",
            headers=auth_headers
        )
        assert response.status_code == 200
        assert response.json()["deleted"] is True
        
        # Verify it's gone
        get_response = requests.get(
            f"{BASE_URL}/api/fake-notification/presets",
            headers=auth_headers
        )
        preset_ids = [p["id"] for p in get_response.json()["presets"]]
        assert preset_id not in preset_ids
    
    def test_cannot_delete_default_preset(self, auth_headers):
        """Should not allow deleting default presets"""
        # Get a default preset ID
        response = requests.get(
            f"{BASE_URL}/api/fake-notification/presets",
            headers=auth_headers
        )
        default_presets = [p for p in response.json()["presets"] if p["is_default"]]
        
        if default_presets:
            default_id = default_presets[0]["id"]
            delete_response = requests.delete(
                f"{BASE_URL}/api/fake-notification/presets/{default_id}",
                headers=auth_headers
            )
            assert delete_response.status_code == 404
            assert "default" in delete_response.json()["detail"].lower() or "not found" in delete_response.json()["detail"].lower()


class TestTriggerNotification:
    """POST /api/fake-notification/trigger - Trigger notification"""
    
    def test_trigger_with_preset_id(self, auth_headers):
        """Should trigger notification using preset_id"""
        # Get a preset ID
        presets_response = requests.get(
            f"{BASE_URL}/api/fake-notification/presets",
            headers=auth_headers
        )
        preset_id = presets_response.json()["presets"][0]["id"]
        
        response = requests.post(
            f"{BASE_URL}/api/fake-notification/trigger",
            headers=auth_headers,
            json={
                "preset_id": preset_id,
                "delay_seconds": 0,
                "trigger_method": "pytest"
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "notification_id" in data
        assert "title" in data
        assert "message" in data
        assert "triggered_at" in data
        
        TestTriggerNotification.triggered_notif_id = data["notification_id"]
    
    def test_trigger_with_custom_title_message(self, auth_headers):
        """Should trigger notification with custom title/message"""
        response = requests.post(
            f"{BASE_URL}/api/fake-notification/trigger",
            headers=auth_headers,
            json={
                "title": "TEST_Custom Notification",
                "message": "This is a test from pytest",
                "category": "Custom",
                "delay_seconds": 5,
                "trigger_method": "pytest_custom"
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["title"] == "TEST_Custom Notification"
        assert data["message"] == "This is a test from pytest"
        assert data["delay_seconds"] == 5
        assert data["trigger_method"] == "pytest_custom"
    
    def test_trigger_returns_notification_id(self, auth_headers):
        """notification_id should be a valid UUID"""
        response = requests.post(
            f"{BASE_URL}/api/fake-notification/trigger",
            headers=auth_headers,
            json={"title": "TEST_UUID Check"}
        )
        assert response.status_code == 200
        
        notif_id = response.json()["notification_id"]
        # Validate UUID format
        uuid.UUID(notif_id)  # Raises if invalid


class TestCompleteNotification:
    """POST /api/fake-notification/complete/{id} - Complete notification"""
    
    def test_complete_with_viewed(self, auth_headers):
        """Should complete notification with viewed=true"""
        # Trigger a notification first
        trigger_response = requests.post(
            f"{BASE_URL}/api/fake-notification/trigger",
            headers=auth_headers,
            json={"title": "TEST_For Complete Viewed"}
        )
        notif_id = trigger_response.json()["notification_id"]
        
        # Complete it
        response = requests.post(
            f"{BASE_URL}/api/fake-notification/complete/{notif_id}",
            headers=auth_headers,
            json={"viewed": True, "dismissed": False, "send_alert": False}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["notification_id"] == notif_id
        assert data["status"] == "completed"
        assert data["viewed"] is True
        assert data["dismissed"] is False
        assert data["alert_sent"] is False
    
    def test_complete_with_dismiss(self, auth_headers):
        """Should complete notification with dismissed=true"""
        trigger_response = requests.post(
            f"{BASE_URL}/api/fake-notification/trigger",
            headers=auth_headers,
            json={"title": "TEST_For Complete Dismiss"}
        )
        notif_id = trigger_response.json()["notification_id"]
        
        response = requests.post(
            f"{BASE_URL}/api/fake-notification/complete/{notif_id}",
            headers=auth_headers,
            json={"viewed": False, "dismissed": True, "send_alert": False}
        )
        assert response.status_code == 200
        assert response.json()["dismissed"] is True
    
    def test_complete_with_alert(self, auth_headers):
        """Should complete notification with send_alert=true"""
        trigger_response = requests.post(
            f"{BASE_URL}/api/fake-notification/trigger",
            headers=auth_headers,
            json={"title": "TEST_For Complete Alert"}
        )
        notif_id = trigger_response.json()["notification_id"]
        
        response = requests.post(
            f"{BASE_URL}/api/fake-notification/complete/{notif_id}",
            headers=auth_headers,
            json={"viewed": True, "dismissed": False, "send_alert": True}
        )
        assert response.status_code == 200
        assert response.json()["alert_sent"] is True
    
    def test_complete_nonexistent_notification(self, auth_headers):
        """Should return 404 for non-existent notification"""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = requests.post(
            f"{BASE_URL}/api/fake-notification/complete/{fake_id}",
            headers=auth_headers,
            json={"viewed": True}
        )
        assert response.status_code == 404


class TestNotificationHistory:
    """GET /api/fake-notification/history - Get notification history"""
    
    def test_history_returns_list(self, auth_headers):
        """Should return history array with count"""
        response = requests.get(
            f"{BASE_URL}/api/fake-notification/history",
            headers=auth_headers
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "history" in data
        assert "count" in data
        assert isinstance(data["history"], list)
    
    def test_history_respects_limit(self, auth_headers):
        """Should respect limit parameter"""
        response = requests.get(
            f"{BASE_URL}/api/fake-notification/history?limit=2",
            headers=auth_headers
        )
        assert response.status_code == 200
        
        data = response.json()
        assert len(data["history"]) <= 2
    
    def test_history_sorted_by_recent(self, auth_headers):
        """Should be sorted by triggered_at DESC (most recent first)"""
        response = requests.get(
            f"{BASE_URL}/api/fake-notification/history?limit=10",
            headers=auth_headers
        )
        history = response.json()["history"]
        
        if len(history) >= 2:
            # Verify descending order
            for i in range(len(history) - 1):
                current = history[i]["triggered_at"]
                next_item = history[i + 1]["triggered_at"]
                assert current >= next_item, "History not sorted by most recent"
    
    def test_history_entry_structure(self, auth_headers):
        """Each history entry should have required fields"""
        response = requests.get(
            f"{BASE_URL}/api/fake-notification/history?limit=5",
            headers=auth_headers
        )
        history = response.json()["history"]
        
        if history:
            entry = history[0]
            assert "id" in entry
            assert "title" in entry
            assert "message" in entry
            assert "category" in entry
            assert "trigger_method" in entry
            assert "delay_seconds" in entry
            assert "status" in entry
            assert "viewed" in entry
            assert "dismissed" in entry
            assert "alert_sent" in entry
            assert "triggered_at" in entry


class TestCleanup:
    """Cleanup test data after all tests"""
    
    def test_cleanup_test_presets(self, auth_headers):
        """Remove TEST_ prefixed presets"""
        response = requests.get(
            f"{BASE_URL}/api/fake-notification/presets",
            headers=auth_headers
        )
        presets = response.json()["presets"]
        
        for preset in presets:
            if preset["title"].startswith("TEST_") and not preset["is_default"]:
                requests.delete(
                    f"{BASE_URL}/api/fake-notification/presets/{preset['id']}",
                    headers=auth_headers
                )
        
        # Verify cleanup
        response = requests.get(
            f"{BASE_URL}/api/fake-notification/presets",
            headers=auth_headers
        )
        remaining = [p for p in response.json()["presets"] if p["title"].startswith("TEST_")]
        assert len(remaining) == 0, f"Cleanup failed, remaining: {remaining}"
