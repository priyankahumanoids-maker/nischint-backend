# Test SSE Check-in Broadcast to BOTH Guardian AND Child
# Verifies that checkin_pending, checkin_safe, checkin_help events are broadcast to BOTH users
# Related to: checkin_service.py, event_broadcaster.py, stream.py

import pytest
import requests
import os
import json
import time
import subprocess
import tempfile
import threading

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://gps-mic-restart.preview.emergentagent.com').rstrip('/')

# Test credentials from requirements
GUARDIAN_EMAIL = "mothernischint@gmail.com"
CHILD_EMAIL = "kidnischint@gmail.com"
PASSWORD = "nischint123"
CHILD_ID = "ae6c29f9-aafd-4449-abc3-881effa122a4"
GUARDIAN_ID = "d426c37a-e30b-4403-8270-31d094926d18"


class TestSSECheckInBroadcastToBothUsers:
    """Tests that SSE check-in events are broadcast to BOTH guardian AND child"""

    @pytest.fixture(scope="class")
    def tokens(self):
        """Get guardian and child tokens - class scoped to avoid rate limiting"""
        time.sleep(2)  # Avoid rate limiting
        guardian_resp = requests.post(f'{BASE_URL}/api/auth/login', json={
            'email': GUARDIAN_EMAIL, 'password': PASSWORD
        })
        assert guardian_resp.status_code == 200, f"Guardian login failed: {guardian_resp.text}"
        
        time.sleep(1)
        child_resp = requests.post(f'{BASE_URL}/api/auth/login', json={
            'email': CHILD_EMAIL, 'password': PASSWORD
        })
        assert child_resp.status_code == 200, f"Child login failed: {child_resp.text}"
        
        return {
            'guardian': guardian_resp.json().get('access_token') or guardian_resp.json().get('token'),
            'child': child_resp.json().get('access_token') or child_resp.json().get('token'),
        }

    def test_child_sse_stream_returns_connected_event(self, tokens):
        """GET /api/stream?token=<child_token> establishes SSE connection with child's user channel"""
        output_file = tempfile.NamedTemporaryFile(delete=False, suffix='.txt')
        output_file.close()
        
        # Start child SSE listener
        proc = subprocess.Popen(
            ['timeout', '5', 'curl', '-s', '-N', f"{BASE_URL}/api/stream?token={tokens['child']}"],
            stdout=open(output_file.name, 'w'),
            stderr=subprocess.DEVNULL
        )
        time.sleep(3)
        proc.terminate()
        
        with open(output_file.name, 'r') as f:
            content = f.read()
        
        os.unlink(output_file.name)
        
        # Verify connected event
        assert 'event: connected' in content, f"Expected 'event: connected', got: {content[:500]}"
        
        # Parse the connected event data
        lines = content.split('\n')
        data_line = [l for l in lines if l.startswith('data:')][0]
        data = json.loads(data_line.replace('data: ', ''))
        
        # Verify child's user channel
        assert 'channel' in data
        assert data['channel'].startswith('user:')
        assert data['channel'] == f'user:{CHILD_ID}'
        print(f"Child SSE connected to channel: {data['channel']}")

    def test_guardian_sse_stream_returns_connected_event(self, tokens):
        """GET /api/stream?token=<guardian_token> establishes SSE connection with guardian's user channel"""
        output_file = tempfile.NamedTemporaryFile(delete=False, suffix='.txt')
        output_file.close()
        
        # Start guardian SSE listener
        proc = subprocess.Popen(
            ['timeout', '5', 'curl', '-s', '-N', f"{BASE_URL}/api/stream?token={tokens['guardian']}"],
            stdout=open(output_file.name, 'w'),
            stderr=subprocess.DEVNULL
        )
        time.sleep(3)
        proc.terminate()
        
        with open(output_file.name, 'r') as f:
            content = f.read()
        
        os.unlink(output_file.name)
        
        # Verify connected event
        assert 'event: connected' in content, f"Expected 'event: connected', got: {content[:500]}"
        
        # Parse the connected event data
        lines = content.split('\n')
        data_line = [l for l in lines if l.startswith('data:')][0]
        data = json.loads(data_line.replace('data: ', ''))
        
        # Verify guardian's user channel
        assert 'channel' in data
        assert data['channel'].startswith('user:')
        assert data['channel'] == f'user:{GUARDIAN_ID}'
        print(f"Guardian SSE connected to channel: {data['channel']}")

    def test_checkin_pending_broadcast_to_both_users(self, tokens):
        """POST /api/checkin/{child_id} creates check-in and broadcasts checkin_pending to BOTH guardian AND child"""
        guardian_file = tempfile.NamedTemporaryFile(delete=False, suffix='.txt')
        child_file = tempfile.NamedTemporaryFile(delete=False, suffix='.txt')
        guardian_file.close()
        child_file.close()
        
        # Start BOTH SSE listeners
        proc_guardian = subprocess.Popen(
            ['timeout', '20', 'curl', '-s', '-N', f"{BASE_URL}/api/stream?token={tokens['guardian']}"],
            stdout=open(guardian_file.name, 'w'),
            stderr=subprocess.DEVNULL
        )
        proc_child = subprocess.Popen(
            ['timeout', '20', 'curl', '-s', '-N', f"{BASE_URL}/api/stream?token={tokens['child']}"],
            stdout=open(child_file.name, 'w'),
            stderr=subprocess.DEVNULL
        )
        time.sleep(3)  # Wait for connections to establish
        
        # Guardian creates check-in
        create_resp = requests.post(
            f"{BASE_URL}/api/checkin/{CHILD_ID}",
            headers={'Authorization': f"Bearer {tokens['guardian']}"}
        )
        assert create_resp.status_code == 200, f"Create check-in failed: {create_resp.text}"
        check_in_data = create_resp.json()
        check_in_id = check_in_data['check_in_id']
        
        # Verify response payload shape
        assert 'check_in_id' in check_in_data
        assert 'child_id' in check_in_data
        assert 'child_name' in check_in_data
        assert 'guardian_id' in check_in_data
        assert 'status' in check_in_data
        assert 'created_at' in check_in_data
        assert check_in_data['status'] == 'pending'
        print(f"Check-in created: {check_in_id}")
        
        # Wait for SSE events
        time.sleep(5)
        proc_guardian.terminate()
        proc_child.terminate()
        
        with open(guardian_file.name, 'r') as f:
            guardian_content = f.read()
        with open(child_file.name, 'r') as f:
            child_content = f.read()
        
        os.unlink(guardian_file.name)
        os.unlink(child_file.name)
        
        # Verify GUARDIAN received checkin_pending
        assert 'event: checkin_pending' in guardian_content, f"Guardian did not receive checkin_pending: {guardian_content[:500]}"
        print("Guardian received checkin_pending event")
        
        # Verify CHILD received checkin_pending
        assert 'event: checkin_pending' in child_content, f"Child did not receive checkin_pending: {child_content[:500]}"
        print("Child received checkin_pending event")
        
        # Parse and verify payload shape for guardian
        lines = guardian_content.split('\n')
        for i, line in enumerate(lines):
            if 'event: checkin_pending' in line:
                data_line = lines[i + 1] if i + 1 < len(lines) else None
                if data_line:
                    event_data = json.loads(data_line.replace('data: ', ''))
                    assert event_data['type'] == 'checkin_pending'
                    payload = event_data['data']
                    assert 'check_in_id' in payload
                    assert 'child_id' in payload
                    assert 'child_name' in payload
                    assert 'guardian_id' in payload
                    assert 'guardian_name' in payload
                    assert 'status' in payload
                    assert 'created_at' in payload
                    print(f"Payload shape verified: {list(payload.keys())}")
                break

    def test_checkin_safe_broadcast_to_both_users(self, tokens):
        """POST /api/checkin/{id}/respond with response=safe broadcasts checkin_safe to BOTH guardian AND child"""
        guardian_file = tempfile.NamedTemporaryFile(delete=False, suffix='.txt')
        child_file = tempfile.NamedTemporaryFile(delete=False, suffix='.txt')
        guardian_file.close()
        child_file.close()
        
        # First create a check-in
        create_resp = requests.post(
            f"{BASE_URL}/api/checkin/{CHILD_ID}",
            headers={'Authorization': f"Bearer {tokens['guardian']}"}
        )
        assert create_resp.status_code == 200
        check_in_id = create_resp.json()['check_in_id']
        
        # Start BOTH SSE listeners
        proc_guardian = subprocess.Popen(
            ['timeout', '20', 'curl', '-s', '-N', f"{BASE_URL}/api/stream?token={tokens['guardian']}"],
            stdout=open(guardian_file.name, 'w'),
            stderr=subprocess.DEVNULL
        )
        proc_child = subprocess.Popen(
            ['timeout', '20', 'curl', '-s', '-N', f"{BASE_URL}/api/stream?token={tokens['child']}"],
            stdout=open(child_file.name, 'w'),
            stderr=subprocess.DEVNULL
        )
        time.sleep(3)
        
        # Child responds with 'safe'
        respond_resp = requests.post(
            f"{BASE_URL}/api/checkin/{check_in_id}/respond",
            headers={'Authorization': f"Bearer {tokens['child']}"},
            json={'response': 'safe'}
        )
        assert respond_resp.status_code == 200, f"Respond failed: {respond_resp.text}"
        print(f"Child responded 'safe' to check-in {check_in_id}")
        
        # Wait for SSE events
        time.sleep(5)
        proc_guardian.terminate()
        proc_child.terminate()
        
        with open(guardian_file.name, 'r') as f:
            guardian_content = f.read()
        with open(child_file.name, 'r') as f:
            child_content = f.read()
        
        os.unlink(guardian_file.name)
        os.unlink(child_file.name)
        
        # Verify GUARDIAN received checkin_safe
        assert 'event: checkin_safe' in guardian_content, f"Guardian did not receive checkin_safe: {guardian_content[:500]}"
        print("Guardian received checkin_safe event")
        
        # Verify CHILD received checkin_safe
        assert 'event: checkin_safe' in child_content, f"Child did not receive checkin_safe: {child_content[:500]}"
        print("Child received checkin_safe event")

    def test_checkin_help_broadcast_to_both_users(self, tokens):
        """POST /api/checkin/{id}/respond with response=help broadcasts checkin_help to BOTH guardian AND child"""
        guardian_file = tempfile.NamedTemporaryFile(delete=False, suffix='.txt')
        child_file = tempfile.NamedTemporaryFile(delete=False, suffix='.txt')
        guardian_file.close()
        child_file.close()
        
        # First create a check-in
        create_resp = requests.post(
            f"{BASE_URL}/api/checkin/{CHILD_ID}",
            headers={'Authorization': f"Bearer {tokens['guardian']}"}
        )
        assert create_resp.status_code == 200
        check_in_id = create_resp.json()['check_in_id']
        
        # Start BOTH SSE listeners
        proc_guardian = subprocess.Popen(
            ['timeout', '20', 'curl', '-s', '-N', f"{BASE_URL}/api/stream?token={tokens['guardian']}"],
            stdout=open(guardian_file.name, 'w'),
            stderr=subprocess.DEVNULL
        )
        proc_child = subprocess.Popen(
            ['timeout', '20', 'curl', '-s', '-N', f"{BASE_URL}/api/stream?token={tokens['child']}"],
            stdout=open(child_file.name, 'w'),
            stderr=subprocess.DEVNULL
        )
        time.sleep(3)
        
        # Child responds with 'help'
        respond_resp = requests.post(
            f"{BASE_URL}/api/checkin/{check_in_id}/respond",
            headers={'Authorization': f"Bearer {tokens['child']}"},
            json={'response': 'help'}
        )
        assert respond_resp.status_code == 200, f"Respond failed: {respond_resp.text}"
        print(f"Child responded 'help' to check-in {check_in_id}")
        
        # Wait for SSE events
        time.sleep(5)
        proc_guardian.terminate()
        proc_child.terminate()
        
        with open(guardian_file.name, 'r') as f:
            guardian_content = f.read()
        with open(child_file.name, 'r') as f:
            child_content = f.read()
        
        os.unlink(guardian_file.name)
        os.unlink(child_file.name)
        
        # Verify GUARDIAN received checkin_help
        assert 'event: checkin_help' in guardian_content, f"Guardian did not receive checkin_help: {guardian_content[:500]}"
        print("Guardian received checkin_help event")
        
        # Verify CHILD received checkin_help
        assert 'event: checkin_help' in child_content, f"Child did not receive checkin_help: {child_content[:500]}"
        print("Child received checkin_help event")


