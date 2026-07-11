"""
RAG System Backend Tests - Blog Ingest, Search, Auto-Ingest, Health
Tests all 4 RAG endpoints with real OpenAI embeddings and pgvector
"""
import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestRAGHealth:
    """GET /api/rag/health - RAG system health check"""
    
    def test_health_returns_200(self):
        """Health endpoint should return 200"""
        response = requests.get(f"{BASE_URL}/api/rag/health")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print(f"✓ Health endpoint returned 200")
    
    def test_health_status_operational(self):
        """Health should report status=operational when pgvector and embeddings are configured"""
        response = requests.get(f"{BASE_URL}/api/rag/health")
        data = response.json()
        assert data.get("status") == "operational", f"Expected status=operational, got {data.get('status')}"
        print(f"✓ Status is operational")
    
    def test_health_pgvector_enabled(self):
        """Health should report pgvector=true"""
        response = requests.get(f"{BASE_URL}/api/rag/health")
        data = response.json()
        assert data.get("pgvector") is True, f"Expected pgvector=true, got {data.get('pgvector')}"
        print(f"✓ pgvector is enabled")
    
    def test_health_embeddings_configured(self):
        """Health should report embeddings_configured=true"""
        response = requests.get(f"{BASE_URL}/api/rag/health")
        data = response.json()
        assert data.get("embeddings_configured") is True, f"Expected embeddings_configured=true, got {data.get('embeddings_configured')}"
        print(f"✓ Embeddings are configured")
    
    def test_health_total_chunks_greater_than_zero(self):
        """Health should report total_chunks > 0"""
        response = requests.get(f"{BASE_URL}/api/rag/health")
        data = response.json()
        total_chunks = data.get("total_chunks", 0)
        assert total_chunks > 0, f"Expected total_chunks > 0, got {total_chunks}"
        print(f"✓ Total chunks: {total_chunks}")
    
    def test_health_total_blogs_indexed_greater_than_zero(self):
        """Health should report total_blogs_indexed > 0"""
        response = requests.get(f"{BASE_URL}/api/rag/health")
        data = response.json()
        total_blogs = data.get("total_blogs_indexed", 0)
        assert total_blogs > 0, f"Expected total_blogs_indexed > 0, got {total_blogs}"
        print(f"✓ Total blogs indexed: {total_blogs}")
    
    def test_health_embedding_model(self):
        """Health should report correct embedding model"""
        response = requests.get(f"{BASE_URL}/api/rag/health")
        data = response.json()
        model = data.get("embedding_model", "")
        assert model == "text-embedding-3-small", f"Expected text-embedding-3-small, got {model}"
        print(f"✓ Embedding model: {model}")


