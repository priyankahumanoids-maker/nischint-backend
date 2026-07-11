"""
Test PWA, Guardian Management, and Device API endpoints.
Tests for iteration 121: PWA, Guardian Network, Push Notification infrastructure.
"""
import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
TEST_EMAIL = "nischint4parents@gmail.com"
TEST_PASSWORD = "secret123"


class TestDeviceAPI:
    """Tests for Device registration and notification API endpoints."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test token."""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        # Login to get token
        response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        if response.status_code == 200:
            token = response.json().get("token") or response.json().get("access_token")
            if token:
                self.session.headers.update({"Authorization": f"Bearer {token}"})

    def test_device_register_success(self):
        """POST /api/device/register - Register a device token."""
        test_token = f"test_device_token_{uuid.uuid4().hex[:8]}"
        response = self.session.post(f"{BASE_URL}/api/device/register", json={
            "device_token": test_token,
            "device_type": "web",
            "app_version": "1.0.0"
        })
        print(f"Device register response: {response.status_code} - {response.text[:200]}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data.get("status") in ["registered", "updated"], f"Status should be 'registered' or 'updated', got {data.get('status')}"

    def test_device_register_android_type(self):
        """POST /api/device/register - Register android device."""
        test_token = f"android_token_{uuid.uuid4().hex[:8]}"
        response = self.session.post(f"{BASE_URL}/api/device/register", json={
            "device_token": test_token,
            "device_type": "android",
            "app_version": "2.0.0"
        })
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") in ["registered", "updated"]

    def test_device_register_ios_type(self):
        """POST /api/device/register - Register iOS device."""
        test_token = f"ios_token_{uuid.uuid4().hex[:8]}"
        response = self.session.post(f"{BASE_URL}/api/device/register", json={
            "device_token": test_token,
            "device_type": "ios"
        })
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") in ["registered", "updated"]

    def test_device_register_update_existing(self):
        """POST /api/device/register - Update existing token."""
        test_token = f"update_test_token_{uuid.uuid4().hex[:8]}"
        # First registration
        response1 = self.session.post(f"{BASE_URL}/api/device/register", json={
            "device_token": test_token,
            "device_type": "web",
            "app_version": "1.0.0"
        })
        assert response1.status_code == 200
        # Second registration should update
        response2 = self.session.post(f"{BASE_URL}/api/device/register", json={
            "device_token": test_token,
            "device_type": "web",
            "app_version": "1.1.0"
        })
        assert response2.status_code == 200
        data = response2.json()
        assert data.get("status") == "updated", "Should be 'updated' for existing token"

    def test_device_notifications_list(self):
        """GET /api/device/notifications - Get notification history."""
        response = self.session.get(f"{BASE_URL}/api/device/notifications")
        print(f"Notifications response: {response.status_code} - {response.text[:200]}")
        assert response.status_code == 200
        data = response.json()
        assert "notifications" in data, "Response should have 'notifications' key"
        assert isinstance(data["notifications"], list), "Notifications should be a list"

    def test_device_notifications_with_limit(self):
        """GET /api/device/notifications?limit=5 - Get notification with limit."""
        response = self.session.get(f"{BASE_URL}/api/device/notifications?limit=5")
        assert response.status_code == 200
        data = response.json()
        assert "notifications" in data
        assert len(data["notifications"]) <= 5

    def test_device_unregister(self):
        """DELETE /api/device/unregister - Unregister a device token."""
        test_token = f"unregister_test_{uuid.uuid4().hex[:8]}"
        # First register the token
        self.session.post(f"{BASE_URL}/api/device/register", json={
            "device_token": test_token,
            "device_type": "web"
        })
        # Now unregister
        response = self.session.delete(f"{BASE_URL}/api/device/unregister?device_token={test_token}")
        print(f"Unregister response: {response.status_code} - {response.text[:200]}")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "unregistered"


class TestGuardianNetworkAPI:
    """Tests for Guardian Network API endpoints."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test token."""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        # Login to get token
        response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        if response.status_code == 200:
            token = response.json().get("token") or response.json().get("access_token")
            if token:
                self.session.headers.update({"Authorization": f"Bearer {token}"})

    def test_guardian_list(self):
        """GET /api/guardian-network/ - List guardians."""
        response = self.session.get(f"{BASE_URL}/api/guardian-network/")
        print(f"Guardian list response: {response.status_code} - {response.text[:300]}")
        assert response.status_code == 200
        data = response.json()
        assert "guardians" in data, "Response should have 'guardians' key"
        assert "total" in data, "Response should have 'total' key"
        assert isinstance(data["guardians"], list)

    def test_guardian_add(self):
        """POST /api/guardian-network/ - Add a guardian."""
        test_email = f"test_guardian_{uuid.uuid4().hex[:6]}@example.com"
        response = self.session.post(f"{BASE_URL}/api/guardian-network/", json={
            "guardian_email": test_email,
            "guardian_name": "Test Guardian",
            "relationship_type": "friend",
            "is_primary": False
        })
        print(f"Add guardian response: {response.status_code} - {response.text[:300]}")
        assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.text}"
        data = response.json()
        assert "id" in data, "Response should have 'id'"
        assert data.get("guardian_email") == test_email or data.get("guardian_name") == "Test Guardian"
        # Store for cleanup
        self.created_guardian_id = data.get("id")

    def test_guardian_add_parent_relationship(self):
        """POST /api/guardian-network/ - Add parent guardian."""
        test_email = f"parent_{uuid.uuid4().hex[:6]}@example.com"
        response = self.session.post(f"{BASE_URL}/api/guardian-network/", json={
            "guardian_email": test_email,
            "guardian_name": "Parent Guardian",
            "relationship_type": "parent",
            "is_primary": True
        })
        assert response.status_code == 201
        data = response.json()
        assert data.get("relationship_type") == "parent"

    def test_guardian_add_sibling_relationship(self):
        """POST /api/guardian-network/ - Add sibling guardian."""
        test_email = f"sibling_{uuid.uuid4().hex[:6]}@example.com"
        response = self.session.post(f"{BASE_URL}/api/guardian-network/", json={
            "guardian_email": test_email,
            "guardian_name": "Sibling Guardian",
            "relationship_type": "sibling",
            "is_primary": False
        })
        assert response.status_code == 201
        data = response.json()
        assert data.get("relationship_type") == "sibling"

    def test_guardian_update(self):
        """PUT /api/guardian-network/{id} - Update guardian."""
        # First create a guardian
        test_email = f"update_guard_{uuid.uuid4().hex[:6]}@example.com"
        create_resp = self.session.post(f"{BASE_URL}/api/guardian-network/", json={
            "guardian_email": test_email,
            "guardian_name": "Original Name",
            "relationship_type": "friend",
            "is_primary": False
        })
        if create_resp.status_code != 201:
            pytest.skip("Could not create guardian for update test")
        guardian_id = create_resp.json().get("id")
        
        # Update the guardian
        response = self.session.put(f"{BASE_URL}/api/guardian-network/{guardian_id}", json={
            "guardian_name": "Updated Name",
            "is_primary": True
        })
        print(f"Update guardian response: {response.status_code} - {response.text[:200]}")
        assert response.status_code == 200
        data = response.json()
        assert data.get("guardian_name") == "Updated Name"
        assert data.get("is_primary") == True

    def test_guardian_delete(self):
        """DELETE /api/guardian-network/{id} - Remove guardian."""
        # First create a guardian
        test_email = f"delete_guard_{uuid.uuid4().hex[:6]}@example.com"
        create_resp = self.session.post(f"{BASE_URL}/api/guardian-network/", json={
            "guardian_email": test_email,
            "guardian_name": "To Delete",
            "relationship_type": "friend",
            "is_primary": False
        })
        if create_resp.status_code != 201:
            pytest.skip("Could not create guardian for delete test")
        guardian_id = create_resp.json().get("id")
        
        # Delete the guardian
        response = self.session.delete(f"{BASE_URL}/api/guardian-network/{guardian_id}")
        print(f"Delete guardian response: {response.status_code} - {response.text[:200]}")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "removed"


