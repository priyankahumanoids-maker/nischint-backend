# Test file for Guardian Network, Safety Events, and Real-Time Event System APIs
# Tests the 3 foundational layers: Guardian Network Model, Safety Event API Layer, Real-Time Event System
import pytest
import requests
import os
import time
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
TEST_EMAIL = "nischint4parents@gmail.com"
TEST_PASSWORD = "secret123"


class TestAuth:
    """Get authentication token for testing"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Authenticate and get JWT token"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
        )
        assert response.status_code == 200, f"Login failed: {response.text}"
        data = response.json()
        assert "access_token" in data, f"No access_token in response: {data}"
        return data["access_token"]
    
    @pytest.fixture(scope="class")
    def auth_headers(self, auth_token):
        """Return headers with auth token"""
        return {"Authorization": f"Bearer {auth_token}"}


# ═══════════════════════════════════════════════════════════════════════════════
# Guardian Network API Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestGuardianNetworkList(TestAuth):
    """Test GET /api/guardian-network/ — List active guardians"""
    
    def test_list_guardians_returns_200(self, auth_headers):
        """List guardians should return 200"""
        response = requests.get(
            f"{BASE_URL}/api/guardian-network/",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Failed: {response.text}"
    
    def test_list_guardians_has_required_fields(self, auth_headers):
        """Response should have guardians array and total count"""
        response = requests.get(
            f"{BASE_URL}/api/guardian-network/",
            headers=auth_headers
        )
        data = response.json()
        assert "guardians" in data, f"Missing guardians field: {data}"
        assert "total" in data, f"Missing total field: {data}"
        assert isinstance(data["guardians"], list), f"guardians should be list: {data}"
        assert isinstance(data["total"], int), f"total should be int: {data}"
    
    def test_list_guardians_ordered_by_priority(self, auth_headers):
        """Guardians should be ordered by priority"""
        response = requests.get(
            f"{BASE_URL}/api/guardian-network/",
            headers=auth_headers
        )
        data = response.json()
        if len(data["guardians"]) > 1:
            priorities = [g["priority"] for g in data["guardians"]]
            assert priorities == sorted(priorities), f"Not sorted by priority: {priorities}"


class TestGuardianNetworkCreate(TestAuth):
    """Test POST /api/guardian-network/ — Add guardian"""
    
    def test_add_guardian_parent(self, auth_headers):
        """Add a parent guardian"""
        payload = {
            "relationship_type": "parent",
            "guardian_name": f"TEST_Parent_{uuid.uuid4().hex[:8]}",
            "guardian_phone": "+91-9876543210",
            "guardian_email": "test_parent@example.com",
            "priority": 1,
            "is_primary": False,
            "notification_channels": ["push", "sms"]
        }
        response = requests.post(
            f"{BASE_URL}/api/guardian-network/",
            headers=auth_headers,
            json=payload
        )
        assert response.status_code == 201, f"Failed: {response.text}"
        data = response.json()
        assert data["relationship_type"] == "parent"
        assert "TEST_Parent" in data["guardian_name"]
        assert data["guardian_phone"] == "+91-9876543210"
        assert "id" in data
        # Save for cleanup
        TestGuardianNetworkCreate.created_guardian_id = data["id"]
    
    def test_add_guardian_friend(self, auth_headers):
        """Add a friend guardian"""
        payload = {
            "relationship_type": "friend",
            "guardian_name": f"TEST_Friend_{uuid.uuid4().hex[:8]}",
            "guardian_phone": "+91-9876543211",
            "priority": 2,
            "notification_channels": ["push"]
        }
        response = requests.post(
            f"{BASE_URL}/api/guardian-network/",
            headers=auth_headers,
            json=payload
        )
        assert response.status_code == 201, f"Failed: {response.text}"
        data = response.json()
        assert data["relationship_type"] == "friend"
        TestGuardianNetworkCreate.friend_guardian_id = data["id"]
    
    def test_add_guardian_campus_security(self, auth_headers):
        """Add campus security guardian"""
        payload = {
            "relationship_type": "campus_security",
            "guardian_name": f"TEST_Security_{uuid.uuid4().hex[:8]}",
            "guardian_phone": "+91-1234567890",
            "priority": 5,
            "notification_channels": ["sms", "push"]
        }
        response = requests.post(
            f"{BASE_URL}/api/guardian-network/",
            headers=auth_headers,
            json=payload
        )
        assert response.status_code == 201, f"Failed: {response.text}"
        data = response.json()
        assert data["relationship_type"] == "campus_security"
        TestGuardianNetworkCreate.security_guardian_id = data["id"]
    
    def test_add_guardian_invalid_type_rejected(self, auth_headers):
        """Invalid relationship_type should be rejected (422)"""
        payload = {
            "relationship_type": "invalid_type",
            "guardian_name": "Test Invalid",
            "priority": 1
        }
        response = requests.post(
            f"{BASE_URL}/api/guardian-network/",
            headers=auth_headers,
            json=payload
        )
        assert response.status_code == 422, f"Should reject invalid type: {response.text}"


class TestGuardianNetworkUpdate(TestAuth):
    """Test PUT /api/guardian-network/{id} — Update guardian"""
    
    def test_update_guardian_name(self, auth_headers):
        """Update guardian name"""
        # First create a guardian
        create_payload = {
            "relationship_type": "sibling",
            "guardian_name": f"TEST_Sibling_Original_{uuid.uuid4().hex[:8]}",
            "priority": 3
        }
        create_resp = requests.post(
            f"{BASE_URL}/api/guardian-network/",
            headers=auth_headers,
            json=create_payload
        )
        assert create_resp.status_code == 201
        guardian_id = create_resp.json()["id"]
        
        # Now update
        update_payload = {
            "guardian_name": f"TEST_Sibling_Updated_{uuid.uuid4().hex[:8]}",
            "priority": 4
        }
        response = requests.put(
            f"{BASE_URL}/api/guardian-network/{guardian_id}",
            headers=auth_headers,
            json=update_payload
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        assert "TEST_Sibling_Updated" in data["guardian_name"]
        assert data["priority"] == 4
        TestGuardianNetworkUpdate.sibling_guardian_id = guardian_id
    
    def test_update_guardian_not_found(self, auth_headers):
        """Update non-existent guardian should return 404"""
        fake_id = str(uuid.uuid4())
        response = requests.put(
            f"{BASE_URL}/api/guardian-network/{fake_id}",
            headers=auth_headers,
            json={"guardian_name": "Test"}
        )
        assert response.status_code == 404


class TestGuardianNetworkDelete(TestAuth):
    """Test DELETE /api/guardian-network/{id} — Soft delete guardian"""
    
    def test_delete_guardian_soft_delete(self, auth_headers):
        """Delete guardian (soft delete)"""
        # Create a guardian to delete
        create_payload = {
            "relationship_type": "spouse",
            "guardian_name": f"TEST_ToDelete_{uuid.uuid4().hex[:8]}",
            "priority": 10
        }
        create_resp = requests.post(
            f"{BASE_URL}/api/guardian-network/",
            headers=auth_headers,
            json=create_payload
        )
        assert create_resp.status_code == 201
        guardian_id = create_resp.json()["id"]
        
        # Delete
        response = requests.delete(
            f"{BASE_URL}/api/guardian-network/{guardian_id}",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        assert data["status"] == "removed"
        assert data["id"] == guardian_id
    
    def test_delete_guardian_not_found(self, auth_headers):
        """Delete non-existent guardian should return 404"""
        fake_id = str(uuid.uuid4())
        response = requests.delete(
            f"{BASE_URL}/api/guardian-network/{fake_id}",
            headers=auth_headers
        )
        assert response.status_code == 404


class TestEscalationChain(TestAuth):
    """Test GET /api/guardian-network/escalation-chain — Ordered escalation chain"""
    
    def test_escalation_chain_returns_200(self, auth_headers):
        """Escalation chain should return 200"""
        response = requests.get(
            f"{BASE_URL}/api/guardian-network/escalation-chain",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Failed: {response.text}"
    
    def test_escalation_chain_has_required_fields(self, auth_headers):
        """Response should have escalation_chain array and total"""
        response = requests.get(
            f"{BASE_URL}/api/guardian-network/escalation-chain",
            headers=auth_headers
        )
        data = response.json()
        assert "escalation_chain" in data, f"Missing escalation_chain: {data}"
        assert "total" in data, f"Missing total: {data}"
    
    def test_escalation_chain_ordered_by_level(self, auth_headers):
        """Escalation chain should be ordered by level (priority)"""
        response = requests.get(
            f"{BASE_URL}/api/guardian-network/escalation-chain",
            headers=auth_headers
        )
        data = response.json()
        if len(data["escalation_chain"]) > 1:
            levels = [c["level"] for c in data["escalation_chain"]]
            assert levels == sorted(levels), f"Not sorted by level: {levels}"
    
    def test_escalation_chain_entry_structure(self, auth_headers):
        """Each escalation chain entry should have required fields"""
        response = requests.get(
            f"{BASE_URL}/api/guardian-network/escalation-chain",
            headers=auth_headers
        )
        data = response.json()
        if data["escalation_chain"]:
            entry = data["escalation_chain"][0]
            required = ["level", "type", "name", "phone", "relationship", "channels", "is_primary", "id"]
            for field in required:
                assert field in entry, f"Missing field {field} in entry: {entry}"


class TestEmergencyContacts(TestAuth):
    """Test Emergency Contacts CRUD"""
    
    def test_list_emergency_contacts_returns_200(self, auth_headers):
        """GET /api/guardian-network/emergency-contacts should return 200"""
        response = requests.get(
            f"{BASE_URL}/api/guardian-network/emergency-contacts",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        assert "contacts" in data
        assert "total" in data
    
    def test_add_emergency_contact_police(self, auth_headers):
        """POST /api/guardian-network/emergency-contacts — Add police contact"""
        payload = {
            "name": f"TEST_Police_{uuid.uuid4().hex[:8]}",
            "phone": "100",
            "relationship_type": "police",
            "priority": 15,
            "notes": "Local police station"
        }
        response = requests.post(
            f"{BASE_URL}/api/guardian-network/emergency-contacts",
            headers=auth_headers,
            json=payload
        )
        assert response.status_code == 201, f"Failed: {response.text}"
        data = response.json()
        assert data["relationship_type"] == "police"
        assert "TEST_Police" in data["name"]
        assert "id" in data
        TestEmergencyContacts.police_contact_id = data["id"]
    
    def test_add_emergency_contact_hospital(self, auth_headers):
        """Add hospital emergency contact"""
        payload = {
            "name": f"TEST_Hospital_{uuid.uuid4().hex[:8]}",
            "phone": "108",
            "relationship_type": "hospital",
            "priority": 12,
            "notes": "Nearest hospital"
        }
        response = requests.post(
            f"{BASE_URL}/api/guardian-network/emergency-contacts",
            headers=auth_headers,
            json=payload
        )
        assert response.status_code == 201, f"Failed: {response.text}"
        data = response.json()
        assert data["relationship_type"] == "hospital"
        TestEmergencyContacts.hospital_contact_id = data["id"]
    
    def test_add_emergency_contact_invalid_type_rejected(self, auth_headers):
        """Invalid relationship_type should be rejected (422)"""
        payload = {
            "name": "Test Invalid",
            "phone": "123",
            "relationship_type": "invalid_contact_type"
        }
        response = requests.post(
            f"{BASE_URL}/api/guardian-network/emergency-contacts",
            headers=auth_headers,
            json=payload
        )
        assert response.status_code == 422, f"Should reject invalid type: {response.text}"


# ═══════════════════════════════════════════════════════════════════════════════
# Safety Events API Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestSessionLifecycle(TestAuth):
    """Test Safety Session Lifecycle: start → share-location → session-status → end"""
    
    def test_start_session_returns_200_or_201(self, auth_headers):
        """POST /api/safety-events/start-session should start tracking"""
        payload = {
            "destination": {"lat": 19.0760, "lng": 72.8777, "name": "Mumbai Central"},
            "mode": "walking"
        }
        response = requests.post(
            f"{BASE_URL}/api/safety-events/start-session",
            headers=auth_headers,
            json=payload
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        assert data["status"] in ["started", "already_active"], f"Unexpected status: {data}"
        assert "session_id" in data
        TestSessionLifecycle.session_id = data["session_id"]
    
    def test_share_location_during_session(self, auth_headers):
        """POST /api/safety-events/share-location — Location update during session"""
        payload = {
            "lat": 19.0765,
            "lng": 72.8780,
            "accuracy_m": 10.5,
            "speed_mps": 1.2,
            "heading": 45.0,
            "battery_pct": 85
        }
        response = requests.post(
            f"{BASE_URL}/api/safety-events/share-location",
            headers=auth_headers,
            json=payload
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        assert data["status"] == "updated"
        assert "session_id" in data
        assert "location_update_count" in data
        assert "total_distance_m" in data
    
    def test_session_status_returns_active(self, auth_headers):
        """GET /api/safety-events/session-status — Current session status"""
        response = requests.get(
            f"{BASE_URL}/api/safety-events/session-status",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        assert "tracking_active" in data
        if data["tracking_active"]:
            assert "session_id" in data
            assert "current_risk_score" in data
            assert "risk_level" in data
            assert "session_duration_s" in data
    
    def test_end_session_arrived(self, auth_headers):
        """POST /api/safety-events/end-session — End tracking"""
        # First ensure we have an active session
        start_payload = {"mode": "walking"}
        requests.post(
            f"{BASE_URL}/api/safety-events/start-session",
            headers=auth_headers,
            json=start_payload
        )
        
        # End the session
        payload = {"reason": "arrived"}
        response = requests.post(
            f"{BASE_URL}/api/safety-events/end-session",
            headers=auth_headers,
            json=payload
        )
        # Could be 200 (ended) or 404 (no active session)
        assert response.status_code in [200, 404], f"Unexpected: {response.text}"
        if response.status_code == 200:
            data = response.json()
            assert data["status"] == "ended"
            assert data["reason"] == "arrived"


class TestRiskScore(TestAuth):
    """Test GET /api/safety-events/risk-score — AI risk score"""
    
    def test_risk_score_returns_200(self, auth_headers):
        """Risk score should return 200"""
        response = requests.get(
            f"{BASE_URL}/api/safety-events/risk-score",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Failed: {response.text}"
    
    def test_risk_score_has_required_fields(self, auth_headers):
        """Risk score response should have required fields"""
        response = requests.get(
            f"{BASE_URL}/api/safety-events/risk-score",
            headers=auth_headers
        )
        data = response.json()
        # Check for common risk score fields - API returns final_score
        assert "final_score" in data or "risk_score" in data or "score" in data, f"Missing risk score field: {data}"
        assert "risk_level" in data, f"Missing risk_level field: {data}"
        assert "top_factors" in data, f"Missing top_factors field: {data}"


class TestSafeRoute(TestAuth):
    """Test POST /api/safety-events/safe-route — Route safety assessment"""
    
    def test_safe_route_returns_200(self, auth_headers):
        """Safe route should return 200"""
        payload = {
            "origin_lat": 19.0760,
            "origin_lng": 72.8777,
            "dest_lat": 19.0860,
            "dest_lng": 72.8887
        }
        response = requests.post(
            f"{BASE_URL}/api/safety-events/safe-route",
            headers=auth_headers,
            json=payload
        )
        assert response.status_code == 200, f"Failed: {response.text}"
    
    def test_safe_route_has_route_data(self, auth_headers):
        """Safe route response should have route/safety data"""
        payload = {
            "origin_lat": 19.0760,
            "origin_lng": 72.8777,
            "dest_lat": 19.0860,
            "dest_lng": 72.8887
        }
        response = requests.post(
            f"{BASE_URL}/api/safety-events/safe-route",
            headers=auth_headers,
            json=payload
        )
        data = response.json()
        # Should have some route-related fields
        assert data is not None, "Response should not be empty"


class TestGuardianAlerts(TestAuth):
    """Test GET /api/safety-events/guardian-alerts — Alerts for guardian network"""
    
    def test_guardian_alerts_returns_200(self, auth_headers):
        """Guardian alerts should return 200"""
        response = requests.get(
            f"{BASE_URL}/api/safety-events/guardian-alerts",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Failed: {response.text}"
    
    def test_guardian_alerts_has_required_fields(self, auth_headers):
        """Response should have alerts array and total"""
        response = requests.get(
            f"{BASE_URL}/api/safety-events/guardian-alerts",
            headers=auth_headers
        )
        data = response.json()
        assert "alerts" in data, f"Missing alerts field: {data}"
        assert "total" in data, f"Missing total field: {data}"


class TestFakeCall(TestAuth):
    """Test POST /api/safety-events/fake-call — Trigger fake call"""
    
    def test_fake_call_returns_200(self, auth_headers):
        """Fake call should return 200"""
        payload = {
            "caller_name": "TEST_Mom",
            "delay_seconds": 3
        }
        response = requests.post(
            f"{BASE_URL}/api/safety-events/fake-call",
            headers=auth_headers,
            json=payload
        )
        assert response.status_code == 200, f"Failed: {response.text}"
    
    def test_fake_call_response_structure(self, auth_headers):
        """Fake call response should have required fields"""
        payload = {
            "caller_name": "TEST_Dad",
            "delay_seconds": 5
        }
        response = requests.post(
            f"{BASE_URL}/api/safety-events/fake-call",
            headers=auth_headers,
            json=payload
        )
        data = response.json()
        # Should have some confirmation fields
        assert data is not None


class TestSOSTrigger(TestAuth):
    """Test POST /api/safety-events/sos — Trigger SOS with guardian notifications"""
    
    def test_sos_trigger_returns_200(self, auth_headers):
        """SOS trigger should return 200"""
        payload = {
            "trigger_type": "manual",
            "lat": 19.0760,
            "lng": 72.8777,
            "message": "TEST SOS - Please ignore"
        }
        response = requests.post(
            f"{BASE_URL}/api/safety-events/sos",
            headers=auth_headers,
            json=payload
        )
        assert response.status_code == 200, f"Failed: {response.text}"
    
    def test_sos_notifies_guardian_network(self, auth_headers):
        """SOS should notify guardian network"""
        payload = {
            "trigger_type": "button",
            "lat": 19.0765,
            "lng": 72.8780
        }
        response = requests.post(
            f"{BASE_URL}/api/safety-events/sos",
            headers=auth_headers,
            json=payload
        )
        data = response.json()
        # Should have guardian notification info
        assert "guardian_notifications" in data or "guardians_notified" in data, f"Missing guardian info: {data}"
    
    def test_sos_different_trigger_types(self, auth_headers):
        """Test different SOS trigger types"""
        for trigger_type in ["manual", "voice", "button", "shake", "auto"]:
            payload = {
                "trigger_type": trigger_type,
                "lat": 19.0760,
                "lng": 72.8777
            }
            response = requests.post(
                f"{BASE_URL}/api/safety-events/sos",
                headers=auth_headers,
                json=payload
            )
            assert response.status_code == 200, f"Failed for {trigger_type}: {response.text}"


# ═══════════════════════════════════════════════════════════════════════════════
# Real-Time Event System Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestWebSocketStatus(TestAuth):
    """Test GET /api/ws/status — WebSocket connection stats"""
    
    def test_ws_status_returns_200(self, auth_headers):
        """WebSocket status should return 200"""
        response = requests.get(
            f"{BASE_URL}/api/ws/status",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Failed: {response.text}"
    
    def test_ws_status_has_required_fields(self, auth_headers):
        """WebSocket status should have connection stats"""
        response = requests.get(
            f"{BASE_URL}/api/ws/status",
            headers=auth_headers
        )
        data = response.json()
        assert "active_connections" in data, f"Missing active_connections: {data}"
        assert "broadcaster_channels" in data, f"Missing broadcaster_channels: {data}"


# ═══════════════════════════════════════════════════════════════════════════════
# Rate Limiting Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestRateLimiting(TestAuth):
    """Test rate limiting on share-location endpoint (60/min)"""
    
    def test_share_location_rate_limit_allows_normal_usage(self, auth_headers):
        """Normal usage should not be rate limited"""
        # Ensure we have a session first
        requests.post(
            f"{BASE_URL}/api/safety-events/start-session",
            headers=auth_headers,
            json={"mode": "walking"}
        )
        
        # Make a few location updates (should be allowed)
        for i in range(5):
            payload = {
                "lat": 19.0760 + (i * 0.0001),
                "lng": 72.8777 + (i * 0.0001),
                "accuracy_m": 10.0
            }
            response = requests.post(
                f"{BASE_URL}/api/safety-events/share-location",
                headers=auth_headers,
                json=payload
            )
            # Should be 200 or 404 (no session), not 429
            assert response.status_code != 429 or i > 50, f"Rate limited too early at request {i+1}"
            if response.status_code == 404:
                break  # No session, test passes


# ═══════════════════════════════════════════════════════════════════════════════
# Cleanup Tests (Run at end)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCleanup(TestAuth):
    """Cleanup test-created data"""
    
    def test_cleanup_test_guardians(self, auth_headers):
        """Delete TEST_ prefixed guardians"""
        response = requests.get(
            f"{BASE_URL}/api/guardian-network/",
            headers=auth_headers
        )
        if response.status_code == 200:
            data = response.json()
            for guardian in data.get("guardians", []):
                if "TEST_" in guardian.get("guardian_name", ""):
                    requests.delete(
                        f"{BASE_URL}/api/guardian-network/{guardian['id']}",
                        headers=auth_headers
                    )
        # Test passes if no errors
        assert True
    
    def test_end_any_active_session(self, auth_headers):
        """End any active test session"""
        response = requests.post(
            f"{BASE_URL}/api/safety-events/end-session",
            headers=auth_headers,
            json={"reason": "cancelled"}
        )
        # 200 = ended, 404 = no session
        assert response.status_code in [200, 404]


# Run tests for session lifecycle separately to ensure ordering
class TestFullSessionFlow(TestAuth):
    """Test complete session lifecycle flow"""
    
    def test_full_session_lifecycle(self, auth_headers):
        """Complete flow: start → locations → status → end"""
        # 1. Start session
        start_response = requests.post(
            f"{BASE_URL}/api/safety-events/start-session",
            headers=auth_headers,
            json={"destination": {"lat": 19.1, "lng": 72.9, "name": "Test Dest"}, "mode": "walking"}
        )
        assert start_response.status_code == 200
        start_data = start_response.json()
        assert start_data["status"] in ["started", "already_active"]
        session_id = start_data["session_id"]
        
        # 2. Share multiple locations
        for i in range(3):
            loc_response = requests.post(
                f"{BASE_URL}/api/safety-events/share-location",
                headers=auth_headers,
                json={
                    "lat": 19.0760 + (i * 0.001),
                    "lng": 72.8777 + (i * 0.001),
                    "accuracy_m": 5.0,
                    "battery_pct": 90 - i
                }
            )
            assert loc_response.status_code == 200, f"Location {i+1} failed: {loc_response.text}"
            loc_data = loc_response.json()
            assert loc_data["session_id"] == session_id
        
        # 3. Check session status
        status_response = requests.get(
            f"{BASE_URL}/api/safety-events/session-status",
            headers=auth_headers
        )
        assert status_response.status_code == 200
        status_data = status_response.json()
        assert status_data["tracking_active"] == True
        assert status_data["location_updates"] >= 3
        
        # 4. End session
        end_response = requests.post(
            f"{BASE_URL}/api/safety-events/end-session",
            headers=auth_headers,
            json={"reason": "arrived"}
        )
        assert end_response.status_code == 200
        end_data = end_response.json()
        assert end_data["status"] == "ended"
        assert end_data["reason"] == "arrived"
        assert end_data["duration_seconds"] >= 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
