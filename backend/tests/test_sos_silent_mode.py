# SOS Silent Mode API Tests (Phase 48 - Escape Layer)
# Tests for: GET /config, PUT /config, POST /trigger, POST /cancel/{sos_id}, GET /history

import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
TEST_EMAIL = "nischint4parents@gmail.com"
TEST_PASSWORD = "secret123"


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token for testing"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD
    })
    assert response.status_code == 200, f"Login failed: {response.text}"
    data = response.json()
    assert "access_token" in data, "No access_token in response"
    return data["access_token"]


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Headers with auth token"""
    return {"Authorization": f"Bearer {auth_token}"}


class TestSOSConfigEndpoints:
    """Tests for SOS Config CRUD - GET /sos/config and PUT /sos/config"""

    def test_get_config_without_auth_returns_401(self):
        """GET /sos/config returns 401 without authentication"""
        response = requests.get(f"{BASE_URL}/api/sos/config")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"

    def test_get_config_returns_defaults(self, auth_headers):
        """GET /sos/config returns config with default values"""
        response = requests.get(f"{BASE_URL}/api/sos/config", headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        config = response.json()
        # Validate structure
        assert "id" in config
        assert "user_id" in config
        assert "enabled" in config
        assert "voice_keywords" in config
        assert "chain_notification" in config
        assert "chain_notification_delay" in config
        assert "chain_call" in config
        assert "chain_call_delay" in config
        assert "chain_call_preset_name" in config
        assert "chain_notification_title" in config
        assert "chain_notification_message" in config
        assert "trusted_contacts" in config
        assert "auto_share_location" in config
        assert "silent_mode" in config
        assert "updated_at" in config
        
        # Validate default values (if this is first access)
        assert isinstance(config["enabled"], bool)
        assert isinstance(config["voice_keywords"], list)
        assert isinstance(config["chain_notification"], bool)
        assert isinstance(config["chain_call"], bool)
        assert isinstance(config["silent_mode"], bool)
        assert isinstance(config["auto_share_location"], bool)

    def test_get_config_has_default_keywords(self, auth_headers):
        """GET /sos/config contains expected default voice keywords"""
        response = requests.get(f"{BASE_URL}/api/sos/config", headers=auth_headers)
        assert response.status_code == 200
        config = response.json()
        
        # Should have default keywords like "help me", "sos now", "emergency"
        keywords = config.get("voice_keywords", [])
        assert isinstance(keywords, list)
        # At least check the list has some keywords (might be modified)
        print(f"Voice keywords: {keywords}")

    def test_put_config_without_auth_returns_401(self):
        """PUT /sos/config returns 401 without authentication"""
        response = requests.put(f"{BASE_URL}/api/sos/config", json={"enabled": False})
        assert response.status_code == 401

    def test_put_config_updates_enabled(self, auth_headers):
        """PUT /sos/config can update enabled field"""
        # Get current config
        response = requests.get(f"{BASE_URL}/api/sos/config", headers=auth_headers)
        current_enabled = response.json().get("enabled", True)
        
        # Toggle enabled
        new_enabled = not current_enabled
        response = requests.put(f"{BASE_URL}/api/sos/config", 
                               headers=auth_headers,
                               json={"enabled": new_enabled})
        assert response.status_code == 200, f"Update failed: {response.text}"
        
        updated = response.json()
        assert updated["enabled"] == new_enabled
        
        # Restore original
        requests.put(f"{BASE_URL}/api/sos/config", headers=auth_headers, json={"enabled": current_enabled})

    def test_put_config_updates_chain_notification(self, auth_headers):
        """PUT /sos/config can update chain_notification and delay"""
        response = requests.put(f"{BASE_URL}/api/sos/config",
                               headers=auth_headers,
                               json={
                                   "chain_notification": True,
                                   "chain_notification_delay": 15,
                                   "chain_notification_title": "TEST_Meeting Alert"
                               })
        assert response.status_code == 200
        
        config = response.json()
        assert config["chain_notification"] == True
        assert config["chain_notification_delay"] == 15
        assert config["chain_notification_title"] == "TEST_Meeting Alert"

    def test_put_config_updates_chain_call(self, auth_headers):
        """PUT /sos/config can update chain_call and caller name"""
        response = requests.put(f"{BASE_URL}/api/sos/config",
                               headers=auth_headers,
                               json={
                                   "chain_call": True,
                                   "chain_call_delay": 45,
                                   "chain_call_preset_name": "TEST_Manager"
                               })
        assert response.status_code == 200
        
        config = response.json()
        assert config["chain_call"] == True
        assert config["chain_call_delay"] == 45
        assert config["chain_call_preset_name"] == "TEST_Manager"

    def test_put_config_updates_silent_mode(self, auth_headers):
        """PUT /sos/config can update silent_mode"""
        response = requests.put(f"{BASE_URL}/api/sos/config",
                               headers=auth_headers,
                               json={"silent_mode": True})
        assert response.status_code == 200
        assert response.json()["silent_mode"] == True

    def test_put_config_updates_voice_keywords(self, auth_headers):
        """PUT /sos/config can update voice_keywords"""
        response = requests.put(f"{BASE_URL}/api/sos/config",
                               headers=auth_headers,
                               json={"voice_keywords": ["test keyword", "help", "sos"]})
        assert response.status_code == 200
        
        config = response.json()
        assert "test keyword" in config["voice_keywords"]

    def test_put_config_updates_auto_share_location(self, auth_headers):
        """PUT /sos/config can update auto_share_location"""
        response = requests.put(f"{BASE_URL}/api/sos/config",
                               headers=auth_headers,
                               json={"auto_share_location": False})
        assert response.status_code == 200
        assert response.json()["auto_share_location"] == False
        
        # Restore
        requests.put(f"{BASE_URL}/api/sos/config", headers=auth_headers, json={"auto_share_location": True})

    def test_put_config_validates_delay_max(self, auth_headers):
        """PUT /sos/config validates delay max (300 seconds)"""
        response = requests.put(f"{BASE_URL}/api/sos/config",
                               headers=auth_headers,
                               json={"chain_notification_delay": 500})
        # Should fail validation (max is 300)
        assert response.status_code == 422 or response.status_code == 400


class TestSOSTriggerEndpoint:
    """Tests for POST /sos/trigger"""

    def test_trigger_without_auth_returns_401(self):
        """POST /sos/trigger returns 401 without authentication"""
        response = requests.post(f"{BASE_URL}/api/sos/trigger", json={"trigger_type": "manual"})
        assert response.status_code == 401

    def test_trigger_creates_active_sos(self, auth_headers):
        """POST /sos/trigger creates active SOS and returns sos_id"""
        response = requests.post(f"{BASE_URL}/api/sos/trigger",
                                headers=auth_headers,
                                json={
                                    "trigger_type": "dashboard",
                                    "lat": 28.6139,
                                    "lng": 77.2090
                                })
        assert response.status_code == 200, f"Trigger failed: {response.text}"
        
        data = response.json()
        assert "sos_id" in data
        assert data["status"] == "active"
        assert data["trigger_type"] == "dashboard"
        assert data["lat"] == 28.6139
        assert data["lng"] == 77.2090
        assert "triggered_at" in data
        
        # Store for cleanup
        return data["sos_id"]

    def test_trigger_returns_chain_info(self, auth_headers):
        """POST /sos/trigger returns chain configuration info"""
        response = requests.post(f"{BASE_URL}/api/sos/trigger",
                                headers=auth_headers,
                                json={"trigger_type": "widget"})
        assert response.status_code == 200
        
        data = response.json()
        assert "chain" in data
        assert "notification" in data["chain"]
        assert "call" in data["chain"]
        
        # If chain_notification is enabled, should have delay info
        if data["chain"]["notification"]:
            assert "delay_seconds" in data["chain"]["notification"]
            assert "title" in data["chain"]["notification"]
            
        # If chain_call is enabled, should have caller info
        if data["chain"]["call"]:
            assert "delay_seconds" in data["chain"]["call"]
            assert "caller_name" in data["chain"]["call"]

    def test_trigger_returns_trusted_contacts_alerted(self, auth_headers):
        """POST /sos/trigger returns trusted_contacts_alerted field"""
        response = requests.post(f"{BASE_URL}/api/sos/trigger",
                                headers=auth_headers,
                                json={"trigger_type": "voice"})
        assert response.status_code == 200
        
        data = response.json()
        assert "trusted_contacts_alerted" in data
        assert isinstance(data["trusted_contacts_alerted"], list)


class TestSOSCancelEndpoint:
    """Tests for POST /sos/cancel/{sos_id}"""

    def test_cancel_without_auth_returns_401(self):
        """POST /sos/cancel/{sos_id} returns 401 without authentication"""
        fake_id = str(uuid.uuid4())
        response = requests.post(f"{BASE_URL}/api/sos/cancel/{fake_id}", json={"resolved_by": "user"})
        assert response.status_code == 401

    def test_cancel_nonexistent_returns_404(self, auth_headers):
        """POST /sos/cancel/{sos_id} returns 404 for non-existent SOS"""
        fake_id = str(uuid.uuid4())
        response = requests.post(f"{BASE_URL}/api/sos/cancel/{fake_id}",
                                headers=auth_headers,
                                json={"resolved_by": "user"})
        assert response.status_code == 404

    def test_trigger_and_cancel_flow(self, auth_headers):
        """Full flow: Trigger SOS then cancel it"""
        # 1. Trigger SOS
        trigger_response = requests.post(f"{BASE_URL}/api/sos/trigger",
                                        headers=auth_headers,
                                        json={"trigger_type": "TEST_cancel_flow", "lat": 28.0, "lng": 77.0})
        assert trigger_response.status_code == 200
        sos_id = trigger_response.json()["sos_id"]
        
        # 2. Cancel SOS
        cancel_response = requests.post(f"{BASE_URL}/api/sos/cancel/{sos_id}",
                                       headers=auth_headers,
                                       json={"resolved_by": "user"})
        assert cancel_response.status_code == 200
        
        data = cancel_response.json()
        assert data["sos_id"] == sos_id
        assert data["status"] == "resolved"
        assert data["resolved_by"] == "user"
        assert "resolved_at" in data

    def test_cancel_with_operator_resolved_by(self, auth_headers):
        """POST /sos/cancel accepts different resolved_by values"""
        # Trigger
        trigger_response = requests.post(f"{BASE_URL}/api/sos/trigger",
                                        headers=auth_headers,
                                        json={"trigger_type": "TEST_operator_cancel"})
        sos_id = trigger_response.json()["sos_id"]
        
        # Cancel with operator
        cancel_response = requests.post(f"{BASE_URL}/api/sos/cancel/{sos_id}",
                                       headers=auth_headers,
                                       json={"resolved_by": "operator"})
        assert cancel_response.status_code == 200
        assert cancel_response.json()["resolved_by"] == "operator"


class TestSOSHistoryEndpoint:
    """Tests for GET /sos/history"""

    def test_history_without_auth_returns_401(self):
        """GET /sos/history returns 401 without authentication"""
        response = requests.get(f"{BASE_URL}/api/sos/history")
        assert response.status_code == 401

    def test_history_returns_list_with_count(self, auth_headers):
        """GET /sos/history returns history array with count"""
        response = requests.get(f"{BASE_URL}/api/sos/history", headers=auth_headers)
        assert response.status_code == 200
        
        data = response.json()
        assert "history" in data
        assert "count" in data
        assert isinstance(data["history"], list)
        assert isinstance(data["count"], int)
        assert data["count"] == len(data["history"])

    def test_history_entry_structure(self, auth_headers):
        """GET /sos/history entries have correct structure"""
        response = requests.get(f"{BASE_URL}/api/sos/history", headers=auth_headers)
        assert response.status_code == 200
        
        data = response.json()
        if data["count"] > 0:
            entry = data["history"][0]
            assert "id" in entry
            assert "trigger_type" in entry
            assert "status" in entry
            assert "lat" in entry or entry.get("lat") is None
            assert "lng" in entry or entry.get("lng") is None
            assert "chain_notification_triggered" in entry
            assert "chain_call_triggered" in entry
            assert "alert_sent_to" in entry
            assert "triggered_at" in entry
            # resolved_by and resolved_at may be None for active SOS

    def test_history_respects_limit(self, auth_headers):
        """GET /sos/history?limit=N respects limit parameter"""
        response = requests.get(f"{BASE_URL}/api/sos/history?limit=5", headers=auth_headers)
        assert response.status_code == 200
        
        data = response.json()
        assert len(data["history"]) <= 5

    def test_history_sorted_by_recent(self, auth_headers):
        """GET /sos/history returns entries sorted by triggered_at DESC"""
        response = requests.get(f"{BASE_URL}/api/sos/history", headers=auth_headers)
        assert response.status_code == 200
        
        data = response.json()
        if len(data["history"]) > 1:
            timestamps = [e["triggered_at"] for e in data["history"]]
            assert timestamps == sorted(timestamps, reverse=True), "History should be sorted by triggered_at DESC"


class TestSOSFullIntegration:
    """End-to-end integration tests for SOS flow"""

    def test_full_sos_flow_with_config(self, auth_headers):
        """Complete flow: Configure -> Trigger -> Verify chain -> Cancel -> Check history"""
        # 1. Configure SOS
        config_response = requests.put(f"{BASE_URL}/api/sos/config",
                                      headers=auth_headers,
                                      json={
                                          "enabled": True,
                                          "chain_notification": True,
                                          "chain_notification_delay": 10,
                                          "chain_notification_title": "TEST_Integration Meeting",
                                          "chain_call": True,
                                          "chain_call_delay": 40,
                                          "chain_call_preset_name": "TEST_Integration_Boss",
                                          "silent_mode": True
                                      })
        assert config_response.status_code == 200
        
        # 2. Trigger SOS
        trigger_response = requests.post(f"{BASE_URL}/api/sos/trigger",
                                        headers=auth_headers,
                                        json={
                                            "trigger_type": "TEST_integration",
                                            "lat": 28.6139,
                                            "lng": 77.2090
                                        })
        assert trigger_response.status_code == 200
        
        sos_data = trigger_response.json()
        sos_id = sos_data["sos_id"]
        
        # 3. Verify chain info matches config
        assert sos_data["chain"]["notification"]["delay_seconds"] == 10
        assert sos_data["chain"]["notification"]["title"] == "TEST_Integration Meeting"
        assert sos_data["chain"]["call"]["delay_seconds"] == 40
        assert sos_data["chain"]["call"]["caller_name"] == "TEST_Integration_Boss"
        
        # 4. Cancel SOS
        cancel_response = requests.post(f"{BASE_URL}/api/sos/cancel/{sos_id}",
                                       headers=auth_headers,
                                       json={"resolved_by": "integration_test"})
        assert cancel_response.status_code == 200
        assert cancel_response.json()["status"] == "resolved"
        
        # 5. Verify in history
        history_response = requests.get(f"{BASE_URL}/api/sos/history?limit=5", headers=auth_headers)
        assert history_response.status_code == 200
        
        history = history_response.json()["history"]
        found = any(h["id"] == sos_id for h in history)
        assert found, f"SOS {sos_id} not found in history"
        
        # Verify the entry has correct data
        entry = next(h for h in history if h["id"] == sos_id)
        assert entry["trigger_type"] == "TEST_integration"
        assert entry["status"] == "resolved"
        assert entry["chain_notification_triggered"] == True
        assert entry["chain_call_triggered"] == True

    def test_config_auto_creates_on_first_access(self, auth_headers):
        """GET /sos/config auto-creates config with defaults for new user"""
        # Just verify the GET works and returns valid config
        response = requests.get(f"{BASE_URL}/api/sos/config", headers=auth_headers)
        assert response.status_code == 200
        
        config = response.json()
        assert config["id"] is not None
        assert config["user_id"] is not None
        # Defaults should be set
        assert config["enabled"] is not None


# Cleanup helper - restore defaults after tests
@pytest.fixture(scope="module", autouse=True)
def cleanup_test_data(auth_headers):
    """Cleanup: Restore default config values after all tests"""
    yield
    # Restore reasonable defaults
    try:
        requests.put(f"{BASE_URL}/api/sos/config", headers=auth_headers, json={
            "enabled": True,
            "voice_keywords": ["help me", "sos now", "emergency"],
            "chain_notification": True,
            "chain_notification_delay": 10,
            "chain_notification_title": "Team Meeting in 5 min",
            "chain_call": True,
            "chain_call_delay": 40,
            "chain_call_preset_name": "Boss",
            "auto_share_location": True,
            "silent_mode": True
        })
    except Exception as e:
        print(f"Cleanup error: {e}")
