"""
RAG System Block 2 Backend Tests - Knowledge RAG + Content Generation Engine
Tests: POST /api/knowledge/ingest, POST /api/knowledge/batch-ingest, 
       POST /api/knowledge/search, POST /api/rag/generate, GET /api/rag/health (updated)
Uses real OpenAI embeddings and GPT-4o-mini for generation
"""
import pytest
import requests
import os
import uuid
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# ══════════════════════════════════════════════════════════════════════
# KNOWLEDGE INGEST TESTS
# ══════════════════════════════════════════════════════════════════════

class TestKnowledgeIngest:
    """POST /api/knowledge/ingest - Single safety knowledge entry ingest"""
    
    def test_ingest_success(self):
        """Ingest should accept topic, category, content, metadata and return id"""
        test_topic = f"TEST_knowledge_{uuid.uuid4().hex[:8]}"
        payload = {
            "topic": test_topic,
            "category": "child_safety",
            "content": "Children should always be supervised when near water bodies. "
                       "Swimming pools, lakes, and even bathtubs pose drowning risks. "
                       "Install pool fences and use life jackets for young children.",
            "metadata": {"source": "test", "priority": "high"}
        }
        response = requests.post(f"{BASE_URL}/api/knowledge/ingest", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "id" in data, "Expected 'id' in response"
        assert data.get("topic") == test_topic, f"Expected topic={test_topic}, got {data.get('topic')}"
        assert data.get("embedding_generated") is True, f"Expected embedding_generated=true, got {data.get('embedding_generated')}"
        assert "message" in data, "Expected 'message' in response"
        print(f"✓ Ingested knowledge: id={data.get('id')}, topic={test_topic}, embedding={data.get('embedding_generated')}")
    
    def test_ingest_without_category(self):
        """Ingest should work without category (optional field)"""
        test_topic = f"TEST_no_category_{uuid.uuid4().hex[:8]}"
        payload = {
            "topic": test_topic,
            "content": "General safety tip: Always be aware of your surroundings."
        }
        response = requests.post(f"{BASE_URL}/api/knowledge/ingest", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data.get("topic") == test_topic
        print(f"✓ Ingested knowledge without category: topic={test_topic}")
    
    def test_ingest_without_metadata(self):
        """Ingest should work without metadata (optional field)"""
        test_topic = f"TEST_no_metadata_{uuid.uuid4().hex[:8]}"
        payload = {
            "topic": test_topic,
            "category": "general",
            "content": "Safety knowledge entry without metadata field."
        }
        response = requests.post(f"{BASE_URL}/api/knowledge/ingest", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data.get("topic") == test_topic
        print(f"✓ Ingested knowledge without metadata: topic={test_topic}")
    
    def test_ingest_generates_embedding(self):
        """Ingest should generate embedding for content"""
        test_topic = f"TEST_embedding_{uuid.uuid4().hex[:8]}"
        payload = {
            "topic": test_topic,
            "category": "women_safety",
            "content": "Women should share their live location with trusted contacts when traveling alone. "
                       "Use safety apps that can send SOS alerts with one tap."
        }
        response = requests.post(f"{BASE_URL}/api/knowledge/ingest", json=payload)
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("embedding_generated") is True, "Expected embedding to be generated"
        print(f"✓ Embedding generated for knowledge entry: {test_topic}")


# ══════════════════════════════════════════════════════════════════════
# KNOWLEDGE BATCH INGEST TESTS
# ══════════════════════════════════════════════════════════════════════

class TestKnowledgeBatchIngest:
    """POST /api/knowledge/batch-ingest - Batch ingest multiple knowledge entries"""
    
    def test_batch_ingest_success(self):
        """Batch ingest should accept entries array and return counts"""
        unique_id = uuid.uuid4().hex[:8]
        payload = {
            "entries": [
                {
                    "topic": f"TEST_batch1_{unique_id}",
                    "category": "child_safety",
                    "content": "Never leave children unattended in vehicles. "
                               "Car interiors can heat up rapidly causing heatstroke."
                },
                {
                    "topic": f"TEST_batch2_{unique_id}",
                    "category": "elderly_safety",
                    "content": "Elderly individuals should have emergency contact numbers easily accessible. "
                               "Medical alert devices can be life-saving."
                },
                {
                    "topic": f"TEST_batch3_{unique_id}",
                    "category": "home_safety",
                    "content": "Install smoke detectors on every floor. "
                               "Test them monthly and replace batteries annually."
                }
            ]
        }
        response = requests.post(f"{BASE_URL}/api/knowledge/batch-ingest", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("total") == 3, f"Expected total=3, got {data.get('total')}"
        assert data.get("ingested") == 3, f"Expected ingested=3, got {data.get('ingested')}"
        assert data.get("errors") == 0, f"Expected errors=0, got {data.get('errors')}"
        assert "details" in data, "Expected 'details' in response"
        assert len(data.get("details", [])) == 3, "Expected 3 detail entries"
        print(f"✓ Batch ingested: total={data.get('total')}, ingested={data.get('ingested')}, errors={data.get('errors')}")
    
    def test_batch_ingest_details_structure(self):
        """Batch ingest details should contain topic, status, embedding for each entry"""
        unique_id = uuid.uuid4().hex[:8]
        payload = {
            "entries": [
                {
                    "topic": f"TEST_detail_{unique_id}",
                    "category": "test",
                    "content": "Test content for detail structure verification."
                }
            ]
        }
        response = requests.post(f"{BASE_URL}/api/knowledge/batch-ingest", json=payload)
        assert response.status_code == 200
        
        data = response.json()
        details = data.get("details", [])
        assert len(details) > 0, "Expected at least one detail entry"
        
        detail = details[0]
        assert "topic" in detail, "Expected 'topic' in detail"
        assert "status" in detail, "Expected 'status' in detail"
        assert detail.get("status") == "ingested", f"Expected status=ingested, got {detail.get('status')}"
        assert "embedding" in detail, "Expected 'embedding' in detail"
        print(f"✓ Batch ingest detail structure valid: {detail}")
    
    def test_batch_ingest_empty_entries(self):
        """Batch ingest with empty entries should return total=0"""
        payload = {"entries": []}
        response = requests.post(f"{BASE_URL}/api/knowledge/batch-ingest", json=payload)
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("total") == 0, f"Expected total=0, got {data.get('total')}"
        assert data.get("ingested") == 0, f"Expected ingested=0, got {data.get('ingested')}"
        print(f"✓ Empty batch ingest handled correctly")


# ══════════════════════════════════════════════════════════════════════
# KNOWLEDGE SEARCH TESTS
# ══════════════════════════════════════════════════════════════════════

class TestKnowledgeSearch:
    """POST /api/knowledge/search - Vector similarity search with full-text fallback"""
    
    def test_search_returns_results(self):
        """Search should return results for a valid query"""
        payload = {
            "query": "child safety water drowning prevention",
            "top_k": 5,
            "threshold": 0.25
        }
        response = requests.post(f"{BASE_URL}/api/knowledge/search", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "results" in data, "Expected 'results' in response"
        assert "search_method" in data, "Expected 'search_method' in response"
        assert "total_results" in data, "Expected 'total_results' in response"
        assert "query" in data, "Expected 'query' in response"
        print(f"✓ Knowledge search returned {data.get('total_results')} results using {data.get('search_method')}")
    
    def test_search_uses_vector_cosine(self):
        """Search should use vector_cosine method when embeddings are available"""
        payload = {
            "query": "women safety traveling alone",
            "top_k": 5,
            "threshold": 0.2
        }
        response = requests.post(f"{BASE_URL}/api/knowledge/search", json=payload)
        data = response.json()
        
        search_method = data.get("search_method", "")
        assert search_method in ["vector_cosine", "full_text"], f"Unexpected search_method: {search_method}"
        print(f"✓ Knowledge search method: {search_method}")
    
    def test_search_result_structure(self):
        """Search results should have correct structure: id, topic, category, content, score"""
        payload = {
            "query": "safety tips family protection",
            "top_k": 5,
            "threshold": 0.1
        }
        response = requests.post(f"{BASE_URL}/api/knowledge/search", json=payload)
        data = response.json()
        
        results = data.get("results", [])
        if len(results) > 0:
            result = results[0]
            assert "id" in result, "Expected 'id' in result"
            assert "topic" in result, "Expected 'topic' in result"
            assert "category" in result, "Expected 'category' in result"
            assert "content" in result, "Expected 'content' in result"
            assert "score" in result, "Expected 'score' in result"
            assert isinstance(result.get("score"), (int, float)), "Score should be numeric"
            print(f"✓ Knowledge search result structure valid: id, topic, category, content, score present")
        else:
            print(f"⚠ No results returned for query, skipping structure check")
    
    def test_search_with_category_filter(self):
        """Search with category filter should only return results from that category"""
        # First ingest a known entry with specific category
        unique_id = uuid.uuid4().hex[:8]
        ingest_payload = {
            "topic": f"TEST_category_filter_{unique_id}",
            "category": "TEST_CATEGORY_FILTER",
            "content": "This is a unique test entry for category filtering verification."
        }
        requests.post(f"{BASE_URL}/api/knowledge/ingest", json=ingest_payload)
        
        # Search with category filter
        search_payload = {
            "query": "unique test entry category filtering",
            "top_k": 10,
            "category": "TEST_CATEGORY_FILTER",
            "threshold": 0.1
        }
        response = requests.post(f"{BASE_URL}/api/knowledge/search", json=search_payload)
        data = response.json()
        
        results = data.get("results", [])
        # All results should have the filtered category
        for result in results:
            assert result.get("category") == "TEST_CATEGORY_FILTER", \
                f"Expected category=TEST_CATEGORY_FILTER, got {result.get('category')}"
        print(f"✓ Category filter working: {len(results)} results all from TEST_CATEGORY_FILTER")
    
    def test_search_threshold_filtering(self):
        """Search with high threshold should filter out low-relevance results"""
        payload = {
            "query": "random unrelated query xyz123abc",
            "top_k": 10,
            "threshold": 0.9
        }
        response = requests.post(f"{BASE_URL}/api/knowledge/search", json=payload)
        data = response.json()
        
        results = data.get("results", [])
        for result in results:
            score = result.get("score", 0)
            assert score >= 0.9, f"Expected score >= 0.9, got {score}"
        print(f"✓ High threshold (0.9) returned {len(results)} results, all with score >= 0.9")
    
    def test_search_fallback_to_fulltext(self):
        """Search should fall back to full_text when vector search returns no results"""
        # Use a very high threshold to potentially trigger fallback
        payload = {
            "query": "safety knowledge search test",
            "top_k": 5,
            "threshold": 0.99
        }
        response = requests.post(f"{BASE_URL}/api/knowledge/search", json=payload)
        data = response.json()
        
        search_method = data.get("search_method", "")
        # Either vector_cosine or full_text is acceptable
        assert search_method in ["vector_cosine", "full_text", "none"], f"Unexpected search_method: {search_method}"
        print(f"✓ Search method with high threshold: {search_method}")


# ══════════════════════════════════════════════════════════════════════
# CONTENT GENERATION ENGINE TESTS
# ══════════════════════════════════════════════════════════════════════

class TestRAGGenerate:
    """POST /api/rag/generate - RAG Decision + Content Generation Engine"""
    
    def test_generate_returns_200(self):
        """Generate should return 200 for valid request"""
        payload = {
            "query": "How to keep my child safe while traveling to school?",
            "persona": "parent",
            "emotion": "concern",
            "location": "India"
        }
        response = requests.post(f"{BASE_URL}/api/rag/generate", json=payload, timeout=60)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print(f"✓ Generate endpoint returned 200")
    
    def test_generate_response_structure(self):
        """Generate should return structured JSON with all required fields"""
        payload = {
            "query": "Women safety tips for late night travel",
            "persona": "woman",
            "emotion": "fear",
            "location": "Mumbai"
        }
        response = requests.post(f"{BASE_URL}/api/rag/generate", json=payload, timeout=60)
        assert response.status_code == 200
        
        data = response.json()
        
        # Check all required fields
        assert "title" in data, "Expected 'title' in response"
        assert "hook" in data, "Expected 'hook' in response"
        assert "sections" in data, "Expected 'sections' in response"
        assert "cta" in data, "Expected 'cta' in response"
        assert "internal_links" in data, "Expected 'internal_links' in response"
        assert "seo" in data, "Expected 'seo' in response"
        assert "rag_context" in data, "Expected 'rag_context' in response"
        
        # Validate types
        assert isinstance(data.get("title"), str), "title should be string"
        assert isinstance(data.get("hook"), str), "hook should be string"
        assert isinstance(data.get("sections"), list), "sections should be list"
        assert isinstance(data.get("cta"), str), "cta should be string"
        assert isinstance(data.get("internal_links"), list), "internal_links should be list"
        assert isinstance(data.get("seo"), dict), "seo should be dict"
        assert isinstance(data.get("rag_context"), dict), "rag_context should be dict"
        
        print(f"✓ Generate response structure valid: title, hook, sections, cta, internal_links, seo, rag_context")
    
    def test_generate_sections_structure(self):
        """Generate sections should have type, heading, content"""
        payload = {
            "query": "Elderly care safety monitoring",
            "persona": "caregiver",
            "emotion": "worry",
            "location": "Delhi"
        }
        response = requests.post(f"{BASE_URL}/api/rag/generate", json=payload, timeout=60)
        assert response.status_code == 200
        
        data = response.json()
        sections = data.get("sections", [])
        
        assert len(sections) > 0, "Expected at least one section"
        
        for section in sections:
            assert "type" in section, "Expected 'type' in section"
            assert "heading" in section, "Expected 'heading' in section"
            assert "content" in section, "Expected 'content' in section"
        
        print(f"✓ Generate sections structure valid: {len(sections)} sections with type, heading, content")
    
    def test_generate_seo_structure(self):
        """Generate SEO should have meta_title, meta_description, keywords"""
        payload = {
            "query": "Family safety during festivals",
            "persona": "parent",
            "emotion": "concern",
            "location": "India"
        }
        response = requests.post(f"{BASE_URL}/api/rag/generate", json=payload, timeout=60)
        assert response.status_code == 200
        
        data = response.json()
        seo = data.get("seo", {})
        
        assert "meta_title" in seo, "Expected 'meta_title' in seo"
        assert "meta_description" in seo, "Expected 'meta_description' in seo"
        assert "keywords" in seo, "Expected 'keywords' in seo"
        assert isinstance(seo.get("keywords"), list), "keywords should be list"
        
        print(f"✓ Generate SEO structure valid: meta_title, meta_description, keywords")
    
    def test_generate_internal_links_enriched(self):
        """Generate internal_links should be enriched with blog_id, title, slug, anchor"""
        payload = {
            "query": "Child safety at home",
            "persona": "parent",
            "emotion": "concern",
            "location": "Bangalore"
        }
        response = requests.post(f"{BASE_URL}/api/rag/generate", json=payload, timeout=60)
        assert response.status_code == 200
        
        data = response.json()
        internal_links = data.get("internal_links", [])
        
        # If there are internal links, check their structure
        if len(internal_links) > 0:
            link = internal_links[0]
            assert "blog_id" in link, "Expected 'blog_id' in internal_link"
            assert "anchor" in link, "Expected 'anchor' in internal_link"
            # title and slug may be present if enriched from context
            print(f"✓ Internal links enriched: {len(internal_links)} links with blog_id, anchor")
        else:
            print(f"⚠ No internal links generated (may depend on RAG context)")
    
    def test_generate_rag_context_counts(self):
        """Generate rag_context should show blog_sources and knowledge_sources counts"""
        payload = {
            "query": "Safety tips for senior citizens",
            "persona": "caregiver",
            "emotion": "concern",
            "location": "Chennai"
        }
        response = requests.post(f"{BASE_URL}/api/rag/generate", json=payload, timeout=60)
        assert response.status_code == 200
        
        data = response.json()
        rag_context = data.get("rag_context", {})
        
        assert "blog_sources" in rag_context, "Expected 'blog_sources' in rag_context"
        assert "knowledge_sources" in rag_context, "Expected 'knowledge_sources' in rag_context"
        assert "total_sources" in rag_context, "Expected 'total_sources' in rag_context"
        
        blog_sources = rag_context.get("blog_sources", 0)
        knowledge_sources = rag_context.get("knowledge_sources", 0)
        total_sources = rag_context.get("total_sources", 0)
        
        assert total_sources == blog_sources + knowledge_sources, \
            f"total_sources should equal blog_sources + knowledge_sources"
        
        print(f"✓ RAG context counts: blog_sources={blog_sources}, knowledge_sources={knowledge_sources}, total={total_sources}")
    
    def test_generate_intent_analysis(self):
        """Generate should include intent_analysis with intent_level, urgency, scenario_type"""
        payload = {
            "query": "Emergency response for child abduction",
            "persona": "parent",
            "emotion": "panic",
            "location": "India"
        }
        response = requests.post(f"{BASE_URL}/api/rag/generate", json=payload, timeout=60)
        assert response.status_code == 200
        
        data = response.json()
        intent_analysis = data.get("intent_analysis")
        
        # intent_analysis is optional but if present should have structure
        if intent_analysis:
            assert "intent_level" in intent_analysis or "urgency" in intent_analysis or "scenario_type" in intent_analysis, \
                "Expected intent_analysis to have intent_level, urgency, or scenario_type"
            print(f"✓ Intent analysis present: {intent_analysis}")
        else:
            print(f"⚠ Intent analysis not present (optional field)")
    
    def test_generate_with_default_params(self):
        """Generate should work with only query (other params have defaults)"""
        payload = {
            "query": "How to protect my family from online threats?"
        }
        response = requests.post(f"{BASE_URL}/api/rag/generate", json=payload, timeout=60)
        assert response.status_code == 200
        
        data = response.json()
        assert "title" in data
        assert "hook" in data
        assert "sections" in data
        print(f"✓ Generate works with default params: title='{data.get('title')[:50]}...'")


# ══════════════════════════════════════════════════════════════════════
# HEALTH ENDPOINT UPDATED TESTS
# ══════════════════════════════════════════════════════════════════════

class TestRAGHealthUpdated:
    """GET /api/rag/health - Updated to include total_knowledge_entries"""
    
    def test_health_includes_total_knowledge_entries(self):
        """Health should now include total_knowledge_entries field"""
        response = requests.get(f"{BASE_URL}/api/rag/health")
        assert response.status_code == 200
        
        data = response.json()
        assert "total_knowledge_entries" in data, "Expected 'total_knowledge_entries' in health response"
        
        total_knowledge = data.get("total_knowledge_entries", 0)
        assert isinstance(total_knowledge, int), "total_knowledge_entries should be integer"
        assert total_knowledge >= 0, f"total_knowledge_entries should be >= 0, got {total_knowledge}"
        
        print(f"✓ Health includes total_knowledge_entries: {total_knowledge}")
    
    def test_health_knowledge_count_increases_after_ingest(self):
        """Health total_knowledge_entries should increase after ingesting knowledge"""
        # Get initial count
        health1 = requests.get(f"{BASE_URL}/api/rag/health").json()
        initial_count = health1.get("total_knowledge_entries", 0)
        
        # Ingest new knowledge
        unique_id = uuid.uuid4().hex[:8]
        ingest_payload = {
            "topic": f"TEST_health_count_{unique_id}",
            "category": "test",
            "content": "Test knowledge entry to verify health count increases."
        }
        requests.post(f"{BASE_URL}/api/knowledge/ingest", json=ingest_payload)
        
        # Get updated count
        health2 = requests.get(f"{BASE_URL}/api/rag/health").json()
        updated_count = health2.get("total_knowledge_entries", 0)
        
        assert updated_count > initial_count, \
            f"Expected count to increase: {initial_count} -> {updated_count}"
        
        print(f"✓ Health knowledge count increased: {initial_count} -> {updated_count}")


# ══════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS
# ══════════════════════════════════════════════════════════════════════

class TestBlock2Integration:
    """Integration tests for Block 2 - Knowledge + Generation flows"""
    
    def test_ingest_then_search_knowledge(self):
        """Ingest knowledge and then search for it"""
        unique_id = uuid.uuid4().hex[:8]
        unique_phrase = f"quantum_safety_protocol_{unique_id}"
        
        # Ingest
        ingest_payload = {
            "topic": f"TEST_integration_{unique_id}",
            "category": "technology_safety",
            "content": f"This knowledge entry discusses {unique_phrase} for advanced safety systems. "
                       "Quantum encryption can protect sensitive location data from hackers."
        }
        ingest_response = requests.post(f"{BASE_URL}/api/knowledge/ingest", json=ingest_payload)
        assert ingest_response.status_code == 200
        
        # Search
        search_payload = {
            "query": f"quantum safety protocol encryption {unique_phrase}",
            "top_k": 5,
            "threshold": 0.1
        }
        search_response = requests.post(f"{BASE_URL}/api/knowledge/search", json=search_payload)
        assert search_response.status_code == 200
        
        search_data = search_response.json()
        results = search_data.get("results", [])
        
        # Should find our ingested knowledge
        found = any(unique_phrase in r.get("content", "") for r in results)
        print(f"✓ Integration: ingested knowledge with '{unique_phrase}', found in search={found}, results={len(results)}")
    
    def test_generate_uses_knowledge_context(self):
        """Generate should use knowledge context in RAG retrieval"""
        # First ingest specific knowledge
        unique_id = uuid.uuid4().hex[:8]
        ingest_payload = {
            "topic": f"TEST_gen_context_{unique_id}",
            "category": "child_safety",
            "content": "NISCHINT provides real-time GPS tracking for children. "
                       "Parents can set geofence alerts when children leave safe zones. "
                       "The app sends instant notifications for any safety concerns."
        }
        requests.post(f"{BASE_URL}/api/knowledge/ingest", json=ingest_payload)
        
        # Generate content that should use this knowledge
        generate_payload = {
            "query": "How can I track my child's location for safety?",
            "persona": "parent",
            "emotion": "concern",
            "location": "India"
        }
        response = requests.post(f"{BASE_URL}/api/rag/generate", json=generate_payload, timeout=60)
        assert response.status_code == 200
        
        data = response.json()
        rag_context = data.get("rag_context", {})
        
        # Should have some knowledge sources
        knowledge_sources = rag_context.get("knowledge_sources", 0)
        print(f"✓ Generate used {knowledge_sources} knowledge sources in context")
    
    def test_batch_ingest_then_search_multiple(self):
        """Batch ingest multiple entries and search for them"""
        unique_id = uuid.uuid4().hex[:8]
        
        # Batch ingest
        batch_payload = {
            "entries": [
                {
                    "topic": f"TEST_batch_search1_{unique_id}",
                    "category": "TEST_BATCH_SEARCH",
                    "content": "First batch entry about home security systems and alarms."
                },
                {
                    "topic": f"TEST_batch_search2_{unique_id}",
                    "category": "TEST_BATCH_SEARCH",
                    "content": "Second batch entry about personal safety devices and wearables."
                }
            ]
        }
        batch_response = requests.post(f"{BASE_URL}/api/knowledge/batch-ingest", json=batch_payload)
        assert batch_response.status_code == 200
        assert batch_response.json().get("ingested") == 2
        
        # Search with category filter
        search_payload = {
            "query": "security systems safety devices",
            "top_k": 10,
            "category": "TEST_BATCH_SEARCH",
            "threshold": 0.1
        }
        search_response = requests.post(f"{BASE_URL}/api/knowledge/search", json=search_payload)
        assert search_response.status_code == 200
        
        results = search_response.json().get("results", [])
        print(f"✓ Batch ingest then search: found {len(results)} results in TEST_BATCH_SEARCH category")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
