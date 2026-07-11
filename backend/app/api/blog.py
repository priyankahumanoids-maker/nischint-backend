"""
NISCHINT Blog System — SEO-optimized blog API.
Handles CRUD, sitemap, RSS, auto-schema generation.
"""
import logging
import os
import re
import uuid
import json as json_lib
import math
from datetime import datetime, timezone
from xml.sax.saxutils import escape as xml_escape

from fastapi import APIRouter, Request, Depends, HTTPException, Header
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db_session
from app.core.rate_limiter import limiter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/blog", tags=["Blog"])

BLOG_API_KEY = None  # Loaded lazily
BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://nischint.care")

CATEGORIES = ['women_safety', 'child_safety', 'family_safety', 'product', 'technology', 'awareness', 'guide']
STATUSES = ['draft', 'published', 'archived']

SCHEMA_SQL = [
    """CREATE TABLE IF NOT EXISTS blog_posts (
        id UUID PRIMARY KEY,
        title TEXT NOT NULL,
        slug TEXT UNIQUE NOT NULL,
        content TEXT,
        excerpt TEXT,
        meta_title TEXT,
        meta_description TEXT,
        keywords TEXT,
        category TEXT CHECK (category IN ('women_safety','child_safety','family_safety','product','technology','awareness','guide')),
        author TEXT DEFAULT 'NISCHINT Team',
        featured_image_url TEXT,
        faq_json JSONB DEFAULT '[]',
        schema_json JSONB DEFAULT '{}',
        status TEXT DEFAULT 'draft' CHECK (status IN ('draft','published','archived')),
        views INT DEFAULT 0,
        published_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );""",
]

INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_blog_slug ON blog_posts(slug);",
    "CREATE INDEX IF NOT EXISTS idx_blog_status ON blog_posts(status);",
    "CREATE INDEX IF NOT EXISTS idx_blog_category ON blog_posts(category);",
    "CREATE INDEX IF NOT EXISTS idx_blog_published ON blog_posts(published_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_blog_views ON blog_posts(views DESC);",
]

_tables_ready = False


async def ensure_tables(session: AsyncSession):
    global _tables_ready
    if _tables_ready:
        return
    for sql in SCHEMA_SQL:
        await session.execute(text(sql))
    for idx in INDEXES_SQL:
        await session.execute(text(idx))
    await session.commit()
    _tables_ready = True


# ── Helpers ──

def slugify(title: str) -> str:
    s = title.lower().strip()
    s = re.sub(r'[^\w\s-]', '', s)
    s = re.sub(r'[\s_]+', '-', s)
    s = re.sub(r'-+', '-', s).strip('-')
    return s[:120]


def estimate_read_time(html_content: str) -> int:
    text_only = re.sub(r'<[^>]+>', '', html_content or '')
    words = len(text_only.split())
    return max(1, math.ceil(words / 200))


