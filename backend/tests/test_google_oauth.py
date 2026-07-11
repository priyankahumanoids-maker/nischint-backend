# Google OAuth Social Login Tests
# Tests for Google OAuth federation endpoints and backward compatibility

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL').rstrip('/')

# Test credentials
GUARDIAN_EMAIL = "nischint4parents@gmail.com"
GUARDIAN_PASSWORD = "secret123"
GOOGLE_CLIENT_ID = "771020447588-8jpfqsh460q3ruegnrmv9a3oh55ge9ko.apps.googleusercontent.com"


class TestGoogleOAuthStatus:
    """Test Google OAuth status endpoint"""
    
    def test_google_auth_status_returns_200(self):
        """GET /api/auth/google/status returns 200"""
        response = requests.get(f"{BASE_URL}/api/auth/google/status")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    
    def test_google_auth_status_returns_enabled(self):
        """GET /api/auth/google/status returns enabled=true"""
        response = requests.get(f"{BASE_URL}/api/auth/google/status")
        data = response.json()
        assert "enabled" in data, "Response should contain 'enabled' field"
        assert data["enabled"] == True, "Google OAuth should be enabled"
    
    def test_google_auth_status_returns_client_id(self):
        """GET /api/auth/google/status returns client_id"""
        response = requests.get(f"{BASE_URL}/api/auth/google/status")
        data = response.json()
        assert "client_id" in data, "Response should contain 'client_id' field"
        assert data["client_id"] is not None, "client_id should not be null"
        assert data["client_id"].startswith("771020447588"), f"client_id should start with expected prefix, got: {data['client_id']}"


class TestGoogleOAuthCredentialEndpoint:
    """Test POST /api/auth/google (credential flow) error handling"""
    
    def test_google_auth_missing_credential_returns_422(self):
        """POST /api/auth/google with missing credential returns 422"""
        response = requests.post(f"{BASE_URL}/api/auth/google", json={})
        # Pydantic validation error for missing required field
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
    
    def test_google_auth_invalid_credential_returns_401(self):
        """POST /api/auth/google with invalid credential returns 401"""
        response = requests.post(f"{BASE_URL}/api/auth/google", json={
            "credential": "invalid_token_12345"
        })
        # Google will reject invalid token
        assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"
        data = response.json()
        assert "detail" in data, "Response should contain 'detail' field"
        # Should return meaningful error message
        assert any(keyword in data["detail"].lower() for keyword in ["invalid", "credential", "google"]), f"Error message should mention invalid credential: {data['detail']}"
    
    def test_google_auth_empty_credential_returns_401(self):
        """POST /api/auth/google with empty credential returns 401"""
        response = requests.post(f"{BASE_URL}/api/auth/google", json={
            "credential": ""
        })
        # Should fail validation or at Google API
        assert response.status_code in [401, 422], f"Expected 401 or 422, got {response.status_code}: {response.text}"


class TestGoogleOAuthCodeEndpoint:
    """Test POST /api/auth/google/code (authorization code flow) error handling"""
    
    def test_google_auth_code_missing_fields_returns_422(self):
        """POST /api/auth/google/code with missing fields returns 422"""
        response = requests.post(f"{BASE_URL}/api/auth/google/code", json={})
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
    
    def test_google_auth_code_missing_redirect_uri_returns_422(self):
        """POST /api/auth/google/code with missing redirect_uri returns 422"""
        response = requests.post(f"{BASE_URL}/api/auth/google/code", json={
            "code": "test_code"
        })
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
    
    def test_google_auth_code_invalid_code_returns_401(self):
        """POST /api/auth/google/code with invalid code returns 401"""
        response = requests.post(f"{BASE_URL}/api/auth/google/code", json={
            "code": "invalid_authorization_code_12345",
            "redirect_uri": "https://gps-mic-restart.preview.emergentagent.com"
        })
        # Google will reject invalid authorization code
        assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"
        data = response.json()
        assert "detail" in data, "Response should contain 'detail' field"


