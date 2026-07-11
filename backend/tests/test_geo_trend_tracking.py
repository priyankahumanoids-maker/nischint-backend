"""
GEO Trend Tracking Tests - Iteration 185
─────────────────────────────────────────
Tests for NEW trend tracking layer:
- GET /api/engine/geo-health/trends
- GET /api/engine/geo-health/regressions
- GET /api/engine/geo-health/summary
- POST /api/engine/geo-health/deploy-tag
- Verify existing endpoints still work
"""

import pytest
import requests
import os
from datetime import datetime

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestTrendsEndpoint:
    """GET /api/engine/geo-health/trends - Score history per URL"""

    def test_trends_returns_200(self):
        """Trends endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/engine/geo-health/trends")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("✓ GET /geo-health/trends returns 200")

    def test_trends_has_required_fields(self):
        """Response has trends dict and tracked_urls count"""
        response = requests.get(f"{BASE_URL}/api/engine/geo-health/trends")
        data = response.json()
        
        assert "trends" in data, "Missing 'trends' field"
        assert "tracked_urls" in data, "Missing 'tracked_urls' field"
        assert isinstance(data["trends"], dict), "trends should be a dict"
        assert isinstance(data["tracked_urls"], int), "tracked_urls should be int"
        print(f"✓ Trends response has required fields: tracked_urls={data['tracked_urls']}")

    def test_trends_entry_structure(self):
        """Each trend entry has url, data_points, latest_score, rolling_avg_7d, volatility, history"""
        response = requests.get(f"{BASE_URL}/api/engine/geo-health/trends")
        data = response.json()
        
        if data["tracked_urls"] == 0:
            pytest.skip("No tracked URLs - scan may not have run")
        
        # Check first entry
        first_slug = list(data["trends"].keys())[0]
        entry = data["trends"][first_slug]
        
        required_fields = ["url", "data_points", "latest_score", "rolling_avg_7d", "volatility", "history"]
        for field in required_fields:
            assert field in entry, f"Missing field '{field}' in trend entry"
        
        assert isinstance(entry["url"], str), "url should be string"
        assert isinstance(entry["data_points"], int), "data_points should be int"
        assert isinstance(entry["latest_score"], (int, float, type(None))), "latest_score should be numeric or None"
        assert isinstance(entry["rolling_avg_7d"], (int, float)), "rolling_avg_7d should be numeric"
        assert isinstance(entry["volatility"], (int, float)), "volatility should be numeric"
        assert isinstance(entry["history"], list), "history should be list"
        
        print(f"✓ Trend entry structure verified: {first_slug}")
        print(f"  - data_points: {entry['data_points']}")
        print(f"  - latest_score: {entry['latest_score']}")
        print(f"  - rolling_avg_7d: {entry['rolling_avg_7d']}")
        print(f"  - volatility: {entry['volatility']}")

    def test_trends_history_entry_structure(self):
        """History entries have date, score, issues"""
        response = requests.get(f"{BASE_URL}/api/engine/geo-health/trends")
        data = response.json()
        
        if data["tracked_urls"] == 0:
            pytest.skip("No tracked URLs")
        
        first_slug = list(data["trends"].keys())[0]
        entry = data["trends"][first_slug]
        
        if not entry["history"]:
            pytest.skip("No history entries")
        
        hist_entry = entry["history"][0]
        assert "date" in hist_entry, "History entry missing 'date'"
        assert "score" in hist_entry, "History entry missing 'score'"
        assert "issues" in hist_entry, "History entry missing 'issues'"
        
        print(f"✓ History entry structure verified: date={hist_entry['date']}, score={hist_entry['score']}")

    def test_trends_url_filter(self):
        """GET /geo-health/trends?url=specific returns filtered history"""
        # First get a valid URL from trends
        response = requests.get(f"{BASE_URL}/api/engine/geo-health/trends")
        data = response.json()
        
        if data["tracked_urls"] == 0:
            pytest.skip("No tracked URLs")
        
        first_slug = list(data["trends"].keys())[0]
        test_url = data["trends"][first_slug]["url"]
        
        # Now filter by URL
        filtered_response = requests.get(f"{BASE_URL}/api/engine/geo-health/trends", params={"url": test_url})
        assert filtered_response.status_code == 200
        
        filtered_data = filtered_response.json()
        assert "url" in filtered_data, "Filtered response missing 'url'"
        assert "history" in filtered_data, "Filtered response missing 'history'"
        assert "data_points" in filtered_data, "Filtered response missing 'data_points'"
        assert filtered_data["url"] == test_url, "URL mismatch in filtered response"
        
        print(f"✓ URL filter works: {test_url[:50]}... → {filtered_data['data_points']} data points")


class TestRegressionsEndpoint:
    """GET /api/engine/geo-health/regressions - Detected score drops"""

    def test_regressions_returns_200(self):
        """Regressions endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/engine/geo-health/regressions")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("✓ GET /geo-health/regressions returns 200")

    def test_regressions_has_required_fields(self):
        """Response has regressions array, count, total_stored"""
        response = requests.get(f"{BASE_URL}/api/engine/geo-health/regressions")
        data = response.json()
        
        assert "regressions" in data, "Missing 'regressions' field"
        assert "count" in data, "Missing 'count' field"
        assert "total_stored" in data, "Missing 'total_stored' field"
        
        assert isinstance(data["regressions"], list), "regressions should be list"
        assert isinstance(data["count"], int), "count should be int"
        assert isinstance(data["total_stored"], int), "total_stored should be int"
        
        print(f"✓ Regressions response: count={data['count']}, total_stored={data['total_stored']}")

    def test_regressions_limit_parameter(self):
        """Limit parameter works"""
        response = requests.get(f"{BASE_URL}/api/engine/geo-health/regressions", params={"limit": 5})
        assert response.status_code == 200
        data = response.json()
        assert len(data["regressions"]) <= 5, "Limit not respected"
        print("✓ Regressions limit parameter works")


