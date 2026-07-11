# Digital Twin Engine - Backend API Tests
# Tests GET /api/operator/devices/{device_id}/digital-twin
# Tests POST /api/operator/devices/{device_id}/digital-twin/rebuild
# Tests GET /api/operator/digital-twins/fleet

import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL').rstrip('/')
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"


@pytest.fixture(scope="module")
def operator_token():
    """Get operator authentication token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": OPERATOR_EMAIL,
        "password": OPERATOR_PASSWORD
    })
    assert response.status_code == 200, f"Login failed: {response.text}"
    data = response.json()
    return data["access_token"]


@pytest.fixture(scope="module")
def auth_headers(operator_token):
    """Auth headers for operator requests"""
    return {"Authorization": f"Bearer {operator_token}"}


@pytest.fixture(scope="module")
def device_id(auth_headers):
    """Get a valid device_id from device-health endpoint"""
    response = requests.get(f"{BASE_URL}/api/operator/device-health?window_hours=24", headers=auth_headers)
    assert response.status_code == 200
    devices = response.json()
    assert len(devices) > 0, "No devices found"
    # Return DEV-001's UUID if available
    for d in devices:
        if d.get("device_identifier") == "DEV-001":
            return d["device_id"]
    return devices[0]["device_id"]


class TestDigitalTwinEndpointAuthentication:
    """Test authentication requirements for Digital Twin endpoints"""
    
    def test_get_twin_requires_authentication(self, device_id):
        """GET /api/operator/devices/{device_id}/digital-twin returns 401 without auth"""
        response = requests.get(f"{BASE_URL}/api/operator/devices/{device_id}/digital-twin")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: GET digital-twin requires authentication")
    
    def test_rebuild_twin_requires_authentication(self, device_id):
        """POST /api/operator/devices/{device_id}/digital-twin/rebuild returns 401 without auth"""
        response = requests.post(f"{BASE_URL}/api/operator/devices/{device_id}/digital-twin/rebuild")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: POST rebuild requires authentication")
    
    def test_fleet_twins_requires_authentication(self):
        """GET /api/operator/digital-twins/fleet returns 401 without auth"""
        response = requests.get(f"{BASE_URL}/api/operator/digital-twins/fleet")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: GET fleet twins requires authentication")


class TestGetDeviceDigitalTwin:
    """Tests for GET /api/operator/devices/{device_id}/digital-twin"""
    
    def test_get_twin_returns_200(self, auth_headers, device_id):
        """GET /api/operator/devices/{device_id}/digital-twin returns 200"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{device_id}/digital-twin",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: GET digital-twin returns 200")
    
    def test_get_twin_has_device_info(self, auth_headers, device_id):
        """Response contains device_id and device_identifier"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{device_id}/digital-twin",
            headers=auth_headers
        )
        data = response.json()
        assert "device_id" in data, "Missing device_id"
        assert "device_identifier" in data, "Missing device_identifier"
        print(f"PASS: Twin has device info: {data['device_identifier']}")
    
    def test_get_twin_has_twin_exists_field(self, auth_headers, device_id):
        """Response contains twin_exists boolean"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{device_id}/digital-twin",
            headers=auth_headers
        )
        data = response.json()
        assert "twin_exists" in data, "Missing twin_exists field"
        assert isinstance(data["twin_exists"], bool), "twin_exists must be boolean"
        print(f"PASS: twin_exists = {data['twin_exists']}")
    
    def test_twin_without_data_shows_false(self, auth_headers, device_id):
        """If twin not built, twin_exists=false and has message"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{device_id}/digital-twin",
            headers=auth_headers
        )
        data = response.json()
        if not data.get("twin_exists"):
            assert "message" in data, "Missing message when twin_exists=False"
            print(f"PASS: Twin not built, message: {data['message']}")
        else:
            print("SKIP: Twin exists for this device, skipping not-built test")
    
    def test_twin_with_data_has_profile_fields(self, auth_headers, device_id):
        """If twin exists, verify wake_hour, sleep_hour, peak_activity_hour, movement_interval, inactivity threshold"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{device_id}/digital-twin",
            headers=auth_headers
        )
        data = response.json()
        if data.get("twin_exists"):
            required_fields = [
                "wake_hour", "sleep_hour", "peak_activity_hour",
                "movement_interval_minutes", "typical_inactivity_max_minutes",
                "daily_rhythm", "activity_windows", "confidence_score", "profile_summary"
            ]
            for field in required_fields:
                assert field in data, f"Missing field: {field}"
            print(f"PASS: Twin has all required profile fields")
            print(f"  wake_hour: {data['wake_hour']}, sleep_hour: {data['sleep_hour']}")
            print(f"  peak_activity_hour: {data['peak_activity_hour']}")
            print(f"  movement_interval_minutes: {data['movement_interval_minutes']}")
            print(f"  typical_inactivity_max_minutes: {data['typical_inactivity_max_minutes']}")
        else:
            print("SKIP: Twin not built, skipping profile fields test")
    
    def test_twin_daily_rhythm_structure(self, auth_headers, device_id):
        """daily_rhythm is dict with hour keys containing avg_movement, avg_interaction, expected_active"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{device_id}/digital-twin",
            headers=auth_headers
        )
        data = response.json()
        if data.get("twin_exists") and data.get("daily_rhythm"):
            rhythm = data["daily_rhythm"]
            assert isinstance(rhythm, dict), "daily_rhythm must be a dict"
            if len(rhythm) > 0:
                sample_hour = list(rhythm.keys())[0]
                sample_data = rhythm[sample_hour]
                assert "avg_movement" in sample_data, "Missing avg_movement in rhythm"
                assert "avg_interaction" in sample_data, "Missing avg_interaction in rhythm"
                assert "expected_active" in sample_data, "Missing expected_active in rhythm"
                print(f"PASS: daily_rhythm has correct structure ({len(rhythm)} hours profiled)")
        else:
            print("SKIP: No twin or rhythm data")
    
    def test_twin_activity_windows_structure(self, auth_headers, device_id):
        """activity_windows is list with start_hour, end_hour, type, avg_movement"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{device_id}/digital-twin",
            headers=auth_headers
        )
        data = response.json()
        if data.get("twin_exists") and data.get("activity_windows"):
            windows = data["activity_windows"]
            assert isinstance(windows, list), "activity_windows must be a list"
            if len(windows) > 0:
                w = windows[0]
                assert "start_hour" in w, "Missing start_hour"
                assert "end_hour" in w, "Missing end_hour"
                assert "type" in w, "Missing type"
                assert "avg_movement" in w, "Missing avg_movement"
                print(f"PASS: activity_windows has correct structure ({len(windows)} windows)")
        else:
            print("SKIP: No twin or activity_windows data")
    
    def test_twin_profile_summary_has_personality_tag(self, auth_headers, device_id):
        """profile_summary contains personality_tag"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{device_id}/digital-twin",
            headers=auth_headers
        )
        data = response.json()
        if data.get("twin_exists") and data.get("profile_summary"):
            summary = data["profile_summary"]
            assert "personality_tag" in summary, "Missing personality_tag in profile_summary"
            print(f"PASS: profile_summary has personality_tag: {summary['personality_tag']}")
        else:
            print("SKIP: No twin or profile_summary")
    
    def test_twin_has_current_state(self, auth_headers, device_id):
        """Response contains current_state with deviation_status"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{device_id}/digital-twin",
            headers=auth_headers
        )
        data = response.json()
        if data.get("twin_exists"):
            assert "current_state" in data, "Missing current_state"
            cs = data["current_state"]
            assert "hour" in cs, "Missing hour in current_state"
            assert "deviation_status" in cs, "Missing deviation_status"
            valid_statuses = ["aligned", "deviation", "positive_deviation"]
            assert cs["deviation_status"] in valid_statuses or cs["deviation_status"] is None, \
                f"Invalid deviation_status: {cs['deviation_status']}"
            print(f"PASS: current_state.deviation_status = {cs['deviation_status']}")
        else:
            print("SKIP: No twin built")
    
    def test_404_for_nonexistent_device(self, auth_headers):
        """GET with fake device_id returns 404"""
        fake_id = str(uuid.uuid4())
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{fake_id}/digital-twin",
            headers=auth_headers
        )
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("PASS: Non-existent device returns 404")


