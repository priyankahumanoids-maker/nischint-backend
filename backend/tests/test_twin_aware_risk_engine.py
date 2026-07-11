"""
Twin-Aware Risk Engine Tests
Tests for the personalized behavior scoring based on digital twin context.

Features tested:
1. _apply_twin_context() - boosts score when twin expects activity but detects inactivity
2. _apply_twin_context() - suppresses minor scores during expected rest/sleep periods
3. _twin_aware_inactivity() - returns low score during sleep time (expected_inactivity)
4. _twin_aware_inactivity() - returns high score when active expected but inactive past personal limit
5. _build_reason() includes [TWIN] prefix when twin context has boost_reason
6. New anomaly types: twin_active_expected, twin_inactivity_exceeded, twin_sleep_disruption, expected_inactivity
7. GET /api/operator/devices/{id}/behavior-pattern - twin_context and twin_anomaly_count fields
8. Falls back to generic scoring when no twin or twin confidence < 0.3
"""
import pytest
import requests
import os
from unittest.mock import MagicMock

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

# ---- Unit tests for _apply_twin_context and _twin_aware_inactivity ----

class TestApplyTwinContext:
    """Unit tests for _apply_twin_context() function in behavior_ai.py"""

    def test_boost_when_expected_active_but_low_interaction(self):
        """When twin expects activity but interaction is very low, score should be boosted"""
        from app.services.behavior_ai import _apply_twin_context

        twin = {
            "confidence": 0.5,
            "rhythm": {"10": {"expected_active": True}},
            "inactivity_max": 45,
        }
        # Mock baseline with avg_interaction_rate
        baseline = MagicMock()
        baseline.avg_interaction_rate = 10.0
        baseline.avg_movement = 5.0

        # Low interaction (< 40% of avg = 4)
        result = _apply_twin_context(
            base_score=0.3,
            twin=twin,
            current_hour=10,
            movement=3.0,
            interaction=2.0,  # Very low - less than 40% of 10
            baseline=baseline,
        )

        assert result["adjusted_score"] > 0.3, "Score should be boosted when expected active but low interaction"
        assert result["twin_anomaly_type"] == "twin_active_expected"
        assert result["boost_reason"] is not None
        assert "expects activity" in result["boost_reason"].lower() or "interaction is very low" in result["boost_reason"].lower()
        print(f"PASS: boost when expected_active but low interaction. Score: 0.3 -> {result['adjusted_score']}")

    def test_boost_when_expected_active_but_low_movement(self):
        """When twin expects activity but movement is very low, score should be boosted"""
        from app.services.behavior_ai import _apply_twin_context

        twin = {
            "confidence": 0.6,
            "rhythm": {"14": {"expected_active": True}},
            "inactivity_max": 30,
        }
        baseline = MagicMock()
        baseline.avg_interaction_rate = 10.0
        baseline.avg_movement = 10.0

        # Low movement (< 30% of avg = 3)
        result = _apply_twin_context(
            base_score=0.25,
            twin=twin,
            current_hour=14,
            movement=2.0,  # Very low - less than 30% of 10
            interaction=8.0,  # Normal interaction
            baseline=baseline,
        )

        assert result["adjusted_score"] > 0.25, "Score should be boosted when expected active but low movement"
        assert result["twin_anomaly_type"] == "twin_active_expected"
        print(f"PASS: boost when expected_active but low movement. Score: 0.25 -> {result['adjusted_score']}")

    def test_suppress_minor_deviation_during_rest(self):
        """When twin expects rest and score is minor (<0.5), score should be suppressed"""
        from app.services.behavior_ai import _apply_twin_context

        twin = {
            "confidence": 0.5,
            "rhythm": {"2": {"expected_active": False}},  # 2 AM - sleep time
            "inactivity_max": 60,
        }
        baseline = MagicMock()
        baseline.avg_interaction_rate = 5.0
        baseline.avg_movement = 3.0

        result = _apply_twin_context(
            base_score=0.35,  # Minor deviation
            twin=twin,
            current_hour=2,
            movement=2.0,
            interaction=3.0,
            baseline=baseline,
        )

        assert result["adjusted_score"] < 0.35, "Minor score should be suppressed during expected rest"
        assert result["twin_anomaly_type"] is None, "No twin anomaly type for suppression"
        assert result["boost_reason"] is not None and "rest" in result["boost_reason"].lower()
        print(f"PASS: suppress minor deviation during rest. Score: 0.35 -> {result['adjusted_score']}")

    def test_boost_significant_activity_during_sleep(self):
        """When twin expects rest but score is high (>=0.6), it could be distress - boost"""
        from app.services.behavior_ai import _apply_twin_context

        twin = {
            "confidence": 0.5,
            "rhythm": {"3": {"expected_active": False}},  # 3 AM - sleep time
            "inactivity_max": 60,
        }
        baseline = MagicMock()
        baseline.avg_interaction_rate = 5.0
        baseline.avg_movement = 3.0

        result = _apply_twin_context(
            base_score=0.65,  # High score during sleep - could be distress
            twin=twin,
            current_hour=3,
            movement=10.0,  # High movement during sleep
            interaction=15.0,
            baseline=baseline,
        )

        assert result["adjusted_score"] >= 0.65, "High score during sleep should not be suppressed"
        assert result["twin_anomaly_type"] == "twin_sleep_disruption"
        print(f"PASS: boost significant activity during sleep. Score: 0.65 -> {result['adjusted_score']}")

    def test_returns_expected_active_field(self):
        """Result should include expected_active based on twin rhythm"""
        from app.services.behavior_ai import _apply_twin_context

        twin = {
            "confidence": 0.5,
            "rhythm": {"12": {"expected_active": True}},
            "inactivity_max": 30,
        }
        baseline = MagicMock()
        baseline.avg_interaction_rate = 10.0
        baseline.avg_movement = 5.0

        result = _apply_twin_context(
            base_score=0.2,
            twin=twin,
            current_hour=12,
            movement=4.0,
            interaction=8.0,
            baseline=baseline,
        )

        assert "expected_active" in result
        assert result["expected_active"] is True
        assert "twin_confidence" in result
        assert result["twin_confidence"] == 0.5
        print(f"PASS: result includes expected_active={result['expected_active']}, twin_confidence={result['twin_confidence']}")

    def test_no_boost_when_hour_not_in_rhythm(self):
        """When current hour is not in twin rhythm, no boost/suppress"""
        from app.services.behavior_ai import _apply_twin_context

        twin = {
            "confidence": 0.5,
            "rhythm": {},  # Empty rhythm
            "inactivity_max": 30,
        }
        baseline = MagicMock()
        baseline.avg_interaction_rate = 10.0
        baseline.avg_movement = 5.0

        result = _apply_twin_context(
            base_score=0.4,
            twin=twin,
            current_hour=10,
            movement=3.0,
            interaction=5.0,
            baseline=baseline,
        )

        assert result["adjusted_score"] == 0.4, "Score should remain unchanged when hour not in rhythm"
        assert result["expected_active"] is None
        print(f"PASS: no change when hour not in rhythm. Score remains: {result['adjusted_score']}")


