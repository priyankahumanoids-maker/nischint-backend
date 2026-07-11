"""
RAG-26 Predictive Decision Engine Tests
Tests for PR Intelligence RAG-26 additions:
- Decisions CRUD with enum validation
- Event outcome tracking
- Features summary aggregation
- Backward compatibility
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


class TestEnumsEndpoint:
    """GET /api/pr/enums - Returns valid enum values"""
    
    def test_get_enums_returns_narrative_angles(self):
        """Verify narrative_angles array is returned"""
        response = requests.get(f"{BASE_URL}/api/pr/enums")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "narrative_angles" in data, "Missing narrative_angles in response"
        assert isinstance(data["narrative_angles"], list), "narrative_angles should be a list"
        assert len(data["narrative_angles"]) == 8, f"Expected 8 narrative_angles, got {len(data['narrative_angles'])}"
        assert set(data["narrative_angles"]) == set(VALID_NARRATIVE_ANGLES), "narrative_angles mismatch"
        print(f"✓ GET /api/pr/enums - narrative_angles: {data['narrative_angles']}")
    
    def test_get_enums_returns_cta_types(self):
        """Verify cta_types array is returned"""
        response = requests.get(f"{BASE_URL}/api/pr/enums")
        assert response.status_code == 200
        
        data = response.json()
        assert "cta_types" in data, "Missing cta_types in response"
        assert isinstance(data["cta_types"], list), "cta_types should be a list"
        assert len(data["cta_types"]) == 8, f"Expected 8 cta_types, got {len(data['cta_types'])}"
        assert set(data["cta_types"]) == set(VALID_CTA_TYPES), "cta_types mismatch"
        print(f"✓ GET /api/pr/enums - cta_types: {data['cta_types']}")


class TestDecisionsCRUD:
    """POST/GET/PATCH /api/pr/decisions - Decision recording and outcome tracking"""
    
    def test_create_decision_with_valid_enums(self):
        """POST /api/pr/decisions - Create decision with valid narrative_angle and cta_type"""
        payload = {
            "narrative_angle": "safety",
            "cta_type": "exclusive",
            "subject_line": "TEST_RAG26_Subject_Line",
            "headline_variant": "TEST_RAG26_Headline",
            "journalist_score": 75,
            "utm_source": "test",
            "utm_campaign": "rag26_test"
        }
        response = requests.post(f"{BASE_URL}/api/pr/decisions", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["status"] == "ok", f"Expected status ok, got {data.get('status')}"
        assert "decision_id" in data, "Missing decision_id in response"
        assert len(data["decision_id"]) == 36, "decision_id should be UUID format"
        print(f"✓ POST /api/pr/decisions - Created decision: {data['decision_id']}")
        return data["decision_id"]
    
    def test_create_decision_invalid_narrative_angle_returns_422(self):
        """POST /api/pr/decisions - 422 on invalid narrative_angle enum value"""
        payload = {
            "narrative_angle": "invalid_angle_xyz",
            "cta_type": "exclusive"
        }
        response = requests.post(f"{BASE_URL}/api/pr/decisions", json=payload)
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "detail" in data, "Missing detail in 422 response"
        assert "narrative_angle" in data["detail"].lower(), f"Error should mention narrative_angle: {data['detail']}"
        print(f"✓ POST /api/pr/decisions - 422 on invalid narrative_angle: {data['detail']}")
    
    def test_create_decision_invalid_cta_type_returns_422(self):
        """POST /api/pr/decisions - 422 on invalid cta_type enum value"""
        payload = {
            "narrative_angle": "trust",
            "cta_type": "invalid_cta_xyz"
        }
        response = requests.post(f"{BASE_URL}/api/pr/decisions", json=payload)
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "detail" in data, "Missing detail in 422 response"
        assert "cta_type" in data["detail"].lower(), f"Error should mention cta_type: {data['detail']}"
        print(f"✓ POST /api/pr/decisions - 422 on invalid cta_type: {data['detail']}")
    
    def test_update_decision_outcome(self):
        """PATCH /api/pr/decisions/{id} - Update outcome fields"""
        # First create a decision
        create_payload = {
            "narrative_angle": "urgency",
            "cta_type": "demo_request",
            "subject_line": "TEST_RAG26_Outcome_Update"
        }
        create_resp = requests.post(f"{BASE_URL}/api/pr/decisions", json=create_payload)
        assert create_resp.status_code == 200
        decision_id = create_resp.json()["decision_id"]
        
        # Update outcome fields
        update_payload = {
            "outcome_reply": True,
            "outcome_publish": True,
            "outcome_leads": 5,
            "outcome_revenue": 2500.50
        }
        response = requests.patch(f"{BASE_URL}/api/pr/decisions/{decision_id}", json=update_payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["status"] == "ok"
        assert data["decision_id"] == decision_id
        assert data["updated_fields"] == 4, f"Expected 4 updated fields, got {data.get('updated_fields')}"
        print(f"✓ PATCH /api/pr/decisions/{decision_id} - Updated 4 outcome fields")
        
        # Verify by fetching decisions
        list_resp = requests.get(f"{BASE_URL}/api/pr/decisions")
        assert list_resp.status_code == 200
        decisions = list_resp.json()["decisions"]
        updated_decision = next((d for d in decisions if d["decision_id"] == decision_id), None)
        assert updated_decision is not None, "Decision not found in list"
        assert updated_decision["outcome_reply"] == True
        assert updated_decision["outcome_publish"] == True
        assert updated_decision["outcome_leads"] == 5
        assert updated_decision["outcome_revenue"] == 2500.50
        print(f"✓ Verified outcome fields persisted correctly")
    
    def test_update_decision_nonexistent_returns_404(self):
        """PATCH /api/pr/decisions/{invalid_id} - 404 on non-existent decision"""
        fake_id = str(uuid.uuid4())
        update_payload = {"outcome_reply": True}
        response = requests.patch(f"{BASE_URL}/api/pr/decisions/{fake_id}", json=update_payload)
        assert response.status_code == 404, f"Expected 404, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "detail" in data
        print(f"✓ PATCH /api/pr/decisions/{fake_id} - 404 on non-existent decision")
    
    def test_list_decisions(self):
        """GET /api/pr/decisions - List all decisions"""
        response = requests.get(f"{BASE_URL}/api/pr/decisions")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "decisions" in data, "Missing decisions in response"
        assert "total" in data, "Missing total in response"
        assert isinstance(data["decisions"], list)
        print(f"✓ GET /api/pr/decisions - Listed {data['total']} decisions")
    
    def test_list_decisions_filter_by_narrative_angle(self):
        """GET /api/pr/decisions?narrative_angle=safety - Filter by narrative_angle"""
        # First create a decision with safety angle
        create_payload = {
            "narrative_angle": "safety",
            "cta_type": "whitepaper",
            "subject_line": "TEST_RAG26_Filter_Safety"
        }
        requests.post(f"{BASE_URL}/api/pr/decisions", json=create_payload)
        
        # Filter by safety
        response = requests.get(f"{BASE_URL}/api/pr/decisions?narrative_angle=safety")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "decisions" in data
        # All returned decisions should have narrative_angle=safety
        for d in data["decisions"]:
            assert d["narrative_angle"] == "safety", f"Expected safety, got {d['narrative_angle']}"
        print(f"✓ GET /api/pr/decisions?narrative_angle=safety - Filtered {data['total']} decisions")
    
    def test_list_decisions_filter_by_cta_type(self):
        """GET /api/pr/decisions?cta_type=exclusive - Filter by cta_type"""
        # First create a decision with exclusive cta
        create_payload = {
            "narrative_angle": "innovation",
            "cta_type": "exclusive",
            "subject_line": "TEST_RAG26_Filter_Exclusive"
        }
        requests.post(f"{BASE_URL}/api/pr/decisions", json=create_payload)
        
        # Filter by exclusive
        response = requests.get(f"{BASE_URL}/api/pr/decisions?cta_type=exclusive")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "decisions" in data
        # All returned decisions should have cta_type=exclusive
        for d in data["decisions"]:
            assert d["cta_type"] == "exclusive", f"Expected exclusive, got {d['cta_type']}"
        print(f"✓ GET /api/pr/decisions?cta_type=exclusive - Filtered {data['total']} decisions")


class TestEventRAG26Fields:
    """POST /api/pr/events with RAG-26 fields and outcome tracking"""
    
    def test_create_event_with_rag26_fields(self):
        """POST /api/pr/events with narrative_angle, headline_variant, email_subject, cta_type, journalist_score_at_send"""
        unique_email = f"test_rag26_{uuid.uuid4().hex[:8]}@example.com"
        payload = {
            "event_type": "pr_outreach_sent",
            "journalist_name": "TEST_RAG26_Journalist",
            "journalist_email": unique_email,
            "publication": "TEST_RAG26_Publication",
            "narrative_angle": "empowerment",
            "headline_variant": "TEST_RAG26_Headline_Variant",
            "email_subject": "TEST_RAG26_Email_Subject",
            "cta_type": "case_study",
            "journalist_score_at_send": 85
        }
        response = requests.post(f"{BASE_URL}/api/pr/events", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["status"] == "ok", f"Expected status ok, got {data.get('status')}"
        assert "event_id" in data, "Missing event_id in response"
        print(f"✓ POST /api/pr/events with RAG-26 fields - Created event: {data['event_id']}")
        return data["event_id"]
    
    def test_update_event_outcome(self):
        """PATCH /api/pr/events/{id}/outcome - Update opened, replied, outcome_article, outcome_leads, outcome_revenue"""
        # First create an event
        unique_email = f"test_rag26_outcome_{uuid.uuid4().hex[:8]}@example.com"
        create_payload = {
            "event_type": "pr_outreach_sent",
            "journalist_name": "TEST_RAG26_Outcome_Journalist",
            "journalist_email": unique_email,
            "narrative_angle": "trust",
            "cta_type": "interview"
        }
        create_resp = requests.post(f"{BASE_URL}/api/pr/events", json=create_payload)
        assert create_resp.status_code == 200
        event_id = create_resp.json()["event_id"]
        
        # Update outcome fields
        update_payload = {
            "opened": True,
            "replied": True,
            "outcome_article": True,
            "outcome_leads": 3,
            "outcome_revenue": 1500.00
        }
        response = requests.patch(f"{BASE_URL}/api/pr/events/{event_id}/outcome", json=update_payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["status"] == "ok"
        assert data["event_id"] == event_id
        assert data["updated_fields"] == 5, f"Expected 5 updated fields, got {data.get('updated_fields')}"
        print(f"✓ PATCH /api/pr/events/{event_id}/outcome - Updated 5 outcome fields")
    
    def test_update_event_outcome_nonexistent_returns_404(self):
        """PATCH /api/pr/events/{invalid_id}/outcome - 404 on non-existent event"""
        fake_id = str(uuid.uuid4())
        update_payload = {"opened": True}
        response = requests.patch(f"{BASE_URL}/api/pr/events/{fake_id}/outcome", json=update_payload)
        assert response.status_code == 404, f"Expected 404, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "detail" in data
        print(f"✓ PATCH /api/pr/events/{fake_id}/outcome - 404 on non-existent event")


class TestFeaturesSummary:
    """GET /api/pr/features/summary - Aggregation endpoint for Predictive Decision Engine"""
    
    def test_features_summary_returns_required_fields(self):
        """GET /api/pr/features/summary - Returns readiness, by_narrative_angle, by_cta_type, cross_tab, event_outcome_stats"""
        response = requests.get(f"{BASE_URL}/api/pr/features/summary")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Check required top-level fields
        assert "period_days" in data, "Missing period_days"
        assert "readiness" in data, "Missing readiness"
        assert "by_narrative_angle" in data, "Missing by_narrative_angle"
        assert "by_cta_type" in data, "Missing by_cta_type"
        assert "cross_tab" in data, "Missing cross_tab"
        assert "event_outcome_stats" in data, "Missing event_outcome_stats"
        
        print(f"✓ GET /api/pr/features/summary - All required fields present")
    
    def test_features_summary_readiness_structure(self):
        """Verify readiness object structure"""
        response = requests.get(f"{BASE_URL}/api/pr/features/summary")
        assert response.status_code == 200
        
        data = response.json()
        readiness = data["readiness"]
        
        assert "total_decisions" in readiness, "Missing total_decisions in readiness"
        assert "tagged_events" in readiness, "Missing tagged_events in readiness"
        assert "prediction_ready" in readiness, "Missing prediction_ready in readiness"
        assert "message" in readiness, "Missing message in readiness"
        
        assert isinstance(readiness["total_decisions"], int)
        assert isinstance(readiness["prediction_ready"], bool)
        print(f"✓ Readiness: {readiness['total_decisions']} decisions, prediction_ready={readiness['prediction_ready']}")
    
    def test_features_summary_by_narrative_angle_structure(self):
        """Verify by_narrative_angle array structure"""
        response = requests.get(f"{BASE_URL}/api/pr/features/summary")
        assert response.status_code == 200
        
        data = response.json()
        by_narrative = data["by_narrative_angle"]
        
        assert isinstance(by_narrative, list), "by_narrative_angle should be a list"
        
        if len(by_narrative) > 0:
            item = by_narrative[0]
            assert "narrative_angle" in item
            assert "total_decisions" in item
            assert "reply_rate" in item
            assert "publish_rate" in item
            assert "total_leads" in item
            assert "total_revenue" in item
            print(f"✓ by_narrative_angle: {len(by_narrative)} angles with proper structure")
        else:
            print(f"✓ by_narrative_angle: empty (no decisions with narrative_angle yet)")
    
    def test_features_summary_by_cta_type_structure(self):
        """Verify by_cta_type array structure"""
        response = requests.get(f"{BASE_URL}/api/pr/features/summary")
        assert response.status_code == 200
        
        data = response.json()
        by_cta = data["by_cta_type"]
        
        assert isinstance(by_cta, list), "by_cta_type should be a list"
        
        if len(by_cta) > 0:
            item = by_cta[0]
            assert "cta_type" in item
            assert "total_decisions" in item
            assert "reply_rate" in item
            assert "publish_rate" in item
            assert "total_leads" in item
            assert "total_revenue" in item
            print(f"✓ by_cta_type: {len(by_cta)} CTA types with proper structure")
        else:
            print(f"✓ by_cta_type: empty (no decisions with cta_type yet)")
    
    def test_features_summary_event_outcome_stats_structure(self):
        """Verify event_outcome_stats object structure"""
        response = requests.get(f"{BASE_URL}/api/pr/features/summary")
        assert response.status_code == 200
        
        data = response.json()
        stats = data["event_outcome_stats"]
        
        assert "opened" in stats, "Missing opened in event_outcome_stats"
        assert "replied" in stats, "Missing replied in event_outcome_stats"
        assert "articles" in stats, "Missing articles in event_outcome_stats"
        assert "leads" in stats, "Missing leads in event_outcome_stats"
        assert "revenue" in stats, "Missing revenue in event_outcome_stats"
        
        print(f"✓ event_outcome_stats: opened={stats['opened']}, replied={stats['replied']}, articles={stats['articles']}")


class TestBackwardCompatibility:
    """Verify existing endpoints still work after RAG-26 additions"""
    
    def test_dashboard_still_works(self):
        """GET /api/pr/dashboard - Existing endpoint still functional"""
        response = requests.get(f"{BASE_URL}/api/pr/dashboard")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "overview" in data
        assert "conversion_rates" in data
        print(f"✓ GET /api/pr/dashboard - Still working (backward compatible)")
    
    def test_journalists_still_works(self):
        """GET /api/pr/journalists - Existing endpoint still functional"""
        response = requests.get(f"{BASE_URL}/api/pr/journalists")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "journalists" in data
        assert "total" in data
        print(f"✓ GET /api/pr/journalists - Still working ({data['total']} journalists)")
    
    def test_events_without_rag26_fields_still_works(self):
        """POST /api/pr/events without new fields - Backward compatible"""
        unique_email = f"test_backward_{uuid.uuid4().hex[:8]}@example.com"
        payload = {
            "event_type": "pr_outreach_sent",
            "journalist_name": "TEST_Backward_Compat_Journalist",
            "journalist_email": unique_email,
            "publication": "TEST_Publication"
            # No RAG-26 fields - should still work
        }
        response = requests.post(f"{BASE_URL}/api/pr/events", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["status"] == "ok"
        print(f"✓ POST /api/pr/events without RAG-26 fields - Backward compatible")
    
    def test_campaigns_still_works(self):
        """GET /api/pr/campaigns - Existing endpoint still functional"""
        response = requests.get(f"{BASE_URL}/api/pr/campaigns")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "campaigns" in data
        assert "total" in data
        print(f"✓ GET /api/pr/campaigns - Still working ({data['total']} campaigns)")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
