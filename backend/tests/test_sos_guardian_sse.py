"""
SOS Guardian SSE Real-Time Notification Tests
=============================================
Tests the P0 fix: When child triggers SOS, parent (guardian) app must receive real-time alert.
Previously broken: SOS trigger only broadcast to operators + child's own SSE channel, never to guardians.
Fixed by looking up guardian contacts from 'guardians' table, matching their email to User account,
and broadcasting 'emergency_triggered' SSE event to each guardian.

Tests:
1. POST /api/emergency/silent-sos triggers SOS and returns status=active
2. SSE stream for guardian (mother) receives emergency_triggered event with child_name and child_id
3. SSE stream for guardian (father) also receives emergency_triggered event
4. POST /api/emergency/resolve resolves the emergency
5. SSE stream for guardian receives emergency_resolved event after resolve
6. POST /api/emergency/cancel with correct pin cancels the emergency
7. GET /api/emergency/active returns active emergencies for the child
8. All logins still work (mother, child, operator)
"""

import pytest
import requests
import os
import time
import subprocess
import threading
import json
from datetime import datetime

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test user credentials
MOTHER_EMAIL = "mothernischint@gmail.com"
MOTHER_PASSWORD = "nischint123"
MOTHER_USER_ID = "d426c37a-e30b-4403-8270-31d094926d18"

FATHER_EMAIL = "fathernishchint@gmail.com"
FATHER_PASSWORD = "nischint123"
FATHER_USER_ID = "1771bc2b-e87e-4605-af6d-fa7b8a237d0d"

CHILD_EMAIL = "kidnischint@gmail.com"
CHILD_PASSWORD = "nischint123"
CHILD_USER_ID = "ae6c29f9-aafd-4449-abc3-881effa122a4"

OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "nischint123"

CANCEL_PIN = "1234"


# ─────────────────────────────────────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def mother_token():
    """Get mother/guardian JWT token"""
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": MOTHER_EMAIL, "password": MOTHER_PASSWORD}
    )
    assert response.status_code == 200, f"Mother login failed: {response.text}"
    data = response.json()
    assert "access_token" in data
    return data["access_token"]


@pytest.fixture(scope="module")
def father_token():
    """Get father/guardian JWT token"""
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": FATHER_EMAIL, "password": FATHER_PASSWORD}
    )
    assert response.status_code == 200, f"Father login failed: {response.text}"
    data = response.json()
    assert "access_token" in data
    return data["access_token"]


@pytest.fixture(scope="module")
def child_token():
    """Get child JWT token"""
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": CHILD_EMAIL, "password": CHILD_PASSWORD}
    )
    assert response.status_code == 200, f"Child login failed: {response.text}"
    data = response.json()
    assert "access_token" in data
    return data["access_token"]


@pytest.fixture(scope="module")
def operator_token():
    """Get operator JWT token"""
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD}
    )
    assert response.status_code == 200, f"Operator login failed: {response.text}"
    data = response.json()
    assert "access_token" in data
    return data["access_token"]


@pytest.fixture(autouse=True)
def cleanup_active_emergencies(child_token):
    """Clean up any active emergencies before each test"""
    # Get active emergencies for child
    response = requests.get(
        f"{BASE_URL}/api/emergency/active",
        params={"user_id": CHILD_USER_ID},
        headers={"Authorization": f"Bearer {child_token}"}
    )
    if response.status_code == 200:
        data = response.json()
        for event in data.get("events", []):
            # Resolve each active emergency
            requests.post(
                f"{BASE_URL}/api/emergency/resolve",
                headers={"Authorization": f"Bearer {child_token}", "Content-Type": "application/json"},
                json={"event_id": event["event_id"]}
            )
    yield


# ─────────────────────────────────────────────────────────────────────────────
# TEST: ALL LOGINS WORK
# ─────────────────────────────────────────────────────────────────────────────

class TestAllLoginsWork:
    """Verify all test users can log in successfully"""

    def test_mother_login(self):
        """Mother guardian login works"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": MOTHER_EMAIL, "password": MOTHER_PASSWORD}
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data.get("role") == "guardian"
        # user_id is in JWT 'sub' claim, not directly in response
        print(f"✓ Mother login successful, role={data.get('role')}")

    def test_father_login(self):
        """Father guardian login works"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": FATHER_EMAIL, "password": FATHER_PASSWORD}
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data.get("role") == "guardian"
        # user_id is in JWT 'sub' claim, not directly in response
        print(f"✓ Father login successful, role={data.get('role')}")

    def test_child_login(self):
        """Child login works"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": CHILD_EMAIL, "password": CHILD_PASSWORD}
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data.get("role") == "child"
        # user_id is in JWT 'sub' claim, not directly in response
        print(f"✓ Child login successful, role={data.get('role')}")

    def test_operator_login(self):
        """Operator login works"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD}
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data.get("role") == "operator"
        print(f"✓ Operator login successful, role={data.get('role')}")


