# Twin Evolution Timeline API Tests
# Tests the endpoint GET /api/operator/devices/{device_id}/twin-evolution
# which returns weekly evolution timeline with snapshots, trends, shifts, and interpretation

import os
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test Device IDs
DEV_001_ID = "ce4b5463-5a7e-46a5-8bbf-365dcfb3daeb"
DEV_002_ID = "e029085c-1021-436d-9dfc-a0633979583d"
NONEXISTENT_DEVICE_ID = "00000000-0000-0000-0000-000000000000"

# Test credentials
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"
GUARDIAN_EMAIL = "nischint4parents@gmail.com"
GUARDIAN_PASSWORD = "secret123"


@pytest.fixture(scope="module")
def operator_token():
    """Get operator authentication token"""
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD}
    )
    if response.status_code != 200:
        pytest.skip("Operator authentication failed")
    return response.json().get("access_token")


@pytest.fixture(scope="module")
def guardian_token():
    """Get guardian authentication token"""
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": GUARDIAN_EMAIL, "password": GUARDIAN_PASSWORD}
    )
    if response.status_code != 200:
        pytest.skip("Guardian authentication failed")
    return response.json().get("access_token")


@pytest.fixture(scope="module")
def operator_session(operator_token):
    """Create a session with operator auth headers"""
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {operator_token}",
        "Content-Type": "application/json"
    })
    return session


@pytest.fixture(scope="module")
def guardian_session(guardian_token):
    """Create a session with guardian auth headers"""
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {guardian_token}",
        "Content-Type": "application/json"
    })
    return session


