# Test Fake Call Escape Mechanism API
# Tests: presets CRUD, trigger, complete, history endpoints
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
    """Login and get auth token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD
    })
    assert response.status_code == 200, f"Login failed: {response.text}"
    data = response.json()
    token = data.get("access_token")
    assert token, "No access_token in login response"
    return token


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Return headers with auth token"""
    return {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json"
    }


class TestFakeCallPresets:
    """Tests for /api/fake-call/presets endpoints"""
    
    def test_get_presets_requires_auth(self):
        """GET /api/fake-call/presets should return 401 without auth"""
        response = requests.get(f"{BASE_URL}/api/fake-call/presets")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: GET /presets returns 401 without auth")
    
    def test_get_presets_returns_default_presets(self, auth_headers):
        """GET /api/fake-call/presets should return default presets (Mom, Boss, Best Friend)"""
        response = requests.get(f"{BASE_URL}/api/fake-call/presets", headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "presets" in data, "Response should have 'presets' key"
        presets = data["presets"]
        
        # Should have at least 3 default presets
        assert len(presets) >= 3, f"Expected at least 3 presets, got {len(presets)}"
        
        # Verify structure of each preset
        for preset in presets:
            assert "id" in preset, "Preset should have 'id'"
            assert "caller_name" in preset, "Preset should have 'caller_name'"
            assert "caller_label" in preset, "Preset should have 'caller_label'"
            assert "ringtone_style" in preset, "Preset should have 'ringtone_style'"
            assert "is_default" in preset, "Preset should have 'is_default'"
        
        # Check that default presets (Mom, Boss, Best Friend) exist
        preset_names = [p["caller_name"] for p in presets]
        assert "Mom" in preset_names, "Default preset 'Mom' should exist"
        assert "Boss" in preset_names, "Default preset 'Boss' should exist"
        assert "Best Friend" in preset_names, "Default preset 'Best Friend' should exist"
        
        print(f"PASS: GET /presets returns {len(presets)} presets including defaults (Mom, Boss, Best Friend)")
    
    def test_create_custom_preset(self, auth_headers):
        """POST /api/fake-call/presets should create a custom preset"""
        unique_name = f"TEST_Contact_{uuid.uuid4().hex[:8]}"
        payload = {
            "caller_name": unique_name,
            "caller_label": "Friend",
            "ringtone_style": "upbeat"
        }
        response = requests.post(f"{BASE_URL}/api/fake-call/presets", json=payload, headers=auth_headers)
        assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["caller_name"] == unique_name, "Caller name should match"
        assert data["caller_label"] == "Friend", "Caller label should match"
        assert data["ringtone_style"] == "upbeat", "Ringtone style should match"
        assert data["is_default"] == False, "Custom preset should not be default"
        assert "id" in data, "Response should include preset id"
        
        print(f"PASS: POST /presets creates custom preset '{unique_name}'")
        return data["id"]
    
    def test_update_preset(self, auth_headers):
        """PUT /api/fake-call/presets/{preset_id} should update a preset"""
        # First create a preset to update
        unique_name = f"TEST_Update_{uuid.uuid4().hex[:8]}"
        create_resp = requests.post(f"{BASE_URL}/api/fake-call/presets", json={
            "caller_name": unique_name,
            "caller_label": "Custom",
            "ringtone_style": "default"
        }, headers=auth_headers)
        assert create_resp.status_code == 201
        preset_id = create_resp.json()["id"]
        
        # Update the preset
        new_name = f"TEST_Updated_{uuid.uuid4().hex[:8]}"
        update_payload = {
            "caller_name": new_name,
            "ringtone_style": "professional"
        }
        response = requests.put(f"{BASE_URL}/api/fake-call/presets/{preset_id}", json=update_payload, headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["caller_name"] == new_name, "Caller name should be updated"
        assert data["ringtone_style"] == "professional", "Ringtone style should be updated"
        
        # Verify by GET
        get_resp = requests.get(f"{BASE_URL}/api/fake-call/presets", headers=auth_headers)
        presets = get_resp.json()["presets"]
        updated = next((p for p in presets if p["id"] == preset_id), None)
        assert updated is not None, "Updated preset should exist"
        assert updated["caller_name"] == new_name, "Updated name should persist"
        
        print(f"PASS: PUT /presets/{preset_id} updates preset successfully")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/fake-call/presets/{preset_id}", headers=auth_headers)
    
    def test_delete_custom_preset(self, auth_headers):
        """DELETE /api/fake-call/presets/{preset_id} should delete non-default preset"""
        # Create a preset to delete
        unique_name = f"TEST_Delete_{uuid.uuid4().hex[:8]}"
        create_resp = requests.post(f"{BASE_URL}/api/fake-call/presets", json={
            "caller_name": unique_name,
            "caller_label": "Custom",
            "ringtone_style": "default"
        }, headers=auth_headers)
        assert create_resp.status_code == 201
        preset_id = create_resp.json()["id"]
        
        # Delete the preset
        response = requests.delete(f"{BASE_URL}/api/fake-call/presets/{preset_id}", headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("deleted") == True, "Response should confirm deletion"
        
        # Verify preset no longer exists
        get_resp = requests.get(f"{BASE_URL}/api/fake-call/presets", headers=auth_headers)
        presets = get_resp.json()["presets"]
        deleted_preset = next((p for p in presets if p["id"] == preset_id), None)
        assert deleted_preset is None, "Deleted preset should not exist"
        
        print(f"PASS: DELETE /presets/{preset_id} deletes custom preset")
    
    def test_delete_default_preset_fails(self, auth_headers):
        """DELETE /api/fake-call/presets/{preset_id} should fail for default preset"""
        # Get a default preset ID
        get_resp = requests.get(f"{BASE_URL}/api/fake-call/presets", headers=auth_headers)
        presets = get_resp.json()["presets"]
        default_preset = next((p for p in presets if p["is_default"] == True), None)
        assert default_preset is not None, "Should have default preset"
        
        # Try to delete it
        response = requests.delete(f"{BASE_URL}/api/fake-call/presets/{default_preset['id']}", headers=auth_headers)
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        
        print(f"PASS: DELETE /presets/{default_preset['id']} fails for default preset (returns 404)")


class TestFakeCallTrigger:
    """Tests for /api/fake-call/trigger endpoint"""
    
    def test_trigger_requires_auth(self):
        """POST /api/fake-call/trigger should return 401 without auth"""
        response = requests.post(f"{BASE_URL}/api/fake-call/trigger", json={})
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: POST /trigger returns 401 without auth")
    
    def test_trigger_fake_call_with_preset(self, auth_headers):
        """POST /api/fake-call/trigger with preset_id should trigger a call"""
        # Get a preset
        get_resp = requests.get(f"{BASE_URL}/api/fake-call/presets", headers=auth_headers)
        presets = get_resp.json()["presets"]
        preset = presets[0]
        
        payload = {
            "preset_id": preset["id"],
            "delay_seconds": 0,
            "trigger_method": "test"
        }
        response = requests.post(f"{BASE_URL}/api/fake-call/trigger", json=payload, headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "call_id" in data, "Response should have 'call_id'"
        assert data["caller_name"] == preset["caller_name"], f"Caller name should be '{preset['caller_name']}'"
        assert data["delay_seconds"] == 0, "Delay should be 0"
        assert data["trigger_method"] == "test", "Trigger method should be 'test'"
        assert "triggered_at" in data, "Response should have 'triggered_at'"
        
        print(f"PASS: POST /trigger with preset triggers call (call_id: {data['call_id'][:8]}...)")
        return data["call_id"]
    
    def test_trigger_fake_call_with_caller_name(self, auth_headers):
        """POST /api/fake-call/trigger with caller_name should trigger a call"""
        payload = {
            "caller_name": "Test Emergency Contact",
            "delay_seconds": 10,
            "trigger_method": "quick_access"
        }
        response = requests.post(f"{BASE_URL}/api/fake-call/trigger", json=payload, headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["caller_name"] == "Test Emergency Contact"
        assert data["delay_seconds"] == 10
        
        print(f"PASS: POST /trigger with custom caller_name triggers call")
        return data["call_id"]


class TestFakeCallComplete:
    """Tests for /api/fake-call/complete/{call_id} endpoint"""
    
    def test_complete_requires_auth(self):
        """POST /api/fake-call/complete/{call_id} should return 401 without auth"""
        fake_id = str(uuid.uuid4())
        response = requests.post(f"{BASE_URL}/api/fake-call/complete/{fake_id}", json={})
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: POST /complete returns 401 without auth")
    
    def test_complete_call_answered(self, auth_headers):
        """POST /api/fake-call/complete/{call_id} should complete a call as answered"""
        # First trigger a call
        get_resp = requests.get(f"{BASE_URL}/api/fake-call/presets", headers=auth_headers)
        preset = get_resp.json()["presets"][0]
        
        trigger_resp = requests.post(f"{BASE_URL}/api/fake-call/trigger", json={
            "preset_id": preset["id"],
            "trigger_method": "test"
        }, headers=auth_headers)
        assert trigger_resp.status_code == 200
        call_id = trigger_resp.json()["call_id"]
        
        # Complete the call
        complete_payload = {
            "answered": True,
            "duration_seconds": 45,
            "send_alert": False
        }
        response = requests.post(f"{BASE_URL}/api/fake-call/complete/{call_id}", json=complete_payload, headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["call_id"] == call_id, "Call ID should match"
        assert data["status"] == "completed", "Status should be 'completed'"
        assert data["answered"] == True, "Answered should be True"
        assert data["duration_seconds"] == 45, "Duration should be 45"
        assert data["alert_sent"] == False, "Alert sent should be False"
        
        print(f"PASS: POST /complete/{call_id[:8]}... completes call as answered")
    
    def test_complete_call_declined(self, auth_headers):
        """POST /api/fake-call/complete/{call_id} should complete a declined call"""
        # Trigger a call
        trigger_resp = requests.post(f"{BASE_URL}/api/fake-call/trigger", json={
            "caller_name": "Test Declined Call",
            "trigger_method": "test"
        }, headers=auth_headers)
        assert trigger_resp.status_code == 200
        call_id = trigger_resp.json()["call_id"]
        
        # Decline the call
        complete_payload = {
            "answered": False,
            "duration_seconds": 0,
            "send_alert": False
        }
        response = requests.post(f"{BASE_URL}/api/fake-call/complete/{call_id}", json=complete_payload, headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data["answered"] == False
        assert data["duration_seconds"] == 0
        
        print(f"PASS: POST /complete/{call_id[:8]}... completes call as declined")
    
    def test_complete_call_with_alert(self, auth_headers):
        """POST /api/fake-call/complete/{call_id} with send_alert=True should send alert"""
        # Trigger a call
        trigger_resp = requests.post(f"{BASE_URL}/api/fake-call/trigger", json={
            "caller_name": "Emergency Test",
            "trigger_method": "test"
        }, headers=auth_headers)
        assert trigger_resp.status_code == 200
        call_id = trigger_resp.json()["call_id"]
        
        # Complete with alert
        complete_payload = {
            "answered": True,
            "duration_seconds": 30,
            "send_alert": True
        }
        response = requests.post(f"{BASE_URL}/api/fake-call/complete/{call_id}", json=complete_payload, headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data["alert_sent"] == True, "Alert should be sent"
        
        print(f"PASS: POST /complete/{call_id[:8]}... with send_alert=True sends alert")
    
    def test_complete_invalid_call_id(self, auth_headers):
        """POST /api/fake-call/complete/{call_id} with invalid ID should return 404"""
        fake_id = str(uuid.uuid4())
        response = requests.post(f"{BASE_URL}/api/fake-call/complete/{fake_id}", json={
            "answered": True,
            "duration_seconds": 0,
            "send_alert": False
        }, headers=auth_headers)
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print(f"PASS: POST /complete with invalid call_id returns 404")


class TestFakeCallHistory:
    """Tests for /api/fake-call/history endpoint"""
    
    def test_history_requires_auth(self):
        """GET /api/fake-call/history should return 401 without auth"""
        response = requests.get(f"{BASE_URL}/api/fake-call/history")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: GET /history returns 401 without auth")
    
    def test_history_returns_calls(self, auth_headers):
        """GET /api/fake-call/history should return call history"""
        response = requests.get(f"{BASE_URL}/api/fake-call/history", headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "history" in data, "Response should have 'history' key"
        assert "count" in data, "Response should have 'count' key"
        
        history = data["history"]
        assert isinstance(history, list), "History should be a list"
        
        # If there's history, verify structure
        if len(history) > 0:
            call = history[0]
            assert "id" in call, "Call should have 'id'"
            assert "caller_name" in call, "Call should have 'caller_name'"
            assert "status" in call, "Call should have 'status'"
            assert "triggered_at" in call, "Call should have 'triggered_at'"
            assert "answered" in call, "Call should have 'answered'"
        
        print(f"PASS: GET /history returns {len(history)} calls")
    
    def test_history_limit_parameter(self, auth_headers):
        """GET /api/fake-call/history with limit should respect limit"""
        response = requests.get(f"{BASE_URL}/api/fake-call/history?limit=5", headers=auth_headers)
        assert response.status_code == 200
        
        data = response.json()
        history = data["history"]
        assert len(history) <= 5, f"History should have at most 5 entries, got {len(history)}"
        
        print(f"PASS: GET /history?limit=5 returns at most 5 entries")
    
    def test_history_sorted_by_recent(self, auth_headers):
        """GET /api/fake-call/history should return calls sorted by most recent"""
        response = requests.get(f"{BASE_URL}/api/fake-call/history?limit=10", headers=auth_headers)
        assert response.status_code == 200
        
        data = response.json()
        history = data["history"]
        
        if len(history) > 1:
            # Verify descending order by triggered_at
            for i in range(len(history) - 1):
                current = history[i]["triggered_at"]
                next_call = history[i + 1]["triggered_at"]
                assert current >= next_call, f"History should be sorted by most recent first"
        
        print("PASS: GET /history returns calls sorted by most recent")


class TestFakeCallEndToEnd:
    """End-to-end test of fake call flow"""
    
    def test_full_fake_call_flow(self, auth_headers):
        """Test complete flow: get presets -> trigger -> complete -> verify in history"""
        # Step 1: Get presets
        presets_resp = requests.get(f"{BASE_URL}/api/fake-call/presets", headers=auth_headers)
        assert presets_resp.status_code == 200
        presets = presets_resp.json()["presets"]
        assert len(presets) >= 3
        
        # Step 2: Trigger a call with first preset
        preset = presets[0]
        trigger_resp = requests.post(f"{BASE_URL}/api/fake-call/trigger", json={
            "preset_id": preset["id"],
            "caller_name": preset["caller_name"],
            "delay_seconds": 0,
            "trigger_method": "e2e_test"
        }, headers=auth_headers)
        assert trigger_resp.status_code == 200
        call_data = trigger_resp.json()
        call_id = call_data["call_id"]
        
        # Step 3: Complete the call
        complete_resp = requests.post(f"{BASE_URL}/api/fake-call/complete/{call_id}", json={
            "answered": True,
            "duration_seconds": 60,
            "send_alert": False
        }, headers=auth_headers)
        assert complete_resp.status_code == 200
        
        # Step 4: Verify call appears in history
        history_resp = requests.get(f"{BASE_URL}/api/fake-call/history?limit=10", headers=auth_headers)
        assert history_resp.status_code == 200
        history = history_resp.json()["history"]
        
        # Find our call in history
        our_call = next((h for h in history if h["id"] == call_id), None)
        assert our_call is not None, "Our call should appear in history"
        assert our_call["status"] == "completed", "Call status should be 'completed'"
        assert our_call["answered"] == True, "Call should be marked as answered"
        assert our_call["duration_seconds"] == 60, "Duration should be 60 seconds"
        
        print(f"PASS: Full fake call E2E flow works correctly")
