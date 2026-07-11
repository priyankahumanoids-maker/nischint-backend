# Test Guardian Self-Registration Feature
# Tests POST /api/auth/register endpoint with various scenarios

import os
import time
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL')
if BASE_URL:
    BASE_URL = BASE_URL.rstrip('/')

class TestGuardianRegistration:
    """Guardian self-registration endpoint tests"""
    
    # Module 1: Registration with valid data
    def test_register_with_valid_data_returns_201_and_jwt(self):
        """POST /api/auth/register with valid data returns 201 + JWT token + role=guardian"""
        timestamp = int(time.time() * 1000)
        response = requests.post(f"{BASE_URL}/api/auth/register", json={
            "email": f"pytest-reg-{timestamp}@test.com",
            "password": "testpass123",
            "full_name": "Test Guardian",
            "phone": "+919876543210"
        })
        
        assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.text}"
        data = response.json()
        assert "access_token" in data, "Response should contain access_token"
        assert data["token_type"] == "bearer", "Token type should be bearer"
        assert data["role"] == "guardian", f"Role should be guardian, got {data['role']}"
        assert len(data["access_token"]) > 50, "Access token should be a valid JWT"
    
    def test_register_without_phone_works(self):
        """POST /api/auth/register without phone (optional field) works"""
        timestamp = int(time.time() * 1000)
        response = requests.post(f"{BASE_URL}/api/auth/register", json={
            "email": f"pytest-nophone-{timestamp}@test.com",
            "password": "testpass123",
            "full_name": "No Phone User"
        })
        
        assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["role"] == "guardian"
    
    # Module 2: Duplicate email validation
    def test_register_duplicate_email_returns_409(self):
        """POST /api/auth/register with duplicate email returns 409"""
        response = requests.post(f"{BASE_URL}/api/auth/register", json={
            "email": "nischint4parents@gmail.com",  # Existing guardian
            "password": "testpass123",
            "full_name": "Duplicate Test"
        })
        
        assert response.status_code == 409, f"Expected 409, got {response.status_code}: {response.text}"
        data = response.json()
        assert "already exists" in data.get("detail", "").lower(), "Should indicate email already exists"
    
    # Module 3: Password validation
    def test_register_short_password_returns_422(self):
        """POST /api/auth/register with password < 8 chars returns 422"""
        timestamp = int(time.time() * 1000)
        response = requests.post(f"{BASE_URL}/api/auth/register", json={
            "email": f"pytest-short-{timestamp}@test.com",
            "password": "short",  # Less than 8 characters
            "full_name": "Short Password User"
        })
        
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        data = response.json()
        detail = data.get("detail", [])
        assert any("password" in str(d).lower() and "8" in str(d) for d in detail), "Should indicate password too short"
    
    # Module 4: Missing required fields validation
    def test_register_missing_password_returns_422(self):
        """POST /api/auth/register without password returns 422"""
        response = requests.post(f"{BASE_URL}/api/auth/register", json={
            "email": "missing-pw@test.com",
            "full_name": "No Password"
        })
        
        assert response.status_code == 422, f"Expected 422, got {response.status_code}"
        data = response.json()
        detail = data.get("detail", [])
        assert any("password" in str(d).lower() and "required" in str(d).lower() for d in detail)
    
    def test_register_missing_full_name_returns_422(self):
        """POST /api/auth/register without full_name returns 422"""
        response = requests.post(f"{BASE_URL}/api/auth/register", json={
            "email": "missing-name@test.com",
            "password": "testpass123"
        })
        
        assert response.status_code == 422, f"Expected 422, got {response.status_code}"
        data = response.json()
        detail = data.get("detail", [])
        assert any("full_name" in str(d).lower() and "required" in str(d).lower() for d in detail)
    
    def test_register_missing_email_returns_422(self):
        """POST /api/auth/register without email returns 422"""
        response = requests.post(f"{BASE_URL}/api/auth/register", json={
            "password": "testpass123",
            "full_name": "No Email User"
        })
        
        assert response.status_code == 422, f"Expected 422, got {response.status_code}"


class TestNewUserAccess:
    """Tests that newly registered users can access guardian endpoints"""
    
    @pytest.fixture
    def new_user_token(self):
        """Create a new user and return their token"""
        timestamp = int(time.time() * 1000)
        response = requests.post(f"{BASE_URL}/api/auth/register", json={
            "email": f"pytest-access-{timestamp}@test.com",
            "password": "testpass123",
            "full_name": "Access Test User"
        })
        assert response.status_code == 201
        return response.json()["access_token"]
    
    def test_newly_registered_user_can_login(self):
        """Newly registered user can login via POST /api/auth/login"""
        timestamp = int(time.time() * 1000)
        email = f"pytest-login-{timestamp}@test.com"
        password = "testpass123"
        
        # Register
        reg_response = requests.post(f"{BASE_URL}/api/auth/register", json={
            "email": email,
            "password": password,
            "full_name": "Login Test User"
        })
        assert reg_response.status_code == 201
        
        # Login with same credentials
        login_response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": email,
            "password": password
        })
        assert login_response.status_code == 200, f"Login failed: {login_response.text}"
        data = login_response.json()
        assert "access_token" in data
        assert data["role"] == "guardian"
    
    def test_newly_registered_user_can_access_dashboard(self, new_user_token):
        """Newly registered user can access GET /api/dashboard/summary"""
        response = requests.get(
            f"{BASE_URL}/api/dashboard/summary",
            headers={"Authorization": f"Bearer {new_user_token}"}
        )
        assert response.status_code == 200, f"Dashboard access failed: {response.text}"
        data = response.json()
        # New user should have 0 seniors, 0 devices, 0 incidents
        assert "total_seniors" in data
        assert "total_devices" in data
        assert "active_incidents" in data
    
    def test_newly_registered_user_cannot_access_operator_endpoints(self, new_user_token):
        """Newly registered user (guardian) cannot access operator endpoints (403)"""
        response = requests.get(
            f"{BASE_URL}/api/operator/notification-jobs/stats",
            headers={"Authorization": f"Bearer {new_user_token}"}
        )
        assert response.status_code == 403, f"Expected 403, got {response.status_code}"
        assert "permission" in response.json().get("detail", "").lower()


class TestRegressionExistingLogin:
    """Regression tests to ensure existing login still works"""
    
    def test_existing_guardian_login_works(self):
        """Existing guardian login still works (regression)"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "nischint4parents@gmail.com",
            "password": "secret123"
        })
        assert response.status_code == 200, f"Guardian login failed: {response.text}"
        data = response.json()
        assert data["role"] == "guardian"
        assert "access_token" in data
    
    def test_existing_operator_login_works(self):
        """Existing operator login still works (regression)"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "operator@nischint.com",
            "password": "operator123"
        })
        assert response.status_code == 200, f"Operator login failed: {response.text}"
        data = response.json()
        assert data["role"] == "operator"
        assert "access_token" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
