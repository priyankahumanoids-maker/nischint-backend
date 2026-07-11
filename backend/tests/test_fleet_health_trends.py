"""
Fleet Health Trends API Tests
Testing GET /api/operator/fleet-health-trends endpoint
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL').rstrip('/')

class TestFleetHealthTrendsAPI:
    """Fleet-wide health trends endpoint tests"""
    
    @pytest.fixture(autouse=True)
    def setup(self, api_client, auth_token):
        """Setup for each test"""
        self.client = api_client
        self.token = auth_token
        self.headers = {"Authorization": f"Bearer {self.token}"}

    # Test: Endpoint returns correct JSON structure
    def test_fleet_health_trends_returns_correct_structure(self, api_client, auth_token):
        """GET /api/operator/fleet-health-trends returns correct JSON structure"""
        response = api_client.get(
            f"{BASE_URL}/api/operator/fleet-health-trends?window_minutes=10080",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Check required top-level keys
        assert "window_minutes" in data
        assert "bucket_seconds" in data
        assert "total_points" in data
        assert "summary" in data
        assert "points" in data
        
        # Validate types
        assert isinstance(data["window_minutes"], int)
        assert isinstance(data["bucket_seconds"], int)
        assert isinstance(data["total_points"], int)
        assert isinstance(data["summary"], dict)
        assert isinstance(data["points"], list)
        
        print(f"PASS: Correct structure returned - {data['total_points']} points")

    # Test: Summary includes all peak metrics
    def test_fleet_health_trends_summary_has_peak_metrics(self, api_client, auth_token):
        """Summary includes peak_devices_reporting, peak_combined_score, peak_battery_score, peak_signal_score"""
        response = api_client.get(
            f"{BASE_URL}/api/operator/fleet-health-trends?window_minutes=10080",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        
        summary = response.json()["summary"]
        
        assert "peak_devices_reporting" in summary
        assert "peak_combined_score" in summary
        assert "peak_battery_score" in summary
        assert "peak_signal_score" in summary
        
        print(f"PASS: Summary has all peak metrics - devices:{summary['peak_devices_reporting']}, combined:{summary['peak_combined_score']}, battery:{summary['peak_battery_score']}, signal:{summary['peak_signal_score']}")

    # Test: 6h window (360 minutes)
    def test_fleet_health_trends_6h_window(self, api_client, auth_token):
        """Respects window_minutes=360 (6 hours)"""
        response = api_client.get(
            f"{BASE_URL}/api/operator/fleet-health-trends?window_minutes=360",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["window_minutes"] == 360
        # 6h = 21600 seconds, bucket = max(60, 21600//120) = 180 seconds
        assert data["bucket_seconds"] >= 60
        print(f"PASS: 6h window - {data['total_points']} points, bucket={data['bucket_seconds']}s")

    # Test: 24h window (1440 minutes)
    def test_fleet_health_trends_24h_window(self, api_client, auth_token):
        """Respects window_minutes=1440 (24 hours)"""
        response = api_client.get(
            f"{BASE_URL}/api/operator/fleet-health-trends?window_minutes=1440",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["window_minutes"] == 1440
        # 24h = 86400 seconds, bucket = max(60, 86400//120) = 720 seconds
        assert data["bucket_seconds"] >= 60
        print(f"PASS: 24h window - {data['total_points']} points, bucket={data['bucket_seconds']}s")

    # Test: 7d window (10080 minutes)
    def test_fleet_health_trends_7d_window(self, api_client, auth_token):
        """Respects window_minutes=10080 (7 days)"""
        response = api_client.get(
            f"{BASE_URL}/api/operator/fleet-health-trends?window_minutes=10080",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["window_minutes"] == 10080
        # 7d = 604800 seconds, bucket = max(60, 604800//120) = 5040 seconds
        assert data["bucket_seconds"] >= 60
        print(f"PASS: 7d window - {data['total_points']} points, bucket={data['bucket_seconds']}s")

    # Test: Points have correct structure
    def test_fleet_health_trends_points_structure(self, api_client, auth_token):
        """Points include timestamp, devices_reporting, avg/max battery/signal/combined scores"""
        response = api_client.get(
            f"{BASE_URL}/api/operator/fleet-health-trends?window_minutes=10080",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        
        points = response.json()["points"]
        
        if len(points) > 0:
            point = points[0]
            # Check required fields in each point
            assert "timestamp" in point
            assert "devices_reporting" in point
            assert "avg_battery_score" in point
            assert "max_battery_score" in point
            assert "avg_signal_score" in point
            assert "max_signal_score" in point
            assert "avg_combined_score" in point
            assert "max_combined_score" in point
            
            print(f"PASS: Points have correct structure - {len(points)} points")
        else:
            print("SKIP: No data points available - empty dataset")

    # Test: Requires authentication
    def test_fleet_health_trends_requires_auth(self, api_client):
        """Returns 401/403 without authentication"""
        response = api_client.get(f"{BASE_URL}/api/operator/fleet-health-trends")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print(f"PASS: Requires auth - returns {response.status_code}")

    # Test: Requires operator/admin role (use guardian token to test)
    def test_fleet_health_trends_requires_operator_role(self, api_client):
        """Guardian role should be rejected"""
        # Login as guardian
        login_resp = api_client.post(f"{BASE_URL}/api/auth/login", json={
            "email": "guardian@nischint.com",
            "password": "guardian123"
        })
        if login_resp.status_code != 200:
            pytest.skip("Guardian login not available for role test")
        
        guardian_token = login_resp.json().get("access_token")
        response = api_client.get(
            f"{BASE_URL}/api/operator/fleet-health-trends",
            headers={"Authorization": f"Bearer {guardian_token}"}
        )
        assert response.status_code == 403, f"Expected 403 for guardian, got {response.status_code}"
        print("PASS: Guardian role correctly rejected with 403")

    # Test: Points are limited to max 120
    def test_fleet_health_trends_limits_points(self, api_client, auth_token):
        """Points should be limited to max 120"""
        response = api_client.get(
            f"{BASE_URL}/api/operator/fleet-health-trends?window_minutes=10080",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        
        points = response.json()["points"]
        total_points = response.json()["total_points"]
        
        assert total_points <= 120, f"Expected max 120 points, got {total_points}"
        assert len(points) <= 120, f"Expected max 120 points in array, got {len(points)}"
        print(f"PASS: Points limited - {len(points)}")

    # Test: Bucket seconds calculation is correct
    def test_fleet_health_trends_bucket_calculation(self, api_client, auth_token):
        """bucket_seconds = max(60, window_seconds // 120)"""
        response = api_client.get(
            f"{BASE_URL}/api/operator/fleet-health-trends?window_minutes=10080",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        
        data = response.json()
        window_seconds = data["window_minutes"] * 60
        expected_bucket = max(60, window_seconds // 120)
        
        assert data["bucket_seconds"] == expected_bucket, f"Expected bucket={expected_bucket}, got {data['bucket_seconds']}"
        print(f"PASS: Bucket calculation correct - {data['bucket_seconds']}s")


@pytest.fixture
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


@pytest.fixture
def auth_token(api_client):
    """Get operator authentication token"""
    response = api_client.post(f"{BASE_URL}/api/auth/login", json={
        "email": "operator@nischint.com",
        "password": "operator123"
    })
    if response.status_code == 200:
        return response.json().get("access_token")
    pytest.skip("Operator authentication failed - skipping authenticated tests")
