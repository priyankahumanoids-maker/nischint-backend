"""
Backend API tests for Threat Assessment feature
Tests GET /api/guardian-ai/insights/threat-assessment endpoint
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestThreatAssessmentAuth:
    """Test authentication for threat assessment endpoint"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup auth token for all tests"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        # Login as admin
        login_res = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": "nischint4parents@gmail.com",
            "password": "secret123"
        })
        assert login_res.status_code == 200, f"Login failed: {login_res.text}"
        token = login_res.json().get("access_token")
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    def test_threat_assessment_returns_200(self):
        """Test threat-assessment endpoint returns 200"""
        res = self.session.get(f"{BASE_URL}/api/guardian-ai/insights/threat-assessment")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"

    def test_threat_assessment_has_threat_level(self):
        """Test response includes threat_level field"""
        res = self.session.get(f"{BASE_URL}/api/guardian-ai/insights/threat-assessment")
        data = res.json()
        assert "threat_level" in data, "Missing threat_level field"
        assert data["threat_level"] in ["SAFE", "MODERATE", "HIGH", "CRITICAL"], f"Invalid threat level: {data['threat_level']}"

    def test_threat_assessment_has_summary(self):
        """Test response includes summary field (GPT or fallback narrative)"""
        res = self.session.get(f"{BASE_URL}/api/guardian-ai/insights/threat-assessment")
        data = res.json()
        assert "summary" in data, "Missing summary field"
        assert isinstance(data["summary"], str), "summary should be a string"
        assert len(data["summary"]) > 10, "summary should not be empty"

    def test_threat_assessment_has_zones_escalating(self):
        """Test response includes zones_escalating count"""
        res = self.session.get(f"{BASE_URL}/api/guardian-ai/insights/threat-assessment")
        data = res.json()
        assert "zones_escalating" in data, "Missing zones_escalating field"
        assert isinstance(data["zones_escalating"], int), "zones_escalating should be an integer"
        assert data["zones_escalating"] >= 0, "zones_escalating should be non-negative"

    def test_threat_assessment_has_users_anomaly(self):
        """Test response includes users_anomaly count"""
        res = self.session.get(f"{BASE_URL}/api/guardian-ai/insights/threat-assessment")
        data = res.json()
        assert "users_anomaly" in data, "Missing users_anomaly field"
        assert isinstance(data["users_anomaly"], int), "users_anomaly should be an integer"
        assert data["users_anomaly"] >= 0, "users_anomaly should be non-negative"

    def test_threat_assessment_has_top_zone(self):
        """Test response includes top_zone field"""
        res = self.session.get(f"{BASE_URL}/api/guardian-ai/insights/threat-assessment")
        data = res.json()
        assert "top_zone" in data, "Missing top_zone field"
        assert isinstance(data["top_zone"], str), "top_zone should be a string"

    def test_threat_assessment_has_recent_incidents(self):
        """Test response includes recent_incidents count"""
        res = self.session.get(f"{BASE_URL}/api/guardian-ai/insights/threat-assessment")
        data = res.json()
        assert "recent_incidents" in data, "Missing recent_incidents field"
        assert isinstance(data["recent_incidents"], int), "recent_incidents should be an integer"
        assert data["recent_incidents"] >= 0, "recent_incidents should be non-negative"

    def test_threat_assessment_has_recommended_action(self):
        """Test response includes recommended_action field"""
        res = self.session.get(f"{BASE_URL}/api/guardian-ai/insights/threat-assessment")
        data = res.json()
        assert "recommended_action" in data, "Missing recommended_action field"
        assert isinstance(data["recommended_action"], str), "recommended_action should be a string"
        assert len(data["recommended_action"]) > 10, "recommended_action should not be empty"

    def test_threat_assessment_has_generated_at(self):
        """Test response includes generated_at timestamp"""
        res = self.session.get(f"{BASE_URL}/api/guardian-ai/insights/threat-assessment")
        data = res.json()
        assert "generated_at" in data, "Missing generated_at field"
        assert isinstance(data["generated_at"], str), "generated_at should be a string"
        # Should be ISO format
        assert "T" in data["generated_at"], "generated_at should be ISO format"