def build_schema(post: dict) -> dict:
    schemas = []

    # Article schema
    article = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": post.get("meta_title") or post.get("title", ""),
        "description": post.get("meta_description") or post.get("excerpt", ""),
        "author": {"@type": "Organization", "name": post.get("author", "NISCHINT Team")},
        "publisher": {
            "@type": "Organization",
            "name": "NISCHINT",
            "url": BASE_URL,
            "logo": {"@type": "ImageObject", "url": f"{BASE_URL}/logo192.png"},
        },
        "datePublished": post.get("published_at", ""),
        "dateModified": post.get("updated_at", ""),
        "mainEntityOfPage": {"@type": "WebPage", "@id": f"{BASE_URL}/blog/{post.get('slug', '')}"},
        "keywords": post.get("keywords", ""),
    }
    if post.get("featured_image_url"):
        article["image"] = post["featured_image_url"]
    schemas.append(article)

    # FAQ schema
    faq_items = post.get("faq_json") or []
    if isinstance(faq_items, str):
        try:
            faq_items = json_lib.loads(faq_items)
        except (json_lib.JSONDecodeError, TypeError):
            faq_items = []
    if faq_items:
        faq_schema = {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": item.get("question", ""),
                    "acceptedAnswer": {"@type": "Answer", "text": item.get("answer", "")},
                }
                for item in faq_items
            ],
        }
        schemas.append(faq_schema)

    # Breadcrumb
    breadcrumb = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": BASE_URL},
            {"@type": "ListItem", "position": 2, "name": "Blog", "item": f"{BASE_URL}/blog"},
        ],
    }
    if post.get("category"):
        cat_label = post["category"].replace("_", " ").title()
        breadcrumb["itemListElement"].append(
            {"@type": "ListItem", "position": 3, "name": cat_label, "item": f"{BASE_URL}/blog/category/{post['category']}"}
        )
        breadcrumb["itemListElement"].append(
            {"@type": "ListItem", "position": 4, "name": post.get("title", ""), "item": f"{BASE_URL}/blog/{post.get('slug', '')}"}
        )
    else:
        breadcrumb["itemListElement"].append(
            {"@type": "ListItem", "position": 3, "name": post.get("title", ""), "item": f"{BASE_URL}/blog/{post.get('slug', '')}"}
        )
    schemas.append(breadcrumb)

    return schemas


def post_row_to_dict(r, include_content=False) -> dict:
    d = {
        "id": str(r.id),
        "title": r.title,
        "slug": r.slug,
        "excerpt": r.excerpt,
        "meta_title": r.meta_title,
        "meta_description": r.meta_description,
        "keywords": r.keywords,
        "category": r.category,
        "author": r.author,
        "featured_image_url": r.featured_image_url,
        "status": r.status,
        "views": r.views or 0,
        "read_time": estimate_read_time(r.content) if r.content else 1,
        "published_at": r.published_at.isoformat() if r.published_at else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }
    if include_content:
        d["content"] = r.content
        d["faq_json"] = r.faq_json if isinstance(r.faq_json, list) else (json_lib.loads(r.faq_json) if isinstance(r.faq_json, str) else [])
        d["schema_json"] = r.schema_json if isinstance(r.schema_json, (list, dict)) else (json_lib.loads(r.schema_json) if isinstance(r.schema_json, str) else {})
    return d


def require_api_key(x_blog_api_key: Optional[str] = Header(None), api_key: Optional[str] = None):
    """API key auth via header (X-Blog-API-Key) or query param (?api_key=...).
    Skipped entirely if BLOG_API_KEY is not set in .env."""
    from app.core.config import settings
    key = settings.blog_api_key
    if not key:
        return
    provided = x_blog_api_key or api_key
    if provided != key:
        raise HTTPException(status_code=403, detail="Invalid or missing X-Blog-API-Key header")


# ── Models ──

class BlogPostCreate(BaseModel):
    title: str
    content: Optional[str] = None
    excerpt: Optional[str] = None
    meta_title: Optional[str] = None
    meta_description: Optional[str] = None
    keywords: Optional[str] = None
    category: Optional[str] = None
    author: Optional[str] = "NISCHINT Team"
    featured_image_url: Optional[str] = None
    faq_json: Optional[list] = None
    status: Optional[str] = "draft"


class BlogPostUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    excerpt: Optional[str] = None
    meta_title: Optional[str] = None
    meta_description: Optional[str] = None
    keywords: Optional[str] = None
    category: Optional[str] = None
    author: Optional[str] = None
    featured_image_url: Optional[str] = None
    faq_json: Optional[list] = None
    status: Optional[str] = None


# ── Endpoints ──

