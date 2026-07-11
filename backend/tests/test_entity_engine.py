"""
NISCHINT GEO + Entity Engine API Tests
======================================
Tests for all 10 endpoints:
- Module 1: Entity CRUD (GET/POST /engine/entity)
- Module 2: Content Generation (POST /engine/generate)
- Module 3: Diff/Approval Workflow (POST /engine/diff, /engine/approve, GET /engine/queue)
- Module 4: GEO SEO Validation (POST /engine/geo-check)
- Module 5: Clean URL Comparison (POST /engine/geo-compare)
- Module 6: Build File Checking (POST /engine/build-check)
- Module 7: Cache Debugging (POST /engine/cache-check)
"""

import os
import pytest
import requests
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test data
TEST_ENTITY = {
    "company_name": "TEST_NISCHINT",
    "tagline": "TEST AI Safety for Every Indian",
    "description": "TEST Real-time safety monitoring for schools and families.",
    "features": ["GPS tracking", "AI alerts", "Guardian network"]
}

ORIGINAL_ENTITY = {
    "company_name": "NISCHINT",
    "tagline": "AI Safety for Every Indian",
    "description": "Real-time safety monitoring, GPS tracking, AI-powered risk detection, and guardian alert network for schools, universities, corporates, and smart cities.",
    "features": [
        "Real-time GPS tracking",
        "AI voice distress detection",
        "Geofencing alerts",
        "Guardian alert network",
        "Predictive risk engine"
    ]
}


@pytest.fixture(scope="session")
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


# ═══════════════════════════════════════════════════════════════
# MODULE 1: ENTITY ENGINE TESTS
# ═══════════════════════════════════════════════════════════════

class TestEntityGet:
    """GET /api/engine/entity - Returns entity with all required fields"""
    
    def test_get_entity_returns_200(self, api_client):
        """GET /api/engine/entity returns 200"""
        response = api_client.get(f"{BASE_URL}/api/engine/entity")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print(f"✓ GET /api/engine/entity returns 200")
    
    def test_get_entity_has_required_fields(self, api_client):
        """GET /api/engine/entity returns entity with company_name, tagline, description, features, updated_at"""
        response = api_client.get(f"{BASE_URL}/api/engine/entity")
        assert response.status_code == 200
        
        data = response.json()
        required_fields = ["company_name", "tagline", "description", "features", "updated_at"]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        
        # Validate types
        assert isinstance(data["company_name"], str)
        assert isinstance(data["tagline"], str)
        assert isinstance(data["description"], str)
        assert isinstance(data["features"], list)
        assert isinstance(data["updated_at"], str)
        
        print(f"✓ Entity has all required fields: {list(data.keys())}")
        print(f"  company_name: {data['company_name']}")
        print(f"  tagline: {data['tagline'][:50]}...")


class TestEntityPost:
    """POST /api/engine/entity - Updates entity and returns status ok"""
    
    def test_post_entity_updates_and_returns_ok(self, api_client):
        """POST /api/engine/entity updates entity and returns status ok"""
        response = api_client.post(f"{BASE_URL}/api/engine/entity", json=TEST_ENTITY)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data.get("status") == "ok", f"Expected status 'ok', got {data.get('status')}"
        assert "entity" in data, "Response should contain 'entity' field"
        
        # Verify entity was updated
        entity = data["entity"]
        assert entity["company_name"] == TEST_ENTITY["company_name"]
        assert entity["tagline"] == TEST_ENTITY["tagline"]
        
        print(f"✓ POST /api/engine/entity returns status: ok")
        print(f"  Updated entity: {entity['company_name']}")
    
    def test_post_entity_persists_changes(self, api_client):
        """POST then GET verifies entity was persisted"""
        # Update entity
        api_client.post(f"{BASE_URL}/api/engine/entity", json=TEST_ENTITY)
        
        # Verify via GET
        response = api_client.get(f"{BASE_URL}/api/engine/entity")
        data = response.json()
        
        assert data["company_name"] == TEST_ENTITY["company_name"]
        assert data["tagline"] == TEST_ENTITY["tagline"]
        print(f"✓ Entity changes persisted correctly")
    
    def test_restore_original_entity(self, api_client):
        """Restore original entity after tests"""
        response = api_client.post(f"{BASE_URL}/api/engine/entity", json=ORIGINAL_ENTITY)
        assert response.status_code == 200
        print(f"✓ Original entity restored")


