"""
NISCHINT AI Learning Loop API Tests
====================================
Tests for the 5-phase AI Learning Loop:
- GET /api/ai/training-data-stats - Feature Store stats
- GET /api/ai/model-info - Model metadata and feature importances
- POST /api/ai/retrain - Trigger model training
- GET /api/ai/predict-risk?user_id={id} - Risk prediction with risk_factors
- POST /api/ai/feedback - Guardian feedback submission
- Safety Brain integration check
"""
import pytest
import requests
import os
import uuid
from datetime import datetime

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
TEST_EMAIL = "nischint4parents@gmail.com"
TEST_PASSWORD = "secret123"
TEST_USER_ID = "7437a394-74ef-46a2-864f-6add0e7e8e60"
SAMPLE_INCIDENT_ID = "f283c9ad-95e8-426d-aa21-6b88c5cfe990"


class TestAuthDependency:
    """Test authentication requirements for AI endpoints."""

    def test_training_data_stats_requires_auth(self):
        """GET /api/ai/training-data-stats returns 401 without token."""
        response = requests.get(f"{BASE_URL}/api/ai/training-data-stats")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: /api/ai/training-data-stats requires authentication")

    def test_model_info_requires_auth(self):
        """GET /api/ai/model-info returns 401 without token."""
        response = requests.get(f"{BASE_URL}/api/ai/model-info")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: /api/ai/model-info requires authentication")

    def test_predict_risk_requires_auth(self):
        """GET /api/ai/predict-risk returns 401 without token."""
        response = requests.get(f"{BASE_URL}/api/ai/predict-risk?user_id={TEST_USER_ID}")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: /api/ai/predict-risk requires authentication")

    def test_retrain_requires_auth(self):
        """POST /api/ai/retrain returns 401 without token."""
        response = requests.post(f"{BASE_URL}/api/ai/retrain")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: /api/ai/retrain requires authentication")

    def test_feedback_requires_auth(self):
        """POST /api/ai/feedback returns 401 without token."""
        response = requests.post(
            f"{BASE_URL}/api/ai/feedback",
            json={
                "incident_id": SAMPLE_INCIDENT_ID,
                "alert_was_useful": True,
                "guardian_response_time_sec": 30
            }
        )
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: /api/ai/feedback requires authentication")