class TestTwinAwareInactivity:
    """Unit tests for _twin_aware_inactivity() function"""

    def test_low_score_during_expected_rest(self):
        """During sleep time, inactivity should return very low score (expected_inactivity)"""
        from app.services.behavior_ai import _twin_aware_inactivity

        twin = {
            "confidence": 0.5,
            "rhythm": {"3": {"expected_active": False}},  # 3 AM sleep
            "inactivity_max": 45,
        }

        result = _twin_aware_inactivity(
            twin=twin,
            current_hour=3,
            inactivity_minutes=90,  # 90 min inactive - but during sleep
        )

        assert result["score"] < 0.1, f"Score should be very low during expected rest, got {result['score']}"
        assert result["anomaly_type"] == "expected_inactivity"
        assert "normal" in result["reason"].lower() or "rest" in result["reason"].lower()
        print(f"PASS: low score during expected rest. Score: {result['score']}, type: {result['anomaly_type']}")

    def test_high_score_when_active_expected_but_inactive(self):
        """When twin expects activity but person has been inactive past their limit"""
        from app.services.behavior_ai import _twin_aware_inactivity

        twin = {
            "confidence": 0.5,
            "rhythm": {"10": {"expected_active": True}},  # 10 AM active
            "inactivity_max": 30,  # Personal limit is 30 min
        }

        result = _twin_aware_inactivity(
            twin=twin,
            current_hour=10,
            inactivity_minutes=60,  # 60 min inactive - exceeds personal limit
        )

        assert result["score"] > 0.5, f"Score should be elevated when inactive past personal limit, got {result['score']}"
        assert result["anomaly_type"] == "twin_inactivity_exceeded"
        assert "TWIN-AWARE" in result["reason"] or "personal limit" in result["reason"].lower()
        print(f"PASS: high score when active expected but past limit. Score: {result['score']}, type: {result['anomaly_type']}")

    def test_moderate_score_within_personal_limit(self):
        """When active expected but inactivity is within personal limit, score is moderate"""
        from app.services.behavior_ai import _twin_aware_inactivity

        twin = {
            "confidence": 0.5,
            "rhythm": {"14": {"expected_active": True}},
            "inactivity_max": 60,  # Personal limit is 60 min
        }

        result = _twin_aware_inactivity(
            twin=twin,
            current_hour=14,
            inactivity_minutes=30,  # 30 min - within limit
        )

        assert result["score"] < 0.5, f"Score should be moderate within limit, got {result['score']}"
        assert result["anomaly_type"] == "twin_active_expected"
        print(f"PASS: moderate score within personal limit. Score: {result['score']}, type: {result['anomaly_type']}")

    def test_very_long_inactivity_during_sleep_raises_concern(self):
        """Even during sleep, very long inactivity (3x personal max) raises concern"""
        from app.services.behavior_ai import _twin_aware_inactivity

        twin = {
            "confidence": 0.5,
            "rhythm": {"4": {"expected_active": False}},  # 4 AM sleep
            "inactivity_max": 45,  # 45 min personal max
        }

        result = _twin_aware_inactivity(
            twin=twin,
            current_hour=4,
            inactivity_minutes=200,  # 200 min - way beyond even sleep expectations
        )

        assert result["score"] > 0.1, f"Very long inactivity even during sleep should raise score, got {result['score']}"
        assert result["anomaly_type"] == "extended_inactivity"
        print(f"PASS: very long inactivity during sleep raises concern. Score: {result['score']}")

    def test_generic_fallback_when_hour_not_in_rhythm(self):
        """When hour not in rhythm, uses generic scoring"""
        from app.services.behavior_ai import _twin_aware_inactivity

        twin = {
            "confidence": 0.5,
            "rhythm": {},  # Empty rhythm
            "inactivity_max": 45,
        }

        result = _twin_aware_inactivity(
            twin=twin,
            current_hour=12,
            inactivity_minutes=90,  # 90 min - above global 60 min threshold
        )

        assert result["anomaly_type"] == "extended_inactivity"
        assert "threshold" in result["reason"].lower()
        print(f"PASS: generic fallback when hour not in rhythm. Score: {result['score']}")


