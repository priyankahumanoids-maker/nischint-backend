# Guardian Mode API Tests - Phase 36
# Tests guardian contacts CRUD, session lifecycle, location updates, zone escalation, session history

import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"
GUARDIAN_EMAIL = "nischint4parents@gmail.com"
GUARDIAN_PASSWORD = "secret123"

# Test coordinates
START_LAT = 12.971
START_LNG = 77.594
DEST_LAT = 12.935
DEST_LNG = 77.624
HIGH_ZONE_LAT = 12.972
HIGH_ZONE_LNG = 77.587


class TestGuardianModeAuth:
    """Test authentication requirements for Guardian Mode endpoints"""
    
    def test_list_guardians_requires_auth(self):
        """GET /guardian/list without token returns 401/403"""
        response = requests.get(f"{BASE_URL}/api/guardian/list")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("PASS: list_guardians requires auth")
    
    def test_add_guardian_requires_auth(self):
        """POST /guardian/add without token returns 401/403"""
        response = requests.post(f"{BASE_URL}/api/guardian/add", json={
            "name": "Test Guardian", "relationship": "friend"
        })
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("PASS: add_guardian requires auth")
    
    def test_start_session_requires_auth(self):
        """POST /guardian/start without token returns 401/403"""
        response = requests.post(f"{BASE_URL}/api/guardian/start", json={
            "location": {"lat": START_LAT, "lng": START_LNG}
        })
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("PASS: start_session requires auth")
    
    def test_active_sessions_requires_auth(self):
        """GET /guardian/sessions/active without token returns 401/403"""
        response = requests.get(f"{BASE_URL}/api/guardian/sessions/active")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("PASS: active_sessions requires auth")


