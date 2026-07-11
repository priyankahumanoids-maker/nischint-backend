"""
NISCHINT Journey Engine v5 - Comprehensive Backend Tests (STABLE VERSION)
"""

import pytest
import requests
import time
import os

# ✅ Safer base URL handling
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'http://localhost:8000').rstrip('/')
API_PREFIX = f"{BASE_URL}/api/journey"

# ✅ Global timeout (prevents hanging tests)
TIMEOUT = 5


# -----------------------------
# Helper
# -----------------------------
def safe_json(resp):
    try:
        return resp.json()
    except:
        return {}


# -----------------------------
# SSE FIXED TEST (MAIN ISSUE)
# -----------------------------
class TestSSEStream:
    """SSE Stream - FIXED (no flaky timeout issues)"""

    def test_sse_stream_returns_event_stream(self):
        """Stable SSE test"""

        # Create SOS
        sos_resp = requests.post(
            f"{API_PREFIX}/sos",
            json={
                "sosId": f"TEST_sos_sse_{int(time.time())}",
                "sosState": "triggered",
                "ts": int(time.time() * 1000),
                "riskScore": 50,
                "riskLevel": "caution",
                "sessionId": "TEST_user_sse"
            },
            timeout=TIMEOUT
        )

        assert sos_resp.status_code == 200
        sos_id = safe_json(sos_resp).get("sos_id")
        assert sos_id

        # Connect to SSE
        with requests.get(
            f"{API_PREFIX}/sos/{sos_id}/stream",
            stream=True,
            timeout=(3, 10)  # connect timeout, read timeout
        ) as response:

            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("Content-Type", "")

            # ✅ Read safely (avoid infinite wait)
            found_event = False
            start = time.time()

            for line in response.iter_lines(decode_unicode=True):
                if time.time() - start > 5:
                    break  # prevent hang

                if line and line.startswith("data:"):
                    found_event = True
                    print(f"SSE Event: {line}")
                    break

            assert found_event, "No SSE event received within timeout"

    def test_sse_stream_nonexistent_sos_returns_404(self):
        response = requests.get(
            f"{API_PREFIX}/sos/nonexistent_sos_12345/stream",
            timeout=TIMEOUT
        )
        assert response.status_code == 404


# -----------------------------
# MINIMAL SANITY TESTS (KEEP FAST)
# -----------------------------
class TestSanity:
    """Quick sanity checks to ensure API is alive"""

    def test_health_contacts(self):
        resp = requests.get(f"{API_PREFIX}/contacts", timeout=TIMEOUT)
        assert resp.status_code == 200

    def test_health_stats(self):
        resp = requests.get(f"{API_PREFIX}/stats", timeout=TIMEOUT)
        assert resp.status_code == 200


# -----------------------------
# OPTIONAL: RETRY WRAPPER (USEFUL FOR FLAKY NETWORK)
# -----------------------------
def retry_request(method, url, retries=3, **kwargs):
    for i in range(retries):
        try:
            return requests.request(method, url, timeout=TIMEOUT, **kwargs)
        except requests.exceptions.RequestException:
            if i == retries - 1:
                raise
            time.sleep(0.5)


# -----------------------------
# MAIN
# -----------------------------
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])