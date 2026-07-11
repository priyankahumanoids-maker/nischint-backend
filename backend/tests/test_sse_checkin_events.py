# Test SSE Stream endpoint and check-in event broadcasting
# Tests real-time SSE delivery for checkin_help and checkin_safe events
# Related services: stream.py, event_broadcaster.py, checkin_service.py

import pytest
import requests
import os
import json
import time
import subprocess
import threading
import tempfile

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://gps-mic-restart.preview.emergentagent.com').rstrip('/')

# Test credentials
MOTHER_EMAIL = "mothernischint@gmail.com"
FATHER_EMAIL = "fathernishchint@gmail.com"
CHILD_EMAIL = "kidnischint@gmail.com"
OPERATOR_EMAIL = "operator@nischint.com"
PASSWORD = "nischint123"
CHILD_ID = "ae6c29f9-aafd-4449-abc3-881effa122a4"


class TestSSEAuthentication:
    """Tests for SSE stream authentication requirements"""

    def test_sse_without_token_returns_401(self):
        """GET /api/stream without token should return 401"""
        resp = requests.get(f'{BASE_URL}/api/stream', timeout=10)
        assert resp.status_code == 401
        data = resp.json()
        assert "detail" in data
        assert "token" in data["detail"].lower()

    def test_sse_with_invalid_token_returns_401(self):
        """GET /api/stream with invalid token should return 401"""
        resp = requests.get(f'{BASE_URL}/api/stream?token=invalid_fake_token', timeout=10)
        assert resp.status_code == 401
        data = resp.json()
        assert "detail" in data
        assert "invalid" in data["detail"].lower() or "token" in data["detail"].lower()

    def test_sse_with_expired_token_returns_401(self):
        """GET /api/stream with expired token should return 401"""
        # Expired JWT token
        expired_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ0ZXN0IiwiZXhwIjoxMDAwMDAwMDAwfQ.test"
        resp = requests.get(f'{BASE_URL}/api/stream?token={expired_token}', timeout=10)
        assert resp.status_code == 401


class TestSSEConnectedEvent:
    """Tests for SSE connected event format and channel assignment"""

    @pytest.fixture
    def guardian_token(self):
        """Get guardian auth token"""
        resp = requests.post(f'{BASE_URL}/api/auth/login', json={
            'email': MOTHER_EMAIL, 'password': PASSWORD
        })
        assert resp.status_code == 200
        data = resp.json()
        return data.get('access_token') or data.get('token')

    @pytest.fixture
    def operator_token(self):
        """Get operator auth token"""
        resp = requests.post(f'{BASE_URL}/api/auth/login', json={
            'email': OPERATOR_EMAIL, 'password': PASSWORD
        })
        assert resp.status_code == 200
        data = resp.json()
        return data.get('access_token') or data.get('token')

    def test_guardian_sse_returns_connected_event_with_user_channel(self, guardian_token):
        """Guardian SSE stream returns connected event with user:{user_id} channel"""
        output_file = tempfile.NamedTemporaryFile(delete=False, suffix='.txt')
        output_file.close()
        
        # Start SSE listener with timeout
        proc = subprocess.Popen(
            ['timeout', '5', 'curl', '-s', '-N', f'{BASE_URL}/api/stream?token={guardian_token}'],
            stdout=open(output_file.name, 'w'),
            stderr=subprocess.DEVNULL
        )
        time.sleep(3)
        proc.terminate()
        
        with open(output_file.name, 'r') as f:
            content = f.read()
        
        os.unlink(output_file.name)
        
        # Parse SSE content
        assert 'event: connected' in content
        assert 'data:' in content
        
        # Extract JSON data
        lines = content.split('\n')
        data_line = [l for l in lines if l.startswith('data:')][0]
        data = json.loads(data_line.replace('data: ', ''))
        
        assert 'channel' in data
        assert data['channel'].startswith('user:')
        assert 'user_id' in data

    def test_operator_sse_returns_connected_event_with_role_channel(self, operator_token):
        """Operator SSE stream returns connected event with role:operator channel"""
        output_file = tempfile.NamedTemporaryFile(delete=False, suffix='.txt')
        output_file.close()
        
        proc = subprocess.Popen(
            ['timeout', '5', 'curl', '-s', '-N', f'{BASE_URL}/api/stream?token={operator_token}'],
            stdout=open(output_file.name, 'w'),
            stderr=subprocess.DEVNULL
        )
        time.sleep(3)
        proc.terminate()
        
        with open(output_file.name, 'r') as f:
            content = f.read()
        
        os.unlink(output_file.name)
        
        # Parse SSE content
        assert 'event: connected' in content
        
        lines = content.split('\n')
        data_line = [l for l in lines if l.startswith('data:')][0]
        data = json.loads(data_line.replace('data: ', ''))
        
        assert data['channel'] == 'role:operator'
        assert data.get('role') == 'operator'


