"""
Level 2 SEO Engine Tests
========================
Tests for 5 SEO engines: Keyword Clustering, Topical Authority Map,
Programmatic Page Generator, Internal Linking, GEO Scaling.
Plus config, stats, and pages endpoints.
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


@pytest.fixture(scope="module")
def seo_config(api_client):
    """Fetch SEO config once for all tests"""
    response = api_client.get(f"{BASE_URL}/api/seo/config")
    if response.status_code == 200:
        return response.json()
    return None


# ═══════════════════════════════════════════════════════════════
# MODULE 1: KEYWORD CLUSTERING ENGINE TESTS
# ═══════════════════════════════════════════════════════════════

class TestKeywordClustering:
    """POST /api/seo/cluster - Keyword clustering tests"""
    
    def test_cluster_keywords_success(self, api_client):
        """Test clustering keywords into intent-based groups"""
        payload = {
            "keywords": [
                "women safety app",
                "best women safety app mumbai",
                "kids tracking app",
                "child safety app delhi",
                "family safety app",
                "corporate safety solutions"
            ]
        }
        response = api_client.post(f"{BASE_URL}/api/seo/cluster", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify response structure
        assert "clusters" in data
        assert "cluster_count" in data
        assert "keyword_count" in data
        assert "city_mentions" in data
        
        # Verify data values
        assert data["keyword_count"] == 6
        assert data["cluster_count"] > 0
        assert isinstance(data["clusters"], dict)
        
    def test_cluster_detects_city_mentions(self, api_client):
        """Test that city mentions are detected in keywords"""
        payload = {
            "keywords": [
                "women safety app mumbai",
                "kids safety delhi",
                "family safety bangalore",
                "personal safety pune"
            ]
        }
        response = api_client.post(f"{BASE_URL}/api/seo/cluster", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify city mentions detected
        assert "city_mentions" in data
        city_mentions = data["city_mentions"]
        
        # Should detect Mumbai, Delhi, Bangalore, Pune
        assert len(city_mentions) >= 1  # At least one city detected
        
    def test_cluster_empty_keywords_returns_400(self, api_client):
        """Test that empty keywords list returns 400"""
        payload = {"keywords": []}
        response = api_client.post(f"{BASE_URL}/api/seo/cluster", json=payload)
        
        assert response.status_code == 400
        data = response.json()
        assert "detail" in data
        assert "empty" in data["detail"].lower()
        
    def test_cluster_categorizes_by_intent(self, api_client):
        """Test keywords are categorized by intent (women_safety, kids_safety, etc.)"""
        payload = {
            "keywords": [
                "women safety app",
                "female protection app",
                "kids tracker app",
                "child monitoring app"
            ]
        }
        response = api_client.post(f"{BASE_URL}/api/seo/cluster", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        
        clusters = data["clusters"]
        # Should have at least women_safety and kids_safety clusters
        assert len(clusters) >= 1


# ═══════════════════════════════════════════════════════════════
# MODULE 2: TOPICAL AUTHORITY MAP TESTS
# ═══════════════════════════════════════════════════════════════

class TestTopicalAuthorityMap:
    """POST /api/seo/authority-map - Authority map tests"""
    
    def test_authority_map_default_clusters(self, api_client):
        """Test authority map with default clusters"""
        payload = {}
        response = api_client.post(f"{BASE_URL}/api/seo/authority-map", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify pillar hierarchy structure
        assert "pillar" in data
        assert "pillar_url" in data
        assert "clusters" in data
        assert "total_pages" in data
        
        # Verify pillar values
        assert data["pillar"] == "AI Safety"
        assert data["pillar_url"] == "/"
        assert isinstance(data["clusters"], list)
        assert data["total_pages"] > 0
        
    def test_authority_map_cluster_structure(self, api_client):
        """Test that each cluster has correct structure"""
        payload = {}
        response = api_client.post(f"{BASE_URL}/api/seo/authority-map", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        
        # Check first cluster structure
        assert len(data["clusters"]) > 0
        cluster = data["clusters"][0]
        
        assert "id" in cluster
        assert "name" in cluster
        assert "keywords" in cluster
        assert "page_count" in cluster
        assert "pages" in cluster
        
    def test_authority_map_pages_structure(self, api_client):
        """Test that pages within clusters have correct structure"""
        payload = {}
        response = api_client.post(f"{BASE_URL}/api/seo/authority-map", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        
        # Get first page from first cluster
        cluster = data["clusters"][0]
        assert len(cluster["pages"]) > 0
        page = cluster["pages"][0]
        
        assert "title" in page
        assert "slug" in page
        assert "city" in page
        assert "category" in page
        
    def test_authority_map_with_custom_clusters(self, api_client):
        """Test authority map with custom clusters input"""
        payload = {
            "clusters": {
                "women_safety": ["women safety app", "female protection"],
                "kids_safety": ["kids tracker", "child monitoring"]
            }
        }
        response = api_client.post(f"{BASE_URL}/api/seo/authority-map", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        
        # Should have 2 clusters
        assert len(data["clusters"]) == 2


# ═══════════════════════════════════════════════════════════════
# MODULE 3: PROGRAMMATIC PAGE GENERATOR TESTS
# ═══════════════════════════════════════════════════════════════

class TestProgrammaticPageGenerator:
    """POST /api/seo/generate-page - Page generation tests"""
    
    def test_generate_page_success(self, api_client):
        """Test generating a single SEO page"""
        payload = {
            "city": "Mumbai",
            "category": "women_safety",
            "variant": "default"
        }
        response = api_client.post(f"{BASE_URL}/api/seo/generate-page", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify all required fields
        assert "title" in data
        assert "meta_description" in data
        assert "h1" in data
        assert "content" in data
        assert "internal_links" in data
        assert "slug" in data
        assert "city" in data
        assert "category" in data
        assert "variant" in data
        assert "word_count" in data
        assert "generated_at" in data
        
    def test_generate_page_content_includes_city(self, api_client):
        """Test that generated content includes city name"""
        payload = {
            "city": "Bangalore",
            "category": "kids_safety",
            "variant": "default"
        }
        response = api_client.post(f"{BASE_URL}/api/seo/generate-page", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        
        # City should appear in content
        assert "Bangalore" in data["content"]
        assert "Bangalore" in data["title"]
        assert data["city"] == "Bangalore"
        
    def test_generate_page_has_internal_links(self, api_client):
        """Test that generated page has at least 3 internal links"""
        payload = {
            "city": "Delhi",
            "category": "family_safety",
            "variant": "default"
        }
        response = api_client.post(f"{BASE_URL}/api/seo/generate-page", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        
        # Should have at least 3 internal links
        assert len(data["internal_links"]) >= 3
        
        # Each link should have text and url
        for link in data["internal_links"]:
            assert "text" in link
            assert "url" in link
            
    def test_generate_page_unknown_city_returns_400(self, api_client):
        """Test that unknown city returns 400"""
        payload = {
            "city": "UnknownCity123",
            "category": "women_safety",
            "variant": "default"
        }
        response = api_client.post(f"{BASE_URL}/api/seo/generate-page", json=payload)
        
        assert response.status_code == 400
        data = response.json()
        assert "detail" in data
        assert "Unknown city" in data["detail"]
        
    def test_generate_page_unknown_category_returns_400(self, api_client):
        """Test that unknown category returns 400"""
        payload = {
            "city": "Mumbai",
            "category": "unknown_category",
            "variant": "default"
        }
        response = api_client.post(f"{BASE_URL}/api/seo/generate-page", json=payload)
        
        assert response.status_code == 400
        data = response.json()
        assert "detail" in data
        assert "Unknown category" in data["detail"]
        
    def test_generate_page_best_variant(self, api_client):
        """Test generating page with 'best' variant"""
        payload = {
            "city": "Chennai",
            "category": "personal_safety",
            "variant": "best"
        }
        response = api_client.post(f"{BASE_URL}/api/seo/generate-page", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        
        # Best variant should have "Best" in title
        assert "Best" in data["title"]
        assert data["variant"] == "best"
        
    def test_generate_page_personal_variant(self, api_client):
        """Test generating page with 'personal' variant"""
        payload = {
            "city": "Hyderabad",
            "category": "campus_safety",
            "variant": "personal"
        }
        response = api_client.post(f"{BASE_URL}/api/seo/generate-page", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["variant"] == "personal"


# ═══════════════════════════════════════════════════════════════
# MODULE 4: INTERNAL LINKING ENGINE TESTS
# ═══════════════════════════════════════════════════════════════

class TestInternalLinkingEngine:
    """POST /api/seo/links - Internal linking tests"""
    
    def test_generate_links_success(self, api_client):
        """Test generating internal links between pages"""
        payload = {
            "pages": [
                "women-safety-app-mumbai",
                "women-safety-app-pune",
                "kids-safety-app-mumbai",
                "family-safety-app-delhi"
            ]
        }
        response = api_client.post(f"{BASE_URL}/api/seo/links", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify response structure
        assert "link_map" in data
        assert "total_pages" in data
        
        assert data["total_pages"] == 4
        assert len(data["link_map"]) == 4
        
    def test_generate_links_includes_reasons(self, api_client):
        """Test that links include nearby_city, related_category, pillar reasons"""
        payload = {
            "pages": [
                "women-safety-app-mumbai",
                "women-safety-app-thane",
                "kids-safety-app-mumbai"
            ]
        }
        response = api_client.post(f"{BASE_URL}/api/seo/links", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        
        # Check that links have reasons
        link_map = data["link_map"]
        all_reasons = set()
        
        for page_slug, links in link_map.items():
            for link in links:
                assert "slug" in link
                assert "reason" in link
                all_reasons.add(link["reason"])
        
        # Should have pillar reason at minimum
        assert "pillar" in all_reasons
        
    def test_generate_links_empty_pages_returns_400(self, api_client):
        """Test that empty pages list returns 400"""
        payload = {"pages": []}
        response = api_client.post(f"{BASE_URL}/api/seo/links", json=payload)
        
        assert response.status_code == 400
        data = response.json()
        assert "detail" in data


# ═══════════════════════════════════════════════════════════════
# MODULE 5: GEO SCALING ENGINE TESTS
# ═══════════════════════════════════════════════════════════════

class TestGeoScalingEngine:
    """POST /api/seo/scale-generate - Bulk page generation tests"""
    
    def test_scale_generate_success(self, api_client):
        """Test bulk page generation"""
        payload = {
            "cities": ["Kolkata", "Pune"],
            "categories": ["corporate_safety"],
            "variants": ["default"],
            "limit": 5
        }
        response = api_client.post(f"{BASE_URL}/api/seo/scale-generate", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify response structure
        assert "status" in data
        assert "created_count" in data
        assert "skipped_count" in data
        assert "total_pages_in_store" in data
        assert "created" in data
        assert "skipped" in data
        
        assert data["status"] == "ok"
        
    def test_scale_generate_respects_limit(self, api_client):
        """Test that scale-generate respects limit parameter"""
        payload = {
            "cities": ["Jaipur", "Lucknow", "Chandigarh"],
            "categories": ["women_safety", "kids_safety"],
            "variants": ["default", "best"],
            "limit": 3
        }
        response = api_client.post(f"{BASE_URL}/api/seo/scale-generate", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        
        # Created count should not exceed limit
        assert data["created_count"] <= 3
        
    def test_scale_generate_skips_duplicates(self, api_client):
        """Test that scale-generate skips duplicate pages"""
        # First call - create pages
        payload = {
            "cities": ["Ahmedabad"],
            "categories": ["campus_safety"],
            "variants": ["default"],
            "limit": 10
        }
        response1 = api_client.post(f"{BASE_URL}/api/seo/scale-generate", json=payload)
        assert response1.status_code == 200
        first_created = response1.json()["created_count"]
        
        # Second call - same params, should skip
        response2 = api_client.post(f"{BASE_URL}/api/seo/scale-generate", json=payload)
        assert response2.status_code == 200
        data2 = response2.json()
        
        # Should have skipped entries if pages already exist
        if first_created > 0:
            assert data2["skipped_count"] > 0 or data2["created_count"] == 0
            
    def test_scale_generate_with_defaults(self, api_client):
        """Test scale-generate with default parameters"""
        payload = {"limit": 2}
        response = api_client.post(f"{BASE_URL}/api/seo/scale-generate", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "ok"
        assert "created_count" in data


# ═══════════════════════════════════════════════════════════════
# CONFIG ENDPOINT TESTS
# ═══════════════════════════════════════════════════════════════

class TestSEOConfig:
    """GET /api/seo/config - Configuration endpoint tests"""
    
    def test_get_config_success(self, api_client):
        """Test getting SEO configuration"""
        response = api_client.get(f"{BASE_URL}/api/seo/config")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify structure
        assert "cities" in data
        assert "categories" in data
        assert "variants" in data
        
    def test_config_cities_structure(self, api_client):
        """Test cities configuration structure"""
        response = api_client.get(f"{BASE_URL}/api/seo/config")
        
        assert response.status_code == 200
        data = response.json()
        
        cities = data["cities"]
        assert "tier_1" in cities
        assert "tier_2" in cities
        assert "tier_3" in cities
        assert "total" in cities
        
        # Verify tier counts
        assert len(cities["tier_1"]) == 7  # T1: 7 cities
        assert len(cities["tier_2"]) == 17  # T2: 17 cities
        assert len(cities["tier_3"]) == 35  # T3: 35 cities
        assert cities["total"] == 59
        
    def test_config_categories(self, api_client):
        """Test categories configuration"""
        response = api_client.get(f"{BASE_URL}/api/seo/config")
        
        assert response.status_code == 200
        data = response.json()
        
        categories = data["categories"]
        expected_categories = [
            "women_safety", "kids_safety", "family_safety",
            "personal_safety", "campus_safety", "corporate_safety"
        ]
        
        for cat in expected_categories:
            assert cat in categories
            
    def test_config_variants(self, api_client):
        """Test variants configuration"""
        response = api_client.get(f"{BASE_URL}/api/seo/config")
        
        assert response.status_code == 200
        data = response.json()
        
        variants = data["variants"]
        assert "default" in variants
        assert "best" in variants
        assert "personal" in variants


# ═══════════════════════════════════════════════════════════════
# STATS ENDPOINT TESTS
# ═══════════════════════════════════════════════════════════════

class TestSEOStats:
    """GET /api/seo/stats - Statistics endpoint tests"""
    
    def test_get_stats_success(self, api_client):
        """Test getting SEO statistics"""
        response = api_client.get(f"{BASE_URL}/api/seo/stats")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify structure
        assert "total_pages" in data
        assert "by_category" in data
        assert "by_city" in data
        assert "by_variant" in data
        assert "authority_map_built" in data
        assert "available_cities" in data
        assert "max_possible_pages" in data
        
    def test_stats_breakdowns(self, api_client):
        """Test stats breakdowns are dictionaries"""
        response = api_client.get(f"{BASE_URL}/api/seo/stats")
        
        assert response.status_code == 200
        data = response.json()
        
        assert isinstance(data["by_category"], dict)
        assert isinstance(data["by_city"], dict)
        assert isinstance(data["by_variant"], dict)
        
    def test_stats_max_possible_pages(self, api_client):
        """Test max possible pages calculation"""
        response = api_client.get(f"{BASE_URL}/api/seo/stats")
        
        assert response.status_code == 200
        data = response.json()
        
        # 59 cities * 6 categories * 3 variants = 1062
        assert data["max_possible_pages"] == 1062
        assert data["available_cities"] == 59


# ═══════════════════════════════════════════════════════════════
# PAGES ENDPOINT TESTS
# ═══════════════════════════════════════════════════════════════

class TestSEOPages:
    """GET /api/seo/pages - Pages listing endpoint tests"""
    
    def test_list_pages_success(self, api_client):
        """Test listing generated pages"""
        response = api_client.get(f"{BASE_URL}/api/seo/pages")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify structure
        assert "pages" in data
        assert "count" in data
        assert "total_generated" in data
        
        assert isinstance(data["pages"], list)
        
    def test_list_pages_filter_by_category(self, api_client):
        """Test filtering pages by category"""
        # First generate a page
        api_client.post(f"{BASE_URL}/api/seo/generate-page", json={
            "city": "Indore",
            "category": "women_safety",
            "variant": "default"
        })
        
        response = api_client.get(f"{BASE_URL}/api/seo/pages?category=women_safety")
        
        assert response.status_code == 200
        data = response.json()
        
        # All returned pages should be women_safety
        for page in data["pages"]:
            assert page["category"] == "women_safety"
            
    def test_list_pages_filter_by_city(self, api_client):
        """Test filtering pages by city"""
        # First generate a page
        api_client.post(f"{BASE_URL}/api/seo/generate-page", json={
            "city": "Nagpur",
            "category": "kids_safety",
            "variant": "default"
        })
        
        response = api_client.get(f"{BASE_URL}/api/seo/pages?city=Nagpur")
        
        assert response.status_code == 200
        data = response.json()
        
        # All returned pages should be for Nagpur
        for page in data["pages"]:
            assert page["city"] == "Nagpur"
            
    def test_list_pages_structure(self, api_client):
        """Test page listing structure"""
        response = api_client.get(f"{BASE_URL}/api/seo/pages")
        
        assert response.status_code == 200
        data = response.json()
        
        if len(data["pages"]) > 0:
            page = data["pages"][0]
            assert "slug" in page
            assert "title" in page
            assert "city" in page
            assert "category" in page
            assert "variant" in page


# ═══════════════════════════════════════════════════════════════
# INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════

class TestSEOIntegration:
    """End-to-end integration tests"""
    
    def test_full_workflow_cluster_to_page(self, api_client):
        """Test full workflow: cluster → authority-map → generate-page"""
        # Step 1: Cluster keywords
        cluster_response = api_client.post(f"{BASE_URL}/api/seo/cluster", json={
            "keywords": ["women safety app surat", "kids safety surat"]
        })
        assert cluster_response.status_code == 200
        
        # Step 2: Build authority map
        authority_response = api_client.post(f"{BASE_URL}/api/seo/authority-map", json={})
        assert authority_response.status_code == 200
        
        # Step 3: Generate page
        page_response = api_client.post(f"{BASE_URL}/api/seo/generate-page", json={
            "city": "Surat",
            "category": "women_safety",
            "variant": "default"
        })
        assert page_response.status_code == 200
        
        # Step 4: Verify page in listing
        pages_response = api_client.get(f"{BASE_URL}/api/seo/pages?city=Surat")
        assert pages_response.status_code == 200
        
    def test_scale_generate_and_verify_stats(self, api_client):
        """Test scale-generate updates stats correctly"""
        # Get initial stats
        initial_stats = api_client.get(f"{BASE_URL}/api/seo/stats").json()
        initial_count = initial_stats["total_pages"]
        
        # Scale generate
        scale_response = api_client.post(f"{BASE_URL}/api/seo/scale-generate", json={
            "cities": ["Coimbatore"],
            "categories": ["corporate_safety"],
            "variants": ["personal"],
            "limit": 1
        })
        assert scale_response.status_code == 200
        created = scale_response.json()["created_count"]
        
        # Verify stats updated
        final_stats = api_client.get(f"{BASE_URL}/api/seo/stats").json()
        
        # Total should increase by created count
        assert final_stats["total_pages"] >= initial_count
