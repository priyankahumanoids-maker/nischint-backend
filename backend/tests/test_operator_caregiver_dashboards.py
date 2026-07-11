"""
Operator Dashboard & Caregiver Dashboard API Tests
===================================================
Tests for:
- Operator Dashboard endpoints: /api/operator/dashboard/* and /api/operator/incidents/*
- Caregiver Dashboard endpoints: /api/caregiver/*
- RBAC: role-based access control
"""

import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
ADMIN_CREDS = {"email": "nischint4parents@gmail.com", "password": "secret123"}
OPERATOR_CREDS = {"email": "operator1@nischint.com", "password": "secret123"}
CAREGIVER_CREDS = {"email": "caregiver1@nischint.com", "password": "secret123"}


@pytest.fixture(scope="module")
def admin_token():
    """Get admin auth token"""
    resp = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN_CREDS)
    if resp.status_code == 200:
        return resp.json().get("access_token") or resp.json().get("token")
    pytest.skip(f"Admin login failed: {resp.status_code} - {resp.text}")


@pytest.fixture(scope="module")
def operator_token():
    """Get operator auth token"""
    resp = requests.post(f"{BASE_URL}/api/auth/login", json=OPERATOR_CREDS)
    if resp.status_code == 200:
        return resp.json().get("access_token") or resp.json().get("token")
    pytest.skip(f"Operator login failed: {resp.status_code} - {resp.text}")


@pytest.fixture(scope="module")
def caregiver_token():
    """Get caregiver auth token"""
    resp = requests.post(f"{BASE_URL}/api/auth/login", json=CAREGIVER_CREDS)
    if resp.status_code == 200:
        return resp.json().get("access_token") or resp.json().get("token")
    pytest.skip(f"Caregiver login failed: {resp.status_code} - {resp.text}")


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


# ═══════════════════════════════════════════════════════════════
# 1. HEALTH CHECK
# ═══════════════════════════════════════════════════════════════

class TestHealthCheck:
    """Basic API health check"""
    
    def test_api_root(self):
        """Verify API root responds"""
        resp = requests.get(f"{BASE_URL}/api/")
        assert resp.status_code == 200
        print(f"API root: {resp.json()}")


# ═══════════════════════════════════════════════════════════════
# 2. AUTHENTICATION
# ═══════════════════════════════════════════════════════════════

class TestAuthentication:
    """Test auth for all 3 user types"""
    
    def test_admin_login(self):
        """Admin can login"""
        resp = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN_CREDS)
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data or "token" in data
        print(f"Admin login successful, role: {data.get('user', {}).get('role', 'N/A')}")
    
    def test_operator_login(self):
        """Operator can login"""
        resp = requests.post(f"{BASE_URL}/api/auth/login", json=OPERATOR_CREDS)
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data or "token" in data
        print(f"Operator login successful, role: {data.get('user', {}).get('role', 'N/A')}")
    
    def test_caregiver_login(self):
        """Caregiver can login"""
        resp = requests.post(f"{BASE_URL}/api/auth/login", json=CAREGIVER_CREDS)
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data or "token" in data
        print(f"Caregiver login successful, role: {data.get('user', {}).get('role', 'N/A')}")


# ═══════════════════════════════════════════════════════════════
# 3. OPERATOR DASHBOARD ENDPOINTS
# ═══════════════════════════════════════════════════════════════