class TestLocalAuthBackwardCompatibility:
    """Test local auth still works after Google OAuth addition"""
    
    def test_local_login_works(self):
        """POST /api/auth/login with valid credentials returns 200"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": GUARDIAN_EMAIL,
            "password": GUARDIAN_PASSWORD
        })
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "access_token" in data, "Response should contain 'access_token'"
        assert "role" in data, "Response should contain 'role'"
        assert data["role"] == "guardian", f"Expected role=guardian, got {data['role']}"
    
    def test_local_login_returns_token_type(self):
        """POST /api/auth/login returns token_type=bearer"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": GUARDIAN_EMAIL,
            "password": GUARDIAN_PASSWORD
        })
        data = response.json()
        assert "token_type" in data, "Response should contain 'token_type'"
        assert data["token_type"] == "bearer", f"Expected token_type=bearer, got {data['token_type']}"
    
    def test_local_login_invalid_credentials(self):
        """POST /api/auth/login with invalid credentials returns 401"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "nonexistent@example.com",
            "password": "wrongpassword"
        })
        assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"
    
    def test_local_registration_duplicate_email(self):
        """POST /api/auth/register with existing email returns 409"""
        response = requests.post(f"{BASE_URL}/api/auth/register", json={
            "email": GUARDIAN_EMAIL,
            "password": "newpassword123",
            "full_name": "Test User"
        })
        assert response.status_code == 409, f"Expected 409 for duplicate email, got {response.status_code}: {response.text}"
    
    def test_local_registration_new_user_format(self):
        """POST /api/auth/register with new email returns 201 with correct format"""
        import random
        random_suffix = random.randint(10000, 99999)
        test_email = f"TEST_google_oauth_{random_suffix}@example.com"
        
        response = requests.post(f"{BASE_URL}/api/auth/register", json={
            "email": test_email,
            "password": "testpassword123",
            "full_name": "TEST Google OAuth User"
        })
        assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.text}"
        data = response.json()
        assert "access_token" in data, "Response should contain 'access_token'"
        assert "role" in data, "Response should contain 'role'"


class TestProtectedEndpointsWithJWT:
    """Test protected endpoints work with JWT from local login"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get auth token from local login"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": GUARDIAN_EMAIL,
            "password": GUARDIAN_PASSWORD
        })
        if response.status_code == 200:
            return response.json()["access_token"]
        pytest.skip("Login failed - cannot test protected endpoints")
    
    def test_voice_trigger_commands_with_auth(self, auth_token):
        """GET /api/voice-trigger/commands works with JWT"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(f"{BASE_URL}/api/voice-trigger/commands", headers=headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    
    def test_guardian_ai_chat_with_auth(self, auth_token):
        """POST /api/guardian-ai/chat works with JWT"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.post(f"{BASE_URL}/api/guardian-ai/chat", 
            headers=headers,
            json={"message": "test"}
        )
        # 200 OK or 400/422 for validation - not 401
        assert response.status_code != 401, f"Should not return 401 with valid token: {response.text}"
    
    def test_sos_history_with_auth(self, auth_token):
        """GET /api/sos/history works with JWT"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(f"{BASE_URL}/api/sos/history", headers=headers)
        # 200 or 404 (no history) - not 401
        assert response.status_code in [200, 404], f"Expected 200/404, got {response.status_code}: {response.text}"
    
    def test_fake_call_presets_with_auth(self, auth_token):
        """GET /api/fake-call/presets works with JWT"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(f"{BASE_URL}/api/fake-call/presets", headers=headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"


class TestCognitoStatus:
    """Test Cognito status endpoint still works"""
    
    def test_cognito_status_endpoint(self):
        """GET /api/auth/cognito-status returns 200"""
        response = requests.get(f"{BASE_URL}/api/auth/cognito-status")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "enabled" in data, "Response should contain 'enabled' field"
