"""
Check-In Feature Tests - NISCHINT Kids Safety Platform
Tests for 2-way safety check between guardian and child:
- Guardian creates check-in -> push to child -> child responds (safe/help) -> guardian sees status
- Auto-expiry after 5 minutes, duplicate check-in cancels previous pending
"""
import pytest
import requests
import os
import time
from datetime import datetime

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
CHILD_EMAIL = "kidnischint@gmail.com"
CHILD_PASSWORD = "nischint123"
CHILD_USER_ID = "ae6c29f9-aafd-4449-abc3-881effa122a4"

MOTHER_EMAIL = "mothernischint@gmail.com"
MOTHER_PASSWORD = "nischint123"

FATHER_EMAIL = "fathernishchint@gmail.com"
FATHER_PASSWORD = "nischint123"


class TokenCache:
    """Cache tokens to avoid rate limiting"""
    _tokens = {}
    
    @classmethod
    def get_token(cls, email, password):
        if email in cls._tokens:
            return cls._tokens[email]
        
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": email, "password": password}
        )
        if response.status_code == 200:
            data = response.json()
            token = data.get("access_token")
            cls._tokens[email] = token
            return token
        return None


@pytest.fixture(scope="module")
def child_token():
    """Get child's auth token"""
    token = TokenCache.get_token(CHILD_EMAIL, CHILD_PASSWORD)
    if not token:
        pytest.skip("Could not authenticate child user")
    return token


@pytest.fixture(scope="module")
def mother_token():
    """Get mother's auth token"""
    token = TokenCache.get_token(MOTHER_EMAIL, MOTHER_PASSWORD)
    if not token:
        pytest.skip("Could not authenticate mother guardian")
    return token


@pytest.fixture(scope="module")
def father_token():
    """Get father's auth token"""
    token = TokenCache.get_token(FATHER_EMAIL, FATHER_PASSWORD)
    if not token:
        pytest.skip("Could not authenticate father guardian")
    return token


@pytest.fixture
def mother_headers(mother_token):
    return {"Authorization": f"Bearer {mother_token}", "Content-Type": "application/json"}


@pytest.fixture
def father_headers(father_token):
    return {"Authorization": f"Bearer {father_token}", "Content-Type": "application/json"}


@pytest.fixture
def child_headers(child_token):
    return {"Authorization": f"Bearer {child_token}", "Content-Type": "application/json"}


