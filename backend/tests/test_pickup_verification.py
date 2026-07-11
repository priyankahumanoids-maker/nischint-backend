# Pickup Verification Tests
# Tests pickup authorization, code generation, verification (code + proximity), cancellation, rate limiting
# Features: cryptographic 6-digit code, SHA-256 hashing, Haversine proximity check, 10-min expiry, 5-attempt rate limit

import pytest
import requests
import os
import random
from datetime import datetime, timedelta

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

# Test data
GUARDIAN_EMAIL = "nischint4parents@gmail.com"
GUARDIAN_PASSWORD = "secret123"
GUARDIAN_USER_ID = "7437a394-74ef-46a2-864f-6add0e7e8e60"

# Sample pickup location (Mumbai area)
PICKUP_LAT = 19.076
PICKUP_LNG = 72.8777
PICKUP_RADIUS_M = 50  # default radius

@pytest.fixture(scope="module")
def auth_token():
    """Get guardian auth token"""
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": GUARDIAN_EMAIL,
        "password": GUARDIAN_PASSWORD
    })
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["access_token"]

@pytest.fixture
def auth_headers(auth_token):
    """Auth headers for requests"""
    return {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}


class TestPickupAuthorize:
    """POST /api/pickup/authorize - Create pickup authorization"""

    def test_create_authorization_success(self, auth_headers):
        """Create authorization returns pickup_code + authorization_id"""
        scheduled = (datetime.utcnow() + timedelta(minutes=30)).isoformat() + "Z"
        payload = {
            "user_id": GUARDIAN_USER_ID,
            "authorized_person_name": "TEST_Uncle Ravi",
            "authorized_person_phone": "+919876543210",
            "verification_method": "pin",
            "pickup_location_lat": PICKUP_LAT,
            "pickup_location_lng": PICKUP_LNG,
            "pickup_radius_m": PICKUP_RADIUS_M,
            "pickup_location_name": "TEST School Gate",
            "scheduled_time": scheduled
        }
        resp = requests.post(f"{BASE_URL}/api/pickup/authorize", json=payload, headers=auth_headers)
        assert resp.status_code == 200, f"Failed: {resp.text}"
        data = resp.json()
        
        # Verify response structure
        assert "authorization_id" in data, "Missing authorization_id"
        assert "pickup_code" in data, "Missing pickup_code"
        assert "verification_method" in data
        assert "expires_at" in data
        assert "status" in data
        
        # Verify pickup code is 6 digits
        code = data["pickup_code"]
        assert len(code) == 6, f"Code length is {len(code)}, expected 6"
        assert code.isdigit(), f"Code {code} is not all digits"
        
        # Status should be pending
        assert data["status"] == "pending"
        print(f"PASS: Created authorization {data['authorization_id']} with code {code}")

    def test_create_authorization_qr_method(self, auth_headers):
        """QR verification method accepted"""
        scheduled = (datetime.utcnow() + timedelta(minutes=30)).isoformat() + "Z"
        payload = {
            "user_id": GUARDIAN_USER_ID,
            "authorized_person_name": "TEST_Aunt Maya",
            "verification_method": "qr",
            "pickup_location_lat": PICKUP_LAT,
            "pickup_location_lng": PICKUP_LNG,
            "scheduled_time": scheduled
        }
        resp = requests.post(f"{BASE_URL}/api/pickup/authorize", json=payload, headers=auth_headers)
        assert resp.status_code == 200, f"Failed: {resp.text}"
        data = resp.json()
        assert data["verification_method"] == "qr"
        print(f"PASS: QR method authorization created")

    def test_create_authorization_invalid_method(self, auth_headers):
        """Invalid verification method rejected"""
        scheduled = (datetime.utcnow() + timedelta(minutes=30)).isoformat() + "Z"
        payload = {
            "user_id": GUARDIAN_USER_ID,
            "authorized_person_name": "TEST_Invalid",
            "verification_method": "invalid",
            "pickup_location_lat": PICKUP_LAT,
            "pickup_location_lng": PICKUP_LNG,
            "scheduled_time": scheduled
        }
        resp = requests.post(f"{BASE_URL}/api/pickup/authorize", json=payload, headers=auth_headers)
        assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
        print("PASS: Invalid method rejected with 400")

    def test_create_authorization_no_auth(self):
        """Authorization requires authentication"""
        scheduled = (datetime.utcnow() + timedelta(minutes=30)).isoformat() + "Z"
        payload = {
            "user_id": GUARDIAN_USER_ID,
            "authorized_person_name": "TEST_NoAuth",
            "verification_method": "pin",
            "pickup_location_lat": PICKUP_LAT,
            "pickup_location_lng": PICKUP_LNG,
            "scheduled_time": scheduled
        }
        resp = requests.post(f"{BASE_URL}/api/pickup/authorize", json=payload)
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"
        print("PASS: Unauthenticated request rejected with 401")


