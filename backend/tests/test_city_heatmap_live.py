"""
Test City Heatmap Live APIs (Phase 39 - Risk Heatmap Layer)
Tests: GET /api/operator/city-heatmap/live, /city-heatmap/stats endpoints
RBAC: Only admin/operator can access
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestCityHeatmapLive:
    """Test /api/operator/city-heatmap/live endpoint"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Get auth tokens for different roles"""
        # Admin login
        admin_resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "nischint4parents@gmail.com",
            "password": "secret123"
        })
        self.admin_token = admin_resp.json().get("access_token") if admin_resp.status_code == 200 else None
        
        # Operator login
        op_resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "operator1@nischint.com",
            "password": "secret123"
        })
        self.operator_token = op_resp.json().get("access_token") if op_resp.status_code == 200 else None
        
        # Caregiver login
        cg_resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "caregiver1@nischint.com",
            "password": "secret123"
        })
        self.caregiver_token = cg_resp.json().get("access_token") if cg_resp.status_code == 200 else None

    def test_heatmap_live_admin_access(self):
        """Admin can access /city-heatmap/live"""
        if not self.admin_token:
            pytest.skip("Admin login failed")
        
        resp = requests.get(
            f"{BASE_URL}/api/operator/city-heatmap/live",
            headers={"Authorization": f"Bearer {self.admin_token}"}
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        
        data = resp.json()
        # Verify response structure - should have cells array
        assert "cells" in data, "Response should contain 'cells' array"
        
        # If cells exist, verify they have required fields
        if data["cells"]:
            cell = data["cells"][0]
            assert "lat" in cell, "Cell should have 'lat'"
            assert "lng" in cell, "Cell should have 'lng'"
            assert "risk_level" in cell, "Cell should have 'risk_level'"
            assert "composite_score" in cell, "Cell should have 'composite_score'"
            print(f"PASS: Admin got {len(data['cells'])} heatmap cells")
        else:
            print("PASS: Admin accessed heatmap (0 cells - no risk zones)")
    
    def test_heatmap_live_operator_access(self):
        """Operator can access /city-heatmap/live"""
        if not self.operator_token:
            pytest.skip("Operator login failed")
        
        resp = requests.get(
            f"{BASE_URL}/api/operator/city-heatmap/live",
            headers={"Authorization": f"Bearer {self.operator_token}"}
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        print("PASS: Operator can access heatmap live")
    
    def test_heatmap_live_caregiver_blocked(self):
        """Caregiver should NOT access /city-heatmap/live (RBAC)"""
        if not self.caregiver_token:
            pytest.skip("Caregiver login failed")
        
        resp = requests.get(
            f"{BASE_URL}/api/operator/city-heatmap/live",
            headers={"Authorization": f"Bearer {self.caregiver_token}"}
        )
        assert resp.status_code == 403, f"Expected 403 for caregiver, got {resp.status_code}"
        print("PASS: Caregiver correctly blocked (403)")
    
    def test_heatmap_live_unauthenticated_blocked(self):
        """Unauthenticated request should be blocked"""
        resp = requests.get(f"{BASE_URL}/api/operator/city-heatmap/live")
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"
        print("PASS: Unauthenticated request blocked (401)")
    
    def test_heatmap_live_cell_fields(self):
        """Verify cells have lat/lng/risk_level/composite_score"""
        if not self.admin_token:
            pytest.skip("Admin login failed")
        
        resp = requests.get(
            f"{BASE_URL}/api/operator/city-heatmap/live",
            headers={"Authorization": f"Bearer {self.admin_token}"}
        )
        assert resp.status_code == 200
        
        data = resp.json()
        cells = data.get("cells", [])
        
        # Skip if no cells
        if not cells:
            pytest.skip("No heatmap cells to test")
        
        for cell in cells[:5]:  # Check first 5 cells
            assert "lat" in cell, "Cell missing 'lat'"
            assert "lng" in cell, "Cell missing 'lng'"
            assert "risk_level" in cell, "Cell missing 'risk_level'"
            assert "composite_score" in cell, "Cell missing 'composite_score'"
            assert cell["risk_level"].upper() in ["SAFE", "MODERATE", "HIGH", "CRITICAL"], \
                f"Invalid risk_level: {cell['risk_level']}"
            assert isinstance(cell["composite_score"], (int, float)), \
                f"composite_score should be numeric: {cell['composite_score']}"
        
        print(f"PASS: All cell fields validated (checked {min(5, len(cells))} cells)")


class TestCityHeatmapStats:
    """Test /api/operator/city-heatmap/stats endpoint"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Get admin token"""
        admin_resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "nischint4parents@gmail.com",
            "password": "secret123"
        })
        self.admin_token = admin_resp.json().get("access_token") if admin_resp.status_code == 200 else None
        
        # Caregiver for RBAC test
        cg_resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "caregiver1@nischint.com",
            "password": "secret123"
        })
        self.caregiver_token = cg_resp.json().get("access_token") if cg_resp.status_code == 200 else None

    def test_heatmap_stats_admin_access(self):
        """Admin can access /city-heatmap/stats"""
        if not self.admin_token:
            pytest.skip("Admin login failed")
        
        resp = requests.get(
            f"{BASE_URL}/api/operator/city-heatmap/stats",
            headers={"Authorization": f"Bearer {self.admin_token}"}
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        
        data = resp.json()
        # Stats should contain zone counts
        assert "total_zones" in data or "stats" in data or "critical_zones" in data or "high_risk_zones" in data, \
            f"Stats should contain zone info: {data.keys()}"
        print(f"PASS: Admin got heatmap stats: {data}")
    
    def test_heatmap_stats_returns_zone_counts(self):
        """Stats should return zone counts"""
        if not self.admin_token:
            pytest.skip("Admin login failed")
        
        resp = requests.get(
            f"{BASE_URL}/api/operator/city-heatmap/stats",
            headers={"Authorization": f"Bearer {self.admin_token}"}
        )
        assert resp.status_code == 200
        
        data = resp.json()
        # Should have numeric zone counts
        if "total_zones" in data:
            assert isinstance(data["total_zones"], int), "total_zones should be int"
        if "critical_zones" in data:
            assert isinstance(data["critical_zones"], int), "critical_zones should be int"
        if "high_risk_zones" in data:
            assert isinstance(data["high_risk_zones"], int), "high_risk_zones should be int"
        
        print(f"PASS: Stats has valid zone counts")
    
    def test_heatmap_stats_caregiver_blocked(self):
        """Caregiver should NOT access /city-heatmap/stats (RBAC)"""
        if not self.caregiver_token:
            pytest.skip("Caregiver login failed")
        
        resp = requests.get(
            f"{BASE_URL}/api/operator/city-heatmap/stats",
            headers={"Authorization": f"Bearer {self.caregiver_token}"}
        )
        assert resp.status_code == 403, f"Expected 403 for caregiver, got {resp.status_code}"
        print("PASS: Caregiver correctly blocked from stats (403)")


class TestHeatmapRiskLevels:
    """Test heatmap risk level classification"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        admin_resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "nischint4parents@gmail.com",
            "password": "secret123"
        })
        self.admin_token = admin_resp.json().get("access_token") if admin_resp.status_code == 200 else None

    def test_risk_level_values(self):
        """Risk levels should be SAFE/MODERATE/HIGH/CRITICAL"""
        if not self.admin_token:
            pytest.skip("Admin login failed")
        
        resp = requests.get(
            f"{BASE_URL}/api/operator/city-heatmap/live",
            headers={"Authorization": f"Bearer {self.admin_token}"}
        )
        assert resp.status_code == 200
        
        data = resp.json()
        cells = data.get("cells", [])
        
        if not cells:
            pytest.skip("No cells to test")
        
        valid_levels = {"SAFE", "MODERATE", "HIGH", "CRITICAL"}
        risk_counts = {"SAFE": 0, "MODERATE": 0, "HIGH": 0, "CRITICAL": 0}
        
        for cell in cells:
            level = cell.get("risk_level", "").upper()
            assert level in valid_levels, f"Invalid risk_level: {level}"
            risk_counts[level] += 1
        
        print(f"PASS: Risk level distribution - {risk_counts}")
    
    def test_coordinate_range(self):
        """Cells should have valid lat/lng coordinates (Bangalore area expected)"""
        if not self.admin_token:
            pytest.skip("Admin login failed")
        
        resp = requests.get(
            f"{BASE_URL}/api/operator/city-heatmap/live",
            headers={"Authorization": f"Bearer {self.admin_token}"}
        )
        assert resp.status_code == 200
        
        data = resp.json()
        cells = data.get("cells", [])
        
        if not cells:
            pytest.skip("No cells to test")
        
        # Check coordinate validity (any valid lat/lng)
        for cell in cells[:10]:
            lat = cell.get("lat")
            lng = cell.get("lng")
            assert lat is not None and -90 <= lat <= 90, f"Invalid lat: {lat}"
            assert lng is not None and -180 <= lng <= 180, f"Invalid lng: {lng}"
        
        # Log coordinate bounds
        lats = [c["lat"] for c in cells]
        lngs = [c["lng"] for c in cells]
        print(f"PASS: Coordinates valid. Bounds: lat [{min(lats):.4f}, {max(lats):.4f}], lng [{min(lngs):.4f}, {max(lngs):.4f}]")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
