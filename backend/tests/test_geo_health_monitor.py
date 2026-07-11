"""
NISCHINT GEO Health Monitor API Tests
=====================================
Tests for 3 NEW health monitor endpoints:
- GET /api/engine/geo-health/logs - Returns stored health check logs
- GET /api/engine/geo-health/alerts - Returns alerts (pages below threshold 80)
- POST /api/engine/geo-health/run - Triggers full scan (NOT tested - takes 60s)

Also verifies refactored geo-check still works:
- POST /api/engine/geo-check - GEO SEO validation (refactored to use _run_geo_check)
"""

import os
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


@pytest.fixture(scope="session")
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


# ═══════════════════════════════════════════════════════════════
# MODULE 8: GEO HEALTH MONITOR TESTS
# ═══════════════════════════════════════════════════════════════

class TestGeoHealthLogs:
    """GET /api/engine/geo-health/logs - Returns stored health check logs"""
    
    def test_get_health_logs_returns_200(self, api_client):
        """GET /api/engine/geo-health/logs returns 200"""
        response = api_client.get(f"{BASE_URL}/api/engine/geo-health/logs")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print(f"✓ GET /api/engine/geo-health/logs returns 200")
    
    def test_get_health_logs_has_required_fields(self, api_client):
        """GET /api/engine/geo-health/logs returns logs, count, total_stored"""
        response = api_client.get(f"{BASE_URL}/api/engine/geo-health/logs")
        assert response.status_code == 200
        
        data = response.json()
        required_fields = ["logs", "count", "total_stored"]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        
        # Validate types
        assert isinstance(data["logs"], list), "logs should be a list"
        assert isinstance(data["count"], int), "count should be an int"
        assert isinstance(data["total_stored"], int), "total_stored should be an int"
        
        print(f"✓ GET /api/engine/geo-health/logs has required fields:")
        print(f"  count: {data['count']}")
        print(f"  total_stored: {data['total_stored']}")
    
    def test_get_health_logs_contains_scan_data(self, api_client):
        """GET /api/engine/geo-health/logs returns logs with url, score, status, issues, city, timestamp, scan_id"""
        response = api_client.get(f"{BASE_URL}/api/engine/geo-health/logs")
        assert response.status_code == 200
        
        data = response.json()
        logs = data.get("logs", [])
        
        if len(logs) > 0:
            # Check first log entry has required fields
            log_entry = logs[0]
            log_fields = ["url", "score", "status", "issues", "city", "timestamp", "scan_id"]
            for field in log_fields:
                assert field in log_entry, f"Log entry missing field: {field}"
            
            print(f"✓ Log entries have required fields:")
            print(f"  Sample log: url={log_entry['url'][:50]}...")
            print(f"  score={log_entry['score']}, status={log_entry['status']}")
            print(f"  city={log_entry['city']}, scan_id={log_entry['scan_id']}")
        else:
            print(f"⚠ No logs found - scan may not have been run yet")
            # This is acceptable if no scan has been run
    
    def test_get_health_logs_respects_limit_parameter(self, api_client):
        """GET /api/engine/geo-health/logs?limit=5 respects limit parameter"""
        response = api_client.get(f"{BASE_URL}/api/engine/geo-health/logs?limit=5")
        assert response.status_code == 200
        
        data = response.json()
        logs = data.get("logs", [])
        count = data.get("count", 0)
        total_stored = data.get("total_stored", 0)
        
        # If total_stored > 5, count should be 5 (limited)
        # If total_stored <= 5, count should equal total_stored
        if total_stored > 5:
            assert count == 5, f"Expected count=5 with limit=5, got {count}"
            assert len(logs) == 5, f"Expected 5 logs with limit=5, got {len(logs)}"
        else:
            assert count == total_stored, f"Expected count={total_stored}, got {count}"
        
        print(f"✓ GET /api/engine/geo-health/logs?limit=5 respects limit:")
        print(f"  count: {count}, total_stored: {total_stored}")


class TestGeoHealthAlerts:
    """GET /api/engine/geo-health/alerts - Returns alerts for pages below threshold"""
    
    def test_get_health_alerts_returns_200(self, api_client):
        """GET /api/engine/geo-health/alerts returns 200"""
        response = api_client.get(f"{BASE_URL}/api/engine/geo-health/alerts")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print(f"✓ GET /api/engine/geo-health/alerts returns 200")
    
    def test_get_health_alerts_has_required_fields(self, api_client):
        """GET /api/engine/geo-health/alerts returns alerts, count, threshold"""
        response = api_client.get(f"{BASE_URL}/api/engine/geo-health/alerts")
        assert response.status_code == 200
        
        data = response.json()
        required_fields = ["alerts", "count", "threshold"]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        
        # Validate types
        assert isinstance(data["alerts"], list), "alerts should be a list"
        assert isinstance(data["count"], int), "count should be an int"
        assert isinstance(data["threshold"], int), "threshold should be an int"
        
        print(f"✓ GET /api/engine/geo-health/alerts has required fields:")
        print(f"  count: {data['count']}")
        print(f"  threshold: {data['threshold']}")
    
    def test_get_health_alerts_threshold_is_80(self, api_client):
        """GET /api/engine/geo-health/alerts returns threshold=80"""
        response = api_client.get(f"{BASE_URL}/api/engine/geo-health/alerts")
        assert response.status_code == 200
        
        data = response.json()
        threshold = data.get("threshold")
        
        assert threshold == 80, f"Expected threshold=80, got {threshold}"
        print(f"✓ Alert threshold is correctly set to 80")
    
    def test_get_health_alerts_structure(self, api_client):
        """GET /api/engine/geo-health/alerts - alerts have url, score, issues, city, timestamp, scan_id"""
        response = api_client.get(f"{BASE_URL}/api/engine/geo-health/alerts")
        assert response.status_code == 200
        
        data = response.json()
        alerts = data.get("alerts", [])
        
        if len(alerts) > 0:
            # Check first alert has required fields
            alert = alerts[0]
            alert_fields = ["url", "score", "issues", "city", "timestamp", "scan_id"]
            for field in alert_fields:
                assert field in alert, f"Alert missing field: {field}"
            
            # Verify score is below threshold
            assert alert["score"] < 80, f"Alert score should be < 80, got {alert['score']}"
            
            print(f"✓ Alert entries have required fields:")
            print(f"  Sample alert: url={alert['url'][:50]}...")
            print(f"  score={alert['score']}, city={alert['city']}")
        else:
            # No alerts is valid if all pages scored >= 80
            print(f"✓ No alerts found - all pages scored >= 80 (correct behavior)")


