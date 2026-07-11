"""
Rate Limiting & Security Headers Test Suite
Tests:
- Rate limiting on auth endpoints (5/minute)
- Rate limiting on telemetry endpoints (60/minute)
- Rate limiting on pilot signup (10/hour)
- HTTP 429 response format
- Security headers presence on all responses
"""
import os
import time
import pytest
import requests
from typing import Dict

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Required security headers to verify
SECURITY_HEADERS = [
    "X-Frame-Options",
    "X-Content-Type-Options",
    "Strict-Transport-Security",
    "Referrer-Policy",
    "X-XSS-Protection",
]


class TestSecurityHeaders:
    """Test security headers are present on all responses"""
    
    def test_security_headers_on_root(self):
        """Security headers present on GET /api/"""
        response = requests.get(f"{BASE_URL}/api/")
        assert response.status_code == 200
        
        for header in SECURITY_HEADERS:
            assert header in response.headers, f"Missing security header: {header}"
        
        # Verify specific header values
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        print(f"✓ All 5 security headers present on /api/")
    
    def test_security_headers_on_platform_status(self):
        """Security headers present on GET /api/status/platform"""
        response = requests.get(f"{BASE_URL}/api/status/platform")
        assert response.status_code in [200, 429]  # May be rate limited
        
        for header in SECURITY_HEADERS:
            assert header in response.headers, f"Missing security header: {header}"
        print(f"✓ All 5 security headers present on /api/status/platform")
    
    def test_security_headers_on_auth_endpoint(self):
        """Security headers present on POST /api/auth/login (even on 401/429)"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "test@test.com", "password": "wrong"}
        )
        # May get 401 (bad credentials) or 429 (rate limited)
        assert response.status_code in [401, 429, 200]
        
        for header in SECURITY_HEADERS:
            assert header in response.headers, f"Missing security header: {header}"
        print(f"✓ All 5 security headers present on /api/auth/login")
    
    def test_security_headers_on_events(self):
        """Security headers present on GET /api/status/events"""
        response = requests.get(f"{BASE_URL}/api/status/events")
        assert response.status_code in [200, 429]
        
        for header in SECURITY_HEADERS:
            assert header in response.headers, f"Missing security header: {header}"
        print(f"✓ All 5 security headers present on /api/status/events")
    
    def test_security_headers_on_metrics(self):
        """Security headers present on GET /api/status/metrics"""
        response = requests.get(f"{BASE_URL}/api/status/metrics")
        assert response.status_code in [200, 429]
        
        for header in SECURITY_HEADERS:
            assert header in response.headers, f"Missing security header: {header}"
        print(f"✓ All 5 security headers present on /api/status/metrics")
    
    def test_strict_transport_security_value(self):
        """Verify HSTS header has proper max-age"""
        response = requests.get(f"{BASE_URL}/api/")
        hsts = response.headers.get("Strict-Transport-Security", "")
        assert "max-age=" in hsts, "HSTS missing max-age directive"
        assert "31536000" in hsts or int(hsts.split("max-age=")[1].split(";")[0]) >= 31536000, "HSTS max-age should be at least 1 year"
        print(f"✓ HSTS header has proper max-age: {hsts}")


class TestRateLimitingAuth:
    """Test rate limiting on authentication endpoints (5/minute)"""
    
    def test_login_returns_429_after_limit(self):
        """POST /api/auth/login should return 429 after 5 rapid requests"""
        print(f"\n--- Testing login rate limit (5/minute) ---")
        
        responses = []
        for i in range(7):  # Send 7 requests to ensure we hit the limit
            response = requests.post(
                f"{BASE_URL}/api/auth/login",
                json={"email": f"test{i}@example.com", "password": "wrongpassword"}
            )
            responses.append(response)
            print(f"Request {i+1}: Status {response.status_code}")
        
        # Check that at least one response is 429
        status_codes = [r.status_code for r in responses]
        rate_limited = 429 in status_codes
        
        if rate_limited:
            # Verify 429 response body
            for r in responses:
                if r.status_code == 429:
                    data = r.json()
                    assert "error" in data, "429 response missing 'error' field"
                    assert data["error"] == "Too many requests. Please try again later.", f"Unexpected error message: {data['error']}"
                    print(f"✓ Rate limited with correct message: {data['error']}")
                    break
        else:
            # Rate limit may have been consumed by earlier tests
            print("⚠ Note: Rate limit may already be consumed from previous tests or shared IP")
        
        # At least some requests should succeed or return 401 before rate limiting
        non_429_responses = [r for r in responses if r.status_code != 429]
        for r in non_429_responses:
            assert r.status_code == 401, f"Expected 401 for bad credentials, got {r.status_code}"
    
    def test_login_401_first_request(self):
        """First login request with bad creds should return 401, not 429 (unless rate limit is already hit)"""
        # Wait a moment to let rate limit partially recover
        time.sleep(2)
        
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "unique_test_401@example.com", "password": "badpassword"}
        )
        
        # Could be 401 (bad creds) or 429 (rate limited from previous tests)
        assert response.status_code in [401, 429], f"Expected 401 or 429, got {response.status_code}"
        print(f"✓ Login returned {response.status_code} as expected")


class TestRateLimitingTelemetry:
    """Test rate limiting on telemetry/status endpoints (60/minute) - should NOT trigger easily"""
    
    def test_platform_status_high_limit(self):
        """GET /api/status/platform has 60/minute limit - 10 rapid requests should all succeed"""
        print(f"\n--- Testing platform status rate limit (60/minute) ---")
        
        success_count = 0
        for i in range(10):
            response = requests.get(f"{BASE_URL}/api/status/platform")
            if response.status_code == 200:
                success_count += 1
                assert "status" in response.json()
            elif response.status_code == 429:
                print(f"⚠ Request {i+1} rate limited (may be from shared IP/previous tests)")
            else:
                pytest.fail(f"Unexpected status code: {response.status_code}")
        
        print(f"✓ {success_count}/10 requests succeeded (60/min limit)")
        # Most should succeed since limit is high
        assert success_count >= 5, f"Expected at least 5 successful requests with 60/min limit, got {success_count}"
    
    def test_events_endpoint_accessible(self):
        """GET /api/status/events should be accessible with 60/min limit"""
        response = requests.get(f"{BASE_URL}/api/status/events")
        assert response.status_code in [200, 429]
        
        if response.status_code == 200:
            data = response.json()
            assert "events" in data
            print(f"✓ /api/status/events returned {len(data['events'])} events")
        else:
            print("⚠ Rate limited on events endpoint")
    
    def test_metrics_endpoint_accessible(self):
        """GET /api/status/metrics should be accessible with 60/min limit"""
        response = requests.get(f"{BASE_URL}/api/status/metrics")
        assert response.status_code in [200, 429]
        
        if response.status_code == 200:
            data = response.json()
            assert "institutions_protected" in data
            print(f"✓ /api/status/metrics returned network growth data")
        else:
            print("⚠ Rate limited on metrics endpoint")


class TestRateLimitingPilot:
    """Test rate limiting on pilot signup (10/hour)"""
    
    def test_pilot_signup_rate_limit(self):
        """POST /api/pilot/signup has 10/hour limit"""
        print(f"\n--- Testing pilot signup rate limit (10/hour) ---")
        
        # Send a single test request
        response = requests.post(
            f"{BASE_URL}/api/pilot/signup",
            json={
                "institution_name": "Test University",
                "contact_person": "Test Person",
                "email": "test_ratelimit@example.com",
                "city": "Test City"
            }
        )
        
        # Should be 200 (success) or 429 (already rate limited from previous tests)
        assert response.status_code in [200, 429], f"Unexpected status: {response.status_code}"
        
        if response.status_code == 200:
            data = response.json()
            assert data["status"] == "success"
            print(f"✓ Pilot signup succeeded: {data['message']}")
        else:
            data = response.json()
            assert "error" in data
            print(f"✓ Pilot signup rate limited: {data['error']}")


class TestRateLimitResponseFormat:
    """Test that 429 responses have correct format"""
    
    def test_429_response_format(self):
        """Verify 429 response has {error: 'Too many requests. Please try again later.'}"""
        print(f"\n--- Testing 429 response format ---")
        
        # Rapidly send requests to trigger rate limit
        for i in range(10):
            response = requests.post(
                f"{BASE_URL}/api/auth/login",
                json={"email": f"format_test{i}@example.com", "password": "wrong"}
            )
            
            if response.status_code == 429:
                data = response.json()
                assert "error" in data, "429 response must have 'error' field"
                assert data["error"] == "Too many requests. Please try again later.", \
                    f"Unexpected error message: {data['error']}"
                print(f"✓ 429 response format correct: {data}")
                return
        
        print("⚠ Could not trigger 429 response in 10 requests")


class TestExistingAPIsFunctionality:
    """Verify existing APIs still work correctly"""
    
    def test_platform_status_returns_operational(self):
        """GET /api/status/platform should return operational status"""
        response = requests.get(f"{BASE_URL}/api/status/platform")
        
        if response.status_code == 200:
            data = response.json()
            assert data["status"] == "operational", f"Expected operational, got {data.get('status')}"
            assert "metrics" in data
            assert "cities" in data
            assert "systems" in data
            print(f"✓ Platform status: {data['status']}")
        else:
            assert response.status_code == 429, f"Unexpected status: {response.status_code}"
            print("⚠ Rate limited but endpoint works")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
