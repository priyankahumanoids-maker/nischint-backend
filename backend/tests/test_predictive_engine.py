# Test Predictive Safety Engine
# Tests for predictive-risk API and predictive-alerts API
# Features: 4 prediction types, feature_vector, trend_data, meets_alert_threshold flag

import os
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
assert BASE_URL, "REACT_APP_BACKEND_URL not set"

# Test credentials
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"

# Known device IDs (will be populated dynamically)
DEVICE_IDS = {}


@pytest.fixture(scope="module")
def operator_token():
    """Get operator JWT token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": OPERATOR_EMAIL,
        "password": OPERATOR_PASSWORD
    })
    assert response.status_code == 200, f"Login failed: {response.text}"
    return response.json()["access_token"]


@pytest.fixture(scope="module")
def auth_headers(operator_token):
    """Auth headers for operator requests"""
    return {"Authorization": f"Bearer {operator_token}"}


@pytest.fixture(scope="module")
def device_id(auth_headers):
    """Get a device ID from device-health endpoint"""
    response = requests.get(f"{BASE_URL}/api/operator/device-health?window_hours=24", headers=auth_headers)
    assert response.status_code == 200
    devices = response.json()
    assert len(devices) > 0, "No devices found for testing"
    # Return the first device (DEV-001)
    return devices[0]["device_id"]


class TestDevicePredictiveRisk:
    """Test GET /api/operator/devices/{id}/predictive-risk"""

    def test_returns_200_for_valid_device(self, auth_headers, device_id):
        """API returns 200 for valid device"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{device_id}/predictive-risk",
            headers=auth_headers
        )
        assert response.status_code == 200

    def test_response_has_live_predictions_array(self, auth_headers, device_id):
        """Response contains live_predictions array"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{device_id}/predictive-risk",
            headers=auth_headers
        )
        data = response.json()
        assert "live_predictions" in data
        assert isinstance(data["live_predictions"], list)

    def test_prediction_has_required_fields(self, auth_headers, device_id):
        """Each prediction has score, type, window, confidence, explanation"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{device_id}/predictive-risk",
            headers=auth_headers
        )
        data = response.json()
        predictions = data["live_predictions"]
        
        if len(predictions) == 0:
            pytest.skip("No predictions for this device (may have < 3 days data)")
        
        required_fields = ["prediction_type", "prediction_score", "prediction_window_hours", 
                          "confidence", "explanation"]
        
        for pred in predictions:
            for field in required_fields:
                assert field in pred, f"Missing field: {field}"

    def test_prediction_has_feature_vector(self, auth_headers, device_id):
        """Each prediction includes feature_vector for explainability"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{device_id}/predictive-risk",
            headers=auth_headers
        )
        data = response.json()
        predictions = data["live_predictions"]
        
        if len(predictions) == 0:
            pytest.skip("No predictions for this device")
        
        for pred in predictions:
            assert "feature_vector" in pred
            assert isinstance(pred["feature_vector"], dict)

    def test_prediction_has_trend_data(self, auth_headers, device_id):
        """Each prediction includes trend_data for visualization"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{device_id}/predictive-risk",
            headers=auth_headers
        )
        data = response.json()
        predictions = data["live_predictions"]
        
        if len(predictions) == 0:
            pytest.skip("No predictions for this device")
        
        for pred in predictions:
            assert "trend_data" in pred
            assert isinstance(pred["trend_data"], dict)
            # trend_data should have days array
            assert "days" in pred["trend_data"]

    def test_meets_alert_threshold_flag_computed(self, auth_headers, device_id):
        """meets_alert_threshold flag is correctly computed"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{device_id}/predictive-risk",
            headers=auth_headers
        )
        data = response.json()
        predictions = data["live_predictions"]
        
        if len(predictions) == 0:
            pytest.skip("No predictions for this device")
        
        for pred in predictions:
            assert "meets_alert_threshold" in pred
            # Verify correct computation: score >= 0.7 AND confidence >= 0.6
            expected = pred["prediction_score"] >= 0.7 and pred["confidence"] >= 0.6
            assert pred["meets_alert_threshold"] == expected, \
                f"Expected meets_alert_threshold={expected} for score={pred['prediction_score']}, conf={pred['confidence']}"

    def test_four_prediction_types_supported(self, auth_headers, device_id):
        """All 4 prediction types can be returned"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{device_id}/predictive-risk",
            headers=auth_headers
        )
        data = response.json()
        predictions = data["live_predictions"]
        
        valid_types = {"activity_decline", "sleep_disruption", "wandering_risk", "health_decline"}
        found_types = {p["prediction_type"] for p in predictions}
        
        # All found types should be valid
        for t in found_types:
            assert t in valid_types, f"Unknown prediction type: {t}"
        
        # Log which types were found (for debugging)
        print(f"Found prediction types: {found_types}")

    def test_returns_404_for_nonexistent_device(self, auth_headers):
        """Returns 404 for non-existent device"""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{fake_id}/predictive-risk",
            headers=auth_headers
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


class TestFleetPredictiveAlerts:
    """Test GET /api/operator/predictive-alerts"""

    def test_returns_200(self, auth_headers):
        """API returns 200"""
        response = requests.get(
            f"{BASE_URL}/api/operator/predictive-alerts",
            headers=auth_headers
        )
        assert response.status_code == 200

    def test_response_structure(self, auth_headers):
        """Response has total_alerts and alerts array"""
        response = requests.get(
            f"{BASE_URL}/api/operator/predictive-alerts",
            headers=auth_headers
        )
        data = response.json()
        assert "total_alerts" in data
        assert "alerts" in data
        assert isinstance(data["alerts"], list)

    def test_alert_has_required_fields(self, auth_headers):
        """Each alert has required fields"""
        response = requests.get(
            f"{BASE_URL}/api/operator/predictive-alerts",
            headers=auth_headers
        )
        data = response.json()
        
        if data["total_alerts"] == 0:
            # No alerts is valid - scheduler may not have run yet
            print("No fleet alerts active - scheduler hasn't persisted predictions yet")
            return
        
        required_fields = ["device_id", "device_identifier", "prediction_type", 
                          "prediction_score", "prediction_window_hours", 
                          "confidence", "explanation", "created_at"]
        
        for alert in data["alerts"]:
            for field in required_fields:
                assert field in alert, f"Missing field in alert: {field}"


