# Test Incident Replay Engine - Risk Overlay Feature
# Tests for risk_overlay data in GET /api/operator/incidents/{incident_id}/replay
# Feature: Multi-Signal Overlays (location_risk, environment_risk, behavior_score)

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test Incident ID (SOS alert, critical)
TEST_INCIDENT_ID = "23b02397-f738-448f-8492-d7f82c6bc38e"

@pytest.fixture(scope="module")
def auth_token():
    """Get operator auth token."""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "operator@nischint.com",
        "password": "operator123"
    })
    if response.status_code == 200:
        return response.json().get("access_token")
    pytest.fail(f"Login failed: {response.status_code} - {response.text}")


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Auth headers with bearer token."""
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture(scope="module")
def replay_data(auth_headers):
    """Fetch replay data once for all tests."""
    response = requests.get(
        f"{BASE_URL}/api/operator/incidents/{TEST_INCIDENT_ID}/replay",
        headers=auth_headers
    )
    assert response.status_code == 200, f"Failed to fetch replay: {response.status_code}"
    return response.json()


class TestRiskOverlayStructure:
    """Tests for risk_overlay data structure in replay frames."""
    
    def test_frames_contain_risk_overlay(self, replay_data):
        """Every frame should have risk_overlay object."""
        frames = replay_data.get("frames", [])
        assert len(frames) > 0, "Expected at least one frame"
        
        for i, frame in enumerate(frames):
            assert "risk_overlay" in frame, f"Frame {i} missing risk_overlay"
        
        print(f"PASS: All {len(frames)} frames contain risk_overlay")
    
    def test_risk_overlay_has_required_fields(self, replay_data):
        """risk_overlay should have location_risk, environment_risk, behavior_score."""
        frames = replay_data.get("frames", [])
        required_fields = ["location_risk", "environment_risk", "behavior_score"]
        
        for i, frame in enumerate(frames[:5]):  # Check first 5 frames
            risk_overlay = frame.get("risk_overlay", {})
            for field in required_fields:
                assert field in risk_overlay, f"Frame {i} risk_overlay missing '{field}'"
        
        print(f"PASS: risk_overlay contains all required fields: {required_fields}")
    
    def test_risk_overlay_values_are_numeric(self, replay_data):
        """risk_overlay values should be numeric (float or int)."""
        frames = replay_data.get("frames", [])
        
        for i, frame in enumerate(frames[:10]):
            risk_overlay = frame.get("risk_overlay", {})
            
            location_risk = risk_overlay.get("location_risk")
            assert isinstance(location_risk, (int, float)), f"Frame {i}: location_risk should be numeric, got {type(location_risk)}"
            
            environment_risk = risk_overlay.get("environment_risk")
            assert isinstance(environment_risk, (int, float)), f"Frame {i}: environment_risk should be numeric, got {type(environment_risk)}"
            
            behavior_score = risk_overlay.get("behavior_score")
            assert isinstance(behavior_score, (int, float)), f"Frame {i}: behavior_score should be numeric, got {type(behavior_score)}"
        
        print("PASS: All risk_overlay values are numeric")
    
    def test_risk_overlay_values_in_valid_range(self, replay_data):
        """risk_overlay values should be within 0-10 range."""
        frames = replay_data.get("frames", [])
        
        for i, frame in enumerate(frames):
            risk_overlay = frame.get("risk_overlay", {})
            
            for field in ["location_risk", "environment_risk", "behavior_score"]:
                value = risk_overlay.get(field, 0)
                assert 0 <= value <= 10, f"Frame {i}: {field} value {value} outside 0-10 range"
        
        print("PASS: All risk_overlay values within 0-10 range")


class TestRiskOverlaySemantics:
    """Tests for risk_overlay semantic correctness."""
    
    def test_location_risk_default_zero_when_no_risk_zones(self, replay_data):
        """location_risk should be 0 when no risk zones nearby."""
        frames = replay_data.get("frames", [])
        location_risk_values = [f["risk_overlay"]["location_risk"] for f in frames]
        
        # For this test incident, there are no nearby risk zones
        # So location_risk should be 0 for all frames
        zero_count = sum(1 for v in location_risk_values if v == 0)
        
        # At least 90% should be 0 (accounting for potential edge cases)
        assert zero_count >= len(frames) * 0.9, f"Expected mostly 0 location_risk (no risk zones), got {zero_count}/{len(frames)}"
        
        print(f"PASS: location_risk is 0 for {zero_count}/{len(frames)} frames (no risk zones nearby)")
    
    def test_environment_risk_time_based_fallback(self, replay_data):
        """environment_risk should use time-based fallback when no env telemetry."""
        frames = replay_data.get("frames", [])
        
        # For SOS alert at ~06:45, environment risk should use early morning fallback (~3.0)
        first_frame = frames[0]
        env_risk = first_frame["risk_overlay"]["environment_risk"]
        
        # Expected range for early morning (5-8am): ~3.0
        assert 2.0 <= env_risk <= 5.0, f"Expected environment_risk ~3.0 for early morning, got {env_risk}"
        
        print(f"PASS: environment_risk uses time-based fallback ({env_risk} for early morning)")
    
    def test_behavior_score_zero_when_no_anomalies(self, replay_data):
        """behavior_score should be 0 when no behavior anomalies in window."""
        frames = replay_data.get("frames", [])
        stats = replay_data.get("stats", {})
        
        anomalies_count = stats.get("anomalies", 0)
        behavior_scores = [f["risk_overlay"]["behavior_score"] for f in frames]
        
        if anomalies_count == 0:
            # All behavior scores should be 0
            zero_count = sum(1 for s in behavior_scores if s == 0)
            assert zero_count == len(frames), f"Expected all behavior_scores to be 0 (no anomalies), got {zero_count}/{len(frames)}"
            print(f"PASS: behavior_score is 0 for all frames (no anomalies in window)")
        else:
            # Some frames should have non-zero behavior scores
            nonzero_count = sum(1 for s in behavior_scores if s > 0)
            print(f"INFO: {nonzero_count}/{len(frames)} frames have non-zero behavior_score ({anomalies_count} anomalies)")
    
    def test_risk_overlay_consistent_across_frames(self, replay_data):
        """risk_overlay values should be consistent (no wild jumps between adjacent frames)."""
        frames = replay_data.get("frames", [])
        
        max_delta = 0
        for i in range(1, min(len(frames), 50)):
            prev = frames[i-1]["risk_overlay"]
            curr = frames[i]["risk_overlay"]
            
            for field in ["location_risk", "environment_risk", "behavior_score"]:
                delta = abs(curr.get(field, 0) - prev.get(field, 0))
                max_delta = max(max_delta, delta)
                # No sudden jumps > 5 between adjacent frames (5s apart)
                assert delta <= 5, f"Frame {i}: {field} jumped by {delta} (max allowed: 5)"
        
        print(f"PASS: risk_overlay values consistent across frames (max delta: {max_delta})")


class TestChartDataFormat:
    """Tests for chart-compatible data format."""
    
    def test_risk_overlay_chart_data_array(self, replay_data):
        """Verify data can be transformed to chart format."""
        frames = replay_data.get("frames", [])
        
        # Transform to chart format (similar to frontend chartData)
        chart_data = []
        step = max(1, len(frames) // 120)  # Sample every 3rd frame
        
        for i, frame in enumerate(frames):
            if i % step == 0:
                chart_data.append({
                    "idx": i,
                    "time": frame["timestamp"][11:16] if frame.get("timestamp") else "",
                    "location": frame["risk_overlay"]["location_risk"],
                    "environment": frame["risk_overlay"]["environment_risk"],
                    "behavior": frame["risk_overlay"]["behavior_score"],
                })
        
        assert len(chart_data) > 0, "Expected chart data to have entries"
        
        # Verify chart data structure
        entry = chart_data[0]
        assert "idx" in entry and isinstance(entry["idx"], int)
        assert "time" in entry and isinstance(entry["time"], str)
        assert "location" in entry and isinstance(entry["location"], (int, float))
        assert "environment" in entry and isinstance(entry["environment"], (int, float))
        assert "behavior" in entry and isinstance(entry["behavior"], (int, float))
        
        print(f"PASS: {len(chart_data)} chart data points generated from {len(frames)} frames")
        print(f"      Sample: time={chart_data[0]['time']}, loc={chart_data[0]['location']}, env={chart_data[0]['environment']}, beh={chart_data[0]['behavior']}")


class TestMultiSignalOverlayIntegration:
    """Integration tests for multi-signal overlay feature."""
    
    def test_full_replay_response_structure(self, replay_data):
        """Verify complete replay response with risk_overlay data."""
        # Top-level fields
        assert replay_data.get("incident_id") == TEST_INCIDENT_ID
        assert replay_data.get("incident_type") == "sos_alert"
        assert replay_data.get("severity") == "critical"
        
        # Frames with risk_overlay
        frames = replay_data.get("frames", [])
        assert len(frames) > 0, "Expected frames"
        
        first_frame = frames[0]
        assert "risk_overlay" in first_frame
        assert "location_risk" in first_frame["risk_overlay"]
        assert "environment_risk" in first_frame["risk_overlay"]
        assert "behavior_score" in first_frame["risk_overlay"]
        
        # Events, location_trail, stats
        assert "events" in replay_data
        assert "location_trail" in replay_data
        assert "stats" in replay_data
        assert "ai_narrative" in replay_data
        
        print("PASS: Full replay response structure validated with risk_overlay data")
        print(f"      {len(frames)} frames, {len(replay_data.get('events', []))} events")
        print(f"      First frame risk_overlay: {first_frame['risk_overlay']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
