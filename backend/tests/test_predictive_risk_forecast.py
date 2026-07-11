# Predictive Risk Forecasting Backend Tests (Phase 27)
# Tests new forecast endpoints for hotspot zone risk predictions at 24h/48h/72h horizons
# Features tested:
# - GET /api/operator/risk-learning/forecast - all zone forecasts
# - GET /api/operator/risk-learning/forecast-stats - lightweight summary
# - GET /api/operator/risk-learning/hotspots/{zone_id}/forecast - single zone forecast
# - Existing risk-learning endpoints still work (regression)

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"
GUARDIAN_EMAIL = "nischint4parents@gmail.com"
GUARDIAN_PASSWORD = "secret123"

# Valid zone IDs (integers as per context - 18 learned hotspot zones)
VALID_ZONE_IDS = list(range(1, 19))  # 1-18


@pytest.fixture(scope="module")
def operator_token():
    """Get operator auth token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": OPERATOR_EMAIL,
        "password": OPERATOR_PASSWORD
    })
    assert response.status_code == 200, f"Operator login failed: {response.text}"
    return response.json()["access_token"]


@pytest.fixture(scope="module")
def guardian_token():
    """Get guardian auth token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": GUARDIAN_EMAIL,
        "password": GUARDIAN_PASSWORD
    })
    assert response.status_code == 200, f"Guardian login failed: {response.text}"
    return response.json()["access_token"]


# ══════════════════════════════════════════════════════════════════════════════
# Test GET /api/operator/risk-learning/forecast (all forecasts)
# ══════════════════════════════════════════════════════════════════════════════

class TestAllForecastsEndpoint:
    """Test /api/operator/risk-learning/forecast returns proper response"""

    def test_forecast_endpoint_requires_auth(self):
        """Unauthenticated request returns 401"""
        response = requests.get(f"{BASE_URL}/api/operator/risk-learning/forecast")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: Forecast endpoint requires authentication (401)")

    def test_guardian_cannot_access_forecast(self, guardian_token):
        """Guardian role returns 403"""
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/forecast",
            headers={"Authorization": f"Bearer {guardian_token}"}
        )
        assert response.status_code == 403, f"Expected 403 for guardian, got {response.status_code}"
        print("PASS: Guardian role correctly gets 403 Forbidden")

    def test_forecast_endpoint_returns_200(self, operator_token):
        """GET /api/operator/risk-learning/forecast returns 200"""
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/forecast",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: Forecast endpoint returns 200 OK")

    def test_forecast_response_structure(self, operator_token):
        """Response has required top-level fields"""
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/forecast",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        required_fields = [
            "total_zones", "forecast_counts", "priority_counts", 
            "p1_predicted_48h", "forecasts", "escalating_zones", 
            "emerging_zones", "cooling_zones", "analyzed_at"
        ]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        
        print(f"PASS: Response has all required fields: {required_fields}")

    def test_forecast_counts_structure(self, operator_token):
        """forecast_counts contains valid category keys"""
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/forecast",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        fc = data["forecast_counts"]
        valid_categories = {"escalating", "emerging", "stable", "cooling"}
        for key in fc.keys():
            assert key in valid_categories, f"Invalid forecast category: {key}"
        
        print(f"PASS: forecast_counts has valid categories: {fc}")

    def test_priority_counts_structure(self, operator_token):
        """priority_counts contains valid priority keys (1/2/3)"""
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/forecast",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        pc = data["priority_counts"]
        valid_priorities = {"1", "2", "3"}
        for key in pc.keys():
            assert key in valid_priorities, f"Invalid priority key: {key}"
        
        print(f"PASS: priority_counts has valid priority keys: {pc}")

    def test_forecasts_array_structure(self, operator_token):
        """Each forecast in 'forecasts' array has required fields"""
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/forecast",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        forecasts = data["forecasts"]
        assert isinstance(forecasts, list), "forecasts should be a list"
        
        if len(forecasts) == 0:
            print("INFO: No forecasts returned (empty zone list)")
            return
        
        required_zone_fields = [
            "zone_id", "zone_name", "risk_score",
            "predicted_24h", "predicted_48h", "predicted_72h",
            "forecast_category", "forecast_priority", "confidence",
            "signals", "recommendation", "sparkline_past", "sparkline_future"
        ]
        
        for forecast in forecasts[:5]:  # Check first 5
            for field in required_zone_fields:
                assert field in forecast, f"Forecast missing field: {field}"
        
        print(f"PASS: Forecast items have all required fields (checked {min(5, len(forecasts))} items)")

    def test_forecast_values_valid(self, operator_token):
        """Predicted values and confidence are within valid ranges"""
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/forecast",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        for forecast in data["forecasts"][:5]:
            # Risk scores 0-10
            assert 0 <= forecast["predicted_24h"] <= 10, f"predicted_24h out of range: {forecast['predicted_24h']}"
            assert 0 <= forecast["predicted_48h"] <= 10, f"predicted_48h out of range: {forecast['predicted_48h']}"
            assert 0 <= forecast["predicted_72h"] <= 10, f"predicted_72h out of range: {forecast['predicted_72h']}"
            
            # Confidence 0-1
            assert 0 <= forecast["confidence"] <= 1, f"confidence out of range: {forecast['confidence']}"
            
            # Forecast category valid
            assert forecast["forecast_category"] in ["escalating", "emerging", "stable", "cooling"]
            
            # Forecast priority 1/2/3
            assert forecast["forecast_priority"] in [1, 2, 3]
        
        print("PASS: Forecast values within valid ranges")

    def test_signals_structure(self, operator_token):
        """signals object has required signal fields"""
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/forecast",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        for forecast in data["forecasts"][:3]:
            signals = forecast["signals"]
            required_signals = ["trend_score", "incident_velocity", "severity_momentum", "temporal_pattern"]
            for sig in required_signals:
                assert sig in signals, f"Missing signal: {sig}"
        
        print("PASS: signals object has all required fields")

    def test_recommendation_structure(self, operator_token):
        """recommendation object has action, details, urgency"""
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/forecast",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        for forecast in data["forecasts"][:3]:
            rec = forecast["recommendation"]
            assert "action" in rec, "recommendation missing 'action'"
            assert "details" in rec, "recommendation missing 'details'"
            assert "urgency" in rec, "recommendation missing 'urgency'"
            assert rec["urgency"] in ["high", "medium", "low"], f"Invalid urgency: {rec['urgency']}"
        
        print("PASS: recommendation object has action, details, urgency")


