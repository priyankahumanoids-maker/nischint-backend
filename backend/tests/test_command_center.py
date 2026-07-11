"""
Command Center API Tests
========================
Tests for GET /api/operator/command-center - Unified Intelligence Screen
This endpoint aggregates data from:
- Fleet Safety Score
- Predictive Alerts
- Risk Forecast Highlights
- Twin Evolution Shifts
- Active Incidents
"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

# Test credentials
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"
GUARDIAN_EMAIL = "nischint4parents@gmail.com"
GUARDIAN_PASSWORD = "secret123"


@pytest.fixture(scope="module")
def api_session():
    """Create a requests session."""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


@pytest.fixture(scope="module")
def operator_token(api_session):
    """Get operator authentication token."""
    response = api_session.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD}
    )
    if response.status_code == 200:
        return response.json().get("access_token")
    pytest.skip("Operator authentication failed - skipping tests")


@pytest.fixture(scope="module")
def guardian_token(api_session):
    """Get guardian authentication token."""
    response = api_session.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": GUARDIAN_EMAIL, "password": GUARDIAN_PASSWORD}
    )
    if response.status_code == 200:
        return response.json().get("access_token")
    pytest.skip("Guardian authentication failed - skipping tests")


class TestCommandCenterEndpoint:
    """Tests for GET /api/operator/command-center endpoint."""

    def test_command_center_returns_200(self, api_session, operator_token):
        """Test that command center endpoint returns 200 for operator."""
        response = api_session.get(
            f"{BASE_URL}/api/operator/command-center",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: Command center returns 200 for operator")

    def test_response_structure_has_all_sections(self, api_session, operator_token):
        """Test that response contains all 5 intelligence sections."""
        response = api_session.get(
            f"{BASE_URL}/api/operator/command-center",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Check all required sections exist
        required_sections = [
            "generated_at",
            "fleet_safety",
            "predictive_alerts",
            "forecast_highlights",
            "evolution_shifts",
            "active_incidents",
            "counts"
        ]
        
        for section in required_sections:
            assert section in data, f"Missing section: {section}"
        
        print(f"PASS: Response contains all required sections: {required_sections}")

    def test_fleet_safety_structure(self, api_session, operator_token):
        """Test fleet_safety section has correct structure."""
        response = api_session.get(
            f"{BASE_URL}/api/operator/command-center",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        fleet = data.get("fleet_safety", {})
        
        # Check fleet_safety fields
        assert "fleet_score" in fleet, "Missing fleet_score"
        assert "fleet_status" in fleet, "Missing fleet_status"
        assert "device_count" in fleet, "Missing device_count"
        assert "status_breakdown" in fleet, "Missing status_breakdown"
        assert "devices" in fleet, "Missing devices array"
        
        # Validate types
        assert isinstance(fleet["fleet_score"], (int, float)), "fleet_score should be numeric"
        assert isinstance(fleet["fleet_status"], str), "fleet_status should be string"
        assert isinstance(fleet["device_count"], int), "device_count should be int"
        assert isinstance(fleet["status_breakdown"], dict), "status_breakdown should be dict"
        assert isinstance(fleet["devices"], list), "devices should be list"
        
        print(f"PASS: Fleet safety structure - score={fleet['fleet_score']}, status={fleet['fleet_status']}, devices={fleet['device_count']}")

    def test_fleet_devices_array_structure(self, api_session, operator_token):
        """Test fleet_safety.devices array has correct structure."""
        response = api_session.get(
            f"{BASE_URL}/api/operator/command-center",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        devices = data.get("fleet_safety", {}).get("devices", [])
        
        if len(devices) > 0:
            device = devices[0]
            assert "device_id" in device, "Missing device_id"
            assert "device_identifier" in device, "Missing device_identifier"
            assert "safety_score" in device, "Missing safety_score"
            assert "status" in device, "Missing status"
            
            print(f"PASS: Device structure verified - {device['device_identifier']}: score={device['safety_score']}, status={device['status']}")
        else:
            print("PASS: No devices in fleet (empty list)")

    def test_predictive_alerts_structure(self, api_session, operator_token):
        """Test predictive_alerts array has correct structure."""
        response = api_session.get(
            f"{BASE_URL}/api/operator/command-center",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        alerts = data.get("predictive_alerts", [])
        assert isinstance(alerts, list), "predictive_alerts should be a list"
        
        if len(alerts) > 0:
            alert = alerts[0]
            required_fields = ["device_identifier", "prediction_type", "score", "explanation"]
            for field in required_fields:
                assert field in alert, f"Missing field in alert: {field}"
            
            print(f"PASS: Predictive alert structure - {alert['device_identifier']}: {alert['prediction_type']}, score={alert['score']}")
        else:
            print("PASS: No active predictive alerts (empty list)")

    def test_forecast_highlights_structure(self, api_session, operator_token):
        """Test forecast_highlights array has correct structure."""
        response = api_session.get(
            f"{BASE_URL}/api/operator/command-center",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        highlights = data.get("forecast_highlights", [])
        assert isinstance(highlights, list), "forecast_highlights should be a list"
        
        if len(highlights) > 0:
            hl = highlights[0]
            required_fields = ["device_identifier", "bucket", "risk_score", "risk_level", "reason"]
            for field in required_fields:
                assert field in hl, f"Missing field in forecast: {field}"
            
            print(f"PASS: Forecast structure - {hl['device_identifier']}: {hl['bucket']}, risk={hl['risk_level']}, score={hl['risk_score']}")
        else:
            print("PASS: No high-risk forecast windows (empty list)")

    def test_evolution_shifts_structure(self, api_session, operator_token):
        """Test evolution_shifts array has correct structure."""
        response = api_session.get(
            f"{BASE_URL}/api/operator/command-center",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        shifts = data.get("evolution_shifts", [])
        assert isinstance(shifts, list), "evolution_shifts should be a list"
        
        if len(shifts) > 0:
            shift = shifts[0]
            required_fields = ["device_identifier", "metric", "label", "change_percent", "from_value", "to_value", "severity"]
            for field in required_fields:
                assert field in shift, f"Missing field in shift: {field}"
            
            print(f"PASS: Evolution shift structure - {shift['device_identifier']}: {shift['label']} {shift['change_percent']}%")
        else:
            print("PASS: No behavioral shifts detected (empty list)")

    def test_active_incidents_structure(self, api_session, operator_token):
        """Test active_incidents array has correct structure."""
        response = api_session.get(
            f"{BASE_URL}/api/operator/command-center",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        incidents = data.get("active_incidents", [])
        assert isinstance(incidents, list), "active_incidents should be a list"
        
        if len(incidents) > 0:
            inc = incidents[0]
            required_fields = ["id", "device_identifier", "incident_type", "severity", "status", "escalation_level", "created_at"]
            for field in required_fields:
                assert field in inc, f"Missing field in incident: {field}"
            
            print(f"PASS: Incident structure - {inc['device_identifier']}: {inc['incident_type']}, severity={inc['severity']}, L{inc['escalation_level']}")
        else:
            print("PASS: No active incidents (empty list)")

    def test_counts_object_structure(self, api_session, operator_token):
        """Test counts object has all required counts."""
        response = api_session.get(
            f"{BASE_URL}/api/operator/command-center",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        counts = data.get("counts", {})
        required_counts = [
            "predictive_alerts",
            "high_risk_windows",
            "evolution_shifts",
            "active_incidents",
            "critical_devices"
        ]
        
        for count_name in required_counts:
            assert count_name in counts, f"Missing count: {count_name}"
            assert isinstance(counts[count_name], int), f"{count_name} should be int"
        
        print(f"PASS: Counts - alerts={counts['predictive_alerts']}, high_risk={counts['high_risk_windows']}, shifts={counts['evolution_shifts']}, incidents={counts['active_incidents']}, critical={counts['critical_devices']}")


class TestCommandCenterRBAC:
    """Test RBAC enforcement for command center endpoint."""

    def test_guardian_gets_403(self, api_session, guardian_token):
        """Guardian role should get 403 Forbidden."""
        response = api_session.get(
            f"{BASE_URL}/api/operator/command-center",
            headers={"Authorization": f"Bearer {guardian_token}"}
        )
        assert response.status_code == 403, f"Expected 403 for guardian, got {response.status_code}"
        print("PASS: Guardian correctly gets 403 Forbidden")

    def test_unauthenticated_gets_401(self, api_session):
        """Unauthenticated request should get 401."""
        response = api_session.get(f"{BASE_URL}/api/operator/command-center")
        assert response.status_code == 401, f"Expected 401 for unauthenticated, got {response.status_code}"
        print("PASS: Unauthenticated request correctly gets 401")


class TestCommandCenterDataContent:
    """Test actual data content from command center."""

    def test_fleet_score_in_valid_range(self, api_session, operator_token):
        """Fleet score should be between 0 and 100."""
        response = api_session.get(
            f"{BASE_URL}/api/operator/command-center",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        score = data.get("fleet_safety", {}).get("fleet_score", -1)
        assert 0 <= score <= 100, f"Fleet score {score} out of range [0, 100]"
        print(f"PASS: Fleet score {score} is in valid range [0, 100]")

    def test_fleet_status_is_valid(self, api_session, operator_token):
        """Fleet status should be one of valid statuses."""
        response = api_session.get(
            f"{BASE_URL}/api/operator/command-center",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        status = data.get("fleet_safety", {}).get("fleet_status", "")
        valid_statuses = ["EXCELLENT", "STABLE", "MONITOR", "ATTENTION", "CRITICAL"]
        assert status in valid_statuses, f"Fleet status '{status}' not in {valid_statuses}"
        print(f"PASS: Fleet status '{status}' is valid")

    def test_status_breakdown_counts_match_device_count(self, api_session, operator_token):
        """Sum of status_breakdown should match device_count."""
        response = api_session.get(
            f"{BASE_URL}/api/operator/command-center",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        fleet = data.get("fleet_safety", {})
        device_count = fleet.get("device_count", 0)
        breakdown = fleet.get("status_breakdown", {})
        breakdown_total = sum(breakdown.values())
        
        assert breakdown_total == device_count, f"Breakdown total {breakdown_total} != device_count {device_count}"
        print(f"PASS: Status breakdown total ({breakdown_total}) matches device_count ({device_count})")

    def test_predictive_alert_scores_valid(self, api_session, operator_token):
        """Predictive alert scores should be in valid range [0.5, 1.0]."""
        response = api_session.get(
            f"{BASE_URL}/api/operator/command-center",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        alerts = data.get("predictive_alerts", [])
        for alert in alerts:
            score = alert.get("score", 0)
            # Command center filters predictions with score >= 0.5
            assert 0.5 <= score <= 1.0, f"Alert score {score} out of expected range"
        
        print(f"PASS: All {len(alerts)} predictive alerts have valid scores >= 0.5")

    def test_forecast_risk_levels_valid(self, api_session, operator_token):
        """Forecast risk levels should be HIGH or MEDIUM."""
        response = api_session.get(
            f"{BASE_URL}/api/operator/command-center",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        highlights = data.get("forecast_highlights", [])
        for hl in highlights:
            level = hl.get("risk_level", "")
            assert level in ["HIGH", "MEDIUM"], f"Invalid risk level: {level}"
        
        print(f"PASS: All {len(highlights)} forecast highlights have valid risk levels")

    def test_evolution_shift_severity_valid(self, api_session, operator_token):
        """Evolution shift severity should be 'high' or 'medium'."""
        response = api_session.get(
            f"{BASE_URL}/api/operator/command-center",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        shifts = data.get("evolution_shifts", [])
        for shift in shifts:
            severity = shift.get("severity", "")
            assert severity in ["high", "medium"], f"Invalid shift severity: {severity}"
        
        print(f"PASS: All {len(shifts)} evolution shifts have valid severity")

    def test_incident_severity_levels_valid(self, api_session, operator_token):
        """Incident severity should be valid values."""
        response = api_session.get(
            f"{BASE_URL}/api/operator/command-center",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        incidents = data.get("active_incidents", [])
        valid_severities = ["critical", "high", "medium", "low"]
        for inc in incidents:
            severity = inc.get("severity", "")
            assert severity in valid_severities, f"Invalid incident severity: {severity}"
        
        print(f"PASS: All {len(incidents)} incidents have valid severity")

    def test_generated_at_is_recent(self, api_session, operator_token):
        """generated_at timestamp should be recent."""
        from datetime import datetime, timedelta
        
        response = api_session.get(
            f"{BASE_URL}/api/operator/command-center",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        generated_at = data.get("generated_at", "")
        assert generated_at, "Missing generated_at timestamp"
        
        # Parse and check it's within last 5 minutes
        ts = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        now = datetime.utcnow()
        diff = abs((now - ts.replace(tzinfo=None)).total_seconds())
        assert diff < 300, f"generated_at too old: {diff} seconds ago"
        
        print(f"PASS: generated_at is recent ({diff:.1f} seconds ago)")
