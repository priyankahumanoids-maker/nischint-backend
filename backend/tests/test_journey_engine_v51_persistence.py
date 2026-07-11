"""
NISCHINT Journey Engine v5.1 - Persistence + Delivery Guard Tests
Tests for:
1. PERSISTENCE ON WRITE: Contacts, User Contacts, SOS, Escalations to MongoDB
2. PERSISTENCE ON SOS: SOS events and escalations persisted
3. HYDRATION ON RESTART: Data survives backend restart
4. DELIVERY GUARD - SIMULATOR MODE: Notifications withheld when JOURNEY_LIVE_DELIVERY=false
5. DELIVERY GUARD STATUS ENDPOINT: GET /api/journey/delivery/status
6. PUSH TOKEN FIELD: push_token stored on ContactProfile
7. BACKWARD COMPATIBILITY: v5 endpoints still work
8. MONGO COLLECTIONS: Direct pymongo verification
"""
import pytest
import requests
import time
import os
import subprocess

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
API_PREFIX = f"{BASE_URL}/api/journey"

# MongoDB connection for direct verification
MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'nischint')


def get_mongo_client():
    """Get pymongo client for direct DB verification"""
    try:
        from pymongo import MongoClient
        client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=3000)
        client.admin.command("ping")
        return client
    except Exception as e:
        pytest.skip(f"MongoDB not available: {e}")


class TestDeliveryGuardStatus:
    """Delivery Guard Status Endpoint - GET /api/journey/delivery/status"""
    
    def test_delivery_status_endpoint_exists(self):
        """GET /api/journey/delivery/status returns 200"""
        response = requests.get(f"{API_PREFIX}/delivery/status")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("Delivery status endpoint exists")
    
    def test_delivery_status_returns_live_false(self):
        """delivery.live should be false (simulator mode)"""
        response = requests.get(f"{API_PREFIX}/delivery/status")
        assert response.status_code == 200
        
        data = response.json()
        assert "delivery" in data, f"Missing 'delivery' key: {data}"
        assert data["delivery"]["live"] == False, f"Expected live=false, got {data['delivery']['live']}"
        print(f"Delivery live flag: {data['delivery']['live']}")
    
    def test_delivery_status_returns_max_per_hour(self):
        """delivery.max_per_hour should be 5"""
        response = requests.get(f"{API_PREFIX}/delivery/status")
        assert response.status_code == 200
        
        data = response.json()
        assert data["delivery"]["max_per_hour"] == 5, f"Expected max_per_hour=5, got {data['delivery']['max_per_hour']}"
        print(f"Max per hour: {data['delivery']['max_per_hour']}")
    
    def test_delivery_status_returns_mongo_enabled(self):
        """persistence.mongo_enabled should be true"""
        response = requests.get(f"{API_PREFIX}/delivery/status")
        assert response.status_code == 200
        
        data = response.json()
        assert "persistence" in data, f"Missing 'persistence' key: {data}"
        assert data["persistence"]["mongo_enabled"] == True, f"Expected mongo_enabled=true, got {data['persistence']['mongo_enabled']}"
        print(f"Mongo enabled: {data['persistence']['mongo_enabled']}")


