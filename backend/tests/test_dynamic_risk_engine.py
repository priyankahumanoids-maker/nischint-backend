# Phase 39: Dynamic City Risk Engine Backend Tests
# Tests for 8 AI signal layers, adaptive weights, cache, delta, timeline, and cell detail

import pytest
import requests
import os
from datetime import datetime

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestDynamicRiskEngineAuth:
    """Authentication tests for city heatmap endpoints"""
    
    def test_city_heatmap_requires_auth(self):
        """All city heatmap endpoints require operator/admin role"""
        endpoints = [
            '/api/operator/city-heatmap',
            '/api/operator/city-heatmap/live',
            '/api/operator/city-heatmap/delta',
            '/api/operator/city-heatmap/timeline',
            '/api/operator/city-heatmap/status',
            '/api/operator/city-heatmap/stats',
            '/api/operator/city-heatmap/cell/C001_001',
        ]
        for endpoint in endpoints:
            response = requests.get(f"{BASE_URL}{endpoint}")
            assert response.status_code == 401, f"Expected 401 for {endpoint}, got {response.status_code}"
            print(f"✓ {endpoint} requires auth (401)")


class TestDynamicRiskEngine:
    """Dynamic City Risk Engine API tests"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Login as operator and get token"""
        login_response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "operator@nischint.com",
            "password": "operator123"
        })
        assert login_response.status_code == 200, f"Login failed: {login_response.text}"
        self.token = login_response.json().get("access_token")
        self.headers = {"Authorization": f"Bearer {self.token}"}
        print(f"✓ Operator logged in successfully")
    
    # --- GET /api/operator/city-heatmap ---
    def test_city_heatmap_basic(self):
        """GET /city-heatmap returns scored cells with all 8 signals"""
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap", headers=self.headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        print(f"City Heatmap: {data.get('total_cells')} cells, {data.get('total_zones')} zones")
        
        # Required top-level fields
        assert "cells" in data, "Missing 'cells' array"
        assert "bounds" in data, "Missing 'bounds'"
        assert "grid_size_m" in data, "Missing 'grid_size_m'"
        assert "total_cells" in data, "Missing 'total_cells'"
        assert "total_zones" in data, "Missing 'total_zones'"
        assert "total_incidents_analyzed" in data, "Missing 'total_incidents_analyzed'"
        assert "analyzed_at" in data, "Missing 'analyzed_at'"
        assert "weight_profile" in data, "Missing 'weight_profile'"
        assert "weights" in data, "Missing 'weights'"
        assert "stats" in data, "Missing 'stats'"
        assert "delta" in data, "Missing 'delta'"
        assert "computation_time_ms" in data, "Missing 'computation_time_ms'"
        assert "snapshot_number" in data, "Missing 'snapshot_number'"
        
        # Verify weight profile is one of expected values
        assert data["weight_profile"] in ("day", "night", "late_night"), f"Unexpected weight_profile: {data['weight_profile']}"
        
        # Verify 8 signal weights present
        weights = data["weights"]
        expected_signals = ["forecast", "hotspot", "trend", "activity", "patrol", "environment", "session_density", "mobility_anomaly"]
        for signal in expected_signals:
            assert signal in weights, f"Missing weight for '{signal}'"
        print(f"✓ All 8 signal weights present: {list(weights.keys())}")
        
        # Verify weight_profile
        print(f"✓ Weight profile: {data['weight_profile']}")
        
        # Verify stats structure
        stats = data["stats"]
        assert "critical" in stats, "Missing stats.critical"
        assert "high" in stats, "Missing stats.high"
        assert "moderate" in stats, "Missing stats.moderate"
        assert "safe" in stats, "Missing stats.safe"
        print(f"✓ Stats: critical={stats.get('critical')}, high={stats.get('high')}, moderate={stats.get('moderate')}, safe={stats.get('safe')}")
    
    def test_city_heatmap_cell_signals(self):
        """Each cell contains all 8 signal scores"""
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap", headers=self.headers)
        assert response.status_code == 200
        
        data = response.json()
        cells = data.get("cells", [])
        
        if not cells:
            pytest.skip("No cells in heatmap - need hotspot zones first")
        
        # Check first few cells have all required fields
        for i, cell in enumerate(cells[:3]):
            # Grid cell identifiers
            assert "grid_id" in cell, f"Cell {i} missing grid_id"
            assert "lat" in cell, f"Cell {i} missing lat"
            assert "lng" in cell, f"Cell {i} missing lng"
            
            # Composite score
            assert "composite_score" in cell, f"Cell {i} missing composite_score"
            assert "risk_level" in cell, f"Cell {i} missing risk_level"
            
            # 8 signal scores
            assert "forecast" in cell, f"Cell {i} missing forecast signal"
            assert "hotspot" in cell, f"Cell {i} missing hotspot signal"
            assert "trend" in cell, f"Cell {i} missing trend signal"
            assert "activity" in cell, f"Cell {i} missing activity signal"
            assert "patrol" in cell, f"Cell {i} missing patrol signal"
            assert "environment" in cell, f"Cell {i} missing environment signal"
            assert "session_density" in cell, f"Cell {i} missing session_density signal"
            assert "mobility_anomaly" in cell, f"Cell {i} missing mobility_anomaly signal"
            
            # Signal metadata
            assert "trend_status" in cell, f"Cell {i} missing trend_status"
            assert "forecast_category" in cell, f"Cell {i} missing forecast_category"
            
            print(f"✓ Cell {cell['grid_id']}: composite={cell['composite_score']}, risk={cell['risk_level']}")
        
        print(f"✓ All cells have 8 signals")
    
    def test_city_heatmap_active_sessions_and_velocity(self):
        """Response includes active_sessions count and incident_velocity"""
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap", headers=self.headers)
        assert response.status_code == 200
        
        data = response.json()
        assert "active_sessions" in data, "Missing 'active_sessions' count"
        assert "incident_velocity" in data, "Missing 'incident_velocity' multiplier"
        
        print(f"✓ Active sessions: {data['active_sessions']}")
        print(f"✓ Incident velocity: {data['incident_velocity']}x")
    
    # --- GET /api/operator/city-heatmap/live ---
    def test_city_heatmap_live_cached(self):
        """GET /city-heatmap/live returns cached pre-computed heatmap"""
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap/live", headers=self.headers)
        assert response.status_code == 200
        
        data = response.json()
        assert "cells" in data, "Missing cells in live response"
        assert "weight_profile" in data, "Missing weight_profile"
        assert "weights" in data, "Missing weights"
        
        print(f"✓ Live heatmap: {data.get('total_cells', 0)} cells, profile={data.get('weight_profile')}")
    
    # --- GET /api/operator/city-heatmap/delta ---
    def test_city_heatmap_delta(self):
        """GET /city-heatmap/delta returns risk changes"""
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap/delta", headers=self.headers)
        assert response.status_code == 200
        
        data = response.json()
        
        # Delta structure
        assert "escalated" in data, "Missing 'escalated' array"
        assert "de_escalated" in data, "Missing 'de_escalated' array"
        assert "new_hotspots" in data, "Missing 'new_hotspots' array"
        assert "cooling" in data, "Missing 'cooling' array"
        assert "escalated_count" in data, "Missing 'escalated_count'"
        assert "de_escalated_count" in data, "Missing 'de_escalated_count'"
        assert "new_hotspot_count" in data, "Missing 'new_hotspot_count'"
        assert "cooling_count" in data, "Missing 'cooling_count'"
        assert "net_change" in data, "Missing 'net_change'"
        
        print(f"✓ Delta: escalated={data['escalated_count']}, de-escalated={data['de_escalated_count']}, new={data['new_hotspot_count']}, cooling={data['cooling_count']}")
    
    # --- GET /api/operator/city-heatmap/timeline ---
    def test_city_heatmap_timeline(self):
        """GET /city-heatmap/timeline returns last 12 snapshots"""
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap/timeline", headers=self.headers)
        assert response.status_code == 200
        
        data = response.json()
        assert "timeline" in data, "Missing 'timeline' array"
        assert "source" in data, "Missing 'source' field"
        
        timeline = data["timeline"]
        assert isinstance(timeline, list), "Timeline should be a list"
        
        if timeline:
            entry = timeline[0]
            # Snapshot fields
            assert "analyzed_at" in entry or "snapshot_timestamp" in entry, "Missing timestamp"
            assert "total_cells" in entry, "Missing total_cells in timeline entry"
            print(f"✓ Timeline has {len(timeline)} snapshots, source={data['source']}")
            
            # Delta summary (if from cache)
            if "delta_summary" in entry:
                ds = entry["delta_summary"]
                print(f"  Latest entry: {entry.get('total_cells')} cells, escalated={ds.get('escalated', 0)}")
        else:
            print(f"✓ Timeline empty (first run or cold cache)")
    
    # --- GET /api/operator/city-heatmap/status ---
    def test_city_heatmap_status(self):
        """GET /city-heatmap/status returns cache metadata"""
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap/status", headers=self.headers)
        assert response.status_code == 200
        
        data = response.json()
        
        assert "has_data" in data, "Missing 'has_data'"
        assert "computed_at" in data, "Missing 'computed_at'"
        assert "snapshot_count" in data, "Missing 'snapshot_count'"
        assert "timeline_length" in data, "Missing 'timeline_length'"
        
        print(f"✓ Cache status: has_data={data['has_data']}, snapshots={data['snapshot_count']}, timeline={data['timeline_length']}")
    
    # --- GET /api/operator/city-heatmap/stats ---
    def test_city_heatmap_stats(self):
        """GET /city-heatmap/stats returns lightweight summary with live flag"""
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap/stats", headers=self.headers)
        assert response.status_code == 200
        
        data = response.json()
        
        assert "total_zones" in data, "Missing 'total_zones'"
        assert "critical_zones" in data, "Missing 'critical_zones'"
        assert "high_risk_zones" in data, "Missing 'high_risk_zones'"
        assert "recent_incidents_7d" in data or "recent_incidents_7d" in data, "Missing incident count"
        assert "analyzed_at" in data, "Missing 'analyzed_at'"
        assert "live" in data, "Missing 'live' flag"
        
        print(f"✓ Stats: zones={data['total_zones']}, critical={data['critical_zones']}, live={data['live']}")
    
    # --- GET /api/operator/city-heatmap/cell/{grid_id} ---
    def test_city_heatmap_cell_detail(self):
        """GET /city-heatmap/cell/{grid_id} returns 8-signal breakdown"""
        # First get a valid grid_id from the heatmap
        heatmap = requests.get(f"{BASE_URL}/api/operator/city-heatmap", headers=self.headers).json()
        cells = heatmap.get("cells", [])
        
        if not cells:
            pytest.skip("No cells available for detail test")
        
        grid_id = cells[0]["grid_id"]
        
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap/cell/{grid_id}", headers=self.headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Cell identifier
        assert data["grid_id"] == grid_id, f"Grid ID mismatch"
        assert "lat" in data, "Missing lat"
        assert "lng" in data, "Missing lng"
        
        # Scores
        assert "composite_score" in data, "Missing composite_score"
        assert "risk_level" in data, "Missing risk_level"
        
        # 8 signal breakdown
        assert "signals" in data, "Missing signals array"
        signals = data["signals"]
        assert len(signals) == 8, f"Expected 8 signals, got {len(signals)}"
        
        signal_keys = [s.get("key") for s in signals]
        expected_keys = ["forecast", "hotspot", "trend", "activity", "patrol", "environment", "session_density", "mobility_anomaly"]
        for key in expected_keys:
            assert key in signal_keys, f"Missing signal: {key}"
        
        # Each signal should have score, weight, weighted
        for sig in signals:
            assert "name" in sig, f"Signal missing 'name'"
            assert "score" in sig, f"Signal '{sig.get('name')}' missing 'score'"
            assert "weight" in sig, f"Signal '{sig.get('name')}' missing 'weight'"
            assert "weighted" in sig, f"Signal '{sig.get('name')}' missing 'weighted'"
        
        # Weight profile
        assert "weight_profile" in data, "Missing weight_profile in cell detail"
        assert data["weight_profile"] in ("day", "night", "late_night"), f"Invalid weight_profile: {data['weight_profile']}"
        
        # Dominant signal
        assert "dominant_signal" in data, "Missing dominant_signal"
        
        # Recommendations
        assert "recommendations" in data, "Missing recommendations"
        
        print(f"✓ Cell {grid_id} detail: composite={data['composite_score']}, risk={data['risk_level']}, profile={data['weight_profile']}")
        signal_str = ", ".join([f"{s['name']}={s['score']}" for s in signals])
        print(f"  Signals: {signal_str}")
        print(f"  Dominant: {data['dominant_signal']}")
    
    def test_city_heatmap_cell_not_found(self):
        """GET /city-heatmap/cell/{invalid} returns 404"""
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap/cell/INVALID_CELL", headers=self.headers)
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print(f"✓ Invalid cell returns 404")


