"""
Funnel Tracking API Tests
Tests for: POST /api/track, POST /api/track/batch, GET /api/funnel-metrics
Tracks: page_view → cta_click → modal_open → lead_submit → whatsapp_redirect
"""
import pytest
import requests
import os
import uuid
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test session ID for tracking
TEST_SESSION_ID = f"TEST_funnel_{uuid.uuid4().hex[:8]}"


class TestFunnelTrackingSingleEvent:
    """Tests for POST /api/track - single event ingestion"""
    
    def test_track_page_view_event(self):
        """Test tracking a page_view event"""
        response = requests.post(f"{BASE_URL}/api/track", json={
            "event": "page_view",
            "page": "women",
            "session_id": TEST_SESSION_ID
        })
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data.get("status") == "ok", f"Expected status: ok, got {data}"
    
    def test_track_cta_click_event(self):
        """Test tracking a cta_click event"""
        response = requests.post(f"{BASE_URL}/api/track", json={
            "event": "cta_click",
            "page": "women",
            "session_id": TEST_SESSION_ID
        })
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"
    
    def test_track_modal_open_event(self):
        """Test tracking a modal_open event"""
        response = requests.post(f"{BASE_URL}/api/track", json={
            "event": "modal_open",
            "page": "kids",
            "session_id": TEST_SESSION_ID
        })
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"
    
    def test_track_lead_submit_event(self):
        """Test tracking a lead_submit event"""
        response = requests.post(f"{BASE_URL}/api/track", json={
            "event": "lead_submit",
            "page": "family",
            "session_id": TEST_SESSION_ID
        })
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"
    
    def test_track_whatsapp_redirect_event(self):
        """Test tracking a whatsapp_redirect event"""
        response = requests.post(f"{BASE_URL}/api/track", json={
            "event": "whatsapp_redirect",
            "page": "women",
            "session_id": TEST_SESSION_ID
        })
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"
    
    def test_track_event_without_page(self):
        """Test tracking event without page (should still work)"""
        response = requests.post(f"{BASE_URL}/api/track", json={
            "event": "page_view",
            "session_id": TEST_SESSION_ID
        })
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"
    
    def test_track_event_without_session_id(self):
        """Test tracking event without session_id (should still work)"""
        response = requests.post(f"{BASE_URL}/api/track", json={
            "event": "page_view",
            "page": "women"
        })
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"


class TestFunnelTrackingBatch:
    """Tests for POST /api/track/batch - batch event ingestion"""
    
    def test_batch_track_multiple_events(self):
        """Test batch tracking multiple events"""
        batch_session = f"TEST_batch_{uuid.uuid4().hex[:8]}"
        events = [
            {"event": "page_view", "page": "women", "session_id": batch_session},
            {"event": "cta_click", "page": "women", "session_id": batch_session},
            {"event": "modal_open", "page": "women", "session_id": batch_session},
        ]
        response = requests.post(f"{BASE_URL}/api/track/batch", json={"events": events})
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data.get("status") == "ok", f"Expected status: ok, got {data}"
        assert data.get("count") == 3, f"Expected count: 3, got {data.get('count')}"
    
    def test_batch_track_empty_events(self):
        """Test batch tracking with empty events array"""
        response = requests.post(f"{BASE_URL}/api/track/batch", json={"events": []})
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"
        assert data.get("count") == 0
    
    def test_batch_track_single_event(self):
        """Test batch tracking with single event"""
        batch_session = f"TEST_single_{uuid.uuid4().hex[:8]}"
        events = [
            {"event": "lead_submit", "page": "kids", "session_id": batch_session}
        ]
        response = requests.post(f"{BASE_URL}/api/track/batch", json={"events": events})
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"
        assert data.get("count") == 1
    
    def test_batch_track_all_funnel_events(self):
        """Test batch tracking complete funnel flow"""
        batch_session = f"TEST_full_funnel_{uuid.uuid4().hex[:8]}"
        events = [
            {"event": "page_view", "page": "family", "session_id": batch_session},
            {"event": "cta_click", "page": "family", "session_id": batch_session},
            {"event": "modal_open", "page": "family", "session_id": batch_session},
            {"event": "lead_submit", "page": "family", "session_id": batch_session},
            {"event": "whatsapp_redirect", "page": "family", "session_id": batch_session},
        ]
        response = requests.post(f"{BASE_URL}/api/track/batch", json={"events": events})
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"
        assert data.get("count") == 5