class TestEmergencyContactsAPI:
    """Tests for Emergency Contacts API endpoints."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test token."""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        # Login to get token
        response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        if response.status_code == 200:
            token = response.json().get("token") or response.json().get("access_token")
            if token:
                self.session.headers.update({"Authorization": f"Bearer {token}"})

    def test_contacts_list(self):
        """GET /api/guardian-network/emergency-contacts - List contacts."""
        response = self.session.get(f"{BASE_URL}/api/guardian-network/emergency-contacts")
        print(f"Contacts list response: {response.status_code} - {response.text[:300]}")
        assert response.status_code == 200
        data = response.json()
        assert "contacts" in data, "Response should have 'contacts' key"
        assert isinstance(data["contacts"], list)

    def test_contact_add(self):
        """POST /api/guardian-network/emergency-contacts - Add contact."""
        response = self.session.post(f"{BASE_URL}/api/guardian-network/emergency-contacts", json={
            "name": f"Test Contact {uuid.uuid4().hex[:4]}",
            "phone": "+1234567890",
            "relationship_type": "neighbor",
            "notes": "Test contact for automated testing"
        })
        print(f"Add contact response: {response.status_code} - {response.text[:300]}")
        assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.text}"
        data = response.json()
        assert "id" in data
        assert data.get("phone") == "+1234567890"

    def test_contact_add_hospital(self):
        """POST /api/guardian-network/emergency-contacts - Add hospital contact."""
        response = self.session.post(f"{BASE_URL}/api/guardian-network/emergency-contacts", json={
            "name": "City Hospital",
            "phone": "+1911999111",
            "relationship_type": "hospital"
        })
        assert response.status_code == 201
        data = response.json()
        assert data.get("relationship_type") == "hospital"

    def test_contact_update(self):
        """PUT /api/guardian-network/emergency-contacts/{id} - Update contact."""
        # First create a contact
        create_resp = self.session.post(f"{BASE_URL}/api/guardian-network/emergency-contacts", json={
            "name": "Original Contact",
            "phone": "+1111111111",
            "relationship_type": "other"
        })
        if create_resp.status_code != 201:
            pytest.skip("Could not create contact for update test")
        contact_id = create_resp.json().get("id")
        
        # Update the contact
        response = self.session.put(f"{BASE_URL}/api/guardian-network/emergency-contacts/{contact_id}", json={
            "name": "Updated Contact",
            "phone": "+2222222222"
        })
        print(f"Update contact response: {response.status_code} - {response.text[:200]}")
        assert response.status_code == 200
        data = response.json()
        assert data.get("name") == "Updated Contact"
        assert data.get("phone") == "+2222222222"

    def test_contact_delete(self):
        """DELETE /api/guardian-network/emergency-contacts/{id} - Delete contact."""
        # First create a contact
        create_resp = self.session.post(f"{BASE_URL}/api/guardian-network/emergency-contacts", json={
            "name": "To Delete Contact",
            "phone": "+3333333333",
            "relationship_type": "other"
        })
        if create_resp.status_code != 201:
            pytest.skip("Could not create contact for delete test")
        contact_id = create_resp.json().get("id")
        
        # Delete the contact
        response = self.session.delete(f"{BASE_URL}/api/guardian-network/emergency-contacts/{contact_id}")
        print(f"Delete contact response: {response.status_code} - {response.text[:200]}")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "removed"


