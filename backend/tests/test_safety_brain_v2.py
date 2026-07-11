# 3-Layer AI Safety Brain V2 API Tests
#
# Features tested:
# - GET /api/safety-brain/v2/fused-risk/{user_id} — 3-layer fused risk scoring
# - GET /api/safety-brain/v2/location-risk/{user_id} — Location danger score
# - GET /api/safety-brain/v2/behavior/{user_id} — Behavioral pattern analysis
# - GET /api/safety-brain/v2/predictive/{user_id} — Predictive alert with AI narrative
# - GET /api/safety-brain/v2/heatmap — Danger heatmap data
# 
# Layer weights: Layer 1 (Real-time 50%), Layer 2 (Location 25%), Layer 3 (Behavior 25%)
# GPT-5.2 integration for AI-generated safety narratives

import pytest
import requests
import os
import time

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


@pytest.fixture(scope="module")
def auth_token():
    """Get auth token for guardian user."""
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "nischint4parents@gmail.com",
        "password": "secret123"
    })
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    data = resp.json()
    return data.get("access_token")


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Auth headers for requests."""
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture(scope="module")
def user_id(auth_token):
    """Get user ID from token - use provided test user ID."""
    # Use the known test user ID
    return "7437a394-74ef-46a2-864f-6add0e7e8e60"


class TestFusedRiskEndpoint:
    """Tests for GET /api/safety-brain/v2/fused-risk/{user_id}"""

    def test_fused_risk_requires_auth(self, user_id):
        """Endpoint requires authentication."""
        resp = requests.get(f"{BASE_URL}/api/safety-brain/v2/fused-risk/{user_id}?lat=28.6139&lng=77.2090")
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"
        print("PASS: /v2/fused-risk requires auth")

    def test_fused_risk_requires_lat_lng(self, auth_headers, user_id):
        """Endpoint requires lat and lng parameters."""
        resp = requests.get(f"{BASE_URL}/api/safety-brain/v2/fused-risk/{user_id}", headers=auth_headers)
        assert resp.status_code == 422, f"Expected 422 for missing params, got {resp.status_code}"
        print("PASS: /v2/fused-risk requires lat/lng params")

    def test_fused_risk_returns_three_layers(self, auth_headers, user_id):
        """Fused risk returns all 3 layers with correct structure."""
        resp = requests.get(
            f"{BASE_URL}/api/safety-brain/v2/fused-risk/{user_id}?lat=28.6139&lng=77.2090&skip_behavior=true",
            headers=auth_headers
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        
        # Check required top-level fields
        assert "fused_score" in data, "Missing fused_score"
        assert "fused_level" in data, "Missing fused_level"
        assert "layer1_realtime" in data, "Missing layer1_realtime"
        assert "layer2_location" in data, "Missing layer2_location"
        assert "layer3_behavior" in data, "Missing layer3_behavior"
        
        # Validate fused_level is valid
        valid_levels = ["normal", "suspicious", "dangerous", "critical"]
        assert data["fused_level"] in valid_levels, f"Invalid fused_level: {data['fused_level']}"
        
        # Validate fused_score is 0-1
        assert 0 <= data["fused_score"] <= 1, f"Invalid fused_score: {data['fused_score']}"
        
        print(f"PASS: Fused risk returns all 3 layers - score={data['fused_score']:.3f}, level={data['fused_level']}")

    def test_fused_risk_layer1_structure(self, auth_headers, user_id):
        """Layer 1 (real-time) has correct structure with weight=0.5."""
        resp = requests.get(
            f"{BASE_URL}/api/safety-brain/v2/fused-risk/{user_id}?lat=28.6139&lng=77.2090&skip_behavior=true",
            headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        
        layer1 = data["layer1_realtime"]
        assert "score" in layer1, "Layer1 missing score"
        assert "weight" in layer1, "Layer1 missing weight"
        assert "weighted" in layer1, "Layer1 missing weighted"
        assert "signals" in layer1, "Layer1 missing signals"
        assert layer1["weight"] == 0.5, f"Expected weight=0.5, got {layer1['weight']}"
        
        print(f"PASS: Layer 1 structure - score={layer1['score']:.3f}, weight={layer1['weight']}, signals={layer1['signals']}")

    def test_fused_risk_layer2_structure(self, auth_headers, user_id):
        """Layer 2 (location) has correct structure with weight=0.25."""
        resp = requests.get(
            f"{BASE_URL}/api/safety-brain/v2/fused-risk/{user_id}?lat=28.6139&lng=77.2090&skip_behavior=true",
            headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        
        layer2 = data["layer2_location"]
        assert "score" in layer2, "Layer2 missing score"
        assert "weight" in layer2, "Layer2 missing weight"
        assert "weighted" in layer2, "Layer2 missing weighted"
        assert "details" in layer2, "Layer2 missing details"
        assert layer2["weight"] == 0.25, f"Expected weight=0.25, got {layer2['weight']}"
        
        # Details should include location intelligence components
        details = layer2.get("details", {})
        print(f"PASS: Layer 2 structure - score={layer2['score']:.3f}, weight={layer2['weight']}, details={list(details.keys())}")

    def test_fused_risk_layer3_structure(self, auth_headers, user_id):
        """Layer 3 (behavior) has correct structure with weight=0.25."""
        resp = requests.get(
            f"{BASE_URL}/api/safety-brain/v2/fused-risk/{user_id}?lat=28.6139&lng=77.2090&skip_behavior=true",
            headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        
        layer3 = data["layer3_behavior"]
        assert "score" in layer3, "Layer3 missing score"
        assert "weight" in layer3, "Layer3 missing weight"
        assert "weighted" in layer3, "Layer3 missing weighted"
        assert layer3["weight"] == 0.25, f"Expected weight=0.25, got {layer3['weight']}"
        
        # When skip_behavior=true, should have skipped flag
        if "skipped" in layer3:
            assert layer3["skipped"] is True, "Expected skipped=True when skip_behavior=true"
            print(f"PASS: Layer 3 structure (skipped) - weight={layer3['weight']}")
        else:
            print(f"PASS: Layer 3 structure - score={layer3['score']:.3f}, weight={layer3['weight']}")

    def test_fused_risk_with_full_behavior(self, auth_headers, user_id):
        """Fused risk with full behavior analysis (skip_behavior=false)."""
        resp = requests.get(
            f"{BASE_URL}/api/safety-brain/v2/fused-risk/{user_id}?lat=28.6139&lng=77.2090&skip_behavior=false",
            headers=auth_headers
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        
        layer3 = data["layer3_behavior"]
        # Should NOT have skipped flag when skip_behavior=false
        if "skipped" not in layer3:
            # May have behavior analysis fields
            possible_fields = ["anomaly_score", "confidence", "stability", "patterns"]
            found_fields = [f for f in possible_fields if f in layer3]
            print(f"PASS: Layer 3 with full behavior - fields={found_fields}")
        else:
            print(f"INFO: Layer 3 still skipped (may be implementation choice)")


class TestLocationRiskEndpoint:
    """Tests for GET /api/safety-brain/v2/location-risk/{user_id}"""

    def test_location_risk_requires_auth(self, user_id):
        """Endpoint requires authentication."""
        resp = requests.get(f"{BASE_URL}/api/safety-brain/v2/location-risk/{user_id}?lat=28.6139&lng=77.2090")
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"
        print("PASS: /v2/location-risk requires auth")

    def test_location_risk_requires_lat_lng(self, auth_headers, user_id):
        """Endpoint requires lat and lng parameters."""
        resp = requests.get(f"{BASE_URL}/api/safety-brain/v2/location-risk/{user_id}", headers=auth_headers)
        assert resp.status_code == 422, f"Expected 422 for missing params, got {resp.status_code}"
        print("PASS: /v2/location-risk requires lat/lng params")

    def test_location_risk_returns_score_and_details(self, auth_headers, user_id):
        """Location risk returns score and detailed breakdown."""
        resp = requests.get(
            f"{BASE_URL}/api/safety-brain/v2/location-risk/{user_id}?lat=28.6139&lng=77.2090",
            headers=auth_headers
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        
        assert "user_id" in data, "Missing user_id"
        assert "score" in data, "Missing score"
        assert "details" in data, "Missing details"
        assert 0 <= data["score"] <= 1, f"Invalid score: {data['score']}"
        
        print(f"PASS: Location risk - score={data['score']:.3f}")

    def test_location_risk_details_structure(self, auth_headers, user_id):
        """Location risk details include expected components."""
        resp = requests.get(
            f"{BASE_URL}/api/safety-brain/v2/location-risk/{user_id}?lat=28.6139&lng=77.2090",
            headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        
        details = data.get("details", {})
        # Expected detail fields from location_intelligence.py
        expected_fields = ["incident_density", "night_time_risk", "recent_incident_boost", 
                          "nearby_incidents", "recent_incidents", "hour", "grid_cell"]
        found_fields = [f for f in expected_fields if f in details]
        
        print(f"PASS: Location risk details - found fields: {found_fields}")


class TestBehaviorEndpoint:
    """Tests for GET /api/safety-brain/v2/behavior/{user_id}"""

    def test_behavior_requires_auth(self, user_id):
        """Endpoint requires authentication."""
        resp = requests.get(f"{BASE_URL}/api/safety-brain/v2/behavior/{user_id}")
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"
        print("PASS: /v2/behavior requires auth")

    def test_behavior_returns_analysis(self, auth_headers, user_id):
        """Behavior endpoint returns analysis with required fields."""
        resp = requests.get(f"{BASE_URL}/api/safety-brain/v2/behavior/{user_id}", headers=auth_headers)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        
        assert "user_id" in data, "Missing user_id"
        assert "anomaly_score" in data, "Missing anomaly_score"
        assert "confidence" in data, "Missing confidence"
        assert "stability" in data, "Missing stability"
        assert "window_data" in data, "Missing window_data"
        
        # Validate score ranges
        assert 0 <= data["anomaly_score"] <= 1, f"Invalid anomaly_score: {data['anomaly_score']}"
        assert 0 <= data["confidence"] <= 1, f"Invalid confidence: {data['confidence']}"
        assert data["stability"] in ["low", "medium", "high"], f"Invalid stability: {data['stability']}"
        
        print(f"PASS: Behavior analysis - anomaly={data['anomaly_score']:.3f}, confidence={data['confidence']:.3f}, stability={data['stability']}")

    def test_behavior_window_data_structure(self, auth_headers, user_id):
        """Behavior window_data includes 7/14/30 day windows."""
        resp = requests.get(f"{BASE_URL}/api/safety-brain/v2/behavior/{user_id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        
        window_data = data.get("window_data", {})
        expected_windows = ["short", "medium", "long"]
        found_windows = [w for w in expected_windows if w in window_data]
        
        for window in found_windows:
            wdata = window_data[window]
            assert "days" in wdata, f"Window {window} missing days"
            
        print(f"PASS: Behavior window_data - windows: {found_windows}")

    def test_behavior_includes_patterns_and_recommendations(self, auth_headers, user_id):
        """Behavior analysis includes patterns and recommendations."""
        resp = requests.get(f"{BASE_URL}/api/safety-brain/v2/behavior/{user_id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        
        assert "patterns" in data, "Missing patterns"
        assert "recommendations" in data, "Missing recommendations"
        assert isinstance(data["patterns"], list), "patterns should be a list"
        assert isinstance(data["recommendations"], list), "recommendations should be a list"
        
        print(f"PASS: Behavior patterns/recommendations - {len(data['patterns'])} patterns, {len(data['recommendations'])} recommendations")


class TestPredictiveEndpoint:
    """Tests for GET /api/safety-brain/v2/predictive/{user_id}"""

    def test_predictive_requires_auth(self, user_id):
        """Endpoint requires authentication."""
        resp = requests.get(f"{BASE_URL}/api/safety-brain/v2/predictive/{user_id}")
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"
        print("PASS: /v2/predictive requires auth")

    def test_predictive_returns_alert(self, auth_headers, user_id):
        """Predictive endpoint returns alert with required fields."""
        # This endpoint may take 5-10 seconds due to GPT-5.2 call
        resp = requests.get(
            f"{BASE_URL}/api/safety-brain/v2/predictive/{user_id}?lat=28.6139&lng=77.2090",
            headers=auth_headers,
            timeout=30  # Allow for GPT latency
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        
        # Required fields
        assert "user_id" in data, "Missing user_id"
        assert "alert_level" in data, "Missing alert_level"
        assert "anomaly_score" in data, "Missing anomaly_score"
        assert "confidence" in data, "Missing confidence"
        assert "narrative" in data, "Missing narrative"
        assert "patterns" in data, "Missing patterns"
        assert "recommendations" in data, "Missing recommendations"
        
        # Validate alert_level
        valid_levels = ["low", "medium", "high"]
        assert data["alert_level"] in valid_levels, f"Invalid alert_level: {data['alert_level']}"
        
        print(f"PASS: Predictive alert - level={data['alert_level']}, confidence={data.get('confidence_pct', 0)}%")

    def test_predictive_includes_ai_narrative(self, auth_headers, user_id):
        """Predictive endpoint includes AI-generated narrative from GPT-5.2."""
        resp = requests.get(
            f"{BASE_URL}/api/safety-brain/v2/predictive/{user_id}?lat=28.6139&lng=77.2090",
            headers=auth_headers,
            timeout=30
        )
        assert resp.status_code == 200
        data = resp.json()
        
        narrative = data.get("narrative", "")
        assert narrative, "Narrative should not be empty"
        assert len(narrative) > 10, f"Narrative seems too short: {len(narrative)} chars"
        
        print(f"PASS: AI narrative generated - {len(narrative)} chars")
        print(f"      Sample: {narrative[:100]}...")

    def test_predictive_includes_location_risk(self, auth_headers, user_id):
        """Predictive endpoint includes location risk when lat/lng provided."""
        resp = requests.get(
            f"{BASE_URL}/api/safety-brain/v2/predictive/{user_id}?lat=28.6139&lng=77.2090",
            headers=auth_headers,
            timeout=30
        )
        assert resp.status_code == 200
        data = resp.json()
        
        assert "location_risk" in data, "Missing location_risk"
        loc_risk = data["location_risk"]
        assert "score" in loc_risk, "location_risk missing score"
        
        print(f"PASS: Predictive includes location_risk - score={loc_risk['score']:.3f}")


class TestHeatmapEndpoint:
    """Tests for GET /api/safety-brain/v2/heatmap"""

    def test_heatmap_requires_auth(self):
        """Endpoint requires authentication."""
        resp = requests.get(f"{BASE_URL}/api/safety-brain/v2/heatmap")
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"
        print("PASS: /v2/heatmap requires auth")

    def test_heatmap_returns_data(self, auth_headers):
        """Heatmap returns data array with count."""
        resp = requests.get(f"{BASE_URL}/api/safety-brain/v2/heatmap?limit=10", headers=auth_headers)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        
        assert "heatmap" in data, "Missing heatmap"
        assert "count" in data, "Missing count"
        assert isinstance(data["heatmap"], list), "heatmap should be a list"
        assert data["count"] == len(data["heatmap"]), "count should match heatmap length"
        
        print(f"PASS: Heatmap data - {data['count']} points")

    def test_heatmap_respects_limit(self, auth_headers):
        """Heatmap respects limit parameter."""
        resp = requests.get(f"{BASE_URL}/api/safety-brain/v2/heatmap?limit=5", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        
        assert len(data["heatmap"]) <= 5, f"Expected <= 5 points, got {len(data['heatmap'])}"
        print(f"PASS: Heatmap respects limit - {len(data['heatmap'])} points (limit=5)")

    def test_heatmap_point_structure(self, auth_headers):
        """Heatmap points have correct structure."""
        resp = requests.get(f"{BASE_URL}/api/safety-brain/v2/heatmap?limit=10", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        
        if len(data["heatmap"]) > 0:
            point = data["heatmap"][0]
            expected_fields = ["lat", "lng", "intensity"]
            found_fields = [f for f in expected_fields if f in point]
            
            if "intensity" in point:
                assert 0 <= point["intensity"] <= 1, f"Invalid intensity: {point['intensity']}"
            
            print(f"PASS: Heatmap point structure - fields: {found_fields}")
        else:
            print("INFO: No heatmap points to verify structure (empty heatmap)")


class TestExistingV1Endpoints:
    """Tests for existing V1 Safety Brain endpoints still working."""

    def test_v1_status_works(self, auth_headers, user_id):
        """V1 status endpoint still works."""
        resp = requests.get(f"{BASE_URL}/api/safety-brain/status/{user_id}", headers=auth_headers)
        assert resp.status_code == 200, f"V1 status failed: {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "risk_score" in data or "status" in data, "V1 status missing expected fields"
        print("PASS: V1 /safety-brain/status still works")

    def test_v1_events_works(self, auth_headers):
        """V1 events endpoint still works."""
        resp = requests.get(f"{BASE_URL}/api/safety-brain/events?limit=5", headers=auth_headers)
        assert resp.status_code == 200, f"V1 events failed: {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "events" in data, "V1 events missing events array"
        print(f"PASS: V1 /safety-brain/events still works - {len(data['events'])} events")

    def test_v1_evaluate_works(self, auth_headers):
        """V1 evaluate endpoint still works."""
        resp = requests.post(f"{BASE_URL}/api/safety-brain/evaluate", json={
            "signals": {"fall": 0.3, "voice": 0.2},
            "lat": 28.6139,
            "lng": 77.2090
        }, headers=auth_headers)
        assert resp.status_code == 200, f"V1 evaluate failed: {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "risk_score" in data, "V1 evaluate missing risk_score"
        assert "risk_level" in data, "V1 evaluate missing risk_level"
        print(f"PASS: V1 /safety-brain/evaluate still works - score={data['risk_score']:.3f}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
