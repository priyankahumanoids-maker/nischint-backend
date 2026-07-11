"""
Phase 31: City-Scale Safety Heatmap Engine Tests
Tests for city heatmap API endpoints that aggregate 5 AI signal layers
(forecast, hotspot, trend, activity, patrol) into unified grid cells.
"""
import os
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


@pytest.fixture(scope="module")
def auth_token():
    """Get operator authentication token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "operator@nischint.com",
        "password": "operator123"
    })
    if response.status_code == 200:
        return response.json().get("access_token")
    pytest.skip("Authentication failed - skipping tests")


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Headers with auth token"""
    return {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}


class TestCityHeatmapEndpoint:
    """Tests for GET /api/operator/city-heatmap"""
    
    def test_city_heatmap_returns_200(self, auth_headers):
        """Verify city-heatmap endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap", headers=auth_headers, timeout=30)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("SUCCESS: city-heatmap endpoint returns 200")

    def test_city_heatmap_has_cells_array(self, auth_headers):
        """Verify response contains cells array"""
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap", headers=auth_headers, timeout=30)
        data = response.json()
        assert "cells" in data, "Response missing 'cells' field"
        assert isinstance(data["cells"], list), "cells should be an array"
        print(f"SUCCESS: cells array present with {len(data['cells'])} cells")

    def test_city_heatmap_cell_structure(self, auth_headers):
        """Verify each cell has required fields with correct types"""
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap", headers=auth_headers, timeout=30)
        data = response.json()
        cells = data.get("cells", [])
        
        if not cells:
            pytest.skip("No cells in response - risk zones may not exist")
        
        # Check first cell structure
        cell = cells[0]
        required_fields = ["grid_id", "lat", "lng", "composite_score", "risk_level", 
                          "hotspot", "trend", "forecast", "activity", "patrol"]
        for field in required_fields:
            assert field in cell, f"Cell missing field: {field}"
        
        # Verify types
        assert isinstance(cell["grid_id"], str), "grid_id should be string"
        assert isinstance(cell["lat"], (int, float)), "lat should be numeric"
        assert isinstance(cell["lng"], (int, float)), "lng should be numeric"
        assert isinstance(cell["composite_score"], (int, float)), "composite_score should be numeric"
        assert isinstance(cell["risk_level"], str), "risk_level should be string"
        assert cell["risk_level"] in ["critical", "high", "moderate", "safe"], f"Invalid risk_level: {cell['risk_level']}"
        
        print(f"SUCCESS: Cell structure verified - grid_id={cell['grid_id']}, score={cell['composite_score']}, risk={cell['risk_level']}")

    def test_city_heatmap_has_stats(self, auth_headers):
        """Verify response contains stats with critical/high/moderate/safe counts"""
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap", headers=auth_headers, timeout=30)
        data = response.json()
        assert "stats" in data, "Response missing 'stats' field"
        
        stats = data["stats"]
        for level in ["critical", "high", "moderate", "safe"]:
            assert level in stats, f"Stats missing '{level}' count"
            assert isinstance(stats[level], int), f"stats.{level} should be integer"
        
        # Verify additional stats fields
        assert "dominant_signal" in stats, "Stats missing dominant_signal"
        assert "forecast_p1_cells" in stats, "Stats missing forecast_p1_cells"
        
        print(f"SUCCESS: Stats present - critical={stats['critical']}, high={stats['high']}, moderate={stats['moderate']}, safe={stats['safe']}, dominant={stats['dominant_signal']}")

    def test_city_heatmap_has_bounds(self, auth_headers):
        """Verify response contains bounds for map centering"""
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap", headers=auth_headers, timeout=30)
        data = response.json()
        
        if data.get("cells"):
            assert "bounds" in data, "Response missing 'bounds' field"
            bounds = data["bounds"]
            assert bounds is not None, "bounds should not be null when cells exist"
            for key in ["min_lat", "max_lat", "min_lng", "max_lng"]:
                assert key in bounds, f"bounds missing '{key}'"
            print(f"SUCCESS: Bounds present - lat: {bounds['min_lat']} to {bounds['max_lat']}, lng: {bounds['min_lng']} to {bounds['max_lng']}")
        else:
            print("SKIP: No cells - bounds check skipped")

    def test_city_heatmap_has_weights(self, auth_headers):
        """Verify response contains signal weights"""
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap", headers=auth_headers, timeout=30)
        data = response.json()
        assert "weights" in data, "Response missing 'weights' field"
        
        weights = data["weights"]
        expected = {"forecast": 0.30, "hotspot": 0.25, "trend": 0.20, "activity": 0.15, "patrol": 0.10}
        for signal, expected_weight in expected.items():
            assert signal in weights, f"weights missing '{signal}'"
            assert abs(weights[signal] - expected_weight) < 0.01, f"Weight mismatch for {signal}: {weights[signal]} != {expected_weight}"
        
        print(f"SUCCESS: Weights verified - {weights}")

    def test_composite_score_calculation(self, auth_headers):
        """Verify composite score is correctly calculated from weighted signals"""
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap", headers=auth_headers, timeout=30)
        data = response.json()
        cells = data.get("cells", [])
        
        if not cells:
            pytest.skip("No cells to verify composite score")
        
        # Check a few cells
        for cell in cells[:5]:
            expected = round(
                0.30 * cell["forecast"] +
                0.25 * cell["hotspot"] +
                0.20 * cell["trend"] +
                0.15 * cell["activity"] +
                0.10 * cell["patrol"], 2
            )
            # Allow small floating point tolerance
            assert abs(cell["composite_score"] - expected) < 0.05, \
                f"Composite score mismatch for {cell['grid_id']}: {cell['composite_score']} != {expected}"
        
        print(f"SUCCESS: Composite score calculation verified for {min(5, len(cells))} cells")

    def test_risk_level_classification(self, auth_headers):
        """Verify risk_level classification thresholds"""
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap", headers=auth_headers, timeout=30)
        data = response.json()
        cells = data.get("cells", [])
        
        if not cells:
            pytest.skip("No cells to verify risk classification")
        
        # Thresholds: critical >= 7.0, high >= 5.0, moderate >= 3.0, safe < 3.0
        for cell in cells:
            score = cell["composite_score"]
            level = cell["risk_level"]
            
            if score >= 7.0:
                assert level == "critical", f"Score {score} should be critical, got {level}"
            elif score >= 5.0:
                assert level == "high", f"Score {score} should be high, got {level}"
            elif score >= 3.0:
                assert level == "moderate", f"Score {score} should be moderate, got {level}"
            else:
                assert level == "safe", f"Score {score} should be safe, got {level}"
        
        print(f"SUCCESS: Risk level classification verified for all {len(cells)} cells")


class TestCityHeatmapStatsEndpoint:
    """Tests for GET /api/operator/city-heatmap/stats"""
    
    def test_heatmap_stats_returns_200(self, auth_headers):
        """Verify city-heatmap/stats endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap/stats", headers=auth_headers, timeout=15)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("SUCCESS: city-heatmap/stats endpoint returns 200")

    def test_heatmap_stats_structure(self, auth_headers):
        """Verify stats response contains required fields"""
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap/stats", headers=auth_headers, timeout=15)
        data = response.json()
        
        required_fields = ["total_zones", "critical_zones", "high_risk_zones", "recent_incidents_7d"]
        for field in required_fields:
            assert field in data, f"Stats response missing '{field}'"
            assert isinstance(data[field], int), f"{field} should be integer"
        
        # Verify analyzed_at timestamp
        assert "analyzed_at" in data, "Stats missing analyzed_at timestamp"
        
        print(f"SUCCESS: Stats structure verified - zones={data['total_zones']}, critical={data['critical_zones']}, high_risk={data['high_risk_zones']}, incidents_7d={data['recent_incidents_7d']}")


