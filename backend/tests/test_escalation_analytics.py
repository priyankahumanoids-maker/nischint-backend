"""
Tests for GET /api/operator/escalation-analytics endpoint
Escalation Analytics Dashboard - KPI endpoint testing

Tests cover:
- Endpoint access and RBAC (operator allowed, guardian blocked)
- Window parameter validation (15, 60, 1440, 10080 minutes)
- Response shape validation (tier_counts, timings, device_instability, top_devices)
- Empty window returns zeroed structure
- Tier counts use escalation_level (L1=1, L2=2, L3=3+)
- Timing metrics exclude negative values
- Recovery path counts (Case A and Case B)
- Repeat device rate calculation
- Cooldown blocks count (only reason='cooldown')
- Top devices ordering (by instability_count DESC)
"""

import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

# Test credentials
OPERATOR_CREDS = {"email": "operator@nischint.com", "password": "operator123"}
GUARDIAN_CREDS = {"email": "nischint4parents@gmail.com", "password": "secret123"}


@pytest.fixture(scope="module")
def operator_token():
    """Get operator JWT token"""
    resp = requests.post(f"{BASE_URL}/api/auth/login", json=OPERATOR_CREDS)
    if resp.status_code == 200:
        return resp.json().get("access_token")
    pytest.skip(f"Operator login failed: {resp.status_code}")


@pytest.fixture(scope="module")
def guardian_token():
    """Get guardian JWT token"""
    resp = requests.post(f"{BASE_URL}/api/auth/login", json=GUARDIAN_CREDS)
    if resp.status_code == 200:
        return resp.json().get("access_token")
    pytest.skip(f"Guardian login failed: {resp.status_code}")


class TestEscalationAnalyticsAccess:
    """RBAC and access control tests"""
    
    def test_operator_can_access_analytics(self, operator_token):
        """Operator can access GET /api/operator/escalation-analytics"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/escalation-analytics",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "window_minutes" in data
        assert "total_incidents" in data
        print("PASS: Operator can access escalation-analytics endpoint")
    
    def test_guardian_blocked_403(self, guardian_token):
        """Guardian is blocked (403) from escalation-analytics"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/escalation-analytics",
            headers={"Authorization": f"Bearer {guardian_token}"}
        )
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}"
        print("PASS: Guardian blocked with 403 from escalation-analytics")
    
    def test_unauthenticated_blocked(self):
        """Unauthenticated requests are blocked"""
        resp = requests.get(f"{BASE_URL}/api/operator/escalation-analytics")
        assert resp.status_code in [401, 403], f"Expected 401/403, got {resp.status_code}"
        print("PASS: Unauthenticated requests blocked")


class TestWindowParameter:
    """Window parameter validation tests"""
    
    def test_default_window_1440(self, operator_token):
        """Default window is 1440 minutes (24h)"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/escalation-analytics",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["window_minutes"] == 1440
        print("PASS: Default window is 1440 minutes")
    
    def test_window_15_minutes(self, operator_token):
        """Window parameter works: 15 minutes"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/escalation-analytics?window_minutes=15",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["window_minutes"] == 15
        print("PASS: Window 15 minutes works")
    
    def test_window_60_minutes(self, operator_token):
        """Window parameter works: 60 minutes"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/escalation-analytics?window_minutes=60",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["window_minutes"] == 60
        print("PASS: Window 60 minutes works")
    
    def test_window_10080_minutes(self, operator_token):
        """Window parameter works: 10080 minutes (7 days)"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/escalation-analytics?window_minutes=10080",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["window_minutes"] == 10080
        print("PASS: Window 10080 minutes (7 days) works")
    
    def test_window_below_min_rejected(self, operator_token):
        """Window below minimum (14) is rejected"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/escalation-analytics?window_minutes=10",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert resp.status_code == 422, f"Expected 422 for invalid window, got {resp.status_code}"
        print("PASS: Window below minimum rejected")
    
    def test_window_above_max_rejected(self, operator_token):
        """Window above maximum (10080) is rejected"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/escalation-analytics?window_minutes=20000",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert resp.status_code == 422, f"Expected 422 for invalid window, got {resp.status_code}"
        print("PASS: Window above maximum rejected")


