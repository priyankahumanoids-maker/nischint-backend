"""
RAG Insights Tracking System (Block 3) - Backend API Tests
Tests the full lifecycle: Query → Blog → CTA → Lead → Conversion

Endpoints tested:
- POST /api/rag/insight - Log RAG lifecycle events
- GET /api/rag/insights - Retrieve insights with filters
- GET /api/rag/insights/top-queries - Funnel progression data
- GET /api/rag/health - Includes total_insights field
- POST /api/rag/generate - Auto-logs blog_generated insight
- POST /api/enquiry - Auto-logs lead_created insight
"""
import os
import pytest
import requests
import time
import uuid

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

@pytest.fixture(scope="module")
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


class TestRAGInsightEndpoint:
    """Tests for POST /api/rag/insight endpoint"""

    def test_log_blog_generated_insight(self, api_client):
        """POST /api/rag/insight with event_type=blog_generated should log correctly"""
        payload = {
            "event_type": "blog_generated",
            "query": "TEST_child safety tips",
            "persona": "parent",
            "emotion": "concern",
            "blog_slug": "test-child-safety-tips",
            "source": "blog",
            "metadata": {"title": "Child Safety Tips", "sections_count": 5}
        }
        response = api_client.post(f"{BASE_URL}/api/rag/insight", json=payload)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Verify response structure
        assert "id" in data, "Response should contain 'id'"
        assert "event_type" in data, "Response should contain 'event_type'"
        assert "message" in data, "Response should contain 'message'"
        
        # Verify values
        assert data["event_type"] == "blog_generated"
        assert data["message"] == "Insight logged"
        assert len(data["id"]) == 36  # UUID format
        print(f"✓ blog_generated insight logged with id: {data['id']}")

    def test_log_cta_clicked_insight(self, api_client):
        """POST /api/rag/insight with event_type=cta_clicked should log correctly"""
        payload = {
            "event_type": "cta_clicked",
            "query": "TEST_school bus tracking",
            "blog_slug": "school-bus-tracking-guide",
            "source": "blog",
            "metadata": {"cta_type": "contact_form", "position": "bottom"}
        }
        response = api_client.post(f"{BASE_URL}/api/rag/insight", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["event_type"] == "cta_clicked"
        assert data["message"] == "Insight logged"
        print(f"✓ cta_clicked insight logged with id: {data['id']}")

    def test_log_lead_created_insight_with_score_priority(self, api_client):
        """POST /api/rag/insight with event_type=lead_created should log correctly with lead_id, score, priority"""
        lead_id = str(uuid.uuid4())
        payload = {
            "event_type": "lead_created",
            "query": "TEST_elderly care monitoring",
            "blog_slug": "elderly-care-monitoring",
            "lead_id": lead_id,
            "score": 85,
            "priority": "high",
            "source": "website",
            "metadata": {"name": "Test User", "email": "test@example.com"}
        }
        response = api_client.post(f"{BASE_URL}/api/rag/insight", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["event_type"] == "lead_created"
        assert data["message"] == "Insight logged"
        print(f"✓ lead_created insight logged with id: {data['id']}, lead_id: {lead_id}")

    def test_log_insight_with_conversion(self, api_client):
        """POST /api/rag/insight with conversion=true should log correctly"""
        payload = {
            "event_type": "lead_created",
            "query": "TEST_conversion tracking",
            "lead_id": str(uuid.uuid4()),
            "conversion": True,
            "score": 95,
            "priority": "critical",
            "source": "website"
        }
        response = api_client.post(f"{BASE_URL}/api/rag/insight", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        assert data["event_type"] == "lead_created"
        print(f"✓ Insight with conversion=true logged with id: {data['id']}")

    def test_log_insight_minimal_payload(self, api_client):
        """POST /api/rag/insight with minimal payload (only event_type)"""
        payload = {
            "event_type": "blog_generated"
        }
        response = api_client.post(f"{BASE_URL}/api/rag/insight", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        assert data["event_type"] == "blog_generated"
        print(f"✓ Minimal insight logged with id: {data['id']}")


class TestRAGInsightsListEndpoint:
    """Tests for GET /api/rag/insights endpoint"""

    def test_get_all_insights_with_pagination(self, api_client):
        """GET /api/rag/insights should return all insights with pagination"""
        response = api_client.get(f"{BASE_URL}/api/rag/insights")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify pagination structure
        assert "total" in data, "Response should contain 'total'"
        assert "results" in data, "Response should contain 'results'"
        assert "limit" in data, "Response should contain 'limit'"
        assert "offset" in data, "Response should contain 'offset'"
        
        assert isinstance(data["results"], list)
        assert data["limit"] == 50  # Default limit
        assert data["offset"] == 0  # Default offset
        
        print(f"✓ Retrieved {len(data['results'])} insights, total: {data['total']}")

    def test_filter_by_event_type(self, api_client):
        """GET /api/rag/insights?event_type=blog_generated should filter by event_type"""
        response = api_client.get(f"{BASE_URL}/api/rag/insights?event_type=blog_generated")
        
        assert response.status_code == 200
        data = response.json()
        
        # All results should have event_type=blog_generated
        for result in data["results"]:
            assert result["event_type"] == "blog_generated", f"Expected blog_generated, got {result['event_type']}"
        
        print(f"✓ Filtered by event_type=blog_generated: {len(data['results'])} results")

    def test_filter_by_blog_slug(self, api_client):
        """GET /api/rag/insights?blog_slug=xxx should filter by blog_slug"""
        # First create an insight with a specific blog_slug
        unique_slug = f"test-slug-{uuid.uuid4().hex[:8]}"
        api_client.post(f"{BASE_URL}/api/rag/insight", json={
            "event_type": "blog_generated",
            "blog_slug": unique_slug,
            "query": "TEST_filter test"
        })
        
        response = api_client.get(f"{BASE_URL}/api/rag/insights?blog_slug={unique_slug}")
        
        assert response.status_code == 200
        data = response.json()
        
        # All results should have the specified blog_slug
        for result in data["results"]:
            assert result["blog_slug"] == unique_slug
        
        print(f"✓ Filtered by blog_slug={unique_slug}: {len(data['results'])} results")

    def test_filter_by_source(self, api_client):
        """GET /api/rag/insights?source=blog should filter by source"""
        response = api_client.get(f"{BASE_URL}/api/rag/insights?source=blog")
        
        assert response.status_code == 200
        data = response.json()
        
        # All results should have source=blog
        for result in data["results"]:
            assert result["source"] == "blog", f"Expected source=blog, got {result['source']}"
        
        print(f"✓ Filtered by source=blog: {len(data['results'])} results")

    def test_filter_by_partial_query_match(self, api_client):
        """GET /api/rag/insights?query=child should filter by partial query match"""
        # First create an insight with 'child' in query
        api_client.post(f"{BASE_URL}/api/rag/insight", json={
            "event_type": "blog_generated",
            "query": "TEST_child safety monitoring tips",
            "source": "blog"
        })
        
        response = api_client.get(f"{BASE_URL}/api/rag/insights?query=child")
        
        assert response.status_code == 200
        data = response.json()
        
        # All results should contain 'child' in query (case-insensitive)
        for result in data["results"]:
            if result["query"]:
                assert "child" in result["query"].lower(), f"Query should contain 'child': {result['query']}"
        
        print(f"✓ Filtered by query containing 'child': {len(data['results'])} results")

    def test_pagination_with_limit_offset(self, api_client):
        """GET /api/rag/insights with limit and offset parameters"""
        response = api_client.get(f"{BASE_URL}/api/rag/insights?limit=5&offset=0")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["limit"] == 5
        assert data["offset"] == 0
        assert len(data["results"]) <= 5
        
        print(f"✓ Pagination working: limit=5, offset=0, returned {len(data['results'])} results")


class TestTopQueriesEndpoint:
    """Tests for GET /api/rag/insights/top-queries endpoint"""

    def test_get_top_queries_funnel_data(self, api_client):
        """GET /api/rag/insights/top-queries should return funnel data"""
        response = api_client.get(f"{BASE_URL}/api/rag/insights/top-queries")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify response structure
        assert "queries" in data, "Response should contain 'queries'"
        assert isinstance(data["queries"], list)
        
        # Verify each query has funnel fields
        for query_data in data["queries"]:
            assert "query" in query_data, "Each result should have 'query'"
            assert "generated" in query_data, "Each result should have 'generated'"
            assert "cta_clicks" in query_data, "Each result should have 'cta_clicks'"
            assert "leads" in query_data, "Each result should have 'leads'"
            assert "conversions" in query_data, "Each result should have 'conversions'"
            assert "total_events" in query_data, "Each result should have 'total_events'"
        
        print(f"✓ Top queries endpoint returned {len(data['queries'])} queries with funnel data")

    def test_top_queries_with_limit(self, api_client):
        """GET /api/rag/insights/top-queries?limit=5 should respect limit"""
        response = api_client.get(f"{BASE_URL}/api/rag/insights/top-queries?limit=5")
        
        assert response.status_code == 200
        data = response.json()
        
        assert len(data["queries"]) <= 5
        print(f"✓ Top queries with limit=5 returned {len(data['queries'])} queries")


class TestRAGHealthWithInsights:
    """Tests for GET /api/rag/health including total_insights field"""

    def test_health_includes_total_insights(self, api_client):
        """GET /api/rag/health should include total_insights field"""
        response = api_client.get(f"{BASE_URL}/api/rag/health")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify total_insights field exists
        assert "total_insights" in data, "Health response should include 'total_insights'"
        assert isinstance(data["total_insights"], int)
        assert data["total_insights"] >= 0
        
        print(f"✓ Health endpoint includes total_insights: {data['total_insights']}")

    def test_health_insights_count_increases_after_logging(self, api_client):
        """GET /api/rag/health total_insights should increase after logging new insight"""
        # Get initial count
        response1 = api_client.get(f"{BASE_URL}/api/rag/health")
        initial_count = response1.json()["total_insights"]
        
        # Log a new insight
        api_client.post(f"{BASE_URL}/api/rag/insight", json={
            "event_type": "blog_generated",
            "query": "TEST_health count test"
        })
        
        # Get new count
        response2 = api_client.get(f"{BASE_URL}/api/rag/health")
        new_count = response2.json()["total_insights"]
        
        assert new_count > initial_count, f"Expected count to increase from {initial_count}, got {new_count}"
        print(f"✓ total_insights increased from {initial_count} to {new_count}")


class TestGenerateAutoLogging:
    """Tests for POST /api/rag/generate auto-logging blog_generated insight"""

    def test_generate_auto_logs_blog_generated_insight(self, api_client):
        """POST /api/rag/generate should auto-log a blog_generated insight"""
        # Get initial insights count
        response1 = api_client.get(f"{BASE_URL}/api/rag/insights?event_type=blog_generated")
        initial_count = response1.json()["total"]
        
        # Call generate endpoint (takes 15-20 seconds due to OpenAI API)
        payload = {
            "query": "TEST_auto_log child safety at school",
            "persona": "parent",
            "emotion": "concern",
            "location": "India"
        }
        response = api_client.post(f"{BASE_URL}/api/rag/generate", json=payload, timeout=60)
        
        assert response.status_code == 200, f"Generate failed: {response.text}"
        data = response.json()
        
        # Verify generate response structure
        assert "title" in data
        assert "hook" in data
        assert "sections" in data
        assert "cta" in data
        assert "rag_context" in data
        
        # Wait a moment for async logging
        time.sleep(1)
        
        # Check insights count increased
        response2 = api_client.get(f"{BASE_URL}/api/rag/insights?event_type=blog_generated")
        new_count = response2.json()["total"]
        
        assert new_count > initial_count, f"Expected blog_generated insights to increase from {initial_count}, got {new_count}"
        print(f"✓ Generate auto-logged blog_generated insight. Count: {initial_count} → {new_count}")


class TestEnquiryAutoLogging:
    """Tests for POST /api/enquiry auto-logging lead_created insight"""

    def test_enquiry_auto_logs_lead_created_insight(self, api_client):
        """POST /api/enquiry with blog_slug and query should auto-log a lead_created insight"""
        # Get initial lead_created insights count
        response1 = api_client.get(f"{BASE_URL}/api/rag/insights?event_type=lead_created")
        initial_count = response1.json()["total"]
        
        # Create enquiry with blog_slug and query for RAG tracking
        unique_email = f"test_{uuid.uuid4().hex[:8]}@example.com"
        payload = {
            "name": "Test User",
            "email": unique_email,
            "phone": "+919876543210",
            "message": "I need help with child safety",
            "source": "website",
            "channel": "form",
            "blog_slug": "child-safety-guide",
            "query": "TEST_child safety monitoring"
        }
        response = api_client.post(f"{BASE_URL}/api/enquiry", json=payload, timeout=30)
        
        # Note: n8n webhook may timeout but enquiry should still be captured
        assert response.status_code == 200, f"Enquiry failed: {response.text}"
        data = response.json()
        
        assert data["status"] in ["ok", "duplicate"]
        assert "lead_id" in data
        
        # Wait a moment for async logging
        time.sleep(1)
        
        # Check lead_created insights count increased
        response2 = api_client.get(f"{BASE_URL}/api/rag/insights?event_type=lead_created")
        new_count = response2.json()["total"]
        
        assert new_count > initial_count, f"Expected lead_created insights to increase from {initial_count}, got {new_count}"
        print(f"✓ Enquiry auto-logged lead_created insight. Count: {initial_count} → {new_count}")

    def test_enquiry_without_rag_fields_still_works(self, api_client):
        """POST /api/enquiry without blog_slug/query should still work (backward compatible)"""
        unique_email = f"test_{uuid.uuid4().hex[:8]}@example.com"
        payload = {
            "name": "Test User No RAG",
            "email": unique_email,
            "phone": "+919876543211",
            "message": "General enquiry",
            "source": "website",
            "channel": "form"
        }
        response = api_client.post(f"{BASE_URL}/api/enquiry", json=payload, timeout=30)
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["ok", "duplicate"]
        print(f"✓ Enquiry without RAG fields works. Lead ID: {data['lead_id']}")


class TestInsightDataIntegrity:
    """Tests for verifying insight data is stored and retrieved correctly"""

    def test_insight_data_persisted_correctly(self, api_client):
        """Verify all fields are persisted and retrieved correctly"""
        unique_query = f"TEST_data_integrity_{uuid.uuid4().hex[:8]}"
        unique_slug = f"test-slug-{uuid.uuid4().hex[:8]}"
        lead_id = str(uuid.uuid4())
        
        # Create insight with all fields
        payload = {
            "event_type": "lead_created",
            "query": unique_query,
            "persona": "parent",
            "emotion": "anxiety",
            "blog_id": "blog-123",
            "blog_slug": unique_slug,
            "lead_id": lead_id,
            "conversion": True,
            "score": 90,
            "priority": "high",
            "source": "website",
            "metadata": {"test_key": "test_value"}
        }
        create_response = api_client.post(f"{BASE_URL}/api/rag/insight", json=payload)
        assert create_response.status_code == 200
        insight_id = create_response.json()["id"]
        
        # Retrieve and verify
        get_response = api_client.get(f"{BASE_URL}/api/rag/insights?query={unique_query}")
        assert get_response.status_code == 200
        data = get_response.json()
        
        # Find our insight
        found = None
        for result in data["results"]:
            if result["id"] == insight_id:
                found = result
                break
        
        assert found is not None, f"Insight {insight_id} not found in results"
        
        # Verify all fields
        assert found["query"] == unique_query
        assert found["persona"] == "parent"
        assert found["emotion"] == "anxiety"
        assert found["blog_slug"] == unique_slug
        assert found["lead_id"] == lead_id
        assert found["conversion"] == True
        assert found["score"] == 90
        assert found["priority"] == "high"
        assert found["source"] == "website"
        assert found["event_type"] == "lead_created"
        
        print(f"✓ All insight fields persisted and retrieved correctly for id: {insight_id}")


class TestFunnelProgression:
    """Tests for verifying funnel progression tracking"""

    def test_full_funnel_tracking(self, api_client):
        """Test complete funnel: blog_generated → cta_clicked → lead_created"""
        unique_query = f"TEST_funnel_{uuid.uuid4().hex[:8]}"
        unique_slug = f"funnel-test-{uuid.uuid4().hex[:8]}"
        
        # Step 1: Blog generated
        api_client.post(f"{BASE_URL}/api/rag/insight", json={
            "event_type": "blog_generated",
            "query": unique_query,
            "blog_slug": unique_slug,
            "source": "blog"
        })
        
        # Step 2: CTA clicked
        api_client.post(f"{BASE_URL}/api/rag/insight", json={
            "event_type": "cta_clicked",
            "query": unique_query,
            "blog_slug": unique_slug,
            "source": "blog"
        })
        
        # Step 3: Lead created
        api_client.post(f"{BASE_URL}/api/rag/insight", json={
            "event_type": "lead_created",
            "query": unique_query,
            "blog_slug": unique_slug,
            "lead_id": str(uuid.uuid4()),
            "source": "website"
        })
        
        # Verify in top-queries
        response = api_client.get(f"{BASE_URL}/api/rag/insights/top-queries?limit=50")
        assert response.status_code == 200
        data = response.json()
        
        # Find our query in top queries
        found = None
        for q in data["queries"]:
            if q["query"] == unique_query:
                found = q
                break
        
        assert found is not None, f"Query '{unique_query}' not found in top queries"
        assert found["generated"] >= 1, "Should have at least 1 generated"
        assert found["cta_clicks"] >= 1, "Should have at least 1 cta_click"
        assert found["leads"] >= 1, "Should have at least 1 lead"
        assert found["total_events"] >= 3, "Should have at least 3 total events"
        
        print(f"✓ Full funnel tracked for query '{unique_query}': generated={found['generated']}, cta_clicks={found['cta_clicks']}, leads={found['leads']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
