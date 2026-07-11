"""
GEO Analytics Enhanced API Tests
Tests for enhanced GET /api/geo-analytics endpoint with new filter params and response fields:
- Filter params: city, variant, type
- New response fields: daily_trend, recent_events, conversion_by_variant, filter_options
"""
import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestGeoAnalyticsNewResponseFields:
    """Tests for new response fields in GET /api/geo-analytics"""
    
    def test_response_contains_daily_trend(self):
        """Test that response contains daily_trend field"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=7")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "daily_trend" in data, "Response should contain daily_trend"
        assert isinstance(data["daily_trend"], dict), "daily_trend should be a dict"
        
        # If there's data, verify structure
        if data["daily_trend"]:
            for day, events in data["daily_trend"].items():
                assert isinstance(events, dict), f"Events for {day} should be a dict"
                print(f"✓ Daily trend for {day}: {events}")
        else:
            print("✓ daily_trend field present (empty)")
    
    def test_response_contains_recent_events(self):
        """Test that response contains recent_events field"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=7")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "recent_events" in data, "Response should contain recent_events"
        assert isinstance(data["recent_events"], list), "recent_events should be a list"
        
        # If there's data, verify structure
        if data["recent_events"]:
            event = data["recent_events"][0]
            assert "event" in event, "Event should have 'event' field"
            assert "city" in event, "Event should have 'city' field"
            assert "type" in event, "Event should have 'type' field"
            assert "variant" in event, "Event should have 'variant' field"
            assert "url" in event, "Event should have 'url' field"
            assert "created_at" in event, "Event should have 'created_at' field"
            print(f"✓ Recent event: {event['event']} in {event['city']} at {event['created_at']}")
        else:
            print("✓ recent_events field present (empty)")
    
    def test_response_contains_conversion_by_variant(self):
        """Test that response contains conversion_by_variant field"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=7")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "conversion_by_variant" in data, "Response should contain conversion_by_variant"
        assert isinstance(data["conversion_by_variant"], list), "conversion_by_variant should be a list"
        
        # If there's data, verify structure
        if data["conversion_by_variant"]:
            variant_conv = data["conversion_by_variant"][0]
            assert "variant" in variant_conv, "Should have 'variant' field"
            assert "views" in variant_conv, "Should have 'views' field"
            assert "clicks" in variant_conv, "Should have 'clicks' field"
            assert "rate" in variant_conv, "Should have 'rate' field"
            print(f"✓ Conversion by variant: {variant_conv['variant']} - {variant_conv['rate']}%")
        else:
            print("✓ conversion_by_variant field present (empty)")
    
    def test_response_contains_filter_options(self):
        """Test that response contains filter_options field"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "filter_options" in data, "Response should contain filter_options"
        assert isinstance(data["filter_options"], dict), "filter_options should be a dict"
        
        filter_opts = data["filter_options"]
        assert "cities" in filter_opts, "filter_options should have 'cities'"
        assert "variants" in filter_opts, "filter_options should have 'variants'"
        assert "types" in filter_opts, "filter_options should have 'types'"
        
        assert isinstance(filter_opts["cities"], list), "cities should be a list"
        assert isinstance(filter_opts["variants"], list), "variants should be a list"
        assert isinstance(filter_opts["types"], list), "types should be a list"
        
        print(f"✓ Filter options: {len(filter_opts['cities'])} cities, {len(filter_opts['variants'])} variants, {len(filter_opts['types'])} types")


class TestGeoAnalyticsCityFilter:
    """Tests for city filter parameter"""
    
    def test_filter_by_city_mumbai(self):
        """Test filtering results by city=Mumbai"""
        # First ensure we have Mumbai data
        payload = {
            "event": "geo_page_view",
            "city": "Mumbai",
            "type": "women",
            "variant": "default"
        }
        requests.post(f"{BASE_URL}/api/geo-events", json=payload)
        
        # Get filtered analytics
        response = requests.get(f"{BASE_URL}/api/geo-analytics?city=Mumbai&days=7")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify only Mumbai data is returned
        if data["top_cities"]:
            for city_entry in data["top_cities"]:
                assert city_entry["city"] == "Mumbai", f"Expected only Mumbai, got {city_entry['city']}"
        
        if data["conversion_rates"]:
            for conv in data["conversion_rates"]:
                assert conv["city"] == "Mumbai", f"Expected only Mumbai in conversion_rates"
        
        print(f"✓ City filter working: {data['total_views']} views for Mumbai")
    
    def test_filter_by_nonexistent_city(self):
        """Test filtering by a city that doesn't exist"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?city=NonExistentCity123&days=7")
        
        assert response.status_code == 200
        data = response.json()
        
        # Should return empty results
        assert data["total_views"] == 0, "Should have 0 views for nonexistent city"
        assert data["total_clicks"] == 0, "Should have 0 clicks for nonexistent city"
        assert len(data["top_cities"]) == 0, "Should have no cities"
        print("✓ Nonexistent city filter returns empty results")


class TestGeoAnalyticsVariantFilter:
    """Tests for variant filter parameter"""
    
    def test_filter_by_variant_best(self):
        """Test filtering results by variant=best"""
        # First ensure we have 'best' variant data
        payload = {
            "event": "geo_page_view",
            "city": "TEST_VariantCity",
            "type": "women",
            "variant": "best"
        }
        requests.post(f"{BASE_URL}/api/geo-events", json=payload)
        
        # Get filtered analytics
        response = requests.get(f"{BASE_URL}/api/geo-analytics?variant=best&days=7")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify only 'best' variant data is returned
        if data["top_variants"]:
            for variant_entry in data["top_variants"]:
                assert variant_entry["variant"] == "best", f"Expected only 'best', got {variant_entry['variant']}"
        
        print(f"✓ Variant filter working: {data['total_views']} views for 'best' variant")
    
    def test_filter_by_variant_default(self):
        """Test filtering results by variant=default"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?variant=default&days=7")
        
        assert response.status_code == 200
        data = response.json()
        
        if data["top_variants"]:
            for variant_entry in data["top_variants"]:
                assert variant_entry["variant"] == "default"
        
        print(f"✓ Default variant filter: {data['total_views']} views")


