# OSRM Self-Hosted Integration Tests
# Tests for self-hosted OSRM v5.27.1 with Redis route caching
# Endpoints tested: /api/system/osrm-status, /api/system/cache-status, /api/safe-route, 
# /api/predictive-alert, /api/safety-score/location, /api/operator/city-heatmap/*

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


class TestOSRMServiceStatus:
    """Tests for OSRM service health endpoint"""
    
    def test_osrm_status_connected(self):
        """GET /api/system/osrm-status returns connected status"""
        resp = requests.get(f"{BASE_URL}/api/system/osrm-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["osrm"] == "connected", f"OSRM should be connected, got: {data}"
        
    def test_osrm_status_source_self_hosted(self):
        """OSRM source should be self-hosted"""
        resp = requests.get(f"{BASE_URL}/api/system/osrm-status")
        data = resp.json()
        assert data["source"] == "self-hosted", f"Expected self-hosted, got: {data['source']}"
        
    def test_osrm_test_route_ok(self):
        """OSRM test route should return ok"""
        resp = requests.get(f"{BASE_URL}/api/system/osrm-status")
        data = resp.json()
        assert data["test_route"] == "ok", f"Test route failed: {data}"
        
    def test_osrm_url_configured(self):
        """OSRM URL should point to localhost:5000"""
        resp = requests.get(f"{BASE_URL}/api/system/osrm-status")
        data = resp.json()
        assert "localhost:5000" in data.get("url", ""), f"OSRM URL should be localhost:5000, got: {data.get('url')}"


class TestRedisCacheStatus:
    """Tests for Redis cache health endpoint"""
    
    def test_cache_status_connected(self):
        """GET /api/system/cache-status returns connected status"""
        resp = requests.get(f"{BASE_URL}/api/system/cache-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "connected", f"Redis should be connected, got: {data}"
        
    def test_cache_status_has_keys(self):
        """Redis should have cached keys"""
        resp = requests.get(f"{BASE_URL}/api/system/cache-status")
        data = resp.json()
        assert data.get("keys", 0) > 0, f"Redis should have keys, got: {data.get('keys')}"
        
    def test_cache_backend_is_redis(self):
        """Cache backend should be redis"""
        resp = requests.get(f"{BASE_URL}/api/system/cache-status")
        data = resp.json()
        assert data.get("cache") == "redis", f"Cache backend should be redis, got: {data.get('cache')}"


class TestAuthentication:
    """Tests for authentication endpoints"""
    
    def test_operator_login_success(self):
        """POST /api/auth/login with operator credentials returns valid JWT"""
        resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": OPERATOR_EMAIL,
            "password": OPERATOR_PASSWORD
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data, "Response should contain access_token"
        assert data["role"] == "operator", f"Role should be operator, got: {data['role']}"
        
    def test_guardian_login_success(self):
        """POST /api/auth/login with guardian credentials returns valid JWT"""
        resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": GUARDIAN_EMAIL,
            "password": GUARDIAN_PASSWORD
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data, "Response should contain access_token"
        assert data["role"] == "guardian", f"Role should be guardian, got: {data['role']}"
        
    def test_invalid_credentials_rejected(self):
        """Invalid credentials should return 401"""
        resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "wrong@test.com",
            "password": "wrongpassword"
        })
        assert resp.status_code == 401


@pytest.fixture
def operator_token():
    """Get operator JWT token"""
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": OPERATOR_EMAIL,
        "password": OPERATOR_PASSWORD
    })
    if resp.status_code == 200:
        return resp.json()["access_token"]
    pytest.skip("Failed to get operator token")


@pytest.fixture
def guardian_token():
    """Get guardian JWT token"""
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": GUARDIAN_EMAIL,
        "password": GUARDIAN_PASSWORD
    })
    if resp.status_code == 200:
        return resp.json()["access_token"]
    pytest.skip("Failed to get guardian token")


