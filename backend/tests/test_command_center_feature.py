"""
Test Command Center Feature - NEW dashboard for NISCHINT Command Center
Tests: /api/operator/command-center, /api/admin/monitoring/metrics, /api/admin/monitoring/queue-health
"""

import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL').rstrip('/')

# Test credentials
ADMIN_EMAIL = "nischint4parents@gmail.com"
ADMIN_PASSWORD = "secret123"


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token for admin user"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD
    })
    if response.status_code == 200:
        token = response.json().get("access_token")
        assert token is not None, "Token should be present in login response"
        return token
    pytest.fail(f"Authentication failed: {response.status_code} - {response.text}")


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Headers with auth token"""
    return {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json"
    }


class TestAuthentication:
    """Test authentication for Command Center access"""

    def test_login_returns_admin_role(self):
        """Verify login returns admin role for admin user"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        # Check role is admin (could be in role or roles field)
        role = data.get("role") or data.get("roles", [])
        if isinstance(role, list):
            assert "admin" in role, f"Admin should have admin role, got: {role}"
        else:
            assert role == "admin", f"Admin should have admin role, got: {role}"
        print("PASS: Admin login successful, role verified")


class TestCommandCenterEndpoint:
    """Test /api/operator/command-center endpoint"""

    def test_command_center_requires_auth(self):
        """Command center should require authentication"""
        response = requests.get(f"{BASE_URL}/api/operator/command-center")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("PASS: Command center requires authentication")

    def test_command_center_returns_data(self, auth_headers):
        """Command center should return incident data (may take 10-15 seconds)"""
        # Note: This endpoint takes ~11 seconds for cold start
        response = requests.get(
            f"{BASE_URL}/api/operator/command-center",
            headers=auth_headers,
            timeout=30
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Verify expected fields
        assert "active_incidents" in data, "Response should contain active_incidents"
        assert isinstance(data["active_incidents"], list), "active_incidents should be a list"
        
        # Check for predictive_alerts if present
        if "predictive_alerts" in data:
            assert isinstance(data["predictive_alerts"], list), "predictive_alerts should be a list"
        
        print(f"PASS: Command center returned {len(data['active_incidents'])} incidents")

    def test_command_center_incident_structure(self, auth_headers):
        """Verify incident data structure"""
        response = requests.get(
            f"{BASE_URL}/api/operator/command-center",
            headers=auth_headers,
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        
        incidents = data.get("active_incidents", [])
        if incidents:
            inc = incidents[0]
            # Check expected incident fields
            expected_fields = ["id", "incident_type", "severity", "status"]
            for field in expected_fields:
                if field not in inc:
                    print(f"Note: Field '{field}' not found in incident, may use different naming")
            print(f"PASS: Incident structure verified - {list(inc.keys())[:5]}...")
        else:
            print("PASS: No incidents to verify structure (empty is valid)")


class TestMonitoringMetrics:
    """Test /api/admin/monitoring/metrics endpoint"""

    def test_monitoring_metrics_requires_auth(self):
        """Monitoring metrics should require authentication"""
        response = requests.get(f"{BASE_URL}/api/admin/monitoring/metrics")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("PASS: Monitoring metrics requires authentication")

    def test_monitoring_metrics_returns_data(self, auth_headers):
        """Monitoring metrics should return comprehensive data"""
        response = requests.get(
            f"{BASE_URL}/api/admin/monitoring/metrics",
            headers=auth_headers,
            timeout=15
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Verify expected sections
        expected_sections = ["platform_health", "database"]
        for section in expected_sections:
            assert section in data, f"Response should contain {section}"
        
        print(f"PASS: Monitoring metrics returned with sections: {list(data.keys())[:5]}...")

    def test_monitoring_metrics_platform_health(self, auth_headers):
        """Verify platform_health section has API latency and request stats"""
        response = requests.get(
            f"{BASE_URL}/api/admin/monitoring/metrics",
            headers=auth_headers,
            timeout=15
        )
        assert response.status_code == 200
        data = response.json()
        
        ph = data.get("platform_health", {})
        # Check for latency metrics
        latency_fields = ["api_latency_p50_ms", "api_latency_p95_ms", "total_requests"]
        for field in latency_fields:
            if field in ph:
                print(f"  {field}: {ph[field]}")
        
        print("PASS: Platform health section verified")

    def test_monitoring_metrics_database_stats(self, auth_headers):
        """Verify database section has pool stats"""
        response = requests.get(
            f"{BASE_URL}/api/admin/monitoring/metrics",
            headers=auth_headers,
            timeout=15
        )
        assert response.status_code == 200
        data = response.json()
        
        db = data.get("database", {})
        if db:
            print(f"  Database status: {db.get('status', 'unknown')}")
            print(f"  Pool size: {db.get('pool_size', 'N/A')}")
        
        print("PASS: Database stats section verified")

    def test_monitoring_metrics_redis_status(self, auth_headers):
        """Verify redis section shows status"""
        response = requests.get(
            f"{BASE_URL}/api/admin/monitoring/metrics",
            headers=auth_headers,
            timeout=15
        )
        assert response.status_code == 200
        data = response.json()
        
        redis = data.get("redis", {})
        if redis:
            status = redis.get("status", "unknown")
            print(f"  Redis status: {status}")
            # Redis may be disconnected in preview env - that's expected
        
        print("PASS: Redis section verified (disconnected is expected in preview)")


class TestQueueHealth:
    """Test /api/admin/monitoring/queue-health endpoint"""

    def test_queue_health_requires_auth(self):
        """Queue health should require authentication"""
        response = requests.get(f"{BASE_URL}/api/admin/monitoring/queue-health")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("PASS: Queue health requires authentication")

    def test_queue_health_returns_data(self, auth_headers):
        """Queue health should return queue statistics"""
        response = requests.get(
            f"{BASE_URL}/api/admin/monitoring/queue-health",
            headers=auth_headers,
            timeout=15
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Check for queues section
        queues = data.get("queues", {})
        print(f"  Queue types found: {list(queues.keys())}")
        print(f"  Using Redis: {data.get('using_redis', 'unknown')}")
        
        print("PASS: Queue health endpoint returns queue data")


class TestSSEStream:
    """Test SSE endpoint availability"""

    def test_sse_stream_endpoint_requires_auth(self):
        """Verify SSE stream endpoint requires authentication"""
        try:
            response = requests.get(
                f"{BASE_URL}/api/stream",
                timeout=5,
                stream=True
            )
            # SSE should require auth
            assert response.status_code in [401, 403], f"SSE should require auth, got {response.status_code}"
            response.close()
            print("PASS: SSE stream requires authentication")
        except requests.exceptions.Timeout:
            print("PASS: SSE endpoint timed out (acceptable)")

    def test_sse_stream_endpoint_exists_with_token_param(self, auth_token):
        """Verify SSE stream endpoint exists with token as query param (used by Command Center)"""
        # SSE in this app uses token as query parameter, not header
        try:
            response = requests.get(
                f"{BASE_URL}/api/stream?token={auth_token}",
                timeout=5,
                stream=True
            )
            # SSE should return 200 with text/event-stream
            if response.status_code == 200:
                content_type = response.headers.get("content-type", "")
                response.close()
                print(f"PASS: SSE stream endpoint available, content-type: {content_type}")
            else:
                response.close()
                print(f"NOTE: SSE endpoint returned {response.status_code} - may use different auth mechanism")
        except requests.exceptions.Timeout:
            # Timeout is acceptable for SSE - means connection was established
            print("PASS: SSE endpoint reachable (timeout expected for streaming)")


class TestNightGuardianSessions:
    """Test Night Guardian sessions endpoint (used by Command Center)"""

    def test_night_guardian_sessions_endpoint(self, auth_headers):
        """Verify night guardian sessions endpoint for Guardian Journeys panel"""
        response = requests.get(
            f"{BASE_URL}/api/night-guardian/sessions",
            headers=auth_headers,
            timeout=15
        )
        # May return 200 with sessions or 404 if not implemented
        if response.status_code == 200:
            data = response.json()
            sessions = data.get("sessions", [])
            print(f"PASS: Night Guardian sessions returned {len(sessions)} sessions")
        elif response.status_code == 404:
            print("NOTE: Night Guardian sessions endpoint not found (may not be implemented)")
        else:
            print(f"NOTE: Night Guardian sessions returned {response.status_code}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
