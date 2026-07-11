"""
Dashboard Card Improvements Test Suite
======================================
Tests for:
1. GET /api/dashboard/summary — family-scoped data with correct field names
2. GET /api/dashboard/family-users — returns seniors with full_name, age, status
3. GET /api/dashboard/family-devices — returns devices with device_identifier, device_type, status, last_seen, senior_name
4. Mother and Father GET /api/dashboard/summary must return identical numbers
5. Mother and Father GET /api/dashboard/family-users must return same count
6. Mother and Father GET /api/dashboard/family-devices must return same count
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
MOTHER_EMAIL = "mothernischint@gmail.com"
MOTHER_PASSWORD = "nischint123"
FATHER_EMAIL = "fathernishchint@gmail.com"
FATHER_PASSWORD = "nischint123"


class TestDashboardCardImprovements:
    """Tests for dashboard card improvements and family scope"""
    
    @pytest.fixture(scope="class")
    def mother_token(self):
        """Get Mother's auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": MOTHER_EMAIL,
            "password": MOTHER_PASSWORD
        })
        assert response.status_code == 200, f"Mother login failed: {response.text}"
        data = response.json()
        return data.get("access_token")
    
    @pytest.fixture(scope="class")
    def father_token(self):
        """Get Father's auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": FATHER_EMAIL,
            "password": FATHER_PASSWORD
        })
        assert response.status_code == 200, f"Father login failed: {response.text}"
        data = response.json()
        return data.get("access_token")
    
    # ============= GET /api/dashboard/summary Tests =============
    
    def test_summary_endpoint_status(self, mother_token):
        """Test /dashboard/summary returns 200"""
        response = requests.get(
            f"{BASE_URL}/api/dashboard/summary",
            headers={"Authorization": f"Bearer {mother_token}"}
        )
        assert response.status_code == 200, f"Summary endpoint failed: {response.text}"
        print(f"✓ GET /dashboard/summary returns 200")
    
    def test_summary_field_names(self, mother_token):
        """Test summary returns correct field names"""
        response = requests.get(
            f"{BASE_URL}/api/dashboard/summary",
            headers={"Authorization": f"Bearer {mother_token}"}
        )
        data = response.json()
        required_fields = ["total_seniors", "total_devices", "active_incidents", 
                          "critical_incidents", "devices_online", "devices_offline"]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"
        print(f"✓ Summary has all required fields: {list(data.keys())}")
    
    def test_mother_father_summary_identical(self, mother_token, father_token):
        """Test Mother and Father see identical summary data (family scope)"""
        mother_resp = requests.get(
            f"{BASE_URL}/api/dashboard/summary",
            headers={"Authorization": f"Bearer {mother_token}"}
        )
        father_resp = requests.get(
            f"{BASE_URL}/api/dashboard/summary",
            headers={"Authorization": f"Bearer {father_token}"}
        )
        
        mother_data = mother_resp.json()
        father_data = father_resp.json()
        
        print(f"Mother summary: {mother_data}")
        print(f"Father summary: {father_data}")
        
        # All fields should be identical for family scope
        assert mother_data["total_seniors"] == father_data["total_seniors"], \
            f"total_seniors mismatch: Mother={mother_data['total_seniors']}, Father={father_data['total_seniors']}"
        assert mother_data["total_devices"] == father_data["total_devices"], \
            f"total_devices mismatch: Mother={mother_data['total_devices']}, Father={father_data['total_devices']}"
        assert mother_data["active_incidents"] == father_data["active_incidents"], \
            f"active_incidents mismatch: Mother={mother_data['active_incidents']}, Father={father_data['active_incidents']}"
        assert mother_data["critical_incidents"] == father_data["critical_incidents"], \
            f"critical_incidents mismatch: Mother={mother_data['critical_incidents']}, Father={father_data['critical_incidents']}"
        
        print(f"✓ Mother and Father see IDENTICAL summary data (family scope verified)")
    
    # ============= GET /api/dashboard/family-users Tests =============
    
    def test_family_users_endpoint_status(self, mother_token):
        """Test /dashboard/family-users returns 200"""
        response = requests.get(
            f"{BASE_URL}/api/dashboard/family-users",
            headers={"Authorization": f"Bearer {mother_token}"}
        )
        assert response.status_code == 200, f"Family-users endpoint failed: {response.text}"
        print(f"✓ GET /dashboard/family-users returns 200")
    
    def test_family_users_field_names(self, mother_token):
        """Test family-users returns correct field names: full_name, age, status"""
        response = requests.get(
            f"{BASE_URL}/api/dashboard/family-users",
            headers={"Authorization": f"Bearer {mother_token}"}
        )
        data = response.json()
        assert isinstance(data, list), "family-users should return a list"
        
        if len(data) > 0:
            user = data[0]
            assert "full_name" in user, "Missing field: full_name"
            assert "age" in user, "Missing field: age"
            assert "status" in user, "Missing field: status"
            print(f"✓ Family user has required fields: {list(user.keys())}")
        else:
            print("⚠ No family users found (empty list)")
    
    def test_mother_father_family_users_identical_count(self, mother_token, father_token):
        """Test Mother and Father see same family-users count"""
        mother_resp = requests.get(
            f"{BASE_URL}/api/dashboard/family-users",
            headers={"Authorization": f"Bearer {mother_token}"}
        )
        father_resp = requests.get(
            f"{BASE_URL}/api/dashboard/family-users",
            headers={"Authorization": f"Bearer {father_token}"}
        )
        
        mother_data = mother_resp.json()
        father_data = father_resp.json()
        
        print(f"Mother family-users count: {len(mother_data)}")
        print(f"Father family-users count: {len(father_data)}")
        
        assert len(mother_data) == len(father_data), \
            f"family-users count mismatch: Mother={len(mother_data)}, Father={len(father_data)}"
        
        print(f"✓ Mother and Father see IDENTICAL family-users count: {len(mother_data)}")
    
    # ============= GET /api/dashboard/family-devices Tests =============
    
    def test_family_devices_endpoint_status(self, mother_token):
        """Test /dashboard/family-devices returns 200"""
        response = requests.get(
            f"{BASE_URL}/api/dashboard/family-devices",
            headers={"Authorization": f"Bearer {mother_token}"}
        )
        assert response.status_code == 200, f"Family-devices endpoint failed: {response.text}"
        print(f"✓ GET /dashboard/family-devices returns 200")
    
    def test_family_devices_field_names(self, mother_token):
        """Test family-devices returns correct field names: device_identifier, device_type, status, last_seen, senior_name"""
        response = requests.get(
            f"{BASE_URL}/api/dashboard/family-devices",
            headers={"Authorization": f"Bearer {mother_token}"}
        )
        data = response.json()
        assert isinstance(data, list), "family-devices should return a list"
        
        if len(data) > 0:
            device = data[0]
            expected_fields = ["device_identifier", "device_type", "status", "last_seen", "senior_name"]
            for field in expected_fields:
                assert field in device, f"Missing field: {field}"
            print(f"✓ Family device has required fields: {list(device.keys())}")
        else:
            print("⚠ No family devices found (empty list)")
    
    def test_mother_father_family_devices_identical_count(self, mother_token, father_token):
        """Test Mother and Father see same family-devices count"""
        mother_resp = requests.get(
            f"{BASE_URL}/api/dashboard/family-devices",
            headers={"Authorization": f"Bearer {mother_token}"}
        )
        father_resp = requests.get(
            f"{BASE_URL}/api/dashboard/family-devices",
            headers={"Authorization": f"Bearer {father_token}"}
        )
        
        mother_data = mother_resp.json()
        father_data = father_resp.json()
        
        print(f"Mother family-devices count: {len(mother_data)}")
        print(f"Father family-devices count: {len(father_data)}")
        
        assert len(mother_data) == len(father_data), \
            f"family-devices count mismatch: Mother={len(mother_data)}, Father={len(father_data)}"
        
        print(f"✓ Mother and Father see IDENTICAL family-devices count: {len(mother_data)}")
    
    # ============= Summary Match with Endpoint Counts =============
    
    def test_summary_total_seniors_matches_family_users(self, mother_token):
        """Verify summary.total_seniors matches family-users count"""
        summary_resp = requests.get(
            f"{BASE_URL}/api/dashboard/summary",
            headers={"Authorization": f"Bearer {mother_token}"}
        )
        users_resp = requests.get(
            f"{BASE_URL}/api/dashboard/family-users",
            headers={"Authorization": f"Bearer {mother_token}"}
        )
        
        summary = summary_resp.json()
        users = users_resp.json()
        
        assert summary["total_seniors"] == len(users), \
            f"total_seniors ({summary['total_seniors']}) != family-users count ({len(users)})"
        print(f"✓ summary.total_seniors ({summary['total_seniors']}) matches family-users count")
    
    def test_summary_total_devices_matches_family_devices(self, mother_token):
        """Verify summary.total_devices matches family-devices count"""
        summary_resp = requests.get(
            f"{BASE_URL}/api/dashboard/summary",
            headers={"Authorization": f"Bearer {mother_token}"}
        )
        devices_resp = requests.get(
            f"{BASE_URL}/api/dashboard/family-devices",
            headers={"Authorization": f"Bearer {mother_token}"}
        )
        
        summary = summary_resp.json()
        devices = devices_resp.json()
        
        assert summary["total_devices"] == len(devices), \
            f"total_devices ({summary['total_devices']}) != family-devices count ({len(devices)})"
        print(f"✓ summary.total_devices ({summary['total_devices']}) matches family-devices count")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