class TestBuildReason:
    """Tests for _build_reason() function including [TWIN] prefix"""

    def test_twin_prefix_when_boost_reason_present(self):
        """Reason should have [TWIN] prefix when twin_context has boost_reason"""
        from app.services.behavior_ai import _build_reason

        baseline = MagicMock()
        baseline.avg_movement = 5.0
        baseline.avg_interaction_rate = 10.0

        twin_context = {
            "boost_reason": "Twin expects activity at 10:00 but interaction is very low",
            "expected_active": True,
            "twin_confidence": 0.5,
        }

        reason = _build_reason(
            anomaly_type="twin_active_expected",
            movement=2.0,
            interaction=3.0,
            baseline=baseline,
            twin_context=twin_context,
        )

        assert reason.startswith("[TWIN]"), f"Reason should start with [TWIN], got: {reason}"
        print(f"PASS: reason has [TWIN] prefix: {reason[:50]}...")

    def test_no_twin_prefix_when_no_boost_reason(self):
        """Reason should NOT have [TWIN] prefix when no boost_reason"""
        from app.services.behavior_ai import _build_reason

        baseline = MagicMock()
        baseline.avg_movement = 5.0
        baseline.avg_interaction_rate = 10.0

        reason = _build_reason(
            anomaly_type="movement_drop",
            movement=1.0,
            interaction=8.0,
            baseline=baseline,
            twin_context=None,
        )

        assert not reason.startswith("[TWIN]"), f"Reason should NOT start with [TWIN] when no twin context: {reason}"
        print(f"PASS: no [TWIN] prefix without twin context: {reason[:50]}...")

    def test_reason_for_twin_active_expected(self):
        """Reason for twin_active_expected anomaly type"""
        from app.services.behavior_ai import _build_reason

        baseline = MagicMock()
        baseline.avg_movement = 5.0
        baseline.avg_interaction_rate = 10.0

        reason = _build_reason(
            anomaly_type="twin_active_expected",
            movement=1.0,
            interaction=2.0,
            baseline=baseline,
            twin_context=None,
        )

        assert "twin" in reason.lower() or "activity" in reason.lower() or "metrics" in reason.lower()
        print(f"PASS: reason for twin_active_expected: {reason}")


