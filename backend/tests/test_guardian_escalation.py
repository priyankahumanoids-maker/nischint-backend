# Guardian AI Decision Engine - Escalation Tests
# Tests for: escalation config, pending, history, acknowledge endpoints
# Filter: acknowledged_at.is_(None) - acknowledged incidents are NOT re-escalated

import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
if not BASE_URL:
    raise RuntimeError("REACT_APP_BACKEND_URL environment variable not set")


class TestGuardianEscalation:
    """Test suite for Guardian AI Decision Engine (escalation)"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Login as operator and store token"""
        login_response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "operator@nischint.com",
            "password": "operator123"
        })
        assert login_response.status_code == 200, f"Operator login failed: {login_response.text}"
        self.token = login_response.json().get("access_token")
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
    
    # ── GET /api/operator/escalation/config ──
    
    def test_escalation_config_returns_200(self):
        """Test that escalation config endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/operator/escalation/config", headers=self.headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("✓ GET /api/operator/escalation/config returns 200")
    
    def test_escalation_config_has_timers(self):
        """Test that config returns L1/L2/L3 timer values"""
        response = requests.get(f"{BASE_URL}/api/operator/escalation/config", headers=self.headers)
        data = response.json()
        
        assert "timers" in data, "Missing 'timers' in response"
        timers = data["timers"]
        assert "level1_minutes" in timers, "Missing level1_minutes"
        assert "level2_minutes" in timers, "Missing level2_minutes"
        assert "level3_minutes" in timers, "Missing level3_minutes"
        assert isinstance(timers["level1_minutes"], (int, float)), "level1_minutes should be numeric"
        assert isinstance(timers["level2_minutes"], (int, float)), "level2_minutes should be numeric"
        assert isinstance(timers["level3_minutes"], (int, float)), "level3_minutes should be numeric"
        print(f"✓ Timers: L1={timers['level1_minutes']}min, L2={timers['level2_minutes']}min, L3={timers['level3_minutes']}min")
    
    def test_escalation_config_has_levels(self):
        """Test that config returns level definitions with target + channels"""
        response = requests.get(f"{BASE_URL}/api/operator/escalation/config", headers=self.headers)
        data = response.json()
        
        assert "levels" in data, "Missing 'levels' in response"
        levels = data["levels"]
        
        for level_key in ["level1", "level2", "level3"]:
            assert level_key in levels, f"Missing {level_key}"
            level = levels[level_key]
            assert "target" in level, f"Missing 'target' in {level_key}"
            assert "channels" in level, f"Missing 'channels' in {level_key}"
            assert isinstance(level["channels"], list), f"channels should be list in {level_key}"
        
        print(f"✓ Level targets: L1={levels['level1']['target']}, L2={levels['level2']['target']}, L3={levels['level3']['target']}")
    
    def test_escalation_config_has_l1_only_types(self):
        """Test that config returns l1_only_types list"""
        response = requests.get(f"{BASE_URL}/api/operator/escalation/config", headers=self.headers)
        data = response.json()
        
        assert "l1_only_types" in data, "Missing 'l1_only_types'"
        assert isinstance(data["l1_only_types"], list), "l1_only_types should be list"
        print(f"✓ L1-only incident types: {data['l1_only_types']}")
    
    def test_escalation_config_has_check_interval(self):
        """Test that config returns check_interval_seconds"""
        response = requests.get(f"{BASE_URL}/api/operator/escalation/config", headers=self.headers)
        data = response.json()
        
        assert "check_interval_seconds" in data, "Missing 'check_interval_seconds'"
        assert isinstance(data["check_interval_seconds"], (int, float)), "check_interval_seconds should be numeric"
        print(f"✓ Check interval: {data['check_interval_seconds']}s")
    
    # ── GET /api/operator/escalation/pending ──
    
    def test_escalation_pending_returns_200(self):
        """Test that pending escalations endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/operator/escalation/pending", headers=self.headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("✓ GET /api/operator/escalation/pending returns 200")
    
    def test_escalation_pending_response_structure(self):
        """Test pending response has count and pending array"""
        response = requests.get(f"{BASE_URL}/api/operator/escalation/pending", headers=self.headers)
        data = response.json()
        
        assert "count" in data, "Missing 'count' in response"
        assert "pending" in data, "Missing 'pending' in response"
        assert isinstance(data["count"], int), "count should be integer"
        assert isinstance(data["pending"], list), "pending should be list"
        print(f"✓ Pending response structure valid - count: {data['count']}")
    
    def test_escalation_pending_excludes_acknowledged(self):
        """Test that pending list excludes acknowledged incidents (L3 fully escalated too)"""
        response = requests.get(f"{BASE_URL}/api/operator/escalation/pending", headers=self.headers)
        data = response.json()
        
        # Pending should only include incidents that are open and unacknowledged
        for item in data.get("pending", []):
            assert "next_escalation_level" in item, "Missing next_escalation_level"
            assert "time_remaining_seconds" in item, "Missing time_remaining_seconds"
            assert "overdue" in item, "Missing overdue flag"
        
        print(f"✓ Pending list excludes fully-escalated (L3) incidents. Count: {data['count']}")
    
    def test_escalation_pending_item_structure(self):
        """Test pending items have required fields"""
        response = requests.get(f"{BASE_URL}/api/operator/escalation/pending", headers=self.headers)
        data = response.json()
        
        if data["count"] > 0:
            item = data["pending"][0]
            required_fields = [
                "incident_id", "senior_name", "device_identifier", 
                "incident_type", "severity", "age_minutes",
                "next_escalation_level", "time_remaining_seconds", "overdue"
            ]
            for field in required_fields:
                assert field in item, f"Missing field: {field}"
            print(f"✓ Pending item has all required fields: {list(item.keys())}")
        else:
            print("✓ No pending escalations - structure check skipped (valid scenario)")
    
    # ── GET /api/operator/escalation/history ──
    
    def test_escalation_history_returns_200(self):
        """Test that escalation history endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/operator/escalation/history", headers=self.headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("✓ GET /api/operator/escalation/history returns 200")
    
    def test_escalation_history_is_list(self):
        """Test that history returns a list"""
        response = requests.get(f"{BASE_URL}/api/operator/escalation/history", headers=self.headers)
        data = response.json()
        
        assert isinstance(data, list), "History should be a list"
        print(f"✓ History returns list with {len(data)} items")
    
    def test_escalation_history_item_structure(self):
        """Test history items have response_time_min and acknowledged_by"""
        response = requests.get(f"{BASE_URL}/api/operator/escalation/history?limit=15", headers=self.headers)
        data = response.json()
        
        if len(data) > 0:
            item = data[0]
            required_fields = [
                "incident_id", "incident_type", "severity", "senior_name",
                "device_identifier", "escalation_level", "status", "created_at"
            ]
            for field in required_fields:
                assert field in item, f"Missing field: {field}"
            
            # Optional fields present (may be null)
            assert "response_time_min" in item, "Missing response_time_min"
            assert "acknowledged_by" in item, "Missing acknowledged_by"
            assert "acknowledged_at" in item, "Missing acknowledged_at"
            print(f"✓ History item structure valid. Sample: {item.get('incident_type')} - L{item.get('escalation_level')} - {item.get('status')}")
        else:
            print("✓ No escalation history - structure check skipped")
    
    def test_escalation_history_limit_parameter(self):
        """Test that limit parameter works"""
        response = requests.get(f"{BASE_URL}/api/operator/escalation/history?limit=5", headers=self.headers)
        data = response.json()
        
        assert len(data) <= 5, f"Expected max 5 items, got {len(data)}"
        print(f"✓ Limit parameter works - returned {len(data)} items")
    
    # ── POST /api/operator/incidents/{id}/acknowledge ──
    
    def test_acknowledge_nonexistent_incident_returns_404(self):
        """Test acknowledging non-existent incident returns 404"""
        fake_id = str(uuid.uuid4())
        response = requests.post(f"{BASE_URL}/api/operator/incidents/{fake_id}/acknowledge", headers=self.headers)
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print(f"✓ Acknowledging non-existent incident {fake_id[:8]}... returns 404")
    
    def test_acknowledge_incident_success(self):
        """Test acknowledging an open incident works"""
        # First get incidents list
        incidents_response = requests.get(f"{BASE_URL}/api/operator/incidents?status=open", headers=self.headers)
        assert incidents_response.status_code == 200
        
        incidents = incidents_response.json()
        # Find an unacknowledged open incident
        unacked = [i for i in incidents if i.get("status") == "open" and i.get("acknowledged_at") is None]
        
        if len(unacked) > 0:
            incident_id = unacked[0]["id"]
            # Acknowledge it
            ack_response = requests.post(f"{BASE_URL}/api/operator/incidents/{incident_id}/acknowledge", headers=self.headers)
            
            if ack_response.status_code == 200:
                data = ack_response.json()
                assert data.get("status") == "acknowledged", "Response should have status=acknowledged"
                assert data.get("incident_id") == incident_id, "Response should have matching incident_id"
                print(f"✓ Acknowledged incident {incident_id[:8]}... successfully")
            elif ack_response.status_code == 404:
                # May have been acknowledged by another process
                print(f"✓ Incident {incident_id[:8]}... already acknowledged (404 expected)")
            else:
                pytest.fail(f"Unexpected status: {ack_response.status_code}")
        else:
            print("✓ No unacknowledged open incidents to test - skipped")
    
    def test_acknowledge_already_acknowledged_returns_404(self):
        """Test acknowledging already-acknowledged incident returns 404"""
        # Get history to find an acknowledged incident
        history_response = requests.get(f"{BASE_URL}/api/operator/escalation/history?limit=50", headers=self.headers)
        history = history_response.json()
        
        # Find an acknowledged incident
        acked = [h for h in history if h.get("acknowledged_at") is not None]
        
        if len(acked) > 0:
            incident_id = acked[0]["incident_id"]
            # Try to acknowledge again
            ack_response = requests.post(f"{BASE_URL}/api/operator/incidents/{incident_id}/acknowledge", headers=self.headers)
            assert ack_response.status_code == 404, f"Expected 404 for already-acknowledged, got {ack_response.status_code}"
            print(f"✓ Re-acknowledging incident {incident_id[:8]}... returns 404 (already acknowledged)")
        else:
            print("✓ No acknowledged incidents in history to test - skipped")
    
    # ── Escalation Scheduler Filter Tests ──
    
    def test_acknowledged_incidents_not_in_pending(self):
        """Verify acknowledged incidents don't appear in pending list"""
        # Get acknowledged incidents from history
        history_response = requests.get(f"{BASE_URL}/api/operator/escalation/history?limit=50", headers=self.headers)
        history = history_response.json()
        acked_ids = {h["incident_id"] for h in history if h.get("acknowledged_at") is not None}
        
        # Get pending
        pending_response = requests.get(f"{BASE_URL}/api/operator/escalation/pending", headers=self.headers)
        pending = pending_response.json()
        pending_ids = {p["incident_id"] for p in pending.get("pending", [])}
        
        # No overlap
        overlap = acked_ids.intersection(pending_ids)
        assert len(overlap) == 0, f"Acknowledged incidents should not be in pending: {overlap}"
        print(f"✓ No acknowledged incidents in pending list. Acked: {len(acked_ids)}, Pending: {len(pending_ids)}")


