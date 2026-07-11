"""
SEO Factory Pipeline Tests - POST /api/seo/full-deploy
Tests the automated SEO factory pipeline that generates GEO pages,
writes files, runs static HTML generation, validates build, and updates sitemap.
"""

import os
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestFullDeployDryRun:
    """Test dry_run mode - returns page count without writing files"""

    def test_dry_run_returns_page_count(self):
        """dry_run=true should return pages_generated without writing files"""
        response = requests.post(f"{BASE_URL}/api/seo/full-deploy", json={
            "dry_run": True,
            "limit": 10
        })
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "dry_run"
        assert "pages_generated" in data
        assert data["pages_generated"] <= 10
        assert "sample" in data
        assert "pipeline_log" in data
        assert "elapsed_seconds" in data
        print(f"PASS: dry_run returned {data['pages_generated']} pages")

    def test_dry_run_with_tier_1_only(self):
        """dry_run with tier_1 cities should return 7 cities worth of pages"""
        response = requests.post(f"{BASE_URL}/api/seo/full-deploy", json={
            "dry_run": True,
            "city_tiers": ["tier_1"],
            "limit": 100
        })
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "dry_run"
        # tier_1 = 7 cities, default 4 categories, 2 variants = 56 pages max
        assert data["pages_generated"] <= 56
        print(f"PASS: tier_1 dry_run returned {data['pages_generated']} pages")

    def test_dry_run_with_categories_filter(self):
        """dry_run with specific categories should filter correctly"""
        response = requests.post(f"{BASE_URL}/api/seo/full-deploy", json={
            "dry_run": True,
            "categories": ["women_safety"],
            "city_tiers": ["tier_1"],
            "limit": 100
        })
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "dry_run"
        # tier_1 = 7 cities, 1 category, 2 variants = 14 pages max
        assert data["pages_generated"] <= 14
        print(f"PASS: categories filter dry_run returned {data['pages_generated']} pages")

    def test_dry_run_respects_limit(self):
        """dry_run should respect limit parameter"""
        response = requests.post(f"{BASE_URL}/api/seo/full-deploy", json={
            "dry_run": True,
            "limit": 5
        })
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "dry_run"
        assert data["pages_generated"] <= 5
        print(f"PASS: limit=5 dry_run returned {data['pages_generated']} pages")


class TestFullDeployResponseStructure:
    """Test response structure of full-deploy endpoint"""

    def test_dry_run_response_structure(self):
        """Verify dry_run response has all expected fields"""
        response = requests.post(f"{BASE_URL}/api/seo/full-deploy", json={
            "dry_run": True,
            "limit": 5
        })
        assert response.status_code == 200
        data = response.json()
        
        # Required fields for dry_run
        assert "status" in data
        assert "pages_generated" in data
        assert "sample" in data
        assert "pipeline_log" in data
        assert "elapsed_seconds" in data
        
        # Verify sample is a list of slugs
        assert isinstance(data["sample"], list)
        
        # Verify pipeline_log has step entries
        assert isinstance(data["pipeline_log"], list)
        assert len(data["pipeline_log"]) > 0
        
        # Verify elapsed_seconds is a number
        assert isinstance(data["elapsed_seconds"], (int, float))
        print("PASS: dry_run response structure is correct")

    def test_pipeline_log_contains_steps(self):
        """Verify pipeline_log contains step-by-step execution trace"""
        response = requests.post(f"{BASE_URL}/api/seo/full-deploy", json={
            "dry_run": True,
            "limit": 5
        })
        assert response.status_code == 200
        data = response.json()
        
        pipeline_log = data["pipeline_log"]
        assert len(pipeline_log) >= 1
        
        # Each log entry should have step, message, time
        for entry in pipeline_log:
            assert "step" in entry
            assert "message" in entry
            assert "time" in entry
        
        print(f"PASS: pipeline_log has {len(pipeline_log)} step entries")


