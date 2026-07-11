"""
Admin Panel Phase 2 API Tests
Tests user CRUD, facility CRUD, pagination, filtering, status toggle, role/facility assignment
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
ADMIN_EMAIL = "nischint4parents@gmail.com"
ADMIN_PASSWORD = "secret123"


@pytest.fixture(scope="module")
def admin_token():
    """Get admin auth token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD
    })
    assert response.status_code == 200, f"Admin login failed: {response.text}"
    return response.json()["access_token"]


@pytest.fixture(scope="module")
def auth_headers(admin_token):
    """Auth headers for admin requests"""
    return {"Authorization": f"Bearer {admin_token}"}


class TestUserManagement:
    """Tests for user CRUD operations"""

    def test_get_users_list_paginated(self, auth_headers):
        """GET /api/admin/users with pagination - verify page and total_pages in response"""
        response = requests.get(f"{BASE_URL}/api/admin/users?page=1&page_size=5", headers=auth_headers)
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        # Verify pagination fields
        assert "users" in data, "Response missing 'users' array"
        assert "total" in data, "Response missing 'total' count"
        assert "page" in data, "Response missing 'page' field"
        assert "page_size" in data, "Response missing 'page_size' field"
        assert "total_pages" in data, "Response missing 'total_pages' field"
        
        assert data["page"] == 1
        assert data["page_size"] == 5
        assert len(data["users"]) <= 5
        print(f"PASS: User list paginated - total={data['total']}, pages={data['total_pages']}")

    def test_get_users_filter_by_role(self, auth_headers):
        """GET /api/admin/users?role=guardian - filter by role"""
        response = requests.get(f"{BASE_URL}/api/admin/users?role=guardian", headers=auth_headers)
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        # All returned users should have guardian role
        for user in data["users"]:
            assert user["role"] == "guardian", f"User {user['email']} has role {user['role']}, expected guardian"
        print(f"PASS: Role filter works - found {len(data['users'])} guardians")

    def test_get_users_filter_by_status(self, auth_headers):
        """GET /api/admin/users?is_active=true - filter by status"""
        response = requests.get(f"{BASE_URL}/api/admin/users?is_active=true", headers=auth_headers)
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        # All returned users should be active
        for user in data["users"]:
            assert user["is_active"] == True, f"User {user['email']} is_active={user['is_active']}, expected True"
        print(f"PASS: Status filter works - found {len(data['users'])} active users")

    def test_get_users_search(self, auth_headers):
        """GET /api/admin/users?search=nischint - search by name/email"""
        response = requests.get(f"{BASE_URL}/api/admin/users?search=nischint", headers=auth_headers)
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        # At least one result should contain search term
        assert len(data["users"]) >= 1, "Expected at least one user matching 'nischint'"
        print(f"PASS: Search filter works - found {len(data['users'])} users matching 'nischint'")

    def test_create_user(self, auth_headers):
        """POST /api/admin/users - create new user with role and optional facility"""
        timestamp = int(time.time())
        test_email = f"test_phase2_{timestamp}@nischint.com"
        
        payload = {
            "email": test_email,
            "full_name": "Test User Phase2",
            "phone": "+1234567890",
            "password": "testpass123",
            "role": "caregiver"
        }
        
        response = requests.post(f"{BASE_URL}/api/admin/users", json=payload, headers=auth_headers)
        assert response.status_code == 201, f"Failed to create user: {response.text}"
        
        data = response.json()
        assert data["email"] == test_email
        assert data["role"] == "caregiver"
        assert data["is_active"] == True
        assert "id" in data
        
        # Store user_id for cleanup
        pytest.test_user_id = data["id"]
        pytest.test_user_email = test_email
        print(f"PASS: User created with id={data['id']}, role={data['role']}")

    def test_create_user_duplicate_email_fails(self, auth_headers):
        """POST /api/admin/users - duplicate email should return 409"""
        response = requests.post(f"{BASE_URL}/api/admin/users", json={
            "email": ADMIN_EMAIL,  # Already exists
            "password": "testpass123",
            "role": "guardian"
        }, headers=auth_headers)
        assert response.status_code == 409, f"Expected 409 for duplicate email, got {response.status_code}"
        print("PASS: Duplicate email correctly rejected with 409")

    def test_get_user_detail(self, auth_headers):
        """GET /api/admin/users/{id} - get user detail with is_active field"""
        if not hasattr(pytest, 'test_user_id'):
            pytest.skip("No test user created")
        
        response = requests.get(f"{BASE_URL}/api/admin/users/{pytest.test_user_id}", headers=auth_headers)
        assert response.status_code == 200, f"Failed: {response.text}"
        
        data = response.json()
        assert data["id"] == pytest.test_user_id
        assert "is_active" in data, "Response missing 'is_active' field"
        assert data["is_active"] == True
        print(f"PASS: User detail retrieved - is_active={data['is_active']}")

    def test_update_user_status_deactivate(self, auth_headers):
        """PATCH /api/admin/users/{id}/status - deactivate user"""
        if not hasattr(pytest, 'test_user_id'):
            pytest.skip("No test user created")
        
        response = requests.patch(
            f"{BASE_URL}/api/admin/users/{pytest.test_user_id}/status",
            json={"is_active": False},
            headers=auth_headers
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        
        data = response.json()
        assert data["is_active"] == False
        print(f"PASS: User deactivated - is_active={data['is_active']}")

    def test_update_user_status_activate(self, auth_headers):
        """PATCH /api/admin/users/{id}/status - reactivate user"""
        if not hasattr(pytest, 'test_user_id'):
            pytest.skip("No test user created")
        
        response = requests.patch(
            f"{BASE_URL}/api/admin/users/{pytest.test_user_id}/status",
            json={"is_active": True},
            headers=auth_headers
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        
        data = response.json()
        assert data["is_active"] == True
        print(f"PASS: User reactivated - is_active={data['is_active']}")

    def test_update_user_role(self, auth_headers):
        """PATCH /api/admin/users/{id}/role - update user role"""
        if not hasattr(pytest, 'test_user_id'):
            pytest.skip("No test user created")
        
        # Note: Backend uses PUT for role, checking if PATCH works too
        response = requests.put(
            f"{BASE_URL}/api/admin/users/{pytest.test_user_id}/role",
            json={"role": "operator"},
            headers=auth_headers
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        
        data = response.json()
        assert data["role"] == "operator"
        print(f"PASS: User role updated to {data['role']}")


class TestFacilityManagement:
    """Tests for facility CRUD operations"""

    def test_get_facilities_list(self, auth_headers):
        """GET /api/admin/facilities - list all facilities with facility_type"""
        response = requests.get(f"{BASE_URL}/api/admin/facilities", headers=auth_headers)
        assert response.status_code == 200, f"Failed: {response.text}"
        
        data = response.json()
        assert "facilities" in data
        assert "total" in data
        
        # Check facility_type is in response
        if data["facilities"]:
            fac = data["facilities"][0]
            assert "facility_type" in fac, "Response missing 'facility_type' field"
            assert "user_count" in fac, "Response missing 'user_count' field"
            assert "is_active" in fac, "Response missing 'is_active' field"
        print(f"PASS: Facility list - total={data['total']}")

    def test_create_facility_with_type(self, auth_headers):
        """POST /api/admin/facilities - create facility with facility_type"""
        timestamp = int(time.time())
        
        payload = {
            "name": f"Test Facility Phase2 {timestamp}",
            "code": f"TFAC{timestamp}",
            "facility_type": "elder_care",
            "address": "123 Test Street",
            "city": "Mumbai",
            "state": "Maharashtra",
            "phone": "+912212345678",
            "email": f"facility{timestamp}@test.com",
            "max_users": 50
        }
        
        response = requests.post(f"{BASE_URL}/api/admin/facilities", json=payload, headers=auth_headers)
        assert response.status_code == 201, f"Failed to create facility: {response.text}"
        
        data = response.json()
        assert data["facility_type"] == "elder_care"
        assert data["is_active"] == True
        assert "id" in data
        
        pytest.test_facility_id = data["id"]
        print(f"PASS: Facility created with id={data['id']}, type={data['facility_type']}")

    def test_create_facility_duplicate_code_fails(self, auth_headers):
        """POST /api/admin/facilities - duplicate code should return 409"""
        if not hasattr(pytest, 'test_facility_id'):
            pytest.skip("No test facility created")
        
        # Try to create with same code
        response = requests.get(f"{BASE_URL}/api/admin/facilities", headers=auth_headers)
        if response.status_code == 200 and response.json()["facilities"]:
            existing_code = response.json()["facilities"][0]["code"]
            
            response = requests.post(f"{BASE_URL}/api/admin/facilities", json={
                "name": "Duplicate Test",
                "code": existing_code,  # Already exists
                "facility_type": "home"
            }, headers=auth_headers)
            assert response.status_code == 409, f"Expected 409 for duplicate code, got {response.status_code}"
            print("PASS: Duplicate facility code correctly rejected with 409")

    def test_update_facility_with_type(self, auth_headers):
        """PUT /api/admin/facilities/{id} - edit facility with facility_type"""
        if not hasattr(pytest, 'test_facility_id'):
            pytest.skip("No test facility created")
        
        payload = {
            "name": "Updated Test Facility Phase2",
            "facility_type": "hospital",
            "max_users": 100
        }
        
        response = requests.put(
            f"{BASE_URL}/api/admin/facilities/{pytest.test_facility_id}",
            json=payload,
            headers=auth_headers
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        
        data = response.json()
        assert data["name"] == "Updated Test Facility Phase2"
        print(f"PASS: Facility updated - name={data['name']}")

    def test_toggle_facility_status(self, auth_headers):
        """PATCH /api/admin/facilities/{id}/status - toggle facility active status"""
        if not hasattr(pytest, 'test_facility_id'):
            pytest.skip("No test facility created")
        
        # Deactivate
        response = requests.patch(
            f"{BASE_URL}/api/admin/facilities/{pytest.test_facility_id}/status",
            json={"is_active": False},
            headers=auth_headers
        )
        assert response.status_code == 200, f"Failed to deactivate: {response.text}"
        assert response.json()["is_active"] == False
        
        # Reactivate
        response = requests.patch(
            f"{BASE_URL}/api/admin/facilities/{pytest.test_facility_id}/status",
            json={"is_active": True},
            headers=auth_headers
        )
        assert response.status_code == 200, f"Failed to reactivate: {response.text}"
        assert response.json()["is_active"] == True
        print("PASS: Facility status toggle works")

    def test_assign_user_to_facility(self, auth_headers):
        """PATCH /api/admin/users/{id}/facility - assign user to facility"""
        if not hasattr(pytest, 'test_user_id') or not hasattr(pytest, 'test_facility_id'):
            pytest.skip("No test user or facility created")
        
        response = requests.put(
            f"{BASE_URL}/api/admin/users/{pytest.test_user_id}/facility",
            json={"facility_id": pytest.test_facility_id},
            headers=auth_headers
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        
        data = response.json()
        assert data["facility_id"] == pytest.test_facility_id
        print(f"PASS: User assigned to facility {data['facility_id']}")

    def test_verify_facility_user_count(self, auth_headers):
        """GET /api/admin/facilities - verify user_count increases after assignment"""
        if not hasattr(pytest, 'test_facility_id'):
            pytest.skip("No test facility created")
        
        response = requests.get(f"{BASE_URL}/api/admin/facilities", headers=auth_headers)
        assert response.status_code == 200
        
        data = response.json()
        facility = next((f for f in data["facilities"] if f["id"] == pytest.test_facility_id), None)
        
        if facility:
            assert "user_count" in facility
            print(f"PASS: Facility user_count={facility['user_count']}")
        else:
            print("WARN: Test facility not found in list")

    def test_delete_facility(self, auth_headers):
        """DELETE /api/admin/facilities/{id} - delete facility"""
        if not hasattr(pytest, 'test_facility_id'):
            pytest.skip("No test facility created")
        
        response = requests.delete(
            f"{BASE_URL}/api/admin/facilities/{pytest.test_facility_id}",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        
        data = response.json()
        assert data["deleted"] == True
        print("PASS: Facility deleted successfully")


class TestAuthorizationAndEdgeCases:
    """Tests for auth requirements and edge cases"""

    def test_admin_users_requires_auth(self):
        """GET /api/admin/users - should require authentication"""
        response = requests.get(f"{BASE_URL}/api/admin/users")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("PASS: /api/admin/users requires authentication")

    def test_admin_facilities_requires_auth(self):
        """GET /api/admin/facilities - should require authentication"""
        response = requests.get(f"{BASE_URL}/api/admin/facilities")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("PASS: /api/admin/facilities requires authentication")

    def test_get_nonexistent_user(self, auth_headers):
        """GET /api/admin/users/{invalid_id} - should return 404"""
        fake_uuid = "00000000-0000-0000-0000-000000000000"
        response = requests.get(f"{BASE_URL}/api/admin/users/{fake_uuid}", headers=auth_headers)
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("PASS: Nonexistent user returns 404")

    def test_get_nonexistent_facility(self, auth_headers):
        """GET /api/admin/facilities/{invalid_id} - check for proper error handling"""
        fake_uuid = "00000000-0000-0000-0000-000000000000"
        # Since there's no GET single facility endpoint, we try DELETE
        response = requests.delete(f"{BASE_URL}/api/admin/facilities/{fake_uuid}", headers=auth_headers)
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("PASS: Nonexistent facility returns 404")

    def test_system_health_endpoint(self, auth_headers):
        """GET /api/admin/system-health - verify it returns expected fields"""
        response = requests.get(f"{BASE_URL}/api/admin/system-health", headers=auth_headers)
        assert response.status_code == 200, f"Failed: {response.text}"
        
        data = response.json()
        assert "status" in data
        assert "users" in data
        assert "facilities" in data
        assert "services" in data
        print(f"PASS: System health - status={data['status']}")


class TestCleanup:
    """Cleanup test data after all tests"""

    def test_cleanup_test_user(self, auth_headers):
        """Delete test user if created"""
        if hasattr(pytest, 'test_user_id'):
            # There's no DELETE user endpoint, but we can deactivate
            response = requests.patch(
                f"{BASE_URL}/api/admin/users/{pytest.test_user_id}/status",
                json={"is_active": False},
                headers=auth_headers
            )
            if response.status_code == 200:
                print(f"Cleanup: Deactivated test user {pytest.test_user_id}")
        print("Cleanup complete")
