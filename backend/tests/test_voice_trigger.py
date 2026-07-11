# Voice Trigger API Tests — Tests for voice command management and recognition
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
    """Get authentication token for guardian user"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD
    })
    assert response.status_code == 200, f"Login failed: {response.text}"
    data = response.json()
    assert "access_token" in data, f"No access_token in response: {data}"
    return data["access_token"]


@pytest.fixture(scope="module")
def api_client(auth_token):
    """Authenticated API session"""
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {auth_token}"
    })
    return session


@pytest.fixture(scope="module")
def unauthenticated_client():
    """Session without auth for testing 401 responses"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


# ========== GET /api/voice-trigger/commands Tests ==========
class TestListCommands:
    """Tests for GET /api/voice-trigger/commands"""

    def test_requires_auth(self, unauthenticated_client):
        """Should return 401 without authentication"""
        response = unauthenticated_client.get(f"{BASE_URL}/api/voice-trigger/commands")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: GET /commands requires authentication")

    def test_returns_commands_list(self, api_client):
        """Should return commands array with at least 3 defaults"""
        response = api_client.get(f"{BASE_URL}/api/voice-trigger/commands")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "commands" in data, f"Missing commands key: {data}"
        assert isinstance(data["commands"], list), "Commands should be a list"
        assert len(data["commands"]) >= 3, f"Expected at least 3 default commands, got {len(data['commands'])}"
        print(f"PASS: GET /commands returns {len(data['commands'])} commands")

    def test_default_commands_seeded(self, api_client):
        """Should have 3 default commands: help me→sos, call me now→fake_call, notify me now→fake_notification"""
        response = api_client.get(f"{BASE_URL}/api/voice-trigger/commands")
        assert response.status_code == 200
        commands = response.json()["commands"]
        
        # Check for default commands
        default_phrases = {c["phrase"] for c in commands if c.get("is_default")}
        expected = {"help me", "call me now", "notify me now"}
        assert expected.issubset(default_phrases), f"Missing default phrases. Found: {default_phrases}"
        print("PASS: All 3 default commands seeded (help me, call me now, notify me now)")

    def test_command_structure(self, api_client):
        """Should return commands with correct structure"""
        response = api_client.get(f"{BASE_URL}/api/voice-trigger/commands")
        assert response.status_code == 200
        commands = response.json()["commands"]
        
        required_fields = ["id", "phrase", "linked_action", "confidence_threshold", "enabled", "is_default", "created_at"]
        for cmd in commands:
            for field in required_fields:
                assert field in cmd, f"Missing field '{field}' in command: {cmd}"
        print("PASS: Command structure has all required fields")

    def test_default_command_actions(self, api_client):
        """Default commands should link to correct actions"""
        response = api_client.get(f"{BASE_URL}/api/voice-trigger/commands")
        commands = response.json()["commands"]
        
        action_map = {c["phrase"]: c["linked_action"] for c in commands if c.get("is_default")}
        assert action_map.get("help me") == "sos", f"help me should link to sos, got {action_map.get('help me')}"
        assert action_map.get("call me now") == "fake_call", f"call me now should link to fake_call"
        assert action_map.get("notify me now") == "fake_notification", f"notify me now should link to fake_notification"
        print("PASS: Default commands linked to correct actions")


# ========== POST /api/voice-trigger/commands Tests ==========
class TestCreateCommand:
    """Tests for POST /api/voice-trigger/commands"""

    def test_requires_auth(self, unauthenticated_client):
        """Should return 401 without authentication"""
        response = unauthenticated_client.post(f"{BASE_URL}/api/voice-trigger/commands", json={
            "phrase": "test phrase",
            "linked_action": "sos"
        })
        assert response.status_code == 401
        print("PASS: POST /commands requires authentication")

    def test_creates_custom_command(self, api_client):
        """Should create custom voice command and return it"""
        test_phrase = f"TEST_escape now {uuid.uuid4().hex[:6]}"
        response = api_client.post(f"{BASE_URL}/api/voice-trigger/commands", json={
            "phrase": test_phrase,
            "linked_action": "fake_call",
            "confidence_threshold": 0.8
        })
        assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["phrase"] == test_phrase.lower(), f"Phrase mismatch: {data['phrase']}"
        assert data["linked_action"] == "fake_call"
        assert data["confidence_threshold"] == 0.8
        assert data["is_default"] == False
        assert "id" in data
        print(f"PASS: Created custom command with id {data['id']}")

    def test_validates_linked_action(self, api_client):
        """Should reject invalid linked_action values"""
        response = api_client.post(f"{BASE_URL}/api/voice-trigger/commands", json={
            "phrase": "test invalid action",
            "linked_action": "invalid_action"
        })
        assert response.status_code == 422, f"Expected 422 for invalid action, got {response.status_code}"
        print("PASS: Rejects invalid linked_action")

    def test_validates_confidence_threshold_min(self, api_client):
        """Should reject confidence_threshold below 0.3"""
        response = api_client.post(f"{BASE_URL}/api/voice-trigger/commands", json={
            "phrase": "test low threshold",
            "linked_action": "sos",
            "confidence_threshold": 0.1
        })
        assert response.status_code == 422, f"Expected 422 for low threshold, got {response.status_code}"
        print("PASS: Rejects confidence_threshold < 0.3")

    def test_validates_confidence_threshold_max(self, api_client):
        """Should reject confidence_threshold above 1.0"""
        response = api_client.post(f"{BASE_URL}/api/voice-trigger/commands", json={
            "phrase": "test high threshold",
            "linked_action": "sos",
            "confidence_threshold": 1.5
        })
        assert response.status_code == 422, f"Expected 422 for high threshold, got {response.status_code}"
        print("PASS: Rejects confidence_threshold > 1.0")