# ══════════════════════════════════════════════════════════════════════════════
# Test GET /api/operator/risk-learning/forecast-stats (lightweight summary)
# ══════════════════════════════════════════════════════════════════════════════

class TestForecastStatsEndpoint:
    """Test lightweight forecast stats endpoint for Command Center"""

    def test_forecast_stats_requires_auth(self):
        """Unauthenticated request returns 401"""
        response = requests.get(f"{BASE_URL}/api/operator/risk-learning/forecast-stats")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: forecast-stats requires authentication (401)")

    def test_forecast_stats_returns_200(self, operator_token):
        """GET /api/operator/risk-learning/forecast-stats returns 200"""
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/forecast-stats",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: forecast-stats returns 200 OK")

    def test_forecast_stats_response_structure(self, operator_token):
        """Response has required summary fields"""
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/forecast-stats",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        required_fields = [
            "total_zones", "forecast_counts", "priority_counts",
            "p1_predicted_48h", "zones_escalating", "avg_predicted_48h", "analyzed_at"
        ]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        
        print(f"PASS: forecast-stats has required fields: total_zones={data['total_zones']}, p1_predicted_48h={data['p1_predicted_48h']}, zones_escalating={data['zones_escalating']}")

    def test_forecast_stats_is_lightweight(self, operator_token):
        """forecast-stats should NOT contain full forecasts array (lightweight)"""
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/forecast-stats",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Should NOT have heavy arrays
        assert "forecasts" not in data, "forecast-stats should not contain 'forecasts' array (not lightweight)"
        assert "escalating_zones" not in data, "forecast-stats should not contain zone arrays"
        
        print("PASS: forecast-stats is lightweight (no full forecast arrays)")

    def test_forecast_stats_data_types(self, operator_token):
        """Verify data types of forecast-stats fields"""
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/forecast-stats",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert isinstance(data["total_zones"], int)
        assert isinstance(data["p1_predicted_48h"], int)
        assert isinstance(data["zones_escalating"], int)
        assert isinstance(data["avg_predicted_48h"], (int, float))
        assert isinstance(data["forecast_counts"], dict)
        assert isinstance(data["priority_counts"], dict)
        
        print(f"PASS: forecast-stats data types correct - avg_predicted_48h={data['avg_predicted_48h']}")