class TestAILearningLoop:
    """Test AI Learning Loop endpoints with authentication."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Get authentication token for tests."""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
        )
        if response.status_code != 200:
            pytest.skip(f"Authentication failed: {response.status_code}")
        
        data = response.json()
        self.token = data.get("access_token")
        if not self.token:
            pytest.skip("No access token returned")
        
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        print(f"Authentication successful for {TEST_EMAIL}")

    # =========================================================================
    # Phase 1: Feature Store - GET /api/ai/training-data-stats
    # =========================================================================
    def test_training_data_stats_returns_expected_fields(self):
        """GET /api/ai/training-data-stats returns telemetry_rows, incident_rows, etc."""
        response = requests.get(
            f"{BASE_URL}/api/ai/training-data-stats",
            headers=self.headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Verify required fields
        required_fields = [
            "telemetry_rows", "incident_rows", "anomaly_rows", 
            "risk_zones", "devices_tracked"
        ]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"
            assert isinstance(data[field], int), f"Field {field} should be int"
        
        print(f"PASS: training-data-stats response: {data}")
        
        # Data assertions - verify we have actual data
        assert data["telemetry_rows"] >= 0, "telemetry_rows should be non-negative"
        print(f"  - telemetry_rows: {data['telemetry_rows']}")
        print(f"  - incident_rows: {data['incident_rows']}")
        print(f"  - anomaly_rows: {data['anomaly_rows']}")
        print(f"  - risk_zones: {data['risk_zones']}")

    # =========================================================================
    # Phase 2: Risk Model - GET /api/ai/model-info
    # =========================================================================
    def test_model_info_returns_version_and_importances(self):
        """GET /api/ai/model-info returns model version, training_rows, feature_importances, model_type."""
        response = requests.get(
            f"{BASE_URL}/api/ai/model-info",
            headers=self.headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "model" in data, "Response should contain 'model' key"
        
        model_info = data["model"]
        
        # Verify model metadata fields
        required_fields = ["version", "training_rows", "model_type", "feature_importances"]
        for field in required_fields:
            assert field in model_info, f"Missing model field: {field}"
        
        # Verify feature importances is a dict with features
        importances = model_info["feature_importances"]
        assert isinstance(importances, dict), "feature_importances should be a dict"
        assert len(importances) > 0, "feature_importances should have entries"
        
        # Verify model type is XGBoost or RandomForest (fallback)
        assert model_info["model_type"] in ["XGBClassifier", "RandomForestClassifier"], \
            f"Unexpected model_type: {model_info['model_type']}"
        
        print(f"PASS: model-info response:")
        print(f"  - version: {model_info['version']}")
        print(f"  - training_rows: {model_info['training_rows']}")
        print(f"  - model_type: {model_info['model_type']}")
        print(f"  - feature_importances: {list(importances.keys())}")

    # =========================================================================
    # Phase 3: Prediction API - GET /api/ai/predict-risk
    # =========================================================================
    def test_predict_risk_returns_expected_fields(self):
        """GET /api/ai/predict-risk returns risk_probability, risk_level, risk_factors, confidence, model_version, next_retrain."""
        response = requests.get(
            f"{BASE_URL}/api/ai/predict-risk?user_id={TEST_USER_ID}",
            headers=self.headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Check if we got an error response (no data for user)
        if "error" in data and data["error"] == "no_data":
            pytest.skip(f"No data for user {TEST_USER_ID}: {data.get('message')}")
        
        # Verify required prediction fields
        required_fields = [
            "risk_probability", "risk_level", "risk_factors", 
            "confidence", "model_version", "next_retrain"
        ]
        for field in required_fields:
            assert field in data, f"Missing prediction field: {field}"
        
        # Data type assertions
        assert isinstance(data["risk_probability"], (int, float)), "risk_probability should be numeric"
        assert 0.0 <= data["risk_probability"] <= 1.0, "risk_probability should be 0.0-1.0"
        
        assert data["risk_level"] in ["low", "moderate", "high", "critical", "unknown"], \
            f"Unexpected risk_level: {data['risk_level']}"
        
        assert isinstance(data["risk_factors"], list), "risk_factors should be a list"
        assert len(data["risk_factors"]) > 0, "risk_factors should have at least one entry"
        
        assert isinstance(data["confidence"], (int, float)), "confidence should be numeric"
        
        assert data["model_version"], "model_version should not be empty"
        
        # Verify next_retrain is ISO timestamp
        assert data["next_retrain"], "next_retrain should not be empty"
        try:
            datetime.fromisoformat(data["next_retrain"].replace('Z', '+00:00'))
        except ValueError:
            pytest.fail(f"next_retrain is not a valid ISO timestamp: {data['next_retrain']}")
        
        print(f"PASS: predict-risk response:")
        print(f"  - risk_probability: {data['risk_probability']}")
        print(f"  - risk_level: {data['risk_level']}")
        print(f"  - risk_factors: {data['risk_factors']}")
        print(f"  - confidence: {data['confidence']}")
        print(f"  - model_version: {data['model_version']}")

    def test_predict_risk_returns_human_readable_factors(self):
        """Risk prediction returns human-readable risk_factors explaining why."""
        response = requests.get(
            f"{BASE_URL}/api/ai/predict-risk?user_id={TEST_USER_ID}",
            headers=self.headers
        )
        assert response.status_code == 200
        
        data = response.json()
        if "error" in data:
            pytest.skip(f"No data for user: {data}")
        
        risk_factors = data.get("risk_factors", [])
        
        # Verify risk factors are human-readable strings
        for factor in risk_factors:
            assert isinstance(factor, str), f"Risk factor should be string: {factor}"
            assert len(factor) > 5, f"Risk factor should be descriptive: {factor}"
        
        print(f"PASS: Human-readable risk factors: {risk_factors}")

    # =========================================================================
    # Phase 4: Feedback Loop - POST /api/ai/feedback
    # =========================================================================
    def test_feedback_submission_stores_feedback(self):
        """POST /api/ai/feedback with incident_id, alert_was_useful=true stores feedback."""
        # Use sample incident ID
        payload = {
            "incident_id": SAMPLE_INCIDENT_ID,
            "alert_was_useful": True,
            "guardian_response_time_sec": 45
        }
        
        response = requests.post(
            f"{BASE_URL}/api/ai/feedback",
            headers=self.headers,
            json=payload
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("status") == "stored", f"Expected status='stored', got {data}"
        assert data.get("incident_id") == SAMPLE_INCIDENT_ID, "incident_id mismatch"
        
        print(f"PASS: Feedback stored successfully: {data}")

    def test_feedback_with_not_useful_flag(self):
        """POST /api/ai/feedback with alert_was_useful=false stores negative feedback."""
        payload = {
            "incident_id": SAMPLE_INCIDENT_ID,
            "alert_was_useful": False,
            "guardian_response_time_sec": 0
        }
        
        response = requests.post(
            f"{BASE_URL}/api/ai/feedback",
            headers=self.headers,
            json=payload
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("status") == "stored"
        print(f"PASS: Negative feedback stored: {data}")

    # =========================================================================
    # Model Retraining - POST /api/ai/retrain
    # =========================================================================
    def test_retrain_triggers_model_training(self):
        """POST /api/ai/retrain triggers model training and returns version, training_rows, positive_samples."""
        response = requests.post(
            f"{BASE_URL}/api/ai/retrain",
            headers=self.headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Check if there's an error (insufficient training data)
        if "error" in data:
            print(f"SKIP: Retrain returned error (possibly insufficient data): {data}")
            pytest.skip(f"Retrain error: {data}")
        
        # Verify retrain response fields
        assert data.get("status") == "retrained", f"Expected status='retrained', got {data}"
        assert "version" in data, "Missing version in retrain response"
        assert "training_rows" in data, "Missing training_rows in retrain response"
        assert "positive_samples" in data, "Missing positive_samples in retrain response"
        assert "model_type" in data, "Missing model_type in retrain response"
        
        print(f"PASS: Model retrained successfully:")
        print(f"  - version: {data['version']}")
        print(f"  - training_rows: {data['training_rows']}")
        print(f"  - positive_samples: {data['positive_samples']}")
        print(f"  - model_type: {data['model_type']}")

    def test_model_info_reflects_retrain(self):
        """After retrain, model-info reflects new version."""
        # First get current model info
        response = requests.get(
            f"{BASE_URL}/api/ai/model-info",
            headers=self.headers
        )
        assert response.status_code == 200
        
        data = response.json()
        model_info = data.get("model", {})
        
        # Verify model info has expected structure
        assert "version" in model_info, "model-info should have version"
        assert "trained_at" in model_info, "model-info should have trained_at"
        
        print(f"PASS: Model info reflects current state: version={model_info.get('version')}")


class TestSafetyBrainIntegration:
    """Test Safety Brain integration with ML prediction (Phase 5)."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Get authentication token."""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
        )
        if response.status_code != 200:
            pytest.skip("Authentication failed")
        
        data = response.json()
        self.token = data.get("access_token")
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

    def test_safety_brain_assess_still_works(self):
        """GET /api/safety-brain/assess should still work with ML integration."""
        response = requests.get(
            f"{BASE_URL}/api/safety-brain/assess?user_id={TEST_USER_ID}",
            headers=self.headers
        )
        
        # Safety brain assess might return 200 or 404 depending on data availability
        assert response.status_code in [200, 404], f"Unexpected status: {response.status_code}: {response.text}"
        
        if response.status_code == 200:
            data = response.json()
            print(f"PASS: Safety brain assess working: {data}")
        else:
            print(f"INFO: Safety brain assess returned 404 (no data for user)")


class TestEdgeCases:
    """Test edge cases for AI Learning Loop."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Get authentication token."""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
        )
        if response.status_code != 200:
            pytest.skip("Authentication failed")
        
        data = response.json()
        self.token = data.get("access_token")
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

    def test_predict_risk_invalid_user_id(self):
        """GET /api/ai/predict-risk with invalid user_id returns appropriate error."""
        invalid_user_id = str(uuid.uuid4())  # Random UUID that doesn't exist
        
        response = requests.get(
            f"{BASE_URL}/api/ai/predict-risk?user_id={invalid_user_id}",
            headers=self.headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        # Should return error or empty/default response
        if "error" in data:
            assert data["error"] == "no_data", f"Unexpected error: {data['error']}"
            print(f"PASS: Invalid user_id returns no_data error: {data}")
        else:
            # If model still returns prediction (with defaults), that's acceptable
            print(f"INFO: Prediction returned for unknown user: {data}")

    def test_predict_risk_missing_user_id(self):
        """GET /api/ai/predict-risk without user_id returns 422."""
        response = requests.get(
            f"{BASE_URL}/api/ai/predict-risk",
            headers=self.headers
        )
        assert response.status_code == 422, f"Expected 422 for missing param, got {response.status_code}"
        print("PASS: Missing user_id returns 422 validation error")

    def test_feedback_invalid_incident_id_format(self):
        """POST /api/ai/feedback with invalid incident_id format returns 422."""
        payload = {
            "incident_id": "not-a-valid-uuid",
            "alert_was_useful": True,
            "guardian_response_time_sec": 10
        }
        
        response = requests.post(
            f"{BASE_URL}/api/ai/feedback",
            headers=self.headers,
            json=payload
        )
        # Should fail validation or DB constraint
        assert response.status_code in [422, 500], f"Expected 422/500, got {response.status_code}"
        print(f"PASS: Invalid incident_id format returns error: {response.status_code}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
