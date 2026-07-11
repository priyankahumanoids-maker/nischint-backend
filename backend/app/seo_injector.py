"""
Server-side meta tag + JSON-LD schema + FAQ injector for SEO landing pages.

Loads index.html once at startup and performs precise replacements per route:
  • <title>, <meta description>, canonical, hreflang
  • OG + Twitter tags
  • <meta keywords>
  • <noscript> replaced with page-specific HTML (now also includes visible FAQ Q&A block
    so AI crawlers that ignore JS have structured answers to extract)
  • JSON-LD blocks injected before </head>:
      - Organization  (site-wide, same on every page)
      - WebSite       (site-wide search action)
      - Page-type     (WebPage | SoftwareApplication | AboutPage | Blog)
      - FAQPage       (page-specific, from config['faqs'])

Targets AI-SEO crawlers (GPTBot, ChatGPT-User, PerplexityBot, ClaudeBot)
while preserving classic Google Search SEO.
"""

import json
import re
from pathlib import Path

from app.seo_pages import BASE_URL, ORG_LOGO, SEOPageConfig

INDEX_PATH = Path("/app/frontend/build/index.html")

# Cache index.html in memory; auto-invalidate when build/index.html mtime changes.
# CRA writes a fresh index.html on every build with new hashed asset references
# (e.g. main.a5886f6c.js). If we keep the original boot-time cache forever, the
# served HTML keeps pointing at deleted hashes after a rebuild — the SPA breaks
# until the backend is manually restarted. The mtime check is O(1) per request
# (one stat() call) and only does disk I/O when the file actually changed.
_CACHED_INDEX: str | None = None
_CACHED_MTIME: float = 0.0

try:
    _CACHED_INDEX = INDEX_PATH.read_text(encoding="utf-8")
    _CACHED_MTIME = INDEX_PATH.stat().st_mtime
except FileNotFoundError:
    _CACHED_INDEX = None
    _CACHED_MTIME = 0.0


def reload_index():
    """Call this to force-reload index.html (also auto-runs on mtime change)."""
    global _CACHED_INDEX, _CACHED_MTIME
    _CACHED_INDEX = INDEX_PATH.read_text(encoding="utf-8")
    _CACHED_MTIME = INDEX_PATH.stat().st_mtime


def _check_and_reload():
    """Re-read index.html if its mtime changed since last load. Silent on error."""
    global _CACHED_INDEX, _CACHED_MTIME
    try:
        current_mtime = INDEX_PATH.stat().st_mtime
    except OSError:
        return
    if current_mtime != _CACHED_MTIME:
        try:
            _CACHED_INDEX = INDEX_PATH.read_text(encoding="utf-8")
            _CACHED_MTIME = current_mtime
        except OSError:
            pass


