"""
Test Safety Dashboard API Endpoints
Tests the 4 endpoints used by the Public Safety Dashboard:
1. GET /api/status/platform - Platform metrics and city data
2. GET /api/status/events - Live intelligence feed events
3. GET /api/status/incidents - Active incidents data (NEW)
4. GET /api/status/risk-intelligence - AI risk analysis (NEW)
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestPlatformStatus:
    """Tests for GET /api/status/platform endpoint"""
    
    def test_platform_status_returns_200(self):
        """Platform status endpoint should return 200"""
        response = requests.get(f"{BASE_URL}/api/status/platform")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("PASS: /api/status/platform returns 200")
    
    def test_platform_status_has_metrics(self):
        """Platform status should contain metrics object"""
        response = requests.get(f"{BASE_URL}/api/status/platform")
        data = response.json()
        assert "metrics" in data, "Response should contain 'metrics'"
        metrics = data["metrics"]
        
        # Verify all 6 required metrics exist
        required_metrics = ["active_sessions", "signals_today", "ai_predictions", 
                          "alerts_today", "cities_monitored", "avg_response_time"]
        for metric in required_metrics:
            assert metric in metrics, f"Metrics should contain '{metric}'"
        
        print(f"PASS: Platform metrics contains all 6 required fields")
        print(f"  Values: {metrics}")
    
    def test_platform_status_has_cities(self):
        """Platform status should contain cities array with 6 cities"""
        response = requests.get(f"{BASE_URL}/api/status/platform")
        data = response.json()
        assert "cities" in data, "Response should contain 'cities'"
        cities = data["cities"]
        
        assert len(cities) == 6, f"Expected 6 cities, got {len(cities)}"
        
        # Verify city structure
        for city in cities:
            assert "name" in city, "City should have 'name'"
            assert "risk_level" in city, "City should have 'risk_level'"
            assert "active_sessions" in city, "City should have 'active_sessions'"
            assert "signals_today" in city, "City should have 'signals_today'"
        
        city_names = [c["name"] for c in cities]
        print(f"PASS: Cities array contains 6 cities: {city_names}")
    
    def test_platform_status_is_operational(self):
        """Platform status should show 'operational'"""
        response = requests.get(f"{BASE_URL}/api/status/platform")
        data = response.json()
        assert data.get("status") == "operational", "Status should be 'operational'"
        print("PASS: Platform status is operational")


class TestLiveEvents:
    """Tests for GET /api/status/events endpoint"""
    
    def test_events_returns_200(self):
        """Events endpoint should return 200"""
        response = requests.get(f"{BASE_URL}/api/status/events")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("PASS: /api/status/events returns 200")
    
    def test_events_has_events_array(self):
        """Events response should contain events array"""
        response = requests.get(f"{BASE_URL}/api/status/events")
        data = response.json()
        assert "events" in data, "Response should contain 'events'"
        events = data["events"]
        
        assert isinstance(events, list), "Events should be a list"
        print(f"PASS: Events array contains {len(events)} events")
    
    def test_events_have_required_fields(self):
        """Each event should have timestamp, message, and type"""
        response = requests.get(f"{BASE_URL}/api/status/events")
        data = response.json()
        events = data.get("events", [])
        
        if len(events) > 0:
            for i, event in enumerate(events[:5]):  # Check first 5
                assert "timestamp" in event, f"Event {i} should have 'timestamp'"
                assert "message" in event, f"Event {i} should have 'message'"
                assert "type" in event, f"Event {i} should have 'type'"
            print(f"PASS: Events have required fields (checked {min(5, len(events))} events)")
        else:
            print("SKIP: No events to validate structure")


class TestIncidentsEndpoint:
    """Tests for GET /api/status/incidents endpoint (NEW)"""
    
    def test_incidents_returns_200(self):
        """Incidents endpoint should return 200"""
        response = requests.get(f"{BASE_URL}/api/status/incidents")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("PASS: /api/status/incidents returns 200")
    
    def test_incidents_has_incidents_array(self):
        """Incidents response should contain incidents array"""
        response = requests.get(f"{BASE_URL}/api/status/incidents")
        data = response.json()
        assert "incidents" in data, "Response should contain 'incidents'"
        incidents = data["incidents"]
        
        assert isinstance(incidents, list), "Incidents should be a list"
        print(f"PASS: Incidents array contains {len(incidents)} incidents")
    
    def test_incidents_have_required_fields(self):
        """Each incident should have type, severity, status, zone, created_at"""
        response = requests.get(f"{BASE_URL}/api/status/incidents")
        data = response.json()
        incidents = data.get("incidents", [])
        
        if len(incidents) > 0:
            required_fields = ["type", "severity", "status", "zone", "created_at", "risk_score"]
            for i, incident in enumerate(incidents[:5]):  # Check first 5
                for field in required_fields:
                    assert field in incident, f"Incident {i} should have '{field}'"
            print(f"PASS: Incidents have required fields (checked {min(5, len(incidents))} incidents)")
            print(f"  Sample incident: {incidents[0]}")
        else:
            print("SKIP: No incidents to validate structure")
    
    def test_incidents_have_valid_severity(self):
        """Incident severity should be one of: critical, high, medium, low"""
        response = requests.get(f"{BASE_URL}/api/status/incidents")
        data = response.json()
        incidents = data.get("incidents", [])
        
        valid_severities = ["critical", "high", "medium", "low"]
        if len(incidents) > 0:
            for incident in incidents:
                severity = incident.get("severity")
                assert severity in valid_severities, f"Invalid severity: {severity}"
            print(f"PASS: All incidents have valid severity levels")


class TestRiskIntelligence:
    """Tests for GET /api/status/risk-intelligence endpoint (NEW)"""
    
    def test_risk_intelligence_returns_200(self):
        """Risk intelligence endpoint should return 200"""
        response = requests.get(f"{BASE_URL}/api/status/risk-intelligence")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("PASS: /api/status/risk-intelligence returns 200")
    
    def test_risk_intelligence_has_metrics(self):
        """Risk intelligence should have 4 main metric counts"""
        response = requests.get(f"{BASE_URL}/api/status/risk-intelligence")
        data = response.json()
        
        required_metrics = ["high_risk_incidents", "anomaly_clusters", 
                          "ai_predictions_active", "unresolved_incidents"]
        for metric in required_metrics:
            assert metric in data, f"Response should contain '{metric}'"
            assert isinstance(data[metric], int), f"'{metric}' should be an integer"
        
        print(f"PASS: Risk intelligence has all 4 metric counts")
        print(f"  high_risk={data['high_risk_incidents']}, anomalies={data['anomaly_clusters']}, "
              f"predictions={data['ai_predictions_active']}, unresolved={data['unresolved_incidents']}")
    
    def test_risk_intelligence_has_risk_zones(self):
        """Risk intelligence should have risk_zones array"""
        response = requests.get(f"{BASE_URL}/api/status/risk-intelligence")
        data = response.json()
        
        assert "risk_zones" in data, "Response should contain 'risk_zones'"
        risk_zones = data["risk_zones"]
        assert isinstance(risk_zones, list), "risk_zones should be a list"
        
        if len(risk_zones) > 0:
            for zone in risk_zones:
                assert "zone" in zone, "Risk zone should have 'zone' name"
                assert "risk_level" in zone, "Risk zone should have 'risk_level'"
            print(f"PASS: Risk zones array has {len(risk_zones)} zones")
        else:
            print("PASS: Risk zones array is empty but valid")
    
    def test_risk_intelligence_has_ai_recommendations(self):
        """Risk intelligence should have ai_recommendations array"""
        response = requests.get(f"{BASE_URL}/api/status/risk-intelligence")
        data = response.json()
        
        assert "ai_recommendations" in data, "Response should contain 'ai_recommendations'"
        recs = data["ai_recommendations"]
        assert isinstance(recs, list), "ai_recommendations should be a list"
        
        if len(recs) > 0:
            for rec in recs:
                assert "priority" in rec, "Recommendation should have 'priority'"
                assert "message" in rec, "Recommendation should have 'message'"
            print(f"PASS: AI recommendations array has {len(recs)} recommendations")
        else:
            print("PASS: AI recommendations array is empty but valid")
    
    def test_risk_zones_have_valid_levels(self):
        """Risk zone levels should be: high, elevated, moderate, low"""
        response = requests.get(f"{BASE_URL}/api/status/risk-intelligence")
        data = response.json()
        risk_zones = data.get("risk_zones", [])
        
        valid_levels = ["high", "elevated", "moderate", "low"]
        if len(risk_zones) > 0:
            for zone in risk_zones:
                level = zone.get("risk_level")
                assert level in valid_levels, f"Invalid risk level: {level}"
            print(f"PASS: All risk zones have valid risk levels")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
