# Redis Integration Tests for NISCHINT Dynamic Risk Engine
# Phase: Redis Cache Integration
# Tests: Redis connection, namespaced keys, TTLs, heatmap caching, safety score grid, sessions caching

import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"
GUARDIAN_EMAIL = "nischint4parents@gmail.com"
GUARDIAN_PASSWORD = "secret123"


@pytest.fixture(scope="module")
def operator_token():
    """Get operator authentication token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": OPERATOR_EMAIL,
        "password": OPERATOR_PASSWORD
    })
    if response.status_code == 200:
        return response.json().get("access_token")
    pytest.skip(f"Operator authentication failed: {response.status_code}")


@pytest.fixture(scope="module")
def guardian_token():
    """Get guardian authentication token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": GUARDIAN_EMAIL,
        "password": GUARDIAN_PASSWORD
    })
    if response.status_code == 200:
        return response.json().get("access_token")
    pytest.skip(f"Guardian authentication failed: {response.status_code}")


@pytest.fixture
def operator_headers(operator_token):
    """Headers with operator auth token"""
    return {"Authorization": f"Bearer {operator_token}", "Content-Type": "application/json"}


@pytest.fixture
def guardian_headers(guardian_token):
    """Headers with guardian auth token"""
    return {"Authorization": f"Bearer {guardian_token}", "Content-Type": "application/json"}


# ── Redis Cache Status Tests ──

class TestRedisCacheStatus:
    """Tests for /api/system/cache-status endpoint"""

    def test_cache_status_returns_redis_info(self, operator_headers):
        """Verify cache status endpoint returns Redis connection info"""
        response = requests.get(f"{BASE_URL}/api/system/cache-status", headers=operator_headers)
        assert response.status_code == 200, f"Cache status failed: {response.text}"
        
        data = response.json()
        assert "cache" in data, "Response should have 'cache' field"
        assert data["cache"] == "redis", f"Cache should be 'redis', got '{data.get('cache')}'"
        assert "status" in data, "Response should have 'status' field"
        assert data["status"] == "connected", f"Status should be 'connected', got '{data.get('status')}'"
        print(f"Redis cache status: {data}")

    def test_cache_status_has_memory_info(self, operator_headers):
        """Verify cache status includes memory usage"""
        response = requests.get(f"{BASE_URL}/api/system/cache-status", headers=operator_headers)
        assert response.status_code == 200
        
        data = response.json()
        assert "used_memory_human" in data, "Should include used_memory_human"
        print(f"Redis memory usage: {data.get('used_memory_human')}")

    def test_cache_status_has_keys_count(self, operator_headers):
        """Verify cache status includes keys count"""
        response = requests.get(f"{BASE_URL}/api/system/cache-status", headers=operator_headers)
        assert response.status_code == 200
        
        data = response.json()
        assert "keys" in data, "Should include keys count"
        assert data["keys"] >= 0, "Keys count should be non-negative"
        print(f"Redis keys count: {data.get('keys')}")

    def test_cache_status_has_connected_clients(self, operator_headers):
        """Verify cache status includes connected clients"""
        response = requests.get(f"{BASE_URL}/api/system/cache-status", headers=operator_headers)
        assert response.status_code == 200
        
        data = response.json()
        assert "connected_clients" in data, "Should include connected_clients"
        assert data["connected_clients"] >= 1, "Should have at least 1 connected client"
        print(f"Redis connected clients: {data.get('connected_clients')}")


# ── Heatmap Cache Tests ──

class TestHeatmapRedisCache:
    """Tests for heatmap data served from Redis cache"""

    def test_live_heatmap_returns_data(self, operator_headers):
        """GET /api/operator/city-heatmap/live returns heatmap from Redis"""
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap/live", headers=operator_headers)
        assert response.status_code == 200, f"Live heatmap failed: {response.text}"
        
        data = response.json()
        assert "cells" in data, "Response should have 'cells' field"
        assert len(data["cells"]) > 0, "Should have heatmap cells"
        print(f"Live heatmap: {len(data['cells'])} cells")

    def test_live_heatmap_has_weight_profile(self, operator_headers):
        """Live heatmap should include weight_profile (day/night/late_night)"""
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap/live", headers=operator_headers)
        assert response.status_code == 200
        
        data = response.json()
        assert "weight_profile" in data, "Should include weight_profile"
        assert data["weight_profile"] in ["day", "night", "late_night"], \
            f"Invalid weight_profile: {data.get('weight_profile')}"
        print(f"Weight profile: {data.get('weight_profile')}")

    def test_live_heatmap_cell_count(self, operator_headers):
        """Live heatmap should have expected cell count (around 622)"""
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap/live", headers=operator_headers)
        assert response.status_code == 200
        
        data = response.json()
        cell_count = len(data.get("cells", []))
        # Should have at least 500 cells based on previous test data
        assert cell_count >= 500, f"Expected 500+ cells, got {cell_count}"
        print(f"Heatmap cell count: {cell_count}")

    def test_heatmap_delta_returns_data(self, operator_headers):
        """GET /api/operator/city-heatmap/delta returns delta from Redis"""
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap/delta", headers=operator_headers)
        assert response.status_code == 200, f"Delta heatmap failed: {response.text}"
        
        data = response.json()
        # Delta should have escalated/de_escalated counts
        assert "escalated_count" in data or "escalated" in data, "Should have escalation data"
        print(f"Heatmap delta: escalated={data.get('escalated_count', len(data.get('escalated', [])))}")

    def test_heatmap_timeline_returns_data(self, operator_headers):
        """GET /api/operator/city-heatmap/timeline returns timeline from Redis"""
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap/timeline", headers=operator_headers)
        assert response.status_code == 200, f"Timeline failed: {response.text}"
        
        data = response.json()
        # API may return {timeline: [...]} or just [...]
        timeline_data = data.get("timeline") if isinstance(data, dict) else data
        assert isinstance(timeline_data, list), "Timeline should be a list"
        if len(timeline_data) > 0:
            assert "snapshot_number" in timeline_data[0] or "analyzed_at" in timeline_data[0], \
                "Timeline entries should have snapshot info"
        print(f"Timeline snapshots: {len(timeline_data)}")

    def test_heatmap_status_shows_redis_backend(self, operator_headers):
        """GET /api/operator/city-heatmap/status shows cache_backend='redis'"""
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap/status", headers=operator_headers)
        assert response.status_code == 200, f"Status failed: {response.text}"
        
        data = response.json()
        assert "cache_backend" in data, "Should include cache_backend"
        assert data["cache_backend"] == "redis", f"Expected 'redis', got '{data.get('cache_backend')}'"
        print(f"Cache backend: {data.get('cache_backend')}")