class TestEscalationChainAPI:
    """Tests for Escalation Chain API."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test token."""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        # Login to get token
        response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        if response.status_code == 200:
            token = response.json().get("token") or response.json().get("access_token")
            if token:
                self.session.headers.update({"Authorization": f"Bearer {token}"})

    def test_escalation_chain(self):
        """GET /api/guardian-network/escalation-chain - Get escalation chain."""
        response = self.session.get(f"{BASE_URL}/api/guardian-network/escalation-chain")
        print(f"Escalation chain response: {response.status_code} - {response.text[:400]}")
        assert response.status_code == 200
        data = response.json()
        assert "escalation_chain" in data
        assert "total" in data
        # Chain should be a list
        assert isinstance(data["escalation_chain"], list)


class TestPWAStaticFiles:
    """Tests for PWA static files."""
    
    def test_manifest_json_accessible(self):
        """GET /manifest.json - Manifest file is accessible."""
        response = requests.get(f"{BASE_URL}/manifest.json")
        print(f"Manifest response: {response.status_code}")
        assert response.status_code == 200

    def test_manifest_json_content(self):
        """GET /manifest.json - Manifest has required fields."""
        response = requests.get(f"{BASE_URL}/manifest.json")
        assert response.status_code == 200
        data = response.json()
        # Required PWA fields
        assert data.get("name") == "Nischint Safety"
        assert data.get("short_name") == "Nischint"
        assert data.get("start_url") == "/m/home"
        assert data.get("display") == "standalone"
        assert "icons" in data
        assert len(data["icons"]) >= 2

    def test_service_worker_accessible(self):
        """GET /sw.js - Service worker is accessible."""
        response = requests.get(f"{BASE_URL}/sw.js")
        print(f"SW response: {response.status_code}")
        assert response.status_code == 200

    def test_service_worker_content(self):
        """GET /sw.js - Service worker has PWA event handlers."""
        response = requests.get(f"{BASE_URL}/sw.js")
        assert response.status_code == 200
        content = response.text
        # Check for essential SW patterns
        assert "install" in content
        assert "activate" in content
        assert "fetch" in content
        assert "push" in content  # For push notifications
        assert "caches" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