# ========== DELETE /api/voice-trigger/commands/{id} Tests ==========
class TestDeleteCommand:
    """Tests for DELETE /api/voice-trigger/commands/{id}"""

    def test_requires_auth(self, unauthenticated_client):
        """Should return 401 without authentication"""
        random_id = str(uuid.uuid4())
        response = unauthenticated_client.delete(f"{BASE_URL}/api/voice-trigger/commands/{random_id}")
        assert response.status_code == 401
        print("PASS: DELETE /commands/{id} requires authentication")

    def test_deletes_custom_command(self, api_client):
        """Should delete non-default custom command"""
        # First create a command
        test_phrase = f"TEST_delete me {uuid.uuid4().hex[:6]}"
        create_response = api_client.post(f"{BASE_URL}/api/voice-trigger/commands", json={
            "phrase": test_phrase,
            "linked_action": "fake_notification"
        })
        assert create_response.status_code == 201
        cmd_id = create_response.json()["id"]
        
        # Now delete it
        delete_response = api_client.delete(f"{BASE_URL}/api/voice-trigger/commands/{cmd_id}")
        assert delete_response.status_code == 200, f"Expected 200, got {delete_response.status_code}: {delete_response.text}"
        data = delete_response.json()
        assert data.get("deleted") == True
        print(f"PASS: Deleted custom command {cmd_id}")

    def test_rejects_default_command_deletion(self, api_client):
        """Should return 404 when trying to delete default command"""
        # Get commands to find a default one
        response = api_client.get(f"{BASE_URL}/api/voice-trigger/commands")
        commands = response.json()["commands"]
        default_cmd = next((c for c in commands if c.get("is_default")), None)
        assert default_cmd, "No default command found"
        
        # Try to delete it
        delete_response = api_client.delete(f"{BASE_URL}/api/voice-trigger/commands/{default_cmd['id']}")
        assert delete_response.status_code == 404, f"Expected 404 for default command, got {delete_response.status_code}"
        print(f"PASS: Cannot delete default command '{default_cmd['phrase']}'")

    def test_nonexistent_command_returns_404(self, api_client):
        """Should return 404 for non-existent command"""
        random_id = str(uuid.uuid4())
        response = api_client.delete(f"{BASE_URL}/api/voice-trigger/commands/{random_id}")
        assert response.status_code == 404
        print("PASS: Returns 404 for non-existent command")