class TestSSECheckInHelpEvents:
    """Tests for checkin_help SSE event delivery"""

    @pytest.fixture
    def tokens(self):
        """Get all required tokens"""
        guardian_resp = requests.post(f'{BASE_URL}/api/auth/login', json={
            'email': MOTHER_EMAIL, 'password': PASSWORD
        })
        child_resp = requests.post(f'{BASE_URL}/api/auth/login', json={
            'email': CHILD_EMAIL, 'password': PASSWORD
        })
        operator_resp = requests.post(f'{BASE_URL}/api/auth/login', json={
            'email': OPERATOR_EMAIL, 'password': PASSWORD
        })
        
        return {
            'guardian': guardian_resp.json().get('access_token') or guardian_resp.json().get('token'),
            'child': child_resp.json().get('access_token') or child_resp.json().get('token'),
            'operator': operator_resp.json().get('access_token') or operator_resp.json().get('token'),
        }

    def test_guardian_receives_checkin_help_event(self, tokens):
        """When child responds 'help', guardian SSE stream receives checkin_help event"""
        output_file = tempfile.NamedTemporaryFile(delete=False, suffix='.txt')
        output_file.close()
        
        # Step 1: Start guardian SSE listener with longer timeout
        proc = subprocess.Popen(
            ['timeout', '30', 'curl', '-s', '-N', f"{BASE_URL}/api/stream?token={tokens['guardian']}"],
            stdout=open(output_file.name, 'w'),
            stderr=subprocess.DEVNULL
        )
        time.sleep(5)  # Wait longer for connection to establish
        
        # Step 2: Guardian creates check-in
        create_resp = requests.post(
            f"{BASE_URL}/api/checkin/{CHILD_ID}",
            headers={'Authorization': f"Bearer {tokens['guardian']}"}
        )
        assert create_resp.status_code == 200
        check_in_id = create_resp.json()['check_in_id']
        
        # Step 3: Child responds with 'help'
        respond_resp = requests.post(
            f"{BASE_URL}/api/checkin/{check_in_id}/respond",
            headers={'Authorization': f"Bearer {tokens['child']}"},
            json={'response': 'help'}
        )
        assert respond_resp.status_code == 200
        
        # Step 4: Wait longer for SSE event
        time.sleep(8)
        proc.terminate()
        
        with open(output_file.name, 'r') as f:
            content = f.read()
        
        os.unlink(output_file.name)
        
        # Verify checkin_help event was received
        assert 'event: checkin_help' in content, f"Expected checkin_help event, got: {content[:500]}"
        
        # Parse the event data
        lines = content.split('\n')
        help_data_line = None
        for i, line in enumerate(lines):
            if 'event: checkin_help' in line:
                help_data_line = lines[i + 1] if i + 1 < len(lines) else None
                break
        
        assert help_data_line is not None
        event_data = json.loads(help_data_line.replace('data: ', ''))
        
        assert event_data['type'] == 'checkin_help'
        assert event_data['data']['check_in_id'] == check_in_id
        assert event_data['data']['child_id'] == CHILD_ID
        assert event_data['data']['child_name'] == 'Kid Nischint'
        assert event_data['data']['response'] == 'help'
        assert 'responded_at' in event_data['data']

    def test_operator_receives_checkin_help_event(self, tokens):
        """When child responds 'help', operator SSE stream also receives checkin_help event"""
        output_file = tempfile.NamedTemporaryFile(delete=False, suffix='.txt')
        output_file.close()
        
        # Step 1: Start operator SSE listener
        proc = subprocess.Popen(
            ['timeout', '20', 'curl', '-s', '-N', f"{BASE_URL}/api/stream?token={tokens['operator']}"],
            stdout=open(output_file.name, 'w'),
            stderr=subprocess.DEVNULL
        )
        time.sleep(3)
        
        # Step 2: Guardian creates check-in
        create_resp = requests.post(
            f"{BASE_URL}/api/checkin/{CHILD_ID}",
            headers={'Authorization': f"Bearer {tokens['guardian']}"}
        )
        assert create_resp.status_code == 200
        check_in_id = create_resp.json()['check_in_id']
        
        # Step 3: Child responds with 'help'
        respond_resp = requests.post(
            f"{BASE_URL}/api/checkin/{check_in_id}/respond",
            headers={'Authorization': f"Bearer {tokens['child']}"},
            json={'response': 'help'}
        )
        assert respond_resp.status_code == 200
        
        # Step 4: Wait for SSE event
        time.sleep(5)
        proc.terminate()
        
        with open(output_file.name, 'r') as f:
            content = f.read()
        
        os.unlink(output_file.name)
        
        # Verify operator received the checkin_help event
        assert 'event: checkin_help' in content


