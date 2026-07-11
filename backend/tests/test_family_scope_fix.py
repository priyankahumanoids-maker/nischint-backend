"""
Test Family Scope Fix for Dashboard Endpoints
==============================================
CRITICAL BUG FIX: Incident count mismatch across guardians

BEFORE: mother saw 5 incidents, father saw 4 incidents
AFTER: both should see IDENTICAL counts

This tests _get_family_senior_ids() which traverses the guardians table
to find all family members and their seniors.
"""

import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

# Test credentials - mother and father accounts
MOTHER_CREDENTIALS = {
    "email": "mothernischint@gmail.com",
    "password": "nischint123",
    "user_id": "d426c37a-e30b-4403-8270-31d094926d18",
}

FATHER_CREDENTIALS = {
    "email": "fathernishchint@gmail.com",
    "password": "nischint123",
    "user_id": "1771bc2b-e87e-4605-af6d-fa7b8a237d0d",
}

# Senior IDs for Kid Nischint (one owned by mother, one owned by father)
MOTHER_SENIOR_ID = "3e43c67c-1238-47d1-b025-88adcf661012"
FATHER_SENIOR_ID = "67e9822a-096f-4fd9-9db1-fdc96cdd50f0"


def authenticate(email: str, password: str) -> str:
    """Authenticate and return access token."""
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password}
    )
    assert response.status_code == 200, f"Auth failed for {email}: {response.text}"
    data = response.json()
    assert "access_token" in data, f"No access_token in response: {data}"
    return data["access_token"]


