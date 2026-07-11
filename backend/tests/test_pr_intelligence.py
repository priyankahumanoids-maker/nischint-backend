"""
PR Intelligence & Attribution Engine API Tests
Tests for: POST /api/pr/campaigns, POST /api/pr/events, POST /api/pr/events/batch,
POST /api/pr/webhook/n8n, GET /api/pr/dashboard, GET /api/pr/journalists,
GET /api/pr/campaigns, GET /api/pr/campaigns/{id}, GET /api/pr/attribution,
GET /api/pr/analysis/latest
"""
import pytest
import requests
import os
import uuid
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestPRCampaigns:
    """PR Campaign CRUD tests"""
    
    def test_create_campaign_success(self):
        """POST /api/pr/campaigns - create a new campaign"""
        payload = {
            "name": f"TEST_Campaign_{uuid.uuid4().hex[:8]}",
            "description": "Test campaign for PR Intelligence",
            "narrative_angle": "AI-powered safety for families",
            "target_publications": ["TechCrunch", "Forbes", "YourStory"]
        }
        response = requests.post(f"{BASE_URL}/api/pr/campaigns", json=payload)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data.get("status") == "ok", f"Expected status 'ok', got {data}"
        assert "campaign_id" in data, f"Response missing campaign_id: {data}"
        assert isinstance(data["campaign_id"], str), "campaign_id should be a string"
        assert len(data["campaign_id"]) > 0, "campaign_id should not be empty"
        print(f"Created campaign: {data['campaign_id']}")
        return data["campaign_id"]
    
    def test_list_campaigns(self):
        """GET /api/pr/campaigns - list all campaigns with counters"""
        response = requests.get(f"{BASE_URL}/api/pr/campaigns")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "campaigns" in data, f"Response missing 'campaigns': {data}"
        assert "total" in data, f"Response missing 'total': {data}"
        assert isinstance(data["campaigns"], list), "campaigns should be a list"
        
        # Verify campaign structure if any exist
        if len(data["campaigns"]) > 0:
            camp = data["campaigns"][0]
            required_fields = ["campaign_id", "name", "total_outreach", "total_responses", 
                            "total_articles", "total_leads", "total_revenue"]
            for field in required_fields:
                assert field in camp, f"Campaign missing field '{field}': {camp}"
        
        print(f"Found {data['total']} campaigns")
        return data
    
    def test_get_campaign_detail(self):
        """GET /api/pr/campaigns/{campaign_id} - get campaign detail with events"""
        # First get list of campaigns
        list_resp = requests.get(f"{BASE_URL}/api/pr/campaigns")
        campaigns = list_resp.json().get("campaigns", [])
        
        if len(campaigns) == 0:
            pytest.skip("No campaigns available to test detail endpoint")
        
        campaign_id = campaigns[0]["campaign_id"]
        response = requests.get(f"{BASE_URL}/api/pr/campaigns/{campaign_id}")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert "campaign_id" in data, f"Response missing campaign_id: {data}"
        assert "name" in data, f"Response missing name: {data}"
        assert "metrics" in data, f"Response missing metrics: {data}"
        assert "recent_events" in data, f"Response missing recent_events: {data}"
        
        # Verify metrics structure
        metrics = data["metrics"]
        metric_fields = ["outreach", "responses", "articles", "leads", "revenue", 
                        "response_rate", "coverage_rate", "conversion_rate"]
        for field in metric_fields:
            assert field in metrics, f"Metrics missing field '{field}': {metrics}"
        
        print(f"Campaign detail: {data['name']} with {len(data['recent_events'])} events")
        return data
    
    def test_get_campaign_not_found(self):
        """GET /api/pr/campaigns/{invalid_id} - returns 404"""
        fake_id = str(uuid.uuid4())
        response = requests.get(f"{BASE_URL}/api/pr/campaigns/{fake_id}")
        
        assert response.status_code == 404, f"Expected 404, got {response.status_code}: {response.text}"


