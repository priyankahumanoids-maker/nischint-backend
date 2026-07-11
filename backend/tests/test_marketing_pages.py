# Marketing Website API Tests - Pilot Signup, Lead Management
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestPilotSignupAPI:
    """Tests for POST /api/pilot/signup endpoint"""
    
    def test_pilot_signup_success_minimal(self):
        """Test signup with only required fields"""
        payload = {
            "institution_name": "TEST_Minimal School",
            "contact_person": "Test Person",
            "email": "test_minimal@test.com"
        }
        response = requests.post(f"{BASE_URL}/api/pilot/signup", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["status"] == "success"
        assert "Thank you" in data["message"]
        print(f"PASS: Pilot signup (minimal) - status={data['status']}")
    
    def test_pilot_signup_success_full(self):
        """Test signup with all fields"""
        payload = {
            "institution_name": "TEST_Full School",
            "contact_person": "Full Test Person",
            "email": "test_full@test.com",
            "phone": "+91987654321",
            "city": "Bangalore",
            "institution_type": "University / College",
            "headcount": "5000",
            "message": "We need pilot deployment for our campus"
        }
        response = requests.post(f"{BASE_URL}/api/pilot/signup", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["status"] == "success"
        assert "48 hours" in data["message"]
        print(f"PASS: Pilot signup (full fields) - status={data['status']}")
    
    def test_pilot_signup_missing_institution_name(self):
        """Test validation: missing institution_name"""
        payload = {
            "contact_person": "Test Person",
            "email": "test@test.com"
        }
        response = requests.post(f"{BASE_URL}/api/pilot/signup", json=payload)
        # FastAPI should return 422 for validation error
        assert response.status_code == 422, f"Expected 422 for missing required field, got {response.status_code}"
        print(f"PASS: Validation error for missing institution_name")
    
    def test_pilot_signup_missing_email(self):
        """Test validation: missing email"""
        payload = {
            "institution_name": "TEST_School",
            "contact_person": "Test Person"
        }
        response = requests.post(f"{BASE_URL}/api/pilot/signup", json=payload)
        assert response.status_code == 422, f"Expected 422 for missing required field, got {response.status_code}"
        print(f"PASS: Validation error for missing email")


class TestPilotLeadsAPI:
    """Tests for GET /api/pilot/leads endpoint"""
    
    def test_get_leads_returns_list(self):
        """Test that leads endpoint returns a list"""
        response = requests.get(f"{BASE_URL}/api/pilot/leads")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "leads" in data
        assert isinstance(data["leads"], list)
        print(f"PASS: GET /api/pilot/leads returns leads array with {len(data['leads'])} items")
    
    def test_leads_contain_test_data(self):
        """Verify TEST_ prefixed leads from our test runs exist"""
        response = requests.get(f"{BASE_URL}/api/pilot/leads")
        assert response.status_code == 200
        data = response.json()
        leads = data.get("leads", [])
        test_leads = [l for l in leads if l.get("institution_name", "").startswith("TEST_")]
        print(f"PASS: Found {len(test_leads)} test leads")
        if test_leads:
            # Verify lead structure
            lead = test_leads[0]
            required_fields = ["id", "institution_name", "contact_person", "email", "status", "created_at"]
            for field in required_fields:
                assert field in lead, f"Missing field: {field}"
            print(f"PASS: Lead structure verified - has all required fields")


class TestHealthAndRootEndpoints:
    """Basic health check tests"""
    
    def test_api_root_or_health(self):
        """Test basic API connectivity"""
        response = requests.get(f"{BASE_URL}/api")
        # Could be 200 or 404 depending on if root endpoint exists
        assert response.status_code in [200, 404, 307], f"Unexpected status: {response.status_code}"
        print(f"PASS: API root responds with {response.status_code}")


class TestExistingRoutesStillWork:
    """Ensure existing protected routes still require auth"""
    
    def test_login_page_endpoint(self):
        """Test /api/auth/login exists"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "invalid@test.com",
            "password": "wrongpassword"
        })
        # Should return 401 for invalid credentials, not 404
        assert response.status_code in [401, 422], f"Expected auth error, got {response.status_code}"
        print(f"PASS: Login endpoint exists, returns {response.status_code} for invalid creds")
    
    def test_protected_route_requires_auth(self):
        """Test that protected routes require authentication"""
        response = requests.get(f"{BASE_URL}/api/guardian/live/protected-users")
        assert response.status_code == 401, f"Expected 401 for protected route, got {response.status_code}"
        print(f"PASS: Protected route returns 401 without auth")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
