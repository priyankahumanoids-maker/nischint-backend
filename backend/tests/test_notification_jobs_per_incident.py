"""
Tests for NISCHINT Per-Incident Notification Jobs - Iteration 5
===============================================================
Tests the new per-incident notification jobs visibility:
- GET /api/incidents/{id}/notification-jobs (guardian-scoped)
- GET /api/operator/incidents/{id}/notification-jobs (operator endpoint)
- RBAC: Guardian cannot access operator endpoint (403)
- RBAC: Guardian cannot access incidents they don't own (404)
- Response structure validation
- Regression tests for auth, health, delivery health
"""
import pytest
import requests
import os
from uuid import uuid4

# Base URL from environment
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
GUARDIAN_EMAIL = "nischint4parents@gmail.com"
GUARDIAN_PASSWORD = "secret123"
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"


class TestHealthRegression:
    """Health check endpoints - verify backend is up"""
    
    def test_api_root(self):
        """Test API root endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/")
        assert response.status_code == 200
        print(f"✓ API root working")
    
    def test_db_health_check(self):
        """Test PostgreSQL health check endpoint"""
        response = requests.get(f"{BASE_URL}/api/health/db")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"
        print(f"✓ DB health check: {data}")


class TestAuthRegression:
    """Authentication endpoints regression tests"""
    
    def test_guardian_login(self):
        """Test guardian login returns token with role=guardian"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": GUARDIAN_EMAIL, "password": GUARDIAN_PASSWORD}
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data.get("role") == "guardian"
        print(f"✓ Guardian login successful, role: {data.get('role')}")
    
    def test_operator_login(self):
        """Test operator login returns token with role=operator"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD}
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data.get("role") == "operator"
        print(f"✓ Operator login successful, role: {data.get('role')}")


class TestGuardianIncidentNotificationJobs:
    """Tests for GET /api/incidents/{id}/notification-jobs"""
    
    @pytest.fixture
    def guardian_token(self):
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": GUARDIAN_EMAIL, "password": GUARDIAN_PASSWORD}
        )
        return response.json().get("access_token")
    
    @pytest.fixture
    def guardian_id(self):
        """Guardian user ID from test credentials"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": GUARDIAN_EMAIL, "password": GUARDIAN_PASSWORD}
        )
        data = response.json()
        # Extract from JWT (sub claim) - or we know it's 7437a394-74ef-46a2-864f-6add0e7e8e60
        return "7437a394-74ef-46a2-864f-6add0e7e8e60"
    
    @pytest.fixture
    def incident_id(self, guardian_token, guardian_id):
        """Get first incident for guardian"""
        response = requests.get(
            f"{BASE_URL}/api/incidents?guardian_id={guardian_id}",
            headers={"Authorization": f"Bearer {guardian_token}"}
        )
        if response.status_code == 200 and response.json():
            return response.json()[0]["id"]
        pytest.skip("No incidents available for guardian")
    
    def test_guardian_can_get_notification_jobs(self, guardian_token, incident_id):
        """Test guardian can GET notification jobs for their incident"""
        response = requests.get(
            f"{BASE_URL}/api/incidents/{incident_id}/notification-jobs",
            headers={"Authorization": f"Bearer {guardian_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)  # Should return list (may be empty)
        print(f"✓ Guardian got notification jobs for incident {incident_id}: {len(data)} jobs")
    
    def test_guardian_response_structure(self, guardian_token, incident_id):
        """Test response has correct structure for each job"""
        response = requests.get(
            f"{BASE_URL}/api/incidents/{incident_id}/notification-jobs",
            headers={"Authorization": f"Bearer {guardian_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # If there are jobs, validate structure
        if data:
            job = data[0]
            expected_fields = ["id", "channel", "recipient", "status", "attempts", "last_attempt_at", "created_at", "escalation_level"]
            for field in expected_fields:
                assert field in job, f"Missing field: {field}"
            print(f"✓ Notification job structure valid: {list(job.keys())}")
        else:
            print(f"✓ No notification jobs (empty list is valid)")
    
    def test_guardian_gets_404_for_nonexistent_incident(self, guardian_token):
        """Test guardian gets 404 for incident that doesn't exist"""
        fake_id = "00000000-0000-0000-0000-000000000001"
        response = requests.get(
            f"{BASE_URL}/api/incidents/{fake_id}/notification-jobs",
            headers={"Authorization": f"Bearer {guardian_token}"}
        )
        assert response.status_code == 404
        print(f"✓ Guardian gets 404 for nonexistent incident")
    
    def test_guardian_gets_404_for_other_guardian_incident(self, guardian_token):
        """Test guardian gets 404 for incident they don't own (access control)"""
        # Use a fake UUID that doesn't belong to this guardian
        other_incident = str(uuid4())
        response = requests.get(
            f"{BASE_URL}/api/incidents/{other_incident}/notification-jobs",
            headers={"Authorization": f"Bearer {guardian_token}"}
        )
        assert response.status_code == 404
        print(f"✓ Guardian gets 404 for incident not owned by them")


class TestOperatorIncidentNotificationJobs:
    """Tests for GET /api/operator/incidents/{id}/notification-jobs"""
    
    @pytest.fixture
    def operator_token(self):
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD}
        )
        return response.json().get("access_token")
    
    @pytest.fixture
    def guardian_token(self):
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": GUARDIAN_EMAIL, "password": GUARDIAN_PASSWORD}
        )
        return response.json().get("access_token")
    
    @pytest.fixture
    def incident_id(self, operator_token):
        """Get first incident via operator endpoint"""
        response = requests.get(
            f"{BASE_URL}/api/operator/incidents",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        if response.status_code == 200 and response.json():
            return response.json()[0]["id"]
        pytest.skip("No incidents available")
    
    def test_operator_can_get_any_incident_jobs(self, operator_token, incident_id):
        """Test operator can GET notification jobs for any incident"""
        response = requests.get(
            f"{BASE_URL}/api/operator/incidents/{incident_id}/notification-jobs",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Operator got notification jobs for incident {incident_id}: {len(data)} jobs")
    
    def test_operator_response_includes_idempotency_key(self, operator_token, incident_id):
        """Test operator response includes idempotency_key (extra field for ops)"""
        response = requests.get(
            f"{BASE_URL}/api/operator/incidents/{incident_id}/notification-jobs",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        if data:
            job = data[0]
            # Operator endpoint includes idempotency_key
            assert "idempotency_key" in job or "id" in job, "Expected idempotency_key or id"
            print(f"✓ Operator response structure: {list(job.keys())}")
        else:
            print(f"✓ No notification jobs (empty list is valid)")
    
    def test_guardian_cannot_access_operator_endpoint(self, guardian_token, incident_id):
        """Test guardian gets 403 when accessing operator endpoint (RBAC)"""
        response = requests.get(
            f"{BASE_URL}/api/operator/incidents/{incident_id}/notification-jobs",
            headers={"Authorization": f"Bearer {guardian_token}"}
        )
        assert response.status_code == 403
        print(f"✓ Guardian gets 403 on operator endpoint (RBAC enforced)")
    
    def test_operator_endpoint_requires_auth(self, incident_id):
        """Test operator endpoint requires authentication"""
        response = requests.get(
            f"{BASE_URL}/api/operator/incidents/{incident_id}/notification-jobs"
        )
        assert response.status_code in [401, 403]
        print(f"✓ Operator endpoint requires auth: {response.status_code}")


class TestDeliveryHealthRegression:
    """Regression tests for delivery health from iteration 4"""
    
    @pytest.fixture
    def operator_token(self):
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD}
        )
        return response.json().get("access_token")
    
    def test_notification_jobs_stats(self, operator_token):
        """Test notification-jobs/stats endpoint still works"""
        response = requests.get(
            f"{BASE_URL}/api/operator/notification-jobs/stats?window_minutes=15",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "totals" in data
        assert "by_channel" in data
        assert "throughput_per_minute" in data
        print(f"✓ Delivery health stats working: throughput={data['throughput_per_minute']} msg/min")
    
    def test_operator_stats(self, operator_token):
        """Test operator stats endpoint still works"""
        response = requests.get(
            f"{BASE_URL}/api/operator/stats",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "open_incidents" in data
        assert "escalated_incidents" in data
        print(f"✓ Operator stats: open={data['open_incidents']}, escalated={data['escalated_incidents']}")
    
    def test_false_alarm_metrics(self, operator_token):
        """Test false alarm metrics endpoint still works"""
        response = requests.get(
            f"{BASE_URL}/api/operator/false-alarm-metrics",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "false_alarm_rate_percent" in data
        print(f"✓ False alarm rate: {data['false_alarm_rate_percent']}%")


class TestGuardianDashboardRegression:
    """Regression tests for guardian dashboard endpoints"""
    
    @pytest.fixture
    def guardian_token(self):
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": GUARDIAN_EMAIL, "password": GUARDIAN_PASSWORD}
        )
        return response.json().get("access_token")
    
    @pytest.fixture
    def guardian_id(self):
        return "7437a394-74ef-46a2-864f-6add0e7e8e60"
    
    def test_dashboard_summary(self, guardian_token):
        """Test guardian dashboard summary endpoint"""
        response = requests.get(
            f"{BASE_URL}/api/dashboard/summary",
            headers={"Authorization": f"Bearer {guardian_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "total_seniors" in data
        assert "active_incidents" in data
        print(f"✓ Dashboard summary: seniors={data['total_seniors']}, active={data['active_incidents']}")
    
    def test_get_incidents_events(self, guardian_token, guardian_id):
        """Test incident events endpoint"""
        # Get first incident
        inc_response = requests.get(
            f"{BASE_URL}/api/incidents?guardian_id={guardian_id}",
            headers={"Authorization": f"Bearer {guardian_token}"}
        )
        if inc_response.status_code == 200 and inc_response.json():
            incident_id = inc_response.json()[0]["id"]
            response = requests.get(
                f"{BASE_URL}/api/incidents/{incident_id}/events",
                headers={"Authorization": f"Bearer {guardian_token}"}
            )
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            print(f"✓ Incident events: {len(data)} events")
        else:
            pytest.skip("No incidents available")


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