class TestPREvents:
    """PR Event ingestion tests"""
    
    def test_ingest_single_event(self):
        """POST /api/pr/events - ingest a single PR event"""
        # Use unique email to avoid dedup
        unique_email = f"test_{uuid.uuid4().hex[:8]}@example.com"
        payload = {
            "event_type": "pr_outreach_sent",
            "campaign_id": "795699e4-c16a-4fa8-bc8d-bf41716a4613",  # Pre-seeded campaign
            "journalist_name": "Test Journalist",
            "journalist_email": unique_email,
            "publication": "Test Publication",
            "metadata": {"test": True}
        }
        response = requests.post(f"{BASE_URL}/api/pr/events", json=payload)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data.get("status") == "ok", f"Expected status 'ok', got {data}"
        assert "event_id" in data, f"Response missing event_id: {data}"
        assert data.get("event_type") == "pr_outreach_sent", f"Wrong event_type: {data}"
        
        print(f"Ingested event: {data['event_id']}")
        return data
    
    def test_event_deduplication(self):
        """POST /api/pr/events - verify deduplication within 5 minutes"""
        # Use same email for both requests
        unique_email = f"dedup_test_{uuid.uuid4().hex[:8]}@example.com"
        payload = {
            "event_type": "pr_outreach_sent",
            "campaign_id": "795699e4-c16a-4fa8-bc8d-bf41716a4613",
            "journalist_name": "Dedup Test",
            "journalist_email": unique_email,
            "publication": "Dedup Publication"
        }
        
        # First request should succeed
        resp1 = requests.post(f"{BASE_URL}/api/pr/events", json=payload)
        assert resp1.status_code == 200, f"First request failed: {resp1.text}"
        data1 = resp1.json()
        assert data1.get("status") == "ok", f"First request not ok: {data1}"
        
        # Second request within 5 minutes should be deduplicated
        resp2 = requests.post(f"{BASE_URL}/api/pr/events", json=payload)
        assert resp2.status_code == 200, f"Second request failed: {resp2.text}"
        data2 = resp2.json()
        assert data2.get("status") == "duplicate", f"Expected 'duplicate' status, got: {data2}"
        
        print("Deduplication working correctly")
    
    def test_batch_event_ingestion(self):
        """POST /api/pr/events/batch - batch ingest multiple events"""
        campaign_id = "795699e4-c16a-4fa8-bc8d-bf41716a4613"
        batch_id = uuid.uuid4().hex[:8]
        
        events = [
            {
                "event_type": "pr_outreach_sent",
                "campaign_id": campaign_id,
                "journalist_name": f"Batch Journalist 1 {batch_id}",
                "journalist_email": f"batch1_{batch_id}@example.com",
                "publication": "Batch Pub 1"
            },
            {
                "event_type": "journalist_response",
                "campaign_id": campaign_id,
                "journalist_name": f"Batch Journalist 2 {batch_id}",
                "journalist_email": f"batch2_{batch_id}@example.com",
                "publication": "Batch Pub 2"
            },
            {
                "event_type": "article_published",
                "campaign_id": campaign_id,
                "journalist_name": f"Batch Journalist 3 {batch_id}",
                "journalist_email": f"batch3_{batch_id}@example.com",
                "publication": "Batch Pub 3",
                "article_url": f"https://example.com/article-{batch_id}",
                "article_title": f"Test Article {batch_id}"
            },
            {
                "event_type": "lead_generated",
                "campaign_id": campaign_id,
                "journalist_name": f"Batch Journalist 4 {batch_id}",
                "journalist_email": f"batch4_{batch_id}@example.com",
                "lead_id": str(uuid.uuid4()),
                "utm_source": "pr",
                "utm_campaign": "test_batch"
            },
            {
                "event_type": "conversion",
                "campaign_id": campaign_id,
                "journalist_name": f"Batch Journalist 5 {batch_id}",
                "journalist_email": f"batch5_{batch_id}@example.com",
                "lead_id": str(uuid.uuid4()),
                "revenue": 1500.00
            }
        ]
        
        response = requests.post(f"{BASE_URL}/api/pr/events/batch", json={"events": events})
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data.get("status") == "ok", f"Expected status 'ok', got {data}"
        assert data.get("count") == 5, f"Expected 5 events processed, got {data.get('count')}"
        assert "events" in data, f"Response missing 'events': {data}"
        assert len(data["events"]) == 5, f"Expected 5 events in response, got {len(data['events'])}"
        
        # Verify each event has event_id and event_type
        for ev in data["events"]:
            assert "event_id" in ev, f"Event missing event_id: {ev}"
            assert "event_type" in ev, f"Event missing event_type: {ev}"
        
        print(f"Batch ingested {data['count']} events")
        return data