@router.post("")
@limiter.limit("30/minute")
async def create_blog_post(
    request: Request,
    req: BlogPostCreate,
    session: AsyncSession = Depends(get_db_session),
    _auth=Depends(require_api_key),
):
    """Create a new blog post. Used by n8n auto-publishing."""
    await ensure_tables(session)

    if req.category and req.category not in CATEGORIES:
        raise HTTPException(status_code=422, detail=f"category must be one of: {CATEGORIES}")
    if req.status and req.status not in STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of: {STATUSES}")

    # Generate unique slug
    base_slug = slugify(req.title)
    slug = base_slug
    counter = 1
    while True:
        dup = await session.execute(text("SELECT id FROM blog_posts WHERE slug = :s LIMIT 1"), {"s": slug})
        if not dup.fetchone():
            break
        counter += 1
        slug = f"{base_slug}-{counter}"

    post_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    published_at = now if req.status == "published" else None

    post_data = {
        "title": req.title,
        "slug": slug,
        "content": req.content,
        "excerpt": (req.excerpt or "")[:300],
        "meta_title": (req.meta_title or req.title)[:60],
        "meta_description": (req.meta_description or req.excerpt or "")[:160],
        "keywords": req.keywords,
        "category": req.category,
        "author": req.author or "NISCHINT Team",
        "featured_image_url": req.featured_image_url,
        "faq_json": req.faq_json or [],
        "status": req.status or "draft",
        "published_at": published_at,
    }

    schema_json = build_schema({**post_data, "id": post_id, "published_at": published_at.isoformat() if published_at else "", "updated_at": now.isoformat()})

    await session.execute(text("""
        INSERT INTO blog_posts (
            id, title, slug, content, excerpt,
            meta_title, meta_description, keywords, category,
            author, featured_image_url, faq_json, schema_json,
            status, views, published_at, created_at, updated_at
        ) VALUES (
            :id, :title, :slug, :content, :excerpt,
            :meta_title, :meta_description, :keywords, :category,
            :author, :featured_image_url, CAST(:faq AS jsonb), CAST(:schema AS jsonb),
            :status, 0, :published_at, :now, :now
        )
    """), {
        "id": post_id, "title": req.title, "slug": slug,
        "content": req.content, "excerpt": post_data["excerpt"],
        "meta_title": post_data["meta_title"],
        "meta_description": post_data["meta_description"],
        "keywords": req.keywords, "category": req.category,
        "author": post_data["author"],
        "featured_image_url": req.featured_image_url,
        "faq": json_lib.dumps(req.faq_json or []),
        "schema": json_lib.dumps(schema_json),
        "status": post_data["status"],
        "published_at": published_at,
        "now": now,
    })

    logger.info(f"[BLOG] Created post: slug={slug} status={post_data['status']}")

    return {
        "status": "ok",
        "id": post_id,
        "slug": slug,
        "url": f"{BASE_URL}/blog/{slug}",
        "published_at": published_at.isoformat() if published_at else None,
    }


@router.get("")
async def list_blog_posts(
    category: Optional[str] = None,
    limit: int = 12,
    offset: int = 0,
    sort_by: str = "published_at",
    session: AsyncSession = Depends(get_db_session),
):
    """List published blog posts. Supports category filter and pagination."""
    await ensure_tables(session)

    where_parts = ["status = 'published'"]
    params = {"lim": min(limit, 50), "off": offset}
    if category and category in CATEGORIES:
        where_parts.append("category = :cat")
        params["cat"] = category

    where = " AND ".join(where_parts)
    order = "views DESC" if sort_by == "views" else "published_at DESC"

    count_row = await session.execute(text(f"SELECT COUNT(*) as cnt FROM blog_posts WHERE {where}"), params)
    total = count_row.fetchone().cnt

    rows = await session.execute(text(f"""
        SELECT id, title, slug, excerpt, meta_title, meta_description, keywords,
               category, author, featured_image_url, status, views, content,
               faq_json, schema_json, published_at, created_at, updated_at
        FROM blog_posts WHERE {where}
        ORDER BY {order}
        LIMIT :lim OFFSET :off
    """), params)

    posts = [post_row_to_dict(r) for r in rows.fetchall()]

    return Response(
        content=json_lib.dumps({"posts": posts, "total": total, "limit": limit, "offset": offset}),
        media_type="application/json",
        headers={"Cache-Control": "public, max-age=60, s-maxage=120"},
    )


