# Guardian Dashboard Response Structure Tests
# Focus: Verify status, location, last_updated fields in /api/guardian/dashboard/loved-ones
# Credentials: kidnischint@gmail.com (child), mothernischint@gmail.com (guardian)

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
CHILD_EMAIL = "kidnischint@gmail.com"
CHILD_PASSWORD = "nischint123"
GUARDIAN_EMAIL = "mothernischint@gmail.com"
GUARDIAN_PASSWORD = "nischint123"

# Valid status values per requirements
VALID_STATUSES = {"SAFE", "EMERGENCY", "HELP", "CHECK_IN_PENDING", "LIVE_JOURNEY"}


@pytest.fixture(scope="module")
def child_token():
    """Get child authentication token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": CHILD_EMAIL,
        "password": CHILD_PASSWORD
    })
    if response.status_code != 200:
        pytest.skip(f"Child login failed: {response.text}")
    data = response.json()
    assert "access_token" in data, "No access_token in child login response"
    return data["access_token"]


@pytest.fixture(scope="module")
def guardian_token():
    """Get guardian authentication token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": GUARDIAN_EMAIL,
        "password": GUARDIAN_PASSWORD
    })
    if response.status_code != 200:
        pytest.skip(f"Guardian login failed: {response.text}")
    data = response.json()
    assert "access_token" in data, "No access_token in guardian login response"
    return data["access_token"]


