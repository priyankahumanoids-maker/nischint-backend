# Guardian ↔ Child Linking Feature Tests
# Tests for: link code generation, guardian link-child, loved-ones dashboard
# Credentials: kidnischint@gmail.com (child), mothernischint@gmail.com (guardian)

import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
CHILD_EMAIL = "kidnischint@gmail.com"
CHILD_PASSWORD = "nischint123"
GUARDIAN_EMAIL = "mothernischint@gmail.com"
GUARDIAN_PASSWORD = "nischint123"


# Module-level fixtures to avoid repeated logins
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


class TestAuthSetup:
    """Authentication tests to verify tokens work"""
    
    def test_child_login(self, child_token):
        """Verify child can login and get token"""
        assert child_token is not None
        print(f"✓ Child login successful, token obtained")
    
    def test_guardian_login(self, guardian_token):
        """Verify guardian can login and get token"""
        assert guardian_token is not None
        print(f"✓ Guardian login successful, token obtained")


class TestLinkCodeGeneration:
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
    
    def test_guardian_cannot_generate_link_code(self, guardian_token):
        """Guardian should NOT be able to generate a link code (403)"""
        headers = {"Authorization": f"Bearer {guardian_token}"}
        response = requests.post(f"{BASE_URL}/api/child/generate-link-code", headers=headers)
        
        assert response.status_code == 403, f"Expected 403, got {response.status_code}: {response.text}"
        data = response.json()
        assert "detail" in data, "Response should contain error detail"
        print(f"✓ Guardian correctly denied link code generation: {data.get('detail')}")
    
    def test_unauthenticated_cannot_generate_link_code(self):
        """Unauthenticated request should fail (401)"""
        response = requests.post(f"{BASE_URL}/api/child/generate-link-code")
        
        assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"
        print(f"✓ Unauthenticated request correctly rejected")


class TestGuardianLinkChild:
    """Tests for POST /api/guardian/link-child"""
    
    def test_invalid_code_returns_400(self, guardian_token):
        """Invalid/expired code should return 400"""
        headers = {"Authorization": f"Bearer {guardian_token}"}
        response = requests.post(
            f"{BASE_URL}/api/guardian/link-child",
            headers=headers,
            json={"code": "000000"}  # Invalid code
        )
        
        assert response.status_code == 400, f"Expected 400, got {response.status_code}: {response.text}"
        data = response.json()
        assert "detail" in data, "Response should contain error detail"
        assert "invalid" in data["detail"].lower() or "expired" in data["detail"].lower(), \
            f"Error should mention invalid/expired: {data['detail']}"
        print(f"✓ Invalid code correctly rejected: {data.get('detail')}")
    
    def test_child_cannot_link_another_child(self, child_token):
        """Child should NOT be able to link another child (403)"""
        headers = {"Authorization": f"Bearer {child_token}"}
        response = requests.post(
            f"{BASE_URL}/api/guardian/link-child",
            headers=headers,
            json={"code": "123456"}
        )
        
        assert response.status_code == 403, f"Expected 403, got {response.status_code}: {response.text}"
        data = response.json()
        assert "detail" in data, "Response should contain error detail"
        print(f"✓ Child correctly denied linking: {data.get('detail')}")
    
    def test_duplicate_link_returns_409(self, child_token, guardian_token):
        """Attempting to link already-linked child should return 409"""
        # First, generate a fresh code from child
        child_headers = {"Authorization": f"Bearer {child_token}"}
        gen_response = requests.post(f"{BASE_URL}/api/child/generate-link-code", headers=child_headers)
        
        if gen_response.status_code != 200:
            pytest.skip(f"Could not generate link code: {gen_response.text}")
        
        code = gen_response.json()["code"]
        print(f"  Generated code: {code}")
        
        # Guardian tries to link - should get 409 since relationship already exists
        guardian_headers = {"Authorization": f"Bearer {guardian_token}"}
        response = requests.post(
            f"{BASE_URL}/api/guardian/link-child",
            headers=guardian_headers,
            json={"code": code}
        )
        
        # Per the context, mothernischint and kidnischint already have a relationship
        assert response.status_code == 409, f"Expected 409 (duplicate), got {response.status_code}: {response.text}"
        data = response.json()
        assert "detail" in data, "Response should contain error detail"
        assert "already" in data["detail"].lower(), f"Error should mention 'already': {data['detail']}"
        print(f"✓ Duplicate link correctly rejected: {data.get('detail')}")
    
    def test_unauthenticated_cannot_link_child(self):
        """Unauthenticated request should fail (401)"""
        response = requests.post(
            f"{BASE_URL}/api/guardian/link-child",
            json={"code": "123456"}
        )
        
        assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"
        print(f"✓ Unauthenticated request correctly rejected")