class TestSummaryEndpoint:
    """GET /api/engine/geo-health/summary - Overall health summary"""

    def test_summary_returns_200(self):
        """Summary endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/engine/geo-health/summary")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("✓ GET /geo-health/summary returns 200")

    def test_summary_has_required_fields(self):
        """Response has all required summary fields"""
        response = requests.get(f"{BASE_URL}/api/engine/geo-health/summary")
        data = response.json()
        
        # Check if no_data status
        if data.get("status") == "no_data":
            pytest.skip("No scan data available")
        
        required_fields = [
            "avg_score", "lowest_score", "lowest_url", "total_tracked",
            "healthy_count", "failing_count", "unstable_pages",
            "total_regressions", "last_deploy"
        ]
        
        for field in required_fields:
            assert field in data, f"Missing field '{field}' in summary"
        
        print(f"✓ Summary has all required fields:")
        print(f"  - avg_score: {data['avg_score']}")
        print(f"  - lowest_score: {data['lowest_score']}")
        print(f"  - total_tracked: {data['total_tracked']}")
        print(f"  - healthy_count: {data['healthy_count']}")
        print(f"  - failing_count: {data['failing_count']}")
        print(f"  - total_regressions: {data['total_regressions']}")
        print(f"  - last_deploy: {data['last_deploy']}")

    def test_summary_data_types(self):
        """Summary fields have correct data types"""
        response = requests.get(f"{BASE_URL}/api/engine/geo-health/summary")
        data = response.json()
        
        if data.get("status") == "no_data":
            pytest.skip("No scan data available")
        
        assert isinstance(data["avg_score"], (int, float)), "avg_score should be numeric"
        assert isinstance(data["lowest_score"], (int, float)), "lowest_score should be numeric"
        assert isinstance(data["total_tracked"], int), "total_tracked should be int"
        assert isinstance(data["healthy_count"], int), "healthy_count should be int"
        assert isinstance(data["failing_count"], int), "failing_count should be int"
        assert isinstance(data["unstable_pages"], list), "unstable_pages should be list"
        assert isinstance(data["total_regressions"], int), "total_regressions should be int"
        assert isinstance(data["last_deploy"], str), "last_deploy should be string"
        
        print("✓ Summary data types verified")


class TestDeployTagEndpoint:
    """POST /api/engine/geo-health/deploy-tag - Mark deployment time"""

    def test_deploy_tag_returns_200(self):
        """Deploy-tag endpoint returns 200"""
        response = requests.post(f"{BASE_URL}/api/engine/geo-health/deploy-tag")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("✓ POST /geo-health/deploy-tag returns 200")

    def test_deploy_tag_response_structure(self):
        """Response has status and deploy_time"""
        response = requests.post(f"{BASE_URL}/api/engine/geo-health/deploy-tag")
        data = response.json()
        
        assert "status" in data, "Missing 'status' field"
        assert "deploy_time" in data, "Missing 'deploy_time' field"
        assert data["status"] == "ok", f"Expected status 'ok', got '{data['status']}'"
        
        # Verify deploy_time is ISO format
        try:
            datetime.fromisoformat(data["deploy_time"].replace('Z', '+00:00'))
        except ValueError:
            pytest.fail(f"deploy_time is not valid ISO format: {data['deploy_time']}")
        
        print(f"✓ Deploy-tag response: status={data['status']}, deploy_time={data['deploy_time']}")

    def test_deploy_tag_updates_summary(self):
        """Deploy-tag updates last_deploy in summary"""
        # Tag deployment
        tag_response = requests.post(f"{BASE_URL}/api/engine/geo-health/deploy-tag")
        tag_data = tag_response.json()
        deploy_time = tag_data["deploy_time"]
        
        # Check summary
        summary_response = requests.get(f"{BASE_URL}/api/engine/geo-health/summary")
        summary_data = summary_response.json()
        
        if summary_data.get("status") == "no_data":
            pytest.skip("No scan data available")
        
        assert summary_data["last_deploy"] == deploy_time, "last_deploy not updated in summary"
        print(f"✓ Deploy-tag updates summary.last_deploy: {deploy_time}")


class TestGeoHealthRunResponse:
    """POST /api/engine/geo-health/run - Verify regressions_detected in response"""
    
    def test_run_endpoint_exists(self):
        """Verify /geo-health/run endpoint exists (don't trigger - takes 60s)"""
        # Check OpenAPI schema - use /api/openapi.json
        response = requests.get(f"{BASE_URL}/api/openapi.json")
        assert response.status_code == 200, f"OpenAPI endpoint failed: {response.status_code}"
        
        schema = response.json()
        paths = schema.get("paths", {})
        
        assert "/api/engine/geo-health/run" in paths, "Missing /geo-health/run endpoint"
        assert "post" in paths["/api/engine/geo-health/run"], "Missing POST method"
        
        print("✓ POST /geo-health/run endpoint exists in OpenAPI schema")


class TestExistingEndpointsStillWork:
    """Verify existing endpoints still work after trend tracking addition"""

    def test_geo_health_logs(self):
        """GET /geo-health/logs still works"""
        response = requests.get(f"{BASE_URL}/api/engine/geo-health/logs")
        assert response.status_code == 200
        data = response.json()
        assert "logs" in data
        assert "count" in data
        assert "total_stored" in data
        print(f"✓ GET /geo-health/logs works: count={data['count']}")

    def test_geo_health_alerts(self):
        """GET /geo-health/alerts still works"""
        response = requests.get(f"{BASE_URL}/api/engine/geo-health/alerts")
        assert response.status_code == 200
        data = response.json()
        assert "alerts" in data
        assert "count" in data
        assert "threshold" in data
        assert data["threshold"] == 80, f"Expected threshold 80, got {data['threshold']}"
        print(f"✓ GET /geo-health/alerts works: count={data['count']}, threshold={data['threshold']}")

    def test_entity_endpoint(self):
        """GET /entity still works"""
        response = requests.get(f"{BASE_URL}/api/engine/entity")
        assert response.status_code == 200
        data = response.json()
        assert "company_name" in data
        print(f"✓ GET /entity works: company_name={data['company_name']}")

    def test_geo_check_endpoint(self):
        """POST /geo-check still works"""
        response = requests.post(
            f"{BASE_URL}/api/engine/geo-check",
            json={"url": "https://nischint.care/women-safety-app-mumbai"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "seo_score" in data
        assert "status" in data
        assert "url" in data
        print(f"✓ POST /geo-check works: score={data['seo_score']}, status={data['status']}")


class TestAlertEnhancedFields:
    """Verify alerts include new regression-related fields"""

    def test_alert_structure_has_regression_fields(self):
        """Alerts should have previous_score, drop, regression_type, deployment_related fields"""
        response = requests.get(f"{BASE_URL}/api/engine/geo-health/alerts")
        data = response.json()
        
        if data["count"] == 0:
            # No alerts - check logs for alert structure
            logs_response = requests.get(f"{BASE_URL}/api/engine/geo-health/logs")
            logs_data = logs_response.json()
            
            if logs_data["count"] == 0:
                pytest.skip("No alerts or logs to verify structure")
            
            # Verify log structure instead
            log_entry = logs_data["logs"][0]
            required_log_fields = ["url", "score", "status", "issues", "city", "timestamp", "scan_id"]
            for field in required_log_fields:
                assert field in log_entry, f"Log entry missing '{field}'"
            print("✓ No alerts generated (all scores healthy), log structure verified")
            return
        
        # Check alert structure
        alert = data["alerts"][0]
        
        # These fields should exist (may be None if not a regression)
        expected_fields = ["url", "score", "issues", "timestamp", "scan_id",
                          "previous_score", "drop", "regression_type", "deployment_related"]
        
        for field in expected_fields:
            assert field in alert, f"Alert missing field '{field}'"
        
        print(f"✓ Alert structure has regression fields:")
        print(f"  - previous_score: {alert.get('previous_score')}")
        print(f"  - drop: {alert.get('drop')}")
        print(f"  - regression_type: {alert.get('regression_type')}")
        print(f"  - deployment_related: {alert.get('deployment_related')}")


class TestTrendTrackingDataIntegrity:
    """Verify trend tracking data integrity"""

    def test_tracked_urls_count_matches_trends(self):
        """tracked_urls count matches number of trend entries"""
        response = requests.get(f"{BASE_URL}/api/engine/geo-health/trends")
        data = response.json()
        
        assert data["tracked_urls"] == len(data["trends"]), \
            f"tracked_urls ({data['tracked_urls']}) != len(trends) ({len(data['trends'])})"
        print(f"✓ tracked_urls count matches: {data['tracked_urls']}")

    def test_summary_total_tracked_matches_trends(self):
        """summary.total_tracked matches trends.tracked_urls"""
        trends_response = requests.get(f"{BASE_URL}/api/engine/geo-health/trends")
        trends_data = trends_response.json()
        
        summary_response = requests.get(f"{BASE_URL}/api/engine/geo-health/summary")
        summary_data = summary_response.json()
        
        if summary_data.get("status") == "no_data":
            pytest.skip("No scan data available")
        
        assert summary_data["total_tracked"] == trends_data["tracked_urls"], \
            f"summary.total_tracked ({summary_data['total_tracked']}) != trends.tracked_urls ({trends_data['tracked_urls']})"
        print(f"✓ total_tracked consistent: {summary_data['total_tracked']}")

    def test_healthy_failing_counts_add_up(self):
        """healthy_count + failing_count = total_tracked"""
        response = requests.get(f"{BASE_URL}/api/engine/geo-health/summary")
        data = response.json()
        
        if data.get("status") == "no_data":
            pytest.skip("No scan data available")
        
        total = data["healthy_count"] + data["failing_count"]
        assert total == data["total_tracked"], \
            f"healthy ({data['healthy_count']}) + failing ({data['failing_count']}) != total ({data['total_tracked']})"
        print(f"✓ Counts add up: {data['healthy_count']} healthy + {data['failing_count']} failing = {data['total_tracked']} total")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