class TestGeoAnalyticsTypeFilter:
    """Tests for type filter parameter"""
    
    def test_filter_by_type_women(self):
        """Test filtering results by type=women"""
        # First ensure we have 'women' type data
        payload = {
            "event": "geo_page_view",
            "city": "TEST_TypeCity",
            "type": "women",
            "variant": "default"
        }
        requests.post(f"{BASE_URL}/api/geo-events", json=payload)
        
        # Get filtered analytics
        response = requests.get(f"{BASE_URL}/api/geo-analytics?type=women&days=7")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify only 'women' type data is returned
        if data["top_types"]:
            for type_entry in data["top_types"]:
                assert type_entry["type"] == "women", f"Expected only 'women', got {type_entry['type']}"
        
        print(f"✓ Type filter working: {data['total_views']} views for 'women' type")
    
    def test_filter_by_type_kids(self):
        """Test filtering results by type=kids"""
        # First ensure we have 'kids' type data
        payload = {
            "event": "geo_page_view",
            "city": "TEST_KidsCity",
            "type": "kids",
            "variant": "default"
        }
        requests.post(f"{BASE_URL}/api/geo-events", json=payload)
        
        response = requests.get(f"{BASE_URL}/api/geo-analytics?type=kids&days=7")
        
        assert response.status_code == 200
        data = response.json()
        
        if data["top_types"]:
            for type_entry in data["top_types"]:
                assert type_entry["type"] == "kids"
        
        print(f"✓ Kids type filter: {data['total_views']} views")
    
    def test_filter_by_type_family(self):
        """Test filtering results by type=family"""
        # First ensure we have 'family' type data
        payload = {
            "event": "geo_page_view",
            "city": "TEST_FamilyCity",
            "type": "family",
            "variant": "default"
        }
        requests.post(f"{BASE_URL}/api/geo-events", json=payload)
        
        response = requests.get(f"{BASE_URL}/api/geo-analytics?type=family&days=7")
        
        assert response.status_code == 200
        data = response.json()
        
        if data["top_types"]:
            for type_entry in data["top_types"]:
                assert type_entry["type"] == "family"
        
        print(f"✓ Family type filter: {data['total_views']} views")