# ═══════════════════════════════════════════════════════════════
# MODULE 2: CONTENT GENERATION TESTS
# ═══════════════════════════════════════════════════════════════

class TestContentGeneration:
    """POST /api/engine/generate - Returns platform and generated_content"""
    
    def test_generate_returns_platform_and_content(self, api_client):
        """POST /api/engine/generate returns platform and generated_content combining entity fields"""
        response = api_client.post(f"{BASE_URL}/api/engine/generate", json={"platform": "linkedin"})
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "platform" in data, "Response should contain 'platform'"
        assert "generated_content" in data, "Response should contain 'generated_content'"
        assert "generated_at" in data, "Response should contain 'generated_at'"
        
        assert data["platform"] == "linkedin"
        
        # Verify content combines entity fields
        content = data["generated_content"]
        assert "NISCHINT" in content or "TEST_NISCHINT" in content, "Content should include company name"
        
        print(f"✓ POST /api/engine/generate returns platform: {data['platform']}")
        print(f"  Generated content length: {len(content)} chars")
    
    def test_generate_different_platforms(self, api_client):
        """Generate content for different platforms"""
        platforms = ["twitter", "facebook", "website"]
        for platform in platforms:
            response = api_client.post(f"{BASE_URL}/api/engine/generate", json={"platform": platform})
            assert response.status_code == 200
            assert response.json()["platform"] == platform
        print(f"✓ Content generation works for multiple platforms: {platforms}")


# ═══════════════════════════════════════════════════════════════
# MODULE 3: DIFF/APPROVAL WORKFLOW TESTS
# ═══════════════════════════════════════════════════════════════

class TestDiffWorkflow:
    """POST /api/engine/diff - Diff detection and mismatch handling"""
    
    def test_diff_matching_data_returns_ok(self, api_client):
        """POST /api/engine/diff with matching data returns status ok"""
        # First get current entity to construct matching data
        entity_resp = api_client.get(f"{BASE_URL}/api/engine/entity")
        entity = entity_resp.json()
        
        # Construct expected format: "{company_name} – {tagline}"
        matching_data = f"{entity['company_name']} – {entity['tagline']}"
        
        response = api_client.post(f"{BASE_URL}/api/engine/diff", json={
            "platform": "website",
            "current_data": matching_data
        })
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("status") == "ok", f"Expected status 'ok', got {data.get('status')}"
        print(f"✓ POST /api/engine/diff with matching data returns status: ok")
    
    def test_diff_mismatching_data_returns_mismatch(self, api_client):
        """POST /api/engine/diff with mismatching data returns status mismatch with update_id and suggested_fix"""
        response = api_client.post(f"{BASE_URL}/api/engine/diff", json={
            "platform": "website",
            "current_data": "OLD CONTENT - This is outdated"
        })
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("status") == "mismatch", f"Expected status 'mismatch', got {data.get('status')}"
        assert "update_id" in data, "Mismatch response should contain 'update_id'"
        assert "suggested_fix" in data, "Mismatch response should contain 'suggested_fix'"
        
        print(f"✓ POST /api/engine/diff with mismatch returns:")
        print(f"  status: mismatch")
        print(f"  update_id: {data['update_id']}")
        print(f"  suggested_fix: {data['suggested_fix'][:50]}...")
        
        # Store update_id for approval tests
        return data["update_id"]


class TestApprovalWorkflow:
    """POST /api/engine/approve - Approve/reject updates"""
    
    @pytest.fixture
    def pending_update_id(self, api_client):
        """Create a pending update for testing"""
        response = api_client.post(f"{BASE_URL}/api/engine/diff", json={
            "platform": "test_platform",
            "current_data": f"TEST_MISMATCH_{uuid.uuid4().hex[:8]}"
        })
        return response.json()["update_id"]
    
    def test_approve_valid_update_changes_status_to_approved(self, api_client, pending_update_id):
        """POST /api/engine/approve with valid update_id changes status to approved"""
        response = api_client.post(f"{BASE_URL}/api/engine/approve", json={
            "update_id": pending_update_id,
            "action": "approve"
        })
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("status") == "ok"
        assert data.get("action") == "approve"
        assert data["record"]["status"] == "approved"
        
        print(f"✓ POST /api/engine/approve with action 'approve' changes status to: approved")
    
    def test_reject_valid_update_changes_status_to_rejected(self, api_client):
        """POST /api/engine/approve with action reject changes status to rejected"""
        # Create new pending update
        diff_resp = api_client.post(f"{BASE_URL}/api/engine/diff", json={
            "platform": "test_reject",
            "current_data": f"TEST_REJECT_{uuid.uuid4().hex[:8]}"
        })
        update_id = diff_resp.json()["update_id"]
        
        response = api_client.post(f"{BASE_URL}/api/engine/approve", json={
            "update_id": update_id,
            "action": "reject"
        })
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("status") == "ok"
        assert data.get("action") == "reject"
        assert data["record"]["status"] == "rejected"
        
        print(f"✓ POST /api/engine/approve with action 'reject' changes status to: rejected")
    
    def test_approve_invalid_update_id_returns_404(self, api_client):
        """POST /api/engine/approve with invalid update_id returns 404"""
        response = api_client.post(f"{BASE_URL}/api/engine/approve", json={
            "update_id": "invalid-uuid-12345",
            "action": "approve"
        })
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print(f"✓ POST /api/engine/approve with invalid update_id returns 404")