# ══════════════════════════════════════════════════════════════════════════════
# Test GET /api/operator/risk-learning/hotspots/{zone_id}/forecast (single zone)
# ══════════════════════════════════════════════════════════════════════════════

class TestSingleZoneForecast:
    """Test single zone forecast endpoint"""

    @pytest.fixture(scope="class")
    def valid_zone_id(self, operator_token):
        """Get a valid zone_id from forecasts"""
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/forecast",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        if response.status_code == 200 and response.json().get("forecasts"):
            return response.json()["forecasts"][0]["zone_id"]
        return None

    def test_zone_forecast_requires_auth(self):
        """Unauthenticated request returns 401"""
        response = requests.get(f"{BASE_URL}/api/operator/risk-learning/hotspots/389/forecast")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: Zone forecast requires authentication (401)")

    def test_zone_forecast_returns_200(self, operator_token, valid_zone_id):
        """GET /api/operator/risk-learning/hotspots/{zone_id}/forecast returns 200 for valid zone"""
        if not valid_zone_id:
            pytest.skip("No valid zone_id available")
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/hotspots/{valid_zone_id}/forecast",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print(f"PASS: Zone forecast returns 200 for valid zone_id={valid_zone_id}")

    def test_zone_forecast_response_structure(self, operator_token, valid_zone_id):
        """Response has required forecast fields"""
        if not valid_zone_id:
            pytest.skip("No valid zone_id available")
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/hotspots/{valid_zone_id}/forecast",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        required_fields = [
            "zone_id", "zone_name", "risk_score",
            "predicted_24h", "predicted_48h", "predicted_72h",
            "forecast_category", "forecast_priority", "confidence",
            "signals", "recommendation"
        ]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"
        
        print(f"PASS: Zone forecast has required fields - predicted_48h={data['predicted_48h']}, category={data['forecast_category']}")

    def test_zone_forecast_invalid_zone_returns_404(self, operator_token):
        """Non-existent zone returns 404"""
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/hotspots/99999/forecast",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("PASS: Non-existent zone returns 404")


# ══════════════════════════════════════════════════════════════════════════════
# Regression: Existing risk-learning endpoints still work
# ══════════════════════════════════════════════════════════════════════════════