@router.get("/sitemap")
async def blog_sitemap(session: AsyncSession = Depends(get_db_session)):
    """Complete XML sitemap: static pages + all published blog posts."""
    await ensure_tables(session)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Static pages
    static_pages = [
        {"loc": f"{BASE_URL}/", "changefreq": "weekly", "priority": "1.0"},
        {"loc": f"{BASE_URL}/women-safety-app", "changefreq": "weekly", "priority": "0.95"},
        {"loc": f"{BASE_URL}/kids-safety-app", "changefreq": "weekly", "priority": "0.95"},
        {"loc": f"{BASE_URL}/family-safety-app", "changefreq": "weekly", "priority": "0.95"},
        {"loc": f"{BASE_URL}/pilot", "changefreq": "monthly", "priority": "0.9"},
        {"loc": f"{BASE_URL}/investors", "changefreq": "monthly", "priority": "0.8"},
        {"loc": f"{BASE_URL}/blog", "changefreq": "daily", "priority": "0.85"},
    ]

    urls = []
    for p in static_pages:
        urls.append(f"""  <url>
    <loc>{p["loc"]}</loc>
    <lastmod>{today}</lastmod>
    <changefreq>{p["changefreq"]}</changefreq>
    <priority>{p["priority"]}</priority>
  </url>""")

    # Dynamic blog posts
    rows = await session.execute(text("""
        SELECT slug, updated_at, created_at FROM blog_posts
        WHERE status = 'published' ORDER BY published_at DESC
    """))

    blog_count = 0
    for r in rows.fetchall():
        blog_count += 1
        lastmod = (r.updated_at or r.created_at or datetime.now(timezone.utc)).strftime('%Y-%m-%d')
        urls.append(f"""  <url>
    <loc>{BASE_URL}/blog/{xml_escape(r.slug)}</loc>
    <lastmod>{lastmod}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>""")

    logger.info(f"Sitemap blogs count: {blog_count}, total URLs: {len(urls)}")

    # GEO city pages
    geo_pages = [
        "women-safety-app-mumbai",
        "best-women-safety-app-mumbai",
        "kids-safety-app-mumbai",
        "best-kids-safety-app-mumbai",
        "family-safety-app-mumbai",
        "best-family-safety-app-mumbai",
        "personal-safety-app-mumbai",
        "best-personal-safety-app-mumbai",
        "women-safety-app-delhi",
        "best-women-safety-app-delhi",
        "kids-safety-app-delhi",
        "best-kids-safety-app-delhi",
        "family-safety-app-delhi",
        "best-family-safety-app-delhi",
        "personal-safety-app-delhi",
        "best-personal-safety-app-delhi",
        "women-safety-app-bangalore",
        "best-women-safety-app-bangalore",
        "kids-safety-app-bangalore",
        "best-kids-safety-app-bangalore",
        "family-safety-app-bangalore",
        "best-family-safety-app-bangalore",
        "personal-safety-app-bangalore",
        "best-personal-safety-app-bangalore",
        "women-safety-app-chennai",
        "best-women-safety-app-chennai",
        "kids-safety-app-chennai",
        "best-kids-safety-app-chennai",
        "family-safety-app-chennai",
        "best-family-safety-app-chennai",
        "personal-safety-app-chennai",
        "best-personal-safety-app-chennai",
        "women-safety-app-hyderabad",
        "best-women-safety-app-hyderabad",
        "kids-safety-app-hyderabad",
        "best-kids-safety-app-hyderabad",
        "family-safety-app-hyderabad",
        "best-family-safety-app-hyderabad",
        "personal-safety-app-hyderabad",
        "best-personal-safety-app-hyderabad",
        "women-safety-app-kolkata",
        "best-women-safety-app-kolkata",
        "kids-safety-app-kolkata",
        "best-kids-safety-app-kolkata",
        "family-safety-app-kolkata",
        "best-family-safety-app-kolkata",
        "personal-safety-app-kolkata",
        "best-personal-safety-app-kolkata",
        "women-safety-app-pune",
        "best-women-safety-app-pune",
        "kids-safety-app-pune",
        "best-kids-safety-app-pune",
        "family-safety-app-pune",
        "best-family-safety-app-pune",
        "personal-safety-app-pune",
        "best-personal-safety-app-pune",
        "women-safety-app-ahmedabad",
        "best-women-safety-app-ahmedabad",
        "kids-safety-app-ahmedabad",
        "best-kids-safety-app-ahmedabad",
        "family-safety-app-ahmedabad",
        "best-family-safety-app-ahmedabad",
        "personal-safety-app-ahmedabad",
        "best-personal-safety-app-ahmedabad",
        "women-safety-app-jaipur",
        "best-women-safety-app-jaipur",
        "kids-safety-app-jaipur",
        "best-kids-safety-app-jaipur",
        "family-safety-app-jaipur",
        "best-family-safety-app-jaipur",
        "personal-safety-app-jaipur",
        "best-personal-safety-app-jaipur",
        "women-safety-app-lucknow",
        "best-women-safety-app-lucknow",
        "kids-safety-app-lucknow",
        "best-kids-safety-app-lucknow",
        "family-safety-app-lucknow",
        "best-family-safety-app-lucknow",
        "personal-safety-app-lucknow",
        "best-personal-safety-app-lucknow",
        "women-safety-app-chandigarh",
        "best-women-safety-app-chandigarh",
        "kids-safety-app-chandigarh",
        "best-kids-safety-app-chandigarh",
        "family-safety-app-chandigarh",
        "best-family-safety-app-chandigarh",
        "personal-safety-app-chandigarh",
        "best-personal-safety-app-chandigarh",
        "women-safety-app-indore",
        "best-women-safety-app-indore",
        "kids-safety-app-indore",
        "best-kids-safety-app-indore",
        "family-safety-app-indore",
        "best-family-safety-app-indore",
        "personal-safety-app-indore",
        "best-personal-safety-app-indore",
        "women-safety-app-nagpur",
        "best-women-safety-app-nagpur",
        "kids-safety-app-nagpur",
        "best-kids-safety-app-nagpur",
        "family-safety-app-nagpur",
        "best-family-safety-app-nagpur",
        "personal-safety-app-nagpur",
        "best-personal-safety-app-nagpur",
        "women-safety-app-surat",
        "best-women-safety-app-surat",
        "kids-safety-app-surat",
        "best-kids-safety-app-surat",
        "family-safety-app-surat",
        "best-family-safety-app-surat",
        "personal-safety-app-surat",
        "best-personal-safety-app-surat",
        "women-safety-app-coimbatore",
        "best-women-safety-app-coimbatore",
        "kids-safety-app-coimbatore",
        "best-kids-safety-app-coimbatore",
        "family-safety-app-coimbatore",
        "best-family-safety-app-coimbatore",
        "personal-safety-app-coimbatore",
        "best-personal-safety-app-coimbatore",
        "women-safety-app-kochi",
        "best-women-safety-app-kochi",
        "kids-safety-app-kochi",
        "best-kids-safety-app-kochi",
        "family-safety-app-kochi",
        "best-family-safety-app-kochi",
        "personal-safety-app-kochi",
        "best-personal-safety-app-kochi",
        "women-safety-app-thiruvananthapuram",
        "best-women-safety-app-thiruvananthapuram",
        "kids-safety-app-thiruvananthapuram",
        "best-kids-safety-app-thiruvananthapuram",
        "family-safety-app-thiruvananthapuram",
        "best-family-safety-app-thiruvananthapuram",
        "personal-safety-app-thiruvananthapuram",
        "best-personal-safety-app-thiruvananthapuram",
        "women-safety-app-visakhapatnam",
        "best-women-safety-app-visakhapatnam",
        "kids-safety-app-visakhapatnam",
        "best-kids-safety-app-visakhapatnam",
        "family-safety-app-visakhapatnam",
        "best-family-safety-app-visakhapatnam",
        "personal-safety-app-visakhapatnam",
        "best-personal-safety-app-visakhapatnam",
        "women-safety-app-bhopal",
        "best-women-safety-app-bhopal",
        "kids-safety-app-bhopal",
        "best-kids-safety-app-bhopal",
        "family-safety-app-bhopal",
        "best-family-safety-app-bhopal",
        "personal-safety-app-bhopal",
        "best-personal-safety-app-bhopal",
        "women-safety-app-patna",
        "best-women-safety-app-patna",
        "kids-safety-app-patna",
        "best-kids-safety-app-patna",
        "family-safety-app-patna",
        "best-family-safety-app-patna",
        "personal-safety-app-patna",
        "best-personal-safety-app-patna",
        "women-safety-app-guwahati",
        "best-women-safety-app-guwahati",
        "kids-safety-app-guwahati",
        "best-kids-safety-app-guwahati",
        "family-safety-app-guwahati",
        "best-family-safety-app-guwahati",
        "personal-safety-app-guwahati",
        "best-personal-safety-app-guwahati",
        "women-safety-app-dehradun",
        "best-women-safety-app-dehradun",
        "kids-safety-app-dehradun",
        "best-kids-safety-app-dehradun",
        "family-safety-app-dehradun",
        "best-family-safety-app-dehradun",
        "personal-safety-app-dehradun",
        "best-personal-safety-app-dehradun",
        "women-safety-app-ranchi",
        "best-women-safety-app-ranchi",
        "kids-safety-app-ranchi",
        "best-kids-safety-app-ranchi",
        "family-safety-app-ranchi",
        "best-family-safety-app-ranchi",
        "personal-safety-app-ranchi",
        "best-personal-safety-app-ranchi",
        "women-safety-app-bhubaneswar",
        "best-women-safety-app-bhubaneswar",
        "kids-safety-app-bhubaneswar",
        "best-kids-safety-app-bhubaneswar",
        "family-safety-app-bhubaneswar",
        "best-family-safety-app-bhubaneswar",
        "personal-safety-app-bhubaneswar",
        "best-personal-safety-app-bhubaneswar",
    ]
    for slug in geo_pages:
        urls.append(f"""  <url>
    <loc>{BASE_URL}/{slug}</loc>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>""")

    logger.info(f"Sitemap total: {len(urls)} URLs (static + {blog_count} blogs + {len(geo_pages)} geo)")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{chr(10).join(urls)}