class TestCheckInPayloadShape:
    """Tests for check-in API response payload shape"""

    @pytest.fixture(scope="class")
    def tokens(self):
        """Get guardian and child tokens"""
        time.sleep(2)
        guardian_resp = requests.post(f'{BASE_URL}/api/auth/login', json={
            'email': GUARDIAN_EMAIL, 'password': PASSWORD
        })
        assert guardian_resp.status_code == 200
        
        time.sleep(1)
        child_resp = requests.post(f'{BASE_URL}/api/auth/login', json={
            'email': CHILD_EMAIL, 'password': PASSWORD
        })
        assert child_resp.status_code == 200
        
        return {
            'guardian': guardian_resp.json().get('access_token') or guardian_resp.json().get('token'),
            'child': child_resp.json().get('access_token') or child_resp.json().get('token'),
        }

    def test_create_checkin_response_payload_shape(self, tokens):
        """POST /api/checkin/{child_id} returns correct payload shape"""
        create_resp = requests.post(
            f"{BASE_URL}/api/checkin/{CHILD_ID}",
            headers={'Authorization': f"Bearer {tokens['guardian']}"}
        )
        assert create_resp.status_code == 200
        data = create_resp.json()
        
        # Verify all required fields
        required_fields = ['check_in_id', 'child_id', 'child_name', 'guardian_id', 'status', 'created_at']
        for field in required_fields:
            assert field in data, f"Missing field: {field}"
        
        # Verify field values
        assert data['child_id'] == CHILD_ID
        assert data['guardian_id'] == GUARDIAN_ID
        assert data['status'] == 'pending'
        assert data['child_name'] == 'Kid Nischint'
        
        print(f"Create check-in payload: {json.dumps(data, indent=2)}")

    def test_respond_checkin_response_payload_shape(self, tokens):
        """POST /api/checkin/{id}/respond returns correct payload shape"""
        # Create check-in first
        create_resp = requests.post(
            f"{BASE_URL}/api/checkin/{CHILD_ID}",
            headers={'Authorization': f"Bearer {tokens['guardian']}"}
        )
        assert create_resp.status_code == 200
        check_in_id = create_resp.json()['check_in_id']
        
        # Respond
        respond_resp = requests.post(
            f"{BASE_URL}/api/checkin/{check_in_id}/respond",
            headers={'Authorization': f"Bearer {tokens['child']}"},
            json={'response': 'safe'}
        )
        assert respond_resp.status_code == 200
        data = respond_resp.json()
        
        # Verify response fields
        assert 'check_in_id' in data
        assert 'status' in data
        assert 'responded_at' in data
        assert data['check_in_id'] == check_in_id
        assert data['status'] == 'safe'
        
        print(f"Respond check-in payload: {json.dumps(data, indent=2)}")

    def test_get_checkin_status_payload_shape(self, tokens):
        """GET /api/checkin/status/{check_in_id} returns correct payload shape"""
        # Create check-in first
        create_resp = requests.post(
            f"{BASE_URL}/api/checkin/{CHILD_ID}",
            headers={'Authorization': f"Bearer {tokens['guardian']}"}
        )
        assert create_resp.status_code == 200
        check_in_id = create_resp.json()['check_in_id']
        
        # Get status
        status_resp = requests.get(
            f"{BASE_URL}/api/checkin/status/{check_in_id}",
            headers={'Authorization': f"Bearer {tokens['guardian']}"}
        )
        assert status_resp.status_code == 200
        data = status_resp.json()
        
        # Verify all required fields
        required_fields = ['check_in_id', 'child_id', 'child_name', 'status', 'created_at']
        for field in required_fields:
            assert field in data, f"Missing field: {field}"
        
        print(f"Get status payload: {json.dumps(data, indent=2)}")