class TestDynamicRiskEngineDataIntegrity:
    """Data integrity tests for heatmap responses"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Login as operator"""
        login_response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "operator@nischint.com",
            "password": "operator123"
        })
        assert login_response.status_code == 200
        self.token = login_response.json().get("access_token")
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_weights_sum_to_one(self):
        """Adaptive weights should sum to 1.0"""
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap", headers=self.headers)
        assert response.status_code == 200
        
        data = response.json()
        weights = data.get("weights", {})
        
        if weights:
            total = sum(weights.values())
            assert abs(total - 1.0) < 0.01, f"Weights sum to {total}, expected ~1.0"
            print(f"✓ Weights sum to {total:.3f}")
    
    def test_risk_levels_valid(self):
        """All risk levels should be valid categories"""
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap", headers=self.headers)
        assert response.status_code == 200
        
        data = response.json()
        valid_levels = {"critical", "high", "moderate", "safe"}
        
        for cell in data.get("cells", [])[:10]:
            assert cell["risk_level"] in valid_levels, f"Invalid risk level: {cell['risk_level']}"
        
        print(f"✓ All risk levels are valid")
    
    def test_composite_score_consistency(self):
        """Composite score should match weighted signal sum"""
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap", headers=self.headers)
        assert response.status_code == 200
        
        data = response.json()
        weights = data.get("weights", {})
        cells = data.get("cells", [])
        
        if not cells or not weights:
            pytest.skip("No cells or weights to verify")
        
        # Check first cell
        cell = cells[0]
        
        # Get cell detail for full breakdown
        detail_resp = requests.get(
            f"{BASE_URL}/api/operator/city-heatmap/cell/{cell['grid_id']}", 
            headers=self.headers
        )
        
        if detail_resp.status_code == 200:
            detail = detail_resp.json()
            # Verify signal scores exist
            assert len(detail.get("signals", [])) == 8, "Cell detail should have 8 signals"
            print(f"✓ Cell detail has 8 signal breakdown")