</urlset>"""

    return Response(
        content=xml.encode("utf-8"),
        media_type="application/xml",
        headers={
            "Content-Type": "application/xml; charset=utf-8",
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "CDN-Cache-Control": "no-store",
            "Cloudflare-CDN-Cache-Control": "no-store",
            "X-Sitemap-Version": "geo-v1",
        },
    )


@router.get("/rss")
async def blog_rss(session: AsyncSession = Depends(get_db_session)):
    """RSS feed of latest published posts."""
    await ensure_tables(session)

    rows = await session.execute(text("""
        SELECT title, slug, excerpt, author, category, published_at
        FROM blog_posts WHERE status = 'published'
        ORDER BY published_at DESC LIMIT 20
    """))

    items = []
    for r in rows.fetchall():
        pub_date = r.published_at.strftime('%a, %d %b %Y %H:%M:%S +0000') if r.published_at else ''
        items.append(f"""    <item>
      <title>{xml_escape(r.title)}</title>
      <link>{BASE_URL}/blog/{xml_escape(r.slug)}</link>
      <description>{xml_escape(r.excerpt or '')}</description>
      <author>{xml_escape(r.author or 'NISCHINT Team')}</author>
      <category>{xml_escape((r.category or '').replace('_', ' ').title())}</category>
      <pubDate>{pub_date}</pubDate>
      <guid>{BASE_URL}/blog/{xml_escape(r.slug)}</guid>
    </item>""")

    rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>NISCHINT Blog — Safety Tips, Guides &amp; Updates</title>
    <link>{BASE_URL}/blog</link>
    <description>Expert safety guides, product updates, and awareness articles from NISCHINT — the AI-powered family safety platform.</description>
    <language>en-us</language>
    <atom:link href="{BASE_URL}/api/blog/rss" rel="self" type="application/rss+xml"/>
{chr(10).join(items)}
  </channel>
</rss>"""

    return Response(content=rss, media_type="application/rss+xml",
                    headers={"Cache-Control": "public, max-age=300, s-maxage=600"})


