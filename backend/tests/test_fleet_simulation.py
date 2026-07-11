# Fleet Simulation Endpoint Tests
# Tests POST /api/operator/simulate/fleet - multi-device simulation endpoint
# Also tests simulation isolation (is_simulated, simulation_run_id columns)
# Previous iteration 21 tested single-device heartbeat-seed - this tests fleet-wide simulation

import os
import pytest
import requests
import time

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

# Test credentials
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"
GUARDIAN_EMAIL = "nischint4parents@gmail.com"
GUARDIAN_PASSWORD = "secret123"

# Available devices
DEVICES = ["DEV-001", "DEV-002", "WATCH-001", "WBAND-LC-001", "WBAND-E2E-001", "Mob-01"]


class AuthTokens:
    """Holds authentication tokens"""
    operator_token = None
    guardian_token = None


@pytest.fixture(scope="module")
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


@pytest.fixture(scope="module")
def operator_token(api_client):
    """Get operator authentication token"""
    if AuthTokens.operator_token:
        return AuthTokens.operator_token
    
    response = api_client.post(f"{BASE_URL}/api/auth/login", json={
        "email": OPERATOR_EMAIL,
        "password": OPERATOR_PASSWORD
    })
    assert response.status_code == 200, f"Operator login failed: {response.text}"
    AuthTokens.operator_token = response.json().get("access_token")
    return AuthTokens.operator_token


@pytest.fixture(scope="module")
def guardian_token(api_client):
    """Get guardian authentication token"""
    if AuthTokens.guardian_token:
        return AuthTokens.guardian_token
    
    response = api_client.post(f"{BASE_URL}/api/auth/login", json={
        "email": GUARDIAN_EMAIL,
        "password": GUARDIAN_PASSWORD
    })
    assert response.status_code == 200, f"Guardian login failed: {response.text}"
    AuthTokens.guardian_token = response.json().get("access_token")
    return AuthTokens.guardian_token


@pytest.fixture
def operator_headers(operator_token):
    """Headers with operator auth"""
    return {"Authorization": f"Bearer {operator_token}", "Content-Type": "application/json"}


@pytest.fixture
def guardian_headers(guardian_token):
    """Headers with guardian auth"""
    return {"Authorization": f"Bearer {guardian_token}", "Content-Type": "application/json"}


# ────────────────────────────────────────────────────────────────────────────────
# Fleet Simulation Basic Tests
# ────────────────────────────────────────────────────────────────────────────────

