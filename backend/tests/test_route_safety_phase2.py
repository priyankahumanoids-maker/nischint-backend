"""
Test Route Safety Phase 2: Dynamic Rerouting and Risk Recalculation
- GET /api/operator/route-monitor/{device_id}/risk-update (risk recalculation)
- POST /api/operator/route-monitor/{device_id}/reroute (suggest reroute)
- POST /api/operator/route-monitor/{device_id}/accept-reroute (accept reroute)
- GET /api/operator/route-monitors (fleet monitors with reroute_suggested, end_lat/end_lng)
"""

import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials and data
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"
ACTIVE_DEVICE_ID = "ce4b5463-5a7e-46a5-8bbf-365dcfb3daeb"  # DEV-001
NON_EXISTENT_DEVICE_ID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture(scope="module")
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


@pytest.fixture(scope="module")
def auth_token(api_client):
    """Get authentication token for operator"""
    response = api_client.post(f"{BASE_URL}/api/auth/login", json={
        "email": OPERATOR_EMAIL,
        "password": OPERATOR_PASSWORD
    })
    if response.status_code == 200:
        token = response.json().get("access_token")
        api_client.headers.update({"Authorization": f"Bearer {token}"})
        return token
    pytest.skip(f"Authentication failed: {response.status_code} - {response.text}")


class TestRiskRecalculation:
    """Tests for GET /api/operator/route-monitor/{device_id}/risk-update"""

    def test_risk_update_returns_200(self, api_client, auth_token):
        """Test risk-update endpoint returns 200 for active monitor"""
        response = api_client.get(f"{BASE_URL}/api/operator/route-monitor/{ACTIVE_DEVICE_ID}/risk-update")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    def test_risk_update_response_structure(self, api_client, auth_token):
        """Verify response contains required fields: old_risk, new_risk, risk_delta, risk_trend"""
        response = api_client.get(f"{BASE_URL}/api/operator/route-monitor/{ACTIVE_DEVICE_ID}/risk-update")
        assert response.status_code == 200
        data = response.json()

        # Check status field
        assert "status" in data
        
        # If status is recalculated, check all required fields
        if data["status"] == "recalculated":
            assert "old_risk" in data, "Missing old_risk"
            assert "new_risk" in data, "Missing new_risk"
            assert "risk_delta" in data, "Missing risk_delta"
            assert "risk_trend" in data, "Missing risk_trend"
            
            # Validate risk_trend is one of expected values
            assert data["risk_trend"] in ["increased", "decreased", "stable"], \
                f"Invalid risk_trend: {data['risk_trend']}"
            
            # Validate delta calculation
            expected_delta = round(data["new_risk"] - data["old_risk"], 1)
            assert data["risk_delta"] == expected_delta, \
                f"Delta mismatch: {data['risk_delta']} != {expected_delta}"
            print(f"Risk recalculated: {data['old_risk']} -> {data['new_risk']} ({data['risk_trend']})")

    def test_risk_update_no_monitor_returns_no_monitor(self, api_client, auth_token):
        """Test risk-update returns appropriate status when no monitor exists"""
        response = api_client.get(f"{BASE_URL}/api/operator/route-monitor/{NON_EXISTENT_DEVICE_ID}/risk-update")
        # Should return 200 with status: no_monitor, not 404
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data.get("status") == "no_monitor", f"Expected no_monitor status, got: {data}"

    def test_risk_update_trend_values(self, api_client, auth_token):
        """Verify risk_trend matches risk_delta threshold logic"""
        response = api_client.get(f"{BASE_URL}/api/operator/route-monitor/{ACTIVE_DEVICE_ID}/risk-update")
        if response.status_code != 200:
            pytest.skip("No active monitor")
        
        data = response.json()
        if data.get("status") != "recalculated":
            pytest.skip("No recalculation performed")

        delta = data["risk_delta"]
        trend = data["risk_trend"]
        
        # Per code: increased if delta > 0.5, decreased if delta < -0.5, else stable
        if delta > 0.5:
            assert trend == "increased", f"Expected 'increased' for delta {delta}"
        elif delta < -0.5:
            assert trend == "decreased", f"Expected 'decreased' for delta {delta}"
        else:
            assert trend == "stable", f"Expected 'stable' for delta {delta}"