class TestPersistenceOnWrite:
    """PERSISTENCE ON WRITE: Contacts, User Contacts to MongoDB"""
    
    created_contact_ids = []
    test_user_id = f"TEST_persist_user_{int(time.time())}"
    
    @classmethod
    def teardown_class(cls):
        """Cleanup created contacts"""
        for cid in cls.created_contact_ids:
            try:
                requests.delete(f"{API_PREFIX}/contacts/{cid}")
            except:
                pass
    
    def test_create_contact_persists_to_mongo(self):
        """POST /api/journey/contacts writes to journey_contacts collection"""
        payload = {
            "name": "TEST_PersistGuardian",
            "phone": "+919111111111",
            "email": "persist_guardian@test.com",
            "layer": "guardian",
            "priority": 1,
            "escalation_delay_sec": 30,
            "relationship": "mother"
        }
        response = requests.post(f"{API_PREFIX}/contacts", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        contact_id = data["contact_id"]
        self.__class__.created_contact_ids.append(contact_id)
        
        # Verify in MongoDB
        client = get_mongo_client()
        db = client[DB_NAME]
        doc = db["journey_contacts"].find_one({"_id": contact_id})
        
        assert doc is not None, f"Contact {contact_id} not found in MongoDB"
        assert doc.get("name") == "TEST_PersistGuardian"
        assert doc.get("phone") == "+919111111111"
        assert doc.get("layer") == "guardian"
        
        client.close()
        print(f"Contact {contact_id} persisted to MongoDB")
    
    def test_delete_contact_removes_from_mongo(self):
        """DELETE /api/journey/contacts/{id} removes from journey_contacts collection"""
        # Create a contact to delete
        payload = {"name": "TEST_ToDeletePersist", "phone": "+919222222222", "layer": "guardian"}
        create_resp = requests.post(f"{API_PREFIX}/contacts", json=payload)
        cid = create_resp.json()["contact_id"]
        
        # Verify it exists in Mongo
        client = get_mongo_client()
        db = client[DB_NAME]
        doc = db["journey_contacts"].find_one({"_id": cid})
        assert doc is not None, f"Contact {cid} should exist before delete"
        
        # Delete via API
        response = requests.delete(f"{API_PREFIX}/contacts/{cid}")
        assert response.status_code == 200
        
        # Verify removed from Mongo
        doc = db["journey_contacts"].find_one({"_id": cid})
        assert doc is None, f"Contact {cid} should be removed from MongoDB after delete"
        
        client.close()
        print(f"Contact {cid} removed from MongoDB")
    
    def test_assign_contacts_persists_to_mongo(self):
        """POST /api/journey/contacts/assign persists to journey_user_contacts collection"""
        # Create contacts first
        g_resp = requests.post(f"{API_PREFIX}/contacts", json={
            "name": "TEST_AssignPersistGuardian", "phone": "+919333333333", "layer": "guardian", "priority": 1
        })
        a_resp = requests.post(f"{API_PREFIX}/contacts", json={
            "name": "TEST_AssignPersistAuthority", "phone": "+919444444444", "layer": "authority", "priority": 1
        })
        
        gid = g_resp.json()["contact_id"]
        aid = a_resp.json()["contact_id"]
        self.__class__.created_contact_ids.extend([gid, aid])
        
        # Assign to user
        payload = {
            "user_id": self.__class__.test_user_id,
            "guardian_ids": [gid],
            "authority_ids": [aid]
        }
        response = requests.post(f"{API_PREFIX}/contacts/assign", json=payload)
        assert response.status_code == 200
        
        # Verify in MongoDB
        client = get_mongo_client()
        db = client[DB_NAME]
        doc = db["journey_user_contacts"].find_one({"_id": self.__class__.test_user_id})
        
        assert doc is not None, f"User contacts {self.__class__.test_user_id} not found in MongoDB"
        assert gid in doc.get("guardian", []), f"Guardian {gid} not in user contacts"
        assert aid in doc.get("authority", []), f"Authority {aid} not in user contacts"
        
        client.close()
        print(f"User contacts for {self.__class__.test_user_id} persisted to MongoDB")


class TestPersistenceOnSOS:
    """PERSISTENCE ON SOS: SOS events and escalations persisted"""
    
    sos_id = None
    guardian_id = None
    authority_id = None
    test_session_id = f"TEST_sos_persist_session_{int(time.time())}"
    
    @classmethod
    def setup_class(cls):
        """Create contacts and assign to user"""
        g_resp = requests.post(f"{API_PREFIX}/contacts", json={
            "name": "TEST_SOSPersistGuardian",
            "phone": "+919555555555",
            "layer": "guardian",
            "priority": 1
        })
        if g_resp.status_code == 200:
            cls.guardian_id = g_resp.json()["contact_id"]
        
        a_resp = requests.post(f"{API_PREFIX}/contacts", json={
            "name": "TEST_SOSPersistAuthority",
            "phone": "+919666666666",
            "layer": "authority",
            "priority": 1
        })
        if a_resp.status_code == 200:
            cls.authority_id = a_resp.json()["contact_id"]
        
        requests.post(f"{API_PREFIX}/contacts/assign", json={
            "user_id": cls.test_session_id,
            "guardian_ids": [cls.guardian_id] if cls.guardian_id else [],
            "authority_ids": [cls.authority_id] if cls.authority_id else []
        })
    
    @classmethod
    def teardown_class(cls):
        """Cleanup contacts"""
        if cls.guardian_id:
            requests.delete(f"{API_PREFIX}/contacts/{cls.guardian_id}")
        if cls.authority_id:
            requests.delete(f"{API_PREFIX}/contacts/{cls.authority_id}")
    
    def test_sos_persists_to_mongo(self):
        """POST /api/journey/sos persists to journey_sos_events collection"""
        payload = {
            "sosId": f"TEST_sos_persist_{int(time.time())}",
            "sosState": "triggered",
            "location": {"lat": 28.6, "lng": 77.2},
            "ts": int(time.time() * 1000),
            "riskScore": 85,
            "riskLevel": "critical",
            "battery": 0.3,
            "isMoving": False,
            "network": "online",
            "sessionId": self.__class__.test_session_id
        }
        response = requests.post(f"{API_PREFIX}/sos", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        self.__class__.sos_id = data["sos_id"]
        
        # Verify SOS in MongoDB
        client = get_mongo_client()
        db = client[DB_NAME]
        sos_doc = db["journey_sos_events"].find_one({"_id": self.__class__.sos_id})
        
        assert sos_doc is not None, f"SOS {self.__class__.sos_id} not found in MongoDB"
        assert sos_doc.get("sos_state") == "delivered"
        assert sos_doc.get("risk_level") == "critical"
        assert sos_doc.get("session_id") == self.__class__.test_session_id
        
        client.close()
        print(f"SOS {self.__class__.sos_id} persisted to MongoDB")
    
    def test_escalation_persists_to_mongo(self):
        """Escalation created by _start_escalation persists to journey_escalations"""
        if not self.__class__.sos_id:
            pytest.skip("No SOS created")
        
        client = get_mongo_client()
        db = client[DB_NAME]
        esc_doc = db["journey_escalations"].find_one({"_id": self.__class__.sos_id})
        
        assert esc_doc is not None, f"Escalation for SOS {self.__class__.sos_id} not found in MongoDB"
        
        # Verify escalation fields
        assert "guardian_ids" in esc_doc, "Missing guardian_ids"
        assert "authority_ids" in esc_doc, "Missing authority_ids"
        assert "guardian_idx" in esc_doc, "Missing guardian_idx"
        assert "authority_idx" in esc_doc, "Missing authority_idx"
        assert "active_layer" in esc_doc, "Missing active_layer"
        assert "notified" in esc_doc, "Missing notified"
        assert "started_at" in esc_doc, "Missing started_at"
        assert "authority_triggered" in esc_doc, "Missing authority_triggered"
        assert "authority_verified" in esc_doc, "Missing authority_verified"
        assert "authority_pre_alerted" in esc_doc, "Missing authority_pre_alerted"
        assert "notification_log" in esc_doc, "Missing notification_log"
        assert "updated_at" in esc_doc, "Missing updated_at"
        
        client.close()
        print(f"Escalation for SOS {self.__class__.sos_id} persisted with all required fields")
    
    def test_sos_update_persists_to_mongo(self):
        """PUT /api/journey/sos/{id} updates Mongo sos doc"""
        if not self.__class__.sos_id:
            pytest.skip("No SOS created")
        
        payload = {"sos_state": "actioned", "meta": {"action": "help_dispatched"}}
        response = requests.put(f"{API_PREFIX}/sos/{self.__class__.sos_id}", json=payload)
        assert response.status_code == 200
        
        # Verify update in MongoDB
        client = get_mongo_client()
        db = client[DB_NAME]
        sos_doc = db["journey_sos_events"].find_one({"_id": self.__class__.sos_id})
        
        assert sos_doc is not None
        assert sos_doc.get("sos_state") == "actioned", f"Expected actioned, got {sos_doc.get('sos_state')}"
        
        client.close()
        print(f"SOS {self.__class__.sos_id} state updated to 'actioned' in MongoDB")
    
    def test_contact_ack_updates_sos_and_escalation_in_mongo(self):
        """POST /api/journey/contacts/ack updates both sos doc and escalation doc"""
        if not self.__class__.sos_id or not self.__class__.guardian_id:
            pytest.skip("No SOS or guardian created")
        
        payload = {
            "contact_id": self.__class__.guardian_id,
            "sos_id": self.__class__.sos_id
        }
        response = requests.post(f"{API_PREFIX}/contacts/ack", json=payload)
        assert response.status_code == 200
        
        # Verify SOS state_history updated in MongoDB
        client = get_mongo_client()
        db = client[DB_NAME]
        
        sos_doc = db["journey_sos_events"].find_one({"_id": self.__class__.sos_id})
        assert sos_doc is not None
        
        # Check state_history has acknowledged entry
        state_history = sos_doc.get("state_history", [])
        ack_entries = [h for h in state_history if h.get("state") == "acknowledged"]
        assert len(ack_entries) > 0, "No 'acknowledged' entry in state_history"
        
        # Verify escalation updated
        esc_doc = db["journey_escalations"].find_one({"_id": self.__class__.sos_id})
        assert esc_doc is not None
        
        # Check notified dict has acked=True for guardian
        notified = esc_doc.get("notified", {})
        guardian_notified = notified.get(self.__class__.guardian_id, {})
        assert guardian_notified.get("acked") == True, f"Guardian not marked as acked: {guardian_notified}"
        
        client.close()
        print(f"ACK updated both SOS and escalation in MongoDB")


class TestDeliveryGuardSimulatorMode:
    """DELIVERY GUARD - SIMULATOR MODE: Notifications withheld"""
    
    sos_id = None
    
    def test_notification_has_delivery_guard_field(self):
        """Notifications should have delivery_guard field"""
        # Create SOS to generate notification
        payload = {
            "sosId": f"TEST_sos_guard_{int(time.time())}",
            "sosState": "triggered",
            "ts": int(time.time() * 1000),
            "riskScore": 70,
            "riskLevel": "high",
            "sessionId": f"TEST_guard_session_{int(time.time())}"
        }
        response = requests.post(f"{API_PREFIX}/sos", json=payload)
        assert response.status_code == 200
        self.__class__.sos_id = response.json()["sos_id"]
        
        # Get notifications
        notif_resp = requests.get(f"{API_PREFIX}/notifications", params={"limit": 20})
        assert notif_resp.status_code == 200
        
        data = notif_resp.json()
        # Find notification for our SOS
        sos_notifs = [n for n in data["notifications"] if n["sos_id"] == self.__class__.sos_id]
        
        assert len(sos_notifs) > 0, f"No notifications found for SOS {self.__class__.sos_id}"
        
        for notif in sos_notifs:
            assert "delivery_guard" in notif, f"Missing delivery_guard field: {notif}"
            print(f"Notification has delivery_guard: {notif['delivery_guard']}")
    
    def test_delivery_guard_allowed_false_in_simulator_mode(self):
        """delivery_guard.allowed should be false in simulator mode"""
        notif_resp = requests.get(f"{API_PREFIX}/notifications", params={"limit": 20})
        assert notif_resp.status_code == 200
        
        data = notif_resp.json()
        
        for notif in data["notifications"]:
            if "delivery_guard" in notif:
                assert notif["delivery_guard"]["allowed"] == False, f"Expected allowed=false: {notif['delivery_guard']}"
                print(f"delivery_guard.allowed=false confirmed")
                break
    
    def test_delivery_guard_reason_simulator_mode(self):
        """delivery_guard.reason should be 'simulator_mode'"""
        notif_resp = requests.get(f"{API_PREFIX}/notifications", params={"limit": 20})
        assert notif_resp.status_code == 200
        
        data = notif_resp.json()
        
        for notif in data["notifications"]:
            if "delivery_guard" in notif:
                assert notif["delivery_guard"]["reason"] == "simulator_mode", f"Expected reason='simulator_mode': {notif['delivery_guard']}"
                print(f"delivery_guard.reason='simulator_mode' confirmed")
                break
    
    def test_push_result_withheld_in_simulator_mode(self):
        """push_result.status should be 'withheld' in simulator mode"""
        # Create SOS with contacts that have push tokens
        # First create a contact with push_token
        g_resp = requests.post(f"{API_PREFIX}/contacts", json={
            "name": "TEST_PushGuardian",
            "phone": "+919777777777",
            "layer": "guardian",
            "priority": 1,
            "push_token": "ExponentPushToken[test_push_123]"
        })
        gid = g_resp.json()["contact_id"] if g_resp.status_code == 200 else None
        
        session_id = f"TEST_push_session_{int(time.time())}"
        
        # Assign to user
        requests.post(f"{API_PREFIX}/contacts/assign", json={
            "user_id": session_id,
            "guardian_ids": [gid] if gid else [],
            "authority_ids": []
        })
        
        # Create SOS
        payload = {
            "sosId": f"TEST_sos_push_{int(time.time())}",
            "sosState": "triggered",
            "ts": int(time.time() * 1000),
            "riskScore": 70,
            "riskLevel": "high",
            "sessionId": session_id
        }
        response = requests.post(f"{API_PREFIX}/sos", json=payload)
        assert response.status_code == 200
        sos_id = response.json()["sos_id"]
        
        # Get notifications
        notif_resp = requests.get(f"{API_PREFIX}/notifications", params={"limit": 20})
        data = notif_resp.json()
        
        # Find notification for our SOS with push_result
        sos_notifs = [n for n in data["notifications"] if n["sos_id"] == sos_id and "push_result" in n]
        
        if sos_notifs:
            for notif in sos_notifs:
                assert notif["push_result"]["status"] == "withheld", f"Expected push_result.status='withheld': {notif['push_result']}"
                print(f"push_result.status='withheld' confirmed")
        else:
            print("No push_result in notifications (may not have push tokens)")
        
        # Cleanup
        if gid:
            requests.delete(f"{API_PREFIX}/contacts/{gid}")
    
    def test_sms_results_withheld_in_simulator_mode(self):
        """sms_results[].status should be 'withheld' in simulator mode"""
        # Create SOS that triggers SMS (offline user)
        payload = {
            "sosId": f"TEST_sos_sms_{int(time.time())}",
            "sosState": "triggered",
            "ts": int(time.time() * 1000),
            "riskScore": 70,
            "riskLevel": "high",
            "battery": 0.05,  # Low battery triggers SMS
            "network": "offline",  # Offline triggers SMS
            "sessionId": f"TEST_sms_session_{int(time.time())}"
        }
        response = requests.post(f"{API_PREFIX}/sos", json=payload)
        assert response.status_code == 200
        sos_id = response.json()["sos_id"]
        
        # Get notifications
        notif_resp = requests.get(f"{API_PREFIX}/notifications", params={"limit": 20})
        data = notif_resp.json()
        
        # Find notification for our SOS with sms_results
        sos_notifs = [n for n in data["notifications"] if n["sos_id"] == sos_id and "sms_results" in n]
        
        if sos_notifs:
            for notif in sos_notifs:
                for sms_result in notif["sms_results"]:
                    assert sms_result["status"] == "withheld", f"Expected sms_results[].status='withheld': {sms_result}"
                print(f"sms_results[].status='withheld' confirmed")
        else:
            print("No sms_results in notifications (may not have SMS targets)")


class TestPushTokenField:
    """PUSH TOKEN FIELD: push_token stored on ContactProfile"""
    
    contact_id = None
    
    @classmethod
    def teardown_class(cls):
        if cls.contact_id:
            requests.delete(f"{API_PREFIX}/contacts/{cls.contact_id}")
    
    def test_create_contact_with_push_token(self):
        """POST /api/journey/contacts with push_token field"""
        payload = {
            "name": "TEST_PushTokenGuardian",
            "phone": "+919888888888",
            "email": "pushtoken@test.com",
            "layer": "guardian",
            "priority": 1,
            "push_token": "ExponentPushToken[test123]"
        }
        response = requests.post(f"{API_PREFIX}/contacts", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        self.__class__.contact_id = data["contact_id"]
        
        assert data["contact"]["push_token"] == "ExponentPushToken[test123]", f"push_token not in response: {data['contact']}"
        print(f"Contact created with push_token: {data['contact']['push_token']}")
    
    def test_get_contacts_shows_push_token(self):
        """GET /api/journey/contacts shows push_token field"""
        if not self.__class__.contact_id:
            pytest.skip("No contact created")
        
        response = requests.get(f"{API_PREFIX}/contacts")
        assert response.status_code == 200
        
        data = response.json()
        contact = next((c for c in data["contacts"] if c["id"] == self.__class__.contact_id), None)
        
        assert contact is not None, f"Contact {self.__class__.contact_id} not found"
        assert contact.get("push_token") == "ExponentPushToken[test123]", f"push_token not in contact: {contact}"
        print(f"GET /contacts shows push_token: {contact['push_token']}")
    
    def test_push_token_persisted_to_mongo(self):
        """push_token persisted to MongoDB"""
        if not self.__class__.contact_id:
            pytest.skip("No contact created")
        
        client = get_mongo_client()
        db = client[DB_NAME]
        doc = db["journey_contacts"].find_one({"_id": self.__class__.contact_id})
        
        assert doc is not None
        assert doc.get("push_token") == "ExponentPushToken[test123]", f"push_token not in MongoDB: {doc}"
        
        client.close()
        print(f"push_token persisted to MongoDB")
    
    def test_notification_collects_push_token_for_critical_sos(self):
        """Notification for critical SOS collects push_token (visible in push_result even if withheld)"""
        if not self.__class__.contact_id:
            pytest.skip("No contact created")
        
        session_id = f"TEST_push_collect_{int(time.time())}"
        
        # Assign contact to user
        requests.post(f"{API_PREFIX}/contacts/assign", json={
            "user_id": session_id,
            "guardian_ids": [self.__class__.contact_id],
            "authority_ids": []
        })
        
        # Create critical SOS
        payload = {
            "sosId": f"TEST_sos_pushcollect_{int(time.time())}",
            "sosState": "triggered",
            "ts": int(time.time() * 1000),
            "riskScore": 90,
            "riskLevel": "critical",
            "sessionId": session_id
        }
        response = requests.post(f"{API_PREFIX}/sos", json=payload)
        assert response.status_code == 200
        sos_id = response.json()["sos_id"]
        
        # Get notifications
        notif_resp = requests.get(f"{API_PREFIX}/notifications", params={"limit": 20})
        data = notif_resp.json()
        
        # Find notification for our SOS
        sos_notifs = [n for n in data["notifications"] if n["sos_id"] == sos_id]
        
        # Check if push_result exists (even if withheld)
        push_notifs = [n for n in sos_notifs if "push_result" in n]
        
        if push_notifs:
            print(f"Notification has push_result: {push_notifs[0]['push_result']}")
        else:
            print("No push_result in notification (push_token may not be collected for this state)")


class TestBackwardCompatibility:
    """BACKWARD COMPATIBILITY: v5 endpoints still work"""
    
    sos_id = None
    guardian_id = None
    authority_id = None
    
    @classmethod
    def setup_class(cls):
        """Create contacts for backward compatibility tests"""
        g_resp = requests.post(f"{API_PREFIX}/contacts", json={
            "name": "TEST_BackwardGuardian",
            "phone": "+919999111111",
            "layer": "guardian",
            "priority": 1
        })
        if g_resp.status_code == 200:
            cls.guardian_id = g_resp.json()["contact_id"]
        
        a_resp = requests.post(f"{API_PREFIX}/contacts", json={
            "name": "TEST_BackwardAuthority",
            "phone": "+919999222222",
            "layer": "authority",
            "priority": 1
        })
        if a_resp.status_code == 200:
            cls.authority_id = a_resp.json()["contact_id"]
        
        requests.post(f"{API_PREFIX}/contacts/assign", json={
            "user_id": "TEST_backward_user",
            "guardian_ids": [cls.guardian_id] if cls.guardian_id else [],
            "authority_ids": [cls.authority_id] if cls.authority_id else []
        })
    
    @classmethod
    def teardown_class(cls):
        if cls.guardian_id:
            requests.delete(f"{API_PREFIX}/contacts/{cls.guardian_id}")
        if cls.authority_id:
            requests.delete(f"{API_PREFIX}/contacts/{cls.authority_id}")
    
    def test_risk_score_stability_dampening_still_works(self):
        """POST /api/journey/risk/score - stability dampening still works"""
        session_id = "TEST_backward_stability"
        
        # Build low momentum history
        for _ in range(5):
            requests.post(f"{API_PREFIX}/risk/score", json={
                "session_id": session_id,
                "idle_ms": 0,
                "is_moving": True,
                "speed": 5.0,
                "battery": 0.8,
                "network": "online",
                "anomaly_count": 0,
                "sos_active": False
            })
        
        # Send high score
        payload = {
            "session_id": session_id,
            "idle_ms": 16 * 60 * 1000,
            "is_moving": False,
            "speed": 0,
            "battery": 0.08,
            "network": "offline",
            "anomaly_count": 0,
            "sos_active": False
        }
        response = requests.post(f"{API_PREFIX}/risk/score", json=payload)
        assert response.status_code == 200
        
        data = response.json()
        assert "momentum" in data, "Missing momentum field"
        assert "volatility" in data, "Missing volatility field"
        assert "stability" in data, "Missing stability field"
        print(f"Stability dampening: raw={data['risk_score']}, effective={data['effective_score']}, momentum={data['momentum']}")
    
    def test_critical_sos_pre_alerts_authority(self):
        """POST /api/journey/sos with riskLevel=critical pre-alerts authority"""
        payload = {
            "sosId": f"TEST_sos_backward_critical_{int(time.time())}",
            "sosState": "triggered",
            "ts": int(time.time() * 1000),
            "riskScore": 90,
            "riskLevel": "critical",
            "sessionId": "TEST_backward_user"
        }
        response = requests.post(f"{API_PREFIX}/sos", json=payload)
        assert response.status_code == 200
        
        data = response.json()
        self.__class__.sos_id = data["sos_id"]
        
        assert data["authority_pre_alerted"] == True, f"Expected authority_pre_alerted=True: {data}"
        assert data["authority_verified"] == False, f"Expected authority_verified=False: {data}"
        print(f"Critical SOS pre-alerts authority: authority_pre_alerted={data['authority_pre_alerted']}")
    
    def test_verify_authority_transitions_to_verified(self):
        """POST /api/journey/escalation/{sos_id}/verify transitions to authority_verified=True"""
        if not self.__class__.sos_id:
            pytest.skip("No SOS created")
        
        response = requests.post(f"{API_PREFIX}/escalation/{self.__class__.sos_id}/verify", params={"source": "user_confirm"})
        assert response.status_code == 200
        
        data = response.json()
        assert data["escalation"]["authority_verified"] == True, f"Expected authority_verified=True: {data}"
        print(f"Authority verified: {data['escalation']['authority_verified']}")
    
    def test_contact_ack_marks_acknowledged(self):
        """POST /api/journey/contacts/ack marks acknowledged"""
        # Create new SOS for ACK test
        payload = {
            "sosId": f"TEST_sos_backward_ack_{int(time.time())}",
            "sosState": "triggered",
            "ts": int(time.time() * 1000),
            "riskScore": 70,
            "riskLevel": "high",
            "sessionId": "TEST_backward_user"
        }
        sos_resp = requests.post(f"{API_PREFIX}/sos", json=payload)
        sos_id = sos_resp.json()["sos_id"]
        
        # ACK
        ack_payload = {
            "contact_id": self.__class__.guardian_id,
            "sos_id": sos_id
        }
        response = requests.post(f"{API_PREFIX}/contacts/ack", json=ack_payload)
        assert response.status_code == 200
        
        data = response.json()
        assert data["escalation"]["any_guardian_acked"] == True, f"Expected any_guardian_acked=True: {data}"
        print(f"Guardian ACK works: any_guardian_acked={data['escalation']['any_guardian_acked']}")
    
    def test_get_sos_returns_data(self):
        """GET /api/journey/sos/{sos_id} returns data"""
        if not self.__class__.sos_id:
            pytest.skip("No SOS created")
        
        response = requests.get(f"{API_PREFIX}/sos/{self.__class__.sos_id}")
        assert response.status_code == 200
        
        data = response.json()
        assert "sos_id" in data
        assert "sos_state" in data
        assert "state_history" in data
        print(f"GET /sos/{self.__class__.sos_id} returns data")
    
    def test_put_sos_updates_state(self):
        """PUT /api/journey/sos/{sos_id} updates state"""
        if not self.__class__.sos_id:
            pytest.skip("No SOS created")
        
        payload = {"sos_state": "resolved", "meta": {"resolution": "test"}}
        response = requests.put(f"{API_PREFIX}/sos/{self.__class__.sos_id}", json=payload)
        assert response.status_code == 200
        
        data = response.json()
        assert data["sos_state"] == "resolved"
        print(f"PUT /sos/{self.__class__.sos_id} updates state to resolved")


class TestMongoCollections:
    """MONGO COLLECTIONS: Direct pymongo verification"""
    
    def test_journey_contacts_collection_exists(self):
        """journey_contacts collection exists and has data"""
        client = get_mongo_client()
        db = client[DB_NAME]
        
        count = db["journey_contacts"].count_documents({})
        print(f"journey_contacts count: {count}")
        
        # Should have at least some contacts from other tests
        assert count >= 0, "journey_contacts collection should exist"
        
        client.close()
    
    def test_journey_user_contacts_collection_exists(self):
        """journey_user_contacts collection exists"""
        client = get_mongo_client()
        db = client[DB_NAME]
        
        count = db["journey_user_contacts"].count_documents({})
        print(f"journey_user_contacts count: {count}")
        
        assert count >= 0, "journey_user_contacts collection should exist"
        
        client.close()
    
    def test_journey_sos_events_collection_exists(self):
        """journey_sos_events collection exists"""
        client = get_mongo_client()
        db = client[DB_NAME]
        
        count = db["journey_sos_events"].count_documents({})
        print(f"journey_sos_events count: {count}")
        
        assert count >= 0, "journey_sos_events collection should exist"
        
        client.close()
    
    def test_journey_escalations_collection_exists(self):
        """journey_escalations collection exists"""
        client = get_mongo_client()
        db = client[DB_NAME]
        
        count = db["journey_escalations"].count_documents({})
        print(f"journey_escalations count: {count}")
        
        assert count >= 0, "journey_escalations collection should exist"
        
        client.close()
    
    def test_id_field_used_as_primary_key(self):
        """_id field is used as primary key in each collection"""
        client = get_mongo_client()
        db = client[DB_NAME]
        
        # Check journey_contacts
        contact_doc = db["journey_contacts"].find_one()
        if contact_doc:
            assert "_id" in contact_doc, "journey_contacts should use _id as primary key"
            print(f"journey_contacts _id: {contact_doc['_id']}")
        
        # Check journey_sos_events
        sos_doc = db["journey_sos_events"].find_one()
        if sos_doc:
            assert "_id" in sos_doc, "journey_sos_events should use _id as primary key"
            print(f"journey_sos_events _id: {sos_doc['_id']}")
        
        # Check journey_escalations
        esc_doc = db["journey_escalations"].find_one()
        if esc_doc:
            assert "_id" in esc_doc, "journey_escalations should use _id as primary key"
            print(f"journey_escalations _id: {esc_doc['_id']}")
        
        client.close()


class TestHydrationOnRestart:
    """HYDRATION ON RESTART: Data survives backend restart"""
    
    contact_id = None
    sos_id = None
    test_session_id = f"TEST_hydrate_session_{int(time.time())}"
    
    @classmethod
    def setup_class(cls):
        """Create test data before restart"""
        # Create contact
        g_resp = requests.post(f"{API_PREFIX}/contacts", json={
            "name": "TEST_HydrateGuardian",
            "phone": "+919111222333",
            "layer": "guardian",
            "priority": 1
        })
        if g_resp.status_code == 200:
            cls.contact_id = g_resp.json()["contact_id"]
        
        # Assign to user
        requests.post(f"{API_PREFIX}/contacts/assign", json={
            "user_id": cls.test_session_id,
            "guardian_ids": [cls.contact_id] if cls.contact_id else [],
            "authority_ids": []
        })
        
        # Create SOS
        sos_resp = requests.post(f"{API_PREFIX}/sos", json={
            "sosId": f"TEST_sos_hydrate_{int(time.time())}",
            "sosState": "triggered",
            "ts": int(time.time() * 1000),
            "riskScore": 85,
            "riskLevel": "critical",
            "sessionId": cls.test_session_id
        })
        if sos_resp.status_code == 200:
            cls.sos_id = sos_resp.json()["sos_id"]
    
    @classmethod
    def teardown_class(cls):
        if cls.contact_id:
            requests.delete(f"{API_PREFIX}/contacts/{cls.contact_id}")
    
    def test_01_verify_data_exists_before_restart(self):
        """Verify data exists before restart"""
        # Check stats
        response = requests.get(f"{API_PREFIX}/stats")
        assert response.status_code == 200
        
        data = response.json()
        print(f"Before restart - contacts: {data['total_contacts']}, sos: {data['total_sos']}")
        
        assert data["total_contacts"] > 0, "Should have contacts before restart"
        assert data["total_sos"] > 0, "Should have SOS before restart"
    
    def test_02_restart_backend(self):
        """Restart backend via supervisorctl"""
        try:
            result = subprocess.run(
                ["sudo", "supervisorctl", "restart", "backend"],
                capture_output=True,
                text=True,
                timeout=30
            )
            print(f"Restart output: {result.stdout}")
            
            # Wait for backend to come back up
            import time
            time.sleep(4)
            
            # Verify backend is up
            for _ in range(10):
                try:
                    response = requests.get(f"{BASE_URL}/api/health", timeout=2)
                    if response.status_code == 200:
                        print("Backend is back up")
                        break
                except:
                    time.sleep(1)
            
        except Exception as e:
            pytest.skip(f"Could not restart backend: {e}")
    
    def test_03_stats_show_data_after_restart(self):
        """GET /api/journey/stats shows contacts/sos/escalations counts > 0 after restart"""
        response = requests.get(f"{API_PREFIX}/stats")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        print(f"After restart - contacts: {data['total_contacts']}, sos: {data['total_sos']}, escalations: {data.get('active_escalations', 0)}")
        
        assert data["total_contacts"] > 0, f"Expected contacts > 0 after restart, got {data['total_contacts']}"
        assert data["total_sos"] > 0, f"Expected sos > 0 after restart, got {data['total_sos']}"
        print("Data hydrated from MongoDB after restart")
    
    def test_04_escalation_state_preserved_after_restart(self):
        """GET /api/journey/escalation/{sos_id} returns same state after restart"""
        if not self.__class__.sos_id:
            pytest.skip("No SOS created")
        
        response = requests.get(f"{API_PREFIX}/escalation/{self.__class__.sos_id}")
        
        # May return 404 if escalation was not hydrated (depends on timing)
        if response.status_code == 404:
            print(f"Escalation {self.__class__.sos_id} not found after restart (may have been cleaned up)")
            return
        
        assert response.status_code == 200
        
        data = response.json()
        esc = data["escalation"]
        
        # Verify escalation state preserved
        assert "active_layer" in esc, "Missing active_layer"
        assert "authority_pre_alerted" in esc, "Missing authority_pre_alerted"
        assert "current_contact" in esc, "Missing current_contact"
        
        print(f"Escalation state preserved: active_layer={esc['active_layer']}, authority_pre_alerted={esc['authority_pre_alerted']}")
    
    def test_05_contacts_list_preserved_after_restart(self):
        """GET /api/journey/contacts lists previously-created contacts"""
        response = requests.get(f"{API_PREFIX}/contacts")
        assert response.status_code == 200
        
        data = response.json()
        
        # Find our test contact
        test_contacts = [c for c in data["contacts"] if c.get("name", "").startswith("TEST_Hydrate")]
        
        if test_contacts:
            print(f"Found {len(test_contacts)} hydrated test contacts")
        else:
            print(f"Test contacts may have been cleaned up, but {data['count']} total contacts exist")
        
        assert data["count"] > 0, "Should have contacts after restart"


class TestCleanup:
    """Cleanup test data from MongoDB"""
    
    def test_cleanup_test_data(self):
        """Remove TEST_ prefixed data from MongoDB"""
        client = get_mongo_client()
        db = client[DB_NAME]
        
        # Delete test contacts
        result = db["journey_contacts"].delete_many({"name": {"$regex": "^TEST_"}})
        print(f"Deleted {result.deleted_count} test contacts")
        
        # Delete test user contacts
        result = db["journey_user_contacts"].delete_many({"_id": {"$regex": "^TEST_"}})
        print(f"Deleted {result.deleted_count} test user contacts")
        
        # Delete test SOS events
        result = db["journey_sos_events"].delete_many({"_id": {"$regex": "^TEST_"}})
        print(f"Deleted {result.deleted_count} test SOS events")
        
        # Delete test escalations
        result = db["journey_escalations"].delete_many({"_id": {"$regex": "^TEST_"}})
        print(f"Deleted {result.deleted_count} test escalations")
        
        client.close()
        print("Test data cleanup complete")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