class TestThreatAssessmentCaching:
    """Test caching behavior for threat assessment endpoint"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup auth token for all tests"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        # Login as admin
        login_res = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": "nischint4parents@gmail.com",
            "password": "secret123"
        })
        assert login_res.status_code == 200, f"Login failed: {login_res.text}"
        token = login_res.json().get("access_token")
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    def test_threat_assessment_caches_results(self):
        """Test that endpoint returns cached results within TTL (60 seconds)"""
        # Make first request
        res1 = self.session.get(f"{BASE_URL}/api/guardian-ai/insights/threat-assessment")
        assert res1.status_code == 200
        data1 = res1.json()
        generated_at_1 = data1.get("generated_at")
        
        # Wait 2 seconds and make second request
        time.sleep(2)
        res2 = self.session.get(f"{BASE_URL}/api/guardian-ai/insights/threat-assessment")
        assert res2.status_code == 200
        data2 = res2.json()
        generated_at_2 = data2.get("generated_at")
        
        # Should return same cached result (same timestamp)
        assert generated_at_1 == generated_at_2, f"Expected cached result but got different timestamps: {generated_at_1} vs {generated_at_2}"


class TestThreatAssessmentStructure:
    """Test complete response structure"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup auth token for all tests"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        # Login as admin
        login_res = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": "nischint4parents@gmail.com",
            "password": "secret123"
        })
        assert login_res.status_code == 200, f"Login failed: {login_res.text}"
        token = login_res.json().get("access_token")
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    def test_threat_assessment_complete_structure(self):
        """Test complete response has all required fields"""
        res = self.session.get(f"{BASE_URL}/api/guardian-ai/insights/threat-assessment")
        assert res.status_code == 200
        data = res.json()
        
        required_fields = [
            "threat_level", "summary", "zones_escalating", 
            "users_anomaly", "top_zone", "recent_incidents",
            "recommended_action", "generated_at"
        ]
        
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        
        print(f"\n=== Threat Assessment Response ===")
        print(f"Threat Level: {data['threat_level']}")
        print(f"Zones Escalating: {data['zones_escalating']}")
        print(f"Users Anomaly: {data['users_anomaly']}")
        print(f"Top Zone: {data['top_zone']}")
        print(f"Recent Incidents: {data['recent_incidents']}")
        print(f"Summary: {data['summary'][:100]}...")
        print(f"Recommended Action: {data['recommended_action']}")
        print(f"Generated At: {data['generated_at']}")


class TestThreatAssessmentRecommendedAction:
    """Test recommended action logic based on threat level"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup auth token for all tests"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        # Login as admin
        login_res = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": "nischint4parents@gmail.com",
            "password": "secret123"
        })
        assert login_res.status_code == 200, f"Login failed: {login_res.text}"
        token = login_res.json().get("access_token")
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    def test_recommended_action_matches_threat_level(self):
        """Test recommended action is appropriate for threat level"""
        res = self.session.get(f"{BASE_URL}/api/guardian-ai/insights/threat-assessment")
        assert res.status_code == 200
        data = res.json()
        
        threat_level = data.get("threat_level")
        rec_action = data.get("recommended_action", "")
        
        if threat_level == "CRITICAL":
            assert "Immediate patrol" in rec_action or "immediate" in rec_action.lower(), \
                f"CRITICAL level should have immediate action: {rec_action}"
        elif threat_level == "HIGH":
            assert "Increase patrol" in rec_action or "Notify" in rec_action, \
                f"HIGH level should mention increased patrol: {rec_action}"
        elif threat_level == "MODERATE":
            assert "Monitor" in rec_action or "Standard patrol" in rec_action, \
                f"MODERATE level should mention monitoring: {rec_action}"
        elif threat_level == "SAFE":
            assert "normal" in rec_action.lower() or "standard" in rec_action.lower() or "continue" in rec_action.lower(), \
                f"SAFE level should indicate normal operations: {rec_action}"


class TestThreatAssessmentUnauthorized:
    """Test unauthorized access"""
    
    def test_threat_assessment_requires_auth(self):
        """Test endpoint requires authentication"""
        session = requests.Session()
        session.headers.update({"Content-Type": "application/json"})
        res = session.get(f"{BASE_URL}/api/guardian-ai/insights/threat-assessment")
        # Should return 401 or 403
        assert res.status_code in [401, 403], f"Expected 401/403 without auth, got {res.status_code}"