@router.get("/categories")
async def list_categories(session: AsyncSession = Depends(get_db_session)):
    """List categories with post counts."""
    await ensure_tables(session)
    rows = await session.execute(text("""
        SELECT category, COUNT(*) as cnt
        FROM blog_posts WHERE status = 'published' AND category IS NOT NULL
        GROUP BY category ORDER BY cnt DESC
    """))
    return {"categories": [{"slug": r.category, "label": r.category.replace("_", " ").title(), "count": r.cnt} for r in rows.fetchall()]}


@router.get("/{slug}")
async def get_blog_post(
    slug: str,
    session: AsyncSession = Depends(get_db_session),
):
    """Get a single blog post by slug. Increments view counter."""
    await ensure_tables(session)

    row = await session.execute(text("""
        SELECT id, title, slug, content, excerpt,
               meta_title, meta_description, keywords, category,
               author, featured_image_url, faq_json, schema_json,
               status, views, published_at, created_at, updated_at
        FROM blog_posts WHERE slug = :slug AND status = 'published'
    """), {"slug": slug})
    r = row.fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="Post not found")

    # Increment views (fire and forget)
    await session.execute(text("UPDATE blog_posts SET views = views + 1 WHERE slug = :slug"), {"slug": slug})

    post = post_row_to_dict(r, include_content=True)

    # Get related posts (same category, exclude current)
    related_rows = await session.execute(text("""
        SELECT id, title, slug, excerpt, meta_title, meta_description, keywords,
               category, author, featured_image_url, status, views, content,
               faq_json, schema_json, published_at, created_at, updated_at
        FROM blog_posts
        WHERE status = 'published' AND slug != :slug AND category = :cat
        ORDER BY published_at DESC LIMIT 3
    """), {"slug": slug, "cat": r.category})
    post["related_posts"] = [post_row_to_dict(rr) for rr in related_rows.fetchall()]

    return Response(
        content=json_lib.dumps(post),
        media_type="application/json",
        headers={"Cache-Control": "public, max-age=30, s-maxage=60"},
    )