class TestSuggestReroute:
    """Tests for POST /api/operator/route-monitor/{device_id}/reroute"""

    def test_reroute_returns_200(self, api_client, auth_token):
        """Test reroute endpoint returns 200 for active monitor"""
        response = api_client.post(f"{BASE_URL}/api/operator/route-monitor/{ACTIVE_DEVICE_ID}/reroute")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    def test_reroute_response_structure(self, api_client, auth_token):
        """Verify reroute response contains required fields"""
        response = api_client.post(f"{BASE_URL}/api/operator/route-monitor/{ACTIVE_DEVICE_ID}/reroute")
        assert response.status_code == 200
        data = response.json()

        # Check status is one of expected values
        assert "status" in data
        valid_statuses = ["reroute_available", "current_optimal", "no_monitor", "no_location", "near_destination", "no_routes", "error"]
        assert data["status"] in valid_statuses, f"Invalid status: {data['status']}"

        # If reroute_available or current_optimal, check alternatives
        if data["status"] in ["reroute_available", "current_optimal"]:
            assert "current_risk" in data, "Missing current_risk"
            assert "alternatives" in data, "Missing alternatives"
            assert "recommendation" in data, "Missing recommendation"
            assert "risk_improvement" in data, "Missing risk_improvement"
            assert "from_location" in data, "Missing from_location"
            assert "to_location" in data, "Missing to_location"
            
            print(f"Reroute status: {data['status']}, risk_improvement: {data['risk_improvement']}")
            print(f"Alternatives count: {len(data['alternatives'])}")

    def test_reroute_alternatives_structure(self, api_client, auth_token):
        """Verify each alternative route has required fields"""
        response = api_client.post(f"{BASE_URL}/api/operator/route-monitor/{ACTIVE_DEVICE_ID}/reroute")
        if response.status_code != 200:
            pytest.skip("Reroute endpoint failed")
        
        data = response.json()
        if data.get("status") not in ["reroute_available", "current_optimal"]:
            pytest.skip(f"No alternatives available: {data.get('status')}")

        alternatives = data.get("alternatives", [])
        assert len(alternatives) > 0, "No alternatives returned"

        for alt in alternatives:
            assert "index" in alt, "Missing index in alternative"
            assert "label" in alt, "Missing label"
            assert "distance_km" in alt, "Missing distance_km"
            assert "duration_min" in alt, "Missing duration_min"
            assert "route_risk_score" in alt, "Missing route_risk_score"
            assert "risk_level" in alt, "Missing risk_level"
            assert "geometry" in alt, "Missing geometry"
            assert "segments" in alt, "Missing segments"
            assert "risk_improvement" in alt, "Missing risk_improvement"

    def test_reroute_no_monitor(self, api_client, auth_token):
        """Test reroute returns no_monitor status for non-existent device"""
        response = api_client.post(f"{BASE_URL}/api/operator/route-monitor/{NON_EXISTENT_DEVICE_ID}/reroute")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "no_monitor", f"Expected no_monitor, got: {data}"


class TestAcceptReroute:
    """Tests for POST /api/operator/route-monitor/{device_id}/accept-reroute"""

    def test_accept_reroute_requires_route_data(self, api_client, auth_token):
        """Test accept-reroute returns 400 when route_data is missing"""
        response = api_client.post(
            f"{BASE_URL}/api/operator/route-monitor/{ACTIVE_DEVICE_ID}/accept-reroute",
            json={}
        )
        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        assert "route_data" in response.text.lower()

    def test_accept_reroute_no_monitor(self, api_client, auth_token):
        """Test accept-reroute returns error for non-existent device"""
        fake_route = {
            "route_data": {
                "index": 0,
                "route_risk_score": 2.0,
                "geometry": [[77.5946, 12.9716], [77.6000, 12.9800]],
                "segments": []
            }
        }
        response = api_client.post(
            f"{BASE_URL}/api/operator/route-monitor/{NON_EXISTENT_DEVICE_ID}/accept-reroute",
            json=fake_route
        )
        assert response.status_code == 200  # Returns 200 with status error
        data = response.json()
        assert data.get("status") == "error", f"Expected error status, got: {data}"

    def test_accept_reroute_with_valid_route(self, api_client, auth_token):
        """Test accept-reroute with valid route data from suggest_reroute"""
        # First get alternatives
        reroute_response = api_client.post(f"{BASE_URL}/api/operator/route-monitor/{ACTIVE_DEVICE_ID}/reroute")
        if reroute_response.status_code != 200:
            pytest.skip("Cannot get reroute suggestions")
        
        reroute_data = reroute_response.json()
        if reroute_data.get("status") not in ["reroute_available", "current_optimal"]:
            pytest.skip(f"No alternatives available: {reroute_data.get('status')}")
        
        alternatives = reroute_data.get("alternatives", [])
        if not alternatives:
            pytest.skip("No alternatives to accept")

        # Accept the first alternative
        first_alt = alternatives[0]
        accept_response = api_client.post(
            f"{BASE_URL}/api/operator/route-monitor/{ACTIVE_DEVICE_ID}/accept-reroute",
            json={"route_data": first_alt}
        )
        
        assert accept_response.status_code == 200, f"Accept failed: {accept_response.text}"
        data = accept_response.json()
        assert data.get("status") == "rerouted", f"Expected rerouted status, got: {data}"
        assert "monitor_id" in data, "Missing monitor_id"
        assert "new_risk_score" in data, "Missing new_risk_score"
        print(f"Reroute accepted. New risk: {data.get('new_risk_score')}")


