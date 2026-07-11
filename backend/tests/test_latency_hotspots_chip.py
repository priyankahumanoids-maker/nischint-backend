"""
Test suite for LatencyHotspotsChip feature - Backend API tests
Tests the /api/admin/monitoring/latency and /api/admin/monitoring/latency/reset endpoints

Features tested:
- GET /api/admin/monitoring/latency works with operator token
- GET /api/admin/monitoring/latency works with admin token
- GET /api/admin/monitoring/latency rejects unauthenticated requests (401)
- POST /api/admin/monitoring/latency/reset is admin-only (operator gets 403)
- POST /api/admin/monitoring/latency/reset works with admin token
- Response structure validation (endpoints array sorted by p95 desc)
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


class TestLatencyEndpointAuth:
    """Authentication and authorization tests for latency endpoints"""

    @pytest.fixture(scope="class")
    def operator_token(self):
        """Get operator token"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "operator@nischint.com", "password": "OperatorSecure!2026"},
        )
        assert response.status_code == 200, f"Operator login failed: {response.text}"
        data = response.json()
        return data.get("access_token") or data.get("token")

    @pytest.fixture(scope="class")
    def admin_token(self):
        """Get admin token"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "nischint4parents@gmail.com", "password": "secret123"},
        )
        assert response.status_code == 200, f"Admin login failed: {response.text}"
        data = response.json()
        return data.get("access_token") or data.get("token")

    def test_latency_endpoint_rejects_unauthenticated(self):
        """GET /api/admin/monitoring/latency rejects unauthenticated requests with 401"""
        response = requests.get(f"{BASE_URL}/api/admin/monitoring/latency")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("✓ Unauthenticated request correctly rejected with 401")

    def test_latency_endpoint_works_with_operator(self, operator_token):
        """GET /api/admin/monitoring/latency works with operator token"""
        response = requests.get(
            f"{BASE_URL}/api/admin/monitoring/latency",
            headers={"Authorization": f"Bearer {operator_token}"},
            params={"top_n": 3, "sort_by": "p95_ms"},
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "endpoints" in data, "Response should contain 'endpoints' array"
        print(f"✓ Operator can access latency endpoint, got {len(data['endpoints'])} endpoints")

    def test_latency_endpoint_works_with_admin(self, admin_token):
        """GET /api/admin/monitoring/latency works with admin token"""
        response = requests.get(
            f"{BASE_URL}/api/admin/monitoring/latency",
            headers={"Authorization": f"Bearer {admin_token}"},
            params={"top_n": 3, "sort_by": "p95_ms"},
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "endpoints" in data, "Response should contain 'endpoints' array"
        print(f"✓ Admin can access latency endpoint, got {len(data['endpoints'])} endpoints")

    def test_latency_reset_rejects_operator(self, operator_token):
        """POST /api/admin/monitoring/latency/reset is admin-only - operator gets 403"""
        response = requests.post(
            f"{BASE_URL}/api/admin/monitoring/latency/reset",
            headers={"Authorization": f"Bearer {operator_token}"},
        )
        assert response.status_code == 403, f"Expected 403, got {response.status_code}: {response.text}"
        print("✓ Operator correctly rejected from reset endpoint with 403")

    def test_latency_reset_works_with_admin(self, admin_token):
        """POST /api/admin/monitoring/latency/reset works with admin token"""
        response = requests.post(
            f"{BASE_URL}/api/admin/monitoring/latency/reset",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data.get("reset") is True, "Response should contain 'reset: true'"
        print(f"✓ Admin can reset latency data: {data}")


class TestLatencyResponseStructure:
    """Tests for latency endpoint response structure"""

    @pytest.fixture(scope="class")
    def operator_token(self):
        """Get operator token"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "operator@nischint.com", "password": "OperatorSecure!2026"},
        )
        assert response.status_code == 200
        data = response.json()
        return data.get("access_token") or data.get("token")

    def test_response_contains_required_fields(self, operator_token):
        """Response contains all required top-level fields"""
        response = requests.get(
            f"{BASE_URL}/api/admin/monitoring/latency",
            headers={"Authorization": f"Bearer {operator_token}"},
        )
        assert response.status_code == 200
        data = response.json()

        # Check top-level fields
        assert "captured_at_ms" in data, "Missing captured_at_ms"
        assert "max_samples_per_endpoint" in data, "Missing max_samples_per_endpoint"
        assert "sort_by" in data, "Missing sort_by"
        assert "endpoint_count" in data, "Missing endpoint_count"
        assert "endpoints" in data, "Missing endpoints array"
        print("✓ Response contains all required top-level fields")

    def test_endpoint_structure(self, operator_token):
        """Each endpoint in the response has the correct structure"""
        response = requests.get(
            f"{BASE_URL}/api/admin/monitoring/latency",
            headers={"Authorization": f"Bearer {operator_token}"},
            params={"top_n": 5},
        )
        assert response.status_code == 200
        data = response.json()

        if data["endpoints"]:
            endpoint = data["endpoints"][0]
            required_fields = [
                "endpoint", "samples", "p50_ms", "p95_ms", "p99_ms",
                "min_ms", "max_ms", "total_requests", "error_count", "error_rate"
            ]
            for field in required_fields:
                assert field in endpoint, f"Missing field: {field}"
            print(f"✓ Endpoint structure is correct: {list(endpoint.keys())}")
        else:
            print("⚠ No endpoints in response (may need to seed traffic)")

    def test_endpoints_sorted_by_p95_desc(self, operator_token):
        """Endpoints are sorted by p95_ms in descending order"""
        response = requests.get(
            f"{BASE_URL}/api/admin/monitoring/latency",
            headers={"Authorization": f"Bearer {operator_token}"},
            params={"top_n": 10, "sort_by": "p95_ms"},
        )
        assert response.status_code == 200
        data = response.json()

        endpoints = data["endpoints"]
        if len(endpoints) >= 2:
            p95_values = [e.get("p95_ms") for e in endpoints if e.get("p95_ms") is not None]
            # Check descending order (allowing for None values at the end)
            for i in range(len(p95_values) - 1):
                assert p95_values[i] >= p95_values[i + 1], \
                    f"Not sorted by p95 desc: {p95_values[i]} < {p95_values[i + 1]}"
            print(f"✓ Endpoints sorted by p95_ms desc: {p95_values[:3]}...")
        else:
            print("⚠ Not enough endpoints to verify sorting")

    def test_top_n_parameter(self, operator_token):
        """top_n parameter limits the number of endpoints returned"""
        response = requests.get(
            f"{BASE_URL}/api/admin/monitoring/latency",
            headers={"Authorization": f"Bearer {operator_token}"},
            params={"top_n": 3},
        )
        assert response.status_code == 200
        data = response.json()

        assert len(data["endpoints"]) <= 3, f"Expected at most 3 endpoints, got {len(data['endpoints'])}"
        print(f"✓ top_n=3 correctly limits results to {len(data['endpoints'])} endpoints")