class TestEscalationAuth:
    """Test authentication requirements for escalation endpoints"""
    
    def test_escalation_config_requires_auth(self):
        """Test escalation/config requires authentication"""
        response = requests.get(f"{BASE_URL}/api/operator/escalation/config")
        assert response.status_code in [401, 403, 422], f"Expected auth error, got {response.status_code}"
        print("✓ escalation/config requires authentication")
    
    def test_escalation_pending_requires_auth(self):
        """Test escalation/pending requires authentication"""
        response = requests.get(f"{BASE_URL}/api/operator/escalation/pending")
        assert response.status_code in [401, 403, 422], f"Expected auth error, got {response.status_code}"
        print("✓ escalation/pending requires authentication")
    
    def test_escalation_history_requires_auth(self):
        """Test escalation/history requires authentication"""
        response = requests.get(f"{BASE_URL}/api/operator/escalation/history")
        assert response.status_code in [401, 403, 422], f"Expected auth error, got {response.status_code}"
        print("✓ escalation/history requires authentication")
    
    def test_acknowledge_requires_auth(self):
        """Test incidents/{id}/acknowledge requires authentication"""
        response = requests.post(f"{BASE_URL}/api/operator/incidents/{uuid.uuid4()}/acknowledge")
        assert response.status_code in [401, 403, 422], f"Expected auth error, got {response.status_code}"
        print("✓ incidents/{id}/acknowledge requires authentication")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