class TestAuthAndGuardianLink:
    """Verify auth and guardian linkage before check-in tests"""
    
    def test_child_login(self):
        """Test child can login"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": CHILD_EMAIL, "password": CHILD_PASSWORD}
        )
        assert response.status_code == 200, f"Child login failed: {response.text}"
        data = response.json()
        assert "access_token" in data, "Missing access_token in response"
        # Role is embedded in JWT, not in 'user' object
        print(f"✓ Child login successful, access_token received")
    
    def test_mother_guardian_login(self):
        """Test mother guardian can login"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": MOTHER_EMAIL, "password": MOTHER_PASSWORD}
        )
        assert response.status_code == 200, f"Mother login failed: {response.text}"
        data = response.json()
        assert "access_token" in data
        print(f"✓ Mother login successful, access_token received")
    
    def test_father_guardian_login(self):
        """Test father guardian can login"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": FATHER_EMAIL, "password": FATHER_PASSWORD}
        )
        assert response.status_code == 200, f"Father login failed: {response.text}"
        data = response.json()
        assert "access_token" in data
        print(f"✓ Father login successful, access_token received")


class TestCreateCheckIn:
    """Test POST /api/checkin/{child_user_id} - Guardian creates check-in"""
    
    def test_create_checkin_success(self, mother_headers):
        """Guardian successfully creates check-in for linked child"""
        response = requests.post(
            f"{BASE_URL}/api/checkin/{CHILD_USER_ID}",
            headers=mother_headers
        )
        assert response.status_code == 200, f"Create check-in failed: {response.text}"
        data = response.json()
        
        # Verify response structure
        assert "check_in_id" in data, "Missing check_in_id"
        assert data.get("status") == "pending", f"Expected status=pending, got {data.get('status')}"
        assert data.get("child_id") == CHILD_USER_ID, "Child ID mismatch"
        assert "created_at" in data, "Missing created_at"
        
        print(f"✓ Check-in created: {data.get('check_in_id')}, status={data.get('status')}")
        return data.get("check_in_id")
    
    def test_create_checkin_by_father(self, father_headers):
        """Father guardian can also create check-in"""
        response = requests.post(
            f"{BASE_URL}/api/checkin/{CHILD_USER_ID}",
            headers=father_headers
        )
        assert response.status_code == 200, f"Father create check-in failed: {response.text}"
        data = response.json()
        assert data.get("status") == "pending"
        print(f"✓ Father created check-in: {data.get('check_in_id')}")
    
    def test_create_checkin_unlinked_guardian(self, mother_headers):
        """Guardian cannot create check-in for unlinked random user"""
        random_user_id = "11111111-1111-1111-1111-111111111111"
        response = requests.post(
            f"{BASE_URL}/api/checkin/{random_user_id}",
            headers=mother_headers
        )
        # Should return 400 with error about not being linked
        assert response.status_code == 400, f"Expected 400 for unlinked user, got {response.status_code}"
        data = response.json()
        assert "not linked" in data.get("detail", "").lower() or "not found" in data.get("detail", "").lower(), \
            f"Expected 'not linked' error, got: {data}"
        print(f"✓ Correctly blocked check-in for unlinked user: {data.get('detail')}")


class TestPendingCheckIns:
    """Test GET /api/checkin/pending - Child sees pending check-ins"""
    
    def test_get_pending_checkins_as_child(self, child_headers, mother_headers):
        """Child can see pending check-ins with guardian_name and expires_in_seconds"""
        # First create a check-in as mother
        create_resp = requests.post(
            f"{BASE_URL}/api/checkin/{CHILD_USER_ID}",
            headers=mother_headers
        )
        assert create_resp.status_code == 200, f"Create check-in failed: {create_resp.text}"
        check_in_id = create_resp.json().get("check_in_id")
        
        # Now get pending as child
        response = requests.get(
            f"{BASE_URL}/api/checkin/pending",
            headers=child_headers
        )
        assert response.status_code == 200, f"Get pending failed: {response.text}"
        data = response.json()
        
        assert "check_ins" in data, "Missing check_ins array"
        check_ins = data.get("check_ins", [])
        
        # Find our created check-in
        found = None
        for ci in check_ins:
            if ci.get("check_in_id") == check_in_id:
                found = ci
                break
        
        assert found is not None, f"Created check-in {check_in_id} not found in pending list"
        
        # Verify fields
        assert "guardian_name" in found, "Missing guardian_name"
        assert "expires_in_seconds" in found, "Missing expires_in_seconds"
        assert found.get("status") == "pending"
        
        # expires_in_seconds should be positive (< 5 min = 300 sec)
        expires_in = found.get("expires_in_seconds", 0)
        assert 0 < expires_in <= 300, f"Unexpected expires_in_seconds: {expires_in}"
        
        print(f"✓ Child sees pending check-in: guardian={found.get('guardian_name')}, expires_in={expires_in}s")


class TestRespondToCheckIn:
    """Test POST /api/checkin/{check_in_id}/respond - Child responds"""
    
    def test_respond_safe(self, mother_headers, child_headers):
        """Child responds 'safe' to check-in"""
        # Create check-in
        create_resp = requests.post(
            f"{BASE_URL}/api/checkin/{CHILD_USER_ID}",
            headers=mother_headers
        )
        assert create_resp.status_code == 200
        check_in_id = create_resp.json().get("check_in_id")
        
        # Respond as child
        response = requests.post(
            f"{BASE_URL}/api/checkin/{check_in_id}/respond",
            headers=child_headers,
            json={"response": "safe"}
        )
        assert response.status_code == 200, f"Respond safe failed: {response.text}"
        data = response.json()
        
        assert data.get("check_in_id") == check_in_id
        assert data.get("status") == "safe", f"Expected status=safe, got {data.get('status')}"
        assert "responded_at" in data, "Missing responded_at"
        
        print(f"✓ Child responded 'safe': {check_in_id}")
        return check_in_id
    
    def test_respond_help(self, mother_headers, child_headers):
        """Child responds 'help' to check-in - triggers urgent notification"""
        # Create check-in
        create_resp = requests.post(
            f"{BASE_URL}/api/checkin/{CHILD_USER_ID}",
            headers=mother_headers
        )
        assert create_resp.status_code == 200
        check_in_id = create_resp.json().get("check_in_id")
        
        # Respond help as child
        response = requests.post(
            f"{BASE_URL}/api/checkin/{check_in_id}/respond",
            headers=child_headers,
            json={"response": "help"}
        )
        assert response.status_code == 200, f"Respond help failed: {response.text}"
        data = response.json()
        
        assert data.get("status") == "help", f"Expected status=help, got {data.get('status')}"
        print(f"✓ Child responded 'help': {check_in_id} (push to guardian logged)")
        return check_in_id
    
    def test_respond_invalid_value(self, mother_headers, child_headers):
        """Invalid response value returns 400"""
        # Create check-in
        create_resp = requests.post(
            f"{BASE_URL}/api/checkin/{CHILD_USER_ID}",
            headers=mother_headers
        )
        assert create_resp.status_code == 200
        check_in_id = create_resp.json().get("check_in_id")
        
        # Respond with invalid value
        response = requests.post(
            f"{BASE_URL}/api/checkin/{check_in_id}/respond",
            headers=child_headers,
            json={"response": "maybe"}
        )
        assert response.status_code == 400, f"Expected 400 for invalid response, got {response.status_code}"
        data = response.json()
        assert "safe" in data.get("detail", "").lower() or "help" in data.get("detail", "").lower()
        print(f"✓ Invalid response correctly rejected: {data.get('detail')}")
    
    def test_respond_already_responded(self, mother_headers, child_headers):
        """Responding to already-responded check-in returns error"""
        # Create and respond safe
        create_resp = requests.post(
            f"{BASE_URL}/api/checkin/{CHILD_USER_ID}",
            headers=mother_headers
        )
        assert create_resp.status_code == 200
        check_in_id = create_resp.json().get("check_in_id")
        
        # First response
        response1 = requests.post(
            f"{BASE_URL}/api/checkin/{check_in_id}/respond",
            headers=child_headers,
            json={"response": "safe"}
        )
        assert response1.status_code == 200
        
        # Second response should fail
        response2 = requests.post(
            f"{BASE_URL}/api/checkin/{check_in_id}/respond",
            headers=child_headers,
            json={"response": "help"}
        )
        assert response2.status_code == 400, f"Expected 400 for double respond, got {response2.status_code}"
        data = response2.json()
        assert "already" in data.get("detail", "").lower()
        print(f"✓ Double-response correctly rejected: {data.get('detail')}")


class TestCheckInStatus:
    """Test GET /api/checkin/status/{check_in_id} - Guardian polls status"""
    
    def test_get_status_pending(self, mother_headers):
        """Guardian sees pending status after creating check-in"""
        # Create check-in
        create_resp = requests.post(
            f"{BASE_URL}/api/checkin/{CHILD_USER_ID}",
            headers=mother_headers
        )
        assert create_resp.status_code == 200
        check_in_id = create_resp.json().get("check_in_id")
        
        # Get status
        response = requests.get(
            f"{BASE_URL}/api/checkin/status/{check_in_id}",
            headers=mother_headers
        )
        assert response.status_code == 200, f"Get status failed: {response.text}"
        data = response.json()
        
        assert data.get("check_in_id") == check_in_id
        assert data.get("status") == "pending"
        assert data.get("child_id") == CHILD_USER_ID
        assert "child_name" in data
        assert data.get("responded_at") is None
        
        print(f"✓ Guardian sees pending status: child={data.get('child_name')}")
    
    def test_get_status_after_safe_response(self, mother_headers, child_headers):
        """Guardian sees 'safe' status after child responds"""
        # Create check-in
        create_resp = requests.post(
            f"{BASE_URL}/api/checkin/{CHILD_USER_ID}",
            headers=mother_headers
        )
        assert create_resp.status_code == 200
        check_in_id = create_resp.json().get("check_in_id")
        
        # Child responds safe
        respond_resp = requests.post(
            f"{BASE_URL}/api/checkin/{check_in_id}/respond",
            headers=child_headers,
            json={"response": "safe"}
        )
        assert respond_resp.status_code == 200
        
        # Guardian checks status
        response = requests.get(
            f"{BASE_URL}/api/checkin/status/{check_in_id}",
            headers=mother_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("status") == "safe", f"Expected status=safe, got {data.get('status')}"
        assert data.get("responded_at") is not None, "Missing responded_at"
        
        print(f"✓ Guardian sees safe status with responded_at={data.get('responded_at')}")
    
    def test_get_status_not_found(self, mother_headers):
        """Non-existent check-in returns 404"""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = requests.get(
            f"{BASE_URL}/api/checkin/status/{fake_id}",
            headers=mother_headers
        )
        assert response.status_code == 404, f"Expected 404 for fake check-in, got {response.status_code}"
        print(f"✓ Non-existent check-in returns 404")


class TestLatestCheckIn:
    """Test GET /api/checkin/latest/{child_user_id} - Guardian gets latest"""
    
    def test_get_latest_checkin(self, mother_headers, child_headers):
        """Guardian can get latest check-in for a child"""
        # Create a check-in
        create_resp = requests.post(
            f"{BASE_URL}/api/checkin/{CHILD_USER_ID}",
            headers=mother_headers
        )
        assert create_resp.status_code == 200
        check_in_id = create_resp.json().get("check_in_id")
        
        # Get latest
        response = requests.get(
            f"{BASE_URL}/api/checkin/latest/{CHILD_USER_ID}",
            headers=mother_headers
        )
        assert response.status_code == 200, f"Get latest failed: {response.text}"
        data = response.json()
        
        # Should return our check-in (most recent)
        assert data.get("check_in_id") == check_in_id, \
            f"Expected latest check-in {check_in_id}, got {data.get('check_in_id')}"
        assert data.get("status") == "pending"
        
        print(f"✓ Guardian sees latest check-in: {check_in_id}")
    
    def test_get_latest_no_checkins(self, mother_headers):
        """Returns status=none when no check-ins exist (for random child)"""
        random_child = "22222222-2222-2222-2222-222222222222"
        response = requests.get(
            f"{BASE_URL}/api/checkin/latest/{random_child}",
            headers=mother_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "none", f"Expected status=none, got {data}"
        print(f"✓ No check-ins returns status=none")


class TestDuplicateCheckInCancellation:
    """Test edge case: duplicate check-in cancels previous pending"""
    
    def test_duplicate_checkin_cancels_previous(self, mother_headers):
        """Creating new check-in cancels previous pending from same guardian"""
        # First check-in
        resp1 = requests.post(
            f"{BASE_URL}/api/checkin/{CHILD_USER_ID}",
            headers=mother_headers
        )
        assert resp1.status_code == 200
        check_in_1 = resp1.json().get("check_in_id")
        
        # Second check-in (should cancel first)
        resp2 = requests.post(
            f"{BASE_URL}/api/checkin/{CHILD_USER_ID}",
            headers=mother_headers
        )
        assert resp2.status_code == 200
        check_in_2 = resp2.json().get("check_in_id")
        
        assert check_in_1 != check_in_2, "Should create new check-in, not reuse"
        
        # Check status of first - should be expired/cancelled
        status_resp = requests.get(
            f"{BASE_URL}/api/checkin/status/{check_in_1}",
            headers=mother_headers
        )
        assert status_resp.status_code == 200
        status1 = status_resp.json().get("status")
        assert status1 == "expired", f"First check-in should be expired, got {status1}"
        
        # Check status of second - should be pending
        status_resp2 = requests.get(
            f"{BASE_URL}/api/checkin/status/{check_in_2}",
            headers=mother_headers
        )
        assert status_resp2.status_code == 200
        status2 = status_resp2.json().get("status")
        assert status2 == "pending", f"Second check-in should be pending, got {status2}"
        
        print(f"✓ Duplicate check-in cancelled previous: {check_in_1} -> expired, {check_in_2} -> pending")


class TestGuardianDashboardAlerts:
    """Test GET /api/guardian/dashboard/alerts - Check-in help responses appear in alerts"""
    
    def test_alerts_endpoint_returns_checkin_help_as_critical_alert(self, mother_headers, child_headers):
        """After child responds 'help', guardian's alerts API shows it as critical alert"""
        # Create check-in
        create_resp = requests.post(
            f"{BASE_URL}/api/checkin/{CHILD_USER_ID}",
            headers=mother_headers
        )
        assert create_resp.status_code == 200
        check_in_id = create_resp.json().get("check_in_id")
        
        # Child responds 'help'
        respond_resp = requests.post(
            f"{BASE_URL}/api/checkin/{check_in_id}/respond",
            headers=child_headers,
            json={"response": "help"}
        )
        assert respond_resp.status_code == 200
        
        # Guardian fetches alerts
        alerts_resp = requests.get(
            f"{BASE_URL}/api/guardian/dashboard/alerts",
            headers=mother_headers
        )
        assert alerts_resp.status_code == 200, f"Alerts endpoint failed: {alerts_resp.text}"
        data = alerts_resp.json()
        
        assert "alerts" in data, "Missing alerts array in response"
        alerts = data.get("alerts", [])
        
        # Find our check-in help alert
        found_alert = None
        for alert in alerts:
            # The check-in ID appears in the alert details
            if check_in_id in str(alert.get("details", "")) or alert.get("id") == check_in_id:
                found_alert = alert
                break
        
        assert found_alert is not None, f"Check-in {check_in_id} not found in alerts list"
        
        # Verify alert structure and severity
        assert found_alert.get("alert_type") == "help_requested", \
            f"Expected alert_type='help_requested', got {found_alert.get('alert_type')}"
        assert found_alert.get("severity") == "critical", \
            f"Expected severity='critical', got {found_alert.get('severity')}"
        assert "needs help" in found_alert.get("message", "").lower() or "help" in found_alert.get("message", "").lower()
        
        print(f"✓ Guardian sees help alert: id={found_alert.get('id')}, severity={found_alert.get('severity')}")
    
    def test_alerts_shows_child_name(self, mother_headers, child_headers):
        """Alert includes child's name for identification"""
        # Create and respond with help
        create_resp = requests.post(
            f"{BASE_URL}/api/checkin/{CHILD_USER_ID}",
            headers=mother_headers
        )
        check_in_id = create_resp.json().get("check_in_id")
        
        requests.post(
            f"{BASE_URL}/api/checkin/{check_in_id}/respond",
            headers=child_headers,
            json={"response": "help"}
        )
        
        # Get alerts
        alerts_resp = requests.get(
            f"{BASE_URL}/api/guardian/dashboard/alerts",
            headers=mother_headers
        )
        assert alerts_resp.status_code == 200
        alerts = alerts_resp.json().get("alerts", [])
        
        # Find our alert
        found = [a for a in alerts if check_in_id in str(a.get("details", "")) or a.get("id") == check_in_id]
        assert len(found) > 0, "Alert not found"
        
        alert = found[0]
        assert "user_name" in alert, "Missing user_name in alert"
        # The user_name should be the child's name (Kid Nischint)
        assert alert.get("user_name"), "user_name is empty"
        print(f"✓ Alert shows user_name: {alert.get('user_name')}")


