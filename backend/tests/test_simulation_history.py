"""
Simulation History API Tests

Tests for the immutable research log endpoints:
- GET /api/operator/simulations - paginated list
- GET /api/operator/simulations/{simulation_run_id} - detail view
- Immutability verification (no PUT/DELETE)
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL')

# Test credentials
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"


@pytest.fixture(scope="module")
def operator_token():
    """Authenticate as operator and return token"""
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD}
    )
    assert response.status_code == 200, f"Login failed: {response.text}"
    return response.json()["access_token"]


@pytest.fixture
def auth_headers(operator_token):
    """Return headers with bearer token"""
    return {
        "Authorization": f"Bearer {operator_token}",
        "Content-Type": "application/json"
    }


class TestSimulationHistoryList:
    """Tests for GET /api/operator/simulations endpoint"""

    def test_list_returns_paginated_response(self, auth_headers):
        """Verify list endpoint returns proper pagination structure"""
        response = requests.get(
            f"{BASE_URL}/api/operator/simulations?page=1&limit=20",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        # Verify pagination structure
        assert "items" in data
        assert "total_count" in data
        assert "page" in data
        assert "limit" in data
        assert data["page"] == 1
        assert data["limit"] == 20
        assert isinstance(data["items"], list)
        assert isinstance(data["total_count"], int)

    def test_list_items_contain_required_fields(self, auth_headers):
        """Verify list items have all required fields"""
        response = requests.get(
            f"{BASE_URL}/api/operator/simulations?page=1&limit=20",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        if len(data["items"]) > 0:
            item = data["items"][0]
            required_fields = [
                "id", "simulation_run_id", "run_type",
                "total_devices_affected", "anomalies_triggered",
                "db_write_volume", "executed_by_name", "created_at"
            ]
            for field in required_fields:
                assert field in item, f"Missing field: {field}"

    def test_filter_by_run_type_single(self, auth_headers):
        """Verify run_type=single filter works"""
        response = requests.get(
            f"{BASE_URL}/api/operator/simulations?page=1&limit=20&run_type=single",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        for item in data["items"]:
            assert item["run_type"] == "single"

    def test_filter_by_run_type_fleet(self, auth_headers):
        """Verify run_type=fleet filter works"""
        response = requests.get(
            f"{BASE_URL}/api/operator/simulations?page=1&limit=20&run_type=fleet",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        for item in data["items"]:
            assert item["run_type"] == "fleet"

    def test_sorted_by_created_at_desc(self, auth_headers):
        """Verify results are sorted by created_at DESC"""
        response = requests.get(
            f"{BASE_URL}/api/operator/simulations?page=1&limit=20",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        if len(data["items"]) > 1:
            dates = [item["created_at"] for item in data["items"]]
            assert dates == sorted(dates, reverse=True), "Results not sorted by created_at DESC"


class TestSimulationHistoryDetail:
    """Tests for GET /api/operator/simulations/{simulation_run_id} endpoint"""

    def test_detail_returns_full_data(self, auth_headers):
        """Verify detail endpoint returns config_json and summary_json"""
        # First get list to get a valid simulation_run_id
        list_response = requests.get(
            f"{BASE_URL}/api/operator/simulations?page=1&limit=1",
            headers=auth_headers
        )
        assert list_response.status_code == 200
        items = list_response.json()["items"]
        
        if len(items) == 0:
            pytest.skip("No simulation runs available to test detail endpoint")
        
        run_id = items[0]["simulation_run_id"]
        
        # Get detail
        detail_response = requests.get(
            f"{BASE_URL}/api/operator/simulations/{run_id}",
            headers=auth_headers
        )
        assert detail_response.status_code == 200
        data = detail_response.json()
        
        # Verify required fields including full JSON data
        required_fields = [
            "id", "simulation_run_id", "run_type",
            "config_json", "summary_json",
            "total_devices_affected", "anomalies_triggered",
            "db_write_volume", "executed_by_name", "created_at"
        ]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"
        
        # Verify config_json and summary_json are dicts
        assert isinstance(data["config_json"], dict)
        assert isinstance(data["summary_json"], dict)

    def test_detail_404_for_nonexistent_run(self, auth_headers):
        """Verify 404 is returned for non-existent simulation_run_id"""
        response = requests.get(
            f"{BASE_URL}/api/operator/simulations/non-existent-run-id-12345",
            headers=auth_headers
        )
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
        assert "not found" in data["detail"].lower()


class TestSimulationHistoryImmutability:
    """Tests to verify simulation history is immutable (read-only)"""

    def test_no_put_endpoint(self, auth_headers):
        """Verify PUT method is not allowed (immutability)"""
        response = requests.put(
            f"{BASE_URL}/api/operator/simulations/any-run-id",
            headers=auth_headers,
            json={}
        )
        assert response.status_code == 405, "PUT should return 405 Method Not Allowed"

    def test_no_delete_endpoint(self, auth_headers):
        """Verify DELETE method is not allowed (immutability)"""
        response = requests.delete(
            f"{BASE_URL}/api/operator/simulations/any-run-id",
            headers=auth_headers
        )
        assert response.status_code == 405, "DELETE should return 405 Method Not Allowed"

    def test_no_patch_endpoint(self, auth_headers):
        """Verify PATCH method is not allowed (immutability)"""
        response = requests.patch(
            f"{BASE_URL}/api/operator/simulations/any-run-id",
            headers=auth_headers,
            json={}
        )
        assert response.status_code == 405, "PATCH should return 405 Method Not Allowed"


class TestSimulationPersistence:
    """Tests to verify simulations are persisted atomically"""

    def test_single_simulation_persisted_with_history(self, auth_headers):
        """Verify single device simulation persists history record"""
        # Get list before
        list_before = requests.get(
            f"{BASE_URL}/api/operator/simulations?page=1&limit=100&run_type=single",
            headers=auth_headers
        ).json()
        count_before = list_before["total_count"]
        
        # Run a single device simulation
        sim_response = requests.post(
            f"{BASE_URL}/api/operator/simulate/heartbeat-seed",
            headers=auth_headers,
            json={
                "device_identifier": "DEV-001",
                "duration_minutes": 5,
                "interval_seconds": 60,
                "metric_patterns": [{
                    "metric": "battery_level",
                    "start_value": 90,
                    "normal_rate_per_minute": -0.1,
                    "anomaly": None
                }],
                "gap_patterns": [],
                "noise_percent": 1.0,
                "trigger_evaluation": False
            }
        )
        assert sim_response.status_code == 200, f"Simulation failed: {sim_response.text}"
        sim_data = sim_response.json()
        new_run_id = sim_data["simulation_run_id"]
        
        # Verify it appears in history
        list_after = requests.get(
            f"{BASE_URL}/api/operator/simulations?page=1&limit=100&run_type=single",
            headers=auth_headers
        ).json()
        count_after = list_after["total_count"]
        
        assert count_after == count_before + 1, "Single simulation not persisted to history"
        
        # Verify we can get the detail
        detail_response = requests.get(
            f"{BASE_URL}/api/operator/simulations/{new_run_id}",
            headers=auth_headers
        )
        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert detail["run_type"] == "single"
        assert detail["config_json"] is not None
        assert detail["summary_json"] is not None

    def test_fleet_simulation_persisted_with_history(self, auth_headers):
        """Verify fleet simulation persists history record with FULL raw summary"""
        # Get list before
        list_before = requests.get(
            f"{BASE_URL}/api/operator/simulations?page=1&limit=100&run_type=fleet",
            headers=auth_headers
        ).json()
        count_before = list_before["total_count"]
        
        # Run a fleet simulation
        sim_response = requests.post(
            f"{BASE_URL}/api/operator/simulate/fleet",
            headers=auth_headers,
            json={
                "device_patterns": [
                    {
                        "device_identifier": "DEV-001",
                        "metric_patterns": [{
                            "metric": "battery_level",
                            "start_value": 85,
                            "normal_rate_per_minute": -0.1,
                            "anomaly": None
                        }],
                        "gap_patterns": []
                    }
                ],
                "duration_minutes": 5,
                "interval_seconds": 60,
                "noise_percent": 1.0,
                "trigger_evaluation": False
            }
        )
        assert sim_response.status_code == 200, f"Fleet simulation failed: {sim_response.text}"
        sim_data = sim_response.json()
        new_run_id = sim_data["simulation_run_id"]
        
        # Verify it appears in history
        list_after = requests.get(
            f"{BASE_URL}/api/operator/simulations?page=1&limit=100&run_type=fleet",
            headers=auth_headers
        ).json()
        count_after = list_after["total_count"]
        
        assert count_after == count_before + 1, "Fleet simulation not persisted to history"
        
        # Verify we can get the detail with FULL raw summary
        detail_response = requests.get(
            f"{BASE_URL}/api/operator/simulations/{new_run_id}",
            headers=auth_headers
        )
        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert detail["run_type"] == "fleet"
        assert detail["config_json"] is not None
        assert detail["summary_json"] is not None
        
        # Verify summary_json contains required fleet fields
        summary = detail["summary_json"]
        assert "per_device_results" in summary
        assert "anomaly_distribution" in summary
        assert "is_simulated" in summary


class TestSimulationHistoryRBAC:
    """Tests for role-based access control on simulation history"""

    def test_guardian_cannot_access_simulations(self):
        """Verify guardian role cannot access simulation history"""
        # Login as guardian
        login_response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "nischint4parents@gmail.com", "password": "secret123"}
        )
        assert login_response.status_code == 200
        guardian_token = login_response.json()["access_token"]
        
        # Try to access simulations list
        response = requests.get(
            f"{BASE_URL}/api/operator/simulations?page=1&limit=20",
            headers={"Authorization": f"Bearer {guardian_token}"}
        )
        assert response.status_code == 403, "Guardian should get 403 Forbidden"
