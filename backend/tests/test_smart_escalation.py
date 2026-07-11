"""
Smart Escalation Engine Tests
Tests for adaptive escalation timers that learn from guardian response history.
Features: smart-profile, smart-recommendation APIs, skip_l1 logic, adaptive timers
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL')

# Test credentials
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"

# Test data from context
GUARDIAN_ID = "7437a394-74ef-46a2-864f-6add0e7e8e60"
TEST_INCIDENT_ID = "23b02397-f738-448f-8492-d7f82c6bc38e"  # is_test=true
NON_TEST_INCIDENT_ID = "3c3a9bae-4332-40fa-a0d0-1072d7125a85"  # device_offline, medium


@pytest.fixture(scope="module")
def operator_token():
    """Get operator auth token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": OPERATOR_EMAIL,
        "password": OPERATOR_PASSWORD
    })
    if response.status_code == 200:
        return response.json().get("access_token")
    pytest.skip(f"Operator login failed: {response.status_code}")


@pytest.fixture
def auth_headers(operator_token):
    """Auth headers for requests"""
    return {"Authorization": f"Bearer {operator_token}"}


class TestSmartGuardianProfile:
    """Tests for GET /api/operator/escalation/smart-profile/{guardian_id}"""

    def test_smart_profile_returns_200(self, auth_headers):
        """Smart profile endpoint returns 200 for valid guardian"""
        response = requests.get(
            f"{BASE_URL}/api/operator/escalation/smart-profile/{GUARDIAN_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    def test_smart_profile_structure(self, auth_headers):
        """Smart profile contains all required fields"""
        response = requests.get(
            f"{BASE_URL}/api/operator/escalation/smart-profile/{GUARDIAN_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        # Required fields
        assert "guardian_id" in data
        assert "total_incidents" in data
        assert "acknowledged_count" in data
        assert "response_rate" in data
        assert "avg_response_minutes" in data
        assert "response_by_time_of_day" in data
        assert "response_by_severity" in data
        assert "reliability_score" in data
        assert "recommendation" in data
        assert "has_sufficient_data" in data

    def test_smart_profile_tod_stats(self, auth_headers):
        """Smart profile has time-of-day breakdown"""
        response = requests.get(
            f"{BASE_URL}/api/operator/escalation/smart-profile/{GUARDIAN_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        tod = data.get("response_by_time_of_day", {})
        expected_buckets = ["night", "morning", "afternoon", "evening"]
        for bucket in expected_buckets:
            assert bucket in tod, f"Missing time bucket: {bucket}"
            assert "count" in tod[bucket]
            assert "acknowledged" in tod[bucket]
            assert "rate" in tod[bucket]
            assert "avg_minutes" in tod[bucket]

    def test_smart_profile_severity_stats(self, auth_headers):
        """Smart profile has severity breakdown"""
        response = requests.get(
            f"{BASE_URL}/api/operator/escalation/smart-profile/{GUARDIAN_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        sev = data.get("response_by_severity", {})
        expected_sevs = ["critical", "high", "medium", "low"]
        for s in expected_sevs:
            assert s in sev, f"Missing severity: {s}"
            assert "count" in sev[s]
            assert "acknowledged" in sev[s]
            assert "rate" in sev[s]
            assert "avg_minutes" in sev[s]

    def test_smart_profile_low_reliability_guardian(self, auth_headers):
        """Guardian with <30% response rate gets skip_l1 recommendation"""
        response = requests.get(
            f"{BASE_URL}/api/operator/escalation/smart-profile/{GUARDIAN_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        # Based on context: guardian has 6% response rate, 26/100 reliability
        # Should have skip_l1 recommendation
        response_rate = data.get("response_rate", 0)
        recommendation = data.get("recommendation", "")
        
        if response_rate < 0.30 and data.get("has_sufficient_data", False):
            assert recommendation == "skip_l1", f"Expected skip_l1 for {response_rate*100:.0f}% rate, got {recommendation}"
        
        print(f"Guardian profile: response_rate={response_rate*100:.1f}%, recommendation={recommendation}, reliability={data.get('reliability_score')}")

    def test_smart_profile_empty_for_nonexistent(self, auth_headers):
        """Non-existent guardian returns empty profile"""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = requests.get(
            f"{BASE_URL}/api/operator/escalation/smart-profile/{fake_id}",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("total_incidents", 0) == 0
        assert data.get("has_sufficient_data", True) == False

    def test_smart_profile_requires_auth(self):
        """Smart profile endpoint requires authentication"""
        response = requests.get(
            f"{BASE_URL}/api/operator/escalation/smart-profile/{GUARDIAN_ID}"
        )
        assert response.status_code == 401


class TestSmartRecommendation:
    """Tests for GET /api/operator/escalation/smart-recommendation/{incident_id}"""

    def test_smart_rec_test_incident(self, auth_headers):
        """Test incident returns mode=test with fast timers"""
        response = requests.get(
            f"{BASE_URL}/api/operator/escalation/smart-recommendation/{TEST_INCIDENT_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("mode") == "test", f"Expected mode=test, got {data.get('mode')}"
        assert data.get("timers", {}).get("l1") == 1
        assert data.get("timers", {}).get("l2") == 2
        assert data.get("timers", {}).get("l3") == 3
        assert data.get("skip_l1") == False
        print(f"Test incident recommendation: mode={data.get('mode')}, timers={data.get('timers')}")

    def test_smart_rec_non_test_incident(self, auth_headers):
        """Non-test incident returns mode=adaptive with computed timers"""
        response = requests.get(
            f"{BASE_URL}/api/operator/escalation/smart-recommendation/{NON_TEST_INCIDENT_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("mode") == "adaptive", f"Expected mode=adaptive, got {data.get('mode')}"
        
        # Check structure
        assert "timers" in data
        assert "static_timers" in data
        assert "factors" in data
        assert "skip_l1" in data
        assert "guardian_profile_summary" in data
        assert "reasons" in data
        
        print(f"Non-test incident: mode={data.get('mode')}, timers={data.get('timers')}, skip_l1={data.get('skip_l1')}")

    def test_smart_rec_factors_structure(self, auth_headers):
        """Smart recommendation has proper factors structure"""
        response = requests.get(
            f"{BASE_URL}/api/operator/escalation/smart-recommendation/{NON_TEST_INCIDENT_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        factors = data.get("factors", {})
        assert "time_of_day" in factors
        assert "severity" in factors
        assert "guardian" in factors
        assert "combined" in factors
        
        # Time-of-day factor
        tod = factors.get("time_of_day", {})
        assert "bucket" in tod
        assert "factor" in tod
        assert tod["bucket"] in ["night", "morning", "afternoon", "evening"]
        
        # Severity factor
        sev = factors.get("severity", {})
        assert "level" in sev
        assert "factor" in sev

    def test_smart_rec_guardian_profile_summary(self, auth_headers):
        """Smart recommendation includes guardian profile summary"""
        response = requests.get(
            f"{BASE_URL}/api/operator/escalation/smart-recommendation/{NON_TEST_INCIDENT_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        profile = data.get("guardian_profile_summary", {})
        assert "response_rate" in profile
        assert "avg_response_minutes" in profile
        assert "reliability_score" in profile
        assert "recommendation" in profile

    def test_smart_rec_skip_l1_for_unreliable_guardian(self, auth_headers):
        """Unreliable guardian gets skip_l1=true"""
        response = requests.get(
            f"{BASE_URL}/api/operator/escalation/smart-recommendation/{NON_TEST_INCIDENT_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        profile = data.get("guardian_profile_summary", {})
        skip_l1 = data.get("skip_l1", False)
        
        # If guardian response rate < 30%, skip_l1 should be true
        if profile.get("response_rate", 1) < 0.30:
            assert skip_l1 == True, f"Expected skip_l1=True for response rate {profile.get('response_rate')*100:.0f}%"
            
            # L1 timer should be 0 when skipping
            timers = data.get("timers", {})
            assert timers.get("l1") == 0, f"Expected L1=0 when skip_l1, got {timers.get('l1')}"
            
        print(f"Guardian reliability check: response_rate={profile.get('response_rate', 0)*100:.1f}%, skip_l1={skip_l1}")

    def test_smart_rec_nonexistent_incident(self, auth_headers):
        """Non-existent incident returns 404"""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = requests.get(
            f"{BASE_URL}/api/operator/escalation/smart-recommendation/{fake_id}",
            headers=auth_headers
        )
        assert response.status_code == 404

    def test_smart_rec_requires_auth(self):
        """Smart recommendation requires authentication"""
        response = requests.get(
            f"{BASE_URL}/api/operator/escalation/smart-recommendation/{NON_TEST_INCIDENT_ID}"
        )
        assert response.status_code == 401


class TestEscalationSchedulerIntegration:
    """Tests to verify escalation scheduler uses smart thresholds (via code review)"""

    def test_scheduler_has_smart_thresholds_function(self):
        """Verify escalation scheduler source has _get_smart_thresholds function"""
        with open("/app/backend/app/services/escalation_scheduler.py") as f:
            content = f.read()
        
        assert "async def _get_smart_thresholds" in content, "Missing _get_smart_thresholds in scheduler"
        assert "def _get_thresholds" in content, "Missing _get_thresholds (static fallback)"
        assert "get_adaptive_thresholds" in content, "Scheduler should import get_adaptive_thresholds"

    def test_smart_engine_factors_in_source(self):
        """Verify smart engine source has correct factors defined"""
        with open("/app/backend/app/services/smart_escalation_engine.py") as f:
            content = f.read()
        
        # Time-of-day factors
        assert 'TOD_NIGHT: 0.6' in content, "Night factor should be 0.6"
        assert 'TOD_MORNING: 0.85' in content, "Morning factor should be 0.85"
        assert 'TOD_AFTERNOON: 1.0' in content, "Afternoon factor should be 1.0"
        assert 'TOD_EVENING: 0.9' in content, "Evening factor should be 0.9"
        
        # Severity factors
        assert '"critical": 0.65' in content, "Critical factor should be 0.65"
        assert '"high": 0.8' in content
        assert '"medium": 1.0' in content
        assert '"low": 1.3' in content
        
        # Skip L1 threshold
        assert "SKIP_L1_RESPONSE_RATE = 0.30" in content, "Skip L1 threshold should be 0.30"
        assert "MIN_TIMER_MINUTES = 1" in content


class TestAdaptiveTimerCalculation:
    """Tests for adaptive timer computation logic"""

    def test_adaptive_timers_within_bounds(self, auth_headers):
        """Adaptive timers should respect MIN_TIMER_MINUTES floor"""
        response = requests.get(
            f"{BASE_URL}/api/operator/escalation/smart-recommendation/{NON_TEST_INCIDENT_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        timers = data.get("timers", {})
        skip_l1 = data.get("skip_l1", False)
        
        # L1 can be 0 if skip_l1
        if not skip_l1:
            assert timers.get("l1", 0) >= 1, "L1 timer must be >= 1 min (MIN_TIMER_MINUTES)"
        
        # L2 and L3 should always be above floor
        assert timers.get("l2", 0) >= 2, "L2 timer must be >= 2 min"
        assert timers.get("l3", 0) >= 3, "L3 timer must be >= 3 min"

    def test_static_timers_baseline(self, auth_headers):
        """Static timers should match config (L1=5, L2=10, L3=15)"""
        response = requests.get(
            f"{BASE_URL}/api/operator/escalation/smart-recommendation/{NON_TEST_INCIDENT_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        static = data.get("static_timers", {})
        # From config/context: L1=5min, L2=10min, L3=15min
        assert static.get("l1") == 5, f"Expected static L1=5, got {static.get('l1')}"
        assert static.get("l2") == 10, f"Expected static L2=10, got {static.get('l2')}"
        assert static.get("l3") == 15, f"Expected static L3=15, got {static.get('l3')}"

    def test_reasons_array_populated(self, auth_headers):
        """Reasons array should explain timer adjustments"""
        response = requests.get(
            f"{BASE_URL}/api/operator/escalation/smart-recommendation/{NON_TEST_INCIDENT_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        reasons = data.get("reasons", [])
        # Should have at least one reason if factors != 1.0
        factors = data.get("factors", {})
        combined = factors.get("combined", 1.0)
        
        if combined != 1.0:
            assert len(reasons) > 0, "Expected reasons when combined factor != 1.0"
        
        print(f"Reasons: {reasons}")