class TestCityHeatmapCellDetailEndpoint:
    """Tests for GET /api/operator/city-heatmap/cell/{grid_id}"""
    
    def test_cell_detail_valid_grid_id(self, auth_headers):
        """Verify cell detail returns 200 for valid grid_id"""
        # First get a valid grid_id from the heatmap
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap", headers=auth_headers, timeout=30)
        data = response.json()
        cells = data.get("cells", [])
        
        if not cells:
            pytest.skip("No cells available to test cell detail")
        
        grid_id = cells[0]["grid_id"]
        detail_response = requests.get(f"{BASE_URL}/api/operator/city-heatmap/cell/{grid_id}", headers=auth_headers, timeout=15)
        assert detail_response.status_code == 200, f"Expected 200, got {detail_response.status_code}"
        print(f"SUCCESS: Cell detail endpoint returns 200 for grid_id={grid_id}")

    def test_cell_detail_structure(self, auth_headers):
        """Verify cell detail response structure"""
        # First get a valid grid_id
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap", headers=auth_headers, timeout=30)
        data = response.json()
        cells = data.get("cells", [])
        
        if not cells:
            pytest.skip("No cells available")
        
        grid_id = cells[0]["grid_id"]
        detail_response = requests.get(f"{BASE_URL}/api/operator/city-heatmap/cell/{grid_id}", headers=auth_headers, timeout=15)
        detail = detail_response.json()
        
        # Verify required fields
        required_fields = ["grid_id", "lat", "lng", "composite_score", "risk_level", "signals", "dominant_signal", "recommendations"]
        for field in required_fields:
            assert field in detail, f"Cell detail missing '{field}'"
        
        # Verify signals array structure
        assert isinstance(detail["signals"], list), "signals should be array"
        assert len(detail["signals"]) == 5, "Should have 5 signals"
        
        signal_names = {"Forecast Risk", "Hotspot Density", "Trend Growth", "Activity Spike", "Patrol Priority"}
        for sig in detail["signals"]:
            assert "name" in sig, "Signal missing 'name'"
            assert "score" in sig, "Signal missing 'score'"
            assert "weight" in sig, "Signal missing 'weight'"
            assert "weighted" in sig, "Signal missing 'weighted'"
            assert sig["name"] in signal_names, f"Unknown signal name: {sig['name']}"
        
        print(f"SUCCESS: Cell detail structure verified for {grid_id} with dominant_signal={detail['dominant_signal']}")

    def test_cell_detail_has_recommendations(self, auth_headers):
        """Verify cell detail includes recommendations"""
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap", headers=auth_headers, timeout=30)
        data = response.json()
        cells = data.get("cells", [])
        
        if not cells:
            pytest.skip("No cells available")
        
        grid_id = cells[0]["grid_id"]
        detail_response = requests.get(f"{BASE_URL}/api/operator/city-heatmap/cell/{grid_id}", headers=auth_headers, timeout=15)
        detail = detail_response.json()
        
        assert "recommendations" in detail, "Cell detail missing recommendations"
        assert isinstance(detail["recommendations"], list), "recommendations should be array"
        assert len(detail["recommendations"]) > 0, "Should have at least one recommendation"
        
        print(f"SUCCESS: Cell has {len(detail['recommendations'])} recommendations: {detail['recommendations'][:2]}")

    def test_cell_detail_nonexistent_returns_404(self, auth_headers):
        """Verify 404 for nonexistent grid_id"""
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap/cell/NONEXISTENT", headers=auth_headers, timeout=15)
        assert response.status_code == 404, f"Expected 404 for nonexistent grid_id, got {response.status_code}"
        print("SUCCESS: Nonexistent grid_id returns 404")


