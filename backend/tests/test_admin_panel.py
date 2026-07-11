"""
Admin Panel API Tests — Phase 1 (RBAC Corrected)
Aligned with backend:
- READ endpoints → admin + operator
- WRITE endpoints → admin only
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

ADMIN_EMAIL = "nischint4parents@gmail.com"
ADMIN_PASSWORD = "secret123"
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"


class TestAdminPanelRBAC:

    @pytest.fixture(scope="class")
    def admin_token(self):
        resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD
        })
        assert resp.status_code == 200, resp.text
        return resp.json()["access_token"]

    @pytest.fixture(scope="class")
    def operator_token(self):
        resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD
        })
        assert resp.status_code == 200, resp.text
        return resp.json()["access_token"]

    # ─────────────────────────────
    # ✅ READ ACCESS (Allowed)
    # ─────────────────────────────

    def test_operator_system_health_allowed(self, operator_token):
        resp = requests.get(f"{BASE_URL}/api/admin/system-health",
                            headers={"Authorization": f"Bearer {operator_token}"})
        assert resp.status_code == 200

    def test_operator_stats_allowed(self, operator_token):
        resp = requests.get(f"{BASE_URL}/api/admin/stats",
                            headers={"Authorization": f"Bearer {operator_token}"})
        assert resp.status_code == 200

    def test_operator_users_list_allowed(self, operator_token):
        resp = requests.get(f"{BASE_URL}/api/admin/users",
                            headers={"Authorization": f"Bearer {operator_token}"})
        assert resp.status_code == 200

    def test_operator_facilities_list_allowed(self, operator_token):
        resp = requests.get(f"{BASE_URL}/api/admin/facilities",
                            headers={"Authorization": f"Bearer {operator_token}"})
        assert resp.status_code == 200

    # ─────────────────────────────
    # ❌ WRITE ACCESS (Denied)
    # ─────────────────────────────

    def test_operator_create_user_denied(self, operator_token):
        resp = requests.post(f"{BASE_URL}/api/admin/users",
                             headers={"Authorization": f"Bearer {operator_token}"},
                             json={"email": "x@test.com", "password": "123456", "role": "guardian"})
        assert resp.status_code == 403

    def test_operator_create_facility_denied(self, operator_token):
        resp = requests.post(f"{BASE_URL}/api/admin/facilities",
                             headers={"Authorization": f"Bearer {operator_token}"},
                             json={"name": "X", "code": "X123"})
        assert resp.status_code == 403

    def test_no_token_denied(self):
        resp = requests.get(f"{BASE_URL}/api/admin/system-health")
        assert resp.status_code == 401


class TestUserManagement:

    @pytest.fixture(scope="class")
    def admin_token(self):
        resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD
        })
        return resp.json()["access_token"]

    def test_list_users(self, admin_token):
        resp = requests.get(f"{BASE_URL}/api/admin/users",
                            headers={"Authorization": f"Bearer {admin_token}"})
        data = resp.json()

        assert resp.status_code == 200
        assert "users" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data


class TestFacilityManagement:

    @pytest.fixture(scope="class")
    def admin_token(self):
        resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD
        })
        return resp.json()["access_token"]

    def test_create_and_delete_facility(self, admin_token):
        import uuid
        code = f"T_{uuid.uuid4().hex[:5]}"

        # Create
        resp = requests.post(f"{BASE_URL}/api/admin/facilities",
                             headers={"Authorization": f"Bearer {admin_token}"},
                             json={"name": "Test", "code": code})

        assert resp.status_code == 201
        fac_id = resp.json()["id"]

        # Delete
        resp = requests.delete(f"{BASE_URL}/api/admin/facilities/{fac_id}",
                               headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200


class TestSystemHealth:

    @pytest.fixture(scope="class")
    def admin_token(self):
        resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD
        })
        return resp.json()["access_token"]

    def test_health_structure(self, admin_token):
        resp = requests.get(f"{BASE_URL}/api/admin/system-health",
                            headers={"Authorization": f"Bearer {admin_token}"})
        data = resp.json()

        assert resp.status_code == 200
        assert data["status"] in ["healthy", "degraded"]
        assert "users" in data
        assert "facilities" in data
        assert "services" in data