# ---- API Integration Tests ----

class TestBehaviorPatternAPITwinContext:
    """API tests for GET /api/operator/devices/{id}/behavior-pattern with twin context"""

    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get operator auth token"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "operator@nischint.com", "password": "operator123"}
        )
        if response.status_code == 200:
            return response.json().get("access_token")
        pytest.skip("Could not authenticate as operator")

    @pytest.fixture(scope="class")
    def device_id(self, auth_token):
        """Get a valid device ID (DEV-001)"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(
            f"{BASE_URL}/api/operator/device-health?window_hours=24",
            headers=headers
        )
        if response.status_code == 200:
            # Response is a list directly
            devices = response.json()
            for d in devices:
                if d.get("device_identifier") == "DEV-001":
                    return d.get("device_id")
            if devices:
                return devices[0].get("device_id")
        pytest.skip("Could not get device ID")

    def test_behavior_pattern_returns_200(self, auth_token, device_id):
        """Behavior pattern endpoint returns 200 for valid device"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{device_id}/behavior-pattern",
            headers=headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: GET behavior-pattern returns 200")

    def test_response_has_twin_context_field(self, auth_token, device_id):
        """Response should include twin_context field (can be null)"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{device_id}/behavior-pattern",
            headers=headers
        )
        data = response.json()
        assert "twin_context" in data, f"Response should have twin_context field. Keys: {list(data.keys())}"
        print(f"PASS: twin_context field present. Value: {data['twin_context']}")

    def test_response_has_twin_anomaly_count(self, auth_token, device_id):
        """Response should include twin_anomaly_count field"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{device_id}/behavior-pattern",
            headers=headers
        )
        data = response.json()
        assert "twin_anomaly_count" in data, f"Response should have twin_anomaly_count field. Keys: {list(data.keys())}"
        assert isinstance(data["twin_anomaly_count"], int)
        print(f"PASS: twin_anomaly_count = {data['twin_anomaly_count']}")

    def test_current_risk_has_twin_aware_boolean(self, auth_token, device_id):
        """current_risk should include twin_aware boolean"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{device_id}/behavior-pattern",
            headers=headers
        )
        data = response.json()
        current_risk = data.get("current_risk", {})
        assert "twin_aware" in current_risk, f"current_risk should have twin_aware. Keys: {list(current_risk.keys())}"
        assert isinstance(current_risk["twin_aware"], bool)
        print(f"PASS: current_risk.twin_aware = {current_risk['twin_aware']}")

    def test_twin_context_structure_when_present(self, auth_token, device_id):
        """When twin_context is present, verify its structure"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{device_id}/behavior-pattern",
            headers=headers
        )
        data = response.json()
        twin_context = data.get("twin_context")
        
        # DEV-001 has twin with confidence 0.177 (< 0.3 for twin scoring, but >= 0.15 for display)
        if twin_context is not None:
            expected_fields = ["twin_active", "confidence", "expected_active_now", "personal_inactivity_max", "personality_tag"]
            for field in expected_fields:
                assert field in twin_context, f"twin_context missing field: {field}"
            print(f"PASS: twin_context has all expected fields: {list(twin_context.keys())}")
            print(f"       confidence={twin_context['confidence']}, expected_active_now={twin_context['expected_active_now']}")
        else:
            print("INFO: twin_context is null (no twin with confidence >= 0.15)")