class TestPickupVerify:
    """POST /api/pickup/verify - Verify pickup (code + proximity)"""

    def test_verify_success_within_radius(self, auth_headers):
        """Verify with correct code and within radius succeeds"""
        # First create authorization
        scheduled = (datetime.utcnow() + timedelta(minutes=30)).isoformat() + "Z"
        payload = {
            "user_id": GUARDIAN_USER_ID,
            "authorized_person_name": "TEST_Verify Success",
            "verification_method": "pin",
            "pickup_location_lat": PICKUP_LAT,
            "pickup_location_lng": PICKUP_LNG,
            "pickup_radius_m": 100,  # 100m radius
            "pickup_location_name": "TEST Verify Location",
            "scheduled_time": scheduled
        }
        create_resp = requests.post(f"{BASE_URL}/api/pickup/authorize", json=payload, headers=auth_headers)
        assert create_resp.status_code == 200, f"Create failed: {create_resp.text}"
        auth_data = create_resp.json()
        auth_id = auth_data["authorization_id"]
        pickup_code = auth_data["pickup_code"]
        
        # Now verify - at exact location (within radius)
        verify_payload = {
            "authorization_id": auth_id,
            "pickup_code": pickup_code,
            "lat": PICKUP_LAT,
            "lng": PICKUP_LNG
        }
        # Verify endpoint does NOT require auth (pickup person uses only code)
        verify_resp = requests.post(f"{BASE_URL}/api/pickup/verify", json=verify_payload, headers={"Content-Type": "application/json"})
        assert verify_resp.status_code == 200, f"Verify failed: {verify_resp.text}"
        result = verify_resp.json()
        
        assert result["status"] == "verified", f"Expected verified, got {result['status']}"
        assert result["authorization_id"] == auth_id
        assert "verified_at" in result
        assert "authorized_person" in result
        print(f"PASS: Verification succeeded for {auth_id}")

    def test_verify_invalid_code(self, auth_headers):
        """Invalid code returns invalid_code status"""
        # Create authorization
        scheduled = (datetime.utcnow() + timedelta(minutes=30)).isoformat() + "Z"
        payload = {
            "user_id": GUARDIAN_USER_ID,
            "authorized_person_name": "TEST_Invalid Code",
            "verification_method": "pin",
            "pickup_location_lat": PICKUP_LAT,
            "pickup_location_lng": PICKUP_LNG,
            "scheduled_time": scheduled
        }
        create_resp = requests.post(f"{BASE_URL}/api/pickup/authorize", json=payload, headers=auth_headers)
        assert create_resp.status_code == 200
        auth_data = create_resp.json()
        auth_id = auth_data["authorization_id"]
        
        # Verify with wrong code
        verify_payload = {
            "authorization_id": auth_id,
            "pickup_code": "000000",  # Wrong code
            "lat": PICKUP_LAT,
            "lng": PICKUP_LNG
        }
        verify_resp = requests.post(f"{BASE_URL}/api/pickup/verify", json=verify_payload, headers={"Content-Type": "application/json"})
        assert verify_resp.status_code == 200
        result = verify_resp.json()
        assert result["status"] == "invalid_code", f"Expected invalid_code, got {result}"
        print(f"PASS: Invalid code returns invalid_code status")

    def test_verify_proximity_failed(self, auth_headers):
        """Location outside radius returns proximity_failed with distance"""
        # Create authorization with small radius
        scheduled = (datetime.utcnow() + timedelta(minutes=30)).isoformat() + "Z"
        payload = {
            "user_id": GUARDIAN_USER_ID,
            "authorized_person_name": "TEST_Proximity Fail",
            "verification_method": "pin",
            "pickup_location_lat": PICKUP_LAT,
            "pickup_location_lng": PICKUP_LNG,
            "pickup_radius_m": 50,  # 50m radius
            "scheduled_time": scheduled
        }
        create_resp = requests.post(f"{BASE_URL}/api/pickup/authorize", json=payload, headers=auth_headers)
        assert create_resp.status_code == 200
        auth_data = create_resp.json()
        auth_id = auth_data["authorization_id"]
        pickup_code = auth_data["pickup_code"]
        
        # Verify from far location (~500m away)
        verify_payload = {
            "authorization_id": auth_id,
            "pickup_code": pickup_code,
            "lat": PICKUP_LAT + 0.005,  # ~500m north
            "lng": PICKUP_LNG
        }
        verify_resp = requests.post(f"{BASE_URL}/api/pickup/verify", json=verify_payload, headers={"Content-Type": "application/json"})
        assert verify_resp.status_code == 200
        result = verify_resp.json()
        
        assert result["status"] == "proximity_failed", f"Expected proximity_failed, got {result}"
        assert "distance_m" in result, "Missing distance_m in response"
        assert result["distance_m"] > 50, f"Distance {result['distance_m']} should be > 50m"
        print(f"PASS: Proximity check failed as expected, distance: {result['distance_m']}m")

    def test_verify_already_verified(self, auth_headers):
        """Already verified authorization returns already_verified"""
        # Create and verify first
        scheduled = (datetime.utcnow() + timedelta(minutes=30)).isoformat() + "Z"
        payload = {
            "user_id": GUARDIAN_USER_ID,
            "authorized_person_name": "TEST_Already Verified",
            "verification_method": "pin",
            "pickup_location_lat": PICKUP_LAT,
            "pickup_location_lng": PICKUP_LNG,
            "pickup_radius_m": 100,
            "scheduled_time": scheduled
        }
        create_resp = requests.post(f"{BASE_URL}/api/pickup/authorize", json=payload, headers=auth_headers)
        auth_data = create_resp.json()
        auth_id = auth_data["authorization_id"]
        pickup_code = auth_data["pickup_code"]
        
        # First verification
        verify_payload = {
            "authorization_id": auth_id,
            "pickup_code": pickup_code,
            "lat": PICKUP_LAT,
            "lng": PICKUP_LNG
        }
        first_resp = requests.post(f"{BASE_URL}/api/pickup/verify", json=verify_payload, headers={"Content-Type": "application/json"})
        assert first_resp.status_code == 200
        assert first_resp.json()["status"] == "verified"
        
        # Try to verify again
        second_resp = requests.post(f"{BASE_URL}/api/pickup/verify", json=verify_payload, headers={"Content-Type": "application/json"})
        assert second_resp.status_code == 200
        result = second_resp.json()
        assert result["status"] == "already_verified", f"Expected already_verified, got {result}"
        print(f"PASS: Already verified returns already_verified status")

    def test_verify_not_found(self):
        """Non-existent authorization returns 404"""
        verify_payload = {
            "authorization_id": "00000000-0000-0000-0000-000000000000",
            "pickup_code": "123456",
            "lat": PICKUP_LAT,
            "lng": PICKUP_LNG
        }
        resp = requests.post(f"{BASE_URL}/api/pickup/verify", json=verify_payload, headers={"Content-Type": "application/json"})
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"
        print("PASS: Non-existent authorization returns 404")


