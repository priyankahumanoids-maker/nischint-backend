"""
Test GET /api/operator/replay-timeline endpoint
- Returns aggregated anomaly scores and incident events in time buckets
- Validates date range (end after start, max 7 days)
- Returns score_timeline and events arrays
"""
import pytest
import requests
import os
from datetime import datetime, timedelta

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL').rstrip('/')


class TestReplayTimelineAPI:
    """Replay Timeline endpoint tests"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get operator authentication token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "operator@nischint.com",
            "password": "operator123"
        })
        assert response.status_code == 200, f"Login failed: {response.text}"
        return response.json().get("access_token")
    
    @pytest.fixture(scope="class")
    def auth_headers(self, auth_token):
        """Auth headers for requests"""
        return {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}
    
    # ── Date Validation Tests ──
    
    def test_replay_timeline_missing_start_time_returns_422(self, auth_headers):
        """Missing start_time should return 422"""
        response = requests.get(
            f"{BASE_URL}/api/operator/replay-timeline",
            params={"end_time": "2026-03-05T00:00:00Z"},
            headers=auth_headers
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
    
    def test_replay_timeline_missing_end_time_returns_422(self, auth_headers):
        """Missing end_time should return 422"""
        response = requests.get(
            f"{BASE_URL}/api/operator/replay-timeline",
            params={"start_time": "2026-02-28T00:00:00Z"},
            headers=auth_headers
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
    
    def test_replay_timeline_end_before_start_returns_422(self, auth_headers):
        """End time before start time should return 422"""
        response = requests.get(
            f"{BASE_URL}/api/operator/replay-timeline",
            params={
                "start_time": "2026-03-05T00:00:00Z",
                "end_time": "2026-02-28T00:00:00Z"
            },
            headers=auth_headers
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        assert "end_time must be after start_time" in response.text.lower()
    
    def test_replay_timeline_exceeds_7_days_returns_422(self, auth_headers):
        """Window exceeding 7 days should return 422"""
        response = requests.get(
            f"{BASE_URL}/api/operator/replay-timeline",
            params={
                "start_time": "2026-02-01T00:00:00Z",
                "end_time": "2026-02-15T00:00:00Z"  # 14 days
            },
            headers=auth_headers
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        assert "7 days" in response.text.lower()
    
    # ── Response Structure Tests ──
    
    def test_replay_timeline_returns_correct_json_structure(self, auth_headers):
        """Response should have window, threshold, bucket_seconds, score_timeline, events"""
        response = requests.get(
            f"{BASE_URL}/api/operator/replay-timeline",
            params={
                "start_time": "2026-02-28T00:00:00Z",
                "end_time": "2026-03-05T00:00:00Z",
                "threshold": 60
            },
            headers=auth_headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        # Required top-level fields
        assert "window" in data, "Missing 'window' field"
        assert "threshold" in data, "Missing 'threshold' field"
        assert "bucket_seconds" in data, "Missing 'bucket_seconds' field"
        assert "score_timeline" in data, "Missing 'score_timeline' field"
        assert "events" in data, "Missing 'events' field"
        
        # Window subfields
        assert "start_time" in data["window"], "Missing 'window.start_time'"
        assert "end_time" in data["window"], "Missing 'window.end_time'"
        assert "span_minutes" in data["window"], "Missing 'window.span_minutes'"
        
        # Counts
        assert "total_score_points" in data, "Missing 'total_score_points'"
        assert "total_events" in data, "Missing 'total_events'"
        
        print(f"Response structure: window={data['window']}, threshold={data['threshold']}, bucket_seconds={data['bucket_seconds']}")
        print(f"Score points: {data['total_score_points']}, Events: {data['total_events']}")
    
    def test_replay_timeline_score_timeline_structure(self, auth_headers):
        """score_timeline items should have timestamp, max_combined, avg_combined, devices_above_threshold, total_devices"""
        response = requests.get(
            f"{BASE_URL}/api/operator/replay-timeline",
            params={
                "start_time": "2026-02-28T00:00:00Z",
                "end_time": "2026-03-05T00:00:00Z",
                "threshold": 60
            },
            headers=auth_headers
        )
        assert response.status_code == 200
        
        data = response.json()
        score_timeline = data.get("score_timeline", [])
        
        if len(score_timeline) > 0:
            point = score_timeline[0]
            assert "timestamp" in point, "Missing 'timestamp' in score point"
            assert "max_combined" in point, "Missing 'max_combined' in score point"
            assert "avg_combined" in point, "Missing 'avg_combined' in score point"
            assert "devices_above_threshold" in point, "Missing 'devices_above_threshold' in score point"
            assert "total_devices" in point, "Missing 'total_devices' in score point"
            
            # Validate types
            assert isinstance(point["max_combined"], (int, float))
            assert isinstance(point["avg_combined"], (int, float))
            assert isinstance(point["devices_above_threshold"], int)
            assert isinstance(point["total_devices"], int)
            
            print(f"Sample score point: {point}")
        else:
            print("No score_timeline data in this window (expected if no anomalies)")
    
    def test_replay_timeline_events_structure(self, auth_headers):
        """Events should have timestamp, event_type, device_identifier, severity"""
        response = requests.get(
            f"{BASE_URL}/api/operator/replay-timeline",
            params={
                "start_time": "2026-02-28T00:00:00Z",
                "end_time": "2026-03-05T00:00:00Z",
                "threshold": 60
            },
            headers=auth_headers
        )
        assert response.status_code == 200
        
        data = response.json()
        events = data.get("events", [])
        
        if len(events) > 0:
            event = events[0]
            assert "timestamp" in event, "Missing 'timestamp' in event"
            assert "event_type" in event, "Missing 'event_type' in event"
            assert "device_identifier" in event, "Missing 'device_identifier' in event"
            assert "severity" in event, "Missing 'severity' in event"
            
            print(f"Sample event: {event}")
            print(f"Total events in window: {len(events)}")
        else:
            print("No events in this window (expected if no incidents)")
    
    # ── Limit Tests ──
    
    def test_replay_timeline_limits_score_points_to_120(self, auth_headers):
        """score_timeline should be limited to 120 points"""
        # Use 7-day window (max) which might have many data points
        response = requests.get(
            f"{BASE_URL}/api/operator/replay-timeline",
            params={
                "start_time": "2026-02-26T00:00:00Z",
                "end_time": "2026-03-05T00:00:00Z",
                "threshold": 60
            },
            headers=auth_headers
        )
        assert response.status_code == 200
        
        data = response.json()
        score_timeline = data.get("score_timeline", [])
        total_points = data.get("total_score_points", 0)
        
        assert total_points <= 120, f"Score points exceed 120: {total_points}"
        assert len(score_timeline) <= 120, f"score_timeline array exceeds 120: {len(score_timeline)}"
        
        print(f"Score points: {total_points} (limit: 120)")
    
    def test_replay_timeline_limits_events_to_500(self, auth_headers):
        """events should be limited to 500"""
        response = requests.get(
            f"{BASE_URL}/api/operator/replay-timeline",
            params={
                "start_time": "2026-02-28T00:00:00Z",
                "end_time": "2026-03-05T00:00:00Z",
                "threshold": 60
            },
            headers=auth_headers
        )
        assert response.status_code == 200
        
        data = response.json()
        events = data.get("events", [])
        total_events = data.get("total_events", 0)
        
        assert total_events <= 500, f"Events exceed 500: {total_events}"
        assert len(events) <= 500, f"events array exceeds 500: {len(events)}"
        
        print(f"Total events: {total_events} (limit: 500)")
    
    # ── Threshold Tests ──
    
    def test_replay_timeline_default_threshold_is_60(self, auth_headers):
        """Default threshold should be 60"""
        response = requests.get(
            f"{BASE_URL}/api/operator/replay-timeline",
            params={
                "start_time": "2026-02-28T00:00:00Z",
                "end_time": "2026-03-05T00:00:00Z"
            },
            headers=auth_headers
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["threshold"] == 60, f"Expected threshold 60, got {data['threshold']}"
    
    def test_replay_timeline_custom_threshold(self, auth_headers):
        """Custom threshold should be accepted"""
        response = requests.get(
            f"{BASE_URL}/api/operator/replay-timeline",
            params={
                "start_time": "2026-02-28T00:00:00Z",
                "end_time": "2026-03-05T00:00:00Z",
                "threshold": 75
            },
            headers=auth_headers
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["threshold"] == 75, f"Expected threshold 75, got {data['threshold']}"
    
    # ── Auth Tests ──
    
    def test_replay_timeline_requires_authentication(self):
        """Endpoint requires authentication"""
        response = requests.get(
            f"{BASE_URL}/api/operator/replay-timeline",
            params={
                "start_time": "2026-02-28T00:00:00Z",
                "end_time": "2026-03-05T00:00:00Z"
            }
        )
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
    
    # ── Bucket Size Tests ──
    
    def test_replay_timeline_bucket_seconds_calculation(self, auth_headers):
        """bucket_seconds should be calculated as max(60, window_span // 120)"""
        # 5-day window = 5 * 24 * 3600 = 432000 seconds / 120 = 3600 (1 hour buckets)
        response = requests.get(
            f"{BASE_URL}/api/operator/replay-timeline",
            params={
                "start_time": "2026-02-28T00:00:00Z",
                "end_time": "2026-03-05T00:00:00Z"
            },
            headers=auth_headers
        )
        assert response.status_code == 200
        
        data = response.json()
        bucket_seconds = data["bucket_seconds"]
        
        # 5 days = 5 * 24 * 3600 = 432000 seconds
        # Expected bucket = max(60, 432000 // 120) = max(60, 3600) = 3600
        expected = max(60, 432000 // 120)
        assert bucket_seconds == expected, f"Expected bucket_seconds {expected}, got {bucket_seconds}"
        
        print(f"Bucket seconds: {bucket_seconds} (expected {expected})")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
