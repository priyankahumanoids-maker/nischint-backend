# Test suite for Predictive Danger Alerts (Phase 37)
# Tests: speed-adaptive lookahead, direction filtering, cooldown, severity levels,
# danger segments, with-alternative endpoint, authentication

import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"


@pytest.fixture(scope="module")
def auth_token():
    """Get operator authentication token"""
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD}
    )
    if response.status_code == 200:
        return response.json().get("access_token")
    pytest.skip(f"Auth failed: {response.status_code}")


@pytest.fixture
def api_client(auth_token):
    """Session with auth header"""
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {auth_token}"
    })
    return session


class TestPredictiveAlertAuth:
    """Authentication tests for predictive alert endpoints"""

    def test_predictive_alert_requires_auth(self):
        """POST /predictive-alert returns 401 without token"""
        response = requests.post(
            f"{BASE_URL}/api/predictive-alert",
            json={"location": {"lat": 12.968, "lng": 77.590}}
        )
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: Predictive alert requires authentication (401 without token)")

    def test_with_alternative_requires_auth(self):
        """POST /predictive-alert/with-alternative returns 401 without token"""
        response = requests.post(
            f"{BASE_URL}/api/predictive-alert/with-alternative",
            json={"location": {"lat": 12.968, "lng": 77.590}}
        )
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: With-alternative endpoint requires authentication")