class TestPickupCancel:
    """POST /api/pickup/{id}/cancel - Cancel authorization"""

    def test_cancel_pending_authorization(self, auth_headers):
        """Cancel pending authorization succeeds"""
        # Create authorization
        scheduled = (datetime.utcnow() + timedelta(minutes=30)).isoformat() + "Z"
        payload = {
            "user_id": GUARDIAN_USER_ID,
            "authorized_person_name": "TEST_To Cancel",
            "verification_method": "pin",
            "pickup_location_lat": PICKUP_LAT,
            "pickup_location_lng": PICKUP_LNG,
            "scheduled_time": scheduled
        }
        create_resp = requests.post(f"{BASE_URL}/api/pickup/authorize", json=payload, headers=auth_headers)
        auth_id = create_resp.json()["authorization_id"]
        
        # Cancel
        cancel_resp = requests.post(f"{BASE_URL}/api/pickup/{auth_id}/cancel", headers=auth_headers)
        assert cancel_resp.status_code == 200, f"Cancel failed: {cancel_resp.text}"
        result = cancel_resp.json()
        assert result["status"] == "cancelled"
        print(f"PASS: Authorization cancelled successfully")

    def test_cancel_nonexistent(self, auth_headers):
        """Cancel non-existent authorization returns 404"""
        fake_id = "00000000-0000-0000-0000-000000000000"
        resp = requests.post(f"{BASE_URL}/api/pickup/{fake_id}/cancel", headers=auth_headers)
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"
        print("PASS: Non-existent authorization returns 404 on cancel")

    def test_cancel_requires_auth(self):
        """Cancel requires authentication"""
        fake_id = "00000000-0000-0000-0000-000000000000"
        resp = requests.post(f"{BASE_URL}/api/pickup/{fake_id}/cancel")
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"
        print("PASS: Cancel requires authentication")