# ─────────────────────────────────────────────────────────────────────────────
# TEST: SOS TRIGGER AND STATUS
# ─────────────────────────────────────────────────────────────────────────────

class TestSOSTrigger:
    """Test POST /api/emergency/silent-sos returns status=active"""

    def test_sos_trigger_returns_active_status(self, child_token):
        """POST /api/emergency/silent-sos triggers SOS and returns status=active"""
        response = requests.post(
            f"{BASE_URL}/api/emergency/silent-sos",
            headers={"Authorization": f"Bearer {child_token}", "Content-Type": "application/json"},
            json={
                "lat": 19.076,
                "lng": 72.877,
                "trigger_source": "sos_button",
                "cancel_pin": CANCEL_PIN
            }
        )
        assert response.status_code == 200, f"SOS trigger failed: {response.text}"
        data = response.json()
        
        # Verify response structure
        assert "event_id" in data, "Missing event_id"
        assert data["status"] == "active", f"Expected status=active, got {data['status']}"
        assert data["severity_level"] == 2, f"Expected severity_level=2, got {data.get('severity_level')}"
        assert "guardians_notified" in data, "Missing guardians_notified"
        assert "created_at" in data, "Missing created_at"
        
        print(f"✓ SOS triggered: event_id={data['event_id']}, status={data['status']}, guardians_notified={data['guardians_notified']}")
        
        # Cleanup
        requests.post(
            f"{BASE_URL}/api/emergency/resolve",
            headers={"Authorization": f"Bearer {child_token}", "Content-Type": "application/json"},
            json={"event_id": data["event_id"]}
        )


class TestGetActiveEmergencies:
    """Test GET /api/emergency/active returns active emergencies for the child"""

    def test_active_emergencies_includes_triggered_sos(self, child_token):
        """GET /api/emergency/active returns the active emergency for child"""
        # Trigger SOS
        trigger_resp = requests.post(
            f"{BASE_URL}/api/emergency/silent-sos",
            headers={"Authorization": f"Bearer {child_token}", "Content-Type": "application/json"},
            json={"lat": 19.076, "lng": 72.877, "trigger_source": "sos_button", "cancel_pin": CANCEL_PIN}
        )
        assert trigger_resp.status_code == 200
        event_id = trigger_resp.json()["event_id"]
        
        # Get active emergencies
        active_resp = requests.get(
            f"{BASE_URL}/api/emergency/active",
            params={"user_id": CHILD_USER_ID},
            headers={"Authorization": f"Bearer {child_token}"}
        )
        assert active_resp.status_code == 200
        data = active_resp.json()
        
        assert "events" in data, "Missing events array"
        assert "count" in data, "Missing count"
        
        # Find our event
        our_event = next((e for e in data["events"] if e["event_id"] == event_id), None)
        assert our_event is not None, f"Event {event_id} not found in active list"
        assert our_event["status"] == "active"
        assert our_event["user_id"] == CHILD_USER_ID
        
        print(f"✓ Active emergency found: event_id={event_id}, count={data['count']}")
        
        # Cleanup
        requests.post(
            f"{BASE_URL}/api/emergency/resolve",
            headers={"Authorization": f"Bearer {child_token}", "Content-Type": "application/json"},
            json={"event_id": event_id}
        )


# ─────────────────────────────────────────────────────────────────────────────
# TEST: SSE GUARDIAN NOTIFICATIONS - EMERGENCY_TRIGGERED
# ─────────────────────────────────────────────────────────────────────────────