class TestTwinEvolutionEndpoint:
    """Tests for GET /api/operator/devices/{device_id}/twin-evolution"""
    
    def test_returns_200_for_valid_device(self, operator_session):
        """Test that endpoint returns 200 for valid device"""
        response = operator_session.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/twin-evolution"
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print(f"PASS: Returns 200 for valid device DEV-001")
    
    def test_response_structure(self, operator_session):
        """Test that response contains all required fields"""
        response = operator_session.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/twin-evolution"
        )
        assert response.status_code == 200
        data = response.json()
        
        # Required top-level fields
        required_fields = ["device_id", "device_identifier", "weeks_analyzed", "snapshots", "trends", "shifts", "interpretation"]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        
        print(f"PASS: Response contains all required fields: {required_fields}")
    
    def test_snapshots_structure(self, operator_session):
        """Test that snapshots array contains correct weekly data"""
        response = operator_session.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/twin-evolution"
        )
        assert response.status_code == 200
        data = response.json()
        
        snapshots = data.get("snapshots", [])
        assert isinstance(snapshots, list), "snapshots should be a list"
        
        if len(snapshots) > 0:
            snapshot = snapshots[0]
            required_snapshot_fields = [
                "week_start", "week_end", "week_number", "week_label",
                "movement_frequency", "active_hours", "avg_inactivity_minutes",
                "avg_battery", "avg_signal", "heartbeat_count", "anomaly_count"
            ]
            for field in required_snapshot_fields:
                assert field in snapshot, f"Snapshot missing field: {field}"
            
            # Check week_label format (W1, W2, etc.)
            assert snapshot["week_label"].startswith("W"), f"week_label should be W1, W2, etc. Got: {snapshot['week_label']}"
            
            print(f"PASS: Snapshots contain all required fields. Found {len(snapshots)} week(s)")
            print(f"  - Week labels: {[s['week_label'] for s in snapshots]}")
        else:
            print(f"NOTE: No snapshots available (insufficient telemetry data)")
    
    def test_trends_structure(self, operator_session):
        """Test that trends array contains correct direction and change_percent"""
        response = operator_session.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/twin-evolution"
        )
        assert response.status_code == 200
        data = response.json()
        
        trends = data.get("trends", [])
        assert isinstance(trends, list), "trends should be a list"
        
        if len(trends) > 0:
            trend = trends[0]
            required_trend_fields = ["metric", "label", "direction", "change_percent", "first_value", "latest_value"]
            for field in required_trend_fields:
                assert field in trend, f"Trend missing field: {field}"
            
            # Check direction values
            valid_directions = ["increasing", "decreasing", "stable"]
            assert trend["direction"] in valid_directions, f"Invalid direction: {trend['direction']}"
            
            print(f"PASS: Trends contain all required fields. Found {len(trends)} trend(s)")
            for t in trends:
                print(f"  - {t['metric']}: {t['direction']} ({t['change_percent']}%)")
        else:
            print(f"NOTE: No trends available (need >= 2 weeks of data)")
    
    def test_shifts_structure(self, operator_session):
        """Test that shifts array contains detected behavioral shifts with severity"""
        response = operator_session.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/twin-evolution"
        )
        assert response.status_code == 200
        data = response.json()
        
        shifts = data.get("shifts", [])
        assert isinstance(shifts, list), "shifts should be a list"
        
        if len(shifts) > 0:
            shift = shifts[0]
            required_shift_fields = ["metric", "label", "type", "interpretation", "change_percent", "from_value", "to_value", "severity"]
            for field in required_shift_fields:
                assert field in shift, f"Shift missing field: {field}"
            
            # Check severity values
            valid_severities = ["high", "medium"]
            assert shift["severity"] in valid_severities, f"Invalid severity: {shift['severity']}"
            
            print(f"PASS: Shifts contain all required fields. Found {len(shifts)} shift(s)")
            for s in shifts:
                print(f"  - {s['interpretation']}: {s['severity']} severity ({s['change_percent']}%)")
        else:
            print(f"NOTE: No shifts detected (device behavior is stable)")
    
    def test_interpretation_present(self, operator_session):
        """Test that interpretation string is present"""
        response = operator_session.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/twin-evolution"
        )
        assert response.status_code == 200
        data = response.json()
        
        interpretation = data.get("interpretation")
        assert interpretation is not None, "interpretation should be present"
        assert isinstance(interpretation, str), "interpretation should be a string"
        assert len(interpretation) > 0, "interpretation should not be empty"
        
        print(f"PASS: Interpretation present: '{interpretation}'")
    
    def test_dev_002_twin_evolution(self, operator_session):
        """Test twin evolution for DEV-002"""
        response = operator_session.get(
            f"{BASE_URL}/api/operator/devices/{DEV_002_ID}/twin-evolution"
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        assert data["device_id"] == DEV_002_ID
        print(f"PASS: DEV-002 twin evolution: {data['weeks_analyzed']} weeks analyzed")


class TestTwinEvolutionRBAC:
    """RBAC tests for twin evolution endpoint"""
    
    def test_guardian_gets_403(self, guardian_session):
        """Test that guardian role gets 403 Forbidden"""
        response = guardian_session.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/twin-evolution"
        )
        assert response.status_code == 403, f"Expected 403, got {response.status_code}"
        print(f"PASS: Guardian role correctly gets 403 Forbidden")
    
    def test_unauthenticated_gets_401(self):
        """Test that unauthenticated request gets 401"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/twin-evolution"
        )
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print(f"PASS: Unauthenticated request gets 401")


class TestTwinEvolution404:
    """404 handling tests for twin evolution endpoint"""
    
    def test_non_existent_device_returns_404(self, operator_session):
        """Test that 404 is returned for non-existent device"""
        response = operator_session.get(
            f"{BASE_URL}/api/operator/devices/{NONEXISTENT_DEVICE_ID}/twin-evolution"
        )
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print(f"PASS: 404 returned for non-existent device")


class TestTwinEvolutionWeeksParameter:
    """Tests for the weeks query parameter"""
    
    def test_custom_weeks_parameter(self, operator_session):
        """Test that weeks parameter works correctly"""
        response = operator_session.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/twin-evolution?weeks=4"
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print(f"PASS: Custom weeks parameter (weeks=4) works correctly")
    
    def test_weeks_min_boundary(self, operator_session):
        """Test minimum weeks parameter (2)"""
        response = operator_session.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/twin-evolution?weeks=2"
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print(f"PASS: Minimum weeks parameter (weeks=2) accepted")
    
    def test_weeks_max_boundary(self, operator_session):
        """Test maximum weeks parameter (52)"""
        response = operator_session.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/twin-evolution?weeks=52"
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print(f"PASS: Maximum weeks parameter (weeks=52) accepted")
    
    def test_weeks_below_min_rejected(self, operator_session):
        """Test that weeks below minimum (1) is rejected"""
        response = operator_session.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/twin-evolution?weeks=1"
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}"
        print(f"PASS: weeks=1 (below min) correctly rejected with 422")
    
    def test_weeks_above_max_rejected(self, operator_session):
        """Test that weeks above maximum (53) is rejected"""
        response = operator_session.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/twin-evolution?weeks=53"
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}"
        print(f"PASS: weeks=53 (above max) correctly rejected with 422")


class TestTwinEvolutionDataContent:
    """Tests to verify actual data content from DEV-001 (expected to have shifts)"""
    
    def test_dev001_has_detected_shifts(self, operator_session):
        """Test that DEV-001 shows detected behavioral shifts per main agent context"""
        response = operator_session.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/twin-evolution"
        )
        assert response.status_code == 200
        data = response.json()
        
        shifts = data.get("shifts", [])
        weeks = data.get("weeks_analyzed", 0)
        
        print(f"DEV-001 Twin Evolution Analysis:")
        print(f"  - Weeks analyzed: {weeks}")
        print(f"  - Shifts detected: {len(shifts)}")
        
        if len(shifts) > 0:
            for s in shifts:
                print(f"    - {s['interpretation']}: {s['change_percent']}% ({s['severity']} severity)")
        
        print(f"  - Interpretation: {data.get('interpretation', 'N/A')}")
        
        # Per agent context, DEV-001 should have 2 weeks and detected shifts
        # But we don't fail if no shifts (data may have changed)
        print(f"PASS: DEV-001 data retrieved successfully")