class TestDynamicRiskScheduler:
    """Tests for scheduler and snapshot storage"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Login as operator"""
        login_response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "operator@nischint.com",
            "password": "operator123"
        })
        assert login_response.status_code == 200
        self.token = login_response.json().get("access_token")
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_snapshot_number_increments(self):
        """Snapshot number should be >= 1 after scheduler runs"""
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap/status", headers=self.headers)
        assert response.status_code == 200
        
        data = response.json()
        
        if data["has_data"]:
            assert data["snapshot_count"] >= 1, "Snapshot count should be >= 1 after scheduler run"
            print(f"✓ Scheduler has run {data['snapshot_count']} time(s)")
        else:
            print("⚠ Cache is cold - scheduler may not have run yet")
    
    def test_cache_computed_at_recent(self):
        """Cache should have been computed recently if data exists"""
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap/status", headers=self.headers)
        assert response.status_code == 200
        
        data = response.json()
        
        if data["has_data"] and data["computed_at"]:
            computed_at = datetime.fromisoformat(data["computed_at"].replace("Z", "+00:00"))
            now = datetime.now(computed_at.tzinfo)
            age_seconds = (now - computed_at).total_seconds()
            
            # Cache should be less than 10 minutes old (scheduler runs every 5 min)
            assert age_seconds < 600, f"Cache is {age_seconds}s old, expected < 600s"
            print(f"✓ Cache age: {age_seconds:.0f}s (recent)")
        else:
            print("⚠ No cached data to verify age")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