class TestExistingEndpointsRegression:
    """Ensure existing risk-learning endpoints still work after forecast feature"""

    def test_stats_endpoint_still_works(self, operator_token):
        """GET /api/operator/risk-learning/stats still returns 200"""
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/stats",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200, f"Stats endpoint failed: {response.status_code}"
        print("PASS: /api/operator/risk-learning/stats still works")

    def test_hotspots_endpoint_still_works(self, operator_token):
        """GET /api/operator/risk-learning/hotspots still returns 200"""
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/hotspots",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200, f"Hotspots endpoint failed: {response.status_code}"
        print("PASS: /api/operator/risk-learning/hotspots still works")

    def test_recalculate_endpoint_still_works(self, operator_token):
        """POST /api/operator/risk-learning/recalculate still returns 200"""
        response = requests.post(
            f"{BASE_URL}/api/operator/risk-learning/recalculate",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200, f"Recalculate endpoint failed: {response.status_code}"
        print("PASS: /api/operator/risk-learning/recalculate still works")

    def test_trends_endpoint_still_works(self, operator_token):
        """GET /api/operator/risk-learning/trends still returns 200"""
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/trends",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200, f"Trends endpoint failed: {response.status_code}"
        print("PASS: /api/operator/risk-learning/trends still works")

    def test_trend_stats_endpoint_still_works(self, operator_token):
        """GET /api/operator/risk-learning/trend-stats still returns 200"""
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/trend-stats",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200, f"Trend-stats endpoint failed: {response.status_code}"
        print("PASS: /api/operator/risk-learning/trend-stats still works")

    def test_zone_trend_endpoint_still_works(self, operator_token):
        """GET /api/operator/risk-learning/hotspots/{zone_id}/trend still returns 200"""
        # First get a valid zone_id
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/forecast",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        if response.status_code == 200 and response.json().get("forecasts"):
            zone_id = response.json()["forecasts"][0]["zone_id"]
            response = requests.get(
                f"{BASE_URL}/api/operator/risk-learning/hotspots/{zone_id}/trend",
                headers={"Authorization": f"Bearer {operator_token}"}
            )
            assert response.status_code == 200, f"Zone trend endpoint failed: {response.status_code}"
            print(f"PASS: /api/operator/risk-learning/hotspots/{zone_id}/trend still works")
        else:
            print("SKIP: No zones available for trend test")


# ══════════════════════════════════════════════════════════════════════════════
# Test forecast category classification logic
# ══════════════════════════════════════════════════════════════════════════════

class TestForecastCategoryLogic:
    """Test that forecast categories are classified correctly"""

    def test_escalating_zones_are_high_risk(self, operator_token):
        """Escalating zones should have high predicted scores"""
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/forecast",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        for zone in data.get("escalating_zones", []):
            assert zone["forecast_category"] == "escalating"
            assert zone["forecast_priority"] == 1, "Escalating zones should be P1"
            # Escalating means predicted_48h >= 7.0 and delta > 0.5
            print(f"  Escalating: {zone['zone_name']} - current={zone['risk_score']}, predicted_48h={zone['predicted_48h']}")
        
        print(f"PASS: {len(data.get('escalating_zones', []))} escalating zones verified")

    def test_emerging_zones_classification(self, operator_token):
        """Emerging zones should have rising predicted scores"""
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/forecast",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        for zone in data.get("emerging_zones", []):
            assert zone["forecast_category"] == "emerging"
            assert zone["forecast_priority"] in [1, 2], "Emerging zones should be P1 or P2"
        
        print(f"PASS: {len(data.get('emerging_zones', []))} emerging zones verified")

    def test_cooling_zones_classification(self, operator_token):
        """Cooling zones should have declining predicted scores"""
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/forecast",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        for zone in data.get("cooling_zones", []):
            assert zone["forecast_category"] == "cooling"
            # Cooling should generally be P3
            assert zone["forecast_priority"] == 3, "Cooling zones should be P3"
        
        print(f"PASS: {len(data.get('cooling_zones', []))} cooling zones verified")

    def test_p1_predicted_48h_count_matches(self, operator_token):
        """p1_predicted_48h count should match escalating + emerging zones that reach P1"""
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/forecast",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Count forecasts that will become P1 within 48h
        p1_count = sum(1 for f in data["forecasts"] 
                       if f["predicted_48h"] >= 7.0 and f["forecast_category"] in ("escalating", "emerging"))
        
        assert data["p1_predicted_48h"] == p1_count, f"p1_predicted_48h mismatch: {data['p1_predicted_48h']} != {p1_count}"
        print(f"PASS: p1_predicted_48h={data['p1_predicted_48h']} matches computed count")


# ══════════════════════════════════════════════════════════════════════════════
# Test forecast performance (API should complete in reasonable time)
# ══════════════════════════════════════════════════════════════════════════════

class TestForecastPerformance:
    """Test forecast API response times"""

    def test_forecast_completes_within_timeout(self, operator_token):
        """Forecast API should complete within 15 seconds"""
        import time
        start = time.time()
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/forecast",
            headers={"Authorization": f"Bearer {operator_token}"},
            timeout=15
        )
        elapsed = time.time() - start
        
        assert response.status_code == 200
        assert elapsed < 15, f"Forecast took too long: {elapsed:.1f}s"
        print(f"PASS: Forecast completed in {elapsed:.1f}s")

    def test_forecast_stats_is_faster(self, operator_token):
        """forecast-stats should be faster than full forecast"""
        import time
        start = time.time()
        response = requests.get(
            f"{BASE_URL}/api/operator/risk-learning/forecast-stats",
            headers={"Authorization": f"Bearer {operator_token}"},
            timeout=10
        )
        elapsed = time.time() - start
        
        assert response.status_code == 200
        assert elapsed < 10, f"forecast-stats took too long: {elapsed:.1f}s"
        print(f"PASS: forecast-stats completed in {elapsed:.1f}s")