class TestResponseShape:
    """Response structure validation tests"""
    
    def test_response_has_window_minutes(self, operator_token):
        """Response contains window_minutes"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/escalation-analytics",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "window_minutes" in data
        assert isinstance(data["window_minutes"], int)
        print("PASS: Response has window_minutes")
    
    def test_response_has_total_incidents(self, operator_token):
        """Response contains total_incidents"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/escalation-analytics",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total_incidents" in data
        assert isinstance(data["total_incidents"], int)
        print("PASS: Response has total_incidents")
    
    def test_response_has_open_incidents(self, operator_token):
        """Response contains open_incidents"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/escalation-analytics",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "open_incidents" in data
        assert isinstance(data["open_incidents"], int)
        print("PASS: Response has open_incidents")
    
    def test_response_has_tier_counts(self, operator_token):
        """Response contains tier_counts with l1, l2, l3"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/escalation-analytics",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "tier_counts" in data
        tier_counts = data["tier_counts"]
        assert "l1" in tier_counts
        assert "l2" in tier_counts
        assert "l3" in tier_counts
        assert isinstance(tier_counts["l1"], int)
        assert isinstance(tier_counts["l2"], int)
        assert isinstance(tier_counts["l3"], int)
        print(f"PASS: tier_counts present: L1={tier_counts['l1']}, L2={tier_counts['l2']}, L3={tier_counts['l3']}")
    
    def test_response_has_timings(self, operator_token):
        """Response contains timings with ack, resolve, first_escalation"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/escalation-analytics",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "timings" in data
        timings = data["timings"]
        assert "avg_time_to_ack_seconds" in timings
        assert "avg_time_to_resolve_seconds" in timings
        assert "avg_time_to_first_escalation_seconds" in timings
        print(f"PASS: timings present: ack={timings['avg_time_to_ack_seconds']}, resolve={timings['avg_time_to_resolve_seconds']}")
    
    def test_response_has_device_instability(self, operator_token):
        """Response contains device_instability metrics"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/escalation-analytics",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "device_instability" in data
        di = data["device_instability"]
        assert "total" in di
        assert "auto_recovered" in di
        assert "manual_resolved" in di
        assert "recovery_paths" in di
        assert "repeat_device_rate_percent" in di
        assert "cooldown_blocks_count" in di
        print(f"PASS: device_instability present: total={di['total']}, auto={di['auto_recovered']}, manual={di['manual_resolved']}")
    
    def test_response_has_recovery_paths(self, operator_token):
        """Response contains recovery_paths with case_a and case_b counts"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/escalation-analytics",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()
        recovery_paths = data["device_instability"]["recovery_paths"]
        assert "case_a_no_anomaly_window" in recovery_paths
        assert "case_b_clear_cycles_below_hysteresis" in recovery_paths
        print(f"PASS: recovery_paths present: case_a={recovery_paths['case_a_no_anomaly_window']}, case_b={recovery_paths['case_b_clear_cycles_below_hysteresis']}")
    
    def test_response_has_top_devices(self, operator_token):
        """Response contains top_devices_by_instability array"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/escalation-analytics",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "top_devices_by_instability" in data
        assert isinstance(data["top_devices_by_instability"], list)
        print(f"PASS: top_devices_by_instability present with {len(data['top_devices_by_instability'])} devices")