class TestFullCheckInFlow:
    """Full flow tests: mother creates -> child sees -> responds -> mother sees status"""
    
    def test_full_flow_safe_response(self, mother_headers, child_headers):
        """Complete flow: mother creates check-in -> child responds safe -> mother sees safe"""
        print("\n=== Full Flow Test: Safe Response ===")
        
        # Step 1: Mother creates check-in
        create_resp = requests.post(
            f"{BASE_URL}/api/checkin/{CHILD_USER_ID}",
            headers=mother_headers
        )
        assert create_resp.status_code == 200
        check_in_id = create_resp.json().get("check_in_id")
        print(f"1. Mother created check-in: {check_in_id}")
        
        # Step 2: Child sees pending check-in
        pending_resp = requests.get(
            f"{BASE_URL}/api/checkin/pending",
            headers=child_headers
        )
        assert pending_resp.status_code == 200
        pending_list = pending_resp.json().get("check_ins", [])
        found = any(ci.get("check_in_id") == check_in_id for ci in pending_list)
        assert found, f"Child should see check-in {check_in_id} in pending list"
        print(f"2. Child sees pending check-in in list")
        
        # Step 3: Child responds 'safe'
        respond_resp = requests.post(
            f"{BASE_URL}/api/checkin/{check_in_id}/respond",
            headers=child_headers,
            json={"response": "safe"}
        )
        assert respond_resp.status_code == 200
        assert respond_resp.json().get("status") == "safe"
        print(f"3. Child responded 'I'm Safe'")
        
        # Step 4: Mother sees safe status
        status_resp = requests.get(
            f"{BASE_URL}/api/checkin/status/{check_in_id}",
            headers=mother_headers
        )
        assert status_resp.status_code == 200
        data = status_resp.json()
        assert data.get("status") == "safe", f"Mother should see status=safe, got {data.get('status')}"
        assert data.get("responded_at") is not None
        print(f"4. Mother sees status=safe, responded_at={data.get('responded_at')}")
        
        print("✓ Full flow SAFE completed successfully")
    
    def test_full_flow_help_response(self, mother_headers, child_headers):
        """Complete flow: mother creates check-in -> child responds help -> mother sees help"""
        print("\n=== Full Flow Test: Help Response ===")
        
        # Step 1: Mother creates check-in
        create_resp = requests.post(
            f"{BASE_URL}/api/checkin/{CHILD_USER_ID}",
            headers=mother_headers
        )
        assert create_resp.status_code == 200
        check_in_id = create_resp.json().get("check_in_id")
        print(f"1. Mother created check-in: {check_in_id}")
        
        # Step 2: Child sees pending
        pending_resp = requests.get(
            f"{BASE_URL}/api/checkin/pending",
            headers=child_headers
        )
        assert pending_resp.status_code == 200
        print(f"2. Child fetched pending check-ins")
        
        # Step 3: Child responds 'help'
        respond_resp = requests.post(
            f"{BASE_URL}/api/checkin/{check_in_id}/respond",
            headers=child_headers,
            json={"response": "help"}
        )
        assert respond_resp.status_code == 200
        assert respond_resp.json().get("status") == "help"
        print(f"3. Child responded 'Need Help'")
        
        # Step 4: Mother sees help status
        status_resp = requests.get(
            f"{BASE_URL}/api/checkin/status/{check_in_id}",
            headers=mother_headers
        )
        assert status_resp.status_code == 200
        data = status_resp.json()
        assert data.get("status") == "help", f"Mother should see status=help, got {data.get('status')}"
        print(f"4. Mother sees status=help (URGENT notification sent)")
        
        print("✓ Full flow HELP completed successfully")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
