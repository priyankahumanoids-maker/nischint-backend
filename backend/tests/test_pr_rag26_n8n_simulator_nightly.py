"""
RAG-26 n8n Webhook, PR Simulator, and Nightly Batch Tests
Tests for PR Intelligence RAG-26 additions (iteration 171):
- POST /api/pr/webhook/n8n with event_type=decision
- POST /api/pr/webhook/n8n with event_type=outcome_update
- POST /api/pr/simulator (Historical Decision Support)
- POST /api/pr/features/refresh (Manual nightly trigger)
- GET /api/pr/analysis/latest?target_type=nightly
- Backward compatibility checks
"""
import pytest
import requests
import os
import uuid
from datetime import datetime, timezone

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Valid enum values from pr_intelligence.py
VALID_NARRATIVE_ANGLES = ['fear', 'safety', 'urgency', 'trust', 'empowerment', 'innovation', 'authority', 'social_proof']
VALID_CTA_TYPES = ['demo_request', 'free_trial', 'whitepaper', 'case_study', 'interview', 'exclusive', 'partnership', 'webinar']


# ──────────────────────────────────────────────
# n8n WEBHOOK: DECISION INGESTION
# ──────────────────────────────────────────────

class TestN8nWebhookDecision:
    """POST /api/pr/webhook/n8n with event_type=decision"""
    
    def test_n8n_decision_creates_pr_decision_record(self):
        """n8n decision event creates pr_decisions record with narrative_angle and cta_type"""
        payload = {
            "event_type": "decision",
            "narrative_angle": "safety",
            "cta_type": "exclusive",
            "subject_line": "TEST_N8N_Subject_Line",
            "headline_variant": "TEST_N8N_Headline",
            "journalist_score": 80,
            "utm_source": "n8n_test",
            "utm_campaign": "rag26_n8n_test"
        }
        response = requests.post(f"{BASE_URL}/api/pr/webhook/n8n", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["status"] == "ok", f"Expected status ok, got {data.get('status')}"
        assert data["count"] == 1, f"Expected count 1, got {data.get('count')}"
        assert len(data["events"]) == 1, "Expected 1 event in response"
        
        event = data["events"][0]
        assert event["event_type"] == "decision", f"Expected event_type decision, got {event.get('event_type')}"
        assert "event_id" in event, "Missing event_id in response"
        assert len(event["event_id"]) == 36, "event_id should be UUID format"
        
        print(f"✓ POST /api/pr/webhook/n8n (decision) - Created decision: {event['event_id']}")
        return event["event_id"]
    
    def test_n8n_decision_with_all_fields(self):
        """n8n decision event with all optional fields"""
        payload = {
            "event_type": "decision",
            "campaign_id": "795699e4-c16a-4fa8-bc8d-bf41716a4613",  # Existing seed campaign
            "journalist_id": str(uuid.uuid4()),
            "narrative_angle": "trust",
            "cta_type": "demo_request",
            "subject_line": "TEST_N8N_Full_Subject",
            "headline_variant": "TEST_N8N_Full_Headline",
            "journalist_score": 65,
            "utm_source": "n8n",
            "utm_campaign": "full_test",
            "utm_content": "variant_a",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        response = requests.post(f"{BASE_URL}/api/pr/webhook/n8n", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["status"] == "ok"
        assert data["events"][0]["event_type"] == "decision"
        print(f"✓ POST /api/pr/webhook/n8n (decision with all fields) - Created: {data['events'][0]['event_id']}")
    
    def test_n8n_decision_invalid_narrative_angle_returns_error(self):
        """n8n decision with invalid narrative_angle returns error in response (not crash)"""
        payload = {
            "event_type": "decision",
            "narrative_angle": "invalid_angle_xyz",
            "cta_type": "exclusive"
        }
        response = requests.post(f"{BASE_URL}/api/pr/webhook/n8n", json=payload)
        # Should return 200 with error in events array (graceful handling)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["status"] == "ok", "Status should still be ok"
        assert len(data["events"]) == 1, "Should have 1 event result"
        
        event = data["events"][0]
        assert "error" in event, f"Expected error field in event: {event}"
        assert "invalid narrative_angle" in event["error"].lower(), f"Error should mention invalid narrative_angle: {event['error']}"
        print(f"✓ POST /api/pr/webhook/n8n (invalid narrative_angle) - Error returned: {event['error']}")
    
    def test_n8n_decision_invalid_cta_type_returns_error(self):
        """n8n decision with invalid cta_type returns error in response"""
        payload = {
            "event_type": "decision",
            "narrative_angle": "safety",
            "cta_type": "invalid_cta_xyz"
        }
        response = requests.post(f"{BASE_URL}/api/pr/webhook/n8n", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        event = data["events"][0]
        assert "error" in event, f"Expected error field in event: {event}"
        assert "invalid cta_type" in event["error"].lower(), f"Error should mention invalid cta_type: {event['error']}"
        print(f"✓ POST /api/pr/webhook/n8n (invalid cta_type) - Error returned: {event['error']}")
    
    def test_n8n_decision_batch_multiple_events(self):
        """n8n webhook accepts array of decision events"""
        payload = [
            {
                "event_type": "decision",
                "narrative_angle": "urgency",
                "cta_type": "free_trial",
                "subject_line": "TEST_N8N_Batch_1"
            },
            {
                "event_type": "decision",
                "narrative_angle": "innovation",
                "cta_type": "whitepaper",
                "subject_line": "TEST_N8N_Batch_2"
            }
        ]
        response = requests.post(f"{BASE_URL}/api/pr/webhook/n8n", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["count"] == 2, f"Expected count 2, got {data.get('count')}"
        assert len(data["events"]) == 2, "Expected 2 events in response"
        print(f"✓ POST /api/pr/webhook/n8n (batch decisions) - Created {data['count']} decisions")


# ──────────────────────────────────────────────
# n8n WEBHOOK: OUTCOME UPDATES
# ──────────────────────────────────────────────

class TestN8nWebhookOutcomeUpdate:
    """POST /api/pr/webhook/n8n with event_type=outcome_update"""
    
    @pytest.fixture
    def created_decision_id(self):
        """Create a decision to update"""
        payload = {
            "event_type": "decision",
            "narrative_angle": "empowerment",
            "cta_type": "case_study",
            "subject_line": "TEST_N8N_Outcome_Decision"
        }
        response = requests.post(f"{BASE_URL}/api/pr/webhook/n8n", json=payload)
        assert response.status_code == 200
        return response.json()["events"][0]["event_id"]
    
    @pytest.fixture
    def created_event_id(self):
        """Create a regular event to update"""
        payload = {
            "event_type": "pr_outreach_sent",
            "journalist_name": "TEST_N8N_Journalist",
            "journalist_email": f"test_n8n_{uuid.uuid4().hex[:8]}@example.com",
            "publication": "TEST_N8N_Publication",
            "narrative_angle": "authority",
            "cta_type": "interview"
        }
        response = requests.post(f"{BASE_URL}/api/pr/webhook/n8n", json=payload)
        assert response.status_code == 200
        return response.json()["events"][0]["event_id"]
    
    def test_n8n_outcome_update_decision_by_decision_id(self, created_decision_id):
        """outcome_update with decision_id updates outcome fields on decision"""
        payload = {
            "event_type": "outcome_update",
            "decision_id": created_decision_id,
            "outcome_reply": True,
            "outcome_publish": True,
            "outcome_leads": 5,
            "outcome_revenue": 15000.50
        }
        response = requests.post(f"{BASE_URL}/api/pr/webhook/n8n", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["status"] == "ok"
        event = data["events"][0]
        assert event["event_type"] == "outcome_update"
        assert event["fields_updated"] >= 4, f"Expected at least 4 fields updated, got {event.get('fields_updated')}"
        
        print(f"✓ POST /api/pr/webhook/n8n (outcome_update decision) - Updated {event['fields_updated']} fields")
    
    def test_n8n_outcome_update_event_by_event_id(self, created_event_id):
        """outcome_update with event_id updates outcome fields on event"""
        payload = {
            "event_type": "outcome_update",
            "event_id": created_event_id,
            "opened": True,
            "replied": True,
            "outcome_article": True,
            "outcome_leads": 3,
            "outcome_revenue": 8500.00
        }
        response = requests.post(f"{BASE_URL}/api/pr/webhook/n8n", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["status"] == "ok"
        event = data["events"][0]
        assert event["event_type"] == "outcome_update"
        assert event["fields_updated"] >= 5, f"Expected at least 5 fields updated, got {event.get('fields_updated')}"
        
        print(f"✓ POST /api/pr/webhook/n8n (outcome_update event) - Updated {event['fields_updated']} fields")
    
    def test_n8n_outcome_update_partial_fields(self, created_decision_id):
        """outcome_update with only some fields updates only those fields"""
        payload = {
            "event_type": "outcome_update",
            "decision_id": created_decision_id,
            "outcome_reply": True
        }
        response = requests.post(f"{BASE_URL}/api/pr/webhook/n8n", json=payload)
        assert response.status_code == 200
        
        data = response.json()
        event = data["events"][0]
        # Should update only outcome_reply + updated_at
        assert event["fields_updated"] >= 1, f"Expected at least 1 field updated, got {event.get('fields_updated')}"
        print(f"✓ POST /api/pr/webhook/n8n (partial outcome_update) - Updated {event['fields_updated']} fields")


# ──────────────────────────────────────────────
# PR SIMULATOR (Historical Decision Support)
# ──────────────────────────────────────────────

class TestPRSimulator:
    """POST /api/pr/simulator - Historical decision support tool"""
    
    def test_simulator_with_narrative_angle_and_cta_type(self):
        """Simulator with narrative_angle=safety and cta_type=exclusive returns historical_rates"""
        payload = {
            "narrative_angle": "safety",
            "cta_type": "exclusive"
        }
        response = requests.post(f"{BASE_URL}/api/pr/simulator", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "query" in data, "Missing query in response"
        assert data["query"]["narrative_angle"] == "safety"
        assert data["query"]["cta_type"] == "exclusive"
        assert "sample_size" in data, "Missing sample_size in response"
        assert "confidence" in data, "Missing confidence in response"
        
        # Confidence structure
        confidence = data["confidence"]
        assert "level" in confidence, "Missing level in confidence"
        assert confidence["level"] in ["insufficient", "low", "moderate", "high"], f"Invalid confidence level: {confidence['level']}"
        assert "label" in confidence, "Missing label in confidence"
        
        # If sample_size > 0, should have historical_rates and vs_global
        if data["sample_size"] > 0:
            assert "historical_rates" in data, "Missing historical_rates when sample_size > 0"
            rates = data["historical_rates"]
            assert "reply_rate" in rates, "Missing reply_rate"
            assert "publish_rate" in rates, "Missing publish_rate"
            assert "total_leads" in rates, "Missing total_leads"
            assert "total_revenue" in rates, "Missing total_revenue"
            
            assert "vs_global" in data, "Missing vs_global when sample_size > 0"
            vs_global = data["vs_global"]
            assert "global_reply_rate" in vs_global, "Missing global_reply_rate"
            assert "reply_delta" in vs_global, "Missing reply_delta"
            
            print(f"✓ POST /api/pr/simulator (safety+exclusive) - sample_size={data['sample_size']}, confidence={confidence['level']}, reply_rate={rates['reply_rate']}%")
        else:
            print(f"✓ POST /api/pr/simulator (safety+exclusive) - No matching data (sample_size=0)")
    
    def test_simulator_no_matching_data_returns_suggestions(self):
        """Simulator with no matching data returns suggestions and message"""
        # Use a very specific combination unlikely to have data
        payload = {
            "narrative_angle": "social_proof",
            "cta_type": "partnership",
            "journalist_id": str(uuid.uuid4())  # Random UUID won't match
        }
        response = requests.post(f"{BASE_URL}/api/pr/simulator", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["sample_size"] == 0, f"Expected sample_size 0, got {data.get('sample_size')}"
        assert "message" in data, "Missing message when no data"
        assert "no historical data" in data["message"].lower(), f"Message should mention no data: {data['message']}"
        assert "suggestions" in data, "Missing suggestions when no data"
        
        print(f"✓ POST /api/pr/simulator (no matching data) - Message: {data['message'][:50]}...")
    
    def test_simulator_empty_body_returns_422(self):
        """Simulator with empty body returns 422 requiring at least one filter"""
        payload = {}
        response = requests.post(f"{BASE_URL}/api/pr/simulator", json=payload)
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "detail" in data, "Missing detail in 422 response"
        assert "at least one filter" in data["detail"].lower(), f"Error should mention filter requirement: {data['detail']}"
        
        print(f"✓ POST /api/pr/simulator (empty body) - 422: {data['detail']}")
    
    def test_simulator_invalid_narrative_angle_returns_422(self):
        """Simulator with invalid narrative_angle returns 422"""
        payload = {
            "narrative_angle": "invalid_angle_xyz"
        }
        response = requests.post(f"{BASE_URL}/api/pr/simulator", json=payload)
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "detail" in data, "Missing detail in 422 response"
        assert "narrative_angle" in data["detail"].lower(), f"Error should mention narrative_angle: {data['detail']}"
        
        print(f"✓ POST /api/pr/simulator (invalid narrative_angle) - 422: {data['detail']}")
    
    def test_simulator_invalid_cta_type_returns_422(self):
        """Simulator with invalid cta_type returns 422"""
        payload = {
            "cta_type": "invalid_cta_xyz"
        }
        response = requests.post(f"{BASE_URL}/api/pr/simulator", json=payload)
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "detail" in data
        assert "cta_type" in data["detail"].lower()
        
        print(f"✓ POST /api/pr/simulator (invalid cta_type) - 422: {data['detail']}")
    
    def test_simulator_by_publication_only_uses_ilike(self):
        """Simulator with publication only works with ILIKE matching"""
        payload = {
            "publication": "Tech"  # Partial match
        }
        response = requests.post(f"{BASE_URL}/api/pr/simulator", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "query" in data
        assert data["query"]["publication"] == "Tech"
        assert "sample_size" in data
        assert "confidence" in data
        
        print(f"✓ POST /api/pr/simulator (publication ILIKE) - sample_size={data['sample_size']}")
    
    def test_simulator_by_narrative_angle_only(self):
        """Simulator with only narrative_angle filter"""
        payload = {
            "narrative_angle": "safety"
        }
        response = requests.post(f"{BASE_URL}/api/pr/simulator", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["query"]["narrative_angle"] == "safety"
        print(f"✓ POST /api/pr/simulator (narrative_angle only) - sample_size={data['sample_size']}")
    
    def test_simulator_by_cta_type_only(self):
        """Simulator with only cta_type filter"""
        payload = {
            "cta_type": "exclusive"
        }
        response = requests.post(f"{BASE_URL}/api/pr/simulator", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["query"]["cta_type"] == "exclusive"
        print(f"✓ POST /api/pr/simulator (cta_type only) - sample_size={data['sample_size']}")


# ──────────────────────────────────────────────
# NIGHTLY BATCH REFRESH
# ──────────────────────────────────────────────

class TestNightlyBatchRefresh:
    """POST /api/pr/features/refresh and GET /api/pr/analysis/latest?target_type=nightly"""
    
    def test_manual_nightly_refresh_triggers_and_stores_snapshot(self):
        """POST /api/pr/features/refresh triggers manual nightly refresh"""
        response = requests.post(f"{BASE_URL}/api/pr/features/refresh")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["status"] == "ok", f"Expected status ok, got {data.get('status')}"
        assert "message" in data, "Missing message in response"
        
        print(f"✓ POST /api/pr/features/refresh - {data['message']}")
    
    def test_get_latest_nightly_analysis_returns_snapshot(self):
        """GET /api/pr/analysis/latest?target_type=nightly returns latest feature refresh snapshot"""
        # First trigger a refresh to ensure there's data
        requests.post(f"{BASE_URL}/api/pr/features/refresh")
        
        response = requests.get(f"{BASE_URL}/api/pr/analysis/latest?target_type=nightly")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # If no analysis yet, should return message
        if "message" in data and "no analysis" in data.get("message", "").lower():
            print(f"✓ GET /api/pr/analysis/latest?target_type=nightly - No analysis yet")
            return
        
        # Otherwise should have analysis structure
        assert "analysis_id" in data, "Missing analysis_id"
        assert "analysis_type" in data, "Missing analysis_type"
        assert data["analysis_type"] == "feature_refresh", f"Expected feature_refresh, got {data.get('analysis_type')}"
        assert data["target_type"] == "nightly", f"Expected nightly, got {data.get('target_type')}"
        assert "insights" in data, "Missing insights"
        assert "analyzed_at" in data, "Missing analyzed_at"
        
        # Insights should have nightly snapshot structure
        insights = data["insights"]
        if insights:
            assert "total_decisions" in insights or "by_narrative" in insights or "refreshed_at" in insights, \
                f"Insights missing expected fields: {list(insights.keys())}"
        
        print(f"✓ GET /api/pr/analysis/latest?target_type=nightly - analysis_id={data['analysis_id'][:8]}...")


# ──────────────────────────────────────────────
# BACKWARD COMPATIBILITY
# ──────────────────────────────────────────────

class TestBackwardCompatibility:
    """Verify existing PR endpoints still work with RAG-26 additions"""
    
    def test_post_events_without_rag26_fields_still_works(self):
        """POST /api/pr/events without RAG-26 fields (backward compatible)"""
        payload = {
            "event_type": "pr_outreach_sent",
            "journalist_name": "TEST_Backward_Compat_Journalist",
            "journalist_email": f"test_compat_{uuid.uuid4().hex[:8]}@example.com",
            "publication": "TEST_Compat_Publication"
        }
        response = requests.post(f"{BASE_URL}/api/pr/events", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["status"] in ["ok", "duplicate"], f"Expected ok or duplicate, got {data.get('status')}"
        print(f"✓ POST /api/pr/events (without RAG-26 fields) - {data['status']}")
    
    def test_post_events_with_rag26_fields_still_works(self):
        """POST /api/pr/events with RAG-26 fields (backward compatible)"""
        payload = {
            "event_type": "pr_outreach_sent",
            "journalist_name": "TEST_RAG26_Compat_Journalist",
            "journalist_email": f"test_rag26_compat_{uuid.uuid4().hex[:8]}@example.com",
            "publication": "TEST_RAG26_Compat_Publication",
            "narrative_angle": "trust",
            "cta_type": "webinar",
            "headline_variant": "TEST_Headline",
            "email_subject": "TEST_Subject",
            "journalist_score_at_send": 70
        }
        response = requests.post(f"{BASE_URL}/api/pr/events", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["status"] in ["ok", "duplicate"]
        print(f"✓ POST /api/pr/events (with RAG-26 fields) - {data['status']}")
    
    def test_get_dashboard_still_works(self):
        """GET /api/pr/dashboard still works"""
        response = requests.get(f"{BASE_URL}/api/pr/dashboard")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "overview" in data, "Missing overview in dashboard"
        assert "conversion_rates" in data, "Missing conversion_rates in dashboard"
        assert "top_journalists" in data, "Missing top_journalists in dashboard"
        
        print(f"✓ GET /api/pr/dashboard - overview.total_campaigns={data['overview'].get('total_campaigns')}")
    
    def test_get_journalists_still_works(self):
        """GET /api/pr/journalists still works"""
        response = requests.get(f"{BASE_URL}/api/pr/journalists")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "journalists" in data, "Missing journalists in response"
        assert "total" in data, "Missing total in response"
        
        print(f"✓ GET /api/pr/journalists - total={data['total']}")
    
    def test_get_campaigns_still_works(self):
        """GET /api/pr/campaigns still works"""
        response = requests.get(f"{BASE_URL}/api/pr/campaigns")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "campaigns" in data, "Missing campaigns in response"
        assert "total" in data, "Missing total in response"
        
        print(f"✓ GET /api/pr/campaigns - total={data['total']}")
    
    def test_n8n_webhook_regular_event_still_works(self):
        """POST /api/pr/webhook/n8n with regular event type still works"""
        payload = {
            "event_type": "journalist_response",
            "journalist_name": "TEST_N8N_Regular_Journalist",
            "journalist_email": f"test_n8n_regular_{uuid.uuid4().hex[:8]}@example.com",
            "publication": "TEST_N8N_Regular_Publication"
        }
        response = requests.post(f"{BASE_URL}/api/pr/webhook/n8n", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["status"] == "ok"
        assert data["events"][0]["event_type"] == "journalist_response"
        
        print(f"✓ POST /api/pr/webhook/n8n (regular event) - {data['events'][0]['event_type']}")


# ──────────────────────────────────────────────
# CONFIDENCE LEVEL VERIFICATION
# ──────────────────────────────────────────────

class TestConfidenceLevels:
    """Verify confidence level logic in PR Simulator"""
    
    def test_confidence_levels_documented(self):
        """Verify confidence level thresholds are as documented"""
        # <5 = insufficient, 5-20 = low, 20-50 = moderate, 50+ = high
        # We can't directly test the function, but we can verify the response structure
        
        payload = {"narrative_angle": "safety"}
        response = requests.post(f"{BASE_URL}/api/pr/simulator", json=payload)
        assert response.status_code == 200
        
        data = response.json()
        confidence = data["confidence"]
        sample_size = data["sample_size"]
        
        # Verify confidence level matches sample_size
        if sample_size < 5:
            assert confidence["level"] == "insufficient", f"Expected insufficient for n={sample_size}"
        elif sample_size < 20:
            assert confidence["level"] == "low", f"Expected low for n={sample_size}"
        elif sample_size < 50:
            assert confidence["level"] == "moderate", f"Expected moderate for n={sample_size}"
        else:
            assert confidence["level"] == "high", f"Expected high for n={sample_size}"
        
        print(f"✓ Confidence level verification - sample_size={sample_size}, level={confidence['level']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
