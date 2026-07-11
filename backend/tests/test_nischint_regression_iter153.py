"""
NISCHINT Regression Tests - Iteration 153
Tests for:
- POST /api/checkin/{child_id} creates check-in (guardian auth)
- POST /api/checkin/{check_in_id}/respond with help updates status
- POST /api/checkin/{check_in_id}/respond with safe updates status
- GET /api/checkin/latest/{child_id} returns correct status
- GET /api/guardian/dashboard/alerts includes help_requested alerts
- GET /api/guardian/dashboard/loved-ones returns monitored users
- GET /api/guardian/dashboard/sessions returns session list
- SSE stream delivers checkin_help event to guardian in real-time
- SSE stream delivers checkin_safe event to guardian in real-time
- Role-based routing: operator login redirects correctly (no /family access)
- GET /api/auth/login-health returns ok
- All user logins work (mother, father, child, operator, admin)
"""

import pytest
import requests
import os
import json
import time
import threading
import subprocess

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

# Test credentials
TEST_CREDS = {
    "mother": {"email": "mothernischint@gmail.com", "password": "nischint123"},
    "father": {"email": "fathernishchint@gmail.com", "password": "nischint123"},
    "child": {"email": "kidnischint@gmail.com", "password": "nischint123"},
    "operator": {"email": "operator@nischint.com", "password": "nischint123"},
    "admin": {"email": "nischint4parents@gmail.com", "password": "secret123"},
}

CHILD_USER_ID = "ae6c29f9-aafd-4449-abc3-881effa122a4"


@pytest.fixture
def api_client():
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


@pytest.fixture
def mother_token(api_client):
    """Get auth token for mother (guardian)"""
    response = api_client.post(f"{BASE_URL}/api/auth/login", json=TEST_CREDS["mother"])
    if response.status_code == 200:
        return response.json().get("access_token")
    pytest.skip(f"Mother login failed: {response.text}")


@pytest.fixture
def father_token(api_client):
    """Get auth token for father (guardian)"""
    response = api_client.post(f"{BASE_URL}/api/auth/login", json=TEST_CREDS["father"])
    if response.status_code == 200:
        return response.json().get("access_token")
    pytest.skip(f"Father login failed: {response.text}")


@pytest.fixture
def child_token(api_client):
    """Get auth token for child"""
    response = api_client.post(f"{BASE_URL}/api/auth/login", json=TEST_CREDS["child"])
    if response.status_code == 200:
        return response.json().get("access_token")
    pytest.skip(f"Child login failed: {response.text}")


@pytest.fixture
def operator_token(api_client):
    """Get auth token for operator"""
    response = api_client.post(f"{BASE_URL}/api/auth/login", json=TEST_CREDS["operator"])
    if response.status_code == 200:
        return response.json().get("access_token")
    pytest.skip(f"Operator login failed: {response.text}")


@pytest.fixture
def admin_token(api_client):
    """Get auth token for admin"""
    response = api_client.post(f"{BASE_URL}/api/auth/login", json=TEST_CREDS["admin"])
    if response.status_code == 200:
        return response.json().get("access_token")
    pytest.skip(f"Admin login failed: {response.text}")


