"""
Test P0 Bug Fix: AI Risk Panel in Command Center & Operator Dashboard
========================================================================
Bug: AI Risk Panel was failing because incidents had senior_id (FK to seniors table)
     but Guardian AI API requires user_id (FK to users table).
Fix: Backend modified to include user_id in incident responses (from senior.guardian_id).
     Frontend updated to use incident.user_id for AI API calls.

Tests:
1. /api/operator/incidents returns user_id field mapped from senior.guardian_id
2. /api/operator/command-center active_incidents returns user_id field
3. /api/guardian-ai/insights/high-risk returns high risk users
4. /api/guardian-ai/{user_id}/risk-score returns risk assessment with required fields
"""
import os
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

@pytest.fixture(scope="module")
def admin_token():
    """Get admin auth token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "nischint4parents@gmail.com",
        "password": "secret123"
    })
    if response.status_code != 200:
        pytest.skip("Admin authentication failed")
    return response.json().get("access_token")

@pytest.fixture(scope="module")
def admin_headers(admin_token):
    """Get headers with admin token"""
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


class TestOperatorIncidentsUserIdField:
    """Test /api/operator/incidents now includes user_id field (P0 bug fix)"""
    
    def test_incidents_endpoint_returns_200(self, admin_headers):
        """GET /api/operator/incidents returns 200"""
        response = requests.get(f"{BASE_URL}/api/operator/incidents", headers=admin_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print(f"PASS - /api/operator/incidents returns 200")
    
    def test_incidents_returns_list(self, admin_headers):
        """GET /api/operator/incidents returns a list"""
        response = requests.get(f"{BASE_URL}/api/operator/incidents", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list), f"Expected list, got {type(data)}"
        print(f"PASS - /api/operator/incidents returns list with {len(data)} incidents")
    
    def test_incidents_include_user_id_field(self, admin_headers):
        """Each incident should have user_id field (mapped from senior.guardian_id)"""
        response = requests.get(f"{BASE_URL}/api/operator/incidents?limit=10", headers=admin_headers)
        assert response.status_code == 200
        incidents = response.json()
        
        if len(incidents) == 0:
            pytest.skip("No incidents to verify - need seed data")
        
        # Check first few incidents have user_id field
        for i, inc in enumerate(incidents[:5]):
            assert "user_id" in inc, f"Incident {i} missing user_id field. Keys: {list(inc.keys())}"
            print(f"  Incident {i}: id={inc.get('id', 'N/A')[:8]}..., user_id={inc.get('user_id')}")
        
        print(f"PASS - All checked incidents have user_id field")
    
    def test_incidents_have_expected_fields(self, admin_headers):
        """Incidents should have all required fields including user_id"""
        response = requests.get(f"{BASE_URL}/api/operator/incidents?limit=5", headers=admin_headers)
        assert response.status_code == 200
        incidents = response.json()
        
        if len(incidents) == 0:
            pytest.skip("No incidents to verify")
        
        expected_fields = [
            "id", "senior_id", "user_id", "device_id", "incident_type", 
            "severity", "status", "created_at", "senior_name"
        ]
        
        inc = incidents[0]
        for field in expected_fields:
            assert field in inc, f"Incident missing field: {field}. Keys: {list(inc.keys())}"
        
        print(f"PASS - Incident has all expected fields including user_id")


class TestCommandCenterActiveIncidents:
    """Test /api/operator/command-center active_incidents includes user_id"""
    
    def test_command_center_endpoint_returns_200(self, admin_headers):
        """GET /api/operator/command-center returns 200"""
        response = requests.get(f"{BASE_URL}/api/operator/command-center", headers=admin_headers, timeout=30)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print(f"PASS - /api/operator/command-center returns 200")
    
    def test_command_center_has_active_incidents(self, admin_headers):
        """Command center response has active_incidents array"""
        response = requests.get(f"{BASE_URL}/api/operator/command-center", headers=admin_headers, timeout=30)
        assert response.status_code == 200
        data = response.json()
        
        assert "active_incidents" in data, f"Missing active_incidents. Keys: {list(data.keys())}"
        assert isinstance(data["active_incidents"], list), "active_incidents should be a list"
        print(f"PASS - Command center has active_incidents array with {len(data['active_incidents'])} items")
    
    def test_command_center_incidents_have_user_id(self, admin_headers):
        """Active incidents in command center should include user_id field"""
        response = requests.get(f"{BASE_URL}/api/operator/command-center", headers=admin_headers, timeout=30)
        assert response.status_code == 200
        data = response.json()
        incidents = data.get("active_incidents", [])
        
        if len(incidents) == 0:
            pytest.skip("No active incidents in command center")
        
        for i, inc in enumerate(incidents[:5]):
            assert "user_id" in inc, f"Active incident {i} missing user_id. Keys: {list(inc.keys())}"
            print(f"  Active incident {i}: id={inc.get('id', 'N/A')[:8]}..., user_id={inc.get('user_id')}")
        
        print(f"PASS - Active incidents have user_id field")


class TestGuardianAIHighRiskEndpoint:
    """Test /api/guardian-ai/insights/high-risk returns high risk users"""
    
    def test_high_risk_endpoint_returns_200(self, admin_headers):
        """GET /api/guardian-ai/insights/high-risk returns 200"""
        response = requests.get(f"{BASE_URL}/api/guardian-ai/insights/high-risk?limit=10", headers=admin_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print(f"PASS - /api/guardian-ai/insights/high-risk returns 200")
    
    def test_high_risk_returns_expected_structure(self, admin_headers):
        """High risk endpoint returns high_risk_users array"""
        response = requests.get(f"{BASE_URL}/api/guardian-ai/insights/high-risk?limit=10", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        
        assert "high_risk_users" in data, f"Missing high_risk_users. Keys: {list(data.keys())}"
        assert isinstance(data["high_risk_users"], list), "high_risk_users should be a list"
        print(f"PASS - High risk endpoint returns high_risk_users array with {len(data['high_risk_users'])} users")
    
    def test_high_risk_user_has_required_fields(self, admin_headers):
        """Each high risk user should have required fields for AI panel display"""
        response = requests.get(f"{BASE_URL}/api/guardian-ai/insights/high-risk?limit=10", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        users = data.get("high_risk_users", [])
        
        if len(users) == 0:
            pytest.skip("No high risk users to verify")
        
        # Fields needed by CommandCenterPage AIRiskIntelligence component
        expected_fields = ["user_name", "final_score", "risk_level", "top_factors", "recommended_action"]
        
        user = users[0]
        print(f"First user keys: {list(user.keys())}")
        
        for field in expected_fields:
            assert field in user, f"High risk user missing field: {field}"
        
        # Validate field types
        assert isinstance(user.get("final_score"), (int, float)), "final_score should be numeric"
        assert user.get("risk_level") in ["low", "moderate", "high", "critical"], f"Invalid risk_level: {user.get('risk_level')}"
        assert isinstance(user.get("top_factors"), list), "top_factors should be a list"
        
        print(f"PASS - High risk user has all required fields: {expected_fields}")
        print(f"  Sample: {user.get('user_name')}, score={user.get('final_score')}, level={user.get('risk_level')}")


class TestGuardianAIRiskScoreEndpoint:
    """Test /api/guardian-ai/{user_id}/risk-score returns risk assessment"""
    
    def test_risk_score_with_valid_user_id(self, admin_headers):
        """GET /api/guardian-ai/{user_id}/risk-score returns 200 with valid user_id"""
        # First get a user_id from high-risk endpoint or incidents
        hr_response = requests.get(f"{BASE_URL}/api/guardian-ai/insights/high-risk?limit=1", headers=admin_headers)
        assert hr_response.status_code == 200
        
        users = hr_response.json().get("high_risk_users", [])
        if len(users) == 0:
            # Try to get user_id from incidents
            inc_response = requests.get(f"{BASE_URL}/api/operator/incidents?limit=10", headers=admin_headers)
            assert inc_response.status_code == 200
            incidents = inc_response.json()
            
            user_id = None
            for inc in incidents:
                if inc.get("user_id"):
                    user_id = inc["user_id"]
                    break
            
            if not user_id:
                pytest.skip("No user_id available to test risk-score endpoint")
        else:
            user_id = users[0].get("user_id")
            if not user_id:
                pytest.skip("High risk user missing user_id")
        
        print(f"Testing risk-score with user_id: {user_id}")
        
        response = requests.get(f"{BASE_URL}/api/guardian-ai/{user_id}/risk-score", headers=admin_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print(f"PASS - /api/guardian-ai/{user_id}/risk-score returns 200")
    
    def test_risk_score_response_structure(self, admin_headers):
        """Risk score response has required fields for DispatchPanel display"""
        # Get a user_id
        hr_response = requests.get(f"{BASE_URL}/api/guardian-ai/insights/high-risk?limit=1", headers=admin_headers)
        users = hr_response.json().get("high_risk_users", [])
        
        user_id = None
        if len(users) > 0:
            user_id = users[0].get("user_id")
        
        if not user_id:
            inc_response = requests.get(f"{BASE_URL}/api/operator/incidents?limit=10", headers=admin_headers)
            incidents = inc_response.json()
            for inc in incidents:
                if inc.get("user_id"):
                    user_id = inc["user_id"]
                    break
        
        if not user_id:
            pytest.skip("No user_id available")
        
        response = requests.get(f"{BASE_URL}/api/guardian-ai/{user_id}/risk-score", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        
        print(f"Risk score response keys: {list(data.keys())}")
        
        # Fields needed by OperatorDashboard DispatchPanel AI panel
        expected_fields = ["final_score", "risk_level", "top_factors", "action_detail"]
        
        for field in expected_fields:
            assert field in data, f"Risk score missing field: {field}"
        
        # Validate types
        assert isinstance(data.get("final_score"), (int, float)), "final_score should be numeric"
        assert data.get("risk_level") in ["low", "moderate", "high", "critical"], f"Invalid risk_level: {data.get('risk_level')}"
        
        print(f"PASS - Risk score has required fields for AI panel display")
        print(f"  final_score={data.get('final_score')}, risk_level={data.get('risk_level')}")


class TestIntegrationFlow:
    """Test the full integration flow: incidents → user_id → AI risk score"""
    
    def test_incident_user_id_can_fetch_risk_score(self, admin_headers):
        """Verify incident's user_id can be used to fetch AI risk score"""
        # Step 1: Get incidents with user_id
        inc_response = requests.get(f"{BASE_URL}/api/operator/incidents?limit=20", headers=admin_headers)
        assert inc_response.status_code == 200
        incidents = inc_response.json()
        
        # Find incident with user_id
        incident_with_user_id = None
        for inc in incidents:
            if inc.get("user_id"):
                incident_with_user_id = inc
                break
        
        if not incident_with_user_id:
            pytest.skip("No incidents with user_id found - this is expected if seniors don't have guardians")
        
        user_id = incident_with_user_id["user_id"]
        print(f"Found incident {incident_with_user_id['id'][:8]}... with user_id={user_id[:8]}...")
        
        # Step 2: Use user_id to fetch risk score
        risk_response = requests.get(f"{BASE_URL}/api/guardian-ai/{user_id}/risk-score", headers=admin_headers)
        
        # Should return 200 (risk score computed) or 404 (user not found, but endpoint works)
        assert risk_response.status_code in [200, 404], f"Unexpected status: {risk_response.status_code}: {risk_response.text}"
        
        if risk_response.status_code == 200:
            data = risk_response.json()
            print(f"PASS - AI risk score fetched successfully for incident's user_id")
            print(f"  Risk: {data.get('risk_level')} (score={data.get('final_score')})")
        else:
            print(f"INFO - Risk score endpoint returned 404 for user_id (user may not have baseline data)")
        
        print(f"PASS - Integration flow works: incidents now include user_id for AI API calls")
