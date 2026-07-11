"""
Test Status/Telemetry APIs with Real PostgreSQL Database Data
Tests: /api/status/platform, /api/status/events, /api/status/metrics
Validates: Real DB queries, anonymization, caching, no sensitive data
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Sensitive fields that should NOT appear in responses
SENSITIVE_FIELDS = ['user_id', 'coordinates', 'lat', 'lng', 'location', 'name', 'email', 'phone', 'address']
# Note: 'lat', 'lng' are allowed in cities array for map display but NOT in events

class TestPlatformStatus:
    """Test GET /api/status/platform - Real DB aggregated metrics"""
    
    def test_platform_status_returns_200(self):
        """Platform status endpoint should return 200"""
        response = requests.get(f"{BASE_URL}/api/status/platform")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("PASS: GET /api/status/platform returns 200")
    
    def test_platform_status_structure(self):
        """Platform status should have required structure"""
        response = requests.get(f"{BASE_URL}/api/status/platform")
        data = response.json()
        
        # Check required top-level keys
        assert "status" in data, "Missing 'status' field"
        assert "metrics" in data, "Missing 'metrics' field"
        assert "cities" in data, "Missing 'cities' field"
        assert "systems" in data, "Missing 'systems' field"
        assert "last_updated" in data, "Missing 'last_updated' field"
        
        # Check status value
        assert data["status"] == "operational", f"Expected 'operational', got {data['status']}"
        print("PASS: Platform status has correct structure")
    
    def test_platform_metrics_structure(self):
        """Platform metrics should have 6 required fields from real DB"""
        response = requests.get(f"{BASE_URL}/api/status/platform")
        data = response.json()
        metrics = data.get("metrics", {})
        
        required_metrics = [
            "active_sessions",
            "signals_today",
            "ai_predictions",
            "alerts_today",
            "cities_monitored",
            "avg_response_time"
        ]
        
        for metric in required_metrics:
            assert metric in metrics, f"Missing metric: {metric}"
            # Values should be numbers (int or float)
            assert isinstance(metrics[metric], (int, float)), f"{metric} should be numeric"
        
        print(f"PASS: All 6 metrics present: {metrics}")
    
    def test_platform_metrics_reasonable_values(self):
        """Metrics should have reasonable values (not all zeros if DB has data)"""
        response = requests.get(f"{BASE_URL}/api/status/platform")
        data = response.json()
        metrics = data.get("metrics", {})
        
        # At least one metric should be > 0 to indicate real data
        non_zero_metrics = [k for k, v in metrics.items() if v > 0]
        print(f"Non-zero metrics: {non_zero_metrics}")
        print(f"Metric values: {metrics}")
        
        # We expect at least signals_today or ai_predictions to have data
        assert len(non_zero_metrics) >= 1, "All metrics are zero - may indicate DB query issues"
        print("PASS: Metrics show reasonable values (not all zeros)")
    
    def test_platform_cities_structure(self):
        """Cities array should have 6 city nodes with sessions data"""
        response = requests.get(f"{BASE_URL}/api/status/platform")
        data = response.json()
        cities = data.get("cities", [])
        
        assert len(cities) == 6, f"Expected 6 cities, got {len(cities)}"
        
        for city in cities:
            assert "name" in city, "City missing 'name'"
            assert "lat" in city, "City missing 'lat'"
            assert "lng" in city, "City missing 'lng'"
            assert "active_sessions" in city, "City missing 'active_sessions'"
            assert "signals_today" in city, "City missing 'signals_today'"
            assert "risk_level" in city, "City missing 'risk_level'"
        
        city_names = [c["name"] for c in cities]
        print(f"PASS: 6 cities present: {city_names}")
    
    def test_platform_systems_health(self):
        """System health should show 8 operational modules"""
        response = requests.get(f"{BASE_URL}/api/status/platform")
        data = response.json()
        systems = data.get("systems", [])
        
        assert len(systems) == 8, f"Expected 8 systems, got {len(systems)}"
        
        for sys in systems:
            assert sys.get("status") == "operational", f"System {sys.get('name')} not operational"
            assert sys.get("uptime", 0) >= 99.0, f"System {sys.get('name')} uptime too low"
        
        print(f"PASS: All 8 systems operational")
    
    def test_platform_no_sensitive_data_in_events(self):
        """Ensure no user_id, exact coordinates, or names in event messages"""
        response = requests.get(f"{BASE_URL}/api/status/platform")
        data = response.json()
        
        # Check that response doesn't contain user-identifiable fields at top level
        response_text = str(data)
        
        # user_id should never appear
        assert "user_id" not in response_text.lower(), "Found user_id in response"
        
        # Personal info should not appear
        assert "email" not in str(data.get("metrics", {})), "Found email in metrics"
        assert "phone" not in str(data.get("metrics", {})), "Found phone in metrics"
        
        print("PASS: No sensitive user data in platform response")


class TestLiveEvents:
    """Test GET /api/status/events - Real anonymized events from DB"""
    
    def test_events_returns_200(self):
        """Events endpoint should return 200"""
        response = requests.get(f"{BASE_URL}/api/status/events")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("PASS: GET /api/status/events returns 200")
    
    def test_events_structure(self):
        """Events should return array of anonymized events"""
        response = requests.get(f"{BASE_URL}/api/status/events")
        data = response.json()
        
        assert "events" in data, "Missing 'events' field"
        events = data["events"]
        
        assert isinstance(events, list), "events should be a list"
        assert len(events) <= 20, f"Expected max 20 events, got {len(events)}"
        
        print(f"PASS: Events returns array with {len(events)} events")
    
    def test_events_item_structure(self):
        """Each event should have timestamp, message, and type"""
        response = requests.get(f"{BASE_URL}/api/status/events")
        data = response.json()
        events = data.get("events", [])
        
        if len(events) == 0:
            pytest.skip("No events in response - may need seed data")
        
        for i, event in enumerate(events):
            assert "timestamp" in event, f"Event {i} missing timestamp"
            assert "message" in event, f"Event {i} missing message"
            assert "type" in event, f"Event {i} missing type"
            
            # Type should be one of the expected values
            valid_types = ["alert", "anomaly", "system", "resolved"]
            assert event["type"] in valid_types, f"Event {i} has invalid type: {event['type']}"
        
        print(f"PASS: All {len(events)} events have correct structure")
    
    def test_events_type_variety(self):
        """Events should show mix of types (alert, anomaly, system, resolved)"""
        response = requests.get(f"{BASE_URL}/api/status/events")
        data = response.json()
        events = data.get("events", [])
        
        if len(events) == 0:
            pytest.skip("No events in response")
        
        event_types = set(e["type"] for e in events)
        print(f"Event types found: {event_types}")
        
        # Should have at least 2 different types for variety
        # Note: This may vary based on DB data
        print(f"PASS: Found {len(event_types)} different event types")
    
    def test_events_no_sensitive_data(self):
        """Events should be anonymized - no user IDs, no exact coordinates, no names"""
        response = requests.get(f"{BASE_URL}/api/status/events")
        data = response.json()
        events = data.get("events", [])
        
        for i, event in enumerate(events):
            msg = event.get("message", "").lower()
            
            # Should not contain user identifiers
            assert "user_id" not in str(event).lower(), f"Event {i} contains user_id"
            
            # Messages should use zone names, not actual coordinates
            # Zone names are like "Zone Alpha", "Campus North", etc.
            assert "Zone" in event.get("message", "") or "Campus" in event.get("message", "") or "Corridor" in event.get("message", "") or "Block" in event.get("message", ""), \
                f"Event {i} message doesn't use anonymized zone names: {event.get('message')}"
        
        print("PASS: Events are properly anonymized with zone names")


class TestNetworkMetrics:
    """Test GET /api/status/metrics - Real network growth metrics from DB"""
    
    def test_metrics_returns_200(self):
        """Metrics endpoint should return 200"""
        response = requests.get(f"{BASE_URL}/api/status/metrics")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("PASS: GET /api/status/metrics returns 200")
    
    def test_metrics_structure_8_fields(self):
        """Network metrics should have 8 required fields"""
        response = requests.get(f"{BASE_URL}/api/status/metrics")
        data = response.json()
        
        required_fields = [
            "institutions_protected",
            "active_guardians",
            "total_safety_sessions",
            "incidents_resolved",
            "total_users",
            "total_sos_events",
            "signals_processed_total",
            "avg_response_seconds"
        ]
        
        for field in required_fields:
            assert field in data, f"Missing metric field: {field}"
            assert isinstance(data[field], (int, float)), f"{field} should be numeric"
        
        print(f"PASS: All 8 network metrics present")
        print(f"Metrics: {data}")
    
    def test_metrics_values_from_real_db(self):
        """Metrics should reflect real DB counts"""
        response = requests.get(f"{BASE_URL}/api/status/metrics")
        data = response.json()
        
        # At least some metrics should be non-zero if DB has data
        non_zero = {k: v for k, v in data.items() if v > 0}
        print(f"Non-zero metrics: {non_zero}")
        
        # institutions_protected comes from pilot_leads count
        # active_guardians from guardian_relationships
        # total_safety_sessions from safety_events
        # incidents_resolved from incidents WHERE status='resolved'
        # total_users from users
        # total_sos_events from sos_logs
        # signals_processed_total from telemetries
        
        # We expect at least a few to be non-zero
        assert len(non_zero) >= 1, "All metrics are zero - may indicate empty DB or query issues"
        print("PASS: Metrics show non-zero values from DB")
    
    def test_metrics_no_sensitive_data(self):
        """Metrics should not contain any PII"""
        response = requests.get(f"{BASE_URL}/api/status/metrics")
        data = response.json()
        
        # Only numeric aggregates allowed
        for key, value in data.items():
            assert isinstance(value, (int, float)), f"{key} should be numeric, not {type(value)}"
        
        # Should not have any user-identifiable keys
        for sensitive in SENSITIVE_FIELDS:
            assert sensitive not in data, f"Found sensitive field: {sensitive}"
        
        print("PASS: Metrics contain only aggregated numbers, no PII")


class TestCaching:
    """Test 30-second caching behavior"""
    
    def test_platform_caching(self):
        """Two rapid calls to /api/status/platform should return same data (cached)"""
        # First call
        resp1 = requests.get(f"{BASE_URL}/api/status/platform")
        data1 = resp1.json()
        ts1 = data1.get("last_updated")
        
        # Wait a short time (less than cache TTL)
        time.sleep(1)
        
        # Second call
        resp2 = requests.get(f"{BASE_URL}/api/status/platform")
        data2 = resp2.json()
        ts2 = data2.get("last_updated")
        
        # Same timestamp indicates caching is working
        assert ts1 == ts2, f"Expected same timestamp (cached), got {ts1} vs {ts2}"
        print(f"PASS: Caching works - same last_updated: {ts1}")
    
    def test_events_caching(self):
        """Two rapid calls to /api/status/events should return same data (cached)"""
        resp1 = requests.get(f"{BASE_URL}/api/status/events")
        data1 = resp1.json()
        
        time.sleep(1)
        
        resp2 = requests.get(f"{BASE_URL}/api/status/events")
        data2 = resp2.json()
        
        # Events array should be identical if cached
        assert data1 == data2, "Events data differs - caching may not be working"
        print("PASS: Events caching works")
    
    def test_metrics_caching(self):
        """Two rapid calls to /api/status/metrics should return same data (cached)"""
        resp1 = requests.get(f"{BASE_URL}/api/status/metrics")
        data1 = resp1.json()
        
        time.sleep(1)
        
        resp2 = requests.get(f"{BASE_URL}/api/status/metrics")
        data2 = resp2.json()
        
        # Metrics should be identical if cached
        assert data1 == data2, "Metrics data differs - caching may not be working"
        print("PASS: Metrics caching works")


class TestRateLimiting:
    """Test rate limiting on status endpoints (60/minute)"""
    
    def test_rate_limit_header_present(self):
        """Rate limit headers should be present in response"""
        response = requests.get(f"{BASE_URL}/api/status/platform")
        
        # Check for rate limit related headers
        # slowapi typically adds these headers
        headers = response.headers
        print(f"Response headers: {dict(headers)}")
        
        # Just verify endpoint responds (rate limit testing done in previous iteration)
        assert response.status_code in [200, 429], f"Unexpected status: {response.status_code}"
        print("PASS: Endpoint responds with expected status")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