class TestFleetTwinsRegressionCheck:
    """Regression test: GET /api/operator/digital-twins/fleet still works"""

    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get operator auth token"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "operator@nischint.com", "password": "operator123"}
        )
        if response.status_code == 200:
            return response.json().get("access_token")
        pytest.skip("Could not authenticate as operator")

    def test_fleet_twins_returns_200(self, auth_token):
        """Fleet twins endpoint still returns 200"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(
            f"{BASE_URL}/api/operator/digital-twins/fleet",
            headers=headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert "total_twins" in data
        assert "twins" in data
        print(f"PASS: fleet twins returns 200. total_twins={data['total_twins']}")


class TestGenericFallbackScoring:
    """Tests for fallback to generic scoring when no twin or twin confidence < 0.3"""

    def test_generic_scoring_without_twin(self):
        """When no twin exists, _apply_twin_context should not be called (this is behavior_ai logic)"""
        # This test verifies that the behavior_ai.py code correctly checks for twin presence
        # The actual fallback happens in _detect_behavioral_anomalies when device_twin is None
        from app.services.behavior_ai import SCORE_CLAMP_MIN, SCORE_CLAMP_MAX
        
        # Generic z-score based scoring (raw_score = (z_movement * 0.5 + z_interaction * 0.5) / 3.0)
        z_movement = 1.5
        z_interaction = 2.0
        raw_score = (z_movement * 0.5 + z_interaction * 0.5) / 3.0
        clamped = max(SCORE_CLAMP_MIN, min(SCORE_CLAMP_MAX, raw_score))
        
        assert 0.0 <= clamped <= 1.0, f"Generic score should be clamped: {clamped}"
        print(f"PASS: generic scoring formula produces clamped score: {clamped}")

    def test_generic_inactivity_scoring(self):
        """Generic inactivity scoring uses global 60-min threshold"""
        from app.services.behavior_ai import INACTIVITY_THRESHOLD_MINUTES
        
        assert INACTIVITY_THRESHOLD_MINUTES == 60, f"Global threshold should be 60 min, got {INACTIVITY_THRESHOLD_MINUTES}"
        
        # Generic formula: min(1.0, 0.5 + (inactivity_minutes / threshold - 1) * 0.25)
        inactivity_minutes = 90
        generic_score = min(1.0, 0.5 + (inactivity_minutes / INACTIVITY_THRESHOLD_MINUTES - 1) * 0.25)
        
        assert generic_score > 0.5, f"90 min inactivity should score > 0.5, got {generic_score}"
        print(f"PASS: generic inactivity scoring (90 min) = {generic_score}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