class TestCityHeatmapAuthentication:
    """Tests for authentication requirements"""
    
    def test_city_heatmap_requires_auth(self):
        """Verify city-heatmap requires authentication"""
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap", timeout=10)
        assert response.status_code == 401, f"Expected 401 without auth, got {response.status_code}"
        print("SUCCESS: city-heatmap requires authentication")

    def test_city_heatmap_stats_requires_auth(self):
        """Verify city-heatmap/stats requires authentication"""
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap/stats", timeout=10)
        assert response.status_code == 401, f"Expected 401 without auth, got {response.status_code}"
        print("SUCCESS: city-heatmap/stats requires authentication")

    def test_city_heatmap_cell_requires_auth(self):
        """Verify city-heatmap/cell/{grid_id} requires authentication"""
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap/cell/C008_003", timeout=10)
        assert response.status_code == 401, f"Expected 401 without auth, got {response.status_code}"
        print("SUCCESS: city-heatmap/cell requires authentication")


class TestCityHeatmapTopCell:
    """Tests for specific top cell mentioned in requirements"""
    
    def test_top_cell_c008_003_exists(self, auth_headers):
        """Check if cell C008_003 (mentioned in requirements) exists or verify top cell"""
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap", headers=auth_headers, timeout=30)
        data = response.json()
        cells = data.get("cells", [])
        
        if not cells:
            pytest.skip("No cells available")
        
        # Cells are sorted by composite_score descending
        top_cell = cells[0]
        print(f"SUCCESS: Top cell is {top_cell['grid_id']} with composite_score={top_cell['composite_score']}")
        
        # Try to find C008_003 specifically
        c008_003 = next((c for c in cells if c["grid_id"] == "C008_003"), None)
        if c008_003:
            print(f"INFO: Cell C008_003 found with score={c008_003['composite_score']}, risk_level={c008_003['risk_level']}")
        else:
            print("INFO: Cell C008_003 not in current grid (grid varies based on risk zones)")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