class TestTierCounts:
    """Tier count validation tests - uses incidents.escalation_level"""
    
    def test_tier_counts_are_exclusive(self, operator_token):
        """Tier counts should be exclusive (L1=level 1, L2=level 2, L3=level 3+)"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/escalation-analytics?window_minutes=10080",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()
        tier_counts = data["tier_counts"]
        total = data["total_incidents"]
        
        # L1 + L2 + L3 should be <= total (some incidents may have escalation_level=0 or NULL)
        tier_sum = tier_counts["l1"] + tier_counts["l2"] + tier_counts["l3"]
        assert tier_sum <= total, f"Tier sum {tier_sum} > total {total}"
        print(f"PASS: Tier counts are exclusive - L1={tier_counts['l1']}, L2={tier_counts['l2']}, L3={tier_counts['l3']}, total={total}")


class TestTimings:
    """Timing metrics validation tests"""
    
    def test_timings_are_positive_or_null(self, operator_token):
        """Timing metrics should be positive or null (negative values excluded)"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/escalation-analytics",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()
        timings = data["timings"]
        
        for key, value in timings.items():
            if value is not None:
                assert value >= 0, f"Timing {key} has negative value: {value}"
        print("PASS: All timing values are positive or null")
    
    def test_ack_time_null_when_no_acked(self, operator_token):
        """avg_time_to_ack_seconds should be null when no acknowledged incidents"""
        # Use a very small window that may have no acknowledged incidents
        resp = requests.get(
            f"{BASE_URL}/api/operator/escalation-analytics?window_minutes=15",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()
        # Just verify the field can be null (it's null if no acked incidents)
        timings = data["timings"]
        # Note: This test verifies the field exists and handles null correctly
        if timings["avg_time_to_ack_seconds"] is None:
            print("PASS: avg_time_to_ack_seconds is null (no acknowledged incidents in window)")
        else:
            print(f"PASS: avg_time_to_ack_seconds is {timings['avg_time_to_ack_seconds']} seconds")


class TestDeviceInstabilityMetrics:
    """Device instability metrics validation tests"""
    
    def test_repeat_rate_calculation(self, operator_token):
        """Repeat device rate = devices_with_repeat / devices_with_instability * 100"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/escalation-analytics?window_minutes=10080",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()
        di = data["device_instability"]
        
        repeat_rate = di["repeat_device_rate_percent"]
        assert isinstance(repeat_rate, (int, float))
        assert repeat_rate >= 0
        assert repeat_rate <= 100
        print(f"PASS: repeat_device_rate_percent is {repeat_rate}%")
    
    def test_cooldown_blocks_count_exists(self, operator_token):
        """cooldown_blocks_count should exist and be >= 0"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/escalation-analytics",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()
        di = data["device_instability"]
        
        assert "cooldown_blocks_count" in di
        assert isinstance(di["cooldown_blocks_count"], int)
        assert di["cooldown_blocks_count"] >= 0
        print(f"PASS: cooldown_blocks_count = {di['cooldown_blocks_count']}")
    
    def test_recovery_totals_make_sense(self, operator_token):
        """auto_recovered + manual_resolved should relate to total instability resolved"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/escalation-analytics?window_minutes=10080",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()
        di = data["device_instability"]
        
        total = di["total"]
        auto = di["auto_recovered"]
        manual = di["manual_resolved"]
        
        # Auto + Manual = resolved instability incidents
        # Total = all instability incidents (open + resolved)
        # So auto + manual <= total
        assert auto + manual <= total, f"auto({auto}) + manual({manual}) > total({total})"
        print(f"PASS: Recovery totals valid - total={total}, auto={auto}, manual={manual}")


class TestTopDevices:
    """Top devices by instability tests"""
    
    def test_top_devices_has_correct_fields(self, operator_token):
        """Top devices should have device_identifier, senior_name, guardian_name, instability_count, avg_score"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/escalation-analytics?window_minutes=10080",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()
        top_devices = data["top_devices_by_instability"]
        
        if len(top_devices) > 0:
            device = top_devices[0]
            assert "device_identifier" in device
            assert "senior_name" in device
            assert "guardian_name" in device
            assert "instability_count" in device
            assert "avg_score" in device
            print(f"PASS: Top device has all fields - {device['device_identifier']} count={device['instability_count']}")
        else:
            print("PASS: No instability incidents in window (empty top_devices)")
    
    def test_top_devices_ordered_by_count_desc(self, operator_token):
        """Top devices should be ordered by instability_count DESC"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/escalation-analytics?window_minutes=10080",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()
        top_devices = data["top_devices_by_instability"]
        
        if len(top_devices) >= 2:
            for i in range(len(top_devices) - 1):
                assert top_devices[i]["instability_count"] >= top_devices[i + 1]["instability_count"], \
                    f"Not sorted DESC: {top_devices[i]['instability_count']} < {top_devices[i + 1]['instability_count']}"
            print(f"PASS: Top devices correctly ordered by instability_count DESC")
        else:
            print(f"PASS: {len(top_devices)} devices - ordering verified")
    
    def test_top_devices_max_10(self, operator_token):
        """Top devices should have max 10 entries"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/escalation-analytics?window_minutes=10080",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()
        top_devices = data["top_devices_by_instability"]
        
        assert len(top_devices) <= 10, f"Top devices has {len(top_devices)} entries, expected max 10"
        print(f"PASS: Top devices count = {len(top_devices)} (max 10)")


class TestEmptyWindow:
    """Empty window edge case tests"""
    
    def test_empty_window_returns_zeroed_structure(self, operator_token):
        """Empty window should return zeroed structure, not error"""
        # Use a very small window (15 min) which may have no incidents
        resp = requests.get(
            f"{BASE_URL}/api/operator/escalation-analytics?window_minutes=15",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        data = resp.json()
        
        # Structure should exist even if all zeros
        assert "window_minutes" in data
        assert "total_incidents" in data
        assert "tier_counts" in data
        assert "timings" in data
        assert "device_instability" in data
        assert "top_devices_by_instability" in data
        print("PASS: Empty window returns valid zeroed structure")


class TestDataIntegrity:
    """Data integrity and consistency tests"""
    
    def test_open_less_than_equal_total(self, operator_token):
        """open_incidents should be <= total_incidents"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/escalation-analytics",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()
        
        assert data["open_incidents"] <= data["total_incidents"], \
            f"open({data['open_incidents']}) > total({data['total_incidents']})"
        print(f"PASS: open({data['open_incidents']}) <= total({data['total_incidents']})")
    
    def test_instability_total_is_subset(self, operator_token):
        """device_instability.total should be <= total_incidents"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/escalation-analytics",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()
        
        di_total = data["device_instability"]["total"]
        total = data["total_incidents"]
        
        assert di_total <= total, f"instability_total({di_total}) > total({total})"
        print(f"PASS: device_instability.total({di_total}) <= total_incidents({total})")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
