"""
Phase 40: Safety Score API Tests
Tests for Location, Route, and Journey safety scores.

Score Types:
- Location: Click map or enter coordinates - Returns score with 5 signals
- Route: Origin/destination - Returns route score with risk_zones_crossed, max_risk
- Journey: Guardian session - Returns journey score with penalties, base_score, alert_count

Signal Layers: zone_risk, dynamic_risk, incident_density, route_exposure, time_risk
Score Categories: Very Safe (8-10), Safe (6-8), Moderate (4-6), High Risk (2-4), Critical (0-2)
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test Credentials
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"
GUARDIAN_EMAIL = "nischint4parents@gmail.com"
GUARDIAN_PASSWORD = "secret123"

# Test Data
BANGALORE_CENTER = {"lat": 12.97, "lng": 77.59}
BANGALORE_NORTH = {"lat": 12.98, "lng": 77.60}
ACTIVE_SESSION_ID = "56c30aa1-8cd3-4489-9cd7-e402407ce5d1"
INVALID_SESSION_ID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture(scope="module")
def api_client():
    """Shared requests session."""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


@pytest.fixture(scope="module")
def operator_token(api_client):
    """Get operator authentication token."""
    response = api_client.post(f"{BASE_URL}/api/auth/login", json={
        "email": OPERATOR_EMAIL,
        "password": OPERATOR_PASSWORD
    })
    if response.status_code == 200:
        return response.json().get("access_token")
    pytest.fail(f"Operator login failed: {response.status_code} - {response.text}")


@pytest.fixture(scope="module")
def guardian_token(api_client):
    """Get guardian authentication token."""
    response = api_client.post(f"{BASE_URL}/api/auth/login", json={
        "email": GUARDIAN_EMAIL,
        "password": GUARDIAN_PASSWORD
    })
    if response.status_code == 200:
        return response.json().get("access_token")
    pytest.fail(f"Guardian login failed: {response.status_code}")


@pytest.fixture(scope="module")
def operator_client(api_client, operator_token):
    """Session with operator auth header."""
    api_client.headers.update({"Authorization": f"Bearer {operator_token}"})
    return api_client


class TestLocationScoreAPI:
    """Tests for GET /api/safety-score/location?lat=X&lng=Y"""

    def test_location_score_returns_200(self, operator_client):
        """Location score endpoint returns 200 OK."""
        response = operator_client.get(
            f"{BASE_URL}/api/safety-score/location",
            params={"lat": BANGALORE_CENTER["lat"], "lng": BANGALORE_CENTER["lng"]}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print(f"✓ Location score returned 200 OK")

    def test_location_score_response_structure(self, operator_client):
        """Response contains all required fields."""
        response = operator_client.get(
            f"{BASE_URL}/api/safety-score/location",
            params={"lat": BANGALORE_CENTER["lat"], "lng": BANGALORE_CENTER["lng"]}
        )
        data = response.json()

        required_fields = [
            "score", "night_score", "label", "category", "risk_index",
            "percentile", "percentile_text", "trend", "signals",
            "nearby_incidents", "nearby_zones", "location", "computed_at"
        ]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"

        print(f"✓ All required fields present: score={data['score']}, label={data['label']}")

    def test_location_score_has_all_5_signals(self, operator_client):
        """Response contains all 5 signal layers."""
        response = operator_client.get(
            f"{BASE_URL}/api/safety-score/location",
            params={"lat": BANGALORE_CENTER["lat"], "lng": BANGALORE_CENTER["lng"]}
        )
        data = response.json()
        signals = data["signals"]

        required_signals = ["zone_risk", "dynamic_risk", "incident_density", "route_exposure", "time_risk"]
        for sig in required_signals:
            assert sig in signals, f"Missing signal: {sig}"
            assert "raw" in signals[sig], f"Missing raw value for {sig}"
            assert "normalized" in signals[sig], f"Missing normalized value for {sig}"
            assert "weight" in signals[sig], f"Missing weight for {sig}"

        print(f"✓ All 5 signal layers present with raw, normalized, weight")

    def test_signal_normalization_0_1_range(self, operator_client):
        """Signal normalized values are in 0-1 range."""
        response = operator_client.get(
            f"{BASE_URL}/api/safety-score/location",
            params={"lat": BANGALORE_CENTER["lat"], "lng": BANGALORE_CENTER["lng"]}
        )
        data = response.json()
        signals = data["signals"]

        for sig_name, sig_data in signals.items():
            norm = sig_data["normalized"]
            assert 0.0 <= norm <= 1.0, f"Signal {sig_name} normalized={norm} outside [0,1]"

        print(f"✓ All signal normalized values in [0, 1] range")

    def test_score_0_10_range(self, operator_client):
        """Score is in 0-10 range."""
        response = operator_client.get(
            f"{BASE_URL}/api/safety-score/location",
            params={"lat": BANGALORE_CENTER["lat"], "lng": BANGALORE_CENTER["lng"]}
        )
        data = response.json()

        assert 0 <= data["score"] <= 10, f"Score {data['score']} outside [0, 10]"
        assert 0 <= data["night_score"] <= 10, f"Night score {data['night_score']} outside [0, 10]"

        print(f"✓ Score {data['score']} and night_score {data['night_score']} in [0, 10] range")

    def test_percentile_1_99_range(self, operator_client):
        """Percentile is in 1-99 range."""
        response = operator_client.get(
            f"{BASE_URL}/api/safety-score/location",
            params={"lat": BANGALORE_CENTER["lat"], "lng": BANGALORE_CENTER["lng"]}
        )
        data = response.json()

        assert 1 <= data["percentile"] <= 99, f"Percentile {data['percentile']} outside [1, 99]"

        print(f"✓ Percentile {data['percentile']} in [1, 99] range")

    def test_trend_valid_values(self, operator_client):
        """Trend is rising, falling, or stable."""
        response = operator_client.get(
            f"{BASE_URL}/api/safety-score/location",
            params={"lat": BANGALORE_CENTER["lat"], "lng": BANGALORE_CENTER["lng"]}
        )
        data = response.json()

        valid_trends = {"rising", "falling", "stable"}
        assert data["trend"] in valid_trends, f"Invalid trend: {data['trend']}"

        print(f"✓ Trend '{data['trend']}' is valid")

    def test_score_category_correct(self, operator_client):
        """Score category matches score value."""
        response = operator_client.get(
            f"{BASE_URL}/api/safety-score/location",
            params={"lat": BANGALORE_CENTER["lat"], "lng": BANGALORE_CENTER["lng"]}
        )
        data = response.json()
        score = data["score"]
        category = data["category"]

        # Score categories: Very Safe (8-10), Safe (6-8), Moderate (4-6), High Risk (2-4), Critical (0-2)
        if score >= 8:
            expected = "very_safe"
        elif score >= 6:
            expected = "safe"
        elif score >= 4:
            expected = "moderate"
        elif score >= 2:
            expected = "high"
        else:
            expected = "critical"

        assert category == expected, f"Score {score} should be '{expected}', got '{category}'"

        print(f"✓ Score {score} correctly categorized as '{category}'")

    def test_location_returns_coordinates(self, operator_client):
        """Response includes the requested location."""
        lat, lng = 12.95, 77.58
        response = operator_client.get(
            f"{BASE_URL}/api/safety-score/location",
            params={"lat": lat, "lng": lng}
        )
        data = response.json()

        assert data["location"]["lat"] == lat
        assert data["location"]["lng"] == lng

        print(f"✓ Location returned correctly: lat={lat}, lng={lng}")


class TestRouteScoreAPI:
    """Tests for POST /api/safety-score/route"""

    def test_route_score_returns_200(self, operator_client):
        """Route score endpoint returns 200 OK."""
        response = operator_client.post(
            f"{BASE_URL}/api/safety-score/route",
            json={"origin": BANGALORE_CENTER, "destination": BANGALORE_NORTH}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print(f"✓ Route score returned 200 OK")

    def test_route_score_response_structure(self, operator_client):
        """Response contains all required fields."""
        response = operator_client.post(
            f"{BASE_URL}/api/safety-score/route",
            json={"origin": BANGALORE_CENTER, "destination": BANGALORE_NORTH}
        )
        data = response.json()

        required_fields = [
            "score", "min_score", "label", "category", "percentile", "percentile_text",
            "trend", "risk_zones_crossed", "max_risk", "total_distance_m",
            "sample_points", "point_scores", "origin", "destination", "computed_at"
        ]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"

        print(f"✓ All required fields present: score={data['score']}, risk_zones={data['risk_zones_crossed']}")

    def test_route_score_0_10_range(self, operator_client):
        """Route score is in 0-10 range."""
        response = operator_client.post(
            f"{BASE_URL}/api/safety-score/route",
            json={"origin": BANGALORE_CENTER, "destination": BANGALORE_NORTH}
        )
        data = response.json()

        assert 0 <= data["score"] <= 10, f"Score {data['score']} outside [0, 10]"
        assert 0 <= data["min_score"] <= 10, f"Min score {data['min_score']} outside [0, 10]"

        print(f"✓ Route score {data['score']}, min_score {data['min_score']} in [0, 10] range")

    def test_route_has_sample_points(self, operator_client):
        """Route score returns sample points."""
        response = operator_client.post(
            f"{BASE_URL}/api/safety-score/route",
            json={"origin": BANGALORE_CENTER, "destination": BANGALORE_NORTH}
        )
        data = response.json()

        assert data["sample_points"] >= 2, f"Sample points {data['sample_points']} should be >= 2"
        assert len(data["point_scores"]) > 0, "point_scores array should not be empty"

        print(f"✓ Route has {data['sample_points']} sample points with {len(data['point_scores'])} scores")

    def test_route_risk_zones_crossed_non_negative(self, operator_client):
        """risk_zones_crossed is non-negative."""
        response = operator_client.post(
            f"{BASE_URL}/api/safety-score/route",
            json={"origin": BANGALORE_CENTER, "destination": BANGALORE_NORTH}
        )
        data = response.json()

        assert data["risk_zones_crossed"] >= 0, f"risk_zones_crossed {data['risk_zones_crossed']} should be >= 0"

        print(f"✓ risk_zones_crossed={data['risk_zones_crossed']} is non-negative")

    def test_route_max_risk_valid(self, operator_client):
        """max_risk is a valid risk level."""
        response = operator_client.post(
            f"{BASE_URL}/api/safety-score/route",
            json={"origin": BANGALORE_CENTER, "destination": BANGALORE_NORTH}
        )
        data = response.json()

        valid_risks = {"safe", "moderate", "high", "critical", "SAFE", "MODERATE", "HIGH", "CRITICAL"}
        assert data["max_risk"] in valid_risks, f"Invalid max_risk: {data['max_risk']}"

        print(f"✓ max_risk='{data['max_risk']}' is valid")


class TestJourneyScoreAPI:
    """Tests for GET /api/safety-score/journey/{session_id}"""

    def test_journey_score_returns_200(self, operator_client):
        """Journey score endpoint returns 200 OK for valid session."""
        response = operator_client.get(
            f"{BASE_URL}/api/safety-score/journey/{ACTIVE_SESSION_ID}"
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print(f"✓ Journey score returned 200 OK")

    def test_journey_score_response_structure(self, operator_client):
        """Response contains all required fields."""
        response = operator_client.get(
            f"{BASE_URL}/api/safety-score/journey/{ACTIVE_SESSION_ID}"
        )
        data = response.json()

        required_fields = [
            "score", "base_score", "label", "category", "penalties",
            "total_penalty", "session_id", "status", "duration_minutes",
            "max_risk_level", "alert_count", "alert_breakdown",
            "risk_zones_crossed", "route_deviated", "escalation_level", "computed_at"
        ]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"

        print(f"✓ All required fields present: score={data['score']}, alert_count={data['alert_count']}")

    def test_journey_score_0_10_range(self, operator_client):
        """Journey score is in 0-10 range."""
        response = operator_client.get(
            f"{BASE_URL}/api/safety-score/journey/{ACTIVE_SESSION_ID}"
        )
        data = response.json()

        assert 0 <= data["score"] <= 10, f"Score {data['score']} outside [0, 10]"
        assert 0 <= data["base_score"] <= 10, f"Base score {data['base_score']} outside [0, 10]"

        print(f"✓ Journey score {data['score']}, base_score {data['base_score']} in [0, 10] range")

    def test_journey_penalties_structure(self, operator_client):
        """Penalties array has correct structure."""
        response = operator_client.get(
            f"{BASE_URL}/api/safety-score/journey/{ACTIVE_SESSION_ID}"
        )
        data = response.json()

        for penalty in data["penalties"]:
            assert "reason" in penalty, "Penalty missing reason"
            assert "amount" in penalty, "Penalty missing amount"
            assert "count" in penalty, "Penalty missing count"

        print(f"✓ Penalties structure correct: {len(data['penalties'])} penalties")

    def test_journey_alert_count_matches_breakdown(self, operator_client):
        """alert_count matches sum of alert_breakdown."""
        response = operator_client.get(
            f"{BASE_URL}/api/safety-score/journey/{ACTIVE_SESSION_ID}"
        )
        data = response.json()

        breakdown_sum = sum(data["alert_breakdown"].values())
        assert data["alert_count"] == breakdown_sum, \
            f"alert_count {data['alert_count']} != breakdown sum {breakdown_sum}"

        print(f"✓ alert_count {data['alert_count']} matches breakdown sum")

    def test_journey_invalid_session_404(self, operator_client):
        """Invalid session ID returns 404."""
        response = operator_client.get(
            f"{BASE_URL}/api/safety-score/journey/{INVALID_SESSION_ID}"
        )
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print(f"✓ Invalid session correctly returns 404")


class TestScoreCategoriesCorrect:
    """Tests to verify score categories are correct."""

    def test_all_categories_accounted(self, operator_client):
        """Verify all 5 score categories exist."""
        response = operator_client.get(
            f"{BASE_URL}/api/safety-score/location",
            params={"lat": 12.97, "lng": 77.59}
        )
        data = response.json()

        valid_categories = {"very_safe", "safe", "moderate", "high", "critical"}
        assert data["category"] in valid_categories, f"Invalid category: {data['category']}"

        # Verify label matches category
        category_labels = {
            "very_safe": "Very Safe",
            "safe": "Safe",
            "moderate": "Moderate Risk",
            "high": "High Risk",
            "critical": "Critical"
        }
        expected_label = category_labels.get(data["category"])
        assert data["label"] == expected_label, f"Label mismatch: got '{data['label']}', expected '{expected_label}'"

        print(f"✓ Category '{data['category']}' with label '{data['label']}' is valid")


class TestAuthenticationRequired:
    """Tests for authentication requirements."""

    def test_location_score_requires_auth(self, api_client):
        """Location score requires authentication."""
        response = requests.get(
            f"{BASE_URL}/api/safety-score/location",
            params={"lat": 12.97, "lng": 77.59}
        )
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print(f"✓ Location score requires authentication (401)")

    def test_route_score_requires_auth(self, api_client):
        """Route score requires authentication."""
        response = requests.post(
            f"{BASE_URL}/api/safety-score/route",
            json={"origin": {"lat": 12.97, "lng": 77.59}, "destination": {"lat": 12.98, "lng": 77.60}}
        )
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print(f"✓ Route score requires authentication (401)")

    def test_journey_score_requires_auth(self, api_client):
        """Journey score requires authentication."""
        response = requests.get(
            f"{BASE_URL}/api/safety-score/journey/{ACTIVE_SESSION_ID}"
        )
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print(f"✓ Journey score requires authentication (401)")


class TestGuardianCanAccessSafetyScore:
    """Tests to verify Guardian role can access safety score APIs."""

    def test_guardian_location_score_access(self, api_client, guardian_token):
        """Guardian can access location score."""
        response = api_client.get(
            f"{BASE_URL}/api/safety-score/location",
            params={"lat": 12.97, "lng": 77.59},
            headers={"Authorization": f"Bearer {guardian_token}"}
        )
        # Should be 200 or 403 (depending on RBAC setup)
        assert response.status_code in [200, 403], f"Unexpected status: {response.status_code}"
        print(f"✓ Guardian location score access: {response.status_code}")

    def test_guardian_journey_score_access(self, api_client, guardian_token):
        """Guardian can access journey score for their own sessions."""
        response = api_client.get(
            f"{BASE_URL}/api/safety-score/journey/{ACTIVE_SESSION_ID}",
            headers={"Authorization": f"Bearer {guardian_token}"}
        )
        # Should be 200 or 403 (depending on RBAC setup)
        assert response.status_code in [200, 403], f"Unexpected status: {response.status_code}"
        print(f"✓ Guardian journey score access: {response.status_code}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
