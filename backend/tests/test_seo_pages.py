"""
SEO Landing Pages Backend Tests
Tests for POST /api/enquiry endpoint and sitemap.xml
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestEnquiryAPI:
    """Tests for POST /api/enquiry endpoint with SEO page source"""
    
    def test_enquiry_women_page(self):
        """Test enquiry from women safety page"""
        response = requests.post(f"{BASE_URL}/api/enquiry", json={
            "source": "seo_page",
            "page": "women",
            "intent": "high",
            "message": "CTA clicked from SEO page"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["ok", "duplicate"]
        assert "lead_id" in data
        print(f"Women page enquiry: {data}")
    
    def test_enquiry_kids_page(self):
        """Test enquiry from kids safety page"""
        response = requests.post(f"{BASE_URL}/api/enquiry", json={
            "source": "seo_page",
            "page": "kids",
            "intent": "high",
            "message": "CTA clicked from SEO page"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["ok", "duplicate"]
        assert "lead_id" in data
        print(f"Kids page enquiry: {data}")
    
    def test_enquiry_family_page(self):
        """Test enquiry from family safety page"""
        response = requests.post(f"{BASE_URL}/api/enquiry", json={
            "source": "seo_page",
            "page": "family",
            "intent": "high",
            "message": "CTA clicked from SEO page"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["ok", "duplicate"]
        assert "lead_id" in data
        print(f"Family page enquiry: {data}")
    
    def test_enquiry_seo_page_no_phone_email_required(self):
        """Test that seo_page source doesn't require phone or email"""
        response = requests.post(f"{BASE_URL}/api/enquiry", json={
            "source": "seo_page",
            "page": "women",
            "intent": "high",
            "message": "Test without phone/email"
        })
        # Should succeed without phone/email for seo_page source
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["ok", "duplicate"]
    
    def test_enquiry_regular_source_requires_contact(self):
        """Test that regular source requires phone or email"""
        response = requests.post(f"{BASE_URL}/api/enquiry", json={
            "source": "website",
            "message": "Test without contact info"
        })
        # Should fail without phone/email for regular source
        assert response.status_code == 422  # Validation error


class TestSitemap:
    """Tests for sitemap.xml endpoint"""
    
    def test_sitemap_returns_xml(self):
        """Test that sitemap.xml returns valid XML"""
        # Use localhost to bypass CDN cache
        response = requests.get("http://localhost:8001/sitemap.xml")
        assert response.status_code == 200
        assert "application/xml" in response.headers.get("content-type", "")
        assert '<?xml version="1.0"' in response.text
    
    def test_sitemap_contains_women_safety_url(self):
        """Test sitemap contains women-safety-app URL"""
        response = requests.get("http://localhost:8001/sitemap.xml")
        assert response.status_code == 200
        assert "https://nischint.care/women-safety-app" in response.text
    
    def test_sitemap_contains_kids_safety_url(self):
        """Test sitemap contains kids-safety-app URL"""
        response = requests.get("http://localhost:8001/sitemap.xml")
        assert response.status_code == 200
        assert "https://nischint.care/kids-safety-app" in response.text
    
    def test_sitemap_contains_family_safety_url(self):
        """Test sitemap contains family-safety-app URL"""
        response = requests.get("http://localhost:8001/sitemap.xml")
        assert response.status_code == 200
        assert "https://nischint.care/family-safety-app" in response.text


class TestHealthCheck:
    """Basic health check tests"""
    
    def test_api_health(self):
        """Test API health endpoint"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