class TestSSECheckInSafeEvents:
    """Tests for checkin_safe SSE event delivery"""

    @pytest.fixture
    def tokens(self):
        """Get all required tokens"""
        guardian_resp = requests.post(f'{BASE_URL}/api/auth/login', json={
            'email': MOTHER_EMAIL, 'password': PASSWORD
        })
        child_resp = requests.post(f'{BASE_URL}/api/auth/login', json={
            'email': CHILD_EMAIL, 'password': PASSWORD
        })
        
        return {
            'guardian': guardian_resp.json().get('access_token') or guardian_resp.json().get('token'),
            'child': child_resp.json().get('access_token') or child_resp.json().get('token'),
        }

    def test_guardian_receives_checkin_safe_event(self, tokens):
        """When child responds 'safe', guardian SSE stream receives checkin_safe event"""
        output_file = tempfile.NamedTemporaryFile(delete=False, suffix='.txt')
        output_file.close()
        
        # Start guardian SSE listener
        proc = subprocess.Popen(
            ['timeout', '20', 'curl', '-s', '-N', f"{BASE_URL}/api/stream?token={tokens['guardian']}"],
            stdout=open(output_file.name, 'w'),
            stderr=subprocess.DEVNULL
        )
        time.sleep(3)
        
        # Guardian creates check-in
        create_resp = requests.post(
            f"{BASE_URL}/api/checkin/{CHILD_ID}",
            headers={'Authorization': f"Bearer {tokens['guardian']}"}
        )
        assert create_resp.status_code == 200
        check_in_id = create_resp.json()['check_in_id']
        
        # Child responds with 'safe'
        respond_resp = requests.post(
            f"{BASE_URL}/api/checkin/{check_in_id}/respond",
            headers={'Authorization': f"Bearer {tokens['child']}"},
            json={'response': 'safe'}
        )
        assert respond_resp.status_code == 200
        
        time.sleep(5)
        proc.terminate()
        
        with open(output_file.name, 'r') as f:
            content = f.read()
        
        os.unlink(output_file.name)
        
        # Verify checkin_safe event
        assert 'event: checkin_safe' in content
        
        # Parse the event data
        lines = content.split('\n')
        safe_data_line = None
        for i, line in enumerate(lines):
            if 'event: checkin_safe' in line:
                safe_data_line = lines[i + 1] if i + 1 < len(lines) else None
                break
        
        assert safe_data_line is not None
        event_data = json.loads(safe_data_line.replace('data: ', ''))
        
        assert event_data['type'] == 'checkin_safe'
        assert event_data['data']['response'] == 'safe'