class TestFleetSimulationBasic:
    """Basic functionality tests for fleet simulation endpoint"""

    def test_fleet_simulation_creates_telemetry_for_multiple_devices(self, api_client, operator_headers):
        """Test fleet simulation creates telemetry for multiple devices with unique simulation_run_id"""
        payload = {
            "device_patterns": [
                {
                    "device_identifier": "DEV-001",
                    "metric_patterns": [
                        {"metric": "battery_level", "start_value": 90.0, "normal_rate_per_minute": -0.1}
                    ],
                    "gap_patterns": []
                },
                {
                    "device_identifier": "DEV-002",
                    "metric_patterns": [
                        {"metric": "battery_level", "start_value": 85.0, "normal_rate_per_minute": -0.15}
                    ],
                    "gap_patterns": []
                }
            ],
            "duration_minutes": 10,
            "interval_seconds": 60,
            "trigger_evaluation": False,
            "random_seed": 12345
        }
        
        response = api_client.post(f"{BASE_URL}/api/operator/simulate/fleet", 
                                   json=payload, headers=operator_headers)
        
        assert response.status_code == 200, f"Fleet simulation failed: {response.text}"
        data = response.json()
        
        # Verify simulation_run_id format
        assert "simulation_run_id" in data
        assert data["simulation_run_id"].startswith("fleet-")
        
        # Verify total_devices_affected
        assert data["total_devices_affected"] == 2
        
        # Verify records created
        assert data["total_records_created"] > 0
        
        # Verify per_device_results
        assert len(data["per_device_results"]) == 2
        for result in data["per_device_results"]:
            assert "device_identifier" in result
            assert "records_created" in result
            assert result["records_created"] > 0

    def test_fleet_simulation_with_per_device_metric_patterns(self, api_client, operator_headers):
        """Test per-device metric_patterns work correctly"""
        payload = {
            "device_patterns": [
                {
                    "device_identifier": "WATCH-001",
                    "metric_patterns": [
                        {"metric": "battery_level", "start_value": 100.0, "normal_rate_per_minute": -0.1},
                        {"metric": "signal_strength", "start_value": -40.0, "normal_rate_per_minute": -0.01}
                    ],
                    "gap_patterns": []
                },
                {
                    "device_identifier": "Mob-01",
                    "metric_patterns": [
                        {"metric": "battery_level", "start_value": 75.0, "normal_rate_per_minute": -0.2}
                    ],
                    "gap_patterns": []
                }
            ],
            "duration_minutes": 5,
            "interval_seconds": 30,
            "trigger_evaluation": False
        }
        
        response = api_client.post(f"{BASE_URL}/api/operator/simulate/fleet", 
                                   json=payload, headers=operator_headers)
        
        assert response.status_code == 200, f"Fleet simulation failed: {response.text}"
        data = response.json()
        
        # Find results for each device
        watch_result = next((r for r in data["per_device_results"] 
                            if r["device_identifier"] == "WATCH-001"), None)
        mob_result = next((r for r in data["per_device_results"] 
                          if r["device_identifier"] == "Mob-01"), None)
        
        assert watch_result is not None
        assert mob_result is not None
        
        # WATCH-001 should have both metrics seeded
        assert "battery_level" in watch_result["metrics_seeded"]
        assert "signal_strength" in watch_result["metrics_seeded"]
        
        # Mob-01 should only have battery_level
        assert "battery_level" in mob_result["metrics_seeded"]
        assert len(mob_result["metrics_seeded"]) == 1

    def test_fleet_simulation_with_gap_patterns(self, api_client, operator_headers):
        """Test per-device gap_patterns cause records to be skipped"""
        payload = {
            "device_patterns": [
                {
                    "device_identifier": "DEV-001",
                    "metric_patterns": [
                        {"metric": "battery_level", "start_value": 90.0, "normal_rate_per_minute": -0.1}
                    ],
                    "gap_patterns": [
                        {"start_at_minute": 3, "duration_minutes": 2}  # 2-min gap starting at minute 3
                    ]
                },
                {
                    "device_identifier": "DEV-002",
                    "metric_patterns": [
                        {"metric": "battery_level", "start_value": 85.0, "normal_rate_per_minute": -0.1}
                    ],
                    "gap_patterns": []  # No gaps for this device
                }
            ],
            "duration_minutes": 10,
            "interval_seconds": 60,
            "trigger_evaluation": False
        }
        
        response = api_client.post(f"{BASE_URL}/api/operator/simulate/fleet", 
                                   json=payload, headers=operator_headers)
        
        assert response.status_code == 200, f"Fleet simulation failed: {response.text}"
        data = response.json()
        
        # Verify total_records_skipped > 0 (due to DEV-001's gap)
        assert data["total_records_skipped"] > 0
        
        # Find DEV-001 result
        dev001_result = next((r for r in data["per_device_results"] 
                             if r["device_identifier"] == "DEV-001"), None)
        
        assert dev001_result is not None
        assert dev001_result["records_skipped_by_gaps"] > 0


# ────────────────────────────────────────────────────────────────────────────────
# Response Structure Tests
# ────────────────────────────────────────────────────────────────────────────────

