"""
Test for AI Replay Analysis feature - P1 New Feature
Tests backend API endpoints for journey replay analysis
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestReplayAnalysisAPI:
    """AI Replay Analysis API endpoint tests"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup authentication token"""
        login_response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "nischint4parents@gmail.com", "password": "secret123"}
        )
        assert login_response.status_code == 200, f"Login failed: {login_response.text}"
        self.token = login_response.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    # -- Replay Sessions List --
    def test_replay_sessions_list_returns_200(self):
        """Test GET /api/replay/sessions returns 200"""
        response = requests.get(f"{BASE_URL}/api/replay/sessions", headers=self.headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    
    def test_replay_sessions_list_has_sessions_array(self):
        """Test sessions list has sessions array"""
        response = requests.get(f"{BASE_URL}/api/replay/sessions?limit=5", headers=self.headers)
        data = response.json()
        assert "sessions" in data, "Response should have 'sessions' key"
        assert isinstance(data["sessions"], list), "Sessions should be a list"
    
    def test_replay_session_item_has_required_fields(self):
        """Test session list items have required fields"""
        response = requests.get(f"{BASE_URL}/api/replay/sessions?limit=5", headers=self.headers)
        data = response.json()
        if data["sessions"]:
            session = data["sessions"][0]
            required_fields = ["id", "user_id", "user_name", "status", "risk_level", "started_at"]
            for field in required_fields:
                assert field in session, f"Session should have '{field}' field"
    
    # -- Replay Detail --
    def test_replay_detail_returns_200_for_valid_session(self):
        """Test GET /api/replay/{session_id} returns 200"""
        # First get a session
        list_response = requests.get(f"{BASE_URL}/api/replay/sessions?limit=1", headers=self.headers)
        sessions = list_response.json().get("sessions", [])
        if not sessions:
            pytest.skip("No sessions available for testing")
        
        session_id = sessions[0]["id"]
        response = requests.get(f"{BASE_URL}/api/replay/{session_id}", headers=self.headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    
    def test_replay_detail_has_events_array(self):
        """Test replay detail has events array"""
        list_response = requests.get(f"{BASE_URL}/api/replay/sessions?limit=1", headers=self.headers)
        sessions = list_response.json().get("sessions", [])
        if not sessions:
            pytest.skip("No sessions available")
        
        session_id = sessions[0]["id"]
        response = requests.get(f"{BASE_URL}/api/replay/{session_id}", headers=self.headers)
        data = response.json()
        assert "events" in data, "Response should have 'events' key"
        assert isinstance(data["events"], list), "Events should be a list"
    
    def test_replay_detail_returns_404_for_invalid_session(self):
        """Test GET /api/replay/{invalid_id} returns 404"""
        response = requests.get(f"{BASE_URL}/api/replay/00000000-0000-0000-0000-000000000000", headers=self.headers)
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
    
    # -- AI Analysis Endpoint (P1 New Feature) --
    def test_analysis_endpoint_returns_200(self):
        """Test GET /api/replay/{session_id}/analysis returns 200"""
        list_response = requests.get(f"{BASE_URL}/api/replay/sessions?limit=1", headers=self.headers)
        sessions = list_response.json().get("sessions", [])
        if not sessions:
            pytest.skip("No sessions available")
        
        session_id = sessions[0]["id"]
        response = requests.get(f"{BASE_URL}/api/replay/{session_id}/analysis", headers=self.headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    
    def test_analysis_has_risk_analysis_structure(self):
        """Test analysis response has risk_analysis with required fields"""
        list_response = requests.get(f"{BASE_URL}/api/replay/sessions?limit=1", headers=self.headers)
        sessions = list_response.json().get("sessions", [])
        if not sessions:
            pytest.skip("No sessions available")
        
        session_id = sessions[0]["id"]
        response = requests.get(f"{BASE_URL}/api/replay/{session_id}/analysis", headers=self.headers)
        data = response.json()
        
        assert "risk_analysis" in data, "Response should have 'risk_analysis'"
        risk = data["risk_analysis"]
        
        # Check required risk_analysis fields
        assert "peak_score" in risk, "risk_analysis should have 'peak_score'"
        assert "peak_level" in risk, "risk_analysis should have 'peak_level'"
        assert "peak_factors" in risk, "risk_analysis should have 'peak_factors'"
        assert "risk_timeline" in risk, "risk_analysis should have 'risk_timeline'"
        assert "session_risk_level" in risk, "risk_analysis should have 'session_risk_level'"
    
    def test_analysis_has_response_times_structure(self):
        """Test analysis response has response_times with required fields"""
        list_response = requests.get(f"{BASE_URL}/api/replay/sessions?limit=1", headers=self.headers)
        sessions = list_response.json().get("sessions", [])
        if not sessions:
            pytest.skip("No sessions available")
        
        session_id = sessions[0]["id"]
        response = requests.get(f"{BASE_URL}/api/replay/{session_id}/analysis", headers=self.headers)
        data = response.json()
        
        assert "response_times" in data, "Response should have 'response_times'"
        resp = data["response_times"]
        
        # Check required response_times fields
        assert "incidents_count" in resp, "response_times should have 'incidents_count'"
        assert "avg_acknowledgement_s" in resp, "response_times should have 'avg_acknowledgement_s'"
        assert "avg_dispatch_s" in resp, "response_times should have 'avg_dispatch_s'"
        assert "avg_resolution_s" in resp, "response_times should have 'avg_resolution_s'"
        assert "incidents" in resp, "response_times should have 'incidents'"
    
    def test_analysis_has_preventable_moments(self):
        """Test analysis response has preventable_moments array"""
        list_response = requests.get(f"{BASE_URL}/api/replay/sessions?limit=1", headers=self.headers)
        sessions = list_response.json().get("sessions", [])
        if not sessions:
            pytest.skip("No sessions available")
        
        session_id = sessions[0]["id"]
        response = requests.get(f"{BASE_URL}/api/replay/{session_id}/analysis", headers=self.headers)
        data = response.json()
        
        assert "preventable_moments" in data, "Response should have 'preventable_moments'"
        assert isinstance(data["preventable_moments"], list), "preventable_moments should be a list"
    
    def test_analysis_has_recommendations(self):
        """Test analysis response has recommendations array"""
        list_response = requests.get(f"{BASE_URL}/api/replay/sessions?limit=1", headers=self.headers)
        sessions = list_response.json().get("sessions", [])
        if not sessions:
            pytest.skip("No sessions available")
        
        session_id = sessions[0]["id"]
        response = requests.get(f"{BASE_URL}/api/replay/{session_id}/analysis", headers=self.headers)
        data = response.json()
        
        assert "recommendations" in data, "Response should have 'recommendations'"
        assert isinstance(data["recommendations"], list), "recommendations should be a list"
        # Should always have at least one recommendation
        assert len(data["recommendations"]) >= 1, "Should have at least one recommendation"
    
    def test_analysis_has_session_metadata(self):
        """Test analysis response has session metadata fields"""
        list_response = requests.get(f"{BASE_URL}/api/replay/sessions?limit=1", headers=self.headers)
        sessions = list_response.json().get("sessions", [])
        if not sessions:
            pytest.skip("No sessions available")
        
        session_id = sessions[0]["id"]
        response = requests.get(f"{BASE_URL}/api/replay/{session_id}/analysis", headers=self.headers)
        data = response.json()
        
        assert "session_id" in data, "Response should have 'session_id'"
        assert "user_id" in data, "Response should have 'user_id'"
        assert "duration_seconds" in data, "Response should have 'duration_seconds'"
        assert data["session_id"] == session_id, "session_id should match request"
    
    def test_analysis_returns_404_for_invalid_session(self):
        """Test GET /api/replay/{invalid_id}/analysis returns 404"""
        response = requests.get(f"{BASE_URL}/api/replay/00000000-0000-0000-0000-000000000000/analysis", headers=self.headers)
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
    
    def test_analysis_peak_score_is_numeric(self):
        """Test that peak_score is a valid numeric value"""
        list_response = requests.get(f"{BASE_URL}/api/replay/sessions?limit=1", headers=self.headers)
        sessions = list_response.json().get("sessions", [])
        if not sessions:
            pytest.skip("No sessions available")
        
        session_id = sessions[0]["id"]
        response = requests.get(f"{BASE_URL}/api/replay/{session_id}/analysis", headers=self.headers)
        data = response.json()
        
        peak_score = data["risk_analysis"]["peak_score"]
        assert isinstance(peak_score, (int, float)), f"peak_score should be numeric, got {type(peak_score)}"
        assert 0 <= peak_score <= 10, f"peak_score should be 0-10, got {peak_score}"


class TestReplayAnalysisWithDifferentSessions:
    """Test analysis with different session types"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup authentication token"""
        login_response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "nischint4parents@gmail.com", "password": "secret123"}
        )
        assert login_response.status_code == 200, f"Login failed: {login_response.text}"
        self.token = login_response.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_analysis_for_high_risk_session(self):
        """Test analysis for HIGH risk sessions"""
        list_response = requests.get(f"{BASE_URL}/api/replay/sessions?limit=30", headers=self.headers)
        sessions = list_response.json().get("sessions", [])
        
        high_risk_sessions = [s for s in sessions if s.get("risk_level") == "HIGH"]
        if not high_risk_sessions:
            pytest.skip("No HIGH risk sessions available")
        
        session_id = high_risk_sessions[0]["id"]
        response = requests.get(f"{BASE_URL}/api/replay/{session_id}/analysis", headers=self.headers)
        assert response.status_code == 200
        
        data = response.json()
        assert data["risk_analysis"]["session_risk_level"] == "HIGH", "Session risk level should be HIGH"
    
    def test_analysis_for_safe_session(self):
        """Test analysis for SAFE sessions"""
        list_response = requests.get(f"{BASE_URL}/api/replay/sessions?limit=30", headers=self.headers)
        sessions = list_response.json().get("sessions", [])
        
        safe_sessions = [s for s in sessions if s.get("risk_level") == "SAFE"]
        if not safe_sessions:
            pytest.skip("No SAFE sessions available")
        
        session_id = safe_sessions[0]["id"]
        response = requests.get(f"{BASE_URL}/api/replay/{session_id}/analysis", headers=self.headers)
        assert response.status_code == 200
        
        data = response.json()
        assert data["risk_analysis"]["session_risk_level"] == "SAFE", "Session risk level should be SAFE"
