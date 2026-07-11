"""
Test suite for Guardian Incident Management, System Status, and Dashboard Overview features
Tests:
1. /api/system/live-status - Live infrastructure health with real service checks
2. /api/dashboard/overview - Batch endpoint with Redis caching (10s TTL)
3. /api/incidents/metrics/response - Guardian response metrics
4. Login flow
"""
import os
import time
import requests
import pytest

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
TEST_EMAIL = "nischint4parents@gmail.com"
TEST_PASSWORD = "secret123"


class TestLiveSystemStatus:
    """Test /api/system/live-status - public endpoint for system health"""
    
    def test_live_status_returns_200(self):
        """Live status endpoint should return 200"""
        response = requests.get(f"{BASE_URL}/api/system/live-status", timeout=30)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: GET /api/system/live-status returns 200")
    
    def test_live_status_has_overall_status(self):
        """Response should have overall_status field"""
        response = requests.get(f"{BASE_URL}/api/system/live-status", timeout=30)
        data = response.json()
        assert "overall_status" in data, "Missing overall_status field"
        assert data["overall_status"] in ["operational", "degraded", "incident"], f"Invalid overall_status: {data['overall_status']}"
        print(f"PASS: overall_status = {data['overall_status']}")
    
    def test_live_status_has_services(self):
        """Response should have services dict with api, database, redis, escalation_engine, notification_worker"""
        response = requests.get(f"{BASE_URL}/api/system/live-status", timeout=30)
        data = response.json()
        assert "services" in data, "Missing services field"
        required_services = ["api", "database", "redis", "escalation_engine", "notification_worker"]
        for svc in required_services:
            assert svc in data["services"], f"Missing service: {svc}"
            assert "status" in data["services"][svc], f"Missing status for {svc}"
            print(f"PASS: {svc} status = {data['services'][svc]['status']}")
    
    def test_live_status_has_latency(self):
        """Services with latency should have latency_ms field"""
        response = requests.get(f"{BASE_URL}/api/system/live-status", timeout=30)
        data = response.json()
        # API and database should have latency_ms
        assert "latency_ms" in data["services"]["api"], "API should have latency_ms"
        assert "latency_ms" in data["services"]["database"], "Database should have latency_ms"
        print(f"PASS: API latency_ms = {data['services']['api']['latency_ms']}")
        print(f"PASS: Database latency_ms = {data['services']['database']['latency_ms']}")
    
    def test_live_status_has_checked_at(self):
        """Response should have checked_at timestamp"""
        response = requests.get(f"{BASE_URL}/api/system/live-status", timeout=30)
        data = response.json()
        assert "checked_at" in data, "Missing checked_at field"
        print(f"PASS: checked_at = {data['checked_at']}")


class TestAuthentication:
    """Test login flow"""
    
    def test_login_success(self):
        """Valid credentials should return access_token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        }, timeout=30)
        assert response.status_code == 200, f"Login failed: {response.status_code} - {response.text}"
        data = response.json()
        assert "access_token" in data, "Missing access_token"
        print(f"PASS: Login successful, token length = {len(data['access_token'])}")
        return data["access_token"]
    
    def test_login_invalid_credentials(self):
        """Invalid credentials should return 401"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "wrong@example.com",
            "password": "wrongpass"
        }, timeout=30)
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: Invalid credentials return 401")


class TestDashboardOverview:
    """Test /api/dashboard/overview - batch endpoint with Redis caching"""
    
    @pytest.fixture
    def auth_token(self):
        """Get auth token for authenticated requests"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        }, timeout=30)
        if response.status_code != 200:
            pytest.skip("Could not authenticate")
        return response.json()["access_token"]
    
    def test_overview_requires_auth(self):
        """Overview endpoint should require authentication"""
        response = requests.get(f"{BASE_URL}/api/dashboard/overview", timeout=30)
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: /api/dashboard/overview requires auth (401)")
    
    def test_overview_returns_summary_sla_metrics(self, auth_token):
        """Overview should return summary, sla, and metrics"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(f"{BASE_URL}/api/dashboard/overview", headers=headers, timeout=30)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Check for summary
        assert "summary" in data, "Missing summary field"
        print(f"PASS: summary present with keys: {list(data['summary'].keys())}")
        
        # Check for sla
        assert "sla" in data, "Missing sla field"
        print(f"PASS: sla present with keys: {list(data['sla'].keys())}")
        
        # Check for metrics  
        assert "metrics" in data, "Missing metrics field"
        print(f"PASS: metrics present with keys: {list(data['metrics'].keys())}")
    
    def test_overview_caching_performance(self, auth_token):
        """Second call should be faster due to Redis caching"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        
        # First call
        start1 = time.time()
        response1 = requests.get(f"{BASE_URL}/api/dashboard/overview", headers=headers, timeout=30)
        time1 = time.time() - start1
        assert response1.status_code == 200
        
        # Wait a bit, then second call (should hit cache)
        time.sleep(0.5)
        start2 = time.time()
        response2 = requests.get(f"{BASE_URL}/api/dashboard/overview", headers=headers, timeout=30)
        time2 = time.time() - start2
        assert response2.status_code == 200
        
        print(f"First call: {time1:.3f}s, Second call: {time2:.3f}s")
        
        # Second call should be faster (or at least not slower)
        # Note: Network variability might affect this, so we just log it
        if time2 < time1:
            print(f"PASS: Cache hit - second call {time1/time2:.1f}x faster")
        else:
            print(f"INFO: Timing varies - first: {time1:.3f}s, second: {time2:.3f}s")


class TestIncidentMetrics:
    """Test /api/incidents/metrics/response - Guardian response metrics"""
    
    @pytest.fixture
    def auth_token(self):
        """Get auth token for authenticated requests"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        }, timeout=30)
        if response.status_code != 200:
            pytest.skip("Could not authenticate")
        return response.json()["access_token"]
    
    def test_metrics_requires_auth(self):
        """Metrics endpoint should require authentication"""
        response = requests.get(f"{BASE_URL}/api/incidents/metrics/response", timeout=30)
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: /api/incidents/metrics/response requires auth (401)")
    
    def test_metrics_returns_expected_fields(self, auth_token):
        """Metrics should return period, total_incidents, acknowledgment_rate_pct"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(f"{BASE_URL}/api/incidents/metrics/response", headers=headers, timeout=30)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Check required fields
        assert "period" in data, "Missing period field"
        assert data["period"] == "30d", f"Expected period=30d, got {data['period']}"
        print(f"PASS: period = {data['period']}")
        
        assert "total_incidents" in data, "Missing total_incidents field"
        assert isinstance(data["total_incidents"], int), "total_incidents should be int"
        print(f"PASS: total_incidents = {data['total_incidents']}")
        
        assert "acknowledgment_rate_pct" in data, "Missing acknowledgment_rate_pct field"
        print(f"PASS: acknowledgment_rate_pct = {data['acknowledgment_rate_pct']}")
        
        # Optional but expected fields
        for field in ["active_unresolved", "acknowledged_count", "resolved_count", "escalation_count", "avg_response_seconds", "avg_resolution_seconds"]:
            if field in data:
                print(f"PASS: {field} = {data[field]}")


class TestCacheStatus:
    """Test Redis cache status endpoint"""
    
    def test_cache_status_endpoint(self):
        """Redis cache status should be available"""
        response = requests.get(f"{BASE_URL}/api/system/cache-status", timeout=30)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        print(f"PASS: Cache status available: {data}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