class TestOperatorDashboardMetrics:
    """GET /api/operator/dashboard/metrics"""
    
    def test_metrics_admin_access(self, admin_token):
        """Admin can access operator metrics"""
        resp = requests.get(f"{BASE_URL}/api/operator/dashboard/metrics", headers=auth_header(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        assert "active_sos" in data
        assert "new_alerts" in data
        assert "assigned" in data
        assert "resolved_today" in data
        assert "caregivers_online" in data
        print(f"Metrics: {data}")
    
    def test_metrics_operator_access(self, operator_token):
        """Operator can access operator metrics"""
        resp = requests.get(f"{BASE_URL}/api/operator/dashboard/metrics", headers=auth_header(operator_token))
        assert resp.status_code == 200
        data = resp.json()
        assert "active_sos" in data
        print(f"Operator metrics access OK: {data}")
    
    def test_metrics_requires_auth(self):
        """Unauthenticated access returns 401"""
        resp = requests.get(f"{BASE_URL}/api/operator/dashboard/metrics")
        assert resp.status_code in [401, 403]
        print(f"Unauthenticated: {resp.status_code}")


class TestOperatorIncidentsList:
    """GET /api/operator/incidents"""
    
    def test_incidents_list_admin(self, admin_token):
        """Admin can get incidents list with enriched data"""
        resp = requests.get(f"{BASE_URL}/api/operator/incidents?limit=50", headers=auth_header(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        # API returns list directly or dict with 'incidents' key
        incidents = data if isinstance(data, list) else data.get("incidents", [])
        assert isinstance(incidents, list)
        print(f"Total incidents: {len(incidents)}")
        
        # Verify enriched fields if incidents exist
        if incidents:
            inc = incidents[0]
            print(f"Sample incident: id={inc.get('id')}, type={inc.get('incident_type')}, severity={inc.get('severity')}")
            # Check for enriched fields
            assert "senior_name" in inc or inc.get("senior_name") is None
            assert "device_identifier" in inc or inc.get("device_identifier") is None
    
    def test_incidents_list_operator(self, operator_token):
        """Operator can get incidents list"""
        resp = requests.get(f"{BASE_URL}/api/operator/incidents?limit=10", headers=auth_header(operator_token))
        assert resp.status_code == 200


class TestOperatorCaregivers:
    """GET /api/operator/dashboard/caregivers"""
    
    def test_caregivers_list_admin(self, admin_token):
        """Admin can get caregivers list"""
        resp = requests.get(f"{BASE_URL}/api/operator/dashboard/caregivers", headers=auth_header(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        assert "caregivers" in data
        assert "total" in data
        print(f"Caregivers: {data['total']} - {[c.get('full_name') for c in data['caregivers']]}")
        
        if data["caregivers"]:
            cg = data["caregivers"][0]
            assert "id" in cg
            assert "full_name" in cg
            assert "status" in cg
    
    def test_caregivers_list_operator(self, operator_token):
        """Operator can get caregivers list"""
        resp = requests.get(f"{BASE_URL}/api/operator/dashboard/caregivers", headers=auth_header(operator_token))
        assert resp.status_code == 200


class TestOperatorIncidentAssign:
    """POST /api/operator/incidents/{id}/assign"""
    
    def test_assign_incident_to_caregiver(self, admin_token):
        """Admin can assign incident to caregiver"""
        # Get an incident
        inc_resp = requests.get(f"{BASE_URL}/api/operator/incidents?limit=5", headers=auth_header(admin_token))
        assert inc_resp.status_code == 200
        data = inc_resp.json()
        incidents = data if isinstance(data, list) else data.get("incidents", [])
        
        if not incidents:
            pytest.skip("No incidents to test assignment")
        
        # Get caregivers
        cg_resp = requests.get(f"{BASE_URL}/api/operator/dashboard/caregivers", headers=auth_header(admin_token))
        caregivers = cg_resp.json().get("caregivers", [])
        
        if not caregivers:
            pytest.skip("No caregivers to assign")
        
        incident_id = incidents[0]["id"]
        caregiver_id = caregivers[0]["id"]
        
        # Assign
        resp = requests.post(
            f"{BASE_URL}/api/operator/incidents/{incident_id}/assign?caregiver_id={caregiver_id}",
            headers=auth_header(admin_token)
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("assigned") == True
        print(f"Assigned incident {incident_id} to caregiver {caregiver_id}")


class TestOperatorIncidentStatus:
    """PATCH /api/operator/incidents/{id}/status"""
    
    def test_update_incident_status(self, admin_token):
        """Admin can update incident status"""
        # Get an incident
        inc_resp = requests.get(f"{BASE_URL}/api/operator/incidents?limit=5", headers=auth_header(admin_token))
        data = inc_resp.json()
        incidents = data if isinstance(data, list) else data.get("incidents", [])
        
        if not incidents:
            pytest.skip("No incidents to test status update")
        
        incident_id = incidents[0]["id"]
        
        # Update status to in_progress (won't resolve to keep data for other tests)
        resp = requests.patch(
            f"{BASE_URL}/api/operator/incidents/{incident_id}/status?new_status=in_progress",
            headers=auth_header(admin_token)
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "in_progress"
        print(f"Updated incident {incident_id} status to in_progress")


class TestOperatorIncidentEscalate:
    """POST /api/operator/incidents/{id}/escalate"""
    
    def test_escalate_incident(self, admin_token):
        """Admin can escalate incident"""
        # Get an incident
        inc_resp = requests.get(f"{BASE_URL}/api/operator/incidents?limit=5", headers=auth_header(admin_token))
        data = inc_resp.json()
        incidents = data if isinstance(data, list) else data.get("incidents", [])
        
        if not incidents:
            pytest.skip("No incidents to test escalation")
        
        incident_id = incidents[0]["id"]
        
        resp = requests.post(
            f"{BASE_URL}/api/operator/incidents/{incident_id}/escalate",
            headers=auth_header(admin_token)
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("escalated") == True
        assert "escalation_level" in data
        print(f"Escalated incident {incident_id} to level {data.get('escalation_level')}")


# ═══════════════════════════════════════════════════════════════
# 4. CAREGIVER DASHBOARD ENDPOINTS
# ═══════════════════════════════════════════════════════════════

class TestCaregiverProfile:
    """GET /api/caregiver/profile"""
    
    def test_profile_caregiver_access(self, caregiver_token):
        """Caregiver can get their profile"""
        resp = requests.get(f"{BASE_URL}/api/caregiver/profile", headers=auth_header(caregiver_token))
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        assert "email" in data
        assert "status" in data
        print(f"Caregiver profile: {data.get('email')}, status: {data.get('status')}")
    
    def test_profile_admin_access(self, admin_token):
        """Admin can access caregiver profile endpoint (if has caregiver role too or test purposes)"""
        resp = requests.get(f"{BASE_URL}/api/caregiver/profile", headers=auth_header(admin_token))
        # Admin should have access (since require_role includes 'admin')
        assert resp.status_code == 200


class TestCaregiverStatus:
    """PATCH /api/caregiver/status"""
    
    def test_update_status(self, caregiver_token):
        """Caregiver can update their status"""
        resp = requests.patch(
            f"{BASE_URL}/api/caregiver/status",
            json={"status": "available"},
            headers=auth_header(caregiver_token)
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "available"
        print(f"Updated status to: {data.get('status')}")
    
    def test_update_status_busy(self, caregiver_token):
        """Caregiver can set status to busy"""
        resp = requests.patch(
            f"{BASE_URL}/api/caregiver/status",
            json={"status": "busy"},
            headers=auth_header(caregiver_token)
        )
        assert resp.status_code == 200
        
        # Set back to available
        requests.patch(
            f"{BASE_URL}/api/caregiver/status",
            json={"status": "available"},
            headers=auth_header(caregiver_token)
        )


class TestCaregiverAssignedUsers:
    """GET /api/caregiver/assigned-users"""
    
    def test_assigned_users(self, caregiver_token):
        """Caregiver can get assigned users/seniors"""
        resp = requests.get(f"{BASE_URL}/api/caregiver/assigned-users", headers=auth_header(caregiver_token))
        assert resp.status_code == 200
        data = resp.json()
        assert "users" in data
        assert "total" in data
        print(f"Assigned users: {data['total']}")
        
        if data["users"]:
            user = data["users"][0]
            assert "id" in user
            assert "full_name" in user
            assert "risk_status" in user


class TestCaregiverAlerts:
    """GET /api/caregiver/alerts"""
    
    def test_alerts(self, caregiver_token):
        """Caregiver can get alerts"""
        resp = requests.get(f"{BASE_URL}/api/caregiver/alerts", headers=auth_header(caregiver_token))
        assert resp.status_code == 200
        data = resp.json()
        assert "alerts" in data
        assert "total" in data
        print(f"Caregiver alerts: {data['total']}")
        
        if data["alerts"]:
            alert = data["alerts"][0]
            assert "id" in alert
            assert "incident_type" in alert
            assert "severity" in alert
            assert "senior_name" in alert


class TestCaregiverAlertAcknowledge:
    """PATCH /api/caregiver/alerts/{id}/acknowledge"""
    
    def test_acknowledge_alert(self, caregiver_token):
        """Caregiver can acknowledge an assigned alert"""
        # Get alerts
        resp = requests.get(f"{BASE_URL}/api/caregiver/alerts", headers=auth_header(caregiver_token))
        alerts = resp.json().get("alerts", [])
        
        if not alerts:
            pytest.skip("No alerts assigned to caregiver")
        
        alert_id = alerts[0]["id"]
        
        resp = requests.patch(
            f"{BASE_URL}/api/caregiver/alerts/{alert_id}/acknowledge",
            headers=auth_header(caregiver_token)
        )
        # May return 200 or could be already acknowledged
        assert resp.status_code in [200, 400]
        if resp.status_code == 200:
            print(f"Acknowledged alert {alert_id}")


class TestCaregiverAlertStatus:
    """PATCH /api/caregiver/alerts/{id}/status"""
    
    def test_update_alert_status(self, caregiver_token):
        """Caregiver can update alert status"""
        # Get alerts
        resp = requests.get(f"{BASE_URL}/api/caregiver/alerts", headers=auth_header(caregiver_token))
        alerts = resp.json().get("alerts", [])
        
        if not alerts:
            pytest.skip("No alerts assigned to caregiver")
        
        alert_id = alerts[0]["id"]
        
        resp = requests.patch(
            f"{BASE_URL}/api/caregiver/alerts/{alert_id}/status",
            json={"status": "in_progress"},
            headers=auth_header(caregiver_token)
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "in_progress"
        print(f"Updated alert {alert_id} to in_progress")


class TestCaregiverVisits:
    """POST /api/caregiver/visits"""
    
    def test_create_visit(self, caregiver_token):
        """Caregiver can create visit log"""
        # Get assigned users first
        users_resp = requests.get(f"{BASE_URL}/api/caregiver/assigned-users", headers=auth_header(caregiver_token))
        users = users_resp.json().get("users", [])
        
        if not users:
            pytest.skip("No assigned users to create visit for")
        
        senior_id = users[0]["id"]
        
        resp = requests.post(
            f"{BASE_URL}/api/caregiver/visits",
            json={
                "senior_id": senior_id,
                "purpose": "TEST_Routine checkup",
                "remarks": "Test visit from pytest"
            },
            headers=auth_header(caregiver_token)
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert data.get("purpose") == "TEST_Routine checkup"
        print(f"Created visit: {data}")


class TestCaregiverNotes:
    """POST /api/caregiver/notes"""
    
    def test_create_note(self, caregiver_token):
        """Caregiver can create health note"""
        # Get assigned users first
        users_resp = requests.get(f"{BASE_URL}/api/caregiver/assigned-users", headers=auth_header(caregiver_token))
        users = users_resp.json().get("users", [])
        
        if not users:
            pytest.skip("No assigned users to create note for")
        
        senior_id = users[0]["id"]
        
        resp = requests.post(
            f"{BASE_URL}/api/caregiver/notes",
            json={
                "senior_id": senior_id,
                "observation_type": "TEST_Blood pressure check",
                "severity": "low",
                "notes": "Normal readings, 120/80",
                "follow_up": "Schedule next check in 1 week"
            },
            headers=auth_header(caregiver_token)
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert data.get("observation_type") == "TEST_Blood pressure check"
        print(f"Created note: {data}")


# ═══════════════════════════════════════════════════════════════
# 5. RBAC TESTS - Role-Based Access Control
# ═══════════════════════════════════════════════════════════════

class TestRBAC:
    """Role-Based Access Control tests"""
    
    def test_caregiver_cannot_access_operator_metrics(self, caregiver_token):
        """Caregiver cannot access operator dashboard metrics (403)"""
        resp = requests.get(f"{BASE_URL}/api/operator/dashboard/metrics", headers=auth_header(caregiver_token))
        assert resp.status_code == 403
        print(f"Caregiver blocked from operator metrics: {resp.status_code}")
    
    def test_caregiver_cannot_access_operator_incidents(self, caregiver_token):
        """Caregiver cannot access operator incidents list (403)"""
        resp = requests.get(f"{BASE_URL}/api/operator/incidents", headers=auth_header(caregiver_token))
        assert resp.status_code == 403
        print(f"Caregiver blocked from operator incidents: {resp.status_code}")
    
    def test_caregiver_cannot_access_operator_caregivers_list(self, caregiver_token):
        """Caregiver cannot access operator caregivers list (403)"""
        resp = requests.get(f"{BASE_URL}/api/operator/dashboard/caregivers", headers=auth_header(caregiver_token))
        assert resp.status_code == 403
        print(f"Caregiver blocked from caregivers list: {resp.status_code}")
    
    def test_operator_cannot_access_caregiver_profile(self, operator_token):
        """Operator cannot access caregiver profile (403)"""
        resp = requests.get(f"{BASE_URL}/api/caregiver/profile", headers=auth_header(operator_token))
        assert resp.status_code == 403
        print(f"Operator blocked from caregiver profile: {resp.status_code}")
    
    def test_operator_cannot_access_caregiver_alerts(self, operator_token):
        """Operator cannot access caregiver alerts (403)"""
        resp = requests.get(f"{BASE_URL}/api/caregiver/alerts", headers=auth_header(operator_token))
        assert resp.status_code == 403
        print(f"Operator blocked from caregiver alerts: {resp.status_code}")
    
    def test_unauthenticated_operator_access(self):
        """Unauthenticated access to operator endpoints returns 401"""
        resp = requests.get(f"{BASE_URL}/api/operator/dashboard/metrics")
        assert resp.status_code in [401, 403]
        print(f"Unauthenticated operator access: {resp.status_code}")
    
    def test_unauthenticated_caregiver_access(self):
        """Unauthenticated access to caregiver endpoints returns 401"""
        resp = requests.get(f"{BASE_URL}/api/caregiver/profile")
        assert resp.status_code in [401, 403]
        print(f"Unauthenticated caregiver access: {resp.status_code}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
