"""
Tests for Patrol AI ↔ City Heatmap Integration (Phase 31A)
Verifies heatmap boost scoring applied to patrol route zones.

Key features:
- WITHOUT heatmap: heatmap_enhanced=false, score_breakdown has heatmap_score=0, heatmap_risk=none, heatmap_boost=1.0
- WITH heatmap: heatmap_enhanced=true, heatmap_stats present, score_breakdown has non-zero heatmap_score, 
  heatmap_risk (critical/high/moderate/safe), heatmap_boost (1.25/1.12/1.0/0.9), heatmap_cell_id present
- Heatmap boost changes composite scores: zones in critical cells should have composite_score > base_composite_score
- Response includes base_composite_score field when heatmap is used
"""
import os
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestPatrolHeatmapIntegration:
    """Test patrol routing with and without heatmap integration."""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Authenticate as operator and get token."""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "operator@nischint.com",
            "password": "operator123"
        })
        assert response.status_code == 200, f"Login failed: {response.text}"
        data = response.json()
        return data.get("access_token")
    
    @pytest.fixture(scope="class")
    def auth_headers(self, auth_token):
        """Get authorization headers."""
        return {"Authorization": f"Bearer {auth_token}"}
    
    # ── Test WITHOUT heatmap ──
    
    def test_patrol_generate_without_heatmap_returns_200(self, auth_headers):
        """GET /api/operator/patrol/generate?shift=morning&max_zones=5 - WITHOUT heatmap returns 200."""
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "morning", "max_zones": 5},
            headers=auth_headers
        )
        assert response.status_code == 200, f"Failed: {response.text}"
    
    def test_patrol_without_heatmap_enhanced_false(self, auth_headers):
        """WITHOUT heatmap: heatmap_enhanced=false in response."""
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "morning", "max_zones": 5},
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "heatmap_enhanced" in data, "Missing heatmap_enhanced field"
        assert data["heatmap_enhanced"] == False, f"Expected heatmap_enhanced=false, got {data['heatmap_enhanced']}"
    
    def test_patrol_without_heatmap_stats_null(self, auth_headers):
        """WITHOUT heatmap: heatmap_stats should be null."""
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "morning", "max_zones": 5},
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("heatmap_stats") is None, f"Expected heatmap_stats=null, got {data.get('heatmap_stats')}"
    
    def test_patrol_without_heatmap_score_breakdown_defaults(self, auth_headers):
        """WITHOUT heatmap: score_breakdown has heatmap_score=0, heatmap_risk=none, heatmap_boost=1.0."""
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "morning", "max_zones": 5},
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        route = data.get("route", [])
        if route:
            zone = route[0]
            bd = zone.get("score_breakdown", {})
            
            assert bd.get("heatmap_score") == 0, f"Expected heatmap_score=0, got {bd.get('heatmap_score')}"
            assert bd.get("heatmap_risk") == "none", f"Expected heatmap_risk='none', got {bd.get('heatmap_risk')}"
            assert bd.get("heatmap_boost") == 1.0, f"Expected heatmap_boost=1.0, got {bd.get('heatmap_boost')}"
        else:
            pytest.skip("No route zones available for testing")
    
    # ── Test WITH heatmap ──
    
    def test_patrol_generate_with_heatmap_returns_200(self, auth_headers):
        """GET /api/operator/patrol/generate?shift=morning&max_zones=5&use_heatmap=true returns 200."""
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "morning", "max_zones": 5, "use_heatmap": True},
            headers=auth_headers,
            timeout=30  # Takes ~7-8 seconds due to heatmap generation
        )
        assert response.status_code == 200, f"Failed: {response.text}"
    
    def test_patrol_with_heatmap_enhanced_true(self, auth_headers):
        """WITH heatmap: heatmap_enhanced=true in response."""
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "morning", "max_zones": 5, "use_heatmap": True},
            headers=auth_headers,
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("heatmap_enhanced") == True, f"Expected heatmap_enhanced=true, got {data.get('heatmap_enhanced')}"
    
    def test_patrol_with_heatmap_stats_present(self, auth_headers):
        """WITH heatmap: heatmap_stats is present and contains expected fields."""
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "morning", "max_zones": 5, "use_heatmap": True},
            headers=auth_headers,
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        
        heatmap_stats = data.get("heatmap_stats")
        assert heatmap_stats is not None, "Expected heatmap_stats to be present"
        assert "critical" in heatmap_stats, "Missing 'critical' in heatmap_stats"
        assert "high" in heatmap_stats, "Missing 'high' in heatmap_stats"
        assert "moderate" in heatmap_stats, "Missing 'moderate' in heatmap_stats"
        assert "safe" in heatmap_stats, "Missing 'safe' in heatmap_stats"
    
    def test_patrol_with_heatmap_zone_score_breakdown_has_values(self, auth_headers):
        """WITH heatmap: score_breakdown has non-zero heatmap values where applicable."""
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "morning", "max_zones": 10, "use_heatmap": True},
            headers=auth_headers,
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        
        route = data.get("route", [])
        assert len(route) > 0, "No route zones returned"
        
        # Check that heatmap fields exist in score_breakdown
        for zone in route:
            bd = zone.get("score_breakdown", {})
            assert "heatmap_score" in bd, f"Missing heatmap_score in zone {zone.get('zone_id')}"
            assert "heatmap_risk" in bd, f"Missing heatmap_risk in zone {zone.get('zone_id')}"
            assert "heatmap_boost" in bd, f"Missing heatmap_boost in zone {zone.get('zone_id')}"
            
            # Verify heatmap_risk is valid
            valid_risks = ["critical", "high", "moderate", "safe", "none"]
            assert bd["heatmap_risk"] in valid_risks, f"Invalid heatmap_risk: {bd['heatmap_risk']}"
            
            # Verify heatmap_boost is one of expected values
            valid_boosts = [1.25, 1.12, 1.0, 0.9]
            assert bd["heatmap_boost"] in valid_boosts, f"Invalid heatmap_boost: {bd['heatmap_boost']}"
    
    def test_patrol_with_heatmap_has_base_composite_score(self, auth_headers):
        """WITH heatmap: each zone has base_composite_score field."""
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "morning", "max_zones": 5, "use_heatmap": True},
            headers=auth_headers,
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        
        route = data.get("route", [])
        assert len(route) > 0, "No route zones returned"
        
        for zone in route:
            assert "base_composite_score" in zone, f"Missing base_composite_score in zone {zone.get('zone_id')}"
            assert "composite_score" in zone, f"Missing composite_score in zone {zone.get('zone_id')}"
            assert isinstance(zone["base_composite_score"], (int, float)), "base_composite_score should be numeric"
    
    def test_patrol_with_heatmap_boost_critical_increases_score(self, auth_headers):
        """WITH heatmap: zones in critical cells should have composite_score > base_composite_score (boost x1.25)."""
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "morning", "max_zones": 15, "use_heatmap": True},
            headers=auth_headers,
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        
        route = data.get("route", [])
        
        # Find zones with critical heatmap risk
        critical_zones = [z for z in route if z.get("score_breakdown", {}).get("heatmap_risk") == "critical"]
        
        # If there are critical zones, verify the boost
        for zone in critical_zones:
            base = zone.get("base_composite_score", 0)
            boosted = zone.get("composite_score", 0)
            # composite_score should be approximately base * 1.25 (capped at 10)
            expected_min = base * 1.2  # Allow some tolerance
            assert boosted >= expected_min or boosted == 10.0, \
                f"Zone {zone.get('zone_name')}: expected boosted score ~{base * 1.25:.2f}, got {boosted}"
    
    def test_patrol_with_heatmap_boost_safe_decreases_score(self, auth_headers):
        """WITH heatmap: zones in safe cells should have composite_score < base_composite_score (boost x0.9)."""
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "morning", "max_zones": 15, "use_heatmap": True},
            headers=auth_headers,
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        
        route = data.get("route", [])
        
        # Find zones with safe heatmap risk
        safe_zones = [z for z in route if z.get("score_breakdown", {}).get("heatmap_risk") == "safe"]
        
        # If there are safe zones, verify the reduction
        for zone in safe_zones:
            base = zone.get("base_composite_score", 0)
            boosted = zone.get("composite_score", 0)
            # composite_score should be approximately base * 0.9
            expected_max = base * 0.95  # Allow some tolerance
            assert boosted <= expected_max, \
                f"Zone {zone.get('zone_name')}: expected boosted score ~{base * 0.9:.2f}, got {boosted}"
    
    def test_patrol_with_heatmap_cell_id_present(self, auth_headers):
        """WITH heatmap: score_breakdown includes heatmap_cell_id when matched to a cell."""
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "morning", "max_zones": 10, "use_heatmap": True},
            headers=auth_headers,
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        
        route = data.get("route", [])
        
        # Check zones with non-none heatmap_risk have cell_id
        for zone in route:
            bd = zone.get("score_breakdown", {})
            if bd.get("heatmap_risk") != "none":
                # Cell ID should be present for zones matched to heatmap cells
                assert "heatmap_cell_id" in bd, f"Zone {zone.get('zone_name')} matched to heatmap but missing cell_id"
    
    def test_patrol_with_heatmap_zone_enhanced_flag(self, auth_headers):
        """WITH heatmap: each zone in route has heatmap_enhanced=true."""
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "morning", "max_zones": 5, "use_heatmap": True},
            headers=auth_headers,
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        
        route = data.get("route", [])
        assert len(route) > 0, "No route zones returned"
        
        for zone in route:
            assert zone.get("heatmap_enhanced") == True, \
                f"Zone {zone.get('zone_name')} missing heatmap_enhanced=true"
    
    # ── Compare with and without heatmap ──
    
    def test_patrol_heatmap_affects_ordering(self, auth_headers):
        """Verify heatmap can affect route ordering (zones may be re-prioritized)."""
        # Get route without heatmap
        resp_no_hm = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "morning", "max_zones": 10},
            headers=auth_headers
        )
        assert resp_no_hm.status_code == 200
        data_no_hm = resp_no_hm.json()
        
        # Get route with heatmap
        resp_with_hm = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "morning", "max_zones": 10, "use_heatmap": True},
            headers=auth_headers,
            timeout=30
        )
        assert resp_with_hm.status_code == 200
        data_with_hm = resp_with_hm.json()
        
        # Get zone IDs in order
        order_no_hm = [z["zone_id"] for z in data_no_hm.get("route", [])]
        order_with_hm = [z["zone_id"] for z in data_with_hm.get("route", [])]
        
        # Both should have routes
        assert len(order_no_hm) > 0, "No zones in route without heatmap"
        assert len(order_with_hm) > 0, "No zones in route with heatmap"
        
        # Log comparison (order may or may not differ based on data)
        print(f"\nRoute without heatmap: {order_no_hm[:5]}")
        print(f"Route with heatmap: {order_with_hm[:5]}")
    
    def test_patrol_boost_multipliers_correct(self, auth_headers):
        """Verify heatmap boost multipliers match expected values: critical=1.25, high=1.12, moderate=1.0, safe=0.9."""
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "morning", "max_zones": 15, "use_heatmap": True},
            headers=auth_headers,
            timeout=30
        )
        assert response.status_code == 200
        data = response.json()
        
        route = data.get("route", [])
        
        expected_boosts = {
            "critical": 1.25,
            "high": 1.12,
            "moderate": 1.0,
            "safe": 0.9,
            "none": 1.0,
        }
        
        for zone in route:
            bd = zone.get("score_breakdown", {})
            risk = bd.get("heatmap_risk", "none")
            boost = bd.get("heatmap_boost", 1.0)
            
            expected = expected_boosts.get(risk, 1.0)
            assert boost == expected, \
                f"Zone {zone.get('zone_name')}: heatmap_risk={risk}, expected boost={expected}, got boost={boost}"


class TestPatrolHeatmapAuth:
    """Test authentication requirements for patrol heatmap endpoints."""
    
    def test_patrol_generate_requires_auth(self):
        """Patrol generate endpoint requires authentication."""
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "morning", "max_zones": 5}
        )
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
    
    def test_patrol_generate_with_heatmap_requires_auth(self):
        """Patrol generate with heatmap requires authentication."""
        response = requests.get(
            f"{BASE_URL}/api/operator/patrol/generate",
            params={"shift": "morning", "max_zones": 5, "use_heatmap": True}
        )
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
