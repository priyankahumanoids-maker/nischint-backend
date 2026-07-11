"""
Test cases for GET /api/operator/devices/{device_id}/metric-trends endpoint
Tests the anomaly visualization layer with sparkline chart data
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Known device IDs with telemetry data from context
DEVICE_ID_1 = "ce4b5463-5a7e-46a5-8bbf-365dcfb3daeb"  # DEV-001
DEVICE_ID_2 = "e029085c-1021-436d-9dfc-a0633979583d"  # DEV-002


@pytest.fixture(scope="module")
def auth_token():
    """Authenticate as operator and get token"""
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "operator@nischint.com",
        "password": "operator123"
    })
    if resp.status_code != 200:
        pytest.skip(f"Could not authenticate as operator: {resp.status_code}")
    return resp.json().get("access_token")


@pytest.fixture(scope="module")
def headers(auth_token):
    """Return headers with auth token"""
    return {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json"
    }


class TestMetricTrendsEndpoint:
    """Tests for /api/operator/devices/{device_id}/metric-trends"""
    
    def test_metric_trends_returns_correct_structure(self, headers):
        """Backend: GET /api/operator/devices/{device_id}/metric-trends returns correct JSON structure"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEVICE_ID_1}/metric-trends",
            headers=headers
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        
        data = resp.json()
        # Verify top-level structure
        assert "device_id" in data, "Response must have device_id"
        assert "window_minutes" in data, "Response must have window_minutes"
        assert "bucket_seconds" in data, "Response must have bucket_seconds"
        assert "total_points" in data, "Response must have total_points"
        assert "points" in data, "Response must have points array"
        
        # Verify types
        assert data["device_id"] == DEVICE_ID_1
        assert isinstance(data["window_minutes"], int)
        assert isinstance(data["bucket_seconds"], int)
        assert isinstance(data["total_points"], int)
        assert isinstance(data["points"], list)
        
        print(f"SUCCESS: Response structure correct. total_points={data['total_points']}")
    
    def test_metric_trends_respects_window_parameter(self, headers):
        """Backend: metric-trends endpoint respects window_minutes parameter"""
        # Test different window sizes
        for window in [15, 60, 1440, 10080]:
            resp = requests.get(
                f"{BASE_URL}/api/operator/devices/{DEVICE_ID_1}/metric-trends?window_minutes={window}",
                headers=headers
            )
            assert resp.status_code == 200, f"Expected 200 for window={window}, got {resp.status_code}"
            
            data = resp.json()
            assert data["window_minutes"] == window, f"window_minutes should be {window}, got {data['window_minutes']}"
        
        print("SUCCESS: window_minutes parameter respected for all tested values")
    
    def test_metric_trends_point_structure(self, headers):
        """Backend: metric-trends returns points with correct field structure"""
        # Use 7-day window which has more data based on context
        resp = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEVICE_ID_1}/metric-trends?window_minutes=10080",
            headers=headers
        )
        assert resp.status_code == 200
        
        data = resp.json()
        
        # Even if no points, structure should be valid
        if data["total_points"] > 0:
            point = data["points"][0]
            
            # Verify point has required fields
            required_fields = ["timestamp", "battery_level", "signal_strength", 
                              "battery_score", "signal_score", "combined_score", "samples"]
            for field in required_fields:
                assert field in point, f"Point must have '{field}' field"
            
            print(f"SUCCESS: Point structure correct. Fields: {list(point.keys())}")
        else:
            print("INFO: No points returned (sparse test data), but structure is valid")
    
    def test_metric_trends_limits_to_120_points(self, headers):
        """Backend: metric-trends limits points to max 120"""
        # Request large window that might have many points
        resp = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEVICE_ID_1}/metric-trends?window_minutes=10080",
            headers=headers
        )
        assert resp.status_code == 200
        
        data = resp.json()
        assert data["total_points"] <= 120, f"Points should be limited to 120, got {data['total_points']}"
        
        print(f"SUCCESS: Points limited correctly. total_points={data['total_points']} (max 120)")
    
    def test_metric_trends_with_second_device(self, headers):
        """Backend: metric-trends works for different devices"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEVICE_ID_2}/metric-trends?window_minutes=10080",
            headers=headers
        )
        assert resp.status_code == 200
        
        data = resp.json()
        assert data["device_id"] == DEVICE_ID_2
        
        print(f"SUCCESS: Device 2 returns data. total_points={data['total_points']}")
    
    def test_metric_trends_invalid_device_id(self, headers):
        """Backend: metric-trends returns 404 or error for invalid device ID"""
        fake_uuid = "00000000-0000-0000-0000-000000000000"
        resp = requests.get(
            f"{BASE_URL}/api/operator/devices/{fake_uuid}/metric-trends",
            headers=headers
        )
        # Should return empty points or 404 for non-existent device
        # Based on endpoint code, it queries without validating existence first
        # so it should return 200 with 0 points
        assert resp.status_code in [200, 404], f"Expected 200 or 404, got {resp.status_code}"
        
        if resp.status_code == 200:
            data = resp.json()
            assert data["total_points"] == 0, "Non-existent device should have 0 points"
            print("SUCCESS: Non-existent device returns 200 with 0 points")
        else:
            print("SUCCESS: Non-existent device returns 404")
    
    def test_metric_trends_requires_auth(self):
        """Backend: metric-trends requires authentication"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEVICE_ID_1}/metric-trends"
        )
        # Should be 401 or 403 without auth
        assert resp.status_code in [401, 403], f"Expected 401/403 without auth, got {resp.status_code}"
        
        print("SUCCESS: Endpoint requires authentication")
    
    def test_metric_trends_bucket_size_calculation(self, headers):
        """Backend: bucket_seconds is calculated correctly based on window"""
        # For 60 min window: 60*60=3600s / 120 = 30s (min 30)
        resp = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEVICE_ID_1}/metric-trends?window_minutes=60",
            headers=headers
        )
        assert resp.status_code == 200
        data = resp.json()
        
        # bucket should be max(30, total_seconds // 120)
        expected_bucket = max(30, (60 * 60) // 120)
        assert data["bucket_seconds"] == expected_bucket, f"bucket_seconds should be {expected_bucket}"
        
        # For 1440 min (24h): 1440*60=86400s / 120 = 720s
        resp2 = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEVICE_ID_1}/metric-trends?window_minutes=1440",
            headers=headers
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        expected_bucket2 = max(30, (1440 * 60) // 120)
        assert data2["bucket_seconds"] == expected_bucket2, f"bucket_seconds for 24h should be {expected_bucket2}"
        
        print(f"SUCCESS: bucket_seconds calculated correctly: 60min={expected_bucket}s, 24h={expected_bucket2}s")


class TestMetricTrendsIntegration:
    """Integration tests for the full metric trends flow"""
    
    def test_device_health_endpoint_still_works(self, headers):
        """Verify existing device health endpoint works (regression)"""
        resp = requests.get(f"{BASE_URL}/api/operator/device-health", headers=headers)
        assert resp.status_code == 200, f"Device health endpoint failed: {resp.status_code}"
        
        data = resp.json()
        assert isinstance(data, list), "Should return list of devices"
        
        if len(data) > 0:
            device = data[0]
            assert "device_id" in device
            assert "device_identifier" in device
            
        print(f"SUCCESS: Device health endpoint works. {len(data)} devices returned")
    
    def test_incidents_endpoint_still_works(self, headers):
        """Verify existing incidents endpoint works (regression)"""
        resp = requests.get(f"{BASE_URL}/api/operator/incidents", headers=headers)
        assert resp.status_code == 200, f"Incidents endpoint failed: {resp.status_code}"
        
        data = resp.json()
        assert isinstance(data, list), "Should return list of incidents"
        
        print(f"SUCCESS: Incidents endpoint works. {len(data)} incidents returned")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