class TestGuardianModeCRUD:
    """Test Guardian contact CRUD operations"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Login and get token for operator"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD
        })
        assert response.status_code == 200, f"Login failed: {response.text}"
        self.token = response.json().get("access_token")
        self.headers = {"Authorization": f"Bearer {self.token}"}
        print(f"Setup: Logged in as {OPERATOR_EMAIL}")
    
    def test_list_guardians(self):
        """GET /guardian/list returns guardians array"""
        response = requests.get(f"{BASE_URL}/api/guardian/list", headers=self.headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "guardians" in data, "Response missing 'guardians' key"
        assert isinstance(data["guardians"], list), "guardians should be a list"
        print(f"PASS: list_guardians returned {len(data['guardians'])} guardians")
    
    def test_add_guardian_full_data(self):
        """POST /guardian/add creates guardian with all fields"""
        test_name = f"TEST_Guardian_{int(time.time())}"
        payload = {
            "name": test_name,
            "phone": "+91-9876543210",
            "email": "test@example.com",
            "relationship": "friend"
        }
        response = requests.post(f"{BASE_URL}/api/guardian/add", json=payload, headers=self.headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Validate response structure
        assert "id" in data, "Response missing 'id'"
        assert data["name"] == test_name, f"Name mismatch: {data.get('name')}"
        assert data["phone"] == "+91-9876543210", f"Phone mismatch: {data.get('phone')}"
        assert data["email"] == "test@example.com", f"Email mismatch: {data.get('email')}"
        assert data["relationship"] == "friend", f"Relationship mismatch: {data.get('relationship')}"
        assert data.get("is_active") == True, "Guardian should be active"
        
        # Store for cleanup
        self._created_guardian_id = data["id"]
        print(f"PASS: add_guardian created guardian with id={data['id']}")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/guardian/remove/{data['id']}", headers=self.headers)
    
    def test_add_guardian_minimal_data(self):
        """POST /guardian/add works with only name"""
        test_name = f"TEST_MinimalGuardian_{int(time.time())}"
        payload = {"name": test_name, "relationship": "family"}
        response = requests.post(f"{BASE_URL}/api/guardian/add", json=payload, headers=self.headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert data["name"] == test_name
        assert data["relationship"] == "family"
        print(f"PASS: add_guardian with minimal data works")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/guardian/remove/{data['id']}", headers=self.headers)
    
    def test_remove_guardian(self):
        """DELETE /guardian/remove/{id} deactivates guardian"""
        # First create a guardian
        test_name = f"TEST_ToRemove_{int(time.time())}"
        create_resp = requests.post(f"{BASE_URL}/api/guardian/add", json={
            "name": test_name, "relationship": "family"
        }, headers=self.headers)
        assert create_resp.status_code == 200
        guardian_id = create_resp.json()["id"]
        
        # Now remove it
        response = requests.delete(f"{BASE_URL}/api/guardian/remove/{guardian_id}", headers=self.headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data.get("removed") == True, "Response should confirm removal"
        assert data.get("guardian_id") == guardian_id
        print(f"PASS: remove_guardian deactivated guardian {guardian_id}")
    
    def test_remove_nonexistent_guardian(self):
        """DELETE /guardian/remove/{id} returns 404 for invalid id"""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = requests.delete(f"{BASE_URL}/api/guardian/remove/{fake_id}", headers=self.headers)
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("PASS: remove_guardian returns 404 for nonexistent")


class TestGuardianModeSession:
    """Test session lifecycle: start, status, update-location, stop"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Login and get token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD
        })
        assert response.status_code == 200
        self.token = response.json().get("access_token")
        self.headers = {"Authorization": f"Bearer {self.token}"}
        self.session_id = None
    
    def teardown_method(self, method):
        """Stop any active session after each test"""
        if self.session_id:
            requests.post(f"{BASE_URL}/api/guardian/stop?session_id={self.session_id}", headers=self.headers)
    
    def test_start_session_basic(self):
        """POST /guardian/start creates session with initial zone check"""
        payload = {
            "location": {"lat": START_LAT, "lng": START_LNG}
        }
        response = requests.post(f"{BASE_URL}/api/guardian/start", json=payload, headers=self.headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Validate response
        assert "session_id" in data, "Response missing session_id"
        assert data.get("status") == "active", "Session should be active"
        assert "user_id" in data, "Response missing user_id"
        assert "started_at" in data, "Response missing started_at"
        assert "initial_zone" in data, "Response missing initial_zone"
        assert "guardians_notified" in data, "Response missing guardians_notified"
        
        # Validate initial_zone structure
        zone = data["initial_zone"]
        assert "risk_level" in zone, "Zone missing risk_level"
        assert "risk_score" in zone, "Zone missing risk_score"
        
        self.session_id = data["session_id"]
        print(f"PASS: start_session created session {self.session_id}, notified {data['guardians_notified']} guardians")
    
    def test_start_session_with_destination(self):
        """POST /guardian/start with destination for ETA tracking"""
        payload = {
            "location": {"lat": START_LAT, "lng": START_LNG},
            "destination": {"lat": DEST_LAT, "lng": DEST_LNG}
        }
        response = requests.post(f"{BASE_URL}/api/guardian/start", json=payload, headers=self.headers)
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("destination") is not None, "Destination should be set"
        assert data["destination"]["lat"] == DEST_LAT
        assert data["destination"]["lng"] == DEST_LNG
        
        self.session_id = data["session_id"]
        print(f"PASS: start_session with destination works")
    
    def test_get_session(self):
        """GET /guardian/session/{id} returns full session state"""
        # Start a session first
        start_resp = requests.post(f"{BASE_URL}/api/guardian/start", json={
            "location": {"lat": START_LAT, "lng": START_LNG}
        }, headers=self.headers)
        assert start_resp.status_code == 200
        self.session_id = start_resp.json()["session_id"]
        
        # Get session status
        response = requests.get(f"{BASE_URL}/api/guardian/session/{self.session_id}", headers=self.headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        # Validate fields
        assert data["session_id"] == self.session_id
        assert data["status"] == "active"
        assert "current_location" in data
        assert "risk_level" in data
        assert "risk_score" in data
        assert "duration_minutes" in data
        assert "speed_mps" in data
        assert "total_distance_m" in data
        assert "location_updates" in data
        assert "escalation_level" in data
        assert "alerts" in data
        
        print(f"PASS: get_session returns full state with {len(data.get('alerts', []))} alerts")
    
    def test_get_session_invalid(self):
        """GET /guardian/session/{id} returns 404 for invalid id"""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = requests.get(f"{BASE_URL}/api/guardian/session/{fake_id}", headers=self.headers)
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("PASS: get_session returns 404 for invalid id")
    
    def test_stop_session(self):
        """POST /guardian/stop ends session with summary"""
        # Start a session first
        start_resp = requests.post(f"{BASE_URL}/api/guardian/start", json={
            "location": {"lat": START_LAT, "lng": START_LNG}
        }, headers=self.headers)
        session_id = start_resp.json()["session_id"]
        
        # Stop it
        response = requests.post(f"{BASE_URL}/api/guardian/stop?session_id={session_id}", headers=self.headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert data.get("status") == "ended", "Status should be ended"
        assert "duration_minutes" in data, "Response missing duration"
        assert "total_distance_m" in data, "Response missing distance"
        assert "location_updates" in data, "Response missing location_updates"
        assert "alerts_triggered" in data, "Response missing alerts_triggered"
        assert "final_zone" in data, "Response missing final_zone"
        
        print(f"PASS: stop_session ended with duration={data['duration_minutes']}min, alerts={data['alerts_triggered']}")
    
    def test_stop_session_invalid(self):
        """POST /guardian/stop with invalid session returns 404"""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = requests.post(f"{BASE_URL}/api/guardian/stop?session_id={fake_id}", headers=self.headers)
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("PASS: stop_session returns 404 for invalid id")


class TestGuardianModeLocationUpdate:
    """Test location updates and zone escalation"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Login and start a session for testing"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD
        })
        assert response.status_code == 200
        self.token = response.json().get("access_token")
        self.headers = {"Authorization": f"Bearer {self.token}"}
        
        # Start a session
        start_resp = requests.post(f"{BASE_URL}/api/guardian/start", json={
            "location": {"lat": START_LAT, "lng": START_LNG},
            "destination": {"lat": DEST_LAT, "lng": DEST_LNG}
        }, headers=self.headers)
        assert start_resp.status_code == 200
        self.session_id = start_resp.json()["session_id"]
    
    def teardown_method(self, method):
        """Stop session after test"""
        if self.session_id:
            requests.post(f"{BASE_URL}/api/guardian/stop?session_id={self.session_id}", headers=self.headers)
    
    def test_update_location_basic(self):
        """POST /guardian/update-location processes movement"""
        # Move slightly from starting position
        new_lat = START_LAT + 0.001
        new_lng = START_LNG + 0.001
        
        payload = {
            "session_id": self.session_id,
            "location": {"lat": new_lat, "lng": new_lng}
        }
        response = requests.post(f"{BASE_URL}/api/guardian/update-location", json=payload, headers=self.headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Validate response
        assert data["session_id"] == self.session_id
        assert "location" in data
        assert "zone" in data
        assert "speed_mps" in data
        assert "escalation_level" in data
        assert "alerts" in data
        assert "alert_count" in data
        assert "timestamp" in data
        
        print(f"PASS: update_location processed, speed={data['speed_mps']:.2f}m/s, alerts={data['alert_count']}")
    
    def test_update_location_with_timestamp(self):
        """POST /guardian/update-location accepts custom timestamp"""
        from datetime import datetime, timezone
        
        ts = datetime.now(timezone.utc).isoformat()
        payload = {
            "session_id": self.session_id,
            "location": {"lat": START_LAT + 0.002, "lng": START_LNG + 0.002},
            "timestamp": ts
        }
        response = requests.post(f"{BASE_URL}/api/guardian/update-location", json=payload, headers=self.headers)
        assert response.status_code == 200
        print("PASS: update_location accepts custom timestamp")
    
    def test_update_location_invalid_session(self):
        """POST /guardian/update-location returns 404 for invalid session"""
        fake_id = "00000000-0000-0000-0000-000000000000"
        payload = {
            "session_id": fake_id,
            "location": {"lat": START_LAT, "lng": START_LNG}
        }
        response = requests.post(f"{BASE_URL}/api/guardian/update-location", json=payload, headers=self.headers)
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("PASS: update_location returns 404 for invalid session")
    
    def test_zone_escalation(self):
        """Location update to HIGH zone triggers alert"""
        # First update to safe area
        requests.post(f"{BASE_URL}/api/guardian/update-location", json={
            "session_id": self.session_id,
            "location": {"lat": START_LAT, "lng": START_LNG}
        }, headers=self.headers)
        
        # Move to HIGH risk zone
        response = requests.post(f"{BASE_URL}/api/guardian/update-location", json={
            "session_id": self.session_id,
            "location": {"lat": HIGH_ZONE_LAT, "lng": HIGH_ZONE_LNG}
        }, headers=self.headers)
        assert response.status_code == 200
        data = response.json()
        
        # Check zone info
        assert "zone" in data
        zone = data["zone"]
        assert "risk_level" in zone
        assert "risk_score" in zone
        assert "zone_name" in zone
        
        print(f"PASS: zone_escalation - risk_level={zone['risk_level']}, score={zone['risk_score']}")


class TestGuardianModeAcknowledgeSafety:
    """Test safety acknowledgement"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Login and start session"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD
        })
        assert response.status_code == 200
        self.token = response.json().get("access_token")
        self.headers = {"Authorization": f"Bearer {self.token}"}
        
        # Start a session
        start_resp = requests.post(f"{BASE_URL}/api/guardian/start", json={
            "location": {"lat": START_LAT, "lng": START_LNG}
        }, headers=self.headers)
        self.session_id = start_resp.json()["session_id"]
    
    def teardown_method(self, method):
        if self.session_id:
            requests.post(f"{BASE_URL}/api/guardian/stop?session_id={self.session_id}", headers=self.headers)
    
    def test_acknowledge_safety(self):
        """POST /guardian/acknowledge-safety clears safety check"""
        response = requests.post(
            f"{BASE_URL}/api/guardian/acknowledge-safety?session_id={self.session_id}", 
            headers=self.headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert data.get("acknowledged") == True
        assert data.get("session_id") == self.session_id
        print("PASS: acknowledge_safety works")


class TestGuardianModeHistory:
    """Test session history endpoints"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Login"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD
        })
        self.token = response.json().get("access_token")
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_get_user_history(self):
        """GET /guardian/sessions/history returns user's sessions"""
        response = requests.get(f"{BASE_URL}/api/guardian/sessions/history", headers=self.headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        assert "sessions" in data
        sessions = data["sessions"]
        assert isinstance(sessions, list)
        
        if sessions:
            session = sessions[0]
            assert "session_id" in session
            assert "status" in session
            assert "started_at" in session
            assert "duration_minutes" in session
            assert "risk_level" in session
        
        print(f"PASS: get_user_history returned {len(sessions)} sessions")


class TestGuardianModeActiveSessionsOperator:
    """Test active sessions endpoint (operator-only)"""
    
    def test_operator_can_list_active_sessions(self):
        """GET /guardian/sessions/active works for operator"""
        # Login as operator
        login_resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD
        })
        token = login_resp.json().get("access_token")
        headers = {"Authorization": f"Bearer {token}"}
        
        response = requests.get(f"{BASE_URL}/api/guardian/sessions/active", headers=headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        assert "sessions" in data
        sessions = data["sessions"]
        assert isinstance(sessions, list)
        
        if sessions:
            session = sessions[0]
            assert "session_id" in session
            assert "user_id" in session
            assert "risk_level" in session
            assert "duration_minutes" in session
        
        print(f"PASS: operator can list {len(sessions)} active sessions")
    
    def test_guardian_cannot_list_active_sessions(self):
        """GET /guardian/sessions/active returns 403 for non-operator"""
        # Login as guardian
        login_resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": GUARDIAN_EMAIL, "password": GUARDIAN_PASSWORD
        })
        token = login_resp.json().get("access_token")
        headers = {"Authorization": f"Bearer {token}"}
        
        response = requests.get(f"{BASE_URL}/api/guardian/sessions/active", headers=headers)
        assert response.status_code == 403, f"Expected 403, got {response.status_code}"
        print("PASS: guardian gets 403 for active sessions (operator-only)")


