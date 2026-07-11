"""
Lead Capture Modal Backend Tests
Tests for POST /api/enquiry endpoint with phone and name from SEO pages
"""
import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestLeadCaptureWithPhone:
    """Tests for POST /api/enquiry with phone number from lead capture modal"""
    
    def test_enquiry_with_phone_women_page(self):
        """Test enquiry with phone from women safety page"""
        unique_phone = f"98765{uuid.uuid4().hex[:5]}"
        response = requests.post(f"{BASE_URL}/api/enquiry", json={
            "source": "seo_page",
            "page": "women",
            "intent": "high",
            "phone": unique_phone,
            "name": "Test User Women",
            "message": "Lead captured from SEO page"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "lead_id" in data
        print(f"Women page with phone: {data}")
    
    def test_enquiry_with_phone_kids_page(self):
        """Test enquiry with phone from kids safety page"""
        unique_phone = f"98765{uuid.uuid4().hex[:5]}"
        response = requests.post(f"{BASE_URL}/api/enquiry", json={
            "source": "seo_page",
            "page": "kids",
            "intent": "high",
            "phone": unique_phone,
            "name": "Test Parent Kids",
            "message": "Lead captured from SEO page"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "lead_id" in data
        print(f"Kids page with phone: {data}")
    
    def test_enquiry_with_phone_family_page(self):
        """Test enquiry with phone from family safety page"""
        unique_phone = f"98765{uuid.uuid4().hex[:5]}"
        response = requests.post(f"{BASE_URL}/api/enquiry", json={
            "source": "seo_page",
            "page": "family",
            "intent": "high",
            "phone": unique_phone,
            "name": "Test User Family",
            "message": "Lead captured from SEO page"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "lead_id" in data
        print(f"Family page with phone: {data}")
    
    def test_enquiry_with_phone_only_no_name(self):
        """Test enquiry with phone but no name (name is optional)"""
        unique_phone = f"98765{uuid.uuid4().hex[:5]}"
        response = requests.post(f"{BASE_URL}/api/enquiry", json={
            "source": "seo_page",
            "page": "women",
            "intent": "high",
            "phone": unique_phone,
            "message": "Lead captured from SEO page"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        print(f"Phone only (no name): {data}")


class TestLeadCaptureSkip:
    """Tests for skip button behavior - no phone/email required for seo_page"""
    
    def test_skip_women_page(self):
        """Test skip from women page - no phone/email"""
        response = requests.post(f"{BASE_URL}/api/enquiry", json={
            "source": "seo_page",
            "page": "women",
            "intent": "high",
            "message": "CTA clicked from SEO page (skipped lead capture)"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["ok", "duplicate"]
        print(f"Skip women page: {data}")
    
    def test_skip_kids_page(self):
        """Test skip from kids page - no phone/email"""
        response = requests.post(f"{BASE_URL}/api/enquiry", json={
            "source": "seo_page",
            "page": "kids",
            "intent": "high",
            "message": "CTA clicked from SEO page (skipped lead capture)"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["ok", "duplicate"]
        print(f"Skip kids page: {data}")
    
    def test_skip_family_page(self):
        """Test skip from family page - no phone/email"""
        response = requests.post(f"{BASE_URL}/api/enquiry", json={
            "source": "seo_page",
            "page": "family",
            "intent": "high",
            "message": "CTA clicked from SEO page (skipped lead capture)"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["ok", "duplicate"]
        print(f"Skip family page: {data}")


class TestLeadCaptureValidation:
    """Tests for validation - regular source still requires phone/email"""
    
    def test_regular_source_requires_contact(self):
        """Test that regular source (not seo_page) requires phone or email"""
        response = requests.post(f"{BASE_URL}/api/enquiry", json={
            "source": "website",
            "message": "Test without contact info"
        })
        # Should fail without phone/email for regular source
        assert response.status_code == 422
        print(f"Regular source validation: {response.status_code}")
    
    def test_regular_source_with_phone_works(self):
        """Test that regular source with phone works"""
        unique_phone = f"98765{uuid.uuid4().hex[:5]}"
        response = requests.post(f"{BASE_URL}/api/enquiry", json={
            "source": "website",
            "phone": unique_phone,
            "message": "Test with phone"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        print(f"Regular source with phone: {data}")