class TestLatencyColorThresholds:
    """Tests to verify latency data supports color coding thresholds"""

    @pytest.fixture(scope="class")
    def operator_token(self):
        """Get operator token"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "operator@nischint.com", "password": "OperatorSecure!2026"},
        )
        assert response.status_code == 200
        data = response.json()
        return data.get("access_token") or data.get("token")

    def test_p95_values_for_color_coding(self, operator_token):
        """Verify p95 values are numeric and can be used for color coding"""
        response = requests.get(
            f"{BASE_URL}/api/admin/monitoring/latency",
            headers={"Authorization": f"Bearer {operator_token}"},
            params={"top_n": 10},
        )
        assert response.status_code == 200
        data = response.json()

        for endpoint in data["endpoints"]:
            p95 = endpoint.get("p95_ms")
            if p95 is not None:
                assert isinstance(p95, (int, float)), f"p95_ms should be numeric, got {type(p95)}"
                # Verify color coding thresholds can be applied
                if p95 < 500:
                    color = "green (FAST)"
                elif p95 < 2000:
                    color = "amber (SLOW)"
                else:
                    color = "red (HOTSPOT)"
                print(f"  {endpoint['endpoint']}: p95={p95:.2f}ms → {color}")

        print("✓ All p95 values are numeric and suitable for color coding")

    def test_no_samples_returns_null_p95(self, operator_token):
        """Endpoints with no samples should have null p95 (shown as '—' in UI)"""
        # This is a structural test - the API should handle null gracefully
        response = requests.get(
            f"{BASE_URL}/api/admin/monitoring/latency",
            headers={"Authorization": f"Bearer {operator_token}"},
        )
        assert response.status_code == 200
        data = response.json()

        # Check that the response structure allows for null p95 values
        for endpoint in data["endpoints"]:
            samples = endpoint.get("samples", 0)
            p95 = endpoint.get("p95_ms")
            if samples == 0:
                assert p95 is None, f"Endpoint with 0 samples should have null p95"
                print(f"  {endpoint['endpoint']}: 0 samples → p95=null (shown as '—')")

        print("✓ Response structure correctly handles null p95 values")


class TestLatencyResetEndpoint:
    """Tests for the latency reset endpoint"""

    @pytest.fixture(scope="class")
    def admin_token(self):
        """Get admin token"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "nischint4parents@gmail.com", "password": "secret123"},
        )
        assert response.status_code == 200
        data = response.json()
        return data.get("access_token") or data.get("token")

    def test_reset_returns_correct_structure(self, admin_token):
        """Reset endpoint returns correct response structure"""
        response = requests.post(
            f"{BASE_URL}/api/admin/monitoring/latency/reset",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        data = response.json()

        assert "reset" in data, "Missing 'reset' field"
        assert data["reset"] is True, "reset should be True"
        # These fields are optional but expected
        if "local_endpoints_cleared" in data:
            assert isinstance(data["local_endpoints_cleared"], int)
        if "redis_keys_cleared" in data:
            assert isinstance(data["redis_keys_cleared"], int)

        print(f"✓ Reset response structure correct: {data}")