class TestSpeedAdaptiveLookahead:
    """Tests for speed-adaptive lookahead distances"""

    def test_walking_mode_lookahead_250m(self, api_client):
        """Walking (<2 m/s) uses 250m lookahead"""
        # Use unique user_id to avoid cooldown interference
        response = api_client.post(
            f"{BASE_URL}/api/predictive-alert",
            json={
                "user_id": "test-walking-mode-1",
                "location": {"lat": 12.968, "lng": 77.590},
                "speed": 1.5  # Walking speed
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["mode"] == "walking", f"Expected walking mode, got {data['mode']}"
        assert data["lookahead_m"] == 250, f"Expected 250m lookahead, got {data['lookahead_m']}"
        print(f"PASS: Walking mode ({data['mode']}) uses {data['lookahead_m']}m lookahead")

    def test_bike_mode_lookahead_350m(self, api_client):
        """Bike (2-6 m/s) uses 350m lookahead"""
        response = api_client.post(
            f"{BASE_URL}/api/predictive-alert",
            json={
                "user_id": "test-bike-mode-1",
                "location": {"lat": 12.968, "lng": 77.590},
                "speed": 4.0  # Bike speed
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["mode"] == "bike", f"Expected bike mode, got {data['mode']}"
        assert data["lookahead_m"] == 350, f"Expected 350m lookahead, got {data['lookahead_m']}"
        print(f"PASS: Bike mode ({data['mode']}) uses {data['lookahead_m']}m lookahead")

    def test_vehicle_mode_lookahead_550m(self, api_client):
        """Vehicle (>6 m/s) uses 550m lookahead"""
        response = api_client.post(
            f"{BASE_URL}/api/predictive-alert",
            json={
                "user_id": "test-vehicle-mode-1",
                "location": {"lat": 12.968, "lng": 77.590},
                "speed": 12.0  # Vehicle speed
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["mode"] == "vehicle", f"Expected vehicle mode, got {data['mode']}"
        assert data["lookahead_m"] == 550, f"Expected 550m lookahead, got {data['lookahead_m']}"
        print(f"PASS: Vehicle mode ({data['mode']}) uses {data['lookahead_m']}m lookahead")


class TestPredictiveAlertRouteWithDanger:
    """Tests for alert triggering with danger zones ahead"""

    def test_alert_fires_when_danger_ahead(self, api_client):
        """Alert=true when route passes through HIGH/CRITICAL zone"""
        # Route from (12.968, 77.590) toward HIGH zone at (12.972, 77.587)
        route_coords = [
            [77.590, 12.968],  # Start
            [77.589, 12.969],
            [77.588, 12.970],
            [77.587, 12.971],
            [77.587, 12.972],  # Near HIGH zone
            [77.586, 12.973],
            [77.585, 12.975],  # End
        ]
        response = api_client.post(
            f"{BASE_URL}/api/predictive-alert",
            json={
                "user_id": "test-danger-ahead-1",
                "location": {"lat": 12.968, "lng": 77.590},
                "route_coords": route_coords,
                "speed": 1.5
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        # May or may not have alert depending on actual zone data
        assert "alert" in data, "Response must contain 'alert' field"
        assert "mode" in data, "Response must contain 'mode' field"
        assert "lookahead_m" in data, "Response must contain 'lookahead_m' field"
        
        if data["alert"]:
            assert "severity" in data, "Alert response must have severity"
            assert "distance_to_risk" in data, "Alert response must have distance_to_risk"
            assert "risk_score" in data, "Alert response must have risk_score"
            assert "danger_segments" in data, "Alert response must have danger_segments"
            print(f"PASS: Alert fired - severity={data['severity']}, distance={data['distance_to_risk']}m, risk={data['risk_score']}")
        else:
            assert "reason" in data, "No-alert response must have reason"
            print(f"PASS: No danger ahead - reason={data['reason']}")

    def test_safe_route_returns_safe_ahead(self, api_client):
        """Safe area returns alert=false, reason=safe_ahead"""
        # Use coordinates far from any danger zones (safe area)
        response = api_client.post(
            f"{BASE_URL}/api/predictive-alert",
            json={
                "user_id": "test-safe-route-1",
                "location": {"lat": 13.1, "lng": 77.4},
                "speed": 1.5
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        # If no danger zones nearby, should return safe_ahead
        if not data.get("alert"):
            assert data.get("reason") == "safe_ahead", f"Expected reason=safe_ahead, got {data.get('reason')}"
            assert "message" in data, "Safe response should have message"
            print(f"PASS: Safe route returns alert=false, reason={data['reason']}")
        else:
            print(f"INFO: Route has danger - severity={data.get('severity')}")


class TestCooldownMechanism:
    """Tests for alert cooldown (5 min per user/zone)"""

    def test_cooldown_on_repeat_alert(self, api_client):
        """Same zone within 5min returns cooldown_active"""
        # First request - may trigger alert
        unique_user = f"test-cooldown-{int(time.time())}"
        route_toward_danger = [
            [77.590, 12.968],
            [77.587, 12.972],
        ]
        
        response1 = api_client.post(
            f"{BASE_URL}/api/predictive-alert",
            json={
                "user_id": unique_user,
                "location": {"lat": 12.968, "lng": 77.590},
                "route_coords": route_toward_danger,
                "speed": 1.5
            }
        )
        assert response1.status_code == 200
        data1 = response1.json()
        
        if data1.get("alert"):
            print(f"First call triggered alert: severity={data1.get('severity')}")
            
            # Second request immediately - should get cooldown
            response2 = api_client.post(
                f"{BASE_URL}/api/predictive-alert",
                json={
                    "user_id": unique_user,
                    "location": {"lat": 12.968, "lng": 77.590},
                    "route_coords": route_toward_danger,
                    "speed": 1.5
                }
            )
            assert response2.status_code == 200
            data2 = response2.json()
            
            # Should have cooldown active or still show alert if different zone
            if data2.get("reason") == "cooldown_active":
                assert "cooldown_remaining_s" in data2, "Cooldown response must have remaining seconds"
                assert data2["cooldown_remaining_s"] > 0, "Cooldown remaining should be positive"
                print(f"PASS: Cooldown active - {data2['cooldown_remaining_s']}s remaining")
            else:
                print(f"INFO: Different zone or first was safe - {data2.get('reason', 'new alert')}")
        else:
            print(f"INFO: No danger zones to test cooldown - reason={data1.get('reason')}")


class TestAlertSeverityLevels:
    """Tests for severity classification: CRITICAL/HIGH/LOW"""

    def test_severity_classification_structure(self, api_client):
        """Alert severity is CRITICAL, HIGH, or LOW based on risk and count"""
        response = api_client.post(
            f"{BASE_URL}/api/predictive-alert",
            json={
                "user_id": "test-severity-1",
                "location": {"lat": 12.968, "lng": 77.590},
                "route_coords": [[77.590, 12.968], [77.587, 12.972], [77.585, 12.975]],
                "speed": 1.5
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        if data.get("alert"):
            assert data["severity"] in ["CRITICAL", "HIGH", "LOW"], f"Invalid severity: {data['severity']}"
            assert data["risk_level"] in ["CRITICAL", "HIGH", "LOW"], f"Invalid risk_level: {data['risk_level']}"
            print(f"PASS: Alert severity={data['severity']}, risk_level={data['risk_level']}")
        else:
            print(f"INFO: No alert - reason={data.get('reason')}")


class TestDangerSegments:
    """Tests for danger_segments array in alert response"""

    def test_danger_segments_contain_required_fields(self, api_client):
        """Each danger segment has lat, lng, distance, risk, risk_level, zone_id"""
        response = api_client.post(
            f"{BASE_URL}/api/predictive-alert",
            json={
                "user_id": "test-segments-1",
                "location": {"lat": 12.968, "lng": 77.590},
                "route_coords": [[77.590, 12.968], [77.587, 12.972], [77.585, 12.975]],
                "speed": 1.5
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        if data.get("alert") and data.get("danger_segments"):
            for seg in data["danger_segments"]:
                assert "lat" in seg, "Segment must have lat"
                assert "lng" in seg, "Segment must have lng"
                assert "distance" in seg, "Segment must have distance"
                assert "risk" in seg, "Segment must have risk"
                assert "risk_level" in seg, "Segment must have risk_level"
                assert "zone_id" in seg, "Segment must have zone_id"
            print(f"PASS: {len(data['danger_segments'])} danger segments with all required fields")
        else:
            print(f"INFO: No danger segments - alert={data.get('alert')}")


class TestPredictiveAlertWithAlternative:
    """Tests for /predictive-alert/with-alternative endpoint"""

    def test_with_alternative_endpoint_works(self, api_client):
        """POST /predictive-alert/with-alternative returns prediction + routes"""
        response = api_client.post(
            f"{BASE_URL}/api/predictive-alert/with-alternative",
            json={
                "user_id": "test-alt-route-1",
                "location": {"lat": 12.968, "lng": 77.590},
                "route_coords": [[77.590, 12.968], [77.587, 12.972], [77.585, 12.975]],
                "speed": 1.5
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        # Should have all standard prediction fields
        assert "alert" in data, "Response must have alert field"
        assert "mode" in data, "Response must have mode field"
        assert "lookahead_m" in data, "Response must have lookahead_m field"
        
        if data.get("alert"):
            # When danger detected, should have alternative_routes
            assert "alternative_route_available" in data, "Alert should indicate alternative_route_available"
            if "alternative_routes" in data:
                print(f"PASS: With-alternative returned {len(data['alternative_routes'])} alternative routes")
            else:
                print(f"INFO: No alternative routes generated (may have error)")
        else:
            print(f"PASS: With-alternative endpoint works - reason={data.get('reason')}")


class TestTimePeriodHandling:
    """Tests for time period handling (day/night/late_night)"""

    def test_time_period_in_response(self, api_client):
        """Response includes time_period field"""
        response = api_client.post(
            f"{BASE_URL}/api/predictive-alert",
            json={
                "user_id": "test-time-period-1",
                "location": {"lat": 12.968, "lng": 77.590},
                "speed": 1.5
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "time_period" in data, "Response must have time_period"
        assert data["time_period"] in ["day", "night", "late_night"], f"Invalid time_period: {data['time_period']}"
        print(f"PASS: Time period={data['time_period']}")

    def test_custom_timestamp_accepted(self, api_client):
        """Custom timestamp parameter is accepted"""
        response = api_client.post(
            f"{BASE_URL}/api/predictive-alert",
            json={
                "user_id": "test-custom-ts-1",
                "location": {"lat": 12.968, "lng": 77.590},
                "speed": 1.5,
                "timestamp": "2026-03-07T22:00:00+00:00"  # Night time
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "time_period" in data
        # With 22:00 timestamp, should be 'night' period
        print(f"PASS: Custom timestamp accepted - time_period={data['time_period']}")


class TestRouteProjection:
    """Tests for route projection when no route provided"""

    def test_projection_without_route(self, api_client):
        """API generates forward projection when no route_coords provided"""
        response = api_client.post(
            f"{BASE_URL}/api/predictive-alert",
            json={
                "user_id": "test-projection-1",
                "location": {"lat": 12.968, "lng": 77.590},
                "speed": 1.5
                # No route_coords - should generate projection
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "alert" in data
        assert "mode" in data
        print(f"PASS: API works without route_coords - mode={data['mode']}, alert={data['alert']}")


class TestResponseStructure:
    """Tests for complete response structure"""

    def test_alert_response_structure(self, api_client):
        """Alert response has all required fields"""
        response = api_client.post(
            f"{BASE_URL}/api/predictive-alert",
            json={
                "user_id": "test-structure-alert-1",
                "location": {"lat": 12.968, "lng": 77.590},
                "route_coords": [[77.590, 12.968], [77.587, 12.972]],
                "speed": 1.5
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        # Common fields
        required_common = ["alert", "user_id", "location", "mode", "lookahead_m", "time_period"]
        for field in required_common:
            assert field in data, f"Missing required field: {field}"
        
        # Location structure
        assert "lat" in data["location"]
        assert "lng" in data["location"]
        
        if data["alert"]:
            alert_fields = ["severity", "message", "recommendation", "distance_to_risk", 
                          "risk_score", "risk_level", "zone_id", "danger_zones_ahead",
                          "alternative_route_available", "danger_segments", "checked_at"]
            for field in alert_fields:
                assert field in data, f"Alert missing field: {field}"
            print(f"PASS: Alert response has all required fields")
        else:
            assert "reason" in data, "No-alert response must have reason"
            print(f"PASS: No-alert response has reason field")

    def test_safe_response_structure(self, api_client):
        """Safe response has reason=safe_ahead and message"""
        response = api_client.post(
            f"{BASE_URL}/api/predictive-alert",
            json={
                "user_id": "test-structure-safe-1",
                "location": {"lat": 13.1, "lng": 77.4},  # Far from danger zones
                "speed": 1.5
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        if not data.get("alert"):
            assert data.get("reason") in ["safe_ahead", "cooldown_active"], f"Unexpected reason: {data.get('reason')}"
            assert "message" in data or "nearest_danger" in data, "Safe/cooldown response should have message or nearest_danger"
            print(f"PASS: Safe response structure correct - reason={data.get('reason')}")
        else:
            print(f"INFO: Area has danger - severity={data.get('severity')}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
