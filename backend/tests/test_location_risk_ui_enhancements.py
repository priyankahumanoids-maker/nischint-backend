"""
Backend API Tests for Location Risk UI Enhancements
Tests for the 5 UI enhancement features:
1. Risk Breakdown Visualization - breakdown object with 5 components
2. Incident Clustering - incidents array for MarkerClusterGroup
3. True Heatmap Layer - incidents with severity for intensity
4. Device Risk Indicators - risk_score and risk_level per device
5. Alert Animation - devices with high risk scores (>=5)
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestLocationRiskAPIEnhancements:
    """Test Location Risk API endpoints for UI enhancement support"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup: Login and get auth token"""
        login_resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "operator@nischint.com",
            "password": "operator123"
        })
        assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
        self.token = login_resp.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_heatmap_returns_devices_with_risk_score_and_level(self):
        """Feature 4: Device Risk Indicators - each device has risk_score and risk_level"""
        resp = requests.get(f"{BASE_URL}/api/operator/location-risk/heatmap", headers=self.headers)
        assert resp.status_code == 200
        data = resp.json()
        
        # Verify devices array exists
        assert "devices" in data
        assert len(data["devices"]) > 0
        
        # Each device should have risk_score and risk_level
        for device in data["devices"]:
            assert "device_id" in device
            assert "device_identifier" in device
            assert "lat" in device
            assert "lng" in device
            assert "risk_score" in device, f"Device {device['device_identifier']} missing risk_score"
            assert "risk_level" in device, f"Device {device['device_identifier']} missing risk_level"
            
            # Validate risk_score is a number 0-10
            assert isinstance(device["risk_score"], (int, float))
            assert 0 <= device["risk_score"] <= 10
            
            # Validate risk_level is one of expected values
            assert device["risk_level"] in ["Critical", "High", "Moderate", "Low"]
    
    def test_heatmap_returns_incidents_for_clustering(self):
        """Feature 2: Incident Clustering - incidents array with lat/lng for MarkerClusterGroup"""
        resp = requests.get(f"{BASE_URL}/api/operator/location-risk/heatmap", headers=self.headers)
        assert resp.status_code == 200
        data = resp.json()
        
        # Verify incidents array exists
        assert "incidents" in data
        
        # Each incident should have required fields for clustering
        for incident in data["incidents"]:
            assert "lat" in incident
            assert "lng" in incident
            assert "type" in incident
            assert "severity" in incident
            assert "device" in incident
            assert "created_at" in incident
    
    def test_heatmap_incidents_have_severity_for_heat_intensity(self):
        """Feature 3: True Heatmap Layer - incidents have severity for heat intensity calculation"""
        resp = requests.get(f"{BASE_URL}/api/operator/location-risk/heatmap", headers=self.headers)
        assert resp.status_code == 200
        data = resp.json()
        
        incidents = data.get("incidents", [])
        if len(incidents) > 0:
            # Check severity values for heat intensity
            severity_values = {"critical", "high", "medium", "low"}
            for incident in incidents:
                assert incident["severity"] in severity_values, f"Invalid severity: {incident['severity']}"
    
    def test_location_risk_returns_breakdown_with_5_components(self):
        """Feature 1: Risk Breakdown Visualization - 5 components in breakdown object"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/location-risk?lat=12.97&lng=77.59",
            headers=self.headers
        )
        assert resp.status_code == 200
        data = resp.json()
        
        # Verify breakdown object exists
        assert "breakdown" in data
        breakdown = data["breakdown"]
        
        # Must have exactly 5 components
        expected_components = [
            "incident_density",
            "time_of_day",
            "zone_proximity",
            "isolation",
            "history"
        ]
        
        for component in expected_components:
            assert component in breakdown, f"Missing breakdown component: {component}"
            # Each component should be a number 0-10
            assert isinstance(breakdown[component], (int, float))
            assert 0 <= breakdown[component] <= 10
    
    def test_location_risk_returns_safety_score_and_level(self):
        """Feature 5: Alert Animation - risk score for determining high-risk devices (>=5)"""
        resp = requests.get(
            f"{BASE_URL}/api/operator/location-risk?lat=12.97&lng=77.59",
            headers=self.headers
        )
        assert resp.status_code == 200
        data = resp.json()
        
        # Verify safety_score and risk_level
        assert "safety_score" in data
        assert "risk_level" in data
        
        # Safety score should be 0-10
        assert isinstance(data["safety_score"], (int, float))
        assert 0 <= data["safety_score"] <= 10
        
        # Risk level should match score
        score = data["safety_score"]
        level = data["risk_level"]
        if score >= 7:
            assert level == "Critical"
        elif score >= 5:
            assert level == "High"
        elif score >= 3:
            assert level == "Moderate"
        else:
            assert level == "Low"
    
    def test_heatmap_returns_risk_zones(self):
        """Test risk zones are returned for zone circles on map"""
        resp = requests.get(f"{BASE_URL}/api/operator/location-risk/heatmap", headers=self.headers)
        assert resp.status_code == 200
        data = resp.json()
        
        assert "risk_zones" in data
        assert len(data["risk_zones"]) > 0
        
        for zone in data["risk_zones"]:
            assert "lat" in zone
            assert "lng" in zone
            assert "radius" in zone
            assert "risk_score" in zone
            assert "risk_level" in zone
            assert "name" in zone
    
    def test_heatmap_returns_geofences(self):
        """Test geofences are returned for geofence circles on map"""
        resp = requests.get(f"{BASE_URL}/api/operator/location-risk/heatmap", headers=self.headers)
        assert resp.status_code == 200
        data = resp.json()
        
        assert "geofences" in data
        # May have 0 or more geofences
        for gf in data["geofences"]:
            assert "lat" in gf
            assert "lng" in gf
            assert "radius" in gf
            assert "type" in gf
            assert "name" in gf
    
    def test_heatmap_returns_active_alerts(self):
        """Test active alerts are returned for stats bar badge"""
        resp = requests.get(f"{BASE_URL}/api/operator/location-risk/heatmap", headers=self.headers)
        assert resp.status_code == 200
        data = resp.json()
        
        assert "active_alerts" in data
        for alert in data["active_alerts"]:
            assert "alert_type" in alert
            assert "device_identifier" in alert
    
    def test_heatmap_returns_map_center(self):
        """Test map center coordinates are returned"""
        resp = requests.get(f"{BASE_URL}/api/operator/location-risk/heatmap", headers=self.headers)
        assert resp.status_code == 200
        data = resp.json()
        
        assert "center" in data
        assert "lat" in data["center"]
        assert "lng" in data["center"]
        assert "zoom" in data
    
    def test_unauthorized_access_rejected(self):
        """Test API rejects requests without auth token"""
        resp = requests.get(f"{BASE_URL}/api/operator/location-risk/heatmap")
        assert resp.status_code == 401
        
        resp = requests.get(f"{BASE_URL}/api/operator/location-risk?lat=12.97&lng=77.59")
        assert resp.status_code == 401