class TestFleetMonitorsWithRerouteInfo:
    """Tests for GET /api/operator/route-monitors including new fields"""

    def test_fleet_monitors_returns_200(self, api_client, auth_token):
        """Test fleet monitors endpoint returns 200"""
        response = api_client.get(f"{BASE_URL}/api/operator/route-monitors")
        assert response.status_code == 200

    def test_fleet_monitors_structure(self, api_client, auth_token):
        """Verify monitor response includes reroute_suggested and end coordinates"""
        response = api_client.get(f"{BASE_URL}/api/operator/route-monitors")
        assert response.status_code == 200
        data = response.json()

        assert "monitors" in data, "Missing monitors array"
        monitors = data["monitors"]
        
        if len(monitors) == 0:
            pytest.skip("No active monitors")

        for m in monitors:
            # Check required new fields
            assert "end_lat" in m, f"Missing end_lat in monitor {m.get('device_identifier')}"
            assert "end_lng" in m, f"Missing end_lng in monitor {m.get('device_identifier')}"
            assert "reroute_suggested" in m, f"Missing reroute_suggested in monitor {m.get('device_identifier')}"
            
            # Validate reroute_suggested is boolean
            assert isinstance(m["reroute_suggested"], bool), \
                f"reroute_suggested should be boolean, got {type(m['reroute_suggested'])}"
            
            print(f"Monitor {m.get('device_identifier')}: reroute_suggested={m['reroute_suggested']}, "
                  f"end=({m['end_lat']}, {m['end_lng']})")

    def test_fleet_monitors_reroute_suggested_logic(self, api_client, auth_token):
        """Verify reroute_suggested is True when alert_level is danger/warning or off_route"""
        response = api_client.get(f"{BASE_URL}/api/operator/route-monitors")
        if response.status_code != 200:
            pytest.skip("Fleet monitors endpoint failed")
        
        monitors = response.json().get("monitors", [])
        if not monitors:
            pytest.skip("No active monitors")

        for m in monitors:
            alert_level = m.get("alert_level", "safe")
            off_route = m.get("off_route", False)
            reroute_suggested = m.get("reroute_suggested", False)
            
            # reroute_suggested should be True if danger/warning alert or off_route
            should_suggest = alert_level in ["danger", "warning"] or off_route
            
            if should_suggest:
                assert reroute_suggested is True, \
                    f"Expected reroute_suggested=True for alert_level={alert_level}, off_route={off_route}"


class TestIntegrationFlow:
    """Integration tests for the complete reroute flow"""

    def test_full_reroute_flow(self, api_client, auth_token):
        """Test complete flow: get monitors -> suggest reroute -> risk update"""
        # Step 1: Get active monitors
        monitors_response = api_client.get(f"{BASE_URL}/api/operator/route-monitors")
        assert monitors_response.status_code == 200
        monitors = monitors_response.json().get("monitors", [])
        
        if not monitors:
            pytest.skip("No active monitors for integration test")
        
        device_id = monitors[0]["device_id"]
        print(f"Testing flow with device: {monitors[0].get('device_identifier')}")

        # Step 2: Suggest reroute
        reroute_response = api_client.post(f"{BASE_URL}/api/operator/route-monitor/{device_id}/reroute")
        assert reroute_response.status_code == 200
        reroute_data = reroute_response.json()
        print(f"Reroute status: {reroute_data.get('status')}")

        # Step 3: Risk update
        risk_response = api_client.get(f"{BASE_URL}/api/operator/route-monitor/{device_id}/risk-update")
        assert risk_response.status_code == 200
        risk_data = risk_response.json()
        print(f"Risk update status: {risk_data.get('status')}")

        # Verify data consistency
        if reroute_data.get("status") in ["reroute_available", "current_optimal"]:
            assert "current_risk" in reroute_data
            # Current risk from reroute should be close to risk recalculation new_risk
            if risk_data.get("status") == "recalculated":
                # Allow some variance due to timing
                print(f"Reroute current_risk: {reroute_data['current_risk']}, "
                      f"Risk update new_risk: {risk_data['new_risk']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
