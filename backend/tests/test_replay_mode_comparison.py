"""
Test Historical Replay Mode for Multi-Metric Comparison Engine
Tests: POST /api/operator/simulate/compare/multi-metric with mode='replay'

Key test scenarios:
1. Replay mode validation (missing start/end times returns 422)
2. Replay mode validation (end before start returns 422)  
3. Replay mode validation (window > 7 days returns 422)
4. Successful replay with historical date range
5. Live mode backward compatibility
6. Replay metadata returned in response
"""
import pytest
import requests
import os
from datetime import datetime, timedelta

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestReplayModeComparison:
    """Tests for Historical Replay Mode in Multi-Metric Comparison"""
    
    @pytest.fixture(scope="class")
    def operator_token(self):
        """Get operator authentication token"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "operator@nischint.com", "password": "operator123"}
        )
        assert response.status_code == 200, f"Login failed: {response.text}"
        return response.json()["access_token"]
    
    @pytest.fixture(scope="class")
    def auth_headers(self, operator_token):
        """Create headers with auth token"""
        return {
            "Authorization": f"Bearer {operator_token}",
            "Content-Type": "application/json"
        }
    
    @pytest.fixture
    def default_configs(self):
        """Default config blocks for comparison"""
        return {
            "config_a": {
                "combined_anomaly": {
                    "weight_battery": 0.7,
                    "weight_signal": 0.3,
                    "trigger_threshold": 60,
                    "correlation_bonus": 10,
                    "persistence_minutes": 15
                }
            },
            "config_b": {
                "combined_anomaly": {
                    "weight_battery": 0.7,
                    "weight_signal": 0.3,
                    "trigger_threshold": 55,
                    "correlation_bonus": 10,
                    "persistence_minutes": 10
                }
            }
        }

    # ── Validation Tests ──
    
    def test_replay_mode_missing_start_time_returns_422(self, auth_headers, default_configs):
        """Replay mode without start_time should return 422"""
        payload = {
            **default_configs,
            "mode": "replay",
            "window_minutes": 1440,
            "end_time": "2026-03-04T00:00:00Z"
            # start_time missing
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
            headers=auth_headers,
            json=payload
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        assert "start_time" in response.json().get("detail", "").lower()
        print("✓ Replay mode missing start_time returns 422")
    
    def test_replay_mode_missing_end_time_returns_422(self, auth_headers, default_configs):
        """Replay mode without end_time should return 422"""
        payload = {
            **default_configs,
            "mode": "replay",
            "window_minutes": 1440,
            "start_time": "2026-03-01T00:00:00Z"
            # end_time missing
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
            headers=auth_headers,
            json=payload
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        assert "end_time" in response.json().get("detail", "").lower()
        print("✓ Replay mode missing end_time returns 422")
    
    def test_replay_mode_end_before_start_returns_422(self, auth_headers, default_configs):
        """Replay mode with end_time before start_time should return 422"""
        payload = {
            **default_configs,
            "mode": "replay",
            "window_minutes": 1440,
            "start_time": "2026-03-04T00:00:00Z",
            "end_time": "2026-03-01T00:00:00Z"  # end before start
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
            headers=auth_headers,
            json=payload
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        assert "after" in response.json().get("detail", "").lower()
        print("✓ Replay mode end before start returns 422")
    
    def test_replay_mode_window_exceeds_7_days_returns_422(self, auth_headers, default_configs):
        """Replay mode with window > 7 days should return 422"""
        payload = {
            **default_configs,
            "mode": "replay",
            "window_minutes": 10080,  # max
            "start_time": "2026-02-01T00:00:00Z",
            "end_time": "2026-02-15T00:00:00Z"  # 14 days
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
            headers=auth_headers,
            json=payload
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        assert "7 days" in response.json().get("detail", "").lower()
        print("✓ Replay mode window > 7 days returns 422")

    def test_replay_mode_future_end_time_returns_422(self, auth_headers, default_configs):
        """Replay mode with future end_time should return 422"""
        future_end = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        future_start = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        
        payload = {
            **default_configs,
            "mode": "replay",
            "window_minutes": 1440,
            "start_time": future_start,
            "end_time": future_end  # future
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
            headers=auth_headers,
            json=payload
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        assert "future" in response.json().get("detail", "").lower()
        print("✓ Replay mode future end_time returns 422")

    # ── Successful Replay Tests ──
    
    def test_replay_mode_successful_with_historical_data(self, auth_headers, default_configs):
        """Successful replay with historical date range (March 1-4)"""
        payload = {
            **default_configs,
            "mode": "replay",
            "window_minutes": 4320,  # 3 days computed from dates
            "start_time": "2026-03-01T00:00:00Z",
            "end_time": "2026-03-04T00:00:00Z"
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
            headers=auth_headers,
            json=payload
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Verify response structure
        assert data["mode"] == "replay", f"Expected mode='replay', got {data.get('mode')}"
        assert "summary" in data
        assert "delta" in data
        assert "device_changes" in data
        assert "devices_evaluated" in data
        
        # Verify replay_metadata exists
        assert "replay_metadata" in data, "replay_metadata should be present in replay mode"
        metadata = data["replay_metadata"]
        assert "window_span_minutes" in metadata
        assert "telemetry_events_analyzed" in metadata
        assert "anomaly_records_evaluated" in metadata
        assert "start_time" in metadata
        assert "end_time" in metadata
        
        print(f"✓ Replay mode successful - Devices: {data['devices_evaluated']}, "
              f"Events: {metadata['telemetry_events_analyzed']}, "
              f"Anomaly records: {metadata['anomaly_records_evaluated']}, "
              f"Window: {metadata['window_span_minutes']} min")
    
    def test_replay_metadata_has_correct_fields(self, auth_headers, default_configs):
        """Verify replay_metadata contains all required fields"""
        payload = {
            **default_configs,
            "mode": "replay",
            "window_minutes": 1440,
            "start_time": "2026-03-02T00:00:00Z",
            "end_time": "2026-03-03T00:00:00Z"
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
            headers=auth_headers,
            json=payload
        )
        assert response.status_code == 200
        
        metadata = response.json().get("replay_metadata")
        assert metadata is not None
        
        # Check all required fields
        required_fields = ["mode", "start_time", "end_time", "window_span_minutes", 
                         "telemetry_events_analyzed", "anomaly_records_evaluated"]
        for field in required_fields:
            assert field in metadata, f"Missing field: {field}"
        
        # Verify types
        assert isinstance(metadata["window_span_minutes"], (int, float))
        assert isinstance(metadata["telemetry_events_analyzed"], int)
        assert isinstance(metadata["anomaly_records_evaluated"], int)
        
        print(f"✓ Replay metadata has all required fields: {list(metadata.keys())}")

    # ── Live Mode Backward Compatibility ──
    
    def test_live_mode_still_works(self, auth_headers, default_configs):
        """Live mode should continue to work (backward compatible)"""
        payload = {
            **default_configs,
            "mode": "live",
            "window_minutes": 60
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
            headers=auth_headers,
            json=payload
        )
        assert response.status_code == 200, f"Live mode failed: {response.text}"
        
        data = response.json()
        assert data["mode"] == "live"
        assert "summary" in data
        assert "delta" in data
        
        # Live mode should NOT have replay_metadata
        assert "replay_metadata" not in data or data.get("replay_metadata") is None
        
        print(f"✓ Live mode works - Devices evaluated: {data['devices_evaluated']}")
    
    def test_default_mode_is_live(self, auth_headers, default_configs):
        """When mode is not specified, should default to 'live'"""
        payload = {
            **default_configs,
            "window_minutes": 60
            # mode not specified
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
            headers=auth_headers,
            json=payload
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["mode"] == "live", f"Expected default mode='live', got {data.get('mode')}"
        print("✓ Default mode is 'live' when not specified")

    # ── Various Window Presets ──
    
    def test_replay_15_minute_window(self, auth_headers, default_configs):
        """Test 15-minute replay window"""
        now = datetime.utcnow()
        end = now - timedelta(hours=1)  # Past time
        start = end - timedelta(minutes=15)
        
        payload = {
            **default_configs,
            "mode": "replay",
            "window_minutes": 15,
            "start_time": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_time": end.strftime("%Y-%m-%dT%H:%M:%SZ")
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
            headers=auth_headers,
            json=payload
        )
        assert response.status_code == 200, f"15min replay failed: {response.text}"
        assert response.json()["mode"] == "replay"
        print("✓ 15-minute replay window works")
    
    def test_replay_1_hour_window(self, auth_headers, default_configs):
        """Test 1-hour replay window"""
        now = datetime.utcnow()
        end = now - timedelta(hours=1)
        start = end - timedelta(hours=1)
        
        payload = {
            **default_configs,
            "mode": "replay",
            "window_minutes": 60,
            "start_time": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_time": end.strftime("%Y-%m-%dT%H:%M:%SZ")
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
            headers=auth_headers,
            json=payload
        )
        assert response.status_code == 200
        assert response.json()["mode"] == "replay"
        print("✓ 1-hour replay window works")

    def test_replay_7_day_max_window(self, auth_headers, default_configs):
        """Test 7-day (max) replay window"""
        now = datetime.utcnow()
        end = now - timedelta(hours=1)
        start = end - timedelta(days=7)  # Exactly 7 days
        
        payload = {
            **default_configs,
            "mode": "replay",
            "window_minutes": 10080,  # 7 days
            "start_time": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_time": end.strftime("%Y-%m-%dT%H:%M:%SZ")
        }
        response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
            headers=auth_headers,
            json=payload
        )
        assert response.status_code == 200, f"7-day window failed: {response.text}"
        assert response.json()["mode"] == "replay"
        print("✓ 7-day (max) replay window works")

    # ── Response Contract Consistency ──
    
    def test_replay_and_live_have_same_base_response_structure(self, auth_headers, default_configs):
        """Both modes should return the same base response fields"""
        # Run live comparison
        live_payload = {**default_configs, "mode": "live", "window_minutes": 60}
        live_response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
            headers=auth_headers,
            json=live_payload
        )
        
        # Run replay comparison
        now = datetime.utcnow()
        end = now - timedelta(hours=1)
        start = end - timedelta(hours=1)
        replay_payload = {
            **default_configs,
            "mode": "replay",
            "window_minutes": 60,
            "start_time": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_time": end.strftime("%Y-%m-%dT%H:%M:%SZ")
        }
        replay_response = requests.post(
            f"{BASE_URL}/api/operator/simulate/compare/multi-metric",
            headers=auth_headers,
            json=replay_payload
        )
        
        assert live_response.status_code == 200
        assert replay_response.status_code == 200
        
        live_data = live_response.json()
        replay_data = replay_response.json()
        
        # Both should have these common fields
        common_fields = ["mode", "window_minutes", "devices_evaluated", "summary", "delta", "device_changes"]
        for field in common_fields:
            assert field in live_data, f"Live mode missing: {field}"
            assert field in replay_data, f"Replay mode missing: {field}"
        
        # Summary structure should match
        assert "config_a" in live_data["summary"]
        assert "config_b" in live_data["summary"]
        assert "config_a" in replay_data["summary"]
        assert "config_b" in replay_data["summary"]
        
        # Only replay should have replay_metadata
        assert "replay_metadata" not in live_data or live_data.get("replay_metadata") is None
        assert "replay_metadata" in replay_data
        
        print("✓ Live and replay modes have consistent base response structure")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