class TestSafeRouteAPI:
    """Tests for POST /api/safe-route endpoint with OSRM integration"""
    
    def test_safe_route_returns_three_routes(self, operator_token):
        """POST /api/safe-route returns 3 routes (fastest/safest/balanced)"""
        headers = {"Authorization": f"Bearer {operator_token}"}
        resp = requests.post(f"{BASE_URL}/api/safe-route", 
            headers=headers,
            json={
                "origin": {"lat": 12.9716, "lng": 77.5946},
                "destination": {"lat": 12.9352, "lng": 77.6245}
            }
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "routes" in data, "Response should contain routes"
        assert len(data["routes"]) == 3, f"Should have 3 routes, got: {len(data['routes'])}"
        
    def test_safe_route_types(self, operator_token):
        """Routes should have types: fastest, safest, balanced"""
        headers = {"Authorization": f"Bearer {operator_token}"}
        resp = requests.post(f"{BASE_URL}/api/safe-route", 
            headers=headers,
            json={
                "origin": {"lat": 12.9716, "lng": 77.5946},
                "destination": {"lat": 12.9352, "lng": 77.6245}
            }
        )
        data = resp.json()
        route_types = [r["type"] for r in data["routes"]]
        assert "fastest" in route_types, "Should have fastest route"
        assert "safest" in route_types, "Should have safest route"
        assert "balanced" in route_types, "Should have balanced route"
        
    def test_safe_route_has_distance_km(self, operator_token):
        """Each route should have distance_km"""
        headers = {"Authorization": f"Bearer {operator_token}"}
        resp = requests.post(f"{BASE_URL}/api/safe-route", 
            headers=headers,
            json={
                "origin": {"lat": 12.9716, "lng": 77.5946},
                "destination": {"lat": 12.9352, "lng": 77.6245}
            }
        )
        data = resp.json()
        for route in data["routes"]:
            assert "distance_km" in route, f"Route {route['type']} missing distance_km"
            assert route["distance_km"] > 0, f"Route {route['type']} should have positive distance"
            
    def test_safe_route_has_risk_score(self, operator_token):
        """Each route should have risk_score"""
        headers = {"Authorization": f"Bearer {operator_token}"}
        resp = requests.post(f"{BASE_URL}/api/safe-route", 
            headers=headers,
            json={
                "origin": {"lat": 12.9716, "lng": 77.5946},
                "destination": {"lat": 12.9352, "lng": 77.6245}
            }
        )
        data = resp.json()
        for route in data["routes"]:
            assert "risk_score" in route, f"Route {route['type']} missing risk_score"
            assert isinstance(route["risk_score"], (int, float)), "risk_score should be numeric"
            
    def test_safe_route_requires_auth(self):
        """POST /api/safe-route without auth returns 401"""
        resp = requests.post(f"{BASE_URL}/api/safe-route", json={
            "origin": {"lat": 12.9716, "lng": 77.5946},
            "destination": {"lat": 12.9352, "lng": 77.6245}
        })
        assert resp.status_code in [401, 403], f"Expected 401/403, got: {resp.status_code}"


class TestSafeRouteRedisCache:
    """Tests for Redis route caching in safe-route API"""
    
    def test_second_call_uses_cache(self, operator_token):
        """Second safe route call should hit Redis cache"""
        import subprocess
        headers = {"Authorization": f"Bearer {operator_token}"}
        
        # Make first call to populate cache
        resp1 = requests.post(f"{BASE_URL}/api/safe-route", 
            headers=headers,
            json={
                "origin": {"lat": 12.9716, "lng": 77.5946},
                "destination": {"lat": 12.9352, "lng": 77.6245}
            }
        )
        assert resp1.status_code == 200
        
        # Verify route key exists in Redis
        result = subprocess.run(
            ["redis-cli", "keys", "nischint:route:*"],
            capture_output=True, text=True
        )
        assert "nischint:route:" in result.stdout, f"Route cache key should exist, got: {result.stdout}"
        
    def test_redis_route_key_pattern(self):
        """Redis should have nischint:route:* keys"""
        import subprocess
        result = subprocess.run(
            ["redis-cli", "keys", "nischint:route:*"],
            capture_output=True, text=True
        )
        keys = [k.strip() for k in result.stdout.strip().split('\n') if k.strip()]
        assert len(keys) > 0, "Should have at least one route cache key"


class TestPredictiveAlert:
    """Tests for predictive alert endpoints"""
    
    def test_predictive_alert_basic(self, operator_token):
        """POST /api/predictive-alert returns alerts"""
        headers = {"Authorization": f"Bearer {operator_token}"}
        resp = requests.post(f"{BASE_URL}/api/predictive-alert", 
            headers=headers,
            json={
                "location": {"lat": 12.9716, "lng": 77.5946},
                "speed": 40
            }
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "alert" in data, "Response should have alert field"
        assert "location" in data, "Response should have location"
        
    def test_predictive_alert_with_alternative(self, operator_token):
        """POST /api/predictive-alert/with-alternative returns response"""
        headers = {"Authorization": f"Bearer {operator_token}"}
        resp = requests.post(f"{BASE_URL}/api/predictive-alert/with-alternative", 
            headers=headers,
            json={
                "location": {"lat": 12.9716, "lng": 77.5946},
                "speed": 40
            }
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "alert" in data, "Response should have alert field"


class TestSafetyScoreLocation:
    """Tests for safety score location endpoint"""
    
    def test_safety_score_location_returns_score(self, operator_token):
        """GET /api/safety-score/location returns score with percentile"""
        headers = {"Authorization": f"Bearer {operator_token}"}
        resp = requests.get(
            f"{BASE_URL}/api/safety-score/location?lat=12.9716&lng=77.5946",
            headers=headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "score" in data, "Response should have score"
        assert "percentile" in data, "Response should have percentile"
        
    def test_safety_score_has_label(self, operator_token):
        """Safety score should have label and category"""
        headers = {"Authorization": f"Bearer {operator_token}"}
        resp = requests.get(
            f"{BASE_URL}/api/safety-score/location?lat=12.9716&lng=77.5946",
            headers=headers
        )
        data = resp.json()
        assert "label" in data, "Response should have label"
        assert "category" in data, "Response should have category"


class TestCityHeatmap:
    """Tests for city heatmap endpoints"""
    
    def test_heatmap_live_returns_cells(self, operator_token):
        """GET /api/operator/city-heatmap/live returns heatmap with cells"""
        headers = {"Authorization": f"Bearer {operator_token}"}
        resp = requests.get(
            f"{BASE_URL}/api/operator/city-heatmap/live",
            headers=headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "cells" in data, "Response should have cells"
        
    def test_heatmap_live_has_622_cells(self, operator_token):
        """Live heatmap should have 622 cells"""
        headers = {"Authorization": f"Bearer {operator_token}"}
        resp = requests.get(
            f"{BASE_URL}/api/operator/city-heatmap/live",
            headers=headers
        )
        data = resp.json()
        cell_count = len(data.get("cells", []))
        assert cell_count == 622, f"Expected 622 cells, got: {cell_count}"
        
    def test_heatmap_status_redis_backend(self, operator_token):
        """GET /api/operator/city-heatmap/status shows cache_backend='redis'"""
        headers = {"Authorization": f"Bearer {operator_token}"}
        resp = requests.get(
            f"{BASE_URL}/api/operator/city-heatmap/status",
            headers=headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("cache_backend") == "redis", f"Expected redis backend, got: {data.get('cache_backend')}"


class TestOSRMDirectAccess:
    """Tests for direct OSRM service access"""
    
    def test_osrm_direct_route(self):
        """Direct OSRM call to localhost:5000 should work"""
        import subprocess
        result = subprocess.run(
            ["curl", "-s", "http://localhost:5000/route/v1/driving/77.5946,12.9716;77.6245,12.9352?overview=false"],
            capture_output=True, text=True
        )
        import json
        data = json.loads(result.stdout)
        assert data.get("code") == "Ok", f"OSRM direct call failed: {data}"
        
    def test_osrm_latency_under_100ms(self):
        """OSRM routing latency should be under 100ms"""
        import subprocess
        import time
        start = time.time()
        result = subprocess.run(
            ["curl", "-s", "http://localhost:5000/route/v1/driving/77.5946,12.9716;77.6245,12.9352?overview=false"],
            capture_output=True, text=True
        )
        latency_ms = (time.time() - start) * 1000
        assert latency_ms < 100, f"OSRM latency should be <100ms, got: {latency_ms:.0f}ms"
        

class TestRedisRouteKeys:
    """Tests for Redis route cache keys"""
    
    def test_redis_route_key_exists(self, operator_token):
        """Redis should have nischint:route:* keys after safe route call"""
        import subprocess
        headers = {"Authorization": f"Bearer {operator_token}"}
        
        # Make a route call
        requests.post(f"{BASE_URL}/api/safe-route", 
            headers=headers,
            json={
                "origin": {"lat": 12.9716, "lng": 77.5946},
                "destination": {"lat": 12.9352, "lng": 77.6245}
            }
        )
        
        # Check Redis keys
        result = subprocess.run(
            ["redis-cli", "keys", "nischint:route:*"],
            capture_output=True, text=True
        )
        assert "nischint:route:" in result.stdout
        
    def test_redis_route_key_ttl(self):
        """Route cache keys should have TTL around 1800s (30 min)"""
        import subprocess
        result = subprocess.run(
            ["redis-cli", "keys", "nischint:route:*"],
            capture_output=True, text=True
        )
        keys = [k.strip() for k in result.stdout.strip().split('\n') if k.strip()]
        if keys:
            ttl_result = subprocess.run(
                ["redis-cli", "ttl", keys[0]],
                capture_output=True, text=True
            )
            ttl = int(ttl_result.stdout.strip())
            assert 0 < ttl <= 1800, f"Route cache TTL should be <=1800s, got: {ttl}"