# ========== POST /api/voice-trigger/recognize Tests ==========
class TestRecognize:
    """Tests for POST /api/voice-trigger/recognize (text-based recognition)"""

    def test_requires_auth(self, unauthenticated_client):
        """Should return 401 without authentication"""
        response = unauthenticated_client.post(f"{BASE_URL}/api/voice-trigger/recognize", json={
            "transcribed_text": "help me"
        })
        assert response.status_code == 401
        print("PASS: POST /recognize requires authentication")

    def test_matches_exact_phrase(self, api_client):
        """Should match exact default phrase 'help me' → sos"""
        response = api_client.post(f"{BASE_URL}/api/voice-trigger/recognize", json={
            "transcribed_text": "help me"
        })
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["triggered"] == True, f"Should trigger on 'help me': {data}"
        assert data["matched_phrase"] == "help me"
        assert data["linked_action"] == "sos"
        assert data["confidence"] >= 0.7
        print(f"PASS: 'help me' matched with {data['confidence']*100:.0f}% confidence → sos")

    def test_matches_fake_call_phrase(self, api_client):
        """Should match 'call me now' → fake_call"""
        response = api_client.post(f"{BASE_URL}/api/voice-trigger/recognize", json={
            "transcribed_text": "call me now"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["triggered"] == True
        assert data["matched_phrase"] == "call me now"
        assert data["linked_action"] == "fake_call"
        print("PASS: 'call me now' triggers fake_call")

    def test_matches_fake_notification_phrase(self, api_client):
        """Should match 'notify me now' → fake_notification"""
        response = api_client.post(f"{BASE_URL}/api/voice-trigger/recognize", json={
            "transcribed_text": "notify me now"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["triggered"] == True
        assert data["matched_phrase"] == "notify me now"
        assert data["linked_action"] == "fake_notification"
        print("PASS: 'notify me now' triggers fake_notification")

    def test_matches_substring(self, api_client):
        """Should match when phrase is contained in text"""
        response = api_client.post(f"{BASE_URL}/api/voice-trigger/recognize", json={
            "transcribed_text": "please help me I need assistance"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["triggered"] == True, "Should match 'help me' as substring"
        assert data["matched_phrase"] == "help me"
        print("PASS: Substring match 'please help me...' triggers sos")

    def test_no_match_returns_not_triggered(self, api_client):
        """Should return triggered=false for unmatched text"""
        response = api_client.post(f"{BASE_URL}/api/voice-trigger/recognize", json={
            "transcribed_text": "hello world this is random text"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["triggered"] == False, f"Should not trigger on random text: {data}"
        assert data["matched_phrase"] is None
        assert data["linked_action"] is None
        print("PASS: Random text does not trigger any command")

    def test_returns_result_structure(self, api_client):
        """Should return complete result structure"""
        response = api_client.post(f"{BASE_URL}/api/voice-trigger/recognize", json={
            "transcribed_text": "help me"
        })
        data = response.json()
        required_fields = ["log_id", "transcribed_text", "matched_phrase", "confidence", "triggered", "linked_action", "timestamp"]
        for field in required_fields:
            assert field in data, f"Missing field '{field}' in result: {data}"
        print("PASS: Recognition result has complete structure")

    def test_creates_log_entry(self, api_client):
        """Should create log entry for recognition attempt"""
        test_text = f"unique test {uuid.uuid4().hex[:6]} help me"
        response = api_client.post(f"{BASE_URL}/api/voice-trigger/recognize", json={
            "transcribed_text": test_text
        })
        assert response.status_code == 200
        assert "log_id" in response.json()
        
        # Verify in history
        history_response = api_client.get(f"{BASE_URL}/api/voice-trigger/history?limit=5")
        assert history_response.status_code == 200
        history = history_response.json()["history"]
        found = any(h["transcribed_text"] == test_text for h in history)
        assert found, "Recognition attempt not found in history"
        print("PASS: Recognition attempt logged in history")


# ========== GET /api/voice-trigger/history Tests ==========
class TestHistory:
    """Tests for GET /api/voice-trigger/history"""

    def test_requires_auth(self, unauthenticated_client):
        """Should return 401 without authentication"""
        response = unauthenticated_client.get(f"{BASE_URL}/api/voice-trigger/history")
        assert response.status_code == 401
        print("PASS: GET /history requires authentication")

    def test_returns_history_list(self, api_client):
        """Should return history array with count"""
        response = api_client.get(f"{BASE_URL}/api/voice-trigger/history")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "history" in data
        assert "count" in data
        assert isinstance(data["history"], list)
        print(f"PASS: GET /history returns {data['count']} entries")

    def test_respects_limit_param(self, api_client):
        """Should respect limit query parameter"""
        response = api_client.get(f"{BASE_URL}/api/voice-trigger/history?limit=3")
        assert response.status_code == 200
        data = response.json()
        assert len(data["history"]) <= 3
        print("PASS: History respects limit parameter")

    def test_history_entry_structure(self, api_client):
        """Should return entries with correct structure"""
        response = api_client.get(f"{BASE_URL}/api/voice-trigger/history?limit=5")
        data = response.json()
        if data["history"]:
            entry = data["history"][0]
            required_fields = ["id", "transcribed_text", "matched_phrase", "confidence", "linked_action", "triggered", "status", "triggered_at"]
            for field in required_fields:
                assert field in entry, f"Missing field '{field}' in history entry: {entry}"
        print("PASS: History entries have correct structure")


# ========== Cleanup ==========
class TestCleanup:
    """Cleanup test data"""

    def test_cleanup_test_commands(self, api_client):
        """Delete TEST_ prefixed commands"""
        response = api_client.get(f"{BASE_URL}/api/voice-trigger/commands")
        if response.status_code == 200:
            commands = response.json()["commands"]
            deleted = 0
            for cmd in commands:
                if cmd["phrase"].startswith("test_") and not cmd.get("is_default"):
                    del_resp = api_client.delete(f"{BASE_URL}/api/voice-trigger/commands/{cmd['id']}")
                    if del_resp.status_code == 200:
                        deleted += 1
            print(f"PASS: Cleaned up {deleted} test commands")