class TestRebuildDigitalTwin:
    """Tests for POST /api/operator/devices/{device_id}/digital-twin/rebuild"""
    
    def test_rebuild_returns_200_or_422(self, auth_headers, device_id):
        """POST rebuild returns 200 (success) or 422 (insufficient data)"""
        response = requests.post(
            f"{BASE_URL}/api/operator/devices/{device_id}/digital-twin/rebuild",
            headers=auth_headers
        )
        assert response.status_code in [200, 422], f"Expected 200 or 422, got {response.status_code}: {response.text}"
        if response.status_code == 200:
            print("PASS: Rebuild successful")
        else:
            print(f"PASS: Rebuild returns 422 (insufficient data): {response.json()['detail']}")
    
    def test_rebuild_success_response_structure(self, auth_headers, device_id):
        """On success, response has device_id, status, confidence_score, profile_summary"""
        response = requests.post(
            f"{BASE_URL}/api/operator/devices/{device_id}/digital-twin/rebuild",
            headers=auth_headers
        )
        if response.status_code == 200:
            data = response.json()
            assert "device_id" in data, "Missing device_id"
            assert data.get("status") == "rebuilt", "status should be 'rebuilt'"
            assert "confidence_score" in data, "Missing confidence_score"
            assert "profile_summary" in data, "Missing profile_summary"
            print(f"PASS: Rebuild response structure correct, confidence={data['confidence_score']}")
        else:
            print("SKIP: Rebuild failed (insufficient data), skipping response structure test")
    
    def test_rebuild_404_for_nonexistent_device(self, auth_headers):
        """POST rebuild with fake device_id returns 404"""
        fake_id = str(uuid.uuid4())
        response = requests.post(
            f"{BASE_URL}/api/operator/devices/{fake_id}/digital-twin/rebuild",
            headers=auth_headers
        )
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("PASS: Rebuild non-existent device returns 404")