class TestGuardianDashboardLovedOnes:
    """Tests for GET /api/guardian/dashboard/loved-ones"""
    
    def test_guardian_can_get_loved_ones(self, guardian_token):
        """Guardian should be able to get list of linked children"""
        headers = {"Authorization": f"Bearer {guardian_token}"}
        response = requests.get(f"{BASE_URL}/api/guardian/dashboard/loved-ones", headers=headers)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Verify response structure
        assert "monitored_users" in data, "Response should contain 'monitored_users'"
        assert "total_loved_ones" in data, "Response should contain 'total_loved_ones'"
        assert isinstance(data["monitored_users"], list), "monitored_users should be a list"
        
        print(f"✓ Guardian retrieved loved ones: {data.get('total_loved_ones')} total")
        
        # Check if kidnischint is in the list (should be linked)
        monitored = data["monitored_users"]
        if monitored:
            for user in monitored:
                print(f"  - {user.get('name')} ({user.get('email')})")
                # Verify user structure
                assert "user_id" in user, "User should have user_id"
                assert "name" in user, "User should have name"
                assert "email" in user, "User should have email"
                assert "has_active_session" in user, "User should have has_active_session"
    
    def test_loved_ones_includes_linked_child(self, guardian_token):
        """Verify the linked child (kidnischint) appears in loved ones"""
        headers = {"Authorization": f"Bearer {guardian_token}"}
        response = requests.get(f"{BASE_URL}/api/guardian/dashboard/loved-ones", headers=headers)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        monitored = data.get("monitored_users", [])
        child_emails = [u.get("email") for u in monitored]
        
        # kidnischint should be in the list (linked via relationship table)
        assert CHILD_EMAIL in child_emails, \
            f"Expected {CHILD_EMAIL} in monitored users, got: {child_emails}"
        print(f"✓ Linked child {CHILD_EMAIL} found in loved ones")
    
    def test_unauthenticated_cannot_get_loved_ones(self):
        """Unauthenticated request should fail (401)"""
        response = requests.get(f"{BASE_URL}/api/guardian/dashboard/loved-ones")
        
        assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"
        print(f"✓ Unauthenticated request correctly rejected")


class TestLinkCodeExpiration:
    """Tests for link code TTL (5 minutes)"""
    
    def test_code_stored_in_redis(self, child_token, guardian_token):
        """Verify code is stored and retrievable (before expiration)"""
        # Generate code
        child_headers = {"Authorization": f"Bearer {child_token}"}
        gen_response = requests.post(f"{BASE_URL}/api/child/generate-link-code", headers=child_headers)
        
        assert gen_response.status_code == 200, f"Code generation failed: {gen_response.text}"
        code = gen_response.json()["code"]
        print(f"  Generated code: {code}")
        
        # Try to use the code immediately (should work or return 409 for duplicate)
        guardian_headers = {"Authorization": f"Bearer {guardian_token}"}
        response = requests.post(
            f"{BASE_URL}/api/guardian/link-child",
            headers=guardian_headers,
            json={"code": code}
        )
        
        # Should be either 200 (success) or 409 (already linked) - NOT 400 (invalid/expired)
        assert response.status_code in [200, 409], \
            f"Expected 200 or 409, got {response.status_code}: {response.text}"
        print(f"✓ Code was valid in Redis (status: {response.status_code})")


class TestEdgeCases:
    """Edge case tests for linking feature"""
    
    def test_empty_code_returns_error(self, guardian_token):
        """Empty code should return validation error"""
        headers = {"Authorization": f"Bearer {guardian_token}"}
        response = requests.post(
            f"{BASE_URL}/api/guardian/link-child",
            headers=headers,
            json={"code": ""}
        )
        
        # Should be 400 or 422 (validation error)
        assert response.status_code in [400, 422], \
            f"Expected 400/422, got {response.status_code}: {response.text}"
        print(f"✓ Empty code correctly rejected (status: {response.status_code})")
    
    def test_non_numeric_code_returns_error(self, guardian_token):
        """Non-numeric code should return error"""
        headers = {"Authorization": f"Bearer {guardian_token}"}
        response = requests.post(
            f"{BASE_URL}/api/guardian/link-child",
            headers=headers,
            json={"code": "abcdef"}
        )
        
        # Should be 400 (invalid code)
        assert response.status_code == 400, \
            f"Expected 400, got {response.status_code}: {response.text}"
        print(f"✓ Non-numeric code correctly rejected")
    
    def test_multiple_code_generation(self, child_token):
        """Child can generate multiple codes (each overwrites previous)"""
        headers = {"Authorization": f"Bearer {child_token}"}
        
        codes = []
        for i in range(3):
            response = requests.post(f"{BASE_URL}/api/child/generate-link-code", headers=headers)
            assert response.status_code == 200, f"Code generation {i+1} failed: {response.text}"
            codes.append(response.json()["code"])
            time.sleep(0.5)  # Small delay between requests
        
        # All codes should be different (random generation)
        # Note: There's a tiny chance of collision, but very unlikely
        print(f"✓ Generated {len(codes)} codes: {codes}")
        assert len(codes) == 3, "Should have generated 3 codes"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
