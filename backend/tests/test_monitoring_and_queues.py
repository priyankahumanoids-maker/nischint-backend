# Test suite for NISCHINT Monitoring & Queue features (iteration 106)
# Tests: Monitoring endpoints, Queue health, Middleware latency tracking, Night Guardian flows

import os
import pytest
import requests
import time

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    raise ValueError("REACT_APP_BACKEND_URL not set")

# Test credentials
ADMIN_EMAIL = "nischint4parents@gmail.com"
ADMIN_PASSWORD = "secret123"


@pytest.fixture(scope="module")
def admin_token():
    """Login and get admin token."""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD,
    })
    assert response.status_code == 200, f"Login failed: {response.text}"
    data = response.json()
    assert "access_token" in data, "No access_token in login response"
    assert data.get("role") == "admin", f"Expected admin role, got {data.get('role')}"
    return data["access_token"]


@pytest.fixture(scope="module")
def auth_headers(admin_token):
    """Auth headers with bearer token."""
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


class TestAuthentication:
    """Basic auth tests."""

    def test_login_returns_token_and_admin_role(self):
        """POST /api/auth/login - Returns access_token and admin role."""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD,
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["role"] == "admin"
        print("✓ Login returns token and admin role")


class TestMonitoringEndpoints:
    """Test new monitoring API endpoints."""

    def test_monitoring_metrics_requires_auth(self):
        """GET /api/admin/monitoring/metrics - Requires auth."""
        response = requests.get(f"{BASE_URL}/api/admin/monitoring/metrics")
        assert response.status_code == 401 or response.status_code == 403
        print("✓ Monitoring metrics requires authentication")

    def test_monitoring_metrics_returns_platform_health(self, auth_headers):
        """GET /api/admin/monitoring/metrics - Returns platform_health, emergency_activity, ai_safety."""
        response = requests.get(f"{BASE_URL}/api/admin/monitoring/metrics", headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()

        # Validate top-level structure
        assert "timestamp" in data, "Missing timestamp"
        assert "uptime_seconds" in data, "Missing uptime_seconds"
        assert "platform_health" in data, "Missing platform_health section"
        assert "emergency_activity" in data, "Missing emergency_activity section"
        assert "ai_safety" in data, "Missing ai_safety section"
        assert "database" in data, "Missing database section"
        assert "redis" in data, "Missing redis section"

        # Validate platform_health structure
        ph = data["platform_health"]
        assert "api_latency_p50_ms" in ph, "Missing api_latency_p50_ms"
        assert "api_latency_p95_ms" in ph, "Missing api_latency_p95_ms"
        assert "total_requests" in ph, "Missing total_requests"
        assert "total_errors_5xx" in ph, "Missing total_errors_5xx"
        assert "error_rate_pct" in ph, "Missing error_rate_pct"

        # Validate emergency_activity structure
        ea = data["emergency_activity"]
        assert "last_1h" in ea, "Missing last_1h in emergency_activity"
        assert "last_24h" in ea, "Missing last_24h in emergency_activity"

        # Validate ai_safety structure
        ai = data["ai_safety"]
        assert "risk_spikes" in ai, "Missing risk_spikes in ai_safety"
        assert "heatmap_alerts" in ai, "Missing heatmap_alerts in ai_safety"
        assert "behavior_anomalies" in ai, "Missing behavior_anomalies in ai_safety"

        # Validate guardian_sessions (added by the monitoring endpoint)
        assert "guardian_sessions" in data, "Missing guardian_sessions"
        assert "active" in data["guardian_sessions"], "Missing active in guardian_sessions"

        print(f"✓ Monitoring metrics returned with all sections, uptime: {data['uptime_seconds']}s")
        print(f"  Platform health: p50={ph['api_latency_p50_ms']}ms, p95={ph['api_latency_p95_ms']}ms")
        print(f"  Total requests: {ph['total_requests']}, Error rate: {ph['error_rate_pct']}%")

    def test_monitoring_alerts_returns_array(self, auth_headers):
        """GET /api/admin/monitoring/alerts - Returns alerts array."""
        response = requests.get(f"{BASE_URL}/api/admin/monitoring/alerts", headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert "alerts" in data, "Missing alerts key"
        assert isinstance(data["alerts"], list), "alerts should be a list"
        print(f"✓ Monitoring alerts returned {len(data['alerts'])} alerts")

    def test_monitoring_alerts_with_limit(self, auth_headers):
        """GET /api/admin/monitoring/alerts?limit=5 - Respects limit parameter."""
        response = requests.get(f"{BASE_URL}/api/admin/monitoring/alerts?limit=5", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data["alerts"]) <= 5, f"Expected at most 5 alerts, got {len(data['alerts'])}"
        print("✓ Monitoring alerts respects limit parameter")


class TestQueueHealth:
    """Test queue health monitoring endpoint."""

    def test_queue_health_returns_3_queues(self, auth_headers):
        """GET /api/admin/monitoring/queue-health - Returns 3 queues with stats."""
        response = requests.get(f"{BASE_URL}/api/admin/monitoring/queue-health", headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()

        assert "queues" in data, "Missing queues key"
        queues = data["queues"]

        # Check all 3 queues exist
        expected_queues = ["incident", "ai_signal", "notification"]
        for q in expected_queues:
            assert q in queues, f"Missing queue: {q}"
            qdata = queues[q]
            assert "enqueued" in qdata, f"Missing enqueued count for {q}"
            assert "processed" in qdata, f"Missing processed count for {q}"
            assert "failed" in qdata, f"Missing failed count for {q}"
            assert "depth" in qdata, f"Missing depth for {q}"

        # Check using_redis flag (expected False in preview env)
        assert "using_redis" in data, "Missing using_redis flag"
        print(f"✓ Queue health returned with 3 queues, using_redis={data['using_redis']}")
        for q in expected_queues:
            qd = queues[q]
            print(f"  {q}: enqueued={qd['enqueued']}, processed={qd['processed']}, depth={qd['depth']}")


class TestSystemHealth:
    """Test original admin system health endpoint."""

    def test_system_health_still_works(self, auth_headers):
        """GET /api/admin/system-health - Original endpoint still works."""
        response = requests.get(f"{BASE_URL}/api/admin/system-health", headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert "status" in data, "Missing status key"
        assert "timestamp" in data, "Missing timestamp key"
        print(f"✓ System health returned status: {data['status']}")


class TestNightGuardianFlows:
    """Test Night Guardian endpoints create DB records correctly."""

    def test_guardian_start_creates_session(self, auth_headers):
        """POST /api/night-guardian/start - Creates guardian session in DB."""
        payload = {
            "location": {"lat": 12.9700, "lng": 77.5900},  # Starting location (required)
            "destination": {"lat": 12.9716, "lng": 77.5946},  # Destination
        }
        response = requests.post(f"{BASE_URL}/api/night-guardian/start", json=payload, headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data.get("guardian_active") == True, f"Expected guardian_active=True, got {data.get('guardian_active')}"
        print(f"✓ Night Guardian start creates session successfully")

    def test_guardian_update_location(self, auth_headers):
        """POST /api/night-guardian/update-location - Updates location with zone check."""
        # First ensure there's an active session
        start_payload = {
            "location": {"lat": 12.9700, "lng": 77.5900},
            "destination": {"lat": 12.9716, "lng": 77.5946},
        }
        start_response = requests.post(f"{BASE_URL}/api/night-guardian/start", json=start_payload, headers=auth_headers)
        assert start_response.status_code == 200

        # Now update location
        location_payload = {
            "location": {"lat": 12.9750, "lng": 77.6000},
        }
        response = requests.post(f"{BASE_URL}/api/night-guardian/update-location", json=location_payload, headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        # Response may have zone or other status fields
        assert "status" in data or "zone" in data or "alert_count" in data, "Missing status fields in response"
        print(f"✓ Night Guardian location update works, response keys: {list(data.keys())[:5]}")

    def test_guardian_stop_returns_summary(self, auth_headers):
        """POST /api/night-guardian/stop - Stops session and returns summary."""
        # First start a session
        start_payload = {
            "location": {"lat": 12.9700, "lng": 77.5900},
            "destination": {"lat": 12.9716, "lng": 77.5946},
        }
        requests.post(f"{BASE_URL}/api/night-guardian/start", json=start_payload, headers=auth_headers)

        # Now stop (requires body - even if empty object)
        response = requests.post(f"{BASE_URL}/api/night-guardian/stop", json={}, headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data.get("guardian_active") == False or "summary" in data, "Expected guardian_active=False or summary"
        print("✓ Night Guardian stop works and returns summary")


class TestMiddlewareLatencyTracking:
    """Test that monitoring middleware records API latencies."""

    def test_middleware_records_request_latencies(self, auth_headers):
        """Verify API latencies are being recorded by middleware."""
        # Make several requests to generate data
        for _ in range(3):
            requests.get(f"{BASE_URL}/api/admin/monitoring/metrics", headers=auth_headers)
            time.sleep(0.1)

        # Now check metrics to see if latencies are recorded
        response = requests.get(f"{BASE_URL}/api/admin/monitoring/metrics", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()

        ph = data["platform_health"]
        # After making requests, total_requests should be > 0
        assert ph["total_requests"] > 0, f"Expected total_requests > 0, got {ph['total_requests']}"

        # Check if top_endpoints list is populated
        if ph.get("top_endpoints"):
            print(f"✓ Middleware recorded latencies, top endpoint: {ph['top_endpoints'][0]}")
        else:
            print(f"✓ Middleware tracking active, total_requests={ph['total_requests']}")

        # p50 and p95 should be populated
        print(f"  API latency p50: {ph['api_latency_p50_ms']}ms, p95: {ph['api_latency_p95_ms']}ms")


class TestDatabasePoolMetrics:
    """Test database pool stats in monitoring."""

    def test_db_pool_stats_present(self, auth_headers):
        """Verify database pool stats are included in metrics."""
        response = requests.get(f"{BASE_URL}/api/admin/monitoring/metrics", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()

        db = data.get("database", {})
        # Should have pool info or error
        assert "status" in db or "pool_size" in db, "Missing database pool info"
        print(f"✓ Database pool stats present: {db.get('status', 'pool info available')}")


class TestRedisMetrics:
    """Test Redis stats in monitoring (expected disconnected in preview)."""

    def test_redis_status_present(self, auth_headers):
        """Verify Redis status is included in metrics."""
        response = requests.get(f"{BASE_URL}/api/admin/monitoring/metrics", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()

        redis_info = data.get("redis", {})
        assert "status" in redis_info, "Missing Redis status"
        print(f"✓ Redis status present: {redis_info.get('status')}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
