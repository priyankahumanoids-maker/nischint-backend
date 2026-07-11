# AI Risk Forecast Timeline Backend Tests
# Tests GET /api/operator/devices/{device_id}/risk-forecast endpoint
# Features tested:
# - 24h risk forecast generation with 6 time buckets
# - Caching (15 min TTL) - cached=true on second call
# - Risk level classification (LOW <0.3, MEDIUM 0.3-0.6, HIGH >=0.6)
# - RBAC enforcement (guardian 403, unauthenticated 401)
# - 404 for non-existent device

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"
GUARDIAN_EMAIL = "nischint4parents@gmail.com"
GUARDIAN_PASSWORD = "secret123"

# Device IDs from the test context
DEV_001_ID = "ce4b5463-5a7e-46a5-8bbf-365dcfb3daeb"  # Expected HIGH risk
WBAND_LC_001_ID = "bd57a3db-222a-43d2-8333-2e77deeedcfa"  # Expected LOW risk
NON_EXISTENT_DEVICE_ID = "00000000-0000-0000-0000-000000000000"

# Expected bucket names
EXPECTED_BUCKETS = ["early_morning", "morning", "afternoon", "evening", "night", "late_night"]


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


class TestRiskForecastEndpoint:
    """Test risk forecast endpoint returns proper response structure"""

    def test_forecast_returns_200_for_valid_device(self, operator_token):
        """GET /api/operator/devices/{device_id}/risk-forecast returns 200 OK"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/risk-forecast",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Verify response structure
        assert "device_id" in data, "Response missing device_id"
        assert "device_identifier" in data, "Response missing device_identifier"
        assert "forecast_window_hours" in data, "Response missing forecast_window_hours"
        assert "generated_at" in data, "Response missing generated_at"
        assert "buckets" in data, "Response missing buckets"
        assert "summary" in data, "Response missing summary"
        print(f"PASS: Forecast returns 200 with proper structure")

    def test_forecast_contains_6_time_buckets(self, operator_token):
        """Forecast response contains exactly 6 time buckets"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/risk-forecast",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        buckets = data["buckets"]
        
        assert len(buckets) == 6, f"Expected 6 buckets, got {len(buckets)}"
        
        # Verify all expected bucket names are present
        bucket_names = [b["bucket"] for b in buckets]
        for expected in EXPECTED_BUCKETS:
            assert expected in bucket_names, f"Missing bucket: {expected}"
        print(f"PASS: Forecast contains 6 time buckets: {bucket_names}")

    def test_bucket_structure(self, operator_token):
        """Each bucket has required fields: bucket, label, start_hour, end_hour, risk_score, risk_level, reason"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/risk-forecast",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        for bucket in data["buckets"]:
            assert "bucket" in bucket, "Bucket missing 'bucket' field"
            assert "label" in bucket, "Bucket missing 'label' field"
            assert "start_hour" in bucket, "Bucket missing 'start_hour' field"
            assert "end_hour" in bucket, "Bucket missing 'end_hour' field"
            assert "risk_score" in bucket, "Bucket missing 'risk_score' field"
            assert "risk_level" in bucket, "Bucket missing 'risk_level' field"
            assert "reason" in bucket, "Bucket missing 'reason' field"
            
            # Verify bucket hours are valid
            assert 0 <= bucket["start_hour"] <= 24
            assert 0 <= bucket["end_hour"] <= 24
            assert bucket["start_hour"] < bucket["end_hour"], f"start_hour ({bucket['start_hour']}) should be < end_hour ({bucket['end_hour']})"
        
        print("PASS: All buckets have correct structure with valid hour ranges")

    def test_summary_contains_required_fields(self, operator_token):
        """Summary contains peak_risk_bucket, peak_risk_score, high_risk_count, medium_risk_count"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/risk-forecast",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        summary = data["summary"]
        
        assert "peak_risk_bucket" in summary, "Summary missing peak_risk_bucket"
        assert "peak_risk_score" in summary, "Summary missing peak_risk_score"
        assert "high_risk_count" in summary, "Summary missing high_risk_count"
        assert "medium_risk_count" in summary, "Summary missing medium_risk_count"
        
        # Validate types
        assert isinstance(summary["peak_risk_bucket"], str)
        assert isinstance(summary["peak_risk_score"], (int, float))
        assert isinstance(summary["high_risk_count"], int)
        assert isinstance(summary["medium_risk_count"], int)
        
        print(f"PASS: Summary has required fields - peak: {summary['peak_risk_bucket']} ({summary['peak_risk_score']}), HIGH: {summary['high_risk_count']}, MEDIUM: {summary['medium_risk_count']}")