class TestGuardianModePersistence:
    """Test data persistence across operations"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Login"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD
        })
        self.token = response.json().get("access_token")
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_guardian_persists_after_creation(self):
        """Created guardian appears in list"""
        # Create guardian
        test_name = f"TEST_PersistGuardian_{int(time.time())}"
        create_resp = requests.post(f"{BASE_URL}/api/guardian/add", json={
            "name": test_name, "relationship": "family"
        }, headers=self.headers)
        assert create_resp.status_code == 200
        guardian_id = create_resp.json()["id"]
        
        # Verify in list
        list_resp = requests.get(f"{BASE_URL}/api/guardian/list", headers=self.headers)
        assert list_resp.status_code == 200
        guardians = list_resp.json()["guardians"]
        
        found = any(g["id"] == guardian_id for g in guardians)
        assert found, f"Guardian {guardian_id} not found in list"
        print(f"PASS: guardian persists after creation (found in list)")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/guardian/remove/{guardian_id}", headers=self.headers)
    
    def test_session_appears_in_history(self):
        """Ended session appears in history"""
        # Start and immediately stop a session
        start_resp = requests.post(f"{BASE_URL}/api/guardian/start", json={
            "location": {"lat": START_LAT, "lng": START_LNG}
        }, headers=self.headers)
        session_id = start_resp.json()["session_id"]
        
        # Stop it
        stop_resp = requests.post(f"{BASE_URL}/api/guardian/stop?session_id={session_id}", headers=self.headers)
        assert stop_resp.status_code == 200
        
        # Check history
        history_resp = requests.get(f"{BASE_URL}/api/guardian/sessions/history", headers=self.headers)
        assert history_resp.status_code == 200
        sessions = history_resp.json()["sessions"]
        
        found = any(s["session_id"] == session_id for s in sessions)
        assert found, f"Session {session_id} not found in history"
        
        # Verify status is ended
        session = next(s for s in sessions if s["session_id"] == session_id)
        assert session["status"] == "ended"
        
        print("PASS: ended session appears in history with status=ended")


class TestGuardianModeFullFlow:
    """End-to-end flow test"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Login"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD
        })
        self.token = response.json().get("access_token")
        self.headers = {"Authorization": f"Bearer {self.token}"}
        self.session_id = None
        self.guardian_id = None
    
    def teardown_method(self, method):
        """Cleanup"""
        if self.session_id:
            requests.post(f"{BASE_URL}/api/guardian/stop?session_id={self.session_id}", headers=self.headers)
        if self.guardian_id:
            requests.delete(f"{BASE_URL}/api/guardian/remove/{self.guardian_id}", headers=self.headers)
    
    def test_full_guardian_flow(self):
        """Test complete flow: add guardian -> start session -> update locations -> stop"""
        print("\n=== Starting Full Guardian Mode Flow Test ===")
        
        # Step 1: Add guardian
        guardian_name = f"TEST_FullFlow_{int(time.time())}"
        add_resp = requests.post(f"{BASE_URL}/api/guardian/add", json={
            "name": guardian_name, "phone": "+91-1234567890", "relationship": "family"
        }, headers=self.headers)
        assert add_resp.status_code == 200
        self.guardian_id = add_resp.json()["id"]
        print(f"Step 1: Added guardian '{guardian_name}'")
        
        # Step 2: Verify guardian in list
        list_resp = requests.get(f"{BASE_URL}/api/guardian/list", headers=self.headers)
        guardians = list_resp.json()["guardians"]
        guardian_count = len(guardians)
        print(f"Step 2: Guardian list has {guardian_count} guardians")
        
        # Step 3: Start session
        start_resp = requests.post(f"{BASE_URL}/api/guardian/start", json={
            "location": {"lat": START_LAT, "lng": START_LNG},
            "destination": {"lat": DEST_LAT, "lng": DEST_LNG}
        }, headers=self.headers)
        assert start_resp.status_code == 200
        start_data = start_resp.json()
        self.session_id = start_data["session_id"]
        assert start_data["guardians_notified"] >= 1, "Should notify at least 1 guardian"
        print(f"Step 3: Started session, notified {start_data['guardians_notified']} guardians")
        
        # Step 4: Update location (simulate movement)
        total_steps = 5
        for i in range(total_steps):
            progress = (i + 1) / total_steps
            new_lat = START_LAT + (DEST_LAT - START_LAT) * progress
            new_lng = START_LNG + (DEST_LNG - START_LNG) * progress
            
            update_resp = requests.post(f"{BASE_URL}/api/guardian/update-location", json={
                "session_id": self.session_id,
                "location": {"lat": new_lat, "lng": new_lng}
            }, headers=self.headers)
            assert update_resp.status_code == 200
            update_data = update_resp.json()
            print(f"Step 4.{i+1}: Location updated, risk={update_data['zone']['risk_level']}, alerts={update_data['alert_count']}")
            time.sleep(0.2)  # Small delay between updates
        
        # Step 5: Get session status
        status_resp = requests.get(f"{BASE_URL}/api/guardian/session/{self.session_id}", headers=self.headers)
        assert status_resp.status_code == 200
        status_data = status_resp.json()
        print(f"Step 5: Session status - updates={status_data['location_updates']}, distance={status_data['total_distance_m']:.1f}m")
        
        # Step 6: Stop session
        stop_resp = requests.post(f"{BASE_URL}/api/guardian/stop?session_id={self.session_id}", headers=self.headers)
        assert stop_resp.status_code == 200
        stop_data = stop_resp.json()
        print(f"Step 6: Session stopped - duration={stop_data['duration_minutes']}min, alerts={stop_data['alerts_triggered']}")
        
        # Step 7: Verify in history
        history_resp = requests.get(f"{BASE_URL}/api/guardian/sessions/history", headers=self.headers)
        sessions = history_resp.json()["sessions"]
        found = any(s["session_id"] == self.session_id for s in sessions)
        assert found, "Session should appear in history"
        print(f"Step 7: Session found in history with {len(sessions)} total sessions")
        
        # Step 8: Remove guardian
        remove_resp = requests.delete(f"{BASE_URL}/api/guardian/remove/{self.guardian_id}", headers=self.headers)
        assert remove_resp.status_code == 200
        print(f"Step 8: Guardian removed")
        
        self.session_id = None
        self.guardian_id = None
        print("=== Full Guardian Mode Flow Test PASSED ===\n")