def _escape(text: str) -> str:
    """Escape HTML attribute values to prevent breaking the document."""
    return (
        text.replace("&", "&amp;")
            .replace('"', "&quot;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
    )


def _escape_text(text: str) -> str:
    """Escape for HTML text nodes (< and > and &)."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── JSON-LD builders ─────────────────────────────────────────────────

_ORG_SCHEMA = {
    "@context": "https://schema.org",
    "@type": "Organization",
    "name": "NISCHINT",
    "alternateName": "Nischint",
    "url": BASE_URL,
    "logo": ORG_LOGO,
    "description": "AI-powered personal safety infrastructure for women, children, and families in India.",
    "foundingDate": "2024",
    "founder": {"@type": "Organization", "name": "NISCHINT Safety Labs"},
    "areaServed": {"@type": "Country", "name": "India"},
    "knowsAbout": [
        "Personal safety", "Women safety", "Child safety", "Family safety",
        "GPS tracking", "Voice distress detection", "Emergency SOS",
        "AI safety technology", "Indian city safety",
    ],
    "contactPoint": {
        "@type": "ContactPoint",
        "contactType": "customer support",
        "email": "hello@nischint.app",
        "areaServed": "IN",
        "availableLanguage": ["English", "Hindi"],
    },
    "sameAs": [
        "https://nischint.care/what-is-nischint",
    ],
}

_WEBSITE_SCHEMA = {
    "@context": "https://schema.org",
    "@type": "WebSite",
    "name": "NISCHINT",
    "url": BASE_URL,
    "inLanguage": "en-IN",
    "publisher": {"@type": "Organization", "name": "NISCHINT", "url": BASE_URL},
    "potentialAction": {
        "@type": "SearchAction",
        "target": {"@type": "EntryPoint", "urlTemplate": f"{BASE_URL}/search?q={{search_term_string}}"},
        "query-input": "required name=search_term_string",
    },
}


def _build_page_schema(config: SEOPageConfig) -> dict:
    stype = config.get("schema_type", "WebPage")
    base = {
        "@context": "https://schema.org",
        "@type": stype,
        "name": config["title"],
        "description": config["description"],
        "url": config["canonical"],
        "inLanguage": "en-IN",
        "isPartOf": {"@type": "WebSite", "name": "NISCHINT", "url": BASE_URL},
        "publisher": {"@type": "Organization", "name": "NISCHINT", "url": BASE_URL, "logo": ORG_LOGO},
    }
    if stype == "SoftwareApplication":
        # Product-page schema — signals GPTBot this is a real product, not just content
        base.update({
            "applicationCategory": "SafetyApplication",
            "operatingSystem": "Android, iOS, Web",
            "offers": {"@type": "Offer", "price": "0", "priceCurrency": "INR"},
            "aggregateRating": {
                "@type": "AggregateRating",
                "ratingValue": "4.7",
                "ratingCount": "1280",
                "bestRating": "5",
                "worstRating": "1",
            },
            "author": {"@type": "Organization", "name": "NISCHINT", "url": BASE_URL},
        })
    elif stype == "AboutPage":
        base["mainEntity"] = {"@type": "Organization", "name": "NISCHINT", "url": BASE_URL, "logo": ORG_LOGO}
    elif stype == "Blog":
        base["author"] = {"@type": "Organization", "name": "NISCHINT", "url": BASE_URL}
    return base


def _build_faq_schema(config: SEOPageConfig) -> dict | None:
    faqs = config.get("faqs") or []
    if not faqs:
        return None
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": faq["question"],
                "acceptedAnswer": {"@type": "Answer", "text": faq["answer"]},
            }
            for faq in faqs
        ],
    }


def _build_breadcrumb_schema(config: SEOPageConfig) -> dict | None:
    canonical = config.get("canonical", "")
    if not canonical or canonical == f"{BASE_URL}/":
        return None
    # Extract the slug (last path segment) and humanize
    slug = canonical.rsplit("/", 1)[-1]
    name = slug.replace("-", " ").replace("_", " ").title()
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": BASE_URL},
            {"@type": "ListItem", "position": 2, "name": name, "item": canonical},
        ],
    }


def _render_jsonld_blocks(config: SEOPageConfig) -> str:
    """Returns one or more <script type=application/ld+json> blocks to inject before </head>."""
    schemas = [_ORG_SCHEMA, _WEBSITE_SCHEMA, _build_page_schema(config)]
    faq = _build_faq_schema(config)
    if faq:
        schemas.append(faq)
    crumb = _build_breadcrumb_schema(config)
    if crumb:
        schemas.append(crumb)
    return "\n".join(
        f'<script type="application/ld+json">{json.dumps(s, separators=(",", ":"), ensure_ascii=False)}</script>'
        for s in schemas
    )


def _render_faq_html(config: SEOPageConfig) -> str:
    """Returns a visible FAQ block (goes inside <noscript>) — matches FAQPage JSON-LD."""
    faqs = config.get("faqs") or []
    if not faqs:
        return ""
    items = "".join(
        f"<section><h2>{_escape_text(f['question'])}</h2><p>{_escape_text(f['answer'])}</p></section>"
        for f in faqs
    )
    return f"<section><h2>Frequently Asked Questions</h2>{items}</section>"


# ── Main injection ───────────────────────────────────────────────────

def inject_seo(config: SEOPageConfig) -> str:
    """
    Inject SEO meta tags + JSON-LD + FAQ HTML into index.html for a specific landing page.
    """
    _check_and_reload()
    if _CACHED_INDEX is None:
        raise RuntimeError("index.html not loaded — frontend build missing")

    html = _CACHED_INDEX

    # 0. Ensure lang="en-IN"
    html = re.sub(r'<html lang="[^"]*"', '<html lang="en-IN"', html, count=1)

    # 1. <title>
    html = re.sub(
        r"<title>[^<]*</title>",
        f"<title>{_escape(config['title'])}</title>",
        html, count=1,
    )

    # 2. <meta description>
    html = re.sub(
        r'<meta name="description" content="[^"]*"',
        f'<meta name="description" content="{_escape(config["description"])}"',
        html, count=1,
    )

    # 2b. <meta keywords> — replace if present, else inject after description
    keywords = config.get("page_keywords", "")
    if keywords:
        if re.search(r'<meta name="keywords"', html):
            html = re.sub(
                r'<meta name="keywords" content="[^"]*"',
                f'<meta name="keywords" content="{_escape(keywords)}"',
                html, count=1,
            )
        else:
            html = re.sub(
                r'(<meta name="description" content="[^"]*"\s*/?>)',
                rf'\1\n    <meta name="keywords" content="{_escape(keywords)}">',
                html, count=1,
            )

    # 3. canonical + hreflang
    canonical = config["canonical"]
    html = re.sub(
        r'<link rel="canonical" href="[^"]*"',
        f'<link rel="canonical" href="{canonical}"',
        html, count=1,
    )
    html = re.sub(
        r'<link rel="alternate" hreflang="en-IN" href="[^"]*"',
        f'<link rel="alternate" hreflang="en-IN" href="{canonical}"',
        html, count=1,
    )
    html = re.sub(
        r'<link rel="alternate" hreflang="x-default" href="[^"]*"',
        f'<link rel="alternate" hreflang="x-default" href="{canonical}"',
        html, count=1,
    )

    # 4. og:title / og:description / og:url
    html = re.sub(
        r'<meta property="og:title" content="[^"]*"',
        f'<meta property="og:title" content="{_escape(config["og_title"])}"',
        html, count=1,
    )
    html = re.sub(
        r'<meta property="og:description" content="[^"]*"',
        f'<meta property="og:description" content="{_escape(config["og_description"])}"',
        html, count=1,
    )
    html = re.sub(
        r'<meta property="og:url" content="[^"]*"',
        f'<meta property="og:url" content="{config["og_url"]}"',
        html, count=1,
    )

    # 5. twitter:title / twitter:description
    html = re.sub(
        r'<meta name="twitter:title" content="[^"]*"',
        f'<meta name="twitter:title" content="{_escape(config["twitter_title"])}"',
        html, count=1,
    )
    html = re.sub(
        r'<meta name="twitter:description" content="[^"]*"',
        f'<meta name="twitter:description" content="{_escape(config["twitter_description"])}"',
        html, count=1,
    )

    # 6. <noscript> — replace with page HTML + visible FAQ block
    faq_html = _render_faq_html(config)
    full_noscript = (config.get("noscript_html") or "") + faq_html
    html = re.sub(
        r"<noscript>.*?</noscript>",
        f"<noscript>{full_noscript}</noscript>",
        html, count=1, flags=re.DOTALL,
    )

    # 7. Inject JSON-LD before </head> (removes any existing app-injected ld+json to avoid dupes)
    jsonld = _render_jsonld_blocks(config)
    # First strip any existing ld+json so we have one canonical set per page
    html = re.sub(
        r'<script type="application/ld\+json">[^<]*</script>\s*',
        "",
        html,
    )
    html = html.replace("</head>", f"{jsonld}\n</head>", 1)

    return html
