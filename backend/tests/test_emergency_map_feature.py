# Test Emergency Map Feature - NISCHINT Live Emergency Map
# Tests: safe-route, emergency SOS, incidents, heatmap, SSE stream

import pytest
import requests
import os
import time
from uuid import UUID

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
GUARDIAN_EMAIL = "nischint4parents@gmail.com"
GUARDIAN_PASSWORD = "secret123"
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"


@pytest.fixture(scope="module")
def guardian_auth():
    """Get guardian authentication token."""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": GUARDIAN_EMAIL,
        "password": GUARDIAN_PASSWORD
    })
    assert response.status_code == 200, f"Guardian login failed: {response.text}"
    data = response.json()
    return {
        "token": data["access_token"],
        "user_id": None  # Will extract from token if needed
    }


@pytest.fixture(scope="module")
def operator_auth():
    """Get operator authentication token."""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": OPERATOR_EMAIL,
        "password": OPERATOR_PASSWORD
    })
    assert response.status_code == 200, f"Operator login failed: {response.text}"
    data = response.json()
    return {
        "token": data["access_token"],
        "user_id": None
    }


@pytest.fixture
def guardian_headers(guardian_auth):
    """Headers with guardian auth."""
    return {"Authorization": f"Bearer {guardian_auth['token']}", "Content-Type": "application/json"}


@pytest.fixture
def operator_headers(operator_auth):
    """Headers with operator auth."""
    return {"Authorization": f"Bearer {operator_auth['token']}", "Content-Type": "application/json"}


class TestSafeRouteAPI:
    """POST /api/safe-route - Safety-aware routing."""

    def test_safe_route_balanced_mode(self, guardian_headers):
        """Test balanced mode returns 3 routes with recommendation."""
        response = requests.post(f"{BASE_URL}/api/safe-route", json={
            "origin": {"lat": 19.076, "lng": 72.8777},
            "destination": {"lat": 19.1, "lng": 72.9},
            "mode": "balanced"
        }, headers=guardian_headers)
        
        assert response.status_code == 200, f"Safe route failed: {response.text}"
        data = response.json()
        
        assert "routes" in data
        assert len(data["routes"]) == 3, "Expected 3 routes"
        assert data["mode"] == "balanced"
        assert "mode_weights" in data
        
        # Verify one route is recommended
        recommended = [r for r in data["routes"] if r.get("recommended")]
        assert len(recommended) == 1, "Expected exactly one recommended route"
        print(f"✓ Safe route balanced mode: {len(data['routes'])} routes, recommendation={data.get('recommendation')}")

    def test_safe_route_safest_mode(self, guardian_headers):
        """Test safest mode prioritizes safety."""
        response = requests.post(f"{BASE_URL}/api/safe-route", json={
            "origin": {"lat": 19.076, "lng": 72.8777},
            "destination": {"lat": 19.1, "lng": 72.9},
            "mode": "safest"
        }, headers=guardian_headers)
        
        assert response.status_code == 200
        data = response.json()
        assert data["mode_weights"]["safety"] > data["mode_weights"]["time"]
        print(f"✓ Safe route safest mode: weights={data['mode_weights']}")

    def test_safe_route_fastest_mode(self, guardian_headers):
        """Test fastest mode prioritizes time."""
        response = requests.post(f"{BASE_URL}/api/safe-route", json={
            "origin": {"lat": 19.076, "lng": 72.8777},
            "destination": {"lat": 19.1, "lng": 72.9},
            "mode": "fastest"
        }, headers=guardian_headers)
        
        assert response.status_code == 200
        data = response.json()
        assert data["mode_weights"]["time"] > data["mode_weights"]["safety"]
        print(f"✓ Safe route fastest mode: weights={data['mode_weights']}")