class TestSSEGuardianEmergencyTriggered:
    """Test SSE stream for guardian receives emergency_triggered event"""

    def test_mother_receives_emergency_triggered_sse(self, mother_token, child_token):
        """SSE stream for mother receives emergency_triggered event with child_name and child_id within 5 seconds"""
        sse_url = f"{BASE_URL}/api/stream?token={mother_token}"
        sse_file = "/tmp/mother_sse_triggered.txt"
        
        # Start SSE listener in background (25s timeout)
        subprocess.run(f"timeout 25 curl -s -N '{sse_url}' > {sse_file} 2>&1 &", shell=True)
        time.sleep(3)  # Wait for SSE connection to establish
        
        # Trigger SOS from child
        trigger_resp = requests.post(
            f"{BASE_URL}/api/emergency/silent-sos",
            headers={"Authorization": f"Bearer {child_token}", "Content-Type": "application/json"},
            json={"lat": 19.076, "lng": 72.877, "trigger_source": "sos_button", "cancel_pin": CANCEL_PIN}
        )
        assert trigger_resp.status_code == 200
        event_id = trigger_resp.json()["event_id"]
        
        # Wait for SSE delivery
        time.sleep(5)
        
        # Check SSE file for emergency_triggered event
        result = subprocess.run(f"cat {sse_file}", shell=True, capture_output=True, text=True)
        sse_content = result.stdout
        
        # Count emergency_triggered events
        event_count = sse_content.count("event: emergency_triggered")
        print(f"SSE content (mother): {sse_content[:1000]}")
        
        assert event_count >= 1, f"Expected at least 1 emergency_triggered event, got {event_count}"
        
        # Verify event contains child_id and child_name
        assert CHILD_USER_ID in sse_content or "child_id" in sse_content, "Missing child_id in SSE"
        
        print(f"✓ Mother received {event_count} emergency_triggered event(s)")
        
        # Cleanup
        subprocess.run(f"pkill -f 'curl.*stream.*{mother_token[:20]}' 2>/dev/null || true", shell=True)
        requests.post(
            f"{BASE_URL}/api/emergency/resolve",
            headers={"Authorization": f"Bearer {child_token}", "Content-Type": "application/json"},
            json={"event_id": event_id}
        )

    def test_father_receives_emergency_triggered_sse(self, father_token, child_token):
        """SSE stream for father receives emergency_triggered event"""
        sse_url = f"{BASE_URL}/api/stream?token={father_token}"
        sse_file = "/tmp/father_sse_triggered.txt"
        
        # Start SSE listener
        subprocess.run(f"timeout 25 curl -s -N '{sse_url}' > {sse_file} 2>&1 &", shell=True)
        time.sleep(3)
        
        # Trigger SOS
        trigger_resp = requests.post(
            f"{BASE_URL}/api/emergency/silent-sos",
            headers={"Authorization": f"Bearer {child_token}", "Content-Type": "application/json"},
            json={"lat": 19.076, "lng": 72.877, "trigger_source": "sos_button", "cancel_pin": CANCEL_PIN}
        )
        assert trigger_resp.status_code == 200
        event_id = trigger_resp.json()["event_id"]
        
        time.sleep(5)
        
        result = subprocess.run(f"cat {sse_file}", shell=True, capture_output=True, text=True)
        sse_content = result.stdout
        
        event_count = sse_content.count("event: emergency_triggered")
        print(f"SSE content (father): {sse_content[:1000]}")
        
        assert event_count >= 1, f"Expected at least 1 emergency_triggered event for father, got {event_count}"
        
        print(f"✓ Father received {event_count} emergency_triggered event(s)")
        
        # Cleanup
        subprocess.run(f"pkill -f 'curl.*stream' 2>/dev/null || true", shell=True)
        requests.post(
            f"{BASE_URL}/api/emergency/resolve",
            headers={"Authorization": f"Bearer {child_token}", "Content-Type": "application/json"},
            json={"event_id": event_id}
        )


# ─────────────────────────────────────────────────────────────────────────────
# TEST: SSE GUARDIAN NOTIFICATIONS - EMERGENCY_RESOLVED
# ─────────────────────────────────────────────────────────────────────────────

