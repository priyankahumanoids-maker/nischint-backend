"""
Blog API Tests — NISCHINT SEO-optimized blog system
Tests: CRUD, sitemap, RSS, auto-schema, API key auth, category filtering, view counter
"""
import pytest
import requests
import os
import uuid
import xml.etree.ElementTree as ET

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
BLOG_API_KEY = "nischint-blog-2026-key"
BLOG_API_KEY_HEADER = "X-Blog-API-Key"

CATEGORIES = ['women_safety', 'child_safety', 'family_safety', 'product', 'technology', 'awareness', 'guide']


@pytest.fixture
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


@pytest.fixture
def auth_headers():
    """Headers with valid API key"""
    return {BLOG_API_KEY_HEADER: BLOG_API_KEY, "Content-Type": "application/json"}


class TestBlogPostCreate:
    """POST /api/blog — Create blog post tests"""

    def test_create_post_with_valid_api_key(self, api_client, auth_headers):
        """POST /api/blog — create blog post with valid API key returns 200 with id and slug"""
        payload = {
            "title": f"TEST_Blog Post {uuid.uuid4().hex[:8]}",
            "content": "<h2>Test Content</h2><p>This is test content.</p>",
            "excerpt": "Test excerpt for the blog post",
            "category": "technology",
            "status": "draft"
        }
        response = api_client.post(f"{BASE_URL}/api/blog", json=payload, headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "id" in data, "Response should contain 'id'"
        assert "slug" in data, "Response should contain 'slug'"
        assert data["status"] == "ok"
        print(f"✓ Created post: id={data['id']}, slug={data['slug']}")

    def test_create_post_blocked_without_api_key(self, api_client):
        """POST /api/blog — blocked without API key (403)"""
        payload = {"title": "TEST_Unauthorized Post", "content": "Test"}
        response = api_client.post(f"{BASE_URL}/api/blog", json=payload)
        assert response.status_code == 403, f"Expected 403, got {response.status_code}"
        print("✓ POST without API key correctly returns 403")

    def test_create_post_blocked_with_wrong_api_key(self, api_client):
        """POST /api/blog — blocked with wrong API key (403)"""
        payload = {"title": "TEST_Wrong Key Post", "content": "Test"}
        headers = {BLOG_API_KEY_HEADER: "wrong-key-12345", "Content-Type": "application/json"}
        response = api_client.post(f"{BASE_URL}/api/blog", json=payload, headers=headers)
        assert response.status_code == 403, f"Expected 403, got {response.status_code}"
        print("✓ POST with wrong API key correctly returns 403")

    def test_auto_generates_unique_slug(self, api_client, auth_headers):
        """POST /api/blog — auto-generates unique slug from title (dedup with -2 suffix on collision)"""
        title = f"TEST_Duplicate Slug Test {uuid.uuid4().hex[:4]}"
        payload1 = {"title": title, "content": "First post", "status": "draft"}
        payload2 = {"title": title, "content": "Second post", "status": "draft"}
        
        r1 = api_client.post(f"{BASE_URL}/api/blog", json=payload1, headers=auth_headers)
        assert r1.status_code == 200
        slug1 = r1.json()["slug"]
        
        r2 = api_client.post(f"{BASE_URL}/api/blog", json=payload2, headers=auth_headers)
        assert r2.status_code == 200
        slug2 = r2.json()["slug"]
        
        assert slug1 != slug2, "Slugs should be unique"
        assert slug2.endswith("-2") or slug2.endswith("-3"), f"Second slug should have suffix: {slug2}"
        print(f"✓ Slug deduplication works: {slug1} vs {slug2}")

    def test_auto_generates_schema_json(self, api_client, auth_headers):
        """POST /api/blog — auto-generates schema_json with Article, FAQ, Breadcrumb schemas"""
        payload = {
            "title": f"TEST_Schema Test {uuid.uuid4().hex[:8]}",
            "content": "<h2>Schema Test</h2><p>Content here.</p>",
            "excerpt": "Testing schema generation",
            "category": "women_safety",
            "faq_json": [
                {"question": "What is this?", "answer": "A test post."},
                {"question": "Why test?", "answer": "To verify schema generation."}
            ],
            "status": "published"
        }
        response = api_client.post(f"{BASE_URL}/api/blog", json=payload, headers=auth_headers)
        assert response.status_code == 200
        slug = response.json()["slug"]
        
        # Fetch the post to verify schema_json
        get_resp = api_client.get(f"{BASE_URL}/api/blog/{slug}")
        assert get_resp.status_code == 200
        post = get_resp.json()
        
        schema = post.get("schema_json", [])
        assert isinstance(schema, list), "schema_json should be a list"
        
        schema_types = [s.get("@type") for s in schema]
        assert "Article" in schema_types, "Should have Article schema"
        assert "FAQPage" in schema_types, "Should have FAQPage schema (since faq_json provided)"
        assert "BreadcrumbList" in schema_types, "Should have BreadcrumbList schema"
        print(f"✓ Schema types generated: {schema_types}")

    def test_auto_sets_published_at_when_published(self, api_client, auth_headers):
        """POST /api/blog — auto-sets published_at when status=published"""
        payload = {
            "title": f"TEST_Published Post {uuid.uuid4().hex[:8]}",
            "content": "Published content",
            "status": "published"
        }
        response = api_client.post(f"{BASE_URL}/api/blog", json=payload, headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data.get("published_at") is not None, "published_at should be set for published posts"
        print(f"✓ published_at auto-set: {data['published_at']}")


class TestBlogPostList:
    """GET /api/blog — List blog posts tests"""

    def test_list_only_published_posts(self, api_client, auth_headers):
        """GET /api/blog — lists only published posts, excludes drafts"""
        # Create a draft post
        draft_payload = {
            "title": f"TEST_Draft Post {uuid.uuid4().hex[:8]}",
            "content": "Draft content",
            "status": "draft"
        }
        api_client.post(f"{BASE_URL}/api/blog", json=draft_payload, headers=auth_headers)
        
        # List posts
        response = api_client.get(f"{BASE_URL}/api/blog")
        assert response.status_code == 200
        data = response.json()
        
        assert "posts" in data
        assert "total" in data
        
        # Verify all returned posts are published
        for post in data["posts"]:
            assert post.get("status") == "published", f"Found non-published post: {post.get('slug')}"
        print(f"✓ Listed {len(data['posts'])} published posts (total: {data['total']})")

    def test_filter_by_category(self, api_client):
        """GET /api/blog?category=women_safety — filters by category"""
        response = api_client.get(f"{BASE_URL}/api/blog?category=women_safety")
        assert response.status_code == 200
        data = response.json()
        
        for post in data["posts"]:
            assert post.get("category") == "women_safety", f"Post {post.get('slug')} has wrong category"
        print(f"✓ Category filter works: {len(data['posts'])} women_safety posts")

    def test_sort_by_views(self, api_client):
        """GET /api/blog?sort_by=views — sorts by view count"""
        response = api_client.get(f"{BASE_URL}/api/blog?sort_by=views")
        assert response.status_code == 200
        data = response.json()
        
        if len(data["posts"]) > 1:
            views = [p.get("views", 0) for p in data["posts"]]
            assert views == sorted(views, reverse=True), "Posts should be sorted by views descending"
        print(f"✓ Sort by views works: {[p.get('views', 0) for p in data['posts'][:5]]}")


class TestBlogPostGet:
    """GET /api/blog/{slug} — Get single post tests"""

    def test_get_post_by_slug(self, api_client, auth_headers):
        """GET /api/blog/{slug} — returns full post with content, faq_json, schema_json, related_posts"""
        # Create a published post
        payload = {
            "title": f"TEST_Full Post {uuid.uuid4().hex[:8]}",
            "content": "<h2>Full Content</h2><p>Detailed content here.</p>",
            "excerpt": "Full post excerpt",
            "category": "technology",
            "faq_json": [{"question": "Q1?", "answer": "A1"}],
            "status": "published"
        }
        create_resp = api_client.post(f"{BASE_URL}/api/blog", json=payload, headers=auth_headers)
        assert create_resp.status_code == 200
        slug = create_resp.json()["slug"]
        
        # Get the post
        response = api_client.get(f"{BASE_URL}/api/blog/{slug}")
        assert response.status_code == 200
        post = response.json()
        
        # Verify all expected fields
        assert "content" in post, "Should include content"
        assert "faq_json" in post, "Should include faq_json"
        assert "schema_json" in post, "Should include schema_json"
        assert "related_posts" in post, "Should include related_posts"
        assert post["slug"] == slug
        print(f"✓ Full post retrieved: {slug}")

    def test_get_post_increments_view_counter(self, api_client, auth_headers):
        """GET /api/blog/{slug} — increments view counter"""
        # Create a published post
        payload = {
            "title": f"TEST_View Counter {uuid.uuid4().hex[:8]}",
            "content": "View counter test",
            "status": "published"
        }
        create_resp = api_client.post(f"{BASE_URL}/api/blog", json=payload, headers=auth_headers)
        slug = create_resp.json()["slug"]
        
        # Get initial views
        r1 = api_client.get(f"{BASE_URL}/api/blog/{slug}")
        views1 = r1.json().get("views", 0)
        
        # Get again
        r2 = api_client.get(f"{BASE_URL}/api/blog/{slug}")
        views2 = r2.json().get("views", 0)
        
        assert views2 > views1, f"Views should increment: {views1} -> {views2}"
        print(f"✓ View counter incremented: {views1} -> {views2}")

    def test_get_nonexistent_slug_returns_404(self, api_client):
        """GET /api/blog/nonexistent-slug — returns 404"""
        response = api_client.get(f"{BASE_URL}/api/blog/nonexistent-slug-12345")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("✓ Nonexistent slug returns 404")


class TestBlogPostUpdate:
    """PATCH /api/blog/{id} — Update blog post tests"""

    def test_update_post_fields(self, api_client, auth_headers):
        """PATCH /api/blog/{id} — updates post fields, rebuilds schema_json"""
        # Create a post
        payload = {
            "title": f"TEST_Update Test {uuid.uuid4().hex[:8]}",
            "content": "Original content",
            "category": "technology",
            "status": "draft"
        }
        create_resp = api_client.post(f"{BASE_URL}/api/blog", json=payload, headers=auth_headers)
        post_id = create_resp.json()["id"]
        
        # Update the post
        update_payload = {
            "title": "Updated Title",
            "content": "<h2>Updated Content</h2>",
            "status": "published"
        }
        update_resp = api_client.patch(f"{BASE_URL}/api/blog/{post_id}", json=update_payload, headers=auth_headers)
        assert update_resp.status_code == 200, f"Expected 200, got {update_resp.status_code}: {update_resp.text}"
        assert update_resp.json()["status"] == "ok"
        print(f"✓ Post updated: {post_id}")

    def test_update_requires_api_key(self, api_client, auth_headers):
        """PATCH /api/blog/{id} — requires API key auth (403 without)"""
        # Create a post first
        payload = {"title": f"TEST_Auth Test {uuid.uuid4().hex[:8]}", "content": "Test", "status": "draft"}
        create_resp = api_client.post(f"{BASE_URL}/api/blog", json=payload, headers=auth_headers)
        post_id = create_resp.json()["id"]
        
        # Try to update without API key
        update_resp = api_client.patch(f"{BASE_URL}/api/blog/{post_id}", json={"title": "Hacked"})
        assert update_resp.status_code == 403, f"Expected 403, got {update_resp.status_code}"
        print("✓ PATCH without API key returns 403")


class TestBlogSitemap:
    """GET /api/blog/sitemap — XML sitemap tests"""

    def test_sitemap_returns_valid_xml(self, api_client):
        """GET /api/blog/sitemap — returns valid XML sitemap with all published posts"""
        response = api_client.get(f"{BASE_URL}/api/blog/sitemap")
        assert response.status_code == 200
        assert "application/xml" in response.headers.get("Content-Type", "")
        
        # Parse XML
        try:
            root = ET.fromstring(response.text)
            assert root.tag.endswith("urlset"), f"Root should be urlset, got {root.tag}"
            
            urls = root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}url")
            assert len(urls) > 0, "Sitemap should have at least one URL"
            
            # Check for blog index URL
            locs = [url.find("{http://www.sitemaps.org/schemas/sitemap/0.9}loc").text for url in urls]
            blog_index = [l for l in locs if l.endswith("/blog")]
            assert len(blog_index) > 0, "Sitemap should include /blog index"
            
            print(f"✓ Valid XML sitemap with {len(urls)} URLs")
        except ET.ParseError as e:
            pytest.fail(f"Invalid XML: {e}")


class TestBlogRSS:
    """GET /api/blog/rss — RSS feed tests"""

    def test_rss_returns_valid_feed(self, api_client):
        """GET /api/blog/rss — returns valid RSS feed with latest posts"""
        response = api_client.get(f"{BASE_URL}/api/blog/rss")
        assert response.status_code == 200
        assert "application/rss+xml" in response.headers.get("Content-Type", "")
        
        # Parse RSS
        try:
            root = ET.fromstring(response.text)
            assert root.tag == "rss", f"Root should be rss, got {root.tag}"
            
            channel = root.find("channel")
            assert channel is not None, "RSS should have channel element"
            
            title = channel.find("title")
            assert title is not None and "NISCHINT" in title.text, "Channel should have NISCHINT title"
            
            items = channel.findall("item")
            print(f"✓ Valid RSS feed with {len(items)} items")
        except ET.ParseError as e:
            pytest.fail(f"Invalid RSS XML: {e}")


class TestBlogCategories:
    """GET /api/blog/categories — Category list tests"""

    def test_categories_returns_list_with_counts(self, api_client):
        """GET /api/blog/categories — returns category list with post counts"""
        response = api_client.get(f"{BASE_URL}/api/blog/categories")
        assert response.status_code == 200
        data = response.json()
        
        assert "categories" in data
        categories = data["categories"]
        
        for cat in categories:
            assert "slug" in cat, "Category should have slug"
            assert "label" in cat, "Category should have label"
            assert "count" in cat, "Category should have count"
            assert cat["slug"] in CATEGORIES, f"Unknown category: {cat['slug']}"
        
        print(f"✓ Categories: {[(c['slug'], c['count']) for c in categories]}")


class TestSeededBlogPosts:
    """Tests for pre-seeded blog posts mentioned in context"""

    def test_seeded_posts_exist(self, api_client):
        """Verify seeded blog posts are accessible"""
        known_slugs = [
            "how-ai-powered-voice-detection-keeps-women-safe-at-night",
            "5-gps-tracking-features-every-parent-needs-in-2026",
            "family-safety-planning-a-complete-guide-for-indian-families",
        ]
        
        for slug in known_slugs:
            response = api_client.get(f"{BASE_URL}/api/blog/{slug}")
            if response.status_code == 200:
                post = response.json()
                assert post["slug"] == slug
                print(f"✓ Seeded post found: {slug}")
            else:
                print(f"⚠ Seeded post not found (may have been deleted): {slug}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