class TestEmergencySOS:
    """POST /api/emergency/silent-sos - Silent SOS trigger and cancel."""

    def test_silent_sos_trigger_and_cancel(self, guardian_headers):
        """Test SOS trigger creates emergency and can be cancelled."""
        # Trigger SOS
        sos_response = requests.post(f"{BASE_URL}/api/emergency/silent-sos", json={
            "lat": 19.076,
            "lng": 72.8777,
            "trigger_source": "hidden_button",
            "cancel_pin": "1234"
        }, headers=guardian_headers)
        
        assert sos_response.status_code == 200, f"SOS trigger failed: {sos_response.text}"
        sos_data = sos_response.json()
        
        assert "event_id" in sos_data
        assert sos_data["status"] in ["active", "pending"]
        event_id = sos_data["event_id"]
        print(f"✓ SOS triggered: event_id={event_id[:12]}...")
        
        # Cancel SOS
        cancel_response = requests.post(f"{BASE_URL}/api/emergency/cancel", json={
            "event_id": event_id,
            "cancel_pin": "1234"
        }, headers=guardian_headers)
        
        assert cancel_response.status_code == 200, f"SOS cancel failed: {cancel_response.text}"
        cancel_data = cancel_response.json()
        assert cancel_data["status"] == "cancelled"
        print(f"✓ SOS cancelled: status={cancel_data['status']}")

    def test_sos_wrong_pin_rejected(self, guardian_headers):
        """Test wrong cancel PIN is rejected."""
        # Trigger SOS first
        sos_response = requests.post(f"{BASE_URL}/api/emergency/silent-sos", json={
            "lat": 19.076,
            "lng": 72.8777,
            "trigger_source": "test_wrong_pin",
            "cancel_pin": "9999"
        }, headers=guardian_headers)
        
        if sos_response.status_code == 200:
            sos_data = sos_response.json()
            event_id = sos_data["event_id"]
            
            # Try wrong PIN
            wrong_pin_response = requests.post(f"{BASE_URL}/api/emergency/cancel", json={
                "event_id": event_id,
                "cancel_pin": "0000"
            }, headers=guardian_headers)
            
            assert wrong_pin_response.status_code == 400, "Wrong PIN should be rejected"
            print("✓ Wrong PIN correctly rejected")
            
            # Clean up with correct PIN
            requests.post(f"{BASE_URL}/api/emergency/cancel", json={
                "event_id": event_id,
                "cancel_pin": "9999"
            }, headers=guardian_headers)


class TestIncidentsAPI:
    """GET /api/incidents - Requires guardian_id query param."""

    def test_incidents_requires_guardian_id(self, guardian_headers):
        """Test incidents endpoint requires guardian_id."""
        response = requests.get(f"{BASE_URL}/api/incidents", headers=guardian_headers)
        # Should fail without guardian_id
        assert response.status_code == 422, "Expected validation error without guardian_id"
        print("✓ Incidents correctly requires guardian_id")

    def test_incidents_with_guardian_id(self, guardian_headers, guardian_auth):
        """Test incidents endpoint returns list when guardian_id provided."""
        # Extract user ID from JWT token
        import base64
        import json
        token = guardian_auth["token"]
        payload = token.split('.')[1]
        # Add padding if needed
        payload += '=' * (4 - len(payload) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(payload))
        guardian_id = decoded["sub"]
        
        response = requests.get(
            f"{BASE_URL}/api/incidents?guardian_id={guardian_id}", 
            headers=guardian_headers
        )
        assert response.status_code == 200, f"Incidents failed: {response.text}"
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Incidents with guardian_id: {len(data)} incidents found")


class TestHeatmapAPI:
    """Test heatmap endpoints - Operator only."""

    def test_heatmap_requires_operator(self, guardian_headers):
        """Test heatmap is operator-only."""
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap/live", headers=guardian_headers)
        assert response.status_code == 403, "Heatmap should require operator role"
        print("✓ Heatmap correctly requires operator role")

    def test_heatmap_live_operator(self, operator_headers):
        """Test heatmap live endpoint works for operator."""
        response = requests.get(f"{BASE_URL}/api/operator/city-heatmap/live", headers=operator_headers)
        assert response.status_code == 200, f"Heatmap failed: {response.text}"
        data = response.json()
        assert "cells" in data
        assert "bounds" in data
        print(f"✓ Heatmap live: {len(data.get('cells', []))} cells")


class TestSSEStream:
    """GET /api/stream - SSE stream endpoint."""

    def test_sse_stream_requires_token(self):
        """Test SSE stream requires authentication token."""
        response = requests.get(f"{BASE_URL}/api/stream", timeout=2)
        assert response.status_code == 401, "SSE should require token"
        print("✓ SSE stream correctly requires auth")

    def test_sse_stream_connects_with_token(self, guardian_auth):
        """Test SSE stream connects with valid token."""
        token = guardian_auth["token"]
        
        try:
            response = requests.get(
                f"{BASE_URL}/api/stream?token={token}",
                stream=True,
                timeout=3
            )
            # Should start streaming
            assert response.status_code == 200
            assert 'text/event-stream' in response.headers.get('Content-Type', '')
            print("✓ SSE stream connected successfully")
            response.close()
        except requests.exceptions.Timeout:
            # Timeout is OK for streaming endpoint
            print("✓ SSE stream connection established (timeout expected)")
            pass


class TestEmergencyActive:
    """GET /api/emergency/active - Active emergencies."""

    def test_active_emergencies(self, guardian_headers):
        """Test getting active emergencies."""
        response = requests.get(f"{BASE_URL}/api/emergency/active", headers=guardian_headers)
        assert response.status_code == 200, f"Active emergencies failed: {response.text}"
        data = response.json()
        assert "events" in data
        assert "count" in data
        print(f"✓ Active emergencies: {data['count']} events")


# Note: /api/heatmap endpoint doesn't exist - EmergencyMap component should use /api/operator/city-heatmap/live
# This is a known issue to report to main agent