class TestGeoHealthRunEndpointExists:
    """POST /api/engine/geo-health/run - Verify endpoint exists (DO NOT trigger full scan)"""
    
    def test_geo_health_run_endpoint_exists(self, api_client):
        """Verify POST /api/engine/geo-health/run endpoint exists by checking OPTIONS or docs"""
        # We verify the endpoint exists by checking the OpenAPI schema
        response = api_client.get(f"{BASE_URL}/api/openapi.json")
        assert response.status_code == 200
        
        openapi = response.json()
        paths = openapi.get("paths", {})
        
        # Check if the endpoint is registered
        endpoint_path = "/api/engine/geo-health/run"
        assert endpoint_path in paths, f"Endpoint {endpoint_path} not found in OpenAPI schema"
        assert "post" in paths[endpoint_path], f"POST method not found for {endpoint_path}"
        
        print(f"✓ POST /api/engine/geo-health/run endpoint exists in OpenAPI schema")
        print(f"  (NOT triggering actual scan - takes 60s and calls 35 external URLs)")


# ═══════════════════════════════════════════════════════════════
# REFACTORED GEO-CHECK VERIFICATION
# ═══════════════════════════════════════════════════════════════

class TestRefactoredGeoCheck:
    """POST /api/engine/geo-check - Verify refactored endpoint still works"""
    
    def test_geo_check_still_works_after_refactor(self, api_client):
        """POST /api/engine/geo-check still works after refactor to use _run_geo_check"""
        response = api_client.post(f"{BASE_URL}/api/engine/geo-check", json={
            "url": "https://gps-mic-restart.preview.emergentagent.com/kids-safety-app-delhi.html"
        })
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        
        # Verify response structure
        required_fields = ["status", "url", "issues", "seo_score", "city_detected"]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        
        print(f"✓ POST /api/engine/geo-check still works after refactor:")
        print(f"  url: {data['url'][:50]}...")
        print(f"  seo_score: {data['seo_score']}")
        print(f"  status: {data['status']}")
        print(f"  city_detected: {data['city_detected']}")
        print(f"  issues: {data['issues']}")
    
    def test_geo_check_on_preview_url_returns_valid_score(self, api_client):
        """POST /api/engine/geo-check on preview URL returns valid score (0-100)"""
        response = api_client.post(f"{BASE_URL}/api/engine/geo-check", json={
            "url": "https://gps-mic-restart.preview.emergentagent.com/women-safety-app-mumbai.html"
        })
        assert response.status_code == 200
        
        data = response.json()
        score = data.get("seo_score", -1)
        
        assert 0 <= score <= 100, f"Score should be 0-100, got {score}"
        print(f"✓ POST /api/engine/geo-check returns valid score: {score}")


# ═══════════════════════════════════════════════════════════════
# VERIFY PREVIOUS ENDPOINTS STILL WORK
# ═══════════════════════════════════════════════════════════════

class TestPreviousEndpointsStillWork:
    """Quick verification that previous entity engine endpoints still work"""
    
    def test_entity_endpoint_still_works(self, api_client):
        """GET /api/engine/entity still works"""
        response = api_client.get(f"{BASE_URL}/api/engine/entity")
        assert response.status_code == 200
        data = response.json()
        assert "company_name" in data
        print(f"✓ GET /api/engine/entity still works: {data['company_name']}")
    
    def test_generate_endpoint_still_works(self, api_client):
        """POST /api/engine/generate still works"""
        response = api_client.post(f"{BASE_URL}/api/engine/generate", json={"platform": "test"})
        assert response.status_code == 200
        data = response.json()
        assert "generated_content" in data
        print(f"✓ POST /api/engine/generate still works")
    
    def test_diff_endpoint_still_works(self, api_client):
        """POST /api/engine/diff still works"""
        response = api_client.post(f"{BASE_URL}/api/engine/diff", json={
            "platform": "test",
            "current_data": "test data"
        })
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        print(f"✓ POST /api/engine/diff still works: status={data['status']}")
    
    def test_queue_endpoint_still_works(self, api_client):
        """GET /api/engine/queue still works"""
        response = api_client.get(f"{BASE_URL}/api/engine/queue")
        assert response.status_code == 200
        data = response.json()
        assert "updates" in data
        assert "count" in data
        print(f"✓ GET /api/engine/queue still works: count={data['count']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