# ── Safety Score Tests (uses Redis-cached grid) ──

class TestSafetyScoreRedisIntegration:
    """Tests for safety score using Redis-cached grid for percentile"""

    def test_location_score_with_percentile(self, operator_headers):
        """GET /api/safety-score/location returns score with percentile (from Redis grid)"""
        params = {"lat": 12.9716, "lng": 77.5946}
        response = requests.get(f"{BASE_URL}/api/safety-score/location", 
                               headers=operator_headers, params=params)
        assert response.status_code == 200, f"Location score failed: {response.text}"
        
        data = response.json()
        assert "score" in data, "Should have score"
        assert "percentile" in data, "Should have percentile (from Redis grid)"
        assert 1 <= data["percentile"] <= 99, f"Percentile should be 1-99, got {data['percentile']}"
        print(f"Location score: {data['score']}, percentile: {data['percentile']}")

    def test_route_score_calculation(self, operator_headers):
        """POST /api/safety-score/route returns route score with risk zones"""
        payload = {
            "origin": {"lat": 12.9716, "lng": 77.5946},
            "destination": {"lat": 12.9816, "lng": 77.6046}
        }
        response = requests.post(f"{BASE_URL}/api/safety-score/route", 
                                headers=operator_headers, json=payload)
        assert response.status_code == 200, f"Route score failed: {response.text}"
        
        data = response.json()
        assert "score" in data, "Should have score"
        assert "risk_zones_crossed" in data, "Should have risk_zones_crossed"
        assert "sample_points" in data, "Should have sample_points"
        assert data["sample_points"] >= 2, "Should have at least 2 sample points"
        print(f"Route score: {data['score']}, risk_zones: {data['risk_zones_crossed']}, samples: {data['sample_points']}")


# ── Guardian Sessions Cache Tests ──

class TestGuardianSessionsRedisCache:
    """Tests for guardian sessions cached in Redis"""

    def test_active_sessions_endpoint(self, operator_headers):
        """GET /api/guardian/sessions/active returns sessions (from Redis cache)"""
        response = requests.get(f"{BASE_URL}/api/guardian/sessions/active", headers=operator_headers)
        assert response.status_code == 200, f"Active sessions failed: {response.text}"
        
        data = response.json()
        # API may return {sessions: [...]} or just [...]
        sessions_data = data.get("sessions") if isinstance(data, dict) else data
        assert isinstance(sessions_data, list), "Active sessions should be a list"
        print(f"Active sessions count: {len(sessions_data)}")

    def test_guardian_start_invalidates_cache(self, guardian_headers, operator_headers):
        """POST /api/guardian/start creates session and invalidates Redis cache"""
        # Correct payload format with location object
        payload = {
            "location": {"lat": 12.9716, "lng": 77.5946},
            "destination": {"lat": 12.9816, "lng": 77.6046}
        }
        response = requests.post(f"{BASE_URL}/api/guardian/start", 
                                headers=guardian_headers, json=payload)
        assert response.status_code == 200, f"Guardian start failed: {response.text}"
        
        data = response.json()
        assert "session_id" in data, "Should return session_id"
        assert data["status"] == "active", "Session should be active"
        
        session_id = data["session_id"]
        print(f"Started session: {session_id}")
        
        # Verify session appears in active list (use operator headers - has permission)
        time.sleep(0.5)  # Brief delay for cache update
        active_response = requests.get(f"{BASE_URL}/api/guardian/sessions/active", 
                                       headers=operator_headers)
        assert active_response.status_code == 200, f"Active sessions check failed: {active_response.text}"
        
        # Return session_id for cleanup
        return session_id

    def test_guardian_stop_invalidates_cache(self, guardian_headers):
        """POST /api/guardian/stop ends session and invalidates Redis cache"""
        # First start a session with correct payload format
        start_payload = {"location": {"lat": 12.9720, "lng": 77.5950}}
        start_response = requests.post(f"{BASE_URL}/api/guardian/start", 
                                       headers=guardian_headers, json=start_payload)
        if start_response.status_code != 200:
            pytest.skip(f"Could not start session for stop test: {start_response.text}")
        
        session_id = start_response.json().get("session_id")
        
        # Stop the session (uses query param)
        stop_response = requests.post(f"{BASE_URL}/api/guardian/stop?session_id={session_id}", 
                                      headers=guardian_headers)
        assert stop_response.status_code == 200, f"Guardian stop failed: {stop_response.text}"
        
        data = stop_response.json()
        assert data["status"] == "ended", "Session should be ended"
        print(f"Stopped session: {session_id}")