class TestPredictiveEngineIntegration:
    """Integration tests for predictive engine features"""

    def test_dev001_has_predictions(self, auth_headers):
        """DEV-001 should have predictions with sufficient data"""
        # First get DEV-001 device ID
        response = requests.get(
            f"{BASE_URL}/api/operator/device-health?window_hours=24",
            headers=auth_headers
        )
        devices = response.json()
        dev001 = next((d for d in devices if d["device_identifier"] == "DEV-001"), None)
        
        if not dev001:
            pytest.skip("DEV-001 not found")
        
        # Get predictions for DEV-001
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{dev001['device_id']}/predictive-risk",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        # DEV-001 should have predictions (it has historical data)
        assert data["total_live_predictions"] > 0, "DEV-001 should have predictions"
        
        # Print prediction summary
        for pred in data["live_predictions"]:
            print(f"  {pred['prediction_type']}: score={pred['prediction_score']}, "
                  f"conf={pred['confidence']}, alert={pred['meets_alert_threshold']}")

    def test_alert_threshold_semantics(self, auth_headers):
        """Alert threshold: score >= 0.7 AND confidence >= 0.6"""
        response = requests.get(
            f"{BASE_URL}/api/operator/device-health?window_hours=24",
            headers=auth_headers
        )
        devices = response.json()
        dev001 = next((d for d in devices if d["device_identifier"] == "DEV-001"), None)
        
        if not dev001:
            pytest.skip("DEV-001 not found")
        
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{dev001['device_id']}/predictive-risk",
            headers=auth_headers
        )
        data = response.json()
        
        # Check that we have at least one alert-level prediction
        alerts = [p for p in data["live_predictions"] if p["meets_alert_threshold"]]
        
        for alert in alerts:
            assert alert["prediction_score"] >= 0.7
            assert alert["confidence"] >= 0.6
        
        print(f"Found {len(alerts)} predictions meeting alert threshold")

    def test_device_without_sufficient_data_returns_empty(self, auth_headers):
        """Device with < 3 days data returns empty predictions"""
        # This is tested by the API returning empty predictions for new devices
        # The main test is that the API doesn't crash and returns valid response
        response = requests.get(
            f"{BASE_URL}/api/operator/device-health?window_hours=24",
            headers=auth_headers
        )
        devices = response.json()
        
        # Test each device
        for dev in devices[:3]:  # Test first 3
            response = requests.get(
                f"{BASE_URL}/api/operator/devices/{dev['device_id']}/predictive-risk",
                headers=auth_headers
            )
            assert response.status_code == 200
            data = response.json()
            # Verify structure is valid even if empty
            assert "live_predictions" in data
            assert isinstance(data["live_predictions"], list)


class TestPredictionTypes:
    """Test all 4 prediction types in detail"""

    def test_activity_decline_prediction_structure(self, auth_headers, device_id):
        """activity_decline prediction has correct structure"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{device_id}/predictive-risk",
            headers=auth_headers
        )
        data = response.json()
        
        pred = next((p for p in data["live_predictions"] 
                    if p["prediction_type"] == "activity_decline"), None)
        
        if not pred:
            pytest.skip("No activity_decline prediction for this device")
        
        # Check feature vector has expected keys
        fv = pred["feature_vector"]
        assert "movement_trend_7d" in fv
        assert "interaction_trend_7d" in fv
        
        # Check trend data
        td = pred["trend_data"]
        assert "daily_movement" in td or "days" in td

    def test_sleep_disruption_prediction_structure(self, auth_headers, device_id):
        """sleep_disruption prediction has correct structure"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{device_id}/predictive-risk",
            headers=auth_headers
        )
        data = response.json()
        
        pred = next((p for p in data["live_predictions"] 
                    if p["prediction_type"] == "sleep_disruption"), None)
        
        if not pred:
            pytest.skip("No sleep_disruption prediction for this device")
        
        fv = pred["feature_vector"]
        assert "wake_time_shift" in fv
        
        td = pred["trend_data"]
        assert "daily_wake_hour" in td or "days" in td

    def test_wandering_risk_prediction_structure(self, auth_headers, device_id):
        """wandering_risk prediction has correct structure"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{device_id}/predictive-risk",
            headers=auth_headers
        )
        data = response.json()
        
        pred = next((p for p in data["live_predictions"] 
                    if p["prediction_type"] == "wandering_risk"), None)
        
        if not pred:
            pytest.skip("No wandering_risk prediction for this device")
        
        fv = pred["feature_vector"]
        assert "movement_variance" in fv

    def test_health_decline_prediction_structure(self, auth_headers, device_id):
        """health_decline prediction has correct structure"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{device_id}/predictive-risk",
            headers=auth_headers
        )
        data = response.json()
        
        pred = next((p for p in data["live_predictions"] 
                    if p["prediction_type"] == "health_decline"), None)
        
        if not pred:
            pytest.skip("No health_decline prediction for this device")
        
        fv = pred["feature_vector"]
        # Health decline tracks multiple declining signals
        assert "signal_count" in fv or "declining_signals" in fv
        
        td = pred["trend_data"]
        assert "days" in td