@router.patch("/{post_id}")
async def update_blog_post(
    post_id: str,
    req: BlogPostUpdate,
    session: AsyncSession = Depends(get_db_session),
    _auth=Depends(require_api_key),
):
    """Update an existing blog post."""
    await ensure_tables(session)

    check = await session.execute(text("SELECT id, status, published_at FROM blog_posts WHERE id = :pid"), {"pid": post_id})
    existing = check.fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Post not found")

    sets = []
    params = {"pid": post_id, "now": datetime.now(timezone.utc)}

    field_map = {
        "title": "title", "content": "content", "excerpt": "excerpt",
        "meta_title": "meta_title", "meta_description": "meta_description",
        "keywords": "keywords", "category": "category", "author": "author",
        "featured_image_url": "featured_image_url", "status": "status",
    }
    for attr, col in field_map.items():
        val = getattr(req, attr, None)
        if val is not None:
            if attr == "category" and val not in CATEGORIES:
                raise HTTPException(status_code=422, detail=f"category must be one of: {CATEGORIES}")
            if attr == "status" and val not in STATUSES:
                raise HTTPException(status_code=422, detail=f"status must be one of: {STATUSES}")
            sets.append(f"{col} = :{attr}")
            params[attr] = val

    if req.faq_json is not None:
        sets.append("faq_json = CAST(:faq AS jsonb)")
        params["faq"] = json_lib.dumps(req.faq_json)

    # Auto-set published_at when status changes to published
    if req.status == "published" and not existing.published_at:
        sets.append("published_at = :now")

    sets.append("updated_at = :now")

    await session.execute(text(f"UPDATE blog_posts SET {', '.join(sets)} WHERE id = :pid"), params)

    # Rebuild schema
    updated = await session.execute(text("""
        SELECT id, title, slug, content, excerpt, meta_title, meta_description,
               keywords, category, author, featured_image_url, faq_json,
               status, published_at, updated_at
        FROM blog_posts WHERE id = :pid
    """), {"pid": post_id})
    u = updated.fetchone()
    if u:
        schema_data = {
            "title": u.title, "slug": u.slug, "excerpt": u.excerpt,
            "meta_title": u.meta_title, "meta_description": u.meta_description,
            "keywords": u.keywords, "category": u.category,
            "author": u.author, "featured_image_url": u.featured_image_url,
            "faq_json": u.faq_json,
            "published_at": u.published_at.isoformat() if u.published_at else "",
            "updated_at": u.updated_at.isoformat() if u.updated_at else "",
        }
        new_schema = build_schema(schema_data)
        await session.execute(text(
            "UPDATE blog_posts SET schema_json = CAST(:schema AS jsonb) WHERE id = :pid"
        ), {"schema": json_lib.dumps(new_schema), "pid": post_id})

    return {"status": "ok", "id": post_id}