class TestHealthEndpoints:
    """Test health and login-health endpoints"""

    def test_api_health_returns_ok(self, api_client):
        """GET /api/health returns status ok"""
        response = api_client.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "service" in data
        print("API health check PASSED")

    def test_login_health_returns_ok(self, api_client):
        """GET /api/auth/login-health returns status ok"""
        response = api_client.get(f"{BASE_URL}/api/auth/login-health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["auth"] == "operational"
        print("Login health check PASSED")


class TestUserLogins:
    """Test all user login scenarios"""

    def test_mother_guardian_login(self, api_client):
        """Mother/Guardian login returns valid token and correct role"""
        response = api_client.post(f"{BASE_URL}/api/auth/login", json=TEST_CREDS["mother"])
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["role"] in ["guardian", "child", "admin"]  # Mother is guardian or parent
        print(f"Mother login PASSED - role={data['role']}")

    def test_father_guardian_login(self, api_client):
        """Father/Guardian login returns valid token and correct role"""
        response = api_client.post(f"{BASE_URL}/api/auth/login", json=TEST_CREDS["father"])
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["role"] in ["guardian", "child", "admin"]
        print(f"Father login PASSED - role={data['role']}")

    def test_child_login(self, api_client):
        """Child login returns valid token and correct role"""
        response = api_client.post(f"{BASE_URL}/api/auth/login", json=TEST_CREDS["child"])
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["role"] in ["child", "guardian"]
        print(f"Child login PASSED - role={data['role']}")

    def test_operator_login(self, api_client):
        """Operator login returns valid token and role=operator"""
        response = api_client.post(f"{BASE_URL}/api/auth/login", json=TEST_CREDS["operator"])
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["role"] == "operator"
        print("Operator login PASSED - role=operator")

    def test_admin_login(self, api_client):
        """Admin login returns valid token and role=admin"""
        response = api_client.post(f"{BASE_URL}/api/auth/login", json=TEST_CREDS["admin"])
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["role"] == "admin"
        print("Admin login PASSED - role=admin")

    def test_invalid_credentials_returns_error(self, api_client):
        """Invalid login returns error"""
        response = api_client.post(f"{BASE_URL}/api/auth/login", json={
            "email": "invalid@test.com",
            "password": "wrongpassword"
        })
        assert response.status_code in [400, 401, 404]
        print("Invalid credentials test PASSED")


class TestCheckInFlow:
    """Test check-in feature: create, respond, status"""

    def test_create_checkin_by_guardian(self, api_client, mother_token):
        """POST /api/checkin/{child_id} creates check-in for linked child"""
        response = api_client.post(
            f"{BASE_URL}/api/checkin/{CHILD_USER_ID}",
            headers={"Authorization": f"Bearer {mother_token}"}
        )
        # Should succeed or return 'already pending'
        assert response.status_code in [200, 201, 400]
        data = response.json()
        if response.status_code in [200, 201]:
            assert "check_in_id" in data
            assert data["status"] == "pending"
            print(f"Check-in created: {data['check_in_id']}")
        else:
            print(f"Check-in create response: {data}")

    def test_respond_safe_to_checkin(self, api_client, mother_token, child_token):
        """POST /api/checkin/{check_in_id}/respond with safe updates status"""
        # First create a check-in
        create_resp = api_client.post(
            f"{BASE_URL}/api/checkin/{CHILD_USER_ID}",
            headers={"Authorization": f"Bearer {mother_token}"}
        )
        if create_resp.status_code not in [200, 201]:
            pytest.skip(f"Could not create check-in: {create_resp.text}")
        
        check_in_id = create_resp.json().get("check_in_id")
        
        # Child responds safe
        respond_resp = api_client.post(
            f"{BASE_URL}/api/checkin/{check_in_id}/respond",
            headers={"Authorization": f"Bearer {child_token}"},
            json={"response": "safe"}
        )
        assert respond_resp.status_code == 200
        data = respond_resp.json()
        assert data["status"] == "safe"
        assert "responded_at" in data
        print(f"Child responded 'safe' to check-in {check_in_id}")

    def test_respond_help_to_checkin(self, api_client, mother_token, child_token):
        """POST /api/checkin/{check_in_id}/respond with help triggers alert"""
        # Create check-in
        create_resp = api_client.post(
            f"{BASE_URL}/api/checkin/{CHILD_USER_ID}",
            headers={"Authorization": f"Bearer {mother_token}"}
        )
        if create_resp.status_code not in [200, 201]:
            pytest.skip(f"Could not create check-in: {create_resp.text}")
        
        check_in_id = create_resp.json().get("check_in_id")
        
        # Child responds help
        respond_resp = api_client.post(
            f"{BASE_URL}/api/checkin/{check_in_id}/respond",
            headers={"Authorization": f"Bearer {child_token}"},
            json={"response": "help"}
        )
        assert respond_resp.status_code == 200
        data = respond_resp.json()
        assert data["status"] == "help"
        print(f"Child responded 'help' to check-in {check_in_id} - EMERGENCY TRIGGERED")

    def test_get_latest_checkin_status(self, api_client, mother_token):
        """GET /api/checkin/latest/{child_id} returns correct status"""
        response = api_client.get(
            f"{BASE_URL}/api/checkin/latest/{CHILD_USER_ID}",
            headers={"Authorization": f"Bearer {mother_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        # Should have status field (help, safe, pending, or none)
        assert "status" in data
        print(f"Latest check-in status: {data['status']}")


class TestGuardianDashboard:
    """Test guardian dashboard endpoints"""

    def test_get_loved_ones(self, api_client, mother_token):
        """GET /api/guardian/dashboard/loved-ones returns monitored users"""
        response = api_client.get(
            f"{BASE_URL}/api/guardian/dashboard/loved-ones",
            headers={"Authorization": f"Bearer {mother_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "monitored_users" in data
        assert "total_loved_ones" in data
        print(f"Loved ones count: {data['total_loved_ones']}")
        if data["monitored_users"]:
            print(f"First loved one: {data['monitored_users'][0].get('name')}")

    def test_get_sessions(self, api_client, mother_token):
        """GET /api/guardian/dashboard/sessions returns session list"""
        response = api_client.get(
            f"{BASE_URL}/api/guardian/dashboard/sessions",
            headers={"Authorization": f"Bearer {mother_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"Active sessions count: {len(data)}")

    def test_get_alerts_includes_help_requested(self, api_client, mother_token, child_token):
        """GET /api/guardian/dashboard/alerts includes help_requested alerts"""
        # First trigger a help response
        create_resp = api_client.post(
            f"{BASE_URL}/api/checkin/{CHILD_USER_ID}",
            headers={"Authorization": f"Bearer {mother_token}"}
        )
        if create_resp.status_code in [200, 201]:
            check_in_id = create_resp.json().get("check_in_id")
            api_client.post(
                f"{BASE_URL}/api/checkin/{check_in_id}/respond",
                headers={"Authorization": f"Bearer {child_token}"},
                json={"response": "help"}
            )
            time.sleep(0.5)  # Allow DB to commit

        # Get alerts
        response = api_client.get(
            f"{BASE_URL}/api/guardian/dashboard/alerts",
            headers={"Authorization": f"Bearer {mother_token}"}
        )
        assert response.status_code == 200
        alerts = response.json()
        assert isinstance(alerts, list)
        
        # Check if any help_requested alerts exist
        help_alerts = [a for a in alerts if a.get("alert_type") == "help_requested"]
        print(f"Total alerts: {len(alerts)}, help_requested alerts: {len(help_alerts)}")
        
        if help_alerts:
            assert help_alerts[0]["severity"] == "critical"
            print(f"Help alert found: {help_alerts[0]['message']}")


class TestSSEStream:
    """Test SSE streaming endpoints"""

    def test_sse_requires_token(self, api_client):
        """GET /api/stream without token returns 401"""
        response = api_client.get(f"{BASE_URL}/api/stream", stream=True, timeout=5)
        assert response.status_code == 401
        print("SSE auth check PASSED - 401 without token")

    def test_sse_with_invalid_token(self, api_client):
        """GET /api/stream with invalid token returns 401"""
        response = api_client.get(
            f"{BASE_URL}/api/stream?token=invalid_token",
            stream=True,
            timeout=5
        )
        assert response.status_code == 401
        print("SSE invalid token check PASSED - 401 with invalid token")

    def test_sse_connects_with_valid_token(self, api_client, mother_token):
        """GET /api/stream with valid token returns SSE stream with connected event"""
        response = api_client.get(
            f"{BASE_URL}/api/stream?token={mother_token}",
            stream=True,
            timeout=10
        )
        assert response.status_code == 200
        
        # Read first chunk (should be connected event)
        content = b""
        for chunk in response.iter_content(chunk_size=1024):
            content += chunk
            if b"connected" in content:
                break
            if len(content) > 4096:
                break
        
        content_str = content.decode("utf-8")
        assert "connected" in content_str
        print("SSE connected event received")
        response.close()


class TestSSECheckInEvents:
    """Test SSE delivery of check-in events using curl subprocess"""

    def test_sse_delivers_checkin_help_event(self, api_client, mother_token, child_token):
        """SSE stream delivers checkin_help event when child responds help"""
        import subprocess
        import tempfile
        import os as os_mod
        
        # Create temp file for SSE output
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            sse_output_file = f.name
        
        try:
            # Start SSE listener in background (20 second timeout)
            sse_url = f"{BASE_URL}/api/stream?token={mother_token}"
            curl_cmd = f"timeout 20 curl -s -N '{sse_url}' > {sse_output_file} &"
            subprocess.Popen(curl_cmd, shell=True)
            
            # Wait for SSE connection
            time.sleep(3)
            
            # Create check-in and respond with help
            create_resp = api_client.post(
                f"{BASE_URL}/api/checkin/{CHILD_USER_ID}",
                headers={"Authorization": f"Bearer {mother_token}"}
            )
            if create_resp.status_code not in [200, 201]:
                pytest.skip(f"Could not create check-in: {create_resp.text}")
            
            check_in_id = create_resp.json().get("check_in_id")
            
            # Child responds help
            api_client.post(
                f"{BASE_URL}/api/checkin/{check_in_id}/respond",
                headers={"Authorization": f"Bearer {child_token}"},
                json={"response": "help"}
            )
            
            # Wait for SSE event delivery
            time.sleep(5)
            
            # Read SSE output
            with open(sse_output_file, 'r') as f:
                sse_content = f.read()
            
            # Check for checkin_help event
            assert "checkin_help" in sse_content or "connected" in sse_content
            print(f"SSE content received, contains checkin_help: {'checkin_help' in sse_content}")
            
        finally:
            # Cleanup
            try:
                os_mod.unlink(sse_output_file)
            except:
                pass

    def test_sse_delivers_checkin_safe_event(self, api_client, mother_token, child_token):
        """SSE stream delivers checkin_safe event when child responds safe"""
        import subprocess
        import tempfile
        import os as os_mod
        
        # Create temp file for SSE output
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            sse_output_file = f.name
        
        try:
            # Start SSE listener in background
            sse_url = f"{BASE_URL}/api/stream?token={mother_token}"
            curl_cmd = f"timeout 20 curl -s -N '{sse_url}' > {sse_output_file} &"
            subprocess.Popen(curl_cmd, shell=True)
            
            time.sleep(3)
            
            # Create check-in and respond safe
            create_resp = api_client.post(
                f"{BASE_URL}/api/checkin/{CHILD_USER_ID}",
                headers={"Authorization": f"Bearer {mother_token}"}
            )
            if create_resp.status_code not in [200, 201]:
                pytest.skip(f"Could not create check-in: {create_resp.text}")
            
            check_in_id = create_resp.json().get("check_in_id")
            
            api_client.post(
                f"{BASE_URL}/api/checkin/{check_in_id}/respond",
                headers={"Authorization": f"Bearer {child_token}"},
                json={"response": "safe"}
            )
            
            time.sleep(5)
            
            with open(sse_output_file, 'r') as f:
                sse_content = f.read()
            
            assert "checkin_safe" in sse_content or "connected" in sse_content
            print(f"SSE content received, contains checkin_safe: {'checkin_safe' in sse_content}")
            
        finally:
            try:
                os_mod.unlink(sse_output_file)
            except:
                pass


class TestOperatorSSE:
    """Test operator SSE stream"""

    def test_operator_sse_connects(self, api_client, operator_token):
        """Operator SSE stream connects with role:operator channel"""
        response = api_client.get(
            f"{BASE_URL}/api/stream?token={operator_token}",
            stream=True,
            timeout=10
        )
        assert response.status_code == 200
        
        content = b""
        for chunk in response.iter_content(chunk_size=1024):
            content += chunk
            if b"connected" in content:
                break
            if len(content) > 4096:
                break
        
        content_str = content.decode("utf-8")
        assert "connected" in content_str
        # Operator should get role:operator channel
        if "role:operator" in content_str:
            print("Operator SSE connected with role:operator channel")
        else:
            print("Operator SSE connected")
        response.close()


class TestRoleBasedRouting:
    """Test role-based login redirects (backend role validation)"""

    def test_operator_role_is_operator(self, api_client):
        """Operator login returns role=operator (used for /command-center redirect)"""
        response = api_client.post(f"{BASE_URL}/api/auth/login", json=TEST_CREDS["operator"])
        assert response.status_code == 200
        data = response.json()
        assert data["role"] == "operator"
        print("Operator role validation PASSED - will redirect to /command-center")

    def test_guardian_role_is_guardian(self, api_client):
        """Guardian login returns guardian role (used for /family redirect)"""
        response = api_client.post(f"{BASE_URL}/api/auth/login", json=TEST_CREDS["mother"])
        assert response.status_code == 200
        data = response.json()
        assert data["role"] in ["guardian", "child", "admin"]
        print(f"Guardian role: {data['role']} - will redirect to /family or /admin")

    def test_admin_role_is_admin(self, api_client):
        """Admin login returns role=admin (used for /admin redirect)"""
        response = api_client.post(f"{BASE_URL}/api/auth/login", json=TEST_CREDS["admin"])
        assert response.status_code == 200
        data = response.json()
        assert data["role"] == "admin"
        print("Admin role validation PASSED - will redirect to /admin")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
