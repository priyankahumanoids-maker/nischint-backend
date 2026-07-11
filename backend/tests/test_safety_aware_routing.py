# Safety-Aware Routing Tests
# POST /api/safe-route - generates routes with per-segment risk scoring
# Modes: fastest, safest, balanced, night_guardian
# Night Guardian: 80% safety / 20% time weighting
# Segment Score = 50% live_risk + 30% forecast_risk + 20% environmental

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL')

# Test credentials
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASS = "operator123"
GUARDIAN_EMAIL = "nischint4parents@gmail.com"
GUARDIAN_PASS = "secret123"

# Mumbai test coordinates
MUMBAI_CST = {"lat": 18.9398, "lng": 72.8354}
MUMBAI_BANDRA = {"lat": 19.0544, "lng": 72.8403}


@pytest.fixture(scope="module")
def operator_token():
    """Get operator auth token"""
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": OPERATOR_EMAIL,
        "password": OPERATOR_PASS
    })
    assert resp.status_code == 200, f"Operator login failed: {resp.text}"
    return resp.json().get("access_token")


@pytest.fixture(scope="module")
def guardian_token():
    """Get guardian auth token"""
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": GUARDIAN_EMAIL,
        "password": GUARDIAN_PASS
    })
    assert resp.status_code == 200, f"Guardian login failed: {resp.text}"
    return resp.json().get("access_token")