class TestFullDeployFilters:
    """Test filter parameters: city_tiers, categories, variants, limit"""

    def test_city_tiers_tier_1_only(self):
        """tier_1 filter should only include 7 cities"""
        response = requests.post(f"{BASE_URL}/api/seo/full-deploy", json={
            "dry_run": True,
            "city_tiers": ["tier_1"],
            "categories": ["women_safety"],
            "variants": ["default"],
            "limit": 100
        })
        assert response.status_code == 200
        data = response.json()
        
        # tier_1 = 7 cities, 1 category, 1 variant = 7 pages
        assert data["pages_generated"] == 7
        
        # Verify sample slugs contain tier_1 cities
        tier_1_cities = ["mumbai", "delhi", "bangalore", "chennai", "hyderabad", "kolkata", "pune"]
        for slug in data["sample"]:
            city_found = any(city in slug.lower() for city in tier_1_cities)
            assert city_found, f"Slug {slug} doesn't contain tier_1 city"
        
        print("PASS: tier_1 filter correctly limits to 7 cities")

    def test_city_tiers_tier_2_only(self):
        """tier_2 filter should only include 17 cities"""
        response = requests.post(f"{BASE_URL}/api/seo/full-deploy", json={
            "dry_run": True,
            "city_tiers": ["tier_2"],
            "categories": ["women_safety"],
            "variants": ["default"],
            "limit": 100
        })
        assert response.status_code == 200
        data = response.json()
        
        # tier_2 = 17 cities, 1 category, 1 variant = 17 pages
        assert data["pages_generated"] == 17
        print("PASS: tier_2 filter correctly limits to 17 cities")

    def test_multiple_categories(self):
        """Multiple categories should generate pages for each"""
        response = requests.post(f"{BASE_URL}/api/seo/full-deploy", json={
            "dry_run": True,
            "city_tiers": ["tier_1"],
            "categories": ["women_safety", "kids_safety"],
            "variants": ["default"],
            "limit": 100
        })
        assert response.status_code == 200
        data = response.json()
        
        # tier_1 = 7 cities, 2 categories, 1 variant = 14 pages
        assert data["pages_generated"] == 14
        print("PASS: multiple categories filter works correctly")

    def test_multiple_variants(self):
        """Multiple variants should generate pages for each"""
        response = requests.post(f"{BASE_URL}/api/seo/full-deploy", json={
            "dry_run": True,
            "city_tiers": ["tier_1"],
            "categories": ["women_safety"],
            "variants": ["default", "best"],
            "limit": 100
        })
        assert response.status_code == 200
        data = response.json()
        
        # tier_1 = 7 cities, 1 category, 2 variants = 14 pages
        assert data["pages_generated"] == 14
        print("PASS: multiple variants filter works correctly")

    def test_limit_caps_generation(self):
        """Limit should cap the number of pages generated"""
        response = requests.post(f"{BASE_URL}/api/seo/full-deploy", json={
            "dry_run": True,
            "limit": 3
        })
        assert response.status_code == 200
        data = response.json()
        
        assert data["pages_generated"] == 3
        print("PASS: limit parameter correctly caps generation")


class TestExistingBuildFiles:
    """Test that existing build files are valid (without running full-deploy)"""

    def test_geopages_js_has_192_entries(self):
        """geoPages.js should have 192 entries (24 cities × 4 categories × 2 variants)"""
        # Read geoPages.js and count entries
        geopages_path = "/app/frontend/src/data/geoPages.js"
        with open(geopages_path, "r") as f:
            content = f.read()
        
        # Count slug entries
        slug_count = content.count('slug:')
        assert slug_count == 192, f"Expected 192 entries, found {slug_count}"
        print(f"PASS: geoPages.js has {slug_count} entries")

    def test_build_html_files_exist(self):
        """Build directory should have HTML files for GEO pages"""
        build_dir = "/app/frontend/build"
        
        # Check a sample of expected files
        sample_slugs = [
            "women-safety-app-mumbai",
            "best-women-safety-app-delhi",
            "kids-safety-app-bangalore",
            "family-safety-app-chennai"
        ]
        
        for slug in sample_slugs:
            flat_path = os.path.join(build_dir, f"{slug}.html")
            folder_path = os.path.join(build_dir, slug, "index.html")
            
            exists = os.path.isfile(flat_path) or os.path.isfile(folder_path)
            assert exists, f"HTML file for {slug} not found"
        
        print(f"PASS: Sample HTML files exist in build directory")

    def test_html_files_have_city_specific_titles(self):
        """HTML files should contain city-specific titles, not generic SPA title"""
        build_dir = "/app/frontend/build"
        
        # Check a sample file
        sample_path = os.path.join(build_dir, "women-safety-app-mumbai.html")
        if os.path.isfile(sample_path):
            with open(sample_path, "r") as f:
                content = f.read()
            
            # Should contain Mumbai in title
            assert "Mumbai" in content, "HTML should contain city name Mumbai"
            assert "<title>" in content, "HTML should have title tag"
            
            # Extract title
            import re
            title_match = re.search(r'<title>([^<]+)</title>', content)
            if title_match:
                title = title_match.group(1)
                assert "Mumbai" in title, f"Title should contain Mumbai, got: {title}"
                print(f"PASS: HTML has city-specific title: {title}")
        else:
            pytest.skip("Sample HTML file not found")