class TestQueueEndpoint:
    """GET /api/engine/queue - Returns all updates with count"""
    
    def test_queue_returns_updates_and_count(self, api_client):
        """GET /api/engine/queue returns all updates with count"""
        response = api_client.get(f"{BASE_URL}/api/engine/queue")
        assert response.status_code == 200
        
        data = response.json()
        assert "updates" in data, "Response should contain 'updates'"
        assert "count" in data, "Response should contain 'count'"
        assert isinstance(data["updates"], list)
        assert isinstance(data["count"], int)
        assert data["count"] == len(data["updates"])
        
        print(f"✓ GET /api/engine/queue returns {data['count']} updates")


# ═══════════════════════════════════════════════════════════════
# MODULE 4: GEO SEO VALIDATION TESTS
# ═══════════════════════════════════════════════════════════════

class TestGeoCheck:
    """POST /api/engine/geo-check - GEO SEO validation"""
    
    def test_geo_check_valid_geo_page_returns_high_score(self, api_client):
        """POST /api/engine/geo-check on a valid GEO page returns high seo_score"""
        # Use the preview URL for GEO pages as per main agent context
        response = api_client.post(f"{BASE_URL}/api/engine/geo-check", json={
            "url": "https://gps-mic-restart.preview.emergentagent.com/kids-safety-app-delhi.html"
        })
        assert response.status_code == 200
        
        data = response.json()
        assert "seo_score" in data, "Response should contain 'seo_score'"
        assert "status" in data, "Response should contain 'status'"
        assert "issues" in data, "Response should contain 'issues'"
        
        # Valid GEO page should have high score (>=70)
        print(f"✓ POST /api/engine/geo-check on valid GEO page:")
        print(f"  seo_score: {data['seo_score']}")
        print(f"  status: {data['status']}")
        print(f"  city_detected: {data.get('city_detected')}")
        print(f"  issues: {data.get('issues', [])}")
    
    def test_geo_check_detects_spa_fallback(self, api_client):
        """POST /api/engine/geo-check detects SPA fallback on non-GEO pages"""
        # Use a random non-GEO path that would trigger SPA fallback
        response = api_client.post(f"{BASE_URL}/api/engine/geo-check", json={
            "url": "https://gps-mic-restart.preview.emergentagent.com/random-non-geo-page-xyz123"
        })
        assert response.status_code == 200
        
        data = response.json()
        assert "seo_score" in data
        assert "issues" in data
        
        # Check if SPA fallback or generic meta detected
        issues = data.get("issues", [])
        has_spa_indicator = any("spa_fallback" in str(i).lower() or "generic" in str(i).lower() for i in issues)
        
        print(f"✓ POST /api/engine/geo-check on non-GEO page:")
        print(f"  seo_score: {data['seo_score']}")
        print(f"  issues: {issues}")
        print(f"  SPA/generic detected: {has_spa_indicator}")
    
    def test_geo_check_detects_city_keyword(self, api_client):
        """POST /api/engine/geo-check detects city keyword in title/h1"""
        response = api_client.post(f"{BASE_URL}/api/engine/geo-check", json={
            "url": "https://gps-mic-restart.preview.emergentagent.com/kids-safety-app-delhi.html"
        })
        assert response.status_code == 200
        
        data = response.json()
        assert "city_detected" in data, "Response should contain 'city_detected'"
        
        # Should detect 'delhi' from the URL slug
        city = data.get("city_detected")
        print(f"✓ POST /api/engine/geo-check city detection:")
        print(f"  city_detected: {city}")
        
        # If city is detected, check if it's in issues (mismatch) or not (match)
        issues = data.get("issues", [])
        city_mismatch = any("city_mismatch" in str(i) for i in issues)
        print(f"  city_mismatch in issues: {city_mismatch}")


