# Safe Zone Detection Engine Tests
# Tests for GET /api/safety/zone-map and POST /api/safety/check-zone endpoints
# Phase 33: Safe Zone Detection Engine

import pytest
import requests
import os
from datetime import datetime, timezone

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
OPERATOR_EMAIL = "operator@nischint.com"
OPERATOR_PASSWORD = "operator123"
GUARDIAN_EMAIL = "nischint4parents@gmail.com"
GUARDIAN_PASSWORD = "secret123"

# Test coordinates
CRITICAL_ZONE_COORDS = {"lat": 12.972, "lng": 77.587}  # Near critical zone
SAFE_AREA_COORDS = {"lat": 13.1, "lng": 77.4}  # Safe area

class TestSafeZoneDetection:
    """Safe Zone Detection Engine API Tests"""
    
    @pytest.fixture(scope="class")
    def operator_token(self):
        """Get operator access token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": OPERATOR_EMAIL,
            "password": OPERATOR_PASSWORD
        })
        if response.status_code != 200:
            pytest.skip("Operator login failed")
        return response.json().get("access_token")
    
    @pytest.fixture(scope="class")
    def guardian_token(self):
        """Get guardian access token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": GUARDIAN_EMAIL,
            "password": GUARDIAN_PASSWORD
        })
        if response.status_code != 200:
            pytest.skip("Guardian login failed")
        return response.json().get("access_token")
    
    @pytest.fixture(scope="class")
    def auth_headers(self, operator_token):
        """Returns auth headers"""
        return {"Authorization": f"Bearer {operator_token}"}
    
    # ── Zone Map Tests ──
    def test_get_zone_map_returns_200(self, auth_headers):
        """GET /api/safety/zone-map returns 200"""
        response = requests.get(f"{BASE_URL}/api/safety/zone-map", headers=auth_headers)
        assert response.status_code == 200
        print("GET /api/safety/zone-map: 200 OK")
    
    def test_zone_map_has_required_fields(self, auth_headers):
        """Zone map response has zones, total_zones, time_multiplier, time_period, stats"""
        response = requests.get(f"{BASE_URL}/api/safety/zone-map", headers=auth_headers)
        data = response.json()
        
        assert "zones" in data
        assert "total_zones" in data
        assert "time_multiplier" in data
        assert "time_period" in data
        assert "stats" in data
        assert "generated_at" in data
        print(f"Zone map has all required fields. Total zones: {data['total_zones']}")
    
    def test_zone_map_stats_has_all_risk_levels(self, auth_headers):
        """Stats includes CRITICAL, HIGH, LOW, SAFE counts"""
        response = requests.get(f"{BASE_URL}/api/safety/zone-map", headers=auth_headers)
        stats = response.json().get("stats", {})
        
        assert "CRITICAL" in stats
        assert "HIGH" in stats
        assert "LOW" in stats
        assert "SAFE" in stats
        print(f"Stats: CRITICAL={stats['CRITICAL']}, HIGH={stats['HIGH']}, LOW={stats['LOW']}, SAFE={stats['SAFE']}")
    
    def test_zone_map_zones_have_required_fields(self, auth_headers):
        """Each zone has zone_id, zone_name, lat, lng, radius_m, risk_score, risk_level"""
        response = requests.get(f"{BASE_URL}/api/safety/zone-map", headers=auth_headers)
        zones = response.json().get("zones", [])
        
        assert len(zones) > 0, "Expected at least one zone"
        first_zone = zones[0]
        
        required_fields = ["zone_id", "zone_name", "lat", "lng", "radius_m", "risk_score", "base_risk_score", "risk_level", "incident_count"]
        for field in required_fields:
            assert field in first_zone, f"Missing field: {field}"
        
        print(f"First zone: {first_zone['zone_name']} - {first_zone['risk_level']} (score: {first_zone['risk_score']})")
    
    def test_zone_map_time_multiplier_is_day_during_day_hours(self, auth_headers):
        """Time multiplier is 1.0 for day period (6-20)"""
        response = requests.get(f"{BASE_URL}/api/safety/zone-map", headers=auth_headers)
        data = response.json()
        
        # Note: This depends on server time. Check current hour.
        current_hour = datetime.now(timezone.utc).hour
        if 6 <= current_hour < 20:
            assert data["time_multiplier"] == 1.0, f"Expected 1.0 for day, got {data['time_multiplier']}"
            assert data["time_period"] == "day"
            print(f"Day period: time_multiplier=1.0 (hour={current_hour})")
        elif 20 <= current_hour < 24:
            assert data["time_multiplier"] == 1.3, f"Expected 1.3 for night, got {data['time_multiplier']}"
            assert data["time_period"] == "night"
            print(f"Night period: time_multiplier=1.3 (hour={current_hour})")
        else:  # 0-5
            assert data["time_multiplier"] == 1.6, f"Expected 1.6 for late_night, got {data['time_multiplier']}"
            assert data["time_period"] == "late_night"
            print(f"Late night period: time_multiplier=1.6 (hour={current_hour})")
    
    def test_zone_map_requires_auth(self):
        """Zone map requires authentication"""
        response = requests.get(f"{BASE_URL}/api/safety/zone-map")
        assert response.status_code in [401, 403]
        print("Zone map requires auth: passed")
    
    # ── Check Zone Tests ──
    def test_check_zone_returns_200(self, auth_headers):
        """POST /api/safety/check-zone returns 200"""
        response = requests.post(
            f"{BASE_URL}/api/safety/check-zone",
            headers=auth_headers,
            json={"location": CRITICAL_ZONE_COORDS}
        )
        assert response.status_code == 200
        print("POST /api/safety/check-zone: 200 OK")
    
    def test_check_zone_has_required_fields(self, auth_headers):
        """Check zone response has all required fields"""
        response = requests.post(
            f"{BASE_URL}/api/safety/check-zone",
            headers=auth_headers,
            json={"location": {"lat": 12.98, "lng": 77.59}}
        )
        data = response.json()
        
        required_fields = [
            "zone_id", "zone_name", "zone_status", "risk_level", "risk_score",
            "base_score", "time_multiplier", "time_period", "recommendation",
            "recommendation_message", "safe_route_available", "incident_density",
            "score_breakdown", "transition", "alert_triggered", "cached", "checked_at"
        ]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"
        
        print(f"Check zone has all fields. Zone: {data['zone_name']}, Risk: {data['risk_level']}")
    
    def test_check_zone_score_breakdown(self, auth_headers):
        """Score breakdown includes crime_density, recent_incidents, time_of_day, environment"""
        response = requests.post(
            f"{BASE_URL}/api/safety/check-zone",
            headers=auth_headers,
            json={"location": {"lat": 12.98, "lng": 77.59}}
        )
        breakdown = response.json().get("score_breakdown", {})
        
        assert "crime_density" in breakdown
        assert "recent_incidents" in breakdown
        assert "time_of_day" in breakdown
        assert "environment" in breakdown
        
        print(f"Score breakdown: crime={breakdown['crime_density']}, incidents={breakdown['recent_incidents']}, time={breakdown['time_of_day']}, env={breakdown['environment']}")
    
    def test_check_zone_critical_zone_returns_high_or_critical(self, auth_headers):
        """Checking near critical zone returns HIGH or CRITICAL risk"""
        response = requests.post(
            f"{BASE_URL}/api/safety/check-zone",
            headers=auth_headers,
            json={"location": CRITICAL_ZONE_COORDS}
        )
        data = response.json()
        
        assert data["risk_level"] in ["HIGH", "CRITICAL"], f"Expected HIGH/CRITICAL, got {data['risk_level']}"
        assert data["risk_score"] >= 4.0, f"Expected score >= 4, got {data['risk_score']}"
        print(f"Critical zone check: {data['risk_level']} (score: {data['risk_score']})")
    
    def test_check_zone_safe_area_returns_safe_or_low(self, auth_headers):
        """Checking safe area returns SAFE or LOW risk"""
        response = requests.post(
            f"{BASE_URL}/api/safety/check-zone",
            headers=auth_headers,
            json={"location": SAFE_AREA_COORDS}
        )
        data = response.json()
        
        assert data["risk_level"] in ["SAFE", "LOW"], f"Expected SAFE/LOW, got {data['risk_level']}"
        assert data["risk_score"] < 4.0, f"Expected score < 4, got {data['risk_score']}"
        print(f"Safe area check: {data['risk_level']} (score: {data['risk_score']})")
    
    def test_check_zone_recommendation_for_safe(self, auth_headers):
        """Safe zone returns continue_journey recommendation"""
        response = requests.post(
            f"{BASE_URL}/api/safety/check-zone",
            headers=auth_headers,
            json={"location": SAFE_AREA_COORDS}
        )
        data = response.json()
        
        if data["risk_level"] == "SAFE":
            assert data["recommendation"] == "continue_journey"
            assert "safe" in data["recommendation_message"].lower() or "continue" in data["recommendation_message"].lower()
        print(f"Recommendation: {data['recommendation']} - {data['recommendation_message']}")
    
    def test_check_zone_recommendation_for_high(self, auth_headers):
        """High risk zone returns alternative_route recommendation"""
        response = requests.post(
            f"{BASE_URL}/api/safety/check-zone",
            headers=auth_headers,
            json={"location": CRITICAL_ZONE_COORDS}
        )
        data = response.json()
        
        if data["risk_level"] == "HIGH":
            assert data["recommendation"] == "alternative_route"
            assert data["safe_route_available"] == True
        print(f"High risk recommendation: {data['recommendation']}")
    
    def test_check_zone_transition_new_entry(self, auth_headers):
        """First check for user returns new_entry transition"""
        # Use a unique user_id to ensure new entry
        import uuid
        unique_user_id = str(uuid.uuid4())
        
        response = requests.post(
            f"{BASE_URL}/api/safety/check-zone",
            headers=auth_headers,
            json={
                "user_id": unique_user_id,
                "location": {"lat": 12.98, "lng": 77.59}
            }
        )
        data = response.json()
        transition = data.get("transition", {})
        
        assert transition.get("transitioned") == True
        assert transition.get("type") == "new_entry"
        assert transition.get("previous_zone") is None
        print(f"New entry transition detected: {transition}")
    
    def test_check_zone_same_zone_no_alert(self, auth_headers):
        """Same zone repeat check returns no alert"""
        import uuid
        unique_user_id = str(uuid.uuid4())
        location = {"lat": 12.99, "lng": 77.60}
        
        # First check - should be new_entry
        response1 = requests.post(
            f"{BASE_URL}/api/safety/check-zone",
            headers=auth_headers,
            json={"user_id": unique_user_id, "location": location}
        )
        
        # Second check - same zone, same user
        response2 = requests.post(
            f"{BASE_URL}/api/safety/check-zone",
            headers=auth_headers,
            json={"user_id": unique_user_id, "location": location}
        )
        data2 = response2.json()
        transition2 = data2.get("transition", {})
        
        assert transition2.get("transitioned") == False
        assert transition2.get("type") == "same_zone"
        assert data2.get("alert_triggered") == False
        print(f"Same zone repeat: no alert. Transition: {transition2}")
    
    def test_check_zone_escalation_triggers_alert(self, auth_headers):
        """Escalation (SAFE→HIGH) triggers alert"""
        import uuid
        unique_user_id = str(uuid.uuid4())
        
        # First check safe area
        response1 = requests.post(
            f"{BASE_URL}/api/safety/check-zone",
            headers=auth_headers,
            json={"user_id": unique_user_id, "location": SAFE_AREA_COORDS}
        )
        data1 = response1.json()
        first_level = data1.get("risk_level")
        
        # Then check critical area
        response2 = requests.post(
            f"{BASE_URL}/api/safety/check-zone",
            headers=auth_headers,
            json={"user_id": unique_user_id, "location": CRITICAL_ZONE_COORDS}
        )
        data2 = response2.json()
        transition2 = data2.get("transition", {})
        
        # If first was SAFE/LOW and second is HIGH/CRITICAL, should be escalation
        if first_level in ["SAFE", "LOW"] and data2["risk_level"] in ["HIGH", "CRITICAL"]:
            assert transition2.get("type") == "escalation"
            assert data2.get("alert_triggered") == True
            print(f"Escalation: {first_level} → {data2['risk_level']}. Alert triggered: {data2['alert_triggered']}")
        else:
            print(f"No escalation scenario: {first_level} → {data2['risk_level']}")
    
    def test_check_zone_caching_works(self, auth_headers):
        """Second check for same zone returns cached=true"""
        import uuid
        unique_user_id = str(uuid.uuid4())
        location = {"lat": 12.965, "lng": 77.58}
        
        # First check
        response1 = requests.post(
            f"{BASE_URL}/api/safety/check-zone",
            headers=auth_headers,
            json={"user_id": unique_user_id, "location": location}
        )
        data1 = response1.json()
        
        # Second check - same zone
        response2 = requests.post(
            f"{BASE_URL}/api/safety/check-zone",
            headers=auth_headers,
            json={"user_id": unique_user_id, "location": location}
        )
        data2 = response2.json()
        
        # Second response should be cached
        assert data2.get("cached") == True
        # Zone ID and risk level should match
        assert data1["zone_id"] == data2["zone_id"]
        print(f"Caching works: first cached={data1.get('cached')}, second cached={data2.get('cached')}")
    
    def test_check_zone_requires_auth(self):
        """Check zone requires authentication"""
        response = requests.post(
            f"{BASE_URL}/api/safety/check-zone",
            json={"location": SAFE_AREA_COORDS}
        )
        assert response.status_code in [401, 403]
        print("Check zone requires auth: passed")
    
    def test_check_zone_with_timestamp(self, auth_headers):
        """Check zone accepts timestamp parameter"""
        import uuid
        unique_user_id = str(uuid.uuid4())
        
        # Test with a specific timestamp
        timestamp = "2026-01-15T10:00:00Z"  # Day time
        response = requests.post(
            f"{BASE_URL}/api/safety/check-zone",
            headers=auth_headers,
            json={
                "user_id": unique_user_id,
                "location": {"lat": 12.97, "lng": 77.58},
                "timestamp": timestamp
            }
        )
        data = response.json()
        
        assert response.status_code == 200
        assert data["time_period"] == "day"
        assert data["time_multiplier"] == 1.0
        print(f"Timestamp parameter works: period={data['time_period']}, multiplier={data['time_multiplier']}")
    
    def test_check_zone_night_timestamp(self, auth_headers):
        """Night timestamp returns 1.3 multiplier"""
        import uuid
        unique_user_id = str(uuid.uuid4())
        
        # Night time: 20-24
        timestamp = "2026-01-15T22:00:00Z"
        response = requests.post(
            f"{BASE_URL}/api/safety/check-zone",
            headers=auth_headers,
            json={
                "user_id": unique_user_id,
                "location": {"lat": 12.968, "lng": 77.575},
                "timestamp": timestamp
            }
        )
        data = response.json()
        
        assert data["time_period"] == "night"
        assert data["time_multiplier"] == 1.3
        print(f"Night timestamp: period={data['time_period']}, multiplier={data['time_multiplier']}")
    
    def test_check_zone_late_night_timestamp(self, auth_headers):
        """Late night timestamp returns 1.6 multiplier"""
        import uuid
        unique_user_id = str(uuid.uuid4())
        
        # Late night: 0-5
        timestamp = "2026-01-15T03:00:00Z"
        response = requests.post(
            f"{BASE_URL}/api/safety/check-zone",
            headers=auth_headers,
            json={
                "user_id": unique_user_id,
                "location": {"lat": 12.955, "lng": 77.59},
                "timestamp": timestamp
            }
        )
        data = response.json()
        
        assert data["time_period"] == "late_night"
        assert data["time_multiplier"] == 1.6
        print(f"Late night timestamp: period={data['time_period']}, multiplier={data['time_multiplier']}")
    
    # ── Risk Level Classification Tests ──
    def test_risk_level_classification(self, auth_headers):
        """Verify risk level classification thresholds"""
        # SAFE: 0-2, LOW: 2-4, HIGH: 4-7, CRITICAL: 7-10
        response = requests.get(f"{BASE_URL}/api/safety/zone-map", headers=auth_headers)
        zones = response.json().get("zones", [])
        
        for zone in zones:
            score = zone["risk_score"]
            level = zone["risk_level"]
            
            if score < 2:
                assert level == "SAFE", f"Score {score} should be SAFE, got {level}"
            elif score < 4:
                assert level == "LOW", f"Score {score} should be LOW, got {level}"
            elif score < 7:
                assert level == "HIGH", f"Score {score} should be HIGH, got {level}"
            else:
                assert level == "CRITICAL", f"Score {score} should be CRITICAL, got {level}"
        
        print(f"Risk level classification verified for {len(zones)} zones")
    
    # ── Guardian Access Tests ──
    def test_guardian_can_access_zone_map(self, guardian_token):
        """Guardian can also access zone map"""
        headers = {"Authorization": f"Bearer {guardian_token}"}
        response = requests.get(f"{BASE_URL}/api/safety/zone-map", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        assert "zones" in data
        print(f"Guardian can access zone map. Zones: {len(data['zones'])}")
    
    def test_guardian_can_check_zone(self, guardian_token):
        """Guardian can check zone safety"""
        headers = {"Authorization": f"Bearer {guardian_token}"}
        response = requests.post(
            f"{BASE_URL}/api/safety/check-zone",
            headers=headers,
            json={"location": SAFE_AREA_COORDS}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "risk_level" in data
        print(f"Guardian can check zone. Result: {data['risk_level']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
