# Test AWS Cognito Auth Integration - LOCAL MODE
# Tests the dual-mode auth system when Cognito is NOT enabled
# All tests validate LOCAL JWT fallback behavior

import os
import pytest
import requests
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
TEST_GUARDIAN_EMAIL = "nischint4parents@gmail.com"
TEST_GUARDIAN_PASSWORD = "secret123"


class TestCognitoStatus:
    """Test Cognito status endpoint - should report disabled"""

    def test_cognito_status_returns_disabled(self):
        """GET /api/auth/cognito-status should return enabled=false in local mode"""
        response = requests.get(f"{BASE_URL}/api/auth/cognito-status")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        # Validate response structure
        assert "enabled" in data, "Missing 'enabled' field"
        assert "region" in data, "Missing 'region' field"
        assert "user_pool_id" in data, "Missing 'user_pool_id' field"
        
        # Validate local mode values
        assert data["enabled"] is False, "Cognito should be disabled in local mode"
        assert data["region"] == "", "Region should be empty when disabled"
        assert data["user_pool_id"] == "", "User pool ID should be empty when disabled"
        print(f"PASS: Cognito status returns disabled: {data}")


class TestLoginLocalMode:
    """Test login endpoint in local JWT mode"""

    def test_login_success_returns_correct_response_shape(self):
        """POST /api/auth/login should return proper token response with auth_provider=local"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_GUARDIAN_EMAIL, "password": TEST_GUARDIAN_PASSWORD}
        )
        assert response.status_code == 200, f"Login failed: {response.text}"
        data = response.json()
        
        # Validate required fields
        assert "access_token" in data, "Missing access_token"
        assert "token_type" in data, "Missing token_type"
        assert "role" in data, "Missing role"
        assert "auth_provider" in data, "Missing auth_provider field"
        
        # Validate field values
        assert data["token_type"] == "bearer", f"Expected bearer, got {data['token_type']}"
        assert data["role"] == "guardian", f"Expected guardian role, got {data['role']}"
        assert data["auth_provider"] == "local", f"Expected local auth_provider, got {data['auth_provider']}"
        
        # Optional Cognito fields should be null in local mode
        assert data.get("refresh_token") is None, "refresh_token should be null in local mode"
        assert data.get("cognito_id_token") is None, "cognito_id_token should be null in local mode"
        
        # Validate token is a non-empty string
        assert isinstance(data["access_token"], str), "access_token should be string"
        assert len(data["access_token"]) > 0, "access_token should not be empty"
        
        print(f"PASS: Login returns correct response shape with auth_provider=local")

    def test_login_invalid_credentials_returns_401(self):
        """POST /api/auth/login with wrong password should return 401"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_GUARDIAN_EMAIL, "password": "wrongpassword"}
        )
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        data = response.json()
        assert "detail" in data, "Missing error detail"
        print(f"PASS: Invalid credentials return 401: {data['detail']}")

    def test_login_nonexistent_user_returns_401(self):
        """POST /api/auth/login with non-existent email should return 401"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "nonexistent@test.com", "password": "anypassword"}
        )
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: Non-existent user returns 401")


class TestRegisterLocalMode:
    """Test registration endpoint in local JWT mode"""

    def test_register_success_returns_correct_response_shape(self):
        """POST /api/auth/register should return proper token response with auth_provider=local"""
        unique_email = f"test_reg_{uuid.uuid4().hex[:8]}@test.com"
        response = requests.post(
            f"{BASE_URL}/api/auth/register",
            json={
                "email": unique_email,
                "password": "testpassword123",
                "full_name": "Test Registration User",
                "phone": "+919876543210"
            }
        )
        assert response.status_code == 201, f"Registration failed: {response.text}"
        data = response.json()
        
        # Validate required fields
        assert "access_token" in data, "Missing access_token"
        assert "token_type" in data, "Missing token_type"
        assert "role" in data, "Missing role"
        assert "auth_provider" in data, "Missing auth_provider field"
        
        # Validate field values
        assert data["token_type"] == "bearer", f"Expected bearer, got {data['token_type']}"
        assert data["role"] == "guardian", f"Expected guardian role, got {data['role']}"
        assert data["auth_provider"] == "local", f"Expected local auth_provider, got {data['auth_provider']}"
        
        # Optional Cognito fields should be null in local mode
        assert data.get("refresh_token") is None, "refresh_token should be null in local mode"
        assert data.get("cognito_id_token") is None, "cognito_id_token should be null in local mode"
        
        print(f"PASS: Registration returns correct response shape with auth_provider=local")

    def test_register_duplicate_email_returns_409(self):
        """POST /api/auth/register with existing email should return 409"""
        response = requests.post(
            f"{BASE_URL}/api/auth/register",
            json={
                "email": TEST_GUARDIAN_EMAIL,  # Already exists
                "password": "anypassword123",
                "full_name": "Duplicate User"
            }
        )
        assert response.status_code == 409, f"Expected 409, got {response.status_code}"
        data = response.json()
        assert "detail" in data, "Missing error detail"
        assert "already exists" in data["detail"].lower(), f"Unexpected error: {data['detail']}"
        print(f"PASS: Duplicate email returns 409: {data['detail']}")

    def test_register_validates_email_format(self):
        """POST /api/auth/register with invalid email should return 422"""
        response = requests.post(
            f"{BASE_URL}/api/auth/register",
            json={
                "email": "invalid-email-format",
                "password": "testpassword123",
                "full_name": "Test User"
            }
        )
        assert response.status_code == 422, f"Expected 422 for invalid email, got {response.status_code}"
        print("PASS: Invalid email format returns 422")


class TestRefreshEndpointLocalMode:
    """Test token refresh endpoint - should reject in local mode"""

    def test_refresh_rejected_in_local_mode(self):
        """POST /api/auth/refresh should return 400 when Cognito is not enabled"""
        response = requests.post(
            f"{BASE_URL}/api/auth/refresh",
            json={"refresh_token": "any_token_value"}
        )
        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        data = response.json()
        assert "detail" in data, "Missing error detail"
        assert "Token refresh requires Cognito auth" in data["detail"], f"Unexpected error: {data['detail']}"
        print(f"PASS: Refresh rejected in local mode: {data['detail']}")


class TestConfirmEndpointLocalMode:
    """Test confirmation endpoint - should reject in local mode"""

    def test_confirm_rejected_in_local_mode(self):
        """POST /api/auth/confirm should return 400 when Cognito is not enabled"""
        response = requests.post(
            f"{BASE_URL}/api/auth/confirm",
            json={"email": "test@test.com", "code": "123456"}
        )
        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        data = response.json()
        assert "detail" in data, "Missing error detail"
        assert "Cognito not enabled" in data["detail"], f"Unexpected error: {data['detail']}"
        print(f"PASS: Confirm rejected in local mode: {data['detail']}")


class TestProtectedEndpointsWithLocalJWT:
    """Test that protected endpoints still work with local JWT tokens"""

    @pytest.fixture
    def auth_token(self):
        """Get authentication token"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_GUARDIAN_EMAIL, "password": TEST_GUARDIAN_PASSWORD}
        )
        assert response.status_code == 200, f"Login failed: {response.text}"
        return response.json()["access_token"]

    def test_my_seniors_endpoint_with_local_jwt(self, auth_token):
        """GET /api/my/seniors should work with local JWT"""
        response = requests.get(
            f"{BASE_URL}/api/my/seniors",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200, f"Protected endpoint failed: {response.text}"
        data = response.json()
        assert isinstance(data, list), "Expected list of seniors"
        print(f"PASS: /api/my/seniors works with local JWT (found {len(data)} seniors)")

    def test_guardian_ai_endpoint_with_local_jwt(self, auth_token):
        """GET /api/guardian-ai/status should work with local JWT"""
        response = requests.get(
            f"{BASE_URL}/api/guardian-ai/status",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200, f"Guardian AI status failed: {response.text}"
        print("PASS: /api/guardian-ai/status works with local JWT")

    def test_voice_trigger_commands_with_local_jwt(self, auth_token):
        """GET /api/voice-trigger/commands should work with local JWT"""
        response = requests.get(
            f"{BASE_URL}/api/voice-trigger/commands",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200, f"Voice trigger commands failed: {response.text}"
        data = response.json()
        assert "commands" in data, "Missing commands in response"
        print(f"PASS: /api/voice-trigger/commands works with local JWT (found {len(data['commands'])} commands)")

    def test_fake_call_trigger_with_local_jwt(self, auth_token):
        """POST /api/fake-call/trigger should work with local JWT"""
        response = requests.post(
            f"{BASE_URL}/api/fake-call/trigger",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={"senior_id": None, "delay_seconds": 0}
        )
        # 200 or 404 (if no senior) are acceptable - both mean auth worked
        assert response.status_code in [200, 404], f"Fake call trigger failed: {response.text}"
        print(f"PASS: /api/fake-call/trigger auth works with local JWT (status: {response.status_code})")

    def test_sos_trigger_with_local_jwt(self, auth_token):
        """POST /api/sos/trigger should work with local JWT"""
        response = requests.post(
            f"{BASE_URL}/api/sos/trigger",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={"senior_id": None, "message": "Test SOS", "location": None}
        )
        # 200 or 404 (if no senior) are acceptable
        assert response.status_code in [200, 404], f"SOS trigger failed: {response.text}"
        print(f"PASS: /api/sos/trigger auth works with local JWT (status: {response.status_code})")

    def test_protected_endpoint_without_token_returns_401(self):
        """Protected endpoints should return 401 without token"""
        response = requests.get(f"{BASE_URL}/api/my/seniors")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: Protected endpoint returns 401 without token")

    def test_protected_endpoint_with_invalid_token_returns_401(self):
        """Protected endpoints should return 401 with invalid token"""
        response = requests.get(
            f"{BASE_URL}/api/my/seniors",
            headers={"Authorization": "Bearer invalid_token_here"}
        )
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: Protected endpoint returns 401 with invalid token")


class TestBackwardCompatibility:
    """Test backward compatibility with existing users"""

    def test_existing_user_can_login(self):
        """Existing user nischint4parents@gmail.com can still login with password"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_GUARDIAN_EMAIL, "password": TEST_GUARDIAN_PASSWORD}
        )
        assert response.status_code == 200, f"Existing user login failed: {response.text}"
        data = response.json()
        assert data["auth_provider"] == "local", "Existing user should use local auth"
        assert data["role"] == "guardian", "Role should be guardian"
        print(f"PASS: Existing user {TEST_GUARDIAN_EMAIL} can login with local auth")

    def test_existing_user_token_works_on_endpoints(self):
        """Token from existing user should work on all protected endpoints"""
        # Login
        login_resp = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_GUARDIAN_EMAIL, "password": TEST_GUARDIAN_PASSWORD}
        )
        token = login_resp.json()["access_token"]
        
        # Test multiple endpoints
        endpoints = [
            "/api/my/seniors",
            "/api/guardian-ai/status",
            "/api/voice-trigger/commands",
        ]
        
        for endpoint in endpoints:
            response = requests.get(
                f"{BASE_URL}{endpoint}",
                headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200, f"Endpoint {endpoint} failed with existing user token"
        
        print(f"PASS: Existing user token works on {len(endpoints)} protected endpoints")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