class TestPickupListAuthorizations:
    """GET /api/pickup/authorizations - List authorizations for guardian"""

    def test_list_authorizations(self, auth_headers):
        """List returns authorizations array"""
        resp = requests.get(f"{BASE_URL}/api/pickup/authorizations", headers=auth_headers)
        assert resp.status_code == 200, f"Failed: {resp.text}"
        data = resp.json()
        
        assert "authorizations" in data
        assert "count" in data
        assert isinstance(data["authorizations"], list)
        print(f"PASS: Listed {data['count']} authorizations")

    def test_list_by_status(self, auth_headers):
        """List filtered by status"""
        resp = requests.get(f"{BASE_URL}/api/pickup/authorizations?status=pending", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        
        # All returned should be pending (if any)
        for auth in data["authorizations"]:
            assert auth["status"] == "pending", f"Expected pending, got {auth['status']}"
        print(f"PASS: Filtered by pending status, {data['count']} results")

    def test_list_requires_auth(self):
        """List requires authentication"""
        resp = requests.get(f"{BASE_URL}/api/pickup/authorizations")
        assert resp.status_code == 401
        print("PASS: List requires authentication")


class TestPickupEvents:
    """GET /api/pickup/events - List pickup events (audit log)"""

    def test_list_events(self, auth_headers):
        """List returns events array"""
        resp = requests.get(f"{BASE_URL}/api/pickup/events", headers=auth_headers)
        assert resp.status_code == 200, f"Failed: {resp.text}"
        data = resp.json()
        
        assert "events" in data
        assert "count" in data
        assert isinstance(data["events"], list)
        print(f"PASS: Listed {data['count']} pickup events")

    def test_list_events_with_limit(self, auth_headers):
        """List with limit parameter"""
        resp = requests.get(f"{BASE_URL}/api/pickup/events?limit=5", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) <= 5
        print(f"PASS: Listed events with limit=5")

    def test_list_events_requires_auth(self):
        """Events list requires authentication"""
        resp = requests.get(f"{BASE_URL}/api/pickup/events")
        assert resp.status_code == 401
        print("PASS: Events list requires authentication")


class TestCodeGeneration:
    """Test 6-digit cryptographic code generation properties"""

    def test_code_is_6_digits(self, auth_headers):
        """Generated code is exactly 6 digits"""
        codes = []
        for i in range(3):
            scheduled = (datetime.utcnow() + timedelta(minutes=30+i)).isoformat() + "Z"
            payload = {
                "user_id": GUARDIAN_USER_ID,
                "authorized_person_name": f"TEST_Code Gen {i}",
                "verification_method": "pin",
                "pickup_location_lat": PICKUP_LAT,
                "pickup_location_lng": PICKUP_LNG,
                "scheduled_time": scheduled
            }
            resp = requests.post(f"{BASE_URL}/api/pickup/authorize", json=payload, headers=auth_headers)
            if resp.status_code == 200:
                code = resp.json()["pickup_code"]
                assert len(code) == 6, f"Code {code} is not 6 digits"
                assert code.isdigit(), f"Code {code} is not numeric"
                codes.append(code)
        
        # Check codes are unique (cryptographically random should not repeat)
        assert len(codes) == len(set(codes)), f"Codes are not unique: {codes}"
        print(f"PASS: Generated {len(codes)} unique 6-digit codes: {codes}")


class TestExpiryVerification:
    """Test 10-minute expiry behavior"""

    def test_expiry_time_calculation(self, auth_headers):
        """Expiry is scheduled_time + 10 minutes"""
        scheduled_time = datetime.utcnow() + timedelta(minutes=30)
        scheduled = scheduled_time.isoformat() + "Z"
        payload = {
            "user_id": GUARDIAN_USER_ID,
            "authorized_person_name": "TEST_Expiry Check",
            "verification_method": "pin",
            "pickup_location_lat": PICKUP_LAT,
            "pickup_location_lng": PICKUP_LNG,
            "scheduled_time": scheduled
        }
        resp = requests.post(f"{BASE_URL}/api/pickup/authorize", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        
        expires_at = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
        # Expiry should be ~10 minutes after scheduled time
        expected_expiry = scheduled_time + timedelta(minutes=10)
        
        # Allow 1 minute tolerance for timing
        diff = abs((expires_at.replace(tzinfo=None) - expected_expiry).total_seconds())
        assert diff < 60, f"Expiry time mismatch: expected ~{expected_expiry}, got {expires_at}"
        print(f"PASS: Expiry correctly set to scheduled_time + 10 minutes")


class TestRateLimiting:
    """Test 5-attempt rate limiting per authorization"""

    def test_rate_limit_after_5_attempts(self, auth_headers):
        """After 5 failed attempts, returns rate_limited"""
        # Create authorization
        scheduled = (datetime.utcnow() + timedelta(minutes=30)).isoformat() + "Z"
        payload = {
            "user_id": GUARDIAN_USER_ID,
            "authorized_person_name": "TEST_Rate Limit",
            "verification_method": "pin",
            "pickup_location_lat": PICKUP_LAT,
            "pickup_location_lng": PICKUP_LNG,
            "pickup_radius_m": 100,
            "scheduled_time": scheduled
        }
        create_resp = requests.post(f"{BASE_URL}/api/pickup/authorize", json=payload, headers=auth_headers)
        auth_id = create_resp.json()["authorization_id"]
        
        # Make 5 failed attempts with wrong code
        verify_payload = {
            "authorization_id": auth_id,
            "pickup_code": "000000",
            "lat": PICKUP_LAT,
            "lng": PICKUP_LNG
        }
        
        for i in range(5):
            resp = requests.post(f"{BASE_URL}/api/pickup/verify", json=verify_payload, headers={"Content-Type": "application/json"})
            # Should still work for first 5 attempts (return invalid_code)
            assert resp.status_code == 200, f"Attempt {i+1} failed: {resp.text}"
        
        # 6th attempt should be rate limited (429)
        resp = requests.post(f"{BASE_URL}/api/pickup/verify", json=verify_payload, headers={"Content-Type": "application/json"})
        assert resp.status_code == 429, f"Expected 429 rate limited, got {resp.status_code}: {resp.text}"
        print(f"PASS: Rate limited after 5 attempts")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
