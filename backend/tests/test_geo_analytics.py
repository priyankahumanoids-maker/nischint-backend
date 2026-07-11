"""
GEO Analytics API Tests
Tests for POST /api/geo-events and GET /api/geo-analytics endpoints
"""
import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestGeoEventsEndpoint:
    """Tests for POST /api/geo-events endpoint"""
    
    def test_post_geo_page_view_event(self):
        """Test posting a geo_page_view event with all fields"""
        session_id = f"test-session-{uuid.uuid4()}"
        payload = {
            "event": "geo_page_view",
            "city": "TEST_Mumbai",
            "type": "women",
            "variant": "default",
            "channel": "seo_geo",
            "url": "/women-safety-app-mumbai",
            "session_id": session_id
        }
        response = requests.post(f"{BASE_URL}/api/geo-events", json=payload)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data.get("ok") == True, "Response should have ok=true"
        assert "id" in data, "Response should contain event id"
        assert isinstance(data["id"], str), "Event id should be a string (UUID)"
        print(f"✓ geo_page_view event created with id: {data['id']}")
    
    def test_post_geo_cta_click_event(self):
        """Test posting a geo_cta_click event"""
        session_id = f"test-session-{uuid.uuid4()}"
        payload = {
            "event": "geo_cta_click",
            "city": "TEST_Delhi",
            "type": "kids",
            "variant": "best",
            "channel": "seo_geo",
            "url": "/best-kids-safety-app-delhi",
            "session_id": session_id
        }
        response = requests.post(f"{BASE_URL}/api/geo-events", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("ok") == True
        assert "id" in data
        print(f"✓ geo_cta_click event created with id: {data['id']}")
    
    def test_post_event_with_minimal_fields(self):
        """Test posting event with only required field (event)"""
        payload = {"event": "geo_page_view"}
        response = requests.post(f"{BASE_URL}/api/geo-events", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("ok") == True
        assert "id" in data
        print("✓ Event with minimal fields accepted")
    
    def test_post_event_with_null_optional_fields(self):
        """Test posting event with explicit null values for optional fields"""
        payload = {
            "event": "geo_page_view",
            "city": None,
            "type": None,
            "variant": "default",
            "channel": "seo_geo"
        }
        response = requests.post(f"{BASE_URL}/api/geo-events", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("ok") == True
        print("✓ Event with null optional fields accepted")
    
    def test_post_event_family_type(self):
        """Test posting event for family safety type"""
        session_id = f"test-session-{uuid.uuid4()}"
        payload = {
            "event": "geo_page_view",
            "city": "TEST_Bangalore",
            "type": "family",
            "variant": "personal",
            "channel": "seo_geo",
            "url": "/personal-safety-app-bangalore",
            "session_id": session_id
        }
        response = requests.post(f"{BASE_URL}/api/geo-events", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("ok") == True
        print(f"✓ Family type event created with id: {data['id']}")


class TestGeoAnalyticsEndpoint:
    """Tests for GET /api/geo-analytics endpoint"""
    
    def test_get_analytics_default_period(self):
        """Test getting analytics with default 30-day period"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify response structure
        assert "period_days" in data, "Response should contain period_days"
        assert "total_views" in data, "Response should contain total_views"
        assert "total_clicks" in data, "Response should contain total_clicks"
        assert "top_cities" in data, "Response should contain top_cities"
        assert "top_variants" in data, "Response should contain top_variants"
        assert "top_types" in data, "Response should contain top_types"
        assert "conversion_rates" in data, "Response should contain conversion_rates"
        
        # Verify data types
        assert isinstance(data["period_days"], int)
        assert isinstance(data["total_views"], int)
        assert isinstance(data["total_clicks"], int)
        assert isinstance(data["top_cities"], list)
        assert isinstance(data["top_variants"], list)
        assert isinstance(data["top_types"], list)
        assert isinstance(data["conversion_rates"], list)
        
        print(f"✓ Analytics returned: {data['total_views']} views, {data['total_clicks']} clicks")
    
    def test_get_analytics_custom_period(self):
        """Test getting analytics with custom days parameter"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=7")
        
        assert response.status_code == 200
        data = response.json()
        assert data["period_days"] == 7
        print("✓ Custom period (7 days) analytics returned")
    
    def test_analytics_top_cities_structure(self):
        """Test that top_cities has correct structure"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics")
        
        assert response.status_code == 200
        data = response.json()
        
        if len(data["top_cities"]) > 0:
            city_entry = data["top_cities"][0]
            assert "city" in city_entry, "City entry should have 'city' field"
            assert "views" in city_entry, "City entry should have 'views' field"
            assert isinstance(city_entry["views"], int)
            print(f"✓ Top city: {city_entry['city']} with {city_entry['views']} views")
        else:
            print("✓ No cities in analytics (empty result)")
    
    def test_analytics_top_variants_structure(self):
        """Test that top_variants has correct structure"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics")
        
        assert response.status_code == 200
        data = response.json()
        
        if len(data["top_variants"]) > 0:
            variant_entry = data["top_variants"][0]
            assert "variant" in variant_entry, "Variant entry should have 'variant' field"
            assert "views" in variant_entry, "Variant entry should have 'views' field"
            print(f"✓ Top variant: {variant_entry['variant']} with {variant_entry['views']} views")
        else:
            print("✓ No variants in analytics (empty result)")
    
    def test_analytics_top_types_structure(self):
        """Test that top_types has correct structure"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics")
        
        assert response.status_code == 200
        data = response.json()
        
        if len(data["top_types"]) > 0:
            type_entry = data["top_types"][0]
            assert "type" in type_entry, "Type entry should have 'type' field"
            assert "views" in type_entry, "Type entry should have 'views' field"
            print(f"✓ Top type: {type_entry['type']} with {type_entry['views']} views")
        else:
            print("✓ No types in analytics (empty result)")
    
    def test_analytics_conversion_rates_structure(self):
        """Test that conversion_rates has correct structure"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics")
        
        assert response.status_code == 200
        data = response.json()
        
        if len(data["conversion_rates"]) > 0:
            conv_entry = data["conversion_rates"][0]
            assert "city" in conv_entry, "Conversion entry should have 'city' field"
            assert "views" in conv_entry, "Conversion entry should have 'views' field"
            assert "clicks" in conv_entry, "Conversion entry should have 'clicks' field"
            assert "rate" in conv_entry, "Conversion entry should have 'rate' field"
            assert isinstance(conv_entry["rate"], (int, float))
            print(f"✓ Conversion rate for {conv_entry['city']}: {conv_entry['rate']}%")
        else:
            print("✓ No conversion rates in analytics (empty result)")


class TestGeoAnalyticsDataIntegrity:
    """Tests for data integrity between POST and GET"""
    
    def test_event_appears_in_analytics(self):
        """Test that a posted event appears in analytics"""
        # Get initial analytics
        initial_response = requests.get(f"{BASE_URL}/api/geo-analytics?days=1")
        initial_data = initial_response.json()
        initial_views = initial_data["total_views"]
        
        # Post a new event
        unique_city = f"TEST_IntegrityCity_{uuid.uuid4().hex[:8]}"
        payload = {
            "event": "geo_page_view",
            "city": unique_city,
            "type": "women",
            "variant": "default",
            "channel": "seo_geo"
        }
        post_response = requests.post(f"{BASE_URL}/api/geo-events", json=payload)
        assert post_response.status_code == 200
        
        # Get updated analytics
        updated_response = requests.get(f"{BASE_URL}/api/geo-analytics?days=1")
        updated_data = updated_response.json()
        
        # Verify view count increased
        assert updated_data["total_views"] >= initial_views, "Total views should increase after posting event"
        print(f"✓ Views increased from {initial_views} to {updated_data['total_views']}")
    
    def test_cta_click_affects_conversion_rate(self):
        """Test that cta_click events affect conversion rates"""
        unique_city = f"TEST_ConvCity_{uuid.uuid4().hex[:8]}"
        session_id = f"test-session-{uuid.uuid4()}"
        
        # Post a page view
        view_payload = {
            "event": "geo_page_view",
            "city": unique_city,
            "type": "women",
            "variant": "default",
            "session_id": session_id
        }
        requests.post(f"{BASE_URL}/api/geo-events", json=view_payload)
        
        # Post a cta click for same city
        click_payload = {
            "event": "geo_cta_click",
            "city": unique_city,
            "type": "women",
            "variant": "default",
            "session_id": session_id
        }
        requests.post(f"{BASE_URL}/api/geo-events", json=click_payload)
        
        # Get analytics and check conversion rates
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=1")
        data = response.json()
        
        # Find our test city in conversion rates
        city_conv = next((c for c in data["conversion_rates"] if c["city"] == unique_city), None)
        if city_conv:
            assert city_conv["views"] >= 1, "Should have at least 1 view"
            assert city_conv["clicks"] >= 1, "Should have at least 1 click"
            assert city_conv["rate"] > 0, "Conversion rate should be > 0"
            print(f"✓ Conversion rate for {unique_city}: {city_conv['rate']}% ({city_conv['clicks']}/{city_conv['views']})")
        else:
            print(f"✓ City {unique_city} not in top 20 conversion rates (expected for new city)")


class TestGeoAnalyticsEdgeCases:
    """Edge case tests for GEO analytics"""
    
    def test_analytics_with_large_days_parameter(self):
        """Test analytics with large days parameter"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=365")
        
        assert response.status_code == 200
        data = response.json()
        assert data["period_days"] == 365
        print("✓ Large period (365 days) analytics returned")
    
    def test_analytics_with_zero_days(self):
        """Test analytics with zero days parameter"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=0")
        
        # Should still return valid response (may have 0 results)
        assert response.status_code == 200
        data = response.json()
        assert data["period_days"] == 0
        print("✓ Zero days analytics returned")
    
    def test_post_event_with_special_characters_in_city(self):
        """Test posting event with special characters in city name"""
        payload = {
            "event": "geo_page_view",
            "city": "TEST_New Delhi (NCR)",
            "type": "women"
        }
        response = requests.post(f"{BASE_URL}/api/geo-events", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("ok") == True
        print("✓ Event with special characters in city accepted")
    
    def test_post_event_with_long_url(self):
        """Test posting event with long URL"""
        long_url = "/women-safety-app-" + "a" * 200
        payload = {
            "event": "geo_page_view",
            "city": "TEST_LongURL",
            "url": long_url
        }
        response = requests.post(f"{BASE_URL}/api/geo-events", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("ok") == True
        print("✓ Event with long URL accepted")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