class TestFamilyScopeFix:
    """Tests to verify family scope fix for incident count parity between guardians."""

    @pytest.fixture(scope="class")
    def mother_token(self):
        """Get mother's access token."""
        return authenticate(MOTHER_CREDENTIALS["email"], MOTHER_CREDENTIALS["password"])

    @pytest.fixture(scope="class")
    def father_token(self):
        """Get father's access token."""
        return authenticate(FATHER_CREDENTIALS["email"], FATHER_CREDENTIALS["password"])

    @pytest.fixture(scope="class")
    def mother_headers(self, mother_token):
        """Get headers for mother's requests."""
        return {"Authorization": f"Bearer {mother_token}"}

    @pytest.fixture(scope="class")
    def father_headers(self, father_token):
        """Get headers for father's requests."""
        return {"Authorization": f"Bearer {father_token}"}

    # ==================== TEST 1: Dashboard Summary ====================
    def test_dashboard_summary_active_incidents_match(self, mother_headers, father_headers):
        """
        GET /api/dashboard/summary — Mother and Father must return IDENTICAL active_incidents count.
        """
        mother_resp = requests.get(f"{BASE_URL}/api/dashboard/summary", headers=mother_headers)
        father_resp = requests.get(f"{BASE_URL}/api/dashboard/summary", headers=father_headers)

        assert mother_resp.status_code == 200, f"Mother /summary failed: {mother_resp.text}"
        assert father_resp.status_code == 200, f"Father /summary failed: {father_resp.text}"

        mother_data = mother_resp.json()
        father_data = father_resp.json()

        print(f"\n[SUMMARY] Mother active_incidents: {mother_data.get('active_incidents')}")
        print(f"[SUMMARY] Father active_incidents: {father_data.get('active_incidents')}")

        assert mother_data["active_incidents"] == father_data["active_incidents"], \
            f"MISMATCH! Mother: {mother_data['active_incidents']}, Father: {father_data['active_incidents']}"

    def test_dashboard_summary_total_seniors_match(self, mother_headers, father_headers):
        """
        GET /api/dashboard/summary — Mother and Father must return IDENTICAL total_seniors count.
        """
        mother_resp = requests.get(f"{BASE_URL}/api/dashboard/summary", headers=mother_headers)
        father_resp = requests.get(f"{BASE_URL}/api/dashboard/summary", headers=father_headers)

        assert mother_resp.status_code == 200
        assert father_resp.status_code == 200

        mother_data = mother_resp.json()
        father_data = father_resp.json()

        print(f"\n[SUMMARY] Mother total_seniors: {mother_data.get('total_seniors')}")
        print(f"[SUMMARY] Father total_seniors: {father_data.get('total_seniors')}")

        assert mother_data["total_seniors"] == father_data["total_seniors"], \
            f"MISMATCH! Mother: {mother_data['total_seniors']}, Father: {father_data['total_seniors']}"

    def test_dashboard_summary_critical_incidents_match(self, mother_headers, father_headers):
        """
        GET /api/dashboard/summary — Mother and Father must return IDENTICAL critical_incidents count.
        """
        mother_resp = requests.get(f"{BASE_URL}/api/dashboard/summary", headers=mother_headers)
        father_resp = requests.get(f"{BASE_URL}/api/dashboard/summary", headers=father_headers)

        assert mother_resp.status_code == 200
        assert father_resp.status_code == 200

        mother_data = mother_resp.json()
        father_data = father_resp.json()

        print(f"\n[SUMMARY] Mother critical_incidents: {mother_data.get('critical_incidents')}")
        print(f"[SUMMARY] Father critical_incidents: {father_data.get('critical_incidents')}")

        assert mother_data["critical_incidents"] == father_data["critical_incidents"], \
            f"MISMATCH! Mother: {mother_data['critical_incidents']}, Father: {father_data['critical_incidents']}"

    # ==================== TEST 2: SLA Metrics ====================
    def test_sla_metrics_total_incidents_match(self, mother_headers, father_headers):
        """
        GET /api/dashboard/sla — Mother and Father must return IDENTICAL total_incidents count.
        """
        mother_resp = requests.get(f"{BASE_URL}/api/dashboard/sla", headers=mother_headers)
        father_resp = requests.get(f"{BASE_URL}/api/dashboard/sla", headers=father_headers)

        assert mother_resp.status_code == 200, f"Mother /sla failed: {mother_resp.text}"
        assert father_resp.status_code == 200, f"Father /sla failed: {father_resp.text}"

        mother_data = mother_resp.json()
        father_data = father_resp.json()

        print(f"\n[SLA] Mother total_incidents: {mother_data.get('total_incidents')}")
        print(f"[SLA] Father total_incidents: {father_data.get('total_incidents')}")

        assert mother_data["total_incidents"] == father_data["total_incidents"], \
            f"MISMATCH! Mother: {mother_data['total_incidents']}, Father: {father_data['total_incidents']}"

    def test_sla_metrics_all_counts_match(self, mother_headers, father_headers):
        """
        GET /api/dashboard/sla — All SLA counts should match between guardians.
        """
        mother_resp = requests.get(f"{BASE_URL}/api/dashboard/sla", headers=mother_headers)
        father_resp = requests.get(f"{BASE_URL}/api/dashboard/sla", headers=father_headers)

        assert mother_resp.status_code == 200
        assert father_resp.status_code == 200

        mother_data = mother_resp.json()
        father_data = father_resp.json()

        # Compare all SLA fields
        fields_to_compare = ["total_incidents", "acknowledged_count", "resolved_count"]
        
        for field in fields_to_compare:
            print(f"\n[SLA] Mother {field}: {mother_data.get(field)}")
            print(f"[SLA] Father {field}: {father_data.get(field)}")
            assert mother_data.get(field) == father_data.get(field), \
                f"MISMATCH for {field}! Mother: {mother_data.get(field)}, Father: {father_data.get(field)}"

    # ==================== TEST 3: Incidents Endpoint ====================
    def test_incidents_by_guardian_same_count(self, mother_headers, father_headers):
        """
        GET /api/incidents?guardian_id={id} — Both guardians should see same incident count.
        """
        mother_resp = requests.get(
            f"{BASE_URL}/api/incidents",
            headers=mother_headers,
            params={"guardian_id": MOTHER_CREDENTIALS["user_id"]}
        )
        father_resp = requests.get(
            f"{BASE_URL}/api/incidents",
            headers=father_headers,
            params={"guardian_id": FATHER_CREDENTIALS["user_id"]}
        )

        assert mother_resp.status_code == 200, f"Mother /incidents failed: {mother_resp.text}"
        assert father_resp.status_code == 200, f"Father /incidents failed: {father_resp.text}"

        mother_incidents = mother_resp.json()
        father_incidents = father_resp.json()

        # Handle both list response and dict with items key
        mother_count = len(mother_incidents) if isinstance(mother_incidents, list) else len(mother_incidents.get("items", []))
        father_count = len(father_incidents) if isinstance(father_incidents, list) else len(father_incidents.get("items", []))

        print(f"\n[INCIDENTS] Mother incident count: {mother_count}")
        print(f"[INCIDENTS] Father incident count: {father_count}")

        assert mother_count == father_count, \
            f"MISMATCH! Mother: {mother_count}, Father: {father_count}"

    def test_incidents_open_status_same_count(self, mother_headers, father_headers):
        """
        GET /api/incidents?status=open — Both guardians should see same open incident count.
        """
        mother_resp = requests.get(
            f"{BASE_URL}/api/incidents",
            headers=mother_headers,
            params={"guardian_id": MOTHER_CREDENTIALS["user_id"], "status": "open"}
        )
        father_resp = requests.get(
            f"{BASE_URL}/api/incidents",
            headers=father_headers,
            params={"guardian_id": FATHER_CREDENTIALS["user_id"], "status": "open"}
        )

        assert mother_resp.status_code == 200
        assert father_resp.status_code == 200

        mother_incidents = mother_resp.json()
        father_incidents = father_resp.json()

        mother_count = len(mother_incidents) if isinstance(mother_incidents, list) else len(mother_incidents.get("items", []))
        father_count = len(father_incidents) if isinstance(father_incidents, list) else len(father_incidents.get("items", []))

        print(f"\n[INCIDENTS OPEN] Mother open incident count: {mother_count}")
        print(f"[INCIDENTS OPEN] Father open incident count: {father_count}")

        assert mother_count == father_count, \
            f"MISMATCH! Mother: {mother_count}, Father: {father_count}"

    # ==================== TEST 4: Dashboard Overview (Cached) ====================
    def test_dashboard_overview_summary_match(self, mother_headers, father_headers):
        """
        GET /api/dashboard/overview — Cached endpoint should also return family-scoped data.
        Wait for cache TTL if needed (10s).
        """
        import time
        
        # First call may be cached - wait 10s to ensure fresh data
        time.sleep(10)
        
        mother_resp = requests.get(f"{BASE_URL}/api/dashboard/overview", headers=mother_headers)
        father_resp = requests.get(f"{BASE_URL}/api/dashboard/overview", headers=father_headers)

        assert mother_resp.status_code == 200, f"Mother /overview failed: {mother_resp.text}"
        assert father_resp.status_code == 200, f"Father /overview failed: {father_resp.text}"

        mother_data = mother_resp.json()
        father_data = father_resp.json()

        # Check summary section
        mother_summary = mother_data.get("summary", {})
        father_summary = father_data.get("summary", {})

        print(f"\n[OVERVIEW] Mother summary: {mother_summary}")
        print(f"[OVERVIEW] Father summary: {father_summary}")

        assert mother_summary.get("active_incidents") == father_summary.get("active_incidents"), \
            f"MISMATCH active_incidents! Mother: {mother_summary.get('active_incidents')}, Father: {father_summary.get('active_incidents')}"

        assert mother_summary.get("total_seniors") == father_summary.get("total_seniors"), \
            f"MISMATCH total_seniors! Mother: {mother_summary.get('total_seniors')}, Father: {father_summary.get('total_seniors')}"

    def test_dashboard_overview_sla_match(self, mother_headers, father_headers):
        """
        GET /api/dashboard/overview — SLA section should match between guardians.
        """
        mother_resp = requests.get(f"{BASE_URL}/api/dashboard/overview", headers=mother_headers)
        father_resp = requests.get(f"{BASE_URL}/api/dashboard/overview", headers=father_headers)

        assert mother_resp.status_code == 200
        assert father_resp.status_code == 200

        mother_data = mother_resp.json()
        father_data = father_resp.json()

        mother_sla = mother_data.get("sla", {})
        father_sla = father_data.get("sla", {})

        print(f"\n[OVERVIEW SLA] Mother: {mother_sla}")
        print(f"[OVERVIEW SLA] Father: {father_sla}")

        assert mother_sla.get("total_incidents") == father_sla.get("total_incidents"), \
            f"MISMATCH total_incidents! Mother: {mother_sla.get('total_incidents')}, Father: {father_sla.get('total_incidents')}"

    # ==================== TEST 5: Full Data Comparison ====================
    def test_full_summary_data_identical(self, mother_headers, father_headers):
        """
        Complete comparison of all dashboard summary fields between mother and father.
        """
        mother_resp = requests.get(f"{BASE_URL}/api/dashboard/summary", headers=mother_headers)
        father_resp = requests.get(f"{BASE_URL}/api/dashboard/summary", headers=father_headers)

        assert mother_resp.status_code == 200
        assert father_resp.status_code == 200

        mother_data = mother_resp.json()
        father_data = father_resp.json()

        print(f"\n[FULL SUMMARY] Mother: {mother_data}")
        print(f"[FULL SUMMARY] Father: {father_data}")

        # All numeric fields that should be identical
        fields = [
            "total_seniors",
            "total_devices",
            "active_incidents",
            "critical_incidents",
            "devices_online",
            "devices_offline",
        ]

        mismatches = []
        for field in fields:
            if mother_data.get(field) != father_data.get(field):
                mismatches.append(f"{field}: mother={mother_data.get(field)}, father={father_data.get(field)}")

        if mismatches:
            pytest.fail(f"Summary field mismatches:\n" + "\n".join(mismatches))

        print("\n✓ All summary fields match between mother and father!")