class TestFunnelMetrics:
    """Tests for GET /api/funnel-metrics - funnel conversion metrics"""
    
    def test_funnel_metrics_basic(self):
        """Test basic funnel metrics endpoint"""
        response = requests.get(f"{BASE_URL}/api/funnel-metrics")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Check funnel object exists with all required fields
        assert "funnel" in data, f"Missing 'funnel' in response: {data}"
        funnel = data["funnel"]
        assert "page_views" in funnel, f"Missing 'page_views' in funnel: {funnel}"
        assert "cta_clicks" in funnel, f"Missing 'cta_clicks' in funnel: {funnel}"
        assert "modal_opens" in funnel, f"Missing 'modal_opens' in funnel: {funnel}"
        assert "leads" in funnel, f"Missing 'leads' in funnel: {funnel}"
        assert "whatsapp_redirects" in funnel, f"Missing 'whatsapp_redirects' in funnel: {funnel}"
    
    def test_funnel_metrics_conversion_rates(self):
        """Test funnel metrics includes conversion rates"""
        response = requests.get(f"{BASE_URL}/api/funnel-metrics")
        assert response.status_code == 200
        data = response.json()
        
        # Check conversion_rates object exists with all required fields
        assert "conversion_rates" in data, f"Missing 'conversion_rates' in response: {data}"
        rates = data["conversion_rates"]
        assert "view_to_click" in rates, f"Missing 'view_to_click' in rates: {rates}"
        assert "click_to_modal" in rates, f"Missing 'click_to_modal' in rates: {rates}"
        assert "modal_to_lead" in rates, f"Missing 'modal_to_lead' in rates: {rates}"
        assert "lead_to_whatsapp" in rates, f"Missing 'lead_to_whatsapp' in rates: {rates}"
        assert "overall" in rates, f"Missing 'overall' in rates: {rates}"
    
    def test_funnel_metrics_by_page(self):
        """Test funnel metrics includes by_page breakdown"""
        response = requests.get(f"{BASE_URL}/api/funnel-metrics")
        assert response.status_code == 200
        data = response.json()
        
        # Check by_page object exists
        assert "by_page" in data, f"Missing 'by_page' in response: {data}"
        assert isinstance(data["by_page"], dict), f"by_page should be dict, got {type(data['by_page'])}"
    
    def test_funnel_metrics_daily_trend(self):
        """Test funnel metrics includes daily_trend"""
        response = requests.get(f"{BASE_URL}/api/funnel-metrics")
        assert response.status_code == 200
        data = response.json()
        
        # Check daily_trend object exists
        assert "daily_trend" in data, f"Missing 'daily_trend' in response: {data}"
        assert isinstance(data["daily_trend"], dict), f"daily_trend should be dict, got {type(data['daily_trend'])}"
    
    def test_funnel_metrics_unique_sessions(self):
        """Test funnel metrics includes unique_sessions count"""
        response = requests.get(f"{BASE_URL}/api/funnel-metrics")
        assert response.status_code == 200
        data = response.json()
        
        # Check unique_sessions exists and is a number
        assert "unique_sessions" in data, f"Missing 'unique_sessions' in response: {data}"
        assert isinstance(data["unique_sessions"], int), f"unique_sessions should be int, got {type(data['unique_sessions'])}"
    
    def test_funnel_metrics_page_filter(self):
        """Test funnel metrics with page filter"""
        response = requests.get(f"{BASE_URL}/api/funnel-metrics?page=women")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Check filter_page is set correctly
        assert data.get("filter_page") == "women", f"Expected filter_page: women, got {data.get('filter_page')}"
        assert "funnel" in data
        assert "conversion_rates" in data
    
    def test_funnel_metrics_days_filter(self):
        """Test funnel metrics with days filter"""
        response = requests.get(f"{BASE_URL}/api/funnel-metrics?days=1")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Check period_days is set correctly
        assert data.get("period_days") == 1, f"Expected period_days: 1, got {data.get('period_days')}"
    
    def test_funnel_metrics_combined_filters(self):
        """Test funnel metrics with both page and days filters"""
        response = requests.get(f"{BASE_URL}/api/funnel-metrics?page=kids&days=3")
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("filter_page") == "kids"
        assert data.get("period_days") == 3