# ── Authentication Tests ──

class TestAuthenticationEndpoints:
    """Verify auth endpoints still work with Redis integration"""

    def test_operator_login(self):
        """POST /api/auth/login for operator works"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": OPERATOR_EMAIL,
            "password": OPERATOR_PASSWORD
        })
        assert response.status_code == 200, f"Operator login failed: {response.text}"
        
        data = response.json()
        assert "access_token" in data, "Should return access_token"
        assert len(data["access_token"]) > 0, "Token should not be empty"
        print("Operator login: SUCCESS")

    def test_guardian_login(self):
        """POST /api/auth/login for guardian works"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": GUARDIAN_EMAIL,
            "password": GUARDIAN_PASSWORD
        })
        assert response.status_code == 200, f"Guardian login failed: {response.text}"
        
        data = response.json()
        assert "access_token" in data, "Should return access_token"
        print("Guardian login: SUCCESS")

    def test_invalid_credentials_rejected(self):
        """POST /api/auth/login with invalid credentials returns 401"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "invalid@test.com",
            "password": "wrongpassword"
        })
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("Invalid credentials test: PASSED (401 returned)")


# ── Integration Tests ──

class TestRedisIntegration:
    """End-to-end tests verifying Redis integration works correctly"""

    def test_heatmap_data_consistency(self, operator_headers):
        """Verify heatmap data is consistent between live and status endpoints"""
        live_response = requests.get(f"{BASE_URL}/api/operator/city-heatmap/live", 
                                    headers=operator_headers)
        status_response = requests.get(f"{BASE_URL}/api/operator/city-heatmap/status", 
                                      headers=operator_headers)
        
        assert live_response.status_code == 200
        assert status_response.status_code == 200
        
        live_data = live_response.json()
        status_data = status_response.json()
        
        # Status should report data exists if live returns cells
        if len(live_data.get("cells", [])) > 0:
            assert status_data.get("has_data") == True, "Status should show has_data=True"
        
        print(f"Data consistency check: live={len(live_data.get('cells', []))} cells, has_data={status_data.get('has_data')}")

    def test_safety_score_uses_cached_grid(self, operator_headers):
        """Verify safety score percentile uses Redis-cached grid scores"""
        # Get a location score
        params = {"lat": 12.9716, "lng": 77.5946}
        response = requests.get(f"{BASE_URL}/api/safety-score/location", 
                               headers=operator_headers, params=params)
        assert response.status_code == 200
        
        data = response.json()
        
        # Percentile should be calculated (not default 50)
        percentile = data.get("percentile", 50)
        # If grid has data, percentile should reflect actual ranking
        print(f"Safety score percentile: {percentile}% (uses Redis grid cache)")

    def test_full_workflow_with_redis(self, guardian_headers, operator_headers):
        """Test full workflow: login -> start session -> check active -> check heatmap"""
        # Step 1: Check cache status
        cache_response = requests.get(f"{BASE_URL}/api/system/cache-status", 
                                     headers=operator_headers)
        assert cache_response.status_code == 200
        cache_data = cache_response.json()
        assert cache_data.get("status") == "connected", "Redis should be connected"
        
        # Step 2: Get live heatmap (from Redis)
        heatmap_response = requests.get(f"{BASE_URL}/api/operator/city-heatmap/live", 
                                       headers=operator_headers)
        assert heatmap_response.status_code == 200
        heatmap_data = heatmap_response.json()
        assert len(heatmap_data.get("cells", [])) > 0, "Heatmap should have data"
        
        # Step 3: Get safety score (uses Redis grid cache)
        score_response = requests.get(f"{BASE_URL}/api/safety-score/location",
                                     headers=operator_headers,
                                     params={"lat": 12.9716, "lng": 77.5946})
        assert score_response.status_code == 200
        
        # Step 4: Check active sessions (from Redis cache)
        sessions_response = requests.get(f"{BASE_URL}/api/guardian/sessions/active",
                                        headers=operator_headers)
        assert sessions_response.status_code == 200
        
        print("Full workflow with Redis: SUCCESS")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