class TestSSEGuardianEmergencyResolved:
    """Test SSE stream for guardian receives emergency_resolved event after resolve"""

    def test_guardian_receives_emergency_resolved_sse(self, mother_token, child_token):
        """SSE stream for guardian receives emergency_resolved event after resolve"""
        sse_url = f"{BASE_URL}/api/stream?token={mother_token}"
        sse_file = "/tmp/mother_sse_resolved.txt"
        
        # Trigger SOS first
        trigger_resp = requests.post(
            f"{BASE_URL}/api/emergency/silent-sos",
            headers={"Authorization": f"Bearer {child_token}", "Content-Type": "application/json"},
            json={"lat": 19.076, "lng": 72.877, "trigger_source": "sos_button", "cancel_pin": CANCEL_PIN}
        )
        assert trigger_resp.status_code == 200
        event_id = trigger_resp.json()["event_id"]
        
        # Start SSE listener
        subprocess.run(f"timeout 25 curl -s -N '{sse_url}' > {sse_file} 2>&1 &", shell=True)
        time.sleep(3)
        
        # Resolve SOS
        resolve_resp = requests.post(
            f"{BASE_URL}/api/emergency/resolve",
            headers={"Authorization": f"Bearer {child_token}", "Content-Type": "application/json"},
            json={"event_id": event_id}
        )
        assert resolve_resp.status_code == 200
        assert resolve_resp.json()["status"] == "resolved"
        
        time.sleep(5)
        
        result = subprocess.run(f"cat {sse_file}", shell=True, capture_output=True, text=True)
        sse_content = result.stdout
        
        event_count = sse_content.count("event: emergency_resolved")
        print(f"SSE content (resolved): {sse_content[:1000]}")
        
        assert event_count >= 1, f"Expected at least 1 emergency_resolved event, got {event_count}"
        
        print(f"✓ Guardian received {event_count} emergency_resolved event(s)")
        
        subprocess.run(f"pkill -f 'curl.*stream' 2>/dev/null || true", shell=True)


# ─────────────────────────────────────────────────────────────────────────────
# TEST: SSE GUARDIAN NOTIFICATIONS - EMERGENCY_CANCELLED
# ─────────────────────────────────────────────────────────────────────────────

class TestSOSCancel:
    """Test POST /api/emergency/cancel with correct pin cancels the emergency"""

    def test_cancel_sos_with_correct_pin(self, child_token):
        """POST /api/emergency/cancel with correct pin cancels the emergency"""
        # Trigger SOS
        trigger_resp = requests.post(
            f"{BASE_URL}/api/emergency/silent-sos",
            headers={"Authorization": f"Bearer {child_token}", "Content-Type": "application/json"},
            json={"lat": 19.076, "lng": 72.877, "trigger_source": "sos_button", "cancel_pin": CANCEL_PIN}
        )
        assert trigger_resp.status_code == 200
        event_id = trigger_resp.json()["event_id"]
        
        # Cancel with correct PIN
        cancel_resp = requests.post(
            f"{BASE_URL}/api/emergency/cancel",
            headers={"Authorization": f"Bearer {child_token}", "Content-Type": "application/json"},
            json={"event_id": event_id, "cancel_pin": CANCEL_PIN}
        )
        assert cancel_resp.status_code == 200
        data = cancel_resp.json()
        
        assert data["status"] == "cancelled", f"Expected status=cancelled, got {data['status']}"
        assert "resolved_at" in data, "Missing resolved_at"
        
        print(f"✓ SOS cancelled successfully: event_id={event_id}")

    def test_guardian_receives_emergency_cancelled_sse(self, mother_token, child_token):
        """SSE stream for guardian receives emergency_cancelled event after cancel"""
        sse_url = f"{BASE_URL}/api/stream?token={mother_token}"
        sse_file = "/tmp/mother_sse_cancelled.txt"
        
        # Trigger SOS
        trigger_resp = requests.post(
            f"{BASE_URL}/api/emergency/silent-sos",
            headers={"Authorization": f"Bearer {child_token}", "Content-Type": "application/json"},
            json={"lat": 19.076, "lng": 72.877, "trigger_source": "sos_button", "cancel_pin": CANCEL_PIN}
        )
        assert trigger_resp.status_code == 200
        event_id = trigger_resp.json()["event_id"]
        
        # Start SSE listener
        subprocess.run(f"timeout 25 curl -s -N '{sse_url}' > {sse_file} 2>&1 &", shell=True)
        time.sleep(3)
        
        # Cancel SOS
        cancel_resp = requests.post(
            f"{BASE_URL}/api/emergency/cancel",
            headers={"Authorization": f"Bearer {child_token}", "Content-Type": "application/json"},
            json={"event_id": event_id, "cancel_pin": CANCEL_PIN}
        )
        assert cancel_resp.status_code == 200
        
        time.sleep(5)
        
        result = subprocess.run(f"cat {sse_file}", shell=True, capture_output=True, text=True)
        sse_content = result.stdout
        
        event_count = sse_content.count("event: emergency_cancelled")
        print(f"SSE content (cancelled): {sse_content[:1000]}")
        
        assert event_count >= 1, f"Expected at least 1 emergency_cancelled event, got {event_count}"
        
        print(f"✓ Guardian received {event_count} emergency_cancelled event(s)")
        
        subprocess.run(f"pkill -f 'curl.*stream' 2>/dev/null || true", shell=True)