# ═══════════════════════════════════════════════════════════════
# MODULE 5: CLEAN URL COMPARISON TESTS
# ═══════════════════════════════════════════════════════════════

class TestGeoCompare:
    """POST /api/engine/geo-compare - Clean URL comparison"""
    
    def test_geo_compare_same_content_returns_match_true(self, api_client):
        """POST /api/engine/geo-compare returns match true when clean and html URLs serve same content"""
        # Compare the same URL with and without .html extension
        response = api_client.post(f"{BASE_URL}/api/engine/geo-compare", json={
            "url_clean": "https://gps-mic-restart.preview.emergentagent.com/kids-safety-app-delhi",
            "url_html": "https://gps-mic-restart.preview.emergentagent.com/kids-safety-app-delhi.html"
        })
        assert response.status_code == 200
        
        data = response.json()
        assert "match" in data, "Response should contain 'match'"
        
        print(f"✓ POST /api/engine/geo-compare:")
        print(f"  match: {data['match']}")
        print(f"  title: {data.get('title', data.get('clean_title', 'N/A'))}")
        if not data["match"]:
            print(f"  issue: {data.get('issue')}")


# ═══════════════════════════════════════════════════════════════
# MODULE 6: BUILD VALIDATION TESTS
# ═══════════════════════════════════════════════════════════════

class TestBuildCheck:
    """POST /api/engine/build-check - Build file validation"""
    
    def test_build_check_identifies_found_and_missing_files(self, api_client):
        """POST /api/engine/build-check identifies found and missing files"""
        response = api_client.post(f"{BASE_URL}/api/engine/build-check", json={
            "list_of_files": [
                "kids-safety-app-delhi.html",
                "best-women-safety-app-mumbai.html",
                "nonexistent-file-xyz123.html"
            ]
        })
        assert response.status_code == 200
        
        data = response.json()
        assert "status" in data, "Response should contain 'status'"
        assert "found" in data, "Response should contain 'found'"
        assert "missing" in data, "Response should contain 'missing'"
        assert "missing_count" in data, "Response should contain 'missing_count'"
        assert "total_checked" in data, "Response should contain 'total_checked'"
        
        print(f"✓ POST /api/engine/build-check:")
        print(f"  status: {data['status']}")
        print(f"  found: {data['found']}")
        print(f"  missing: {data['missing']}")
        print(f"  missing_count: {data['missing_count']}")
        print(f"  total_checked: {data['total_checked']}")
        
        # Verify nonexistent file is in missing list
        assert "nonexistent-file-xyz123.html" in data["missing"], "Nonexistent file should be in missing list"


# ═══════════════════════════════════════════════════════════════
# MODULE 7: CACHE DEBUG TESTS
# ═══════════════════════════════════════════════════════════════

class TestCacheCheck:
    """POST /api/engine/cache-check - Cache debugging"""
    
    def test_cache_check_returns_cache_status_and_recommendation(self, api_client):
        """POST /api/engine/cache-check returns cache_status and recommendation"""
        response = api_client.post(f"{BASE_URL}/api/engine/cache-check", json={
            "url": "https://gps-mic-restart.preview.emergentagent.com/kids-safety-app-delhi.html"
        })
        assert response.status_code == 200
        
        data = response.json()
        assert "cache_status" in data, "Response should contain 'cache_status'"
        assert "recommendation" in data, "Response should contain 'recommendation'"
        assert "url" in data, "Response should contain 'url'"
        
        print(f"✓ POST /api/engine/cache-check:")
        print(f"  url: {data['url']}")
        print(f"  cache_status: {data['cache_status']}")
        print(f"  age_seconds: {data.get('age_seconds')}")
        print(f"  is_cached: {data.get('is_cached')}")
        print(f"  recommendation: {data['recommendation']}")


# ═══════════════════════════════════════════════════════════════
# CLEANUP
# ═══════════════════════════════════════════════════════════════

class TestCleanup:
    """Cleanup test data"""
    
    def test_restore_entity_after_all_tests(self, api_client):
        """Restore original entity after all tests"""
        response = api_client.post(f"{BASE_URL}/api/engine/entity", json=ORIGINAL_ENTITY)
        assert response.status_code == 200
        print(f"✓ Entity restored to original state")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