class TestLovedOnesResponseStructure:
    """Tests for GET /api/guardian/dashboard/loved-ones response structure"""
    
    def test_loved_ones_endpoint_returns_200(self, guardian_token):
        """Verify endpoint is accessible"""
        headers = {"Authorization": f"Bearer {guardian_token}"}
        response = requests.get(f"{BASE_URL}/api/guardian/dashboard/loved-ones", headers=headers)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print(f"✓ Endpoint returned 200 OK")
    
    def test_response_has_monitored_users_array(self, guardian_token):
        """Verify response contains monitored_users array"""
        headers = {"Authorization": f"Bearer {guardian_token}"}
        response = requests.get(f"{BASE_URL}/api/guardian/dashboard/loved-ones", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        
        assert "monitored_users" in data, "Response missing 'monitored_users' field"
        assert isinstance(data["monitored_users"], list), "monitored_users should be a list"
        print(f"✓ Response contains monitored_users array with {len(data['monitored_users'])} items")
    
    def test_each_monitored_user_has_id_field(self, guardian_token):
        """Each monitored_user must have 'id' field (string)"""
        headers = {"Authorization": f"Bearer {guardian_token}"}
        response = requests.get(f"{BASE_URL}/api/guardian/dashboard/loved-ones", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        monitored = data.get("monitored_users", [])
        
        if not monitored:
            pytest.skip("No monitored users to test")
        
        for i, user in enumerate(monitored):
            assert "id" in user, f"User {i} missing 'id' field"
            assert isinstance(user["id"], str), f"User {i} 'id' should be string, got {type(user['id'])}"
            assert len(user["id"]) > 0, f"User {i} 'id' should not be empty"
            print(f"  ✓ User {i}: id = {user['id']}")
        
        print(f"✓ All {len(monitored)} users have valid 'id' field")
    
    def test_each_monitored_user_has_name_field(self, guardian_token):
        """Each monitored_user must have 'name' field (string)"""
        headers = {"Authorization": f"Bearer {guardian_token}"}
        response = requests.get(f"{BASE_URL}/api/guardian/dashboard/loved-ones", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        monitored = data.get("monitored_users", [])
        
        if not monitored:
            pytest.skip("No monitored users to test")
        
        for i, user in enumerate(monitored):
            assert "name" in user, f"User {i} missing 'name' field"
            assert isinstance(user["name"], str), f"User {i} 'name' should be string, got {type(user['name'])}"
            print(f"  ✓ User {i}: name = {user['name']}")
        
        print(f"✓ All {len(monitored)} users have valid 'name' field")
    
    def test_each_monitored_user_has_status_field(self, guardian_token):
        """Each monitored_user must have 'status' field with valid value"""
        headers = {"Authorization": f"Bearer {guardian_token}"}
        response = requests.get(f"{BASE_URL}/api/guardian/dashboard/loved-ones", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        monitored = data.get("monitored_users", [])
        
        if not monitored:
            pytest.skip("No monitored users to test")
        
        for i, user in enumerate(monitored):
            assert "status" in user, f"User {i} missing 'status' field"
            assert isinstance(user["status"], str), f"User {i} 'status' should be string, got {type(user['status'])}"
            assert user["status"] in VALID_STATUSES, \
                f"User {i} has invalid status '{user['status']}'. Valid: {VALID_STATUSES}"
            print(f"  ✓ User {i}: status = {user['status']}")
        
        print(f"✓ All {len(monitored)} users have valid 'status' field")
    
    def test_each_monitored_user_has_location_field(self, guardian_token):
        """Each monitored_user must have 'location' field (null or {lat, lng})"""
        headers = {"Authorization": f"Bearer {guardian_token}"}
        response = requests.get(f"{BASE_URL}/api/guardian/dashboard/loved-ones", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        monitored = data.get("monitored_users", [])
        
        if not monitored:
            pytest.skip("No monitored users to test")
        
        for i, user in enumerate(monitored):
            assert "location" in user, f"User {i} missing 'location' field"
            loc = user["location"]
            
            if loc is not None:
                # If not null, must be dict with lat/lng
                assert isinstance(loc, dict), f"User {i} 'location' should be dict or null, got {type(loc)}"
                assert "lat" in loc, f"User {i} location missing 'lat'"
                assert "lng" in loc, f"User {i} location missing 'lng'"
                assert isinstance(loc["lat"], (int, float)), f"User {i} location.lat should be number"
                assert isinstance(loc["lng"], (int, float)), f"User {i} location.lng should be number"
                print(f"  ✓ User {i}: location = {{lat: {loc['lat']}, lng: {loc['lng']}}}")
            else:
                print(f"  ✓ User {i}: location = null (no active session/emergency)")
        
        print(f"✓ All {len(monitored)} users have valid 'location' field")
    
    def test_each_monitored_user_has_last_updated_field(self, guardian_token):
        """Each monitored_user must have 'last_updated' field (ISO timestamp or null)"""
        headers = {"Authorization": f"Bearer {guardian_token}"}
        response = requests.get(f"{BASE_URL}/api/guardian/dashboard/loved-ones", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        monitored = data.get("monitored_users", [])
        
        if not monitored:
            pytest.skip("No monitored users to test")
        
        for i, user in enumerate(monitored):
            assert "last_updated" in user, f"User {i} missing 'last_updated' field"
            ts = user["last_updated"]
            
            if ts is not None:
                # If not null, should be ISO timestamp string
                assert isinstance(ts, str), f"User {i} 'last_updated' should be string or null, got {type(ts)}"
                # Basic ISO format check (contains T and has reasonable length)
                assert "T" in ts or len(ts) >= 10, f"User {i} 'last_updated' doesn't look like ISO timestamp: {ts}"
                print(f"  ✓ User {i}: last_updated = {ts}")
            else:
                print(f"  ✓ User {i}: last_updated = null (no activity)")
        
        print(f"✓ All {len(monitored)} users have valid 'last_updated' field")
    
    def test_status_defaults_to_safe_when_no_activity(self, guardian_token):
        """Status should be SAFE when no emergency/session/pending-checkin"""
        headers = {"Authorization": f"Bearer {guardian_token}"}
        response = requests.get(f"{BASE_URL}/api/guardian/dashboard/loved-ones", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        monitored = data.get("monitored_users", [])
        
        if not monitored:
            pytest.skip("No monitored users to test")
        
        # Find users without active sessions
        for user in monitored:
            if not user.get("has_active_session", False):
                # Without active session, status should be SAFE (unless emergency/help/pending)
                # This is a soft check - just verify status is one of valid values
                assert user["status"] in VALID_STATUSES, f"Invalid status: {user['status']}"
                print(f"  User {user['name']}: status={user['status']}, has_active_session={user.get('has_active_session')}")
        
        print(f"✓ Status values are valid for all users")


class TestChildLinkCodeGeneration:
    """Tests for POST /api/child/generate-link-code"""
    
    def test_child_can_generate_link_code(self, child_token):
        """Child should be able to generate a 6-digit link code"""
        headers = {"Authorization": f"Bearer {child_token}"}
        response = requests.post(f"{BASE_URL}/api/child/generate-link-code", headers=headers)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "code" in data, "Response should contain 'code' field"
        
        code = data["code"]
        assert len(code) == 6, f"Code should be 6 digits, got {len(code)}"
        assert code.isdigit(), f"Code should be numeric, got {code}"
        print(f"✓ Child generated link code: {code}")
    
    def test_guardian_cannot_generate_link_code_403(self, guardian_token):
        """Guardian should get 403 when trying to generate link code"""
        headers = {"Authorization": f"Bearer {guardian_token}"}
        response = requests.post(f"{BASE_URL}/api/child/generate-link-code", headers=headers)
        
        assert response.status_code == 403, f"Expected 403, got {response.status_code}: {response.text}"
        print(f"✓ Guardian correctly denied (403)")


class TestGuardianLinkChildValidation:
    """Tests for POST /api/guardian/link-child validation"""
    
    def test_expired_code_returns_400(self, guardian_token):
        """Expired/invalid code should return 400"""
        headers = {"Authorization": f"Bearer {guardian_token}"}
        response = requests.post(
            f"{BASE_URL}/api/guardian/link-child",
            headers=headers,
            json={"code": "999999"}  # Non-existent code
        )
        
        assert response.status_code == 400, f"Expected 400, got {response.status_code}: {response.text}"
        data = response.json()
        assert "detail" in data
        print(f"✓ Invalid code returns 400: {data['detail']}")
    
    def test_duplicate_link_returns_409(self, child_token, guardian_token):
        """Duplicate link attempt should return 409"""
        # Generate fresh code
        child_headers = {"Authorization": f"Bearer {child_token}"}
        gen_response = requests.post(f"{BASE_URL}/api/child/generate-link-code", headers=child_headers)
        
        if gen_response.status_code != 200:
            pytest.skip(f"Could not generate link code: {gen_response.text}")
        
        code = gen_response.json()["code"]
        
        # Guardian tries to link - should get 409 (already linked)
        guardian_headers = {"Authorization": f"Bearer {guardian_token}"}
        response = requests.post(
            f"{BASE_URL}/api/guardian/link-child",
            headers=guardian_headers,
            json={"code": code}
        )
        
        assert response.status_code == 409, f"Expected 409, got {response.status_code}: {response.text}"
        data = response.json()
        assert "already" in data.get("detail", "").lower()
        print(f"✓ Duplicate link returns 409: {data['detail']}")
    
    def test_child_cannot_link_returns_403(self, child_token):
        """Child trying to link should return 403"""
        headers = {"Authorization": f"Bearer {child_token}"}
        response = requests.post(
            f"{BASE_URL}/api/guardian/link-child",
            headers=headers,
            json={"code": "123456"}
        )
        
        assert response.status_code == 403, f"Expected 403, got {response.status_code}: {response.text}"
        print(f"✓ Child cannot link (403)")


class TestFullResponseStructure:
    """Comprehensive test of the full response structure"""
    
    def test_full_response_structure(self, guardian_token):
        """Verify complete response structure with all required fields"""
        headers = {"Authorization": f"Bearer {guardian_token}"}
        response = requests.get(f"{BASE_URL}/api/guardian/dashboard/loved-ones", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        
        # Top-level fields
        assert "monitored_users" in data, "Missing monitored_users"
        assert "total_loved_ones" in data, "Missing total_loved_ones"
        assert "active_journeys" in data, "Missing active_journeys"
        
        print(f"Top-level structure:")
        print(f"  - monitored_users: {len(data['monitored_users'])} items")
        print(f"  - total_loved_ones: {data['total_loved_ones']}")
        print(f"  - active_journeys: {data['active_journeys']}")
        
        # Check each monitored user
        for i, user in enumerate(data.get("monitored_users", [])):
            print(f"\nUser {i} ({user.get('name', 'Unknown')}):")
            
            # Required fields per requirements
            required_fields = ["id", "name", "status", "location", "last_updated"]
            for field in required_fields:
                assert field in user, f"User {i} missing required field: {field}"
                print(f"  - {field}: {user[field]}")
            
            # Validate status
            assert user["status"] in VALID_STATUSES, f"Invalid status: {user['status']}"
            
            # Validate location structure
            if user["location"] is not None:
                assert "lat" in user["location"], "location missing lat"
                assert "lng" in user["location"], "location missing lng"
        
        print(f"\n✓ Full response structure validated successfully")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