class TestSSEScopedDelivery:
    """Tests that SSE events are delivered only to correct users"""

    @pytest.fixture
    def tokens(self):
        """Get tokens for mother and father guardians"""
        mother_resp = requests.post(f'{BASE_URL}/api/auth/login', json={
            'email': MOTHER_EMAIL, 'password': PASSWORD
        })
        father_resp = requests.post(f'{BASE_URL}/api/auth/login', json={
            'email': FATHER_EMAIL, 'password': PASSWORD
        })
        child_resp = requests.post(f'{BASE_URL}/api/auth/login', json={
            'email': CHILD_EMAIL, 'password': PASSWORD
        })
        
        return {
            'mother': mother_resp.json().get('access_token') or mother_resp.json().get('token'),
            'father': father_resp.json().get('access_token') or father_resp.json().get('token'),
            'child': child_resp.json().get('access_token') or child_resp.json().get('token'),
        }

    def test_mother_and_father_have_different_channels(self, tokens):
        """Each guardian should have their own user:{id} channel"""
        mother_file = tempfile.NamedTemporaryFile(delete=False, suffix='.txt')
        father_file = tempfile.NamedTemporaryFile(delete=False, suffix='.txt')
        mother_file.close()
        father_file.close()
        
        # Start both SSE listeners
        proc_mother = subprocess.Popen(
            ['timeout', '5', 'curl', '-s', '-N', f"{BASE_URL}/api/stream?token={tokens['mother']}"],
            stdout=open(mother_file.name, 'w'),
            stderr=subprocess.DEVNULL
        )
        proc_father = subprocess.Popen(
            ['timeout', '5', 'curl', '-s', '-N', f"{BASE_URL}/api/stream?token={tokens['father']}"],
            stdout=open(father_file.name, 'w'),
            stderr=subprocess.DEVNULL
        )
        
        time.sleep(3)
        proc_mother.terminate()
        proc_father.terminate()
        
        with open(mother_file.name, 'r') as f:
            mother_content = f.read()
        with open(father_file.name, 'r') as f:
            father_content = f.read()
        
        os.unlink(mother_file.name)
        os.unlink(father_file.name)
        
        # Extract channels
        mother_lines = [l for l in mother_content.split('\n') if l.startswith('data:')]
        father_lines = [l for l in father_content.split('\n') if l.startswith('data:')]
        
        mother_data = json.loads(mother_lines[0].replace('data: ', ''))
        father_data = json.loads(father_lines[0].replace('data: ', ''))
        
        # Verify different channels
        assert mother_data['channel'] != father_data['channel']
        assert mother_data['channel'].startswith('user:')
        assert father_data['channel'].startswith('user:')