# ── Blog Tracking ──

class BlogTracking(BaseModel):
    slug: str
    time_on_page: Optional[float] = None
    scroll_depth: Optional[float] = None
    cta_clicked: Optional[str] = None


@router.post("/track")
async def track_blog(data: BlogTracking, session: AsyncSession = Depends(get_db_session)):
    """Track blog engagement for analytics and AI feedback loop.

    Compensating action: conversion telemetry only — losing one
    tracking row is not a safety signal drop. Narrow except types
    to DB-class errors so unknown exceptions (e.g. coding bug)
    still surface in alerting. First failure self-heals via
    `CREATE TABLE IF NOT EXISTS` + retry insert."""
    from sqlalchemy.exc import OperationalError, ProgrammingError
    try:
        await session.execute(text("""
            INSERT INTO blog_tracking (id, slug, time_on_page, scroll_depth, cta_clicked, created_at)
            VALUES (:id, :slug, :top, :sd, :cta, :ts)
        """), {
            "id": str(uuid.uuid4()),
            "slug": data.slug,
            "top": data.time_on_page,
            "sd": data.scroll_depth,
            "cta": data.cta_clicked,
            "ts": datetime.now(timezone.utc),
        })
        await session.commit()
    except (ProgrammingError, OperationalError) as e:
        logger.warning(
            "blog_tracking_insert_failed",
            extra={
                "event":      "blog_tracking_insert_failed",
                "slug":       data.slug,
                "error_type": type(e).__name__,
            },
        )
        # Auto-create table if missing (one-shot self-heal).
        try:
            await session.rollback()
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS blog_tracking (
                    id VARCHAR(36) PRIMARY KEY,
                    slug VARCHAR(500) NOT NULL,
                    time_on_page FLOAT,
                    scroll_depth FLOAT,
                    cta_clicked VARCHAR(200),
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """))
            await session.execute(text("""
                INSERT INTO blog_tracking (id, slug, time_on_page, scroll_depth, cta_clicked, created_at)
                VALUES (:id, :slug, :top, :sd, :cta, :ts)
            """), {
                "id": str(uuid.uuid4()),
                "slug": data.slug,
                "top": data.time_on_page,
                "sd": data.scroll_depth,
                "cta": data.cta_clicked,
                "ts": datetime.now(timezone.utc),
            })
            await session.commit()
        except (ProgrammingError, OperationalError) as e2:
            logger.error(
                "blog_tracking_table_creation_failed",
                extra={
                    "event":      "blog_tracking_table_creation_failed",
                    "slug":       data.slug,
                    "error_type": type(e2).__name__,
                },
            )

    return {"status": "ok"}