class TestN8NWebhook:
    """n8n webhook integration tests"""
    
    def test_n8n_webhook_single_event(self):
        """POST /api/pr/webhook/n8n - accepts flexible JSON format"""
        webhook_id = uuid.uuid4().hex[:8]
        payload = {
            "type": "pr_outreach_sent",  # Using 'type' instead of 'event_type'
            "campaign_id": "795699e4-c16a-4fa8-bc8d-bf41716a4613",
            "journalist": f"N8N Journalist {webhook_id}",  # Using 'journalist' instead of 'journalist_name'
            "email": f"n8n_{webhook_id}@example.com",  # Using 'email' instead of 'journalist_email'
            "publication": "N8N Publication"
        }
        
        response = requests.post(f"{BASE_URL}/api/pr/webhook/n8n", json=payload)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data.get("status") == "ok", f"Expected status 'ok', got {data}"
        assert data.get("count") == 1, f"Expected 1 event, got {data.get('count')}"
        
        print(f"N8N webhook processed: {data}")
    
    def test_n8n_webhook_array_events(self):
        """POST /api/pr/webhook/n8n - accepts array of events"""
        webhook_id = uuid.uuid4().hex[:8]
        payload = [
            {
                "event_type": "pr_outreach_sent",
                "journalist_name": f"N8N Array 1 {webhook_id}",
                "journalist_email": f"n8n_arr1_{webhook_id}@example.com"
            },
            {
                "type": "journalist_response",
                "name": f"N8N Array 2 {webhook_id}",
                "email": f"n8n_arr2_{webhook_id}@example.com"
            }
        ]
        
        response = requests.post(f"{BASE_URL}/api/pr/webhook/n8n", json=payload)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data.get("status") == "ok", f"Expected status 'ok', got {data}"
        assert data.get("count") == 2, f"Expected 2 events, got {data.get('count')}"
        
        print(f"N8N webhook array processed: {data['count']} events")


class TestPRDashboard:
    """CEO Dashboard API tests"""
    
    def test_dashboard_default(self):
        """GET /api/pr/dashboard - returns CEO dashboard with all sections"""
        response = requests.get(f"{BASE_URL}/api/pr/dashboard")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Verify all required sections
        required_sections = ["period_days", "overview", "conversion_rates", 
                           "top_journalists", "top_campaigns", "daily_trend"]
        for section in required_sections:
            assert section in data, f"Dashboard missing section '{section}': {data.keys()}"
        
        # Verify overview structure
        overview = data["overview"]
        overview_fields = ["total_campaigns", "total_outreach", "total_responses",
                         "articles_published", "leads_generated", "revenue_influenced"]
        for field in overview_fields:
            assert field in overview, f"Overview missing field '{field}': {overview}"
        
        # Verify conversion_rates structure
        rates = data["conversion_rates"]
        rate_fields = ["outreach_to_response", "response_to_article", 
                      "article_to_lead", "overall_pr_roi"]
        for field in rate_fields:
            assert field in rates, f"Conversion rates missing field '{field}': {rates}"
        
        # Verify top_journalists is a list
        assert isinstance(data["top_journalists"], list), "top_journalists should be a list"
        
        # Verify top_campaigns is a list
        assert isinstance(data["top_campaigns"], list), "top_campaigns should be a list"
        
        # Verify daily_trend is a dict
        assert isinstance(data["daily_trend"], dict), "daily_trend should be a dict"
        
        print(f"Dashboard: {overview['total_campaigns']} campaigns, {overview['total_outreach']} outreach, ${overview['revenue_influenced']} revenue")
        return data
    
    def test_dashboard_with_days_filter(self):
        """GET /api/pr/dashboard?days=7 - respects days filter"""
        response = requests.get(f"{BASE_URL}/api/pr/dashboard?days=7")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data.get("period_days") == 7, f"Expected period_days=7, got {data.get('period_days')}"
        
        print(f"Dashboard 7-day filter working")