class TestCheckInLatestStatus:
    """Tests for GET /api/checkin/latest/{child_id} endpoint"""

    @pytest.fixture
    def tokens(self):
        """Get guardian and child tokens"""
        guardian_resp = requests.post(f'{BASE_URL}/api/auth/login', json={
            'email': MOTHER_EMAIL, 'password': PASSWORD
        })
        child_resp = requests.post(f'{BASE_URL}/api/auth/login', json={
            'email': CHILD_EMAIL, 'password': PASSWORD
        })
        
        return {
            'guardian': guardian_resp.json().get('access_token') or guardian_resp.json().get('token'),
            'child': child_resp.json().get('access_token') or child_resp.json().get('token'),
        }

    def test_latest_checkin_returns_help_status(self, tokens):
        """After child responds 'help', GET /api/checkin/latest/{child_id} returns status=help"""
        # Create check-in
        create_resp = requests.post(
            f"{BASE_URL}/api/checkin/{CHILD_ID}",
            headers={'Authorization': f"Bearer {tokens['guardian']}"}
        )
        assert create_resp.status_code == 200
        check_in_id = create_resp.json()['check_in_id']
        
        # Respond with help
        respond_resp = requests.post(
            f"{BASE_URL}/api/checkin/{check_in_id}/respond",
            headers={'Authorization': f"Bearer {tokens['child']}"},
            json={'response': 'help'}
        )
        assert respond_resp.status_code == 200
        
        # Get latest status
        status_resp = requests.get(
            f"{BASE_URL}/api/checkin/latest/{CHILD_ID}",
            headers={'Authorization': f"Bearer {tokens['guardian']}"}
        )
        assert status_resp.status_code == 200
        data = status_resp.json()
        
        assert data['status'] == 'help'
        assert data['check_in_id'] == check_in_id
        assert 'responded_at' in data

    def test_latest_checkin_returns_safe_status(self, tokens):
        """After child responds 'safe', GET /api/checkin/latest/{child_id} returns status=safe"""
        # Create check-in
        create_resp = requests.post(
            f"{BASE_URL}/api/checkin/{CHILD_ID}",
            headers={'Authorization': f"Bearer {tokens['guardian']}"}
        )
        assert create_resp.status_code == 200
        check_in_id = create_resp.json()['check_in_id']
        
        # Respond with safe
        respond_resp = requests.post(
            f"{BASE_URL}/api/checkin/{check_in_id}/respond",
            headers={'Authorization': f"Bearer {tokens['child']}"},
            json={'response': 'safe'}
        )
        assert respond_resp.status_code == 200
        
        # Get latest status
        status_resp = requests.get(
            f"{BASE_URL}/api/checkin/latest/{CHILD_ID}",
            headers={'Authorization': f"Bearer {tokens['guardian']}"}
        )
        assert status_resp.status_code == 200
        data = status_resp.json()
        
        assert data['status'] == 'safe'
        assert data['check_in_id'] == check_in_id


class TestGuardianDashboardAlerts:
    """Tests for GET /api/guardian/dashboard/alerts including check-in alerts"""

    def test_alerts_includes_checkin_help_as_critical(self):
        """GET /api/guardian/dashboard/alerts includes help responses as critical alerts"""
        # Get fresh tokens inside the test to avoid expiry
        guardian_resp = requests.post(f'{BASE_URL}/api/auth/login', json={
            'email': MOTHER_EMAIL, 'password': PASSWORD
        })
        assert guardian_resp.status_code == 200
        guardian_token = guardian_resp.json().get('access_token') or guardian_resp.json().get('token')
        
        child_resp = requests.post(f'{BASE_URL}/api/auth/login', json={
            'email': CHILD_EMAIL, 'password': PASSWORD
        })
        assert child_resp.status_code == 200
        child_token = child_resp.json().get('access_token') or child_resp.json().get('token')
        
        tokens = {'guardian': guardian_token, 'child': child_token}
        """GET /api/guardian/dashboard/alerts includes help responses as critical alerts"""
        # Create check-in and respond with help
        create_resp = requests.post(
            f"{BASE_URL}/api/checkin/{CHILD_ID}",
            headers={'Authorization': f"Bearer {tokens['guardian']}"}
        )
        assert create_resp.status_code == 200
        check_in_id = create_resp.json()['check_in_id']
        
        respond_resp = requests.post(
            f"{BASE_URL}/api/checkin/{check_in_id}/respond",
            headers={'Authorization': f"Bearer {tokens['child']}"},
            json={'response': 'help'}
        )
        assert respond_resp.status_code == 200
        
        # Get alerts
        alerts_resp = requests.get(
            f"{BASE_URL}/api/guardian/dashboard/alerts",
            headers={'Authorization': f"Bearer {tokens['guardian']}"}
        )
        assert alerts_resp.status_code == 200
        data = alerts_resp.json()
        
        assert 'alerts' in data
        assert len(data['alerts']) > 0
        
        # Find our check-in alert
        check_in_alert = next(
            (a for a in data['alerts'] if a.get('id') == check_in_id),
            None
        )
        assert check_in_alert is not None
        assert check_in_alert['alert_type'] == 'help_requested'
        assert check_in_alert['severity'] == 'critical'
        assert 'Kid Nischint' in check_in_alert['message']