class TestFunnelDataPersistence:
    """Tests to verify data is actually persisted and counted"""
    
    def test_track_and_verify_count_increases(self):
        """Test that tracking events increases the count in metrics"""
        # Get initial metrics
        initial_response = requests.get(f"{BASE_URL}/api/funnel-metrics?days=1")
        assert initial_response.status_code == 200
        initial_data = initial_response.json()
        initial_page_views = initial_data["funnel"]["page_views"]
        
        # Track a new page_view event
        unique_session = f"TEST_persist_{uuid.uuid4().hex[:8]}"
        track_response = requests.post(f"{BASE_URL}/api/track", json={
            "event": "page_view",
            "page": "women",
            "session_id": unique_session
        })
        assert track_response.status_code == 200
        
        # Get updated metrics
        updated_response = requests.get(f"{BASE_URL}/api/funnel-metrics?days=1")
        assert updated_response.status_code == 200
        updated_data = updated_response.json()
        updated_page_views = updated_data["funnel"]["page_views"]
        
        # Verify count increased
        assert updated_page_views >= initial_page_views, f"Page views should have increased: {initial_page_views} -> {updated_page_views}"
    
    def test_batch_track_and_verify_count_increases(self):
        """Test that batch tracking increases counts correctly"""
        # Get initial metrics
        initial_response = requests.get(f"{BASE_URL}/api/funnel-metrics?days=1")
        assert initial_response.status_code == 200
        initial_data = initial_response.json()
        initial_cta_clicks = initial_data["funnel"]["cta_clicks"]
        
        # Track batch of cta_click events
        batch_session = f"TEST_batch_persist_{uuid.uuid4().hex[:8]}"
        events = [
            {"event": "cta_click", "page": "women", "session_id": batch_session},
            {"event": "cta_click", "page": "kids", "session_id": batch_session},
        ]
        track_response = requests.post(f"{BASE_URL}/api/track/batch", json={"events": events})
        assert track_response.status_code == 200
        
        # Get updated metrics
        updated_response = requests.get(f"{BASE_URL}/api/funnel-metrics?days=1")
        assert updated_response.status_code == 200
        updated_data = updated_response.json()
        updated_cta_clicks = updated_data["funnel"]["cta_clicks"]
        
        # Verify count increased by at least 2
        assert updated_cta_clicks >= initial_cta_clicks + 2, f"CTA clicks should have increased by 2: {initial_cta_clicks} -> {updated_cta_clicks}"


class TestFunnelMetricsDataTypes:
    """Tests to verify correct data types in response"""
    
    def test_funnel_counts_are_integers(self):
        """Test that funnel counts are integers"""
        response = requests.get(f"{BASE_URL}/api/funnel-metrics")
        assert response.status_code == 200
        data = response.json()
        funnel = data["funnel"]
        
        assert isinstance(funnel["page_views"], int), f"page_views should be int"
        assert isinstance(funnel["cta_clicks"], int), f"cta_clicks should be int"
        assert isinstance(funnel["modal_opens"], int), f"modal_opens should be int"
        assert isinstance(funnel["leads"], int), f"leads should be int"
        assert isinstance(funnel["whatsapp_redirects"], int), f"whatsapp_redirects should be int"
    
    def test_conversion_rates_are_floats(self):
        """Test that conversion rates are floats"""
        response = requests.get(f"{BASE_URL}/api/funnel-metrics")
        assert response.status_code == 200
        data = response.json()
        rates = data["conversion_rates"]
        
        assert isinstance(rates["view_to_click"], (int, float)), f"view_to_click should be numeric"
        assert isinstance(rates["click_to_modal"], (int, float)), f"click_to_modal should be numeric"
        assert isinstance(rates["modal_to_lead"], (int, float)), f"modal_to_lead should be numeric"
        assert isinstance(rates["lead_to_whatsapp"], (int, float)), f"lead_to_whatsapp should be numeric"
        assert isinstance(rates["overall"], (int, float)), f"overall should be numeric"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
