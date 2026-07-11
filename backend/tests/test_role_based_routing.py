"""
Test suite for role-based routing and login API verification
Tests the fix for: Operator was redirected to Family Dashboard (incorrect)
Expected behavior: parent→/family, child→/family, operator→/command-center, admin→/admin
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL')

# Test credentials
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "nischint123"
GUARDIAN_EMAIL = "mothernischint@gmail.com"
GUARDIAN_PASSWORD = "nischint123"
ADMIN_EMAIL = "nischint4parents@gmail.com"
ADMIN_PASSWORD = "secret123"


class TestLoginHealthEndpoint:
    """Test the /api/auth/login-health endpoint"""
    
    def test_login_health_returns_200(self):
        """Test that login-health endpoint returns 200 OK"""
        response = requests.get(f"{BASE_URL}/api/auth/login-health")
        assert response.status_code == 200
        print("✅ /api/auth/login-health returns 200")
    
    def test_login_health_returns_json(self):
        """Test that login-health returns valid JSON with status field"""
        response = requests.get(f"{BASE_URL}/api/auth/login-health")
        data = response.json()
        assert "status" in data
        assert data["status"] == "ok"
        print(f"✅ /api/auth/login-health returns JSON: {data}")


class TestOperatorLogin:
    """Test operator login and role verification"""
    
    def test_operator_login_returns_correct_role(self):
        """Test that operator login returns role='operator'"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Verify role field
        assert "role" in data
        assert data["role"] == "operator"
        
        # Verify token exists
        assert "access_token" in data
        assert len(data["access_token"]) > 0
        
        print(f"✅ Operator login returns role='operator'")
    
    def test_operator_login_returns_valid_token(self):
        """Test that operator login returns a valid JWT token"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD}
        )
        data = response.json()
        
        # Token should be a JWT (three parts separated by dots)
        token = data["access_token"]
        token_parts = token.split(".")
        assert len(token_parts) == 3
        
        print(f"✅ Operator login returns valid JWT token")


class TestGuardianLogin:
    """Test guardian/mother login and role verification"""
    
    def test_guardian_login_returns_correct_role(self):
        """Test that guardian login returns role='guardian'"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": GUARDIAN_EMAIL, "password": GUARDIAN_PASSWORD}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Verify role field
        assert "role" in data
        assert data["role"] == "guardian"
        
        # Verify token exists
        assert "access_token" in data
        
        print(f"✅ Guardian login returns role='guardian'")


class TestAdminLogin:
    """Test admin login and role verification"""
    
    def test_admin_login_returns_correct_role(self):
        """Test that admin login returns role='admin'"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Verify role field
        assert "role" in data
        assert data["role"] == "admin"
        
        # Verify token exists
        assert "access_token" in data
        
        print(f"✅ Admin login returns role='admin'")


class TestInvalidLogin:
    """Test invalid login scenarios"""
    
    def test_invalid_credentials_returns_error(self):
        """Test that invalid credentials return appropriate error"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "invalid@example.com", "password": "wrongpassword"}
        )
        # Should return 401 or 400 for invalid credentials
        assert response.status_code in [400, 401]
        print(f"✅ Invalid login returns error status: {response.status_code}")
    
    def test_missing_password_returns_error(self):
        """Test that missing password returns error"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": OPERATOR_EMAIL}
        )
        # Should return error for missing field
        assert response.status_code in [400, 422]
        print(f"✅ Missing password returns error status: {response.status_code}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