class TestJournalists:
    """Journalist ranking API tests"""
    
    def test_list_journalists_default(self):
        """GET /api/pr/journalists - returns ranked journalist list"""
        response = requests.get(f"{BASE_URL}/api/pr/journalists")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert "journalists" in data, f"Response missing 'journalists': {data}"
        assert "total" in data, f"Response missing 'total': {data}"
        assert isinstance(data["journalists"], list), "journalists should be a list"
        
        # Verify journalist structure if any exist
        if len(data["journalists"]) > 0:
            j = data["journalists"][0]
            required_fields = ["journalist_id", "name", "score", "priority", "metrics"]
            for field in required_fields:
                assert field in j, f"Journalist missing field '{field}': {j}"
            
            # Verify metrics structure
            metrics = j["metrics"]
            metric_fields = ["pitches", "responses", "articles", "leads", "revenue",
                           "response_rate", "publication_rate"]
            for field in metric_fields:
                assert field in metrics, f"Journalist metrics missing field '{field}': {metrics}"
        
        print(f"Found {data['total']} journalists")
        return data
    
    def test_list_journalists_sort_by_revenue(self):
        """GET /api/pr/journalists?sort_by=revenue - sorts by revenue"""
        response = requests.get(f"{BASE_URL}/api/pr/journalists?sort_by=revenue")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Verify sorting (revenue should be descending)
        journalists = data.get("journalists", [])
        if len(journalists) >= 2:
            for i in range(len(journalists) - 1):
                rev1 = journalists[i]["metrics"]["revenue"]
                rev2 = journalists[i + 1]["metrics"]["revenue"]
                assert rev1 >= rev2, f"Journalists not sorted by revenue: {rev1} < {rev2}"
        
        print("Journalist revenue sorting working")


class TestAttribution:
    """Revenue attribution API tests"""
    
    def test_attribution_by_journalist(self):
        """GET /api/pr/attribution?group_by=journalist - groups by journalist"""
        response = requests.get(f"{BASE_URL}/api/pr/attribution?group_by=journalist")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert data.get("group_by") == "journalist", f"Expected group_by='journalist', got {data.get('group_by')}"
        assert "period_days" in data, f"Response missing 'period_days': {data}"
        assert "attributions" in data, f"Response missing 'attributions': {data}"
        assert isinstance(data["attributions"], list), "attributions should be a list"
        
        # Verify attribution structure if any exist
        if len(data["attributions"]) > 0:
            attr = data["attributions"][0]
            assert "leads" in attr, f"Attribution missing 'leads': {attr}"
            assert "revenue" in attr, f"Attribution missing 'revenue': {attr}"
        
        print(f"Attribution by journalist: {len(data['attributions'])} entries")
        return data
    
    def test_attribution_by_campaign(self):
        """GET /api/pr/attribution?group_by=campaign - groups by campaign"""
        response = requests.get(f"{BASE_URL}/api/pr/attribution?group_by=campaign")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert data.get("group_by") == "campaign", f"Expected group_by='campaign', got {data.get('group_by')}"
        assert "attributions" in data, f"Response missing 'attributions': {data}"
        
        print(f"Attribution by campaign: {len(data['attributions'])} entries")
    
    def test_attribution_by_publication(self):
        """GET /api/pr/attribution?group_by=publication - groups by publication"""
        response = requests.get(f"{BASE_URL}/api/pr/attribution?group_by=publication")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert data.get("group_by") == "publication", f"Expected group_by='publication', got {data.get('group_by')}"
        assert "attributions" in data, f"Response missing 'attributions': {data}"
        
        print(f"Attribution by publication: {len(data['attributions'])} entries")


