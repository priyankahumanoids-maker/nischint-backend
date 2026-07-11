"""
Test Mobile Auth Registration Bug Fix

Tests for:
1. POST /api/auth/register - successful registration with valid data
2. POST /api/auth/register - duplicate email returns 409
3. POST /api/auth/register - short password (<8 chars) returns 422
4. POST /api/auth/register - missing required fields returns validation error
5. POST /api/auth/login - existing user can login
6. POST /api/auth/login - wrong password returns 401
7. GET /api/auth/me - returns user info with valid token
"""

import pytest
import requests
import os
import uuid

# Use the public URL from environment
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials from review_request
TEST_EMAIL = "nischint4parents@gmail.com"
TEST_PASSWORD = "secret123"


class TestAuthRegistration:
    """Tests for auth registration endpoint"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup for each test"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        yield
        self.session.close()

    def test_register_success_with_valid_data(self):
        """Test successful registration with all valid fields"""
        unique_email = f"TEST_register_{uuid.uuid4().hex[:8]}@example.com"
        
        payload = {
            "email": unique_email,
            "password": "testpass123",  # 8+ chars
            "full_name": "Test User Registration",
            "phone": "+1234567890"
        }
        
        response = self.session.post(f"{BASE_URL}/api/auth/register", json=payload)
        
        # Should return 201 Created
        assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.text}"
        
        data = response.json()
        # Verify response structure
        assert "access_token" in data, "Response should contain access_token"
        assert "token_type" in data, "Response should contain token_type"
        assert data["token_type"] == "bearer", "Token type should be bearer"
        assert "role" in data, "Response should contain role"
        assert data["role"] == "guardian", f"Role should be guardian, got {data['role']}"
        print(f"✅ Registration successful for {unique_email}")

    def test_register_without_phone_optional(self):
        """Test registration succeeds without phone (optional field)"""
        unique_email = f"TEST_nophone_{uuid.uuid4().hex[:8]}@example.com"
        
        payload = {
            "email": unique_email,
            "password": "testpass123",
            "full_name": "Test No Phone"
        }
        
        response = self.session.post(f"{BASE_URL}/api/auth/register", json=payload)
        
        # Should succeed - phone is optional
        assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "access_token" in data
        print(f"✅ Registration without phone succeeded for {unique_email}")

    def test_register_duplicate_email_returns_409(self):
        """Test that registering with duplicate email returns 409 Conflict"""
        # First, register a new user
        unique_email = f"TEST_dup_{uuid.uuid4().hex[:8]}@example.com"
        
        payload = {
            "email": unique_email,
            "password": "testpass123",
            "full_name": "First User"
        }
        
        # First registration should succeed
        response1 = self.session.post(f"{BASE_URL}/api/auth/register", json=payload)
        assert response1.status_code == 201, f"First registration failed: {response1.text}"
        
        # Second registration with same email should fail
        payload2 = {
            "email": unique_email,  # Same email
            "password": "differentpass123",
            "full_name": "Second User"
        }
        
        response2 = self.session.post(f"{BASE_URL}/api/auth/register", json=payload2)
        
        assert response2.status_code == 409, f"Expected 409 for duplicate email, got {response2.status_code}: {response2.text}"
        
        data = response2.json()
        assert "detail" in data, "Response should contain detail"
        assert "already exists" in data["detail"].lower(), f"Error message should mention email exists, got: {data['detail']}"
        print(f"✅ Duplicate email correctly returns 409")

    def test_register_short_password_returns_422(self):
        """Test that password < 8 chars returns 422 validation error"""
        unique_email = f"TEST_short_{uuid.uuid4().hex[:8]}@example.com"
        
        payload = {
            "email": unique_email,
            "password": "short",  # Only 5 chars, minimum is 8
            "full_name": "Short Password User"
        }
        
        response = self.session.post(f"{BASE_URL}/api/auth/register", json=payload)
        
        # Should return 422 Unprocessable Entity (Pydantic validation)
        assert response.status_code == 422, f"Expected 422 for short password, got {response.status_code}: {response.text}"
        
        data = response.json()
        # Pydantic validation errors return in detail array
        assert "detail" in data, "Response should contain detail"
        print(f"✅ Short password correctly returns 422 validation error")

    def test_register_missing_email_returns_422(self):
        """Test that missing email field returns validation error"""
        payload = {
            "password": "testpass123",
            "full_name": "No Email User"
        }
        
        response = self.session.post(f"{BASE_URL}/api/auth/register", json=payload)
        
        assert response.status_code == 422, f"Expected 422 for missing email, got {response.status_code}: {response.text}"
        print(f"✅ Missing email correctly returns 422")

    def test_register_missing_password_returns_422(self):
        """Test that missing password field returns validation error"""
        unique_email = f"TEST_nopass_{uuid.uuid4().hex[:8]}@example.com"
        
        payload = {
            "email": unique_email,
            "full_name": "No Password User"
        }
        
        response = self.session.post(f"{BASE_URL}/api/auth/register", json=payload)
        
        assert response.status_code == 422, f"Expected 422 for missing password, got {response.status_code}: {response.text}"
        print(f"✅ Missing password correctly returns 422")

    def test_register_missing_full_name_returns_422(self):
        """Test that missing full_name field returns validation error"""
        unique_email = f"TEST_noname_{uuid.uuid4().hex[:8]}@example.com"
        
        payload = {
            "email": unique_email,
            "password": "testpass123"
        }
        
        response = self.session.post(f"{BASE_URL}/api/auth/register", json=payload)
        
        assert response.status_code == 422, f"Expected 422 for missing full_name, got {response.status_code}: {response.text}"
        print(f"✅ Missing full_name correctly returns 422")

    def test_register_invalid_email_format_returns_422(self):
        """Test that invalid email format returns validation error"""
        payload = {
            "email": "not-an-email",  # Invalid format
            "password": "testpass123",
            "full_name": "Invalid Email User"
        }
        
        response = self.session.post(f"{BASE_URL}/api/auth/register", json=payload)
        
        assert response.status_code == 422, f"Expected 422 for invalid email, got {response.status_code}: {response.text}"
        print(f"✅ Invalid email format correctly returns 422")


class TestAuthLogin:
    """Tests for auth login endpoint"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup for each test"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        yield
        self.session.close()

    def test_login_existing_user_success(self):
        """Test login with valid credentials (existing user)"""
        payload = {
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        }
        
        response = self.session.post(f"{BASE_URL}/api/auth/login", json=payload)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        # Verify response structure
        assert "access_token" in data, "Response should contain access_token"
        assert "token_type" in data, "Response should contain token_type"
        assert data["token_type"] == "bearer"
        assert "role" in data, "Response should contain role"
        assert len(data["access_token"]) > 0, "Token should not be empty"
        print(f"✅ Login successful for {TEST_EMAIL}, role: {data['role']}")

    def test_login_wrong_password_returns_401(self):
        """Test login with wrong password returns 401"""
        payload = {
            "email": TEST_EMAIL,
            "password": "wrongpassword123"
        }
        
        response = self.session.post(f"{BASE_URL}/api/auth/login", json=payload)
        
        assert response.status_code == 401, f"Expected 401 for wrong password, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "detail" in data, "Response should contain error detail"
        print(f"✅ Wrong password correctly returns 401")

    def test_login_nonexistent_user_returns_401(self):
        """Test login with non-existent email returns 401"""
        payload = {
            "email": "nonexistent_user_xyz@example.com",
            "password": "anypassword123"
        }
        
        response = self.session.post(f"{BASE_URL}/api/auth/login", json=payload)
        
        assert response.status_code == 401, f"Expected 401 for non-existent user, got {response.status_code}: {response.text}"
        print(f"✅ Non-existent user correctly returns 401")

    def test_login_missing_email_returns_422(self):
        """Test login with missing email returns 422"""
        payload = {
            "password": "anypassword"
        }
        
        response = self.session.post(f"{BASE_URL}/api/auth/login", json=payload)
        
        assert response.status_code == 422, f"Expected 422 for missing email, got {response.status_code}: {response.text}"
        print(f"✅ Missing email in login correctly returns 422")

    def test_login_missing_password_returns_422(self):
        """Test login with missing password returns 422"""
        payload = {
            "email": TEST_EMAIL
        }
        
        response = self.session.post(f"{BASE_URL}/api/auth/login", json=payload)
        
        assert response.status_code == 422, f"Expected 422 for missing password, got {response.status_code}: {response.text}"
        print(f"✅ Missing password in login correctly returns 422")