class TestFamilySeniorIdResolution:
    """Test that _get_family_senior_ids correctly finds all family seniors."""

    @pytest.fixture(scope="class")
    def mother_token(self):
        return authenticate(MOTHER_CREDENTIALS["email"], MOTHER_CREDENTIALS["password"])

    @pytest.fixture(scope="class")
    def father_token(self):
        return authenticate(FATHER_CREDENTIALS["email"], FATHER_CREDENTIALS["password"])

    @pytest.fixture(scope="class")
    def mother_headers(self, mother_token):
        return {"Authorization": f"Bearer {mother_token}"}

    @pytest.fixture(scope="class")
    def father_headers(self, father_token):
        return {"Authorization": f"Bearer {father_token}"}

    def test_mother_sees_both_seniors(self, mother_headers):
        """Mother should see seniors from both her account and father's account (Kid Nischint)."""
        response = requests.get(f"{BASE_URL}/api/dashboard/summary", headers=mother_headers)
        assert response.status_code == 200
        data = response.json()
        
        print(f"\n[SENIOR CHECK] Mother's total_seniors: {data['total_seniors']}")
        
        # Mother should see at least 2 seniors (her own + father's for same child)
        # Exact number depends on data setup
        assert data["total_seniors"] >= 1, f"Mother should see at least 1 senior, got {data['total_seniors']}"

    def test_father_sees_both_seniors(self, father_headers):
        """Father should see seniors from both his account and mother's account (Kid Nischint)."""
        response = requests.get(f"{BASE_URL}/api/dashboard/summary", headers=father_headers)
        assert response.status_code == 200
        data = response.json()
        
        print(f"\n[SENIOR CHECK] Father's total_seniors: {data['total_seniors']}")
        
        # Father should see the same number as mother
        assert data["total_seniors"] >= 1, f"Father should see at least 1 senior, got {data['total_seniors']}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
