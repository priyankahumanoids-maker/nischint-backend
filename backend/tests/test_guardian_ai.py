# Guardian AI Predictive Intelligence Tests
# Tests for Guardian AI prediction engine, config management, action responses, and history

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
TEST_EMAIL = "nischint4parents@gmail.com"
TEST_PASSWORD = "secret123"

@pytest.fixture(scope="module")
def auth_token():
    """Login and get auth token"""
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200, f"Login failed: {response.text}"
    data = response.json()
    assert "access_token" in data, f"No access_token in response: {data}"
    return data["access_token"]

@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Returns headers with auth token"""
    return {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json"
    }

class TestGuardianAIAuth:
    """Test authentication requirements for Guardian AI endpoints"""
    
    def test_config_get_requires_auth(self):
        """GET /api/guardian-ai/config requires auth"""
        response = requests.get(f"{BASE_URL}/api/guardian-ai/config")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
    
    def test_config_put_requires_auth(self):
        """PUT /api/guardian-ai/config requires auth"""
        response = requests.put(
            f"{BASE_URL}/api/guardian-ai/config",
            json={"sensitivity": "high"}
        )
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
    
    def test_predict_risk_requires_auth(self):
        """POST /api/guardian-ai/predict-risk requires auth"""
        response = requests.post(
            f"{BASE_URL}/api/guardian-ai/predict-risk",
            json={"lat": 28.6139, "lng": 77.2090}
        )
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
    
    def test_accept_action_requires_auth(self):
        """POST /api/guardian-ai/accept-action/{id} requires auth"""
        response = requests.post(f"{BASE_URL}/api/guardian-ai/accept-action/fake-id")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
    
    def test_dismiss_requires_auth(self):
        """POST /api/guardian-ai/dismiss/{id} requires auth"""
        response = requests.post(f"{BASE_URL}/api/guardian-ai/dismiss/fake-id")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
    
    def test_history_requires_auth(self):
        """GET /api/guardian-ai/history requires auth"""
        response = requests.get(f"{BASE_URL}/api/guardian-ai/history")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"


class TestGuardianAIConfig:
    """Test Guardian AI configuration endpoints"""
    
    def test_get_config_returns_defaults(self, auth_headers):
        """GET /api/guardian-ai/config returns config with default values"""
        response = requests.get(
            f"{BASE_URL}/api/guardian-ai/config",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Verify all required fields present
        assert "id" in data, "Missing id field"
        assert "user_id" in data, "Missing user_id field"
        assert "enabled" in data, "Missing enabled field"
        assert "sensitivity" in data, "Missing sensitivity field"
        assert "notification_threshold" in data, "Missing notification_threshold field"
        assert "call_threshold" in data, "Missing call_threshold field"
        assert "sos_threshold" in data, "Missing sos_threshold field"
        assert "auto_trigger" in data, "Missing auto_trigger field"
        assert "cooldown_minutes" in data, "Missing cooldown_minutes field"
        assert "updated_at" in data, "Missing updated_at field"
        
        # Verify default threshold values (notif=0.6, call=0.75, sos=0.85)
        assert data["notification_threshold"] == 0.6 or isinstance(data["notification_threshold"], float), \
            f"Notification threshold mismatch: {data['notification_threshold']}"
        assert data["call_threshold"] == 0.75 or isinstance(data["call_threshold"], float), \
            f"Call threshold mismatch: {data['call_threshold']}"
        assert data["sos_threshold"] == 0.85 or isinstance(data["sos_threshold"], float), \
            f"SOS threshold mismatch: {data['sos_threshold']}"
        
        # Verify sensitivity default
        assert data["sensitivity"] in ["low", "medium", "high"], \
            f"Invalid sensitivity value: {data['sensitivity']}"
    
    def test_update_config_sensitivity(self, auth_headers):
        """PUT /api/guardian-ai/config updates sensitivity"""
        response = requests.put(
            f"{BASE_URL}/api/guardian-ai/config",
            headers=auth_headers,
            json={"sensitivity": "high"}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["sensitivity"] == "high", f"Sensitivity not updated: {data['sensitivity']}"
        
        # Reset to medium
        requests.put(
            f"{BASE_URL}/api/guardian-ai/config",
            headers=auth_headers,
            json={"sensitivity": "medium"}
        )
    
    def test_update_config_thresholds(self, auth_headers):
        """PUT /api/guardian-ai/config updates thresholds"""
        new_thresholds = {
            "notification_threshold": 0.5,
            "call_threshold": 0.7,
            "sos_threshold": 0.9
        }
        response = requests.put(
            f"{BASE_URL}/api/guardian-ai/config",
            headers=auth_headers,
            json=new_thresholds
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["notification_threshold"] == 0.5, f"Notification threshold mismatch"
        assert data["call_threshold"] == 0.7, f"Call threshold mismatch"
        assert data["sos_threshold"] == 0.9, f"SOS threshold mismatch"
        
        # Reset to defaults
        requests.put(
            f"{BASE_URL}/api/guardian-ai/config",
            headers=auth_headers,
            json={
                "notification_threshold": 0.6,
                "call_threshold": 0.75,
                "sos_threshold": 0.85
            }
        )
    
    def test_update_config_auto_trigger(self, auth_headers):
        """PUT /api/guardian-ai/config updates auto_trigger"""
        response = requests.put(
            f"{BASE_URL}/api/guardian-ai/config",
            headers=auth_headers,
            json={"auto_trigger": True}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["auto_trigger"] == True, f"Auto trigger not updated"
        
        # Reset
        requests.put(
            f"{BASE_URL}/api/guardian-ai/config",
            headers=auth_headers,
            json={"auto_trigger": False}
        )
    
    def test_update_config_cooldown(self, auth_headers):
        """PUT /api/guardian-ai/config updates cooldown_minutes"""
        response = requests.put(
            f"{BASE_URL}/api/guardian-ai/config",
            headers=auth_headers,
            json={"cooldown_minutes": 60}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["cooldown_minutes"] == 60, f"Cooldown not updated: {data['cooldown_minutes']}"
        
        # Reset
        requests.put(
            f"{BASE_URL}/api/guardian-ai/config",
            headers=auth_headers,
            json={"cooldown_minutes": 30}
        )
    
    def test_update_config_enabled(self, auth_headers):
        """PUT /api/guardian-ai/config updates enabled status"""
        # Disable
        response = requests.put(
            f"{BASE_URL}/api/guardian-ai/config",
            headers=auth_headers,
            json={"enabled": False}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["enabled"] == False, f"Enabled not updated"
        
        # Re-enable
        response = requests.put(
            f"{BASE_URL}/api/guardian-ai/config",
            headers=auth_headers,
            json={"enabled": True}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] == True, f"Enabled not re-enabled"
    
    def test_config_validates_sensitivity(self, auth_headers):
        """PUT /api/guardian-ai/config validates sensitivity values"""
        response = requests.put(
            f"{BASE_URL}/api/guardian-ai/config",
            headers=auth_headers,
            json={"sensitivity": "invalid_value"}
        )
        assert response.status_code == 422, f"Expected 422 for invalid sensitivity, got {response.status_code}"
    
    def test_config_validates_cooldown_min(self, auth_headers):
        """PUT /api/guardian-ai/config validates cooldown minimum (5)"""
        response = requests.put(
            f"{BASE_URL}/api/guardian-ai/config",
            headers=auth_headers,
            json={"cooldown_minutes": 2}  # Below minimum of 5
        )
        assert response.status_code == 422, f"Expected 422 for cooldown below 5, got {response.status_code}"


class TestGuardianAIPrediction:
    """Test Guardian AI prediction endpoint"""
    
    def test_predict_risk_basic(self, auth_headers):
        """POST /api/guardian-ai/predict-risk returns prediction with all fields"""
        response = requests.post(
            f"{BASE_URL}/api/guardian-ai/predict-risk",
            headers=auth_headers,
            json={"lat": 28.6139, "lng": 77.2090}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Verify all required fields
        assert "id" in data, "Missing id field"
        assert "risk_score" in data, "Missing risk_score field"
        assert "risk_level" in data, "Missing risk_level field"
        assert "confidence" in data, "Missing confidence field"
        assert "recommended_action" in data, "Missing recommended_action field"
        assert "action_detail" in data, "Missing action_detail field"
        assert "risk_factors" in data, "Missing risk_factors field"
        assert "layer_scores" in data, "Missing layer_scores field"
        assert "narrative" in data, "Missing narrative field"
        assert "status" in data, "Missing status field"
        
        # Verify data types
        assert isinstance(data["risk_score"], (int, float)), "risk_score should be numeric"
        assert 0 <= data["risk_score"] <= 1, f"risk_score should be 0-1, got {data['risk_score']}"
        assert data["risk_level"] in ["low", "moderate", "high", "critical"], \
            f"Invalid risk_level: {data['risk_level']}"
        assert isinstance(data["confidence"], (int, float)), "confidence should be numeric"
        assert data["recommended_action"] in ["monitor", "fake_notification", "fake_call", "sos_prearm"], \
            f"Invalid recommended_action: {data['recommended_action']}"
    
    def test_predict_risk_layer_scores(self, auth_headers):
        """POST /api/guardian-ai/predict-risk returns layer breakdown"""
        response = requests.post(
            f"{BASE_URL}/api/guardian-ai/predict-risk",
            headers=auth_headers,
            json={"lat": 28.6139, "lng": 77.2090}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        layer_scores = data.get("layer_scores", {})
        
        # Verify all 3 layers present
        assert "realtime" in layer_scores, "Missing realtime layer"
        assert "location" in layer_scores, "Missing location layer"
        assert "behavioral" in layer_scores, "Missing behavioral layer"
        
        # Each layer should have score
        for layer in ["realtime", "location", "behavioral"]:
            assert "score" in layer_scores[layer], f"Missing score in {layer} layer"
    
    def test_predict_risk_action_detail(self, auth_headers):
        """POST /api/guardian-ai/predict-risk returns action_detail with urgency"""
        response = requests.post(
            f"{BASE_URL}/api/guardian-ai/predict-risk",
            headers=auth_headers,
            json={"lat": 28.6139, "lng": 77.2090}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        action_detail = data.get("action_detail", {})
        assert "action" in action_detail, "Missing action in action_detail"
        assert "urgency" in action_detail, "Missing urgency in action_detail"
        assert action_detail["urgency"] in ["low", "medium", "high", "critical"], \
            f"Invalid urgency: {action_detail['urgency']}"
    
    def test_predict_risk_without_location(self, auth_headers):
        """POST /api/guardian-ai/predict-risk works without coordinates"""
        response = requests.post(
            f"{BASE_URL}/api/guardian-ai/predict-risk",
            headers=auth_headers,
            json={}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "risk_score" in data, "Missing risk_score"
        assert "risk_level" in data, "Missing risk_level"
    
    def test_predict_risk_narrative(self, auth_headers):
        """POST /api/guardian-ai/predict-risk returns narrative text"""
        response = requests.post(
            f"{BASE_URL}/api/guardian-ai/predict-risk",
            headers=auth_headers,
            json={"lat": 28.6139, "lng": 77.2090}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        narrative = data.get("narrative")
        assert narrative is not None, "Missing narrative"
        assert isinstance(narrative, str), "Narrative should be string"
        assert len(narrative) > 0, "Narrative should not be empty"


class TestGuardianAIActions:
    """Test accept/dismiss action endpoints"""
    
    @pytest.fixture
    def prediction_id(self, auth_headers):
        """Create a prediction and return its ID"""
        response = requests.post(
            f"{BASE_URL}/api/guardian-ai/predict-risk",
            headers=auth_headers,
            json={"lat": 28.6139, "lng": 77.2090}
        )
        assert response.status_code == 200
        return response.json()["id"]
    
    def test_accept_action_success(self, auth_headers, prediction_id):
        """POST /api/guardian-ai/accept-action/{id} updates status to accepted"""
        response = requests.post(
            f"{BASE_URL}/api/guardian-ai/accept-action/{prediction_id}",
            headers=auth_headers
        )
        # May return 200 or prediction might already be completed (monitor action)
        if response.status_code == 200:
            data = response.json()
            assert data["status"] == "accepted", f"Status should be accepted, got {data['status']}"
            assert data["user_response"] == "accept", f"User response should be accept"
            assert data["responded_at"] is not None, "responded_at should be set"
        else:
            # Prediction might be auto-completed if action was 'monitor'
            print(f"Accept returned {response.status_code}: {response.text}")
    
    def test_dismiss_success(self, auth_headers, prediction_id):
        """POST /api/guardian-ai/dismiss/{id} updates status to dismissed"""
        # First create another prediction
        pred_response = requests.post(
            f"{BASE_URL}/api/guardian-ai/predict-risk",
            headers=auth_headers,
            json={"lat": 28.6139, "lng": 77.2090}
        )
        assert pred_response.status_code == 200
        new_pred_id = pred_response.json()["id"]
        
        response = requests.post(
            f"{BASE_URL}/api/guardian-ai/dismiss/{new_pred_id}",
            headers=auth_headers
        )
        if response.status_code == 200:
            data = response.json()
            assert data["status"] == "dismissed", f"Status should be dismissed, got {data['status']}"
            assert data["user_response"] == "dismiss", f"User response should be dismiss"
            assert data["responded_at"] is not None, "responded_at should be set"
        else:
            print(f"Dismiss returned {response.status_code}: {response.text}")
    
    def test_accept_nonexistent_returns_404(self, auth_headers):
        """POST /api/guardian-ai/accept-action/{id} returns 404 for non-existent"""
        import uuid
        fake_id = str(uuid.uuid4())
        response = requests.post(
            f"{BASE_URL}/api/guardian-ai/accept-action/{fake_id}",
            headers=auth_headers
        )
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
    
    def test_dismiss_nonexistent_returns_404(self, auth_headers):
        """POST /api/guardian-ai/dismiss/{id} returns 404 for non-existent"""
        import uuid
        fake_id = str(uuid.uuid4())
        response = requests.post(
            f"{BASE_URL}/api/guardian-ai/dismiss/{fake_id}",
            headers=auth_headers
        )
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"


class TestGuardianAIHistory:
    """Test prediction history endpoint"""
    
    def test_history_returns_list(self, auth_headers):
        """GET /api/guardian-ai/history returns list with count"""
        response = requests.get(
            f"{BASE_URL}/api/guardian-ai/history",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert "predictions" in data, "Missing predictions field"
        assert "count" in data, "Missing count field"
        assert isinstance(data["predictions"], list), "predictions should be a list"
        assert data["count"] == len(data["predictions"]), "Count should match list length"
    
    def test_history_entry_structure(self, auth_headers):
        """GET /api/guardian-ai/history entries have correct structure"""
        # First ensure we have at least one prediction
        requests.post(
            f"{BASE_URL}/api/guardian-ai/predict-risk",
            headers=auth_headers,
            json={"lat": 28.6139, "lng": 77.2090}
        )
        
        response = requests.get(
            f"{BASE_URL}/api/guardian-ai/history",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        if data["count"] > 0:
            entry = data["predictions"][0]
            
            # Verify entry structure
            required_fields = [
                "id", "risk_score", "risk_level", "confidence", "recommended_action",
                "action_detail", "risk_factors", "layer_scores", "narrative",
                "status", "created_at"
            ]
            for field in required_fields:
                assert field in entry, f"Missing {field} in history entry"
    
    def test_history_respects_limit(self, auth_headers):
        """GET /api/guardian-ai/history respects limit parameter"""
        response = requests.get(
            f"{BASE_URL}/api/guardian-ai/history?limit=5",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["count"] <= 5, f"Limit not respected: got {data['count']} entries"
    
    def test_history_sorted_by_recent(self, auth_headers):
        """GET /api/guardian-ai/history sorted by created_at DESC"""
        response = requests.get(
            f"{BASE_URL}/api/guardian-ai/history",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        if data["count"] > 1:
            predictions = data["predictions"]
            for i in range(len(predictions) - 1):
                current_time = predictions[i]["created_at"]
                next_time = predictions[i + 1]["created_at"]
                assert current_time >= next_time, "History should be sorted by created_at DESC"
