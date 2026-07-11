"""
Test Operator Dashboard Real-time Alert System APIs
Tests for: GET /api/operator/dashboard/metrics, GET /api/operator/incidents, 
GET /api/operator/dashboard/caregivers, POST /api/operator/incidents/{id}/assign,
POST /api/operator/incidents/{id}/escalate, PATCH /api/operator/incidents/{id}/status
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
ADMIN_EMAIL = "nischint4parents@gmail.com"
ADMIN_PASSWORD = "secret123"
OPERATOR_EMAIL = "operator1@nischint.com"
OPERATOR_PASSWORD = "secret123"
CAREGIVER_EMAIL = "caregiver1@nischint.com"
CAREGIVER_PASSWORD = "secret123"


@pytest.fixture(scope="module")
def admin_token():
    """Get admin authentication token."""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD
    })
    if response.status_code == 200:
        data = response.json()
        return data.get("access_token") or data.get("token")
    pytest.skip("Admin authentication failed")


@pytest.fixture(scope="module")
def operator_token():
    """Get operator authentication token."""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": OPERATOR_EMAIL,
        "password": OPERATOR_PASSWORD
    })
    if response.status_code == 200:
        data = response.json()
        return data.get("access_token") or data.get("token")
    pytest.skip("Operator authentication failed")


@pytest.fixture(scope="module")
def caregiver_token():
    """Get caregiver authentication token."""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": CAREGIVER_EMAIL,
        "password": CAREGIVER_PASSWORD
    })
    if response.status_code == 200:
        data = response.json()
        return data.get("access_token") or data.get("token")
    pytest.skip("Caregiver authentication failed")


# ── Health Check ──
class TestHealthCheck:
    """Basic API health check."""
    
    def test_api_root(self):
        """Verify API is accessible."""
        response = requests.get(f"{BASE_URL}/api/")
        assert response.status_code == 200
        print(f"API root response: {response.json()}")


# ── Authentication Tests ──
class TestAuthentication:
    """Test authentication for all roles."""
    
    def test_admin_login(self):
        """Test admin login."""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data or "token" in data
        print(f"Admin login successful, role: {data.get('user', {}).get('role')}")
    
    def test_operator_login(self):
        """Test operator login."""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": OPERATOR_EMAIL,
            "password": OPERATOR_PASSWORD
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data or "token" in data
        print(f"Operator login successful")
    
    def test_caregiver_login(self):
        """Test caregiver login."""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": CAREGIVER_EMAIL,
            "password": CAREGIVER_PASSWORD
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data or "token" in data
        print(f"Caregiver login successful")


# ── Operator Dashboard Metrics ──
class TestOperatorDashboardMetrics:
    """Test /api/operator/dashboard/metrics endpoint."""
    
    def test_metrics_admin_access(self, admin_token):
        """Admin can access dashboard metrics."""
        response = requests.get(
            f"{BASE_URL}/api/operator/dashboard/metrics",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Verify required fields for alert system
        assert "active_sos" in data
        assert "new_alerts" in data
        assert "assigned" in data
        assert "resolved_today" in data
        assert "caregivers_online" in data
        
        print(f"Dashboard metrics: {data}")
    
    def test_metrics_operator_access(self, operator_token):
        """Operator can access dashboard metrics."""
        response = requests.get(
            f"{BASE_URL}/api/operator/dashboard/metrics",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "active_sos" in data
        print(f"Operator access to metrics: OK")
    
    def test_metrics_requires_auth(self):
        """Unauthenticated request returns 401."""
        response = requests.get(f"{BASE_URL}/api/operator/dashboard/metrics")
        assert response.status_code == 401
        print("Unauthenticated access correctly rejected")
    
    def test_metrics_caregiver_denied(self, caregiver_token):
        """Caregiver cannot access operator metrics (RBAC)."""
        response = requests.get(
            f"{BASE_URL}/api/operator/dashboard/metrics",
            headers={"Authorization": f"Bearer {caregiver_token}"}
        )
        assert response.status_code == 403
        print("Caregiver access correctly denied")


# ── Operator Incidents List ──
class TestOperatorIncidentsList:
    """Test /api/operator/incidents endpoint."""
    
    def test_incidents_list_admin(self, admin_token):
        """Admin can list all incidents with enriched data."""
        response = requests.get(
            f"{BASE_URL}/api/operator/incidents?limit=50",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Can be list directly or dict with 'incidents' key
        incidents = data if isinstance(data, list) else data.get('incidents', data)
        
        assert isinstance(incidents, list)
        print(f"Found {len(incidents)} incidents")
        
        if len(incidents) > 0:
            inc = incidents[0]
            # Verify enriched fields for alert system
            assert "id" in inc
            assert "severity" in inc
            assert "status" in inc
            assert "senior_name" in inc  # Enriched field
            assert "device_identifier" in inc  # Enriched field
            assert "created_at" in inc
            print(f"Sample incident: severity={inc['severity']}, status={inc['status']}, senior_name={inc['senior_name']}")
    
    def test_incidents_list_operator(self, operator_token):
        """Operator can list incidents."""
        response = requests.get(
            f"{BASE_URL}/api/operator/incidents?limit=10",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        print("Operator can access incidents list")
    
    def test_incidents_filter_by_severity(self, admin_token):
        """Filter incidents by severity (critical for alerts)."""
        response = requests.get(
            f"{BASE_URL}/api/operator/incidents?severity=critical&limit=20",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        incidents = data if isinstance(data, list) else data.get('incidents', data)
        
        # All returned should be critical
        for inc in incidents:
            assert inc['severity'] == 'critical'
        print(f"Found {len(incidents)} critical incidents")
    
    def test_incidents_filter_by_status(self, admin_token):
        """Filter incidents by status (open for new alerts)."""
        response = requests.get(
            f"{BASE_URL}/api/operator/incidents?status=open&limit=20",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        incidents = data if isinstance(data, list) else data.get('incidents', data)
        
        for inc in incidents:
            assert inc['status'] == 'open'
        print(f"Found {len(incidents)} open incidents")


# ── Operator Caregivers List ──
class TestOperatorCaregivers:
    """Test /api/operator/dashboard/caregivers endpoint."""
    
    def test_caregivers_list_admin(self, admin_token):
        """Admin can list caregivers for assignment."""
        response = requests.get(
            f"{BASE_URL}/api/operator/dashboard/caregivers",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "caregivers" in data
        assert "total" in data
        
        caregivers = data["caregivers"]
        print(f"Found {len(caregivers)} caregivers")
        
        if len(caregivers) > 0:
            cg = caregivers[0]
            assert "id" in cg
            assert "full_name" in cg
            assert "status" in cg
            print(f"Sample caregiver: {cg['full_name']}, status={cg['status']}")
    
    def test_caregivers_list_operator(self, operator_token):
        """Operator can list caregivers."""
        response = requests.get(
            f"{BASE_URL}/api/operator/dashboard/caregivers",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        print("Operator can access caregivers list")


# ── Incident Assignment ──
class TestIncidentAssignment:
    """Test /api/operator/incidents/{id}/assign endpoint."""
    
    def test_assign_incident(self, admin_token):
        """Assign incident to caregiver."""
        # First get an incident
        inc_response = requests.get(
            f"{BASE_URL}/api/operator/incidents?status=open&limit=5",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert inc_response.status_code == 200
        incidents = inc_response.json()
        incidents = incidents if isinstance(incidents, list) else incidents.get('incidents', incidents)
        
        if len(incidents) == 0:
            pytest.skip("No open incidents to test assignment")
        
        incident_id = incidents[0]["id"]
        
        # Get a caregiver
        cg_response = requests.get(
            f"{BASE_URL}/api/operator/dashboard/caregivers",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert cg_response.status_code == 200
        caregivers = cg_response.json()["caregivers"]
        
        if len(caregivers) == 0:
            pytest.skip("No caregivers to test assignment")
        
        caregiver_id = caregivers[0]["id"]
        
        # Assign
        response = requests.post(
            f"{BASE_URL}/api/operator/incidents/{incident_id}/assign?caregiver_id={caregiver_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["assigned"] == True
        assert data["incident_id"] == incident_id
        assert data["caregiver_id"] == caregiver_id
        assert "assigned_at" in data
        
        print(f"Successfully assigned incident {incident_id} to caregiver {caregiver_id}")


# ── Incident Escalation ──
class TestIncidentEscalation:
    """Test /api/operator/incidents/{id}/escalate endpoint."""
    
    def test_escalate_incident(self, admin_token):
        """Escalate incident to next level."""
        # Get an incident
        inc_response = requests.get(
            f"{BASE_URL}/api/operator/incidents?limit=5",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert inc_response.status_code == 200
        incidents = inc_response.json()
        incidents = incidents if isinstance(incidents, list) else incidents.get('incidents', incidents)
        
        if len(incidents) == 0:
            pytest.skip("No incidents to test escalation")
        
        incident_id = incidents[0]["id"]
        
        response = requests.post(
            f"{BASE_URL}/api/operator/incidents/{incident_id}/escalate",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["escalated"] == True
        assert data["incident_id"] == incident_id
        assert "escalation_level" in data
        assert data["escalation_level"] >= 1
        
        print(f"Escalated incident {incident_id} to level {data['escalation_level']}")


# ── Incident Status Update ──
class TestIncidentStatusUpdate:
    """Test PATCH /api/operator/incidents/{id}/status endpoint."""
    
    def test_update_status_to_in_progress(self, admin_token):
        """Update incident status to in_progress."""
        # Get an open incident
        inc_response = requests.get(
            f"{BASE_URL}/api/operator/incidents?status=open&limit=5",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert inc_response.status_code == 200
        incidents = inc_response.json()
        incidents = incidents if isinstance(incidents, list) else incidents.get('incidents', incidents)
        
        if len(incidents) == 0:
            pytest.skip("No open incidents to test status update")
        
        incident_id = incidents[0]["id"]
        
        response = requests.patch(
            f"{BASE_URL}/api/operator/incidents/{incident_id}/status?new_status=in_progress",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "in_progress"
        assert data["incident_id"] == incident_id
        
        print(f"Updated incident {incident_id} to in_progress")
    
    def test_update_status_to_resolved(self, admin_token):
        """Update incident status to resolved."""
        # Get an in_progress incident (or any)
        inc_response = requests.get(
            f"{BASE_URL}/api/operator/incidents?limit=10",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert inc_response.status_code == 200
        incidents = inc_response.json()
        incidents = incidents if isinstance(incidents, list) else incidents.get('incidents', incidents)
        
        # Find one that's not already resolved
        target = None
        for inc in incidents:
            if inc["status"] != "resolved":
                target = inc
                break
        
        if not target:
            pytest.skip("No non-resolved incidents to test")
        
        incident_id = target["id"]
        
        response = requests.patch(
            f"{BASE_URL}/api/operator/incidents/{incident_id}/status?new_status=resolved",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "resolved"
        print(f"Resolved incident {incident_id}")


# ── RBAC Tests ──
class TestRBAC:
    """Test role-based access control."""
    
    def test_caregiver_cannot_access_operator_incidents(self, caregiver_token):
        """Caregiver cannot access operator incident list."""
        response = requests.get(
            f"{BASE_URL}/api/operator/incidents",
            headers={"Authorization": f"Bearer {caregiver_token}"}
        )
        assert response.status_code == 403
        print("Caregiver correctly blocked from operator incidents")
    
    def test_caregiver_cannot_access_operator_caregivers(self, caregiver_token):
        """Caregiver cannot access operator caregiver list."""
        response = requests.get(
            f"{BASE_URL}/api/operator/dashboard/caregivers",
            headers={"Authorization": f"Bearer {caregiver_token}"}
        )
        assert response.status_code == 403
        print("Caregiver correctly blocked from operator caregivers")
    
    def test_unauthenticated_assign_blocked(self):
        """Unauthenticated cannot assign incidents."""
        response = requests.post(
            f"{BASE_URL}/api/operator/incidents/00000000-0000-0000-0000-000000000000/assign"
        )
        assert response.status_code == 401
        print("Unauthenticated assignment correctly blocked")


# ── Audio File Test ──
class TestAlertAssets:
    """Test alert sound file accessibility."""
    
    def test_alert_sound_accessible(self):
        """Alert sound file is accessible."""
        response = requests.head(f"{BASE_URL}/sounds/alert.wav")
        assert response.status_code == 200
        print("Alert sound file is accessible")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