class TestFleetDigitalTwins:
    """Tests for GET /api/operator/digital-twins/fleet"""
    
    def test_fleet_twins_returns_200(self, auth_headers):
        """GET /api/operator/digital-twins/fleet returns 200"""
        response = requests.get(
            f"{BASE_URL}/api/operator/digital-twins/fleet",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: GET fleet twins returns 200")
    
    def test_fleet_twins_response_structure(self, auth_headers):
        """Response has total_twins and twins array"""
        response = requests.get(
            f"{BASE_URL}/api/operator/digital-twins/fleet",
            headers=auth_headers
        )
        data = response.json()
        assert "total_twins" in data, "Missing total_twins"
        assert "twins" in data, "Missing twins"
        assert isinstance(data["twins"], list), "twins must be a list"
        print(f"PASS: Fleet has {data['total_twins']} twins")
    
    def test_fleet_twin_item_structure(self, auth_headers):
        """Each twin in fleet response has required fields"""
        response = requests.get(
            f"{BASE_URL}/api/operator/digital-twins/fleet",
            headers=auth_headers
        )
        data = response.json()
        if data["total_twins"] > 0:
            t = data["twins"][0]
            required = ["device_id", "device_identifier", "twin_version", "confidence_score",
                        "wake_hour", "sleep_hour", "peak_activity_hour", "training_data_points",
                        "profile_summary", "last_trained_at"]
            for field in required:
                assert field in t, f"Missing field in fleet twin: {field}"
            print(f"PASS: Fleet twin item has all required fields")
            print(f"  First twin: {t['device_identifier']}, confidence={t['confidence_score']}")
        else:
            print("SKIP: No twins in fleet")


class TestTwinBuilderScheduler:
    """Check twin builder scheduler is registered (from logs or startup)"""
    
    def test_twin_builder_scheduler_info(self, auth_headers):
        """Informational: Just verify API endpoints are responding"""
        # We can't directly check scheduler from API, but we can verify endpoints work
        response = requests.get(
            f"{BASE_URL}/api/operator/digital-twins/fleet",
            headers=auth_headers
        )
        assert response.status_code == 200
        print("INFO: Twin builder scheduler runs every 30min (per digital_twin_builder.py line 409)")
        print("PASS: Digital Twin endpoints are functional")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
