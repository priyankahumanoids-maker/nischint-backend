"""
Test Command Center AI Intelligence Features (Palantir-grade)
Tests: City Risk Radar, Predictive Alert Bar, AI Reasoning Panel, Digital Twin Panel, AI Timeline
All features use Guardian AI APIs
"""
import os
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestCommandCenterAIFeatures:
    """Test the 5 Palantir-grade intelligence features backend APIs"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup: authenticate as admin"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login as admin
        login_resp = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": "nischint4parents@gmail.com",
            "password": "secret123"
        })
        assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
        token = login_resp.json().get("access_token")
        self.session.headers.update({"Authorization": f"Bearer {token}"})
        self.token = token
    
    # -------------------------------------------------------------------
    # City Risk Radar tests - Uses heatmap data for zone counts
    # -------------------------------------------------------------------
    def test_city_heatmap_live_returns_200(self):
        """City Risk Radar data: /operator/city-heatmap/live returns 200"""
        resp = self.session.get(f"{BASE_URL}/api/operator/city-heatmap/live")
        assert resp.status_code == 200, f"City heatmap live failed: {resp.text}"
    
    def test_city_heatmap_has_cells_array(self):
        """City Risk Radar: heatmap has cells array"""
        resp = self.session.get(f"{BASE_URL}/api/operator/city-heatmap/live")
        data = resp.json()
        assert "cells" in data, "Missing 'cells' in heatmap response"
        assert isinstance(data["cells"], list), "cells should be an array"
    
    def test_city_heatmap_cell_has_risk_fields(self):
        """City Risk Radar: cells have risk_level, composite_score fields"""
        resp = self.session.get(f"{BASE_URL}/api/operator/city-heatmap/live")
        data = resp.json()
        if len(data.get("cells", [])) > 0:
            cell = data["cells"][0]
            assert "risk_level" in cell, "Missing risk_level in cell"
            assert "composite_score" in cell, "Missing composite_score in cell"
    
    # -------------------------------------------------------------------
    # High Risk Users - Powers AI Risk Intelligence panel
    # -------------------------------------------------------------------
    def test_high_risk_users_returns_200(self):
        """AI Risk Intelligence: /guardian-ai/insights/high-risk returns 200"""
        resp = self.session.get(f"{BASE_URL}/api/guardian-ai/insights/high-risk?limit=6")
        assert resp.status_code == 200, f"High risk users failed: {resp.text}"
    
    def test_high_risk_users_has_array(self):
        """AI Risk Intelligence: returns high_risk_users array"""
        resp = self.session.get(f"{BASE_URL}/api/guardian-ai/insights/high-risk?limit=6")
        data = resp.json()
        assert "high_risk_users" in data, "Missing high_risk_users"
        assert isinstance(data["high_risk_users"], list), "high_risk_users should be array"
    
    def test_high_risk_user_has_required_fields(self):
        """AI Risk Intelligence: user has user_id, user_name, final_score, risk_level, top_factors"""
        resp = self.session.get(f"{BASE_URL}/api/guardian-ai/insights/high-risk?limit=6")
        data = resp.json()
        users = data.get("high_risk_users", [])
        if len(users) > 0:
            user = users[0]
            assert "user_id" in user, "Missing user_id"
            assert "user_name" in user, "Missing user_name"
            assert "final_score" in user, "Missing final_score"
            assert "risk_level" in user, "Missing risk_level"
            assert "top_factors" in user, "Missing top_factors"
    
    # -------------------------------------------------------------------
    # AI Reasoning Panel tests - Uses /guardian-ai/{user_id}/risk-score
    # -------------------------------------------------------------------
    def test_risk_score_api_returns_200(self):
        """AI Reasoning Panel: /guardian-ai/{user_id}/risk-score returns 200"""
        # First get a user_id from high-risk list
        hr_resp = self.session.get(f"{BASE_URL}/api/guardian-ai/insights/high-risk?limit=1")
        assert hr_resp.status_code == 200
        users = hr_resp.json().get("high_risk_users", [])
        if len(users) == 0:
            pytest.skip("No high-risk users available for testing")
        
        user_id = users[0]["user_id"]
        resp = self.session.get(f"{BASE_URL}/api/guardian-ai/{user_id}/risk-score")
        assert resp.status_code == 200, f"Risk score API failed: {resp.text}"
    
    def test_risk_score_has_final_score_and_level(self):
        """AI Reasoning Panel: risk-score returns final_score and risk_level"""
        hr_resp = self.session.get(f"{BASE_URL}/api/guardian-ai/insights/high-risk?limit=1")
        users = hr_resp.json().get("high_risk_users", [])
        if len(users) == 0:
            pytest.skip("No high-risk users available")
        
        user_id = users[0]["user_id"]
        resp = self.session.get(f"{BASE_URL}/api/guardian-ai/{user_id}/risk-score")
        data = resp.json()
        assert "final_score" in data, "Missing final_score"
        assert "risk_level" in data, "Missing risk_level"
    
    def test_risk_score_has_scores_breakdown(self):
        """AI Reasoning Panel: risk-score returns scores breakdown (behavior, location, device, environment, response)"""
        hr_resp = self.session.get(f"{BASE_URL}/api/guardian-ai/insights/high-risk?limit=1")
        users = hr_resp.json().get("high_risk_users", [])
        if len(users) == 0:
            pytest.skip("No high-risk users available")
        
        user_id = users[0]["user_id"]
        resp = self.session.get(f"{BASE_URL}/api/guardian-ai/{user_id}/risk-score")
        data = resp.json()
        assert "scores" in data, "Missing scores breakdown"
        scores = data["scores"]
        # Check for factor categories used in AI Reasoning Panel
        expected_categories = ["behavior", "location", "device", "environment", "response"]
        for cat in expected_categories:
            assert cat in scores, f"Missing score category: {cat}"
    
    def test_risk_score_has_top_factors(self):
        """AI Reasoning Panel: risk-score returns top_factors with descriptions"""
        hr_resp = self.session.get(f"{BASE_URL}/api/guardian-ai/insights/high-risk?limit=1")
        users = hr_resp.json().get("high_risk_users", [])
        if len(users) == 0:
            pytest.skip("No high-risk users available")
        
        user_id = users[0]["user_id"]
        resp = self.session.get(f"{BASE_URL}/api/guardian-ai/{user_id}/risk-score")
        data = resp.json()
        assert "top_factors" in data, "Missing top_factors"
        assert isinstance(data["top_factors"], list), "top_factors should be array"
    
    # -------------------------------------------------------------------
    # Digital Twin Panel tests - Uses /guardian-ai/{user_id}/baseline
    # -------------------------------------------------------------------
    def test_baseline_api_returns_200(self):
        """Digital Twin Panel: /guardian-ai/{user_id}/baseline returns 200"""
        hr_resp = self.session.get(f"{BASE_URL}/api/guardian-ai/insights/high-risk?limit=1")
        users = hr_resp.json().get("high_risk_users", [])
        if len(users) == 0:
            pytest.skip("No high-risk users available")
        
        user_id = users[0]["user_id"]
        resp = self.session.get(f"{BASE_URL}/api/guardian-ai/{user_id}/baseline")
        assert resp.status_code == 200, f"Baseline API failed: {resp.text}"
    
    def test_baseline_has_active_hours(self):
        """Digital Twin Panel: baseline returns active_hours for normal travel hours"""
        hr_resp = self.session.get(f"{BASE_URL}/api/guardian-ai/insights/high-risk?limit=1")
        users = hr_resp.json().get("high_risk_users", [])
        if len(users) == 0:
            pytest.skip("No high-risk users available")
        
        user_id = users[0]["user_id"]
        resp = self.session.get(f"{BASE_URL}/api/guardian-ai/{user_id}/baseline")
        data = resp.json()
        assert "active_hours" in data, "Missing active_hours in baseline"
    
    def test_baseline_has_common_locations(self):
        """Digital Twin Panel: baseline returns common_locations for safe zones"""
        hr_resp = self.session.get(f"{BASE_URL}/api/guardian-ai/insights/high-risk?limit=1")
        users = hr_resp.json().get("high_risk_users", [])
        if len(users) == 0:
            pytest.skip("No high-risk users available")
        
        user_id = users[0]["user_id"]
        resp = self.session.get(f"{BASE_URL}/api/guardian-ai/{user_id}/baseline")
        data = resp.json()
        assert "common_locations" in data, "Missing common_locations"
    
    def test_baseline_has_route_clusters(self):
        """Digital Twin Panel: baseline returns route_clusters for typical commute"""
        hr_resp = self.session.get(f"{BASE_URL}/api/guardian-ai/insights/high-risk?limit=1")
        users = hr_resp.json().get("high_risk_users", [])
        if len(users) == 0:
            pytest.skip("No high-risk users available")
        
        user_id = users[0]["user_id"]
        resp = self.session.get(f"{BASE_URL}/api/guardian-ai/{user_id}/baseline")
        data = resp.json()
        assert "route_clusters" in data, "Missing route_clusters"
    
    def test_baseline_has_avg_daily_distance(self):
        """Digital Twin Panel: baseline returns avg_daily_distance"""
        hr_resp = self.session.get(f"{BASE_URL}/api/guardian-ai/insights/high-risk?limit=1")
        users = hr_resp.json().get("high_risk_users", [])
        if len(users) == 0:
            pytest.skip("No high-risk users available")
        
        user_id = users[0]["user_id"]
        resp = self.session.get(f"{BASE_URL}/api/guardian-ai/{user_id}/baseline")
        data = resp.json()
        assert "avg_daily_distance" in data, "Missing avg_daily_distance"
    
    # -------------------------------------------------------------------
    # AI Timeline tests - Uses /guardian-ai/{user_id}/risk-history
    # -------------------------------------------------------------------
    def test_risk_history_api_returns_200(self):
        """AI Timeline: /guardian-ai/{user_id}/risk-history returns 200"""
        hr_resp = self.session.get(f"{BASE_URL}/api/guardian-ai/insights/high-risk?limit=1")
        users = hr_resp.json().get("high_risk_users", [])
        if len(users) == 0:
            pytest.skip("No high-risk users available")
        
        user_id = users[0]["user_id"]
        resp = self.session.get(f"{BASE_URL}/api/guardian-ai/{user_id}/risk-history?limit=15")
        assert resp.status_code == 200, f"Risk history API failed: {resp.text}"
    
    def test_risk_history_has_events_array(self):
        """AI Timeline: risk-history returns events array"""
        hr_resp = self.session.get(f"{BASE_URL}/api/guardian-ai/insights/high-risk?limit=1")
        users = hr_resp.json().get("high_risk_users", [])
        if len(users) == 0:
            pytest.skip("No high-risk users available")
        
        user_id = users[0]["user_id"]
        resp = self.session.get(f"{BASE_URL}/api/guardian-ai/{user_id}/risk-history?limit=15")
        data = resp.json()
        assert "events" in data, "Missing events in risk-history"
        assert isinstance(data["events"], list), "events should be array"
    
    def test_risk_history_events_have_timestamp_and_score(self):
        """AI Timeline: events have timestamp and final_risk_score"""
        hr_resp = self.session.get(f"{BASE_URL}/api/guardian-ai/insights/high-risk?limit=1")
        users = hr_resp.json().get("high_risk_users", [])
        if len(users) == 0:
            pytest.skip("No high-risk users available")
        
        user_id = users[0]["user_id"]
        resp = self.session.get(f"{BASE_URL}/api/guardian-ai/{user_id}/risk-history?limit=15")
        data = resp.json()
        events = data.get("events", [])
        if len(events) > 0:
            event = events[0]
            assert "timestamp" in event, "Missing timestamp in event"
            # Check for score field (could be final_risk_score or final_score)
            has_score = "final_risk_score" in event or "final_score" in event
            assert has_score, "Missing risk score in event"
    
    # -------------------------------------------------------------------
    # Predictive Alert Bar tests - Uses /guardian-ai/{user_id}/predictions
    # -------------------------------------------------------------------
    def test_predictions_api_returns_200(self):
        """Predictive Alert Bar: /guardian-ai/{user_id}/predictions returns 200"""
        hr_resp = self.session.get(f"{BASE_URL}/api/guardian-ai/insights/high-risk?limit=1")
        users = hr_resp.json().get("high_risk_users", [])
        if len(users) == 0:
            pytest.skip("No high-risk users available")
        
        user_id = users[0]["user_id"]
        resp = self.session.get(f"{BASE_URL}/api/guardian-ai/{user_id}/predictions")
        assert resp.status_code == 200, f"Predictions API failed: {resp.text}"
    
    def test_predictions_has_predictions_array(self):
        """Predictive Alert Bar: predictions returns predictions array"""
        hr_resp = self.session.get(f"{BASE_URL}/api/guardian-ai/insights/high-risk?limit=1")
        users = hr_resp.json().get("high_risk_users", [])
        if len(users) == 0:
            pytest.skip("No high-risk users available")
        
        user_id = users[0]["user_id"]
        resp = self.session.get(f"{BASE_URL}/api/guardian-ai/{user_id}/predictions")
        data = resp.json()
        assert "predictions" in data, "Missing predictions array"
        assert isinstance(data["predictions"], list), "predictions should be array"


class TestCommandCenterEndpoints:
    """Test Command Center main endpoints"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup: authenticate as admin"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        login_resp = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": "nischint4parents@gmail.com",
            "password": "secret123"
        })
        assert login_resp.status_code == 200
        token = login_resp.json().get("access_token")
        self.session.headers.update({"Authorization": f"Bearer {token}"})
    
    def test_command_center_endpoint_returns_200(self):
        """Command Center: /operator/command-center returns 200"""
        resp = self.session.get(f"{BASE_URL}/api/operator/command-center")
        assert resp.status_code == 200, f"Command center failed: {resp.text}"
    
    def test_command_center_has_active_incidents(self):
        """Command Center: returns active_incidents array"""
        resp = self.session.get(f"{BASE_URL}/api/operator/command-center")
        data = resp.json()
        assert "active_incidents" in data, "Missing active_incidents"
    
    def test_monitoring_metrics_returns_200(self):
        """Command Center Header: /admin/monitoring/metrics returns 200"""
        resp = self.session.get(f"{BASE_URL}/api/admin/monitoring/metrics")
        assert resp.status_code == 200, f"Monitoring metrics failed: {resp.text}"
    
    def test_night_guardian_sessions_returns_200(self):
        """Command Center: /night-guardian/sessions returns 200"""
        resp = self.session.get(f"{BASE_URL}/api/night-guardian/sessions")
        assert resp.status_code == 200, f"Night guardian sessions failed: {resp.text}"
