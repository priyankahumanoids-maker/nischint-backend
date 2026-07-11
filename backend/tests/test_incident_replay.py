# Test Incident Replay Engine - API Endpoints
# Tests for GET /api/operator/incidents/{incident_id}/replay and GET /api/operator/incidents/{incident_id}/timeline

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test Incident ID (provided: SOS alert, critical)
TEST_INCIDENT_ID = "23b02397-f738-448f-8492-d7f82c6bc38e"
INVALID_INCIDENT_ID = "00000000-0000-0000-0000-000000000000"

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


class TestIncidentReplayEndpoint:
    """Tests for GET /api/operator/incidents/{incident_id}/replay"""
    
    def test_replay_requires_authentication(self):
        """Replay endpoint requires auth."""
        response = requests.get(f"{BASE_URL}/api/operator/incidents/{TEST_INCIDENT_ID}/replay")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("PASS: Replay endpoint requires authentication")
    
    def test_replay_returns_full_dataset(self, auth_headers):
        """Replay returns complete replay dataset with all required fields."""
        response = requests.get(
            f"{BASE_URL}/api/operator/incidents/{TEST_INCIDENT_ID}/replay",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Verify top-level required fields
        required_fields = [
            "incident_id", "device_id", "device_identifier", "senior_name",
            "incident_type", "severity", "status", "escalation_level",
            "incident_time", "replay_window", "frames", "events", 
            "location_trail", "stats", "ai_narrative"
        ]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        
        print(f"PASS: Replay returns full dataset - incident_type={data['incident_type']}, severity={data['severity']}")
        print(f"      Device: {data['device_identifier']}, Senior: {data['senior_name']}")
        return data
    
    def test_replay_window_structure(self, auth_headers):
        """Replay window has start/end timestamps and minute values."""
        response = requests.get(
            f"{BASE_URL}/api/operator/incidents/{TEST_INCIDENT_ID}/replay",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        replay_window = data.get("replay_window", {})
        required_window_fields = ["start", "end", "before_minutes", "after_minutes"]
        for field in required_window_fields:
            assert field in replay_window, f"Missing replay_window field: {field}"
        
        # For SOS alert, window should be 10min before + 5min after
        assert replay_window["before_minutes"] == 10, f"Expected 10 minutes before for SOS, got {replay_window['before_minutes']}"
        assert replay_window["after_minutes"] == 5, f"Expected 5 minutes after for SOS, got {replay_window['after_minutes']}"
        
        print(f"PASS: Replay window structure correct - {replay_window['before_minutes']}m before, {replay_window['after_minutes']}m after")
        print(f"      Window: {replay_window['start']} to {replay_window['end']}")
    
    def test_replay_frames_structure(self, auth_headers):
        """Replay frames have required fields: timestamp, location, speed, battery, anomaly_score, events."""
        response = requests.get(
            f"{BASE_URL}/api/operator/incidents/{TEST_INCIDENT_ID}/replay",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        frames = data.get("frames", [])
        assert len(frames) > 0, "Expected at least one frame"
        
        # Check first frame structure
        frame = frames[0]
        required_frame_fields = ["timestamp", "elapsed_s", "location", "speed", "anomaly_score", "events"]
        for field in required_frame_fields:
            assert field in frame, f"Missing frame field: {field}"
        
        # Check location structure
        location = frame.get("location", {})
        assert "lat" in location, "Frame location missing 'lat'"
        assert "lng" in location, "Frame location missing 'lng'"
        
        # Events should be a list
        assert isinstance(frame.get("events"), list), "Frame events should be a list"
        
        print(f"PASS: Frames structure correct - {len(frames)} frames generated")
        print(f"      First frame: {frame['timestamp']}, location: ({location.get('lat')}, {location.get('lng')})")
    
    def test_replay_events_structure(self, auth_headers):
        """Timeline events have required fields: time, type, label, severity, icon."""
        response = requests.get(
            f"{BASE_URL}/api/operator/incidents/{TEST_INCIDENT_ID}/replay",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        events = data.get("events", [])
        # Events might be empty if no significant activity in window
        if len(events) > 0:
            event = events[0]
            required_event_fields = ["time", "type", "label", "severity", "icon"]
            for field in required_event_fields:
                assert field in event, f"Missing event field: {field}"
            
            print(f"PASS: Events structure correct - {len(events)} events")
            print(f"      First event: {event['type']} - {event['label']}")
        else:
            print(f"PASS: Events structure correct - 0 events (no activity in replay window)")
    
    def test_replay_stats_structure(self, auth_headers):
        """Stats includes total_frames, total_events, telemetry_points, anomalies, notifications_sent."""
        response = requests.get(
            f"{BASE_URL}/api/operator/incidents/{TEST_INCIDENT_ID}/replay",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        stats = data.get("stats", {})
        required_stats_fields = ["total_frames", "total_events", "telemetry_points", "anomalies", "notifications_sent"]
        for field in required_stats_fields:
            assert field in stats, f"Missing stats field: {field}"
        
        print(f"PASS: Stats structure correct - {stats['total_frames']} frames, {stats['telemetry_points']} telemetry points")
    
    def test_replay_ai_narrative(self, auth_headers):
        """AI narrative is generated (may be template fallback)."""
        response = requests.get(
            f"{BASE_URL}/api/operator/incidents/{TEST_INCIDENT_ID}/replay",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        narrative = data.get("ai_narrative")
        assert narrative is not None, "ai_narrative should be present"
        assert isinstance(narrative, str), "ai_narrative should be a string"
        assert len(narrative) > 10, "ai_narrative should have meaningful content"
        
        print(f"PASS: AI narrative present - {len(narrative)} chars")
        print(f"      Preview: {narrative[:100]}...")
    
    def test_replay_invalid_incident_returns_404(self, auth_headers):
        """Invalid incident_id returns 404."""
        response = requests.get(
            f"{BASE_URL}/api/operator/incidents/{INVALID_INCIDENT_ID}/replay",
            headers=auth_headers
        )
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("PASS: Invalid incident_id returns 404")


class TestIncidentTimelineEndpoint:
    """Tests for GET /api/operator/incidents/{incident_id}/timeline"""
    
    def test_timeline_requires_authentication(self):
        """Timeline endpoint requires auth."""
        response = requests.get(f"{BASE_URL}/api/operator/incidents/{TEST_INCIDENT_ID}/timeline")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("PASS: Timeline endpoint requires authentication")
    
    def test_timeline_returns_concise_data(self, auth_headers):
        """Timeline returns concise event timeline."""
        response = requests.get(
            f"{BASE_URL}/api/operator/incidents/{TEST_INCIDENT_ID}/timeline",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        
        # Verify required fields for concise timeline
        required_fields = [
            "incident_id", "device_identifier", "incident_type", 
            "severity", "incident_time", "events", "replay_window"
        ]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        
        # Verify it does NOT include bulky data like frames
        assert "frames" not in data, "Timeline should not include frames (use /replay for full data)"
        assert "location_trail" not in data, "Timeline should not include location_trail"
        
        print(f"PASS: Timeline returns concise data - {len(data.get('events', []))} events")
    
    def test_timeline_events_structure(self, auth_headers):
        """Timeline events have time, type, label, severity, icon fields."""
        response = requests.get(
            f"{BASE_URL}/api/operator/incidents/{TEST_INCIDENT_ID}/timeline",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        events = data.get("events", [])
        if len(events) > 0:
            event = events[0]
            required_fields = ["time", "type", "label", "severity", "icon"]
            for field in required_fields:
                assert field in event, f"Missing event field: {field}"
            print(f"PASS: Timeline events structure correct")
        else:
            print("PASS: Timeline events structure correct (empty events list)")
    
    def test_timeline_invalid_incident_returns_404(self, auth_headers):
        """Invalid incident_id returns 404."""
        response = requests.get(
            f"{BASE_URL}/api/operator/incidents/{INVALID_INCIDENT_ID}/timeline",
            headers=auth_headers
        )
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("PASS: Invalid incident_id returns 404")


class TestReplayWindowByIncidentType:
    """Test that different incident types have correct replay windows."""
    
    def test_sos_alert_window(self, auth_headers):
        """SOS alert should have 10min before + 5min after window."""
        response = requests.get(
            f"{BASE_URL}/api/operator/incidents/{TEST_INCIDENT_ID}/replay",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["incident_type"] == "sos_alert", f"Expected sos_alert, got {data['incident_type']}"
        window = data["replay_window"]
        assert window["before_minutes"] == 10, f"SOS should have 10min before, got {window['before_minutes']}"
        assert window["after_minutes"] == 5, f"SOS should have 5min after, got {window['after_minutes']}"
        
        print(f"PASS: SOS alert has correct window (10m before, 5m after)")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