class TestFleetSimulationResponse:
    """Tests for response structure and fields"""

    def test_response_includes_total_devices_affected(self, api_client, operator_headers):
        """Verify response includes total_devices_affected"""
        payload = {
            "device_patterns": [
                {"device_identifier": "DEV-001", "metric_patterns": [
                    {"metric": "battery_level", "start_value": 90.0, "normal_rate_per_minute": -0.1}
                ], "gap_patterns": []},
                {"device_identifier": "DEV-002", "metric_patterns": [
                    {"metric": "battery_level", "start_value": 85.0, "normal_rate_per_minute": -0.1}
                ], "gap_patterns": []},
                {"device_identifier": "WATCH-001", "metric_patterns": [
                    {"metric": "battery_level", "start_value": 80.0, "normal_rate_per_minute": -0.1}
                ], "gap_patterns": []}
            ],
            "duration_minutes": 5,
            "trigger_evaluation": False
        }
        
        response = api_client.post(f"{BASE_URL}/api/operator/simulate/fleet", 
                                   json=payload, headers=operator_headers)
        
        assert response.status_code == 200
        data = response.json()
        assert data["total_devices_affected"] == 3

    def test_response_includes_db_write_volume(self, api_client, operator_headers):
        """Verify response includes db_write_volume (telemetry + anomaly rows)"""
        payload = {
            "device_patterns": [
                {"device_identifier": "DEV-001", "metric_patterns": [
                    {"metric": "battery_level", "start_value": 90.0, "normal_rate_per_minute": -0.1}
                ], "gap_patterns": []}
            ],
            "duration_minutes": 5,
            "interval_seconds": 60,
            "trigger_evaluation": False
        }
        
        response = api_client.post(f"{BASE_URL}/api/operator/simulate/fleet", 
                                   json=payload, headers=operator_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        assert "db_write_volume" in data
        # Without trigger_evaluation, db_write_volume should equal total_records_created
        assert data["db_write_volume"] == data["total_records_created"]

    def test_response_includes_scheduler_execution_ms_when_trigger_evaluation_true(self, api_client, operator_headers):
        """Verify response includes scheduler_execution_ms when trigger_evaluation=true"""
        payload = {
            "device_patterns": [
                {"device_identifier": "DEV-001", "metric_patterns": [
                    {"metric": "battery_level", "start_value": 90.0, "normal_rate_per_minute": -0.1}
                ], "gap_patterns": []}
            ],
            "duration_minutes": 5,
            "interval_seconds": 60,
            "trigger_evaluation": True
        }
        
        response = api_client.post(f"{BASE_URL}/api/operator/simulate/fleet", 
                                   json=payload, headers=operator_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        assert "scheduler_execution_ms" in data
        assert data["scheduler_execution_ms"] is not None
        assert data["scheduler_execution_ms"] >= 0

    def test_response_includes_anomaly_distribution_histogram(self, api_client, operator_headers):
        """Verify response includes anomaly_distribution histogram with 4 buckets"""
        payload = {
            "device_patterns": [
                {"device_identifier": "DEV-001", "metric_patterns": [
                    {"metric": "battery_level", "start_value": 90.0, "normal_rate_per_minute": -0.1}
                ], "gap_patterns": []}
            ],
            "duration_minutes": 5,
            "trigger_evaluation": False
        }
        
        response = api_client.post(f"{BASE_URL}/api/operator/simulate/fleet", 
                                   json=payload, headers=operator_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        assert "anomaly_distribution" in data
        histogram = data["anomaly_distribution"]
        assert len(histogram) == 4  # 0-25, 25-50, 50-75, 75-100
        
        # Verify histogram structure
        labels = [bucket["range_label"] for bucket in histogram]
        assert "0-25" in labels
        assert "25-50" in labels
        assert "50-75" in labels
        assert "75-100" in labels
        
        for bucket in histogram:
            assert "count" in bucket

    def test_response_includes_per_device_results_array(self, api_client, operator_headers):
        """Verify response includes per_device_results array with correct structure"""
        payload = {
            "device_patterns": [
                {"device_identifier": "DEV-001", "metric_patterns": [
                    {"metric": "battery_level", "start_value": 90.0, "normal_rate_per_minute": -0.1}
                ], "gap_patterns": []},
                {"device_identifier": "DEV-002", "metric_patterns": [
                    {"metric": "battery_level", "start_value": 85.0, "normal_rate_per_minute": -0.1}
                ], "gap_patterns": []}
            ],
            "duration_minutes": 5,
            "trigger_evaluation": False
        }
        
        response = api_client.post(f"{BASE_URL}/api/operator/simulate/fleet", 
                                   json=payload, headers=operator_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        assert "per_device_results" in data
        assert len(data["per_device_results"]) == 2
        
        for result in data["per_device_results"]:
            assert "device_identifier" in result
            assert "records_created" in result
            assert "records_skipped_by_gaps" in result
            assert "metrics_seeded" in result

    def test_response_all_required_fields_present(self, api_client, operator_headers):
        """Verify all required FleetSimulationResponse fields are present"""
        payload = {
            "device_patterns": [
                {"device_identifier": "DEV-001", "metric_patterns": [
                    {"metric": "battery_level", "start_value": 90.0, "normal_rate_per_minute": -0.1}
                ], "gap_patterns": []}
            ],
            "duration_minutes": 5,
            "trigger_evaluation": True
        }
        
        response = api_client.post(f"{BASE_URL}/api/operator/simulate/fleet", 
                                   json=payload, headers=operator_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        required_fields = [
            "simulation_run_id", "total_devices_affected", "total_records_created",
            "total_records_skipped", "duration_minutes", "time_range_start",
            "time_range_end", "db_write_volume", "scheduler_execution_ms",
            "anomalies_triggered", "baselines_updated", "anomaly_distribution",
            "per_device_results", "anomaly_details"
        ]
        
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"


# ────────────────────────────────────────────────────────────────────────────────
# RBAC Tests
# ────────────────────────────────────────────────────────────────────────────────

class TestFleetSimulationRBAC:
    """RBAC tests for fleet simulation endpoint"""

    def test_guardian_gets_403(self, api_client, guardian_headers):
        """Test that guardian role gets 403 Forbidden"""
        payload = {
            "device_patterns": [
                {"device_identifier": "DEV-001", "metric_patterns": [
                    {"metric": "battery_level", "start_value": 90.0, "normal_rate_per_minute": -0.1}
                ], "gap_patterns": []}
            ],
            "duration_minutes": 5,
            "trigger_evaluation": False
        }
        
        response = api_client.post(f"{BASE_URL}/api/operator/simulate/fleet", 
                                   json=payload, headers=guardian_headers)
        
        assert response.status_code == 403

    def test_unauthenticated_gets_401(self, api_client):
        """Test that unauthenticated requests get 401"""
        payload = {
            "device_patterns": [
                {"device_identifier": "DEV-001", "metric_patterns": [
                    {"metric": "battery_level", "start_value": 90.0, "normal_rate_per_minute": -0.1}
                ], "gap_patterns": []}
            ],
            "duration_minutes": 5,
            "trigger_evaluation": False
        }
        
        response = api_client.post(f"{BASE_URL}/api/operator/simulate/fleet", json=payload)
        
        assert response.status_code == 401


# ────────────────────────────────────────────────────────────────────────────────
# Error Handling Tests
# ────────────────────────────────────────────────────────────────────────────────

class TestFleetSimulationErrorHandling:
    """Error handling tests for fleet simulation endpoint"""

    def test_404_for_nonexistent_device(self, api_client, operator_headers):
        """Test 404 for nonexistent device in device_patterns"""
        payload = {
            "device_patterns": [
                {"device_identifier": "NONEXISTENT-DEVICE-XYZ", "metric_patterns": [
                    {"metric": "battery_level", "start_value": 90.0, "normal_rate_per_minute": -0.1}
                ], "gap_patterns": []}
            ],
            "duration_minutes": 5,
            "trigger_evaluation": False
        }
        
        response = api_client.post(f"{BASE_URL}/api/operator/simulate/fleet", 
                                   json=payload, headers=operator_headers)
        
        assert response.status_code == 404, f"Expected 404, got {response.status_code}: {response.text}"
        assert "not found" in response.json().get("detail", "").lower()

    def test_422_for_empty_device_patterns_list(self, api_client, operator_headers):
        """Test 422 for empty device_patterns list"""
        payload = {
            "device_patterns": [],
            "duration_minutes": 5,
            "trigger_evaluation": False
        }
        
        response = api_client.post(f"{BASE_URL}/api/operator/simulate/fleet", 
                                   json=payload, headers=operator_headers)
        
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"

    def test_422_for_invalid_duration_minutes(self, api_client, operator_headers):
        """Test 422 for invalid duration_minutes"""
        payload = {
            "device_patterns": [
                {"device_identifier": "DEV-001", "metric_patterns": [
                    {"metric": "battery_level", "start_value": 90.0, "normal_rate_per_minute": -0.1}
                ], "gap_patterns": []}
            ],
            "duration_minutes": 0,  # Invalid - must be >= 1
            "trigger_evaluation": False
        }
        
        response = api_client.post(f"{BASE_URL}/api/operator/simulate/fleet", 
                                   json=payload, headers=operator_headers)
        
        assert response.status_code == 422

    def test_422_for_anomaly_start_at_minute_gte_duration(self, api_client, operator_headers):
        """Test 422 when anomaly.start_at_minute >= duration_minutes"""
        payload = {
            "device_patterns": [
                {"device_identifier": "DEV-001", "metric_patterns": [
                    {"metric": "battery_level", "start_value": 90.0, "normal_rate_per_minute": -0.1,
                     "anomaly": {"start_at_minute": 10, "rate_per_minute": -2.0}}  # start >= duration
                ], "gap_patterns": []}
            ],
            "duration_minutes": 5,  # anomaly starts at minute 10, but duration is only 5
            "trigger_evaluation": False
        }
        
        response = api_client.post(f"{BASE_URL}/api/operator/simulate/fleet", 
                                   json=payload, headers=operator_headers)
        
        assert response.status_code == 422
        assert "anomaly" in response.json().get("detail", "").lower() or "start_at_minute" in response.json().get("detail", "")


# ────────────────────────────────────────────────────────────────────────────────
# Deterministic Mode Tests
# ────────────────────────────────────────────────────────────────────────────────

class TestFleetSimulationDeterministic:
    """Deterministic mode tests for fleet simulation"""

    def test_deterministic_mode_via_random_seed(self, api_client, operator_headers):
        """Test deterministic mode produces same results with same random_seed"""
        payload = {
            "device_patterns": [
                {"device_identifier": "DEV-001", "metric_patterns": [
                    {"metric": "battery_level", "start_value": 90.0, "normal_rate_per_minute": -0.1}
                ], "gap_patterns": []},
                {"device_identifier": "DEV-002", "metric_patterns": [
                    {"metric": "battery_level", "start_value": 85.0, "normal_rate_per_minute": -0.15}
                ], "gap_patterns": []}
            ],
            "duration_minutes": 5,
            "interval_seconds": 60,
            "random_seed": 99999,
            "trigger_evaluation": False
        }
        
        # First call
        response1 = api_client.post(f"{BASE_URL}/api/operator/simulate/fleet", 
                                    json=payload, headers=operator_headers)
        assert response1.status_code == 200
        data1 = response1.json()
        
        # Second call with same seed
        response2 = api_client.post(f"{BASE_URL}/api/operator/simulate/fleet", 
                                    json=payload, headers=operator_headers)
        assert response2.status_code == 200
        data2 = response2.json()
        
        # Record counts should be identical
        assert data1["total_records_created"] == data2["total_records_created"]
        assert data1["total_records_skipped"] == data2["total_records_skipped"]
        
        # Per-device results should match
        for i, result in enumerate(data1["per_device_results"]):
            assert result["records_created"] == data2["per_device_results"][i]["records_created"]


# ────────────────────────────────────────────────────────────────────────────────
# Simulation Isolation Tests
# ────────────────────────────────────────────────────────────────────────────────

class TestSimulationIsolation:
    """Tests for simulation isolation (is_simulated, simulation_run_id)"""

    def test_heartbeat_seed_returns_simulation_run_id(self, api_client, operator_headers):
        """Test POST /api/operator/simulate/heartbeat-seed returns simulation_run_id in response"""
        payload = {
            "device_identifier": "DEV-001",
            "duration_minutes": 5,
            "interval_seconds": 60,
            "metric_patterns": [
                {"metric": "battery_level", "start_value": 90.0, "normal_rate_per_minute": -0.1}
            ],
            "gap_patterns": [],
            "trigger_evaluation": False
        }
        
        response = api_client.post(f"{BASE_URL}/api/operator/simulate/heartbeat-seed", 
                                   json=payload, headers=operator_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        assert "simulation_run_id" in data
        assert data["simulation_run_id"].startswith("seed-")

    def test_device_anomalies_excludes_simulated_by_default(self, api_client, operator_headers):
        """Test GET /api/operator/device-anomalies excludes simulated anomalies by default"""
        # First, create some simulated anomalies using fleet simulation
        sim_payload = {
            "device_patterns": [
                {"device_identifier": "DEV-001", "metric_patterns": [
                    {"metric": "battery_level", "start_value": 100.0, "normal_rate_per_minute": -0.1,
                     "anomaly": {"start_at_minute": 2, "rate_per_minute": -3.0}}  # Aggressive drain to trigger anomaly
                ], "gap_patterns": []}
            ],
            "duration_minutes": 60,  # Longer duration for baseline calculation
            "interval_seconds": 60,
            "trigger_evaluation": True
        }
        
        sim_response = api_client.post(f"{BASE_URL}/api/operator/simulate/fleet", 
                                       json=sim_payload, headers=operator_headers)
        assert sim_response.status_code == 200
        sim_data = sim_response.json()
        sim_run_id = sim_data["simulation_run_id"]
        
        # Now query device-anomalies without include_simulated
        response = api_client.get(f"{BASE_URL}/api/operator/device-anomalies?hours=24", 
                                  headers=operator_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        # Check that no anomaly with this simulation_run_id is present
        for anomaly in data["anomalies"]:
            assert anomaly.get("simulation_run_id") != sim_run_id, \
                f"Simulated anomaly found when it should be excluded: {anomaly}"

    def test_device_anomalies_includes_simulated_when_requested(self, api_client, operator_headers):
        """Test GET /api/operator/device-anomalies?include_simulated=true includes simulated anomalies"""
        # Query device-anomalies with include_simulated=true
        response = api_client.get(f"{BASE_URL}/api/operator/device-anomalies?hours=24&include_simulated=true", 
                                  headers=operator_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify response structure
        assert "anomalies" in data
        assert "baselines" in data
        
        # Check anomaly structure includes is_simulated field
        for anomaly in data["anomalies"]:
            assert "is_simulated" in anomaly
            assert "simulation_run_id" in anomaly


# ────────────────────────────────────────────────────────────────────────────────
# Anomaly Detection Integration Tests
# ────────────────────────────────────────────────────────────────────────────────

class TestFleetSimulationAnomalyDetection:
    """Tests for anomaly detection integration with fleet simulation"""

    def test_fleet_simulation_anomalies_marked_with_simulation_run_id(self, api_client, operator_headers):
        """Test that fleet simulation anomalies are marked with is_simulated=true and simulation_run_id"""
        # Use aggressive drain to trigger anomaly detection
        payload = {
            "device_patterns": [
                {"device_identifier": "DEV-002", "metric_patterns": [
                    {"metric": "battery_level", "start_value": 100.0, "normal_rate_per_minute": -0.1,
                     "anomaly": {"start_at_minute": 5, "rate_per_minute": -5.0}}  # Very aggressive
                ], "gap_patterns": []}
            ],
            "duration_minutes": 60,
            "interval_seconds": 60,
            "trigger_evaluation": True
        }
        
        response = api_client.post(f"{BASE_URL}/api/operator/simulate/fleet", 
                                   json=payload, headers=operator_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        simulation_run_id = data["simulation_run_id"]
        
        # Query anomalies with include_simulated=true to see our anomalies
        anomaly_response = api_client.get(
            f"{BASE_URL}/api/operator/device-anomalies?hours=24&include_simulated=true", 
            headers=operator_headers
        )
        
        assert anomaly_response.status_code == 200
        anomaly_data = anomaly_response.json()
        
        # Find anomalies with our simulation_run_id
        sim_anomalies = [a for a in anomaly_data["anomalies"] 
                        if a.get("simulation_run_id") == simulation_run_id]
        
        # All anomalies from this run should be marked as simulated
        for anomaly in sim_anomalies:
            assert anomaly["is_simulated"] == True
            assert anomaly["simulation_run_id"] == simulation_run_id

    def test_anomaly_details_returned_in_response(self, api_client, operator_headers):
        """Test that anomaly_details is returned in response when anomalies are triggered"""
        # Use very aggressive drain pattern
        payload = {
            "device_patterns": [
                {"device_identifier": "WATCH-001", "metric_patterns": [
                    {"metric": "battery_level", "start_value": 100.0, "normal_rate_per_minute": -0.05,
                     "anomaly": {"start_at_minute": 10, "rate_per_minute": -4.0}}
                ], "gap_patterns": []}
            ],
            "duration_minutes": 60,
            "interval_seconds": 60,
            "trigger_evaluation": True
        }
        
        response = api_client.post(f"{BASE_URL}/api/operator/simulate/fleet", 
                                   json=payload, headers=operator_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        # anomaly_details should be a list
        assert "anomaly_details" in data
        assert isinstance(data["anomaly_details"], list)
        
        # If anomalies were triggered, details should have device_id and score
        if data["anomalies_triggered"] > 0:
            for detail in data["anomaly_details"]:
                assert "device_id" in detail
                assert "score" in detail


# ────────────────────────────────────────────────────────────────────────────────
# Edge Cases
# ────────────────────────────────────────────────────────────────────────────────

class TestFleetSimulationEdgeCases:
    """Edge case tests for fleet simulation"""

    def test_single_device_fleet_simulation(self, api_client, operator_headers):
        """Test fleet simulation with single device works"""
        payload = {
            "device_patterns": [
                {"device_identifier": "DEV-001", "metric_patterns": [
                    {"metric": "battery_level", "start_value": 90.0, "normal_rate_per_minute": -0.1}
                ], "gap_patterns": []}
            ],
            "duration_minutes": 5,
            "trigger_evaluation": False
        }
        
        response = api_client.post(f"{BASE_URL}/api/operator/simulate/fleet", 
                                   json=payload, headers=operator_headers)
        
        assert response.status_code == 200
        data = response.json()
        assert data["total_devices_affected"] == 1

    def test_fleet_simulation_with_many_devices(self, api_client, operator_headers):
        """Test fleet simulation with multiple devices"""
        payload = {
            "device_patterns": [
                {"device_identifier": dev, "metric_patterns": [
                    {"metric": "battery_level", "start_value": 90.0 - i * 5, "normal_rate_per_minute": -0.1}
                ], "gap_patterns": []}
                for i, dev in enumerate(DEVICES[:5])  # Use first 5 devices
            ],
            "duration_minutes": 5,
            "interval_seconds": 60,
            "trigger_evaluation": False
        }
        
        response = api_client.post(f"{BASE_URL}/api/operator/simulate/fleet", 
                                   json=payload, headers=operator_headers)
        
        assert response.status_code == 200
        data = response.json()
        assert data["total_devices_affected"] == 5
        assert len(data["per_device_results"]) == 5

    def test_fleet_simulation_without_trigger_evaluation(self, api_client, operator_headers):
        """Test fleet simulation with trigger_evaluation=false skips scheduler"""
        payload = {
            "device_patterns": [
                {"device_identifier": "DEV-001", "metric_patterns": [
                    {"metric": "battery_level", "start_value": 90.0, "normal_rate_per_minute": -0.1}
                ], "gap_patterns": []}
            ],
            "duration_minutes": 5,
            "trigger_evaluation": False
        }
        
        response = api_client.post(f"{BASE_URL}/api/operator/simulate/fleet", 
                                   json=payload, headers=operator_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        # scheduler_execution_ms should be None when trigger_evaluation=false
        assert data["scheduler_execution_ms"] is None
        # anomalies_triggered should be 0
        assert data["anomalies_triggered"] == 0
        # baselines_updated should be None
        assert data["baselines_updated"] is None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