class TestPreviousSEOEndpoints:
    """Verify previous SEO endpoints still work"""

    def test_cluster_endpoint(self):
        """POST /api/seo/cluster should still work"""
        response = requests.post(f"{BASE_URL}/api/seo/cluster", json={
            "keywords": ["women safety app mumbai", "kids tracker delhi"]
        })
        assert response.status_code == 200
        data = response.json()
        assert "clusters" in data
        print("PASS: /api/seo/cluster endpoint works")

    def test_generate_page_endpoint(self):
        """POST /api/seo/generate-page should still work"""
        response = requests.post(f"{BASE_URL}/api/seo/generate-page", json={
            "city": "Mumbai",
            "category": "women_safety",
            "variant": "default"
        })
        assert response.status_code == 200
        data = response.json()
        assert "slug" in data
        assert "title" in data
        assert "Mumbai" in data["title"]
        print("PASS: /api/seo/generate-page endpoint works")

    def test_config_endpoint(self):
        """GET /api/seo/config should still work"""
        response = requests.get(f"{BASE_URL}/api/seo/config")
        assert response.status_code == 200
        data = response.json()
        assert "cities" in data
        assert "categories" in data
        assert "variants" in data
        assert len(data["cities"]["tier_1"]) == 7
        print("PASS: /api/seo/config endpoint works")

    def test_stats_endpoint(self):
        """GET /api/seo/stats should still work"""
        response = requests.get(f"{BASE_URL}/api/seo/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_pages" in data
        assert "available_cities" in data
        assert data["available_cities"] == 59
        print("PASS: /api/seo/stats endpoint works")


class TestFullDeploySmallRun:
    """Test actual full-deploy with very small limit (safe test)"""

    def test_full_deploy_small_limit(self):
        """
        Run full-deploy with limit=2 to verify it works without rewriting all files.
        This is a safe test that only generates 2 pages.
        """
        response = requests.post(f"{BASE_URL}/api/seo/full-deploy", json={
            "city_tiers": ["tier_1"],
            "categories": ["women_safety"],
            "variants": ["default"],
            "limit": 2,
            "dry_run": False
        })
        assert response.status_code == 200
        data = response.json()
        
        # Should succeed or be partial (if some files already exist)
        assert data["status"] in ["success", "partial"]
        
        # Verify response structure for non-dry-run
        assert "pages_generated" in data
        assert "build_status" in data
        assert "validation" in data
        assert "pipeline_log" in data
        assert "elapsed_seconds" in data
        
        # Verify validation structure
        validation = data["validation"]
        assert "total_expected" in validation
        assert "found" in validation
        assert "pass" in validation
        
        print(f"PASS: full-deploy with limit=2 returned status={data['status']}")
        print(f"  pages_generated: {data['pages_generated']}")
        print(f"  build_status: {data['build_status']}")
        print(f"  validation: found={validation['found']}/{validation['total_expected']}, pass={validation['pass']}")
        print(f"  elapsed_seconds: {data['elapsed_seconds']}")

    def test_full_deploy_response_has_sitemap_updated(self):
        """Verify full-deploy response includes sitemap_updated field"""
        response = requests.post(f"{BASE_URL}/api/seo/full-deploy", json={
            "city_tiers": ["tier_1"],
            "categories": ["kids_safety"],
            "variants": ["default"],
            "limit": 1,
            "dry_run": False
        })
        assert response.status_code == 200
        data = response.json()
        
        if data["status"] == "success":
            assert "sitemap_updated" in data
            print(f"PASS: sitemap_updated = {data['sitemap_updated']}")
        else:
            print(f"INFO: status={data['status']}, sitemap_updated may not be present")


class TestFullDeployValidation:
    """Test validation logic of full-deploy"""

    def test_validation_found_matches_expected(self):
        """Validation should show found count matching total_expected when pass=true"""
        response = requests.post(f"{BASE_URL}/api/seo/full-deploy", json={
            "city_tiers": ["tier_1"],
            "categories": ["family_safety"],
            "variants": ["default"],
            "limit": 1,
            "dry_run": False
        })
        assert response.status_code == 200
        data = response.json()
        
        if data["status"] == "success":
            validation = data["validation"]
            assert validation["pass"] == True
            assert validation["found"] == validation["total_expected"]
            print(f"PASS: validation found={validation['found']} matches total_expected={validation['total_expected']}")
        else:
            print(f"INFO: status={data['status']}, validation may show partial results")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