class TestAIAnalysis:
    """AI Analysis API tests"""
    
    def test_get_latest_analysis(self):
        """GET /api/pr/analysis/latest - returns latest AI analysis (may be empty)"""
        response = requests.get(f"{BASE_URL}/api/pr/analysis/latest")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert "status" in data or "analysis_id" in data, f"Response missing expected fields: {data}"
        
        if data.get("status") == "ok" and data.get("message") == "No analysis available yet":
            print("No AI analysis available yet (expected for fresh system)")
        elif "insights" in data:
            print(f"AI analysis found: {data.get('analysis_id', 'N/A')}")
        
        return data


class TestEndToEndFlow:
    """End-to-end PR flow tests"""
    
    def test_full_pr_flow(self):
        """Test complete PR flow: Campaign -> Events -> Dashboard -> Attribution"""
        flow_id = uuid.uuid4().hex[:8]
        
        # 1. Create campaign
        campaign_payload = {
            "name": f"TEST_E2E_Campaign_{flow_id}",
            "description": "End-to-end test campaign",
            "narrative_angle": "Safety innovation story"
        }
        camp_resp = requests.post(f"{BASE_URL}/api/pr/campaigns", json=campaign_payload)
        assert camp_resp.status_code == 200, f"Campaign creation failed: {camp_resp.text}"
        campaign_id = camp_resp.json()["campaign_id"]
        print(f"1. Created campaign: {campaign_id}")
        
        # 2. Ingest outreach event
        outreach_payload = {
            "event_type": "pr_outreach_sent",
            "campaign_id": campaign_id,
            "journalist_name": f"E2E Journalist {flow_id}",
            "journalist_email": f"e2e_{flow_id}@example.com",
            "publication": "E2E Publication"
        }
        outreach_resp = requests.post(f"{BASE_URL}/api/pr/events", json=outreach_payload)
        assert outreach_resp.status_code == 200, f"Outreach event failed: {outreach_resp.text}"
        print(f"2. Ingested outreach event")
        
        # 3. Ingest response event (different email to avoid dedup)
        response_payload = {
            "event_type": "journalist_response",
            "campaign_id": campaign_id,
            "journalist_name": f"E2E Journalist {flow_id}",
            "journalist_email": f"e2e_resp_{flow_id}@example.com",
            "publication": "E2E Publication"
        }
        resp_resp = requests.post(f"{BASE_URL}/api/pr/events", json=response_payload)
        assert resp_resp.status_code == 200, f"Response event failed: {resp_resp.text}"
        print(f"3. Ingested response event")
        
        # 4. Verify campaign counters updated
        camp_detail = requests.get(f"{BASE_URL}/api/pr/campaigns/{campaign_id}")
        assert camp_detail.status_code == 200, f"Campaign detail failed: {camp_detail.text}"
        metrics = camp_detail.json()["metrics"]
        assert metrics["outreach"] >= 1, f"Outreach counter not updated: {metrics}"
        print(f"4. Campaign counters: outreach={metrics['outreach']}, responses={metrics['responses']}")
        
        # 5. Verify dashboard includes new data
        dash_resp = requests.get(f"{BASE_URL}/api/pr/dashboard")
        assert dash_resp.status_code == 200, f"Dashboard failed: {dash_resp.text}"
        print(f"5. Dashboard accessible")
        
        # 6. Verify attribution endpoint works
        attr_resp = requests.get(f"{BASE_URL}/api/pr/attribution?group_by=campaign")
        assert attr_resp.status_code == 200, f"Attribution failed: {attr_resp.text}"
        print(f"6. Attribution endpoint working")
        
        print("End-to-end PR flow completed successfully!")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