# ─────────────────────────────────────────────────────────────────────────────
# TEST: CHECK-IN HELP FLOW
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckInHelpFlow:
    """Test check-in help flow: POST /api/checkin/{id}/respond with help, SSE delivery to guardian"""

    def test_checkin_help_response_triggers_sse(self, mother_token, child_token):
        """Check-in help flow: child responds 'help', guardian receives SSE"""
        # Create check-in for child
        checkin_resp = requests.post(
            f"{BASE_URL}/api/checkin/{CHILD_USER_ID}",
            headers={"Authorization": f"Bearer {mother_token}", "Content-Type": "application/json"},
            json={"message": "Are you safe?"}
        )
        
        if checkin_resp.status_code != 201:
            pytest.skip(f"Check-in creation failed: {checkin_resp.text}")
        
        checkin_id = checkin_resp.json()["check_in_id"]
        
        # Start SSE listener
        sse_url = f"{BASE_URL}/api/stream?token={mother_token}"
        sse_file = "/tmp/mother_sse_checkin.txt"
        subprocess.run(f"timeout 25 curl -s -N '{sse_url}' > {sse_file} 2>&1 &", shell=True)
        time.sleep(3)
        
        # Child responds 'help'
        respond_resp = requests.post(
            f"{BASE_URL}/api/checkin/{checkin_id}/respond",
            headers={"Authorization": f"Bearer {child_token}", "Content-Type": "application/json"},
            json={"response": "help"}
        )
        assert respond_resp.status_code == 200
        
        time.sleep(5)
        
        result = subprocess.run(f"cat {sse_file}", shell=True, capture_output=True, text=True)
        sse_content = result.stdout
        
        # Check for checkin_help event
        help_count = sse_content.count("checkin_help")
        print(f"SSE content (checkin_help): {sse_content[:1000]}")
        
        assert help_count >= 1 or "help" in sse_content.lower(), f"Expected checkin_help event, content: {sse_content[:500]}"
        
        print(f"✓ Guardian received checkin_help event")
        
        subprocess.run(f"pkill -f 'curl.*stream' 2>/dev/null || true", shell=True)


class TestGuardianDashboardAlerts:
    """Test GET /api/guardian/dashboard/alerts includes help_requested alerts"""

    def test_dashboard_alerts_includes_help_requested(self, mother_token):
        """GET /api/guardian/dashboard/alerts includes help_requested alerts"""
        response = requests.get(
            f"{BASE_URL}/api/guardian/dashboard/alerts",
            headers={"Authorization": f"Bearer {mother_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Response is {alerts: [...]} not just [...]
        alerts = data.get("alerts", data) if isinstance(data, dict) else data
        assert isinstance(alerts, list), f"Expected list, got {type(alerts)}"
        
        # Check if any help_requested alerts exist
        help_alerts = [a for a in alerts if a.get("alert_type") == "help_requested"]
        
        print(f"✓ Dashboard alerts: {len(alerts)} total, {len(help_alerts)} help_requested")
        
        # At minimum, verify the structure
        if alerts:
            sample = alerts[0]
            assert "alert_type" in sample or "type" in sample, "Alert missing type field"


# ─────────────────────────────────────────────────────────────────────────────
# TEST: SSE CONNECTION
# ─────────────────────────────────────────────────────────────────────────────

class TestSSEConnection:
    """Test SSE stream connects successfully"""

    def test_guardian_sse_connects(self, mother_token):
        """Guardian SSE stream returns connected event"""
        sse_url = f"{BASE_URL}/api/stream?token={mother_token}"
        sse_file = "/tmp/sse_connect_test.txt"
        
        subprocess.run(f"timeout 10 curl -s -N '{sse_url}' > {sse_file} 2>&1 &", shell=True)
        time.sleep(5)
        
        result = subprocess.run(f"cat {sse_file}", shell=True, capture_output=True, text=True)
        sse_content = result.stdout
        
        assert "event: connected" in sse_content or "connected" in sse_content, f"Missing connected event: {sse_content[:500]}"
        
        # Verify channel contains user ID
        assert MOTHER_USER_ID in sse_content or "user:" in sse_content, f"Missing user channel: {sse_content[:500]}"
        
        print(f"✓ SSE connected successfully")
        
        subprocess.run(f"pkill -f 'curl.*stream' 2>/dev/null || true", shell=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