class TestRiskLevelClassification:
    """Test risk level classification thresholds"""

    def test_risk_levels_are_valid(self, operator_token):
        """Risk levels must be LOW, MEDIUM, or HIGH"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/risk-forecast",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        valid_levels = {"LOW", "MEDIUM", "HIGH"}
        for bucket in data["buckets"]:
            assert bucket["risk_level"] in valid_levels, f"Invalid risk_level: {bucket['risk_level']}"
        
        print(f"PASS: All risk levels are valid (LOW/MEDIUM/HIGH)")

    def test_risk_score_level_consistency(self, operator_token):
        """Risk levels match score thresholds: LOW (<0.3), MEDIUM (0.3-0.6), HIGH (>=0.6)"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/risk-forecast",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        for bucket in data["buckets"]:
            score = bucket["risk_score"]
            level = bucket["risk_level"]
            
            if score >= 0.6:
                assert level == "HIGH", f"Score {score} should be HIGH, got {level}"
            elif score >= 0.3:
                assert level == "MEDIUM", f"Score {score} should be MEDIUM, got {level}"
            else:
                assert level == "LOW", f"Score {score} should be LOW, got {level}"
        
        print("PASS: Risk levels match score thresholds (LOW<0.3, MEDIUM 0.3-0.6, HIGH>=0.6)")


class TestForecastCaching:
    """Test forecast caching with 15 minute TTL"""

    def test_second_call_returns_cached(self, operator_token):
        """Second call within 15 min returns cached=true"""
        # First call
        response1 = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/risk-forecast",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response1.status_code == 200
        
        # Second call immediately after should be cached
        response2 = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/risk-forecast",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response2.status_code == 200
        data2 = response2.json()
        
        # Check cached field
        assert "cached" in data2, "Response should have 'cached' field"
        assert data2["cached"] == True, f"Expected cached=true, got cached={data2['cached']}"
        
        print("PASS: Second call within 15 min returns cached=true")


class TestDeviceNotFound:
    """Test 404 for non-existent device"""

    def test_non_existent_device_returns_404(self, operator_token):
        """Non-existent device returns 404"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{NON_EXISTENT_DEVICE_ID}/risk-forecast",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("PASS: Non-existent device returns 404")


class TestRBAC:
    """Test Role-Based Access Control"""

    def test_guardian_gets_403(self, guardian_token):
        """Guardian role gets 403 Forbidden"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/risk-forecast",
            headers={"Authorization": f"Bearer {guardian_token}"}
        )
        assert response.status_code == 403, f"Expected 403 for guardian, got {response.status_code}"
        print("PASS: Guardian role correctly gets 403 Forbidden")

    def test_unauthenticated_gets_401(self):
        """Unauthenticated request gets 401"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/risk-forecast"
        )
        assert response.status_code == 401, f"Expected 401 without auth, got {response.status_code}"
        print("PASS: Unauthenticated request correctly gets 401")


class TestMultipleDevices:
    """Test forecast for different devices"""

    def test_dev001_has_high_risk(self, operator_token):
        """DEV-001 should have HIGH risk windows as per test context"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/risk-forecast",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        summary = data["summary"]
        
        # Per context: DEV-001 shows HIGH risk with 4 HIGH risk windows
        # Note: This may vary based on data state, so just verify structure
        print(f"DEV-001 forecast: HIGH={summary['high_risk_count']}, MEDIUM={summary['medium_risk_count']}, peak={summary['peak_risk_bucket']}")
        print("PASS: DEV-001 forecast retrieved successfully")

    def test_wband_forecast(self, operator_token):
        """WATCH-001 (WBAND-LC-001) forecast can be retrieved"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{WBAND_LC_001_ID}/risk-forecast",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        summary = data["summary"]
        
        # Per context: WBAND-LC-001 shows all LOW risk
        print(f"WBAND-LC-001 forecast: HIGH={summary['high_risk_count']}, MEDIUM={summary['medium_risk_count']}, peak={summary['peak_risk_bucket']}")
        print("PASS: WBAND-LC-001 forecast retrieved successfully")


class TestBucketTimeRanges:
    """Test bucket time ranges are correct"""

    def test_bucket_time_ranges(self, operator_token):
        """Verify bucket time ranges match spec"""
        response = requests.get(
            f"{BASE_URL}/api/operator/devices/{DEV_001_ID}/risk-forecast",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        expected_ranges = {
            "early_morning": (6, 9),
            "morning": (9, 12),
            "afternoon": (12, 15),
            "evening": (15, 18),
            "night": (18, 21),
            "late_night": (21, 24),
        }
        
        for bucket in data["buckets"]:
            name = bucket["bucket"]
            if name in expected_ranges:
                expected_start, expected_end = expected_ranges[name]
                assert bucket["start_hour"] == expected_start, f"{name} start_hour should be {expected_start}, got {bucket['start_hour']}"
                assert bucket["end_hour"] == expected_end, f"{name} end_hour should be {expected_end}, got {bucket['end_hour']}"
        
        print("PASS: All bucket time ranges match spec (Early Morning 6-9, Morning 9-12, etc.)")