class TestGeoAnalyticsDaysFilter:
    """Tests for days filter parameter"""
    
    def test_filter_by_days_1_today_only(self):
        """Test filtering results by days=1 (today only)"""
        # Post an event for today
        payload = {
            "event": "geo_page_view",
            "city": "TEST_TodayCity",
            "type": "women",
            "variant": "default"
        }
        requests.post(f"{BASE_URL}/api/geo-events", json=payload)
        
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=1")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["period_days"] == 1, "Period should be 1 day"
        assert data["total_views"] >= 1, "Should have at least 1 view for today"
        
        print(f"✓ Today filter (days=1): {data['total_views']} views, {data['total_clicks']} clicks")
    
    def test_filter_by_days_30(self):
        """Test filtering results by days=30"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["period_days"] == 30
        print(f"✓ 30-day filter: {data['total_views']} views")


class TestGeoAnalyticsCombinedFilters:
    """Tests for combining multiple filter parameters"""
    
    def test_combined_city_and_variant_filter(self):
        """Test combining city and variant filters"""
        # Create specific test data
        unique_city = f"TEST_CombinedCity_{uuid.uuid4().hex[:6]}"
        payload = {
            "event": "geo_page_view",
            "city": unique_city,
            "type": "women",
            "variant": "best"
        }
        requests.post(f"{BASE_URL}/api/geo-events", json=payload)
        
        # Filter by both city and variant
        response = requests.get(f"{BASE_URL}/api/geo-analytics?city={unique_city}&variant=best&days=1")
        
        assert response.status_code == 200
        data = response.json()
        
        # Should have exactly 1 view
        assert data["total_views"] >= 1, "Should have at least 1 view"
        print(f"✓ Combined city+variant filter: {data['total_views']} views")
    
    def test_combined_type_and_days_filter(self):
        """Test combining type and days filters"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?type=women&days=7")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["period_days"] == 7
        if data["top_types"]:
            for t in data["top_types"]:
                assert t["type"] == "women"
        
        print(f"✓ Combined type+days filter: {data['total_views']} views")
    
    def test_all_filters_combined(self):
        """Test combining all filter parameters"""
        # Create specific test data
        unique_city = f"TEST_AllFilters_{uuid.uuid4().hex[:6]}"
        payload = {
            "event": "geo_page_view",
            "city": unique_city,
            "type": "kids",
            "variant": "personal"
        }
        requests.post(f"{BASE_URL}/api/geo-events", json=payload)
        
        # Apply all filters
        response = requests.get(
            f"{BASE_URL}/api/geo-analytics?city={unique_city}&variant=personal&type=kids&days=1"
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["total_views"] >= 1
        print(f"✓ All filters combined: {data['total_views']} views")


class TestGeoAnalyticsDailyTrendData:
    """Tests for daily_trend data structure and content"""
    
    def test_daily_trend_has_correct_date_format(self):
        """Test that daily_trend keys are in YYYY-MM-DD format"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=7")
        
        assert response.status_code == 200
        data = response.json()
        
        if data["daily_trend"]:
            for day_key in data["daily_trend"].keys():
                # Verify date format YYYY-MM-DD
                parts = day_key.split("-")
                assert len(parts) == 3, f"Date should be YYYY-MM-DD format, got {day_key}"
                assert len(parts[0]) == 4, "Year should be 4 digits"
                assert len(parts[1]) == 2, "Month should be 2 digits"
                assert len(parts[2]) == 2, "Day should be 2 digits"
            print(f"✓ Daily trend has {len(data['daily_trend'])} days with correct format")
        else:
            print("✓ Daily trend empty (no data)")
    
    def test_daily_trend_contains_event_counts(self):
        """Test that daily_trend contains event type counts"""
        # Post events to ensure data
        payload = {
            "event": "geo_page_view",
            "city": "TEST_TrendCity",
            "type": "women"
        }
        requests.post(f"{BASE_URL}/api/geo-events", json=payload)
        
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=1")
        
        assert response.status_code == 200
        data = response.json()
        
        if data["daily_trend"]:
            for day, events in data["daily_trend"].items():
                # Events should be a dict with event types as keys
                assert isinstance(events, dict)
                for event_type, count in events.items():
                    assert event_type in ["geo_page_view", "geo_cta_click"], f"Unknown event type: {event_type}"
                    assert isinstance(count, int), "Count should be integer"
                    assert count >= 0, "Count should be non-negative"
            print(f"✓ Daily trend contains valid event counts")


class TestGeoAnalyticsRecentEventsData:
    """Tests for recent_events data structure"""
    
    def test_recent_events_limited_to_25(self):
        """Test that recent_events returns max 25 events"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        
        assert response.status_code == 200
        data = response.json()
        
        assert len(data["recent_events"]) <= 25, "recent_events should be limited to 25"
        print(f"✓ Recent events count: {len(data['recent_events'])} (max 25)")
    
    def test_recent_events_ordered_by_created_at_desc(self):
        """Test that recent_events are ordered by created_at descending"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=7")
        
        assert response.status_code == 200
        data = response.json()
        
        if len(data["recent_events"]) > 1:
            # Verify descending order
            for i in range(len(data["recent_events"]) - 1):
                current = data["recent_events"][i]["created_at"]
                next_event = data["recent_events"][i + 1]["created_at"]
                assert current >= next_event, "Events should be in descending order by created_at"
            print("✓ Recent events are in descending order")
        else:
            print("✓ Not enough events to verify order")
    
    def test_recent_events_have_timestamp(self):
        """Test that recent_events have valid ISO timestamp"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=7")
        
        assert response.status_code == 200
        data = response.json()
        
        if data["recent_events"]:
            for event in data["recent_events"]:
                assert event["created_at"] is not None, "created_at should not be null"
                # Should be ISO format with T separator
                assert "T" in event["created_at"], "Timestamp should be ISO format"
            print("✓ All recent events have valid timestamps")


class TestGeoAnalyticsFilterOptions:
    """Tests for filter_options data"""
    
    def test_filter_options_cities_are_distinct(self):
        """Test that filter_options.cities contains distinct values"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        
        assert response.status_code == 200
        data = response.json()
        
        cities = data["filter_options"]["cities"]
        assert len(cities) == len(set(cities)), "Cities should be distinct"
        print(f"✓ {len(cities)} distinct cities in filter options")
    
    def test_filter_options_variants_are_distinct(self):
        """Test that filter_options.variants contains distinct values"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        
        assert response.status_code == 200
        data = response.json()
        
        variants = data["filter_options"]["variants"]
        assert len(variants) == len(set(variants)), "Variants should be distinct"
        print(f"✓ {len(variants)} distinct variants in filter options")
    
    def test_filter_options_types_are_distinct(self):
        """Test that filter_options.types contains distinct values"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        
        assert response.status_code == 200
        data = response.json()
        
        types = data["filter_options"]["types"]
        assert len(types) == len(set(types)), "Types should be distinct"
        print(f"✓ {len(types)} distinct types in filter options")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