class TestBalancedMode:
    """Test balanced mode returns 3 routes with recommendation"""

    def test_balanced_mode_returns_3_routes(self, operator_token):
        """POST /api/safe-route balanced mode returns 3 routes"""
        resp = requests.post(
            f"{BASE_URL}/api/safe-route",
            json={"origin": MUMBAI_CST, "destination": MUMBAI_BANDRA, "mode": "balanced"},
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data.get("routes", [])) == 3
        route_types = {r["type"] for r in data["routes"]}
        assert route_types == {"fastest", "safest", "balanced"}

    def test_balanced_mode_has_recommendation(self, operator_token):
        """Balanced mode sets recommendation field"""
        resp = requests.post(
            f"{BASE_URL}/api/safe-route",
            json={"origin": MUMBAI_CST, "destination": MUMBAI_BANDRA, "mode": "balanced"},
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        data = resp.json()
        assert "recommendation" in data
        assert data["recommendation"] == "balanced"

    def test_balanced_mode_weights(self, operator_token):
        """Balanced mode has 50/50 time/safety weights"""
        resp = requests.post(
            f"{BASE_URL}/api/safe-route",
            json={"origin": MUMBAI_CST, "destination": MUMBAI_BANDRA, "mode": "balanced"},
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        data = resp.json()
        assert data.get("mode_weights") == {"time": 0.5, "safety": 0.5}


class TestSafestMode:
    """Test safest mode recommends safest route (lowest risk)"""

    def test_safest_mode_recommends_safest(self, operator_token):
        """Safest mode recommends safest route"""
        resp = requests.post(
            f"{BASE_URL}/api/safe-route",
            json={"origin": MUMBAI_CST, "destination": MUMBAI_BANDRA, "mode": "safest"},
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        data = resp.json()
        assert data.get("recommendation") == "safest"
        # First route should be recommended and type=safest
        recommended_route = next((r for r in data["routes"] if r.get("recommended")), None)
        assert recommended_route is not None
        assert recommended_route["type"] == "safest"

    def test_safest_mode_weights(self, operator_token):
        """Safest mode has 20/80 time/safety weights"""
        resp = requests.post(
            f"{BASE_URL}/api/safe-route",
            json={"origin": MUMBAI_CST, "destination": MUMBAI_BANDRA, "mode": "safest"},
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        data = resp.json()
        assert data.get("mode_weights") == {"time": 0.2, "safety": 0.8}


class TestFastestMode:
    """Test fastest mode recommends fastest route (lowest time)"""

    def test_fastest_mode_recommends_fastest(self, operator_token):
        """Fastest mode recommends fastest route"""
        resp = requests.post(
            f"{BASE_URL}/api/safe-route",
            json={"origin": MUMBAI_CST, "destination": MUMBAI_BANDRA, "mode": "fastest"},
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        data = resp.json()
        assert data.get("recommendation") == "fastest"
        recommended_route = next((r for r in data["routes"] if r.get("recommended")), None)
        assert recommended_route is not None
        assert recommended_route["type"] == "fastest"

    def test_fastest_mode_weights(self, operator_token):
        """Fastest mode has 80/20 time/safety weights"""
        resp = requests.post(
            f"{BASE_URL}/api/safe-route",
            json={"origin": MUMBAI_CST, "destination": MUMBAI_BANDRA, "mode": "fastest"},
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        data = resp.json()
        assert data.get("mode_weights") == {"time": 0.8, "safety": 0.2}

    def test_fastest_route_has_lowest_time(self, operator_token):
        """Fastest route has lowest or equal time compared to others"""
        resp = requests.post(
            f"{BASE_URL}/api/safe-route",
            json={"origin": MUMBAI_CST, "destination": MUMBAI_BANDRA, "mode": "fastest"},
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        data = resp.json()
        fastest = next(r for r in data["routes"] if r["type"] == "fastest")
        for route in data["routes"]:
            assert fastest["time_min"] <= route["time_min"], \
                f"Fastest ({fastest['time_min']}min) should be <= {route['type']} ({route['time_min']}min)"


class TestNightGuardianMode:
    """Test night_guardian mode at 2AM: 80/20 safety/time, higher risk, environmental factors"""

    def test_night_guardian_mode_at_2am(self, operator_token):
        """Night guardian at 2AM has correct weights and environmental factors"""
        resp = requests.post(
            f"{BASE_URL}/api/safe-route",
            json={
                "origin": MUMBAI_CST,
                "destination": MUMBAI_BANDRA,
                "mode": "night_guardian",
                "time": "02:00"
            },
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()
        
        # Verify mode and weights
        assert data.get("mode") == "night_guardian"
        assert data.get("mode_weights") == {"time": 0.2, "safety": 0.8}
        
        # Verify time period
        assert data.get("time_period") == "late_night"
        assert data.get("hour") == 2
        assert data.get("night_multiplier") == 1.7

    def test_night_guardian_environmental_factors(self, operator_token):
        """Night guardian at 2AM shows environmental factors"""
        resp = requests.post(
            f"{BASE_URL}/api/safe-route",
            json={
                "origin": MUMBAI_CST,
                "destination": MUMBAI_BANDRA,
                "mode": "night_guardian",
                "time": "02:00"
            },
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        data = resp.json()
        
        # Check environmental factors on routes
        for route in data["routes"]:
            env_factors = route.get("environmental_factors", [])
            # At 2AM should have late_night, deserted_area, low_lighting
            assert "late_night" in env_factors, f"Missing late_night in {env_factors}"
            assert "deserted_area" in env_factors, f"Missing deserted_area in {env_factors}"
            assert "low_lighting" in env_factors, f"Missing low_lighting in {env_factors}"

    def test_night_guardian_higher_risk_scores(self, operator_token):
        """Night guardian at 2AM has higher risk scores due to 1.7x multiplier"""
        # Day time
        resp_day = requests.post(
            f"{BASE_URL}/api/safe-route",
            json={"origin": MUMBAI_CST, "destination": MUMBAI_BANDRA, "mode": "balanced", "time": "10:00"},
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        day_risk = resp_day.json()["routes"][0]["risk_score"]
        
        # Night guardian at 2AM
        resp_night = requests.post(
            f"{BASE_URL}/api/safe-route",
            json={"origin": MUMBAI_CST, "destination": MUMBAI_BANDRA, "mode": "night_guardian", "time": "02:00"},
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        night_risk = resp_night.json()["routes"][0]["risk_score"]
        
        # Night risk should be higher due to multiplier and environmental factors
        assert night_risk >= day_risk, f"Night risk ({night_risk}) should be >= day risk ({day_risk})"


class TestInvalidMode:
    """Test invalid mode returns 400 error"""

    def test_invalid_mode_returns_400(self, operator_token):
        """POST /api/safe-route with invalid mode returns 400"""
        resp = requests.post(
            f"{BASE_URL}/api/safe-route",
            json={"origin": MUMBAI_CST, "destination": MUMBAI_BANDRA, "mode": "invalid_mode"},
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert resp.status_code == 400
        assert "invalid" in resp.text.lower() or "Invalid" in resp.text


class TestSegmentColorCoding:
    """Test segments have color coding (green/yellow/red hex values)"""

    def test_segments_have_color(self, operator_token):
        """Each segment has color field with valid hex value"""
        resp = requests.post(
            f"{BASE_URL}/api/safe-route",
            json={"origin": MUMBAI_CST, "destination": MUMBAI_BANDRA, "mode": "balanced"},
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        data = resp.json()
        valid_colors = {"#22c55e", "#f59e0b", "#ef4444"}  # green, yellow, red
        
        for route in data["routes"]:
            for seg in route.get("segments", []):
                assert "color" in seg, "Segment missing color field"
                assert seg["color"] in valid_colors, f"Invalid segment color: {seg['color']}"


class TestSegmentRiskBreakdown:
    """Test segments include live_risk, forecast_risk, environmental breakdown"""

    def test_segments_have_risk_breakdown(self, operator_token):
        """Each segment has live_risk, forecast_risk, environmental fields"""
        resp = requests.post(
            f"{BASE_URL}/api/safe-route",
            json={"origin": MUMBAI_CST, "destination": MUMBAI_BANDRA, "mode": "balanced"},
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        data = resp.json()
        
        for route in data["routes"]:
            for seg in route.get("segments", []):
                assert "live_risk" in seg, "Segment missing live_risk"
                assert "forecast_risk" in seg, "Segment missing forecast_risk"
                assert "environmental" in seg, "Segment missing environmental"
                # Verify they are numbers
                assert isinstance(seg["live_risk"], (int, float))
                assert isinstance(seg["forecast_risk"], (int, float))
                assert isinstance(seg["environmental"], (int, float))


class TestRouteEnvironmentalFactors:
    """Test routes include environmental_factors list"""

    def test_routes_have_environmental_factors(self, operator_token):
        """Each route has environmental_factors list"""
        resp = requests.post(
            f"{BASE_URL}/api/safe-route",
            json={"origin": MUMBAI_CST, "destination": MUMBAI_BANDRA, "mode": "balanced"},
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        data = resp.json()
        
        for route in data["routes"]:
            assert "environmental_factors" in route
            assert isinstance(route["environmental_factors"], list)


class TestForecastRiskAvg:
    """Test routes include forecast_risk_avg"""

    def test_routes_have_forecast_risk_avg(self, operator_token):
        """Each route has forecast_risk_avg field"""
        resp = requests.post(
            f"{BASE_URL}/api/safe-route",
            json={"origin": MUMBAI_CST, "destination": MUMBAI_BANDRA, "mode": "balanced"},
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        data = resp.json()
        
        for route in data["routes"]:
            assert "forecast_risk_avg" in route
            assert isinstance(route["forecast_risk_avg"], (int, float))
            assert route["forecast_risk_avg"] >= 0


class TestModeWeightsInResponse:
    """Test response includes mode_weights showing time and safety percentages"""

    def test_mode_weights_in_response(self, operator_token):
        """Response has mode_weights with time and safety keys"""
        for mode in ["balanced", "safest", "fastest", "night_guardian"]:
            resp = requests.post(
                f"{BASE_URL}/api/safe-route",
                json={
                    "origin": MUMBAI_CST,
                    "destination": MUMBAI_BANDRA,
                    "mode": mode,
                    "time": "02:00" if mode == "night_guardian" else None
                },
                headers={"Authorization": f"Bearer {operator_token}"}
            )
            data = resp.json()
            assert "mode_weights" in data, f"Missing mode_weights for {mode}"
            assert "time" in data["mode_weights"]
            assert "safety" in data["mode_weights"]


class TestRecommendedFlag:
    """Test recommended flag set to true on primary route"""

    def test_one_route_is_recommended(self, operator_token):
        """Exactly one route has recommended=true"""
        resp = requests.post(
            f"{BASE_URL}/api/safe-route",
            json={"origin": MUMBAI_CST, "destination": MUMBAI_BANDRA, "mode": "balanced"},
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        data = resp.json()
        
        recommended_routes = [r for r in data["routes"] if r.get("recommended")]
        assert len(recommended_routes) == 1, f"Expected 1 recommended route, got {len(recommended_routes)}"

    def test_recommended_matches_mode(self, operator_token):
        """Recommended route matches the mode selection"""
        for mode in ["balanced", "safest", "fastest"]:
            resp = requests.post(
                f"{BASE_URL}/api/safe-route",
                json={"origin": MUMBAI_CST, "destination": MUMBAI_BANDRA, "mode": mode},
                headers={"Authorization": f"Bearer {operator_token}"}
            )
            data = resp.json()
            recommended = next(r for r in data["routes"] if r.get("recommended"))
            assert recommended["type"] == mode, f"For mode={mode}, recommended type should be {mode}, got {recommended['type']}"


class TestTimeParameter:
    """Test time parameter works (e.g. time='23:30' activates night mode)"""

    def test_time_parameter_activates_night_mode(self, operator_token):
        """time='23:30' with balanced mode activates night_guardian"""
        resp = requests.post(
            f"{BASE_URL}/api/safe-route",
            json={
                "origin": MUMBAI_CST,
                "destination": MUMBAI_BANDRA,
                "mode": "balanced",
                "time": "23:30"
            },
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        data = resp.json()
        
        # Should auto-activate night_guardian at night
        assert data.get("mode") == "night_guardian"
        assert data.get("time_period") == "night"
        assert data.get("hour") == 23
        assert data.get("night_multiplier") == 1.4

    def test_time_parameter_day_keeps_balanced(self, operator_token):
        """time='10:00' with balanced mode stays balanced"""
        resp = requests.post(
            f"{BASE_URL}/api/safe-route",
            json={
                "origin": MUMBAI_CST,
                "destination": MUMBAI_BANDRA,
                "mode": "balanced",
                "time": "10:00"
            },
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        data = resp.json()
        
        assert data.get("mode") == "balanced"
        assert data.get("time_period") == "day"
        assert data.get("night_multiplier") == 1.0


class TestForecastCacheStatus:
    """Test GET /api/system/forecast-cache-status returns cache monitoring data"""

    def test_forecast_cache_status_endpoint(self, operator_token):
        """GET /api/system/forecast-cache-status returns cache info"""
        resp = requests.get(
            f"{BASE_URL}/api/system/forecast-cache-status",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()
        
        # Verify expected fields
        assert "redis_keys" in data or "memory_entries" in data
        assert "ttl_seconds" in data
        assert "grid_cell_size_m" in data


class TestAuthentication:
    """Test authentication requirements"""

    def test_safe_route_requires_auth(self):
        """POST /safe-route returns 401/403 without auth"""
        resp = requests.post(
            f"{BASE_URL}/api/safe-route",
            json={"origin": MUMBAI_CST, "destination": MUMBAI_BANDRA}
        )
        assert resp.status_code in [401, 403]

    def test_guardian_can_access(self, guardian_token):
        """Guardian can access safe-route API"""
        resp = requests.post(
            f"{BASE_URL}/api/safe-route",
            json={"origin": MUMBAI_CST, "destination": MUMBAI_BANDRA},
            headers={"Authorization": f"Bearer {guardian_token}"}
        )
        assert resp.status_code == 200


class TestCompleteRouteStructure:
    """Test routes have all required fields"""

    def test_route_has_all_fields(self, operator_token):
        """Each route has all required fields"""
        resp = requests.post(
            f"{BASE_URL}/api/safe-route",
            json={"origin": MUMBAI_CST, "destination": MUMBAI_BANDRA, "mode": "balanced"},
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        data = resp.json()
        
        required_fields = [
            "type", "recommended", "distance_km", "time_min",
            "risk_score", "risk_level", "zones_crossed",
            "high_risk_zones", "critical_zones", "segment_count",
            "color", "geometry", "segments", "warnings",
            "environmental_factors", "forecast_risk_avg", "cost"
        ]
        
        for route in data["routes"]:
            for field in required_fields:
                assert field in route, f"Route missing field: {field}"

    def test_cost_has_components(self, operator_token):
        """Route cost has time, risk, weighted components"""
        resp = requests.post(
            f"{BASE_URL}/api/safe-route",
            json={"origin": MUMBAI_CST, "destination": MUMBAI_BANDRA, "mode": "balanced"},
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        data = resp.json()
        
        for route in data["routes"]:
            cost = route.get("cost", {})
            assert "time" in cost
            assert "risk" in cost
            assert "weighted" in cost