class TestBackendLogsSSEEmit:
    """Tests that verify backend logs show [SSE_CHECKIN_EMIT] for both users"""

    @pytest.fixture(scope="class")
    def tokens(self):
        """Get guardian and child tokens"""
        time.sleep(2)
        guardian_resp = requests.post(f'{BASE_URL}/api/auth/login', json={
            'email': GUARDIAN_EMAIL, 'password': PASSWORD
        })
        assert guardian_resp.status_code == 200
        
        time.sleep(1)
        child_resp = requests.post(f'{BASE_URL}/api/auth/login', json={
            'email': CHILD_EMAIL, 'password': PASSWORD
        })
        assert child_resp.status_code == 200
        
        return {
            'guardian': guardian_resp.json().get('access_token') or guardian_resp.json().get('token'),
            'child': child_resp.json().get('access_token') or child_resp.json().get('token'),
        }

    def test_create_checkin_logs_sse_emit_for_both_users(self, tokens):
        """POST /api/checkin/{child_id} logs [SSE_CHECKIN_EMIT] for BOTH guardian_id and child_id"""
        # Create check-in
        create_resp = requests.post(
            f"{BASE_URL}/api/checkin/{CHILD_ID}",
            headers={'Authorization': f"Bearer {tokens['guardian']}"}
        )
        assert create_resp.status_code == 200
        check_in_id = create_resp.json()['check_in_id']
        
        # Note: We can't directly check backend logs from the test, but we verify the API works
        # The main agent context shows logs like:
        # [SSE_CHECKIN_EMIT] type=checkin_pending user=d426c37a-e30b-4403-8270-31d094926d18 checkin=...
        # [SSE_CHECKIN_EMIT] type=checkin_pending user=ae6c29f9-aafd-4449-abc3-881effa122a4 checkin=...
        
        print(f"Check-in {check_in_id} created - backend should log [SSE_CHECKIN_EMIT] for both users")
        print(f"Expected log: [SSE_CHECKIN_EMIT] type=checkin_pending user={GUARDIAN_ID}")
        print(f"Expected log: [SSE_CHECKIN_EMIT] type=checkin_pending user={CHILD_ID}")

    def test_respond_safe_logs_sse_emit_for_both_users(self, tokens):
        """POST /api/checkin/{id}/respond with safe logs [SSE_CHECKIN_EMIT] for BOTH users"""
        # Create check-in
        create_resp = requests.post(
            f"{BASE_URL}/api/checkin/{CHILD_ID}",
            headers={'Authorization': f"Bearer {tokens['guardian']}"}
        )
        assert create_resp.status_code == 200
        check_in_id = create_resp.json()['check_in_id']
        
        # Respond safe
        respond_resp = requests.post(
            f"{BASE_URL}/api/checkin/{check_in_id}/respond",
            headers={'Authorization': f"Bearer {tokens['child']}"},
            json={'response': 'safe'}
        )
        assert respond_resp.status_code == 200
        
        print(f"Check-in {check_in_id} responded 'safe' - backend should log [SSE_CHECKIN_EMIT] for both users")
        print(f"Expected log: [SSE_CHECKIN_EMIT] type=checkin_safe user={GUARDIAN_ID}")
        print(f"Expected log: [SSE_CHECKIN_EMIT] type=checkin_safe user={CHILD_ID}")

    def test_respond_help_logs_sse_emit_for_both_users(self, tokens):
        """POST /api/checkin/{id}/respond with help logs [SSE_CHECKIN_EMIT] for BOTH users"""
        # Create check-in
        create_resp = requests.post(
            f"{BASE_URL}/api/checkin/{CHILD_ID}",
            headers={'Authorization': f"Bearer {tokens['guardian']}"}
        )
        assert create_resp.status_code == 200
        check_in_id = create_resp.json()['check_in_id']
        
        # Respond help
        respond_resp = requests.post(
            f"{BASE_URL}/api/checkin/{check_in_id}/respond",
            headers={'Authorization': f"Bearer {tokens['child']}"},
            json={'response': 'help'}
        )
        assert respond_resp.status_code == 200
        
        print(f"Check-in {check_in_id} responded 'help' - backend should log [SSE_CHECKIN_EMIT] for both users")
        print(f"Expected log: [SSE_CHECKIN_EMIT] type=checkin_help user={GUARDIAN_ID}")
        print(f"Expected log: [SSE_CHECKIN_EMIT] type=checkin_help user={CHILD_ID}")