class TestAuthMe:
    """Tests for GET /api/auth/me endpoint"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup for each test"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        yield
        self.session.close()

    def get_auth_token(self):
        """Helper to get valid auth token"""
        response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        if response.status_code == 200:
            return response.json().get("access_token")
        return None

    def test_me_with_valid_token(self):
        """Test GET /api/auth/me returns user info with valid token"""
        token = self.get_auth_token()
        assert token is not None, "Failed to obtain auth token"
        
        headers = {"Authorization": f"Bearer {token}"}
        response = self.session.get(f"{BASE_URL}/api/auth/me", headers=headers)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        # Verify user info structure
        assert "id" in data, "Response should contain id"
        assert "email" in data, "Response should contain email"
        assert data["email"] == TEST_EMAIL, f"Email should be {TEST_EMAIL}, got {data['email']}"
        assert "role" in data, "Response should contain role"
        assert "full_name" in data, "Response should contain full_name"
        print(f"✅ GET /api/auth/me returned user: {data['email']}, role: {data['role']}")

    def test_me_without_token_returns_401(self):
        """Test GET /api/auth/me without token returns 401"""
        response = self.session.get(f"{BASE_URL}/api/auth/me")
        
        # Should return 401 or 403 without auth
        assert response.status_code in [401, 403], f"Expected 401/403 without token, got {response.status_code}: {response.text}"
        print(f"✅ GET /api/auth/me without token correctly returns {response.status_code}")

    def test_me_with_invalid_token_returns_401(self):
        """Test GET /api/auth/me with invalid token returns 401"""
        headers = {"Authorization": "Bearer invalid_token_12345"}
        response = self.session.get(f"{BASE_URL}/api/auth/me", headers=headers)
        
        assert response.status_code in [401, 403], f"Expected 401/403 with invalid token, got {response.status_code}: {response.text}"
        print(f"✅ GET /api/auth/me with invalid token correctly returns {response.status_code}")


class TestCognitoStatus:
    """Test Cognito status endpoint (public, no auth needed)"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup for each test"""
        self.session = requests.Session()
        yield
        self.session.close()

    def test_cognito_status_endpoint(self):
        """Test GET /api/auth/cognito-status is accessible without auth"""
        response = self.session.get(f"{BASE_URL}/api/auth/cognito-status")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "enabled" in data, "Response should contain enabled field"
        print(f"✅ Cognito status: enabled={data['enabled']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