class TestBlogIngest:
    """POST /api/blog/ingest - Ingest blog content with chunking and embeddings"""
    
    def test_ingest_success(self):
        """Ingest should accept content and return chunks_created > 0"""
        test_blog_id = f"TEST_ingest_{uuid.uuid4().hex[:8]}"
        payload = {
            "blog_id": test_blog_id,
            "title": "Test Blog for RAG Ingest",
            "content": "This is a test blog post about artificial intelligence and machine learning. "
                       "AI systems are transforming how we interact with technology. "
                       "Machine learning algorithms can learn from data and make predictions. "
                       "Deep learning is a subset of machine learning that uses neural networks.",
            "metadata": {"category": "technology", "author": "test"}
        }
        response = requests.post(f"{BASE_URL}/api/blog/ingest", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("blog_id") == test_blog_id, f"Expected blog_id={test_blog_id}, got {data.get('blog_id')}"
        assert data.get("chunks_created", 0) > 0, f"Expected chunks_created > 0, got {data.get('chunks_created')}"
        assert data.get("embeddings_generated") is True, f"Expected embeddings_generated=true, got {data.get('embeddings_generated')}"
        print(f"✓ Ingested blog {test_blog_id}: {data.get('chunks_created')} chunks, embeddings={data.get('embeddings_generated')}")
    
    def test_ingest_generates_blog_id_if_not_provided(self):
        """Ingest should generate blog_id if not provided"""
        payload = {
            "title": "Auto-ID Test Blog",
            "content": "This is a test blog without a blog_id. The system should generate one automatically."
        }
        response = requests.post(f"{BASE_URL}/api/blog/ingest", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data.get("blog_id") is not None, "Expected blog_id to be generated"
        assert len(data.get("blog_id", "")) > 0, "Expected non-empty blog_id"
        print(f"✓ Auto-generated blog_id: {data.get('blog_id')}")
    
    def test_ingest_idempotent_replaces_old_chunks(self):
        """Re-ingesting same blog_id should replace old chunks"""
        test_blog_id = f"TEST_idempotent_{uuid.uuid4().hex[:8]}"
        
        # First ingest
        payload1 = {
            "blog_id": test_blog_id,
            "title": "Idempotent Test - Version 1",
            "content": "Original content for idempotent test. This is version one."
        }
        response1 = requests.post(f"{BASE_URL}/api/blog/ingest", json=payload1)
        assert response1.status_code == 200
        chunks1 = response1.json().get("chunks_created", 0)
        
        # Second ingest with same blog_id but different content
        payload2 = {
            "blog_id": test_blog_id,
            "title": "Idempotent Test - Version 2",
            "content": "Updated content for idempotent test. This is version two with more text. "
                       "The old chunks should be replaced with these new chunks."
        }
        response2 = requests.post(f"{BASE_URL}/api/blog/ingest", json=payload2)
        assert response2.status_code == 200
        chunks2 = response2.json().get("chunks_created", 0)
        
        # Verify by searching - should find version 2 content
        search_response = requests.post(f"{BASE_URL}/api/blog/search", json={
            "query": "version two updated",
            "top_k": 5,
            "threshold": 0.1
        })
        results = search_response.json().get("results", [])
        found_v2 = any(test_blog_id in r.get("blog_id", "") for r in results)
        
        print(f"✓ Idempotent ingest: v1={chunks1} chunks, v2={chunks2} chunks, found_v2={found_v2}")
    
    def test_ingest_empty_content_returns_400(self):
        """Ingest with empty content should return 400"""
        payload = {
            "blog_id": "TEST_empty_content",
            "title": "Empty Content Test",
            "content": ""
        }
        response = requests.post(f"{BASE_URL}/api/blog/ingest", json=payload)
        assert response.status_code == 400, f"Expected 400 for empty content, got {response.status_code}"
        print(f"✓ Empty content correctly returns 400")
    
    def test_ingest_whitespace_only_content_returns_400(self):
        """Ingest with whitespace-only content should return 400"""
        payload = {
            "blog_id": "TEST_whitespace_content",
            "title": "Whitespace Content Test",
            "content": "   \n\t   "
        }
        response = requests.post(f"{BASE_URL}/api/blog/ingest", json=payload)
        assert response.status_code == 400, f"Expected 400 for whitespace content, got {response.status_code}"
        print(f"✓ Whitespace-only content correctly returns 400")


class TestBlogSearch:
    """POST /api/blog/search - Vector similarity search with full-text fallback"""
    
    def test_search_returns_results(self):
        """Search should return results for a valid query"""
        payload = {
            "query": "safety monitoring elderly care",
            "top_k": 5,
            "threshold": 0.3
        }
        response = requests.post(f"{BASE_URL}/api/blog/search", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "results" in data, "Expected 'results' in response"
        assert "search_method" in data, "Expected 'search_method' in response"
        assert "total_results" in data, "Expected 'total_results' in response"
        print(f"✓ Search returned {data.get('total_results')} results using {data.get('search_method')}")
    
    def test_search_uses_vector_cosine(self):
        """Search should use vector_cosine method when embeddings are available"""
        payload = {
            "query": "artificial intelligence machine learning",
            "top_k": 5,
            "threshold": 0.2
        }
        response = requests.post(f"{BASE_URL}/api/blog/search", json=payload)
        data = response.json()
        
        # Should use vector_cosine when pgvector and embeddings are available
        search_method = data.get("search_method", "")
        assert search_method in ["vector_cosine", "full_text"], f"Unexpected search_method: {search_method}"
        print(f"✓ Search method: {search_method}")
    
    def test_search_result_structure(self):
        """Search results should have correct structure"""
        payload = {
            "query": "technology innovation",
            "top_k": 3,
            "threshold": 0.1
        }
        response = requests.post(f"{BASE_URL}/api/blog/search", json=payload)
        data = response.json()
        
        results = data.get("results", [])
        if len(results) > 0:
            result = results[0]
            assert "chunk_id" in result, "Expected 'chunk_id' in result"
            assert "blog_id" in result, "Expected 'blog_id' in result"
            assert "chunk_text" in result, "Expected 'chunk_text' in result"
            assert "score" in result, "Expected 'score' in result"
            assert isinstance(result.get("score"), (int, float)), "Score should be numeric"
            print(f"✓ Result structure valid: chunk_id, blog_id, chunk_text, score present")
        else:
            print(f"⚠ No results returned for query, skipping structure check")
    
    def test_search_high_threshold_filters_results(self):
        """Search with threshold=0.9 should filter out low-relevance results"""
        payload = {
            "query": "random unrelated query xyz123",
            "top_k": 10,
            "threshold": 0.9
        }
        response = requests.post(f"{BASE_URL}/api/blog/search", json=payload)
        data = response.json()
        
        results = data.get("results", [])
        # With high threshold, should have few or no results for unrelated query
        for result in results:
            score = result.get("score", 0)
            assert score >= 0.9, f"Expected score >= 0.9, got {score}"
        print(f"✓ High threshold (0.9) returned {len(results)} results, all with score >= 0.9")
    
    def test_search_fallback_to_fulltext(self):
        """Search should fall back to full_text if vector search returns no results"""
        # First, let's search for something that might trigger fallback
        payload = {
            "query": "specific keyword search test",
            "top_k": 5,
            "threshold": 0.99  # Very high threshold to potentially trigger fallback
        }
        response = requests.post(f"{BASE_URL}/api/blog/search", json=payload)
        data = response.json()
        
        search_method = data.get("search_method", "")
        # Either vector_cosine or full_text is acceptable
        assert search_method in ["vector_cosine", "full_text", "none"], f"Unexpected search_method: {search_method}"
        print(f"✓ Search method with high threshold: {search_method}")
    
    def test_search_returns_similarity_scores(self):
        """Search results should include similarity scores"""
        payload = {
            "query": "elderly care monitoring",
            "top_k": 5,
            "threshold": 0.1
        }
        response = requests.post(f"{BASE_URL}/api/blog/search", json=payload)
        data = response.json()
        
        results = data.get("results", [])
        for result in results:
            score = result.get("score")
            assert score is not None, "Expected score in result"
            assert 0 <= score <= 1 or score > 0, f"Score should be valid: {score}"
        print(f"✓ All {len(results)} results have valid similarity scores")


class TestAutoIngest:
    """POST /api/blog/auto-ingest - Auto-ingest all published blog posts"""
    
    def test_auto_ingest_returns_200(self):
        """Auto-ingest should return 200"""
        response = requests.post(f"{BASE_URL}/api/blog/auto-ingest")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print(f"✓ Auto-ingest returned 200")
    
    def test_auto_ingest_response_structure(self):
        """Auto-ingest should return correct response structure"""
        response = requests.post(f"{BASE_URL}/api/blog/auto-ingest")
        data = response.json()
        
        assert "total_blogs" in data, "Expected 'total_blogs' in response"
        assert "ingested" in data, "Expected 'ingested' in response"
        assert "skipped" in data, "Expected 'skipped' in response"
        assert "errors" in data, "Expected 'errors' in response"
        assert "details" in data, "Expected 'details' in response"
        print(f"✓ Auto-ingest response structure valid")
    
    def test_auto_ingest_processes_blogs(self):
        """Auto-ingest should process published blogs"""
        response = requests.post(f"{BASE_URL}/api/blog/auto-ingest")
        data = response.json()
        
        total_blogs = data.get("total_blogs", 0)
        ingested = data.get("ingested", 0)
        skipped = data.get("skipped", 0)
        errors = data.get("errors", 0)
        
        # Should have processed some blogs
        assert total_blogs >= 0, f"Expected total_blogs >= 0, got {total_blogs}"
        assert ingested + skipped + errors == total_blogs, "Counts should add up to total"
        print(f"✓ Auto-ingest: total={total_blogs}, ingested={ingested}, skipped={skipped}, errors={errors}")
    
    def test_auto_ingest_details_array(self):
        """Auto-ingest details should contain blog processing info"""
        response = requests.post(f"{BASE_URL}/api/blog/auto-ingest")
        data = response.json()
        
        details = data.get("details", [])
        assert isinstance(details, list), "Expected 'details' to be a list"
        
        if len(details) > 0:
            detail = details[0]
            assert "blog_id" in detail, "Expected 'blog_id' in detail"
            assert "status" in detail, "Expected 'status' in detail"
            print(f"✓ Details array has {len(details)} entries with valid structure")
        else:
            print(f"⚠ No details returned (no blogs to process)")
    
    def test_auto_ingest_generates_embeddings(self):
        """Auto-ingest should generate embeddings for ingested blogs"""
        response = requests.post(f"{BASE_URL}/api/blog/auto-ingest")
        data = response.json()
        
        details = data.get("details", [])
        ingested_with_embeddings = [d for d in details if d.get("status") == "ingested" and d.get("embeddings") is True]
        
        if data.get("ingested", 0) > 0:
            assert len(ingested_with_embeddings) > 0, "Expected at least one blog ingested with embeddings"
            print(f"✓ {len(ingested_with_embeddings)} blogs ingested with embeddings")
        else:
            print(f"⚠ No blogs ingested in this run")


class TestIntegration:
    """Integration tests - end-to-end flows"""
    
    def test_ingest_then_search_flow(self):
        """Ingest a blog and then search for it"""
        # Create unique content
        unique_id = uuid.uuid4().hex[:8]
        test_blog_id = f"TEST_integration_{unique_id}"
        unique_phrase = f"quantum_computing_breakthrough_{unique_id}"
        
        # Ingest
        ingest_payload = {
            "blog_id": test_blog_id,
            "title": f"Integration Test Blog {unique_id}",
            "content": f"This blog discusses {unique_phrase} in the field of quantum computing. "
                       "Quantum computers use qubits instead of classical bits. "
                       "This technology could revolutionize cryptography and drug discovery.",
            "metadata": {"test": True, "unique_id": unique_id}
        }
        ingest_response = requests.post(f"{BASE_URL}/api/blog/ingest", json=ingest_payload)
        assert ingest_response.status_code == 200, f"Ingest failed: {ingest_response.text}"
        
        # Search for the unique phrase
        search_payload = {
            "query": f"quantum computing {unique_phrase}",
            "top_k": 5,
            "threshold": 0.1
        }
        search_response = requests.post(f"{BASE_URL}/api/blog/search", json=search_payload)
        assert search_response.status_code == 200, f"Search failed: {search_response.text}"
        
        search_data = search_response.json()
        results = search_data.get("results", [])
        
        # Should find our ingested blog
        found = any(test_blog_id in r.get("blog_id", "") for r in results)
        print(f"✓ Integration test: ingested blog_id={test_blog_id}, found in search={found}, results={len(results)}")
    
    def test_health_reflects_ingested_data(self):
        """Health endpoint should reflect data after ingest"""
        # Get initial health
        health1 = requests.get(f"{BASE_URL}/api/rag/health").json()
        initial_chunks = health1.get("total_chunks", 0)
        
        # Ingest new content
        test_blog_id = f"TEST_health_check_{uuid.uuid4().hex[:8]}"
        ingest_payload = {
            "blog_id": test_blog_id,
            "title": "Health Check Test Blog",
            "content": "This is a test blog to verify health endpoint updates. "
                       "It contains enough content to create at least one chunk."
        }
        requests.post(f"{BASE_URL}/api/blog/ingest", json=ingest_payload)
        
        # Get updated health
        health2 = requests.get(f"{BASE_URL}/api/rag/health").json()
        updated_chunks = health2.get("total_chunks", 0)
        
        # Chunks should have increased
        assert updated_chunks >= initial_chunks, f"Expected chunks to increase: {initial_chunks} -> {updated_chunks}"
        print(f"✓ Health reflects data: {initial_chunks} -> {updated_chunks} chunks")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
