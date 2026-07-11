"""
Test Suite: Heatmap Cell Detail Drill-Down (Zone Intelligence Panel)
Tests GET /api/operator/city-heatmap/cell/{grid_id} endpoint

New Feature: Clicking a risk zone on Command Center map opens Zone Intelligence Panel
showing: composite risk score, location, 8 AI signal breakdowns, dominant signal, recommended action.
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
ADMIN_CREDS = {"email": "nischint4parents@gmail.com", "password": "secret123"}
OPERATOR_CREDS = {"email": "operator1@nischint.com", "password": "secret123"}
CAREGIVER_CREDS = {"email": "caregiver1@nischint.com", "password": "secret123"}

# Expected 8 signals in the response
EXPECTED_SIGNAL_KEYS = [
    "forecast", "hotspot", "trend", "activity",
    "patrol", "environment", "session_density", "mobility_anomaly"
]


@pytest.fixture(scope="module")
def admin_token():
    """Login as admin and return token."""
    resp = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN_CREDS)
    assert resp.status_code == 200, f"Admin login failed: {resp.text}"
    return resp.json()["access_token"]


@pytest.fixture(scope="module")
def operator_token():
    """Login as operator and return token."""
    resp = requests.post(f"{BASE_URL}/api/auth/login", json=OPERATOR_CREDS)
    assert resp.status_code == 200, f"Operator login failed: {resp.text}"
    return resp.json()["access_token"]


@pytest.fixture(scope="module")
def caregiver_token():
    """Login as caregiver and return token."""
    resp = requests.post(f"{BASE_URL}/api/auth/login", json=CAREGIVER_CREDS)
    assert resp.status_code == 200, f"Caregiver login failed: {resp.text}"
    return resp.json()["access_token"]


@pytest.fixture(scope="module")
def valid_grid_id(admin_token):
    """Get a valid grid_id from the live heatmap."""
    resp = requests.get(
        f"{BASE_URL}/api/operator/city-heatmap/live",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp.status_code == 200, f"Failed to get heatmap: {resp.text}"
    cells = resp.json().get("cells", [])
    assert len(cells) > 0, "No cells in heatmap"
    # Prefer a high-risk cell for testing
    high_risk = [c for c in cells if c.get("risk_level") in ["high", "HIGH", "critical", "CRITICAL"]]
    if high_risk:
        return high_risk[0]["grid_id"]
    return cells[0]["grid_id"]


class TestCellDetailEndpoint:
    """Test GET /api/operator/city-heatmap/cell/{grid_id}"""

    def test_cell_detail_returns_200_for_valid_grid_id(self, admin_token, valid_grid_id):
        """Valid grid_id should return 200 with cell detail."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/city-heatmap/cell/{valid_grid_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_cell_detail_returns_404_for_invalid_grid_id(self, admin_token):
        """Invalid grid_id should return 404."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/city-heatmap/cell/INVALID_GRID_12345",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"
        assert "not found" in resp.json().get("detail", "").lower()


class TestCellDetailResponseFields:
    """Test that response contains all required fields."""

    def test_response_has_grid_id(self, admin_token, valid_grid_id):
        """Response should contain grid_id."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/city-heatmap/cell/{valid_grid_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        data = resp.json()
        assert data.get("grid_id") == valid_grid_id

    def test_response_has_composite_score(self, admin_token, valid_grid_id):
        """Response should contain composite_score."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/city-heatmap/cell/{valid_grid_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        data = resp.json()
        assert "composite_score" in data
        assert isinstance(data["composite_score"], (int, float))
        assert 0 <= data["composite_score"] <= 10

    def test_response_has_risk_level(self, admin_token, valid_grid_id):
        """Response should contain risk_level (safe/moderate/high/critical)."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/city-heatmap/cell/{valid_grid_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        data = resp.json()
        assert "risk_level" in data
        assert data["risk_level"].lower() in ["safe", "moderate", "high", "critical"]

    def test_response_has_lat_lng(self, admin_token, valid_grid_id):
        """Response should contain lat/lng coordinates."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/city-heatmap/cell/{valid_grid_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        data = resp.json()
        assert "lat" in data
        assert "lng" in data
        # Bangalore area coordinates
        assert isinstance(data["lat"], float)
        assert isinstance(data["lng"], float)


class TestCellDetailSignals:
    """Test the 8 AI signal breakdown."""

    def test_response_has_signals_array(self, admin_token, valid_grid_id):
        """Response should contain signals array."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/city-heatmap/cell/{valid_grid_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        data = resp.json()
        assert "signals" in data
        assert isinstance(data["signals"], list)

    def test_signals_has_8_entries(self, admin_token, valid_grid_id):
        """Signals array should have exactly 8 entries."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/city-heatmap/cell/{valid_grid_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        data = resp.json()
        assert len(data["signals"]) == 8, f"Expected 8 signals, got {len(data['signals'])}"

    def test_signals_contains_all_expected_keys(self, admin_token, valid_grid_id):
        """All 8 expected signal keys should be present."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/city-heatmap/cell/{valid_grid_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        data = resp.json()
        signal_keys = [s["key"] for s in data["signals"]]
        for expected_key in EXPECTED_SIGNAL_KEYS:
            assert expected_key in signal_keys, f"Missing signal key: {expected_key}"

    def test_signal_has_name_score_weight_weighted(self, admin_token, valid_grid_id):
        """Each signal should have name, key, score, weight, weighted fields."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/city-heatmap/cell/{valid_grid_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        data = resp.json()
        for signal in data["signals"]:
            assert "name" in signal, f"Signal missing 'name': {signal}"
            assert "key" in signal, f"Signal missing 'key': {signal}"
            assert "score" in signal, f"Signal missing 'score': {signal}"
            assert "weight" in signal, f"Signal missing 'weight': {signal}"
            assert "weighted" in signal, f"Signal missing 'weighted': {signal}"

    def test_signal_scores_are_0_to_10(self, admin_token, valid_grid_id):
        """Signal scores should be between 0 and 10."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/city-heatmap/cell/{valid_grid_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        data = resp.json()
        for signal in data["signals"]:
            assert 0 <= signal["score"] <= 10, f"Score out of range for {signal['name']}: {signal['score']}"

    def test_signal_weights_sum_approximately_to_1(self, admin_token, valid_grid_id):
        """Signal weights should sum to approximately 1.0."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/city-heatmap/cell/{valid_grid_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        data = resp.json()
        weight_sum = sum(s["weight"] for s in data["signals"])
        assert 0.95 <= weight_sum <= 1.05, f"Weights don't sum to ~1.0: {weight_sum}"


class TestCellDetailDominantSignal:
    """Test dominant signal computation."""

    def test_response_has_dominant_signal(self, admin_token, valid_grid_id):
        """Response should contain dominant_signal."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/city-heatmap/cell/{valid_grid_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        data = resp.json()
        assert "dominant_signal" in data
        assert isinstance(data["dominant_signal"], str)


class TestCellDetailRBAC:
    """Test RBAC for cell detail endpoint."""

    def test_admin_can_access_cell_detail(self, admin_token, valid_grid_id):
        """Admin should be able to access cell detail."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/city-heatmap/cell/{valid_grid_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert resp.status_code == 200

    def test_operator_can_access_cell_detail(self, operator_token, valid_grid_id):
        """Operator should be able to access cell detail."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/city-heatmap/cell/{valid_grid_id}",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert resp.status_code == 200

    def test_caregiver_blocked_from_cell_detail(self, caregiver_token, valid_grid_id):
        """Caregiver should be blocked with 403."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/city-heatmap/cell/{valid_grid_id}",
            headers={"Authorization": f"Bearer {caregiver_token}"}
        )
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}"

    def test_unauthenticated_blocked_from_cell_detail(self, valid_grid_id):
        """Unauthenticated request should be blocked with 401."""
        resp = requests.get(
            f"{BASE_URL}/api/operator/city-heatmap/cell/{valid_grid_id}"
        )
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
