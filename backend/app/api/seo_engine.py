"""
NISCHINT Level 2 SEO System
────────────────────────────
5 engines: Keyword Clustering, Topical Authority Map,
Programmatic Page Generator, Internal Linking, GEO Scaling.
All in-memory, no DB, no auth.
"""

import logging
import re
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/seo", tags=["Level 2 SEO"])

# ═══════════════════════════════════════════════════════════════
# SHARED DATA: CITIES + CATEGORIES
# ═══════════════════════════════════════════════════════════════

TIER_1 = ["Mumbai", "Delhi", "Bangalore", "Chennai", "Hyderabad", "Kolkata", "Pune"]
TIER_2 = ["Ahmedabad", "Jaipur", "Lucknow", "Chandigarh", "Indore", "Nagpur", "Surat",
          "Coimbatore", "Kochi", "Thiruvananthapuram", "Visakhapatnam", "Bhopal",
          "Patna", "Guwahati", "Dehradun", "Ranchi", "Bhubaneswar"]
TIER_3 = ["Mysore", "Vadodara", "Noida", "Gurugram", "Thane", "Navi Mumbai",
          "Agra", "Varanasi", "Ludhiana", "Amritsar", "Jodhpur", "Raipur",
          "Gwalior", "Mangalore", "Tiruchirappalli", "Madurai", "Vijayawada",
          "Jabalpur", "Aurangabad", "Hubli", "Salem", "Warangal", "Guntur",
          "Rajkot", "Meerut", "Bareilly", "Aligarh", "Moradabad", "Gorakhpur",
          "Bikaner", "Jamnagar", "Bhavnagar", "Udaipur", "Kota", "Ajmer"]

ALL_CITIES = TIER_1 + TIER_2 + TIER_3

CATEGORIES = {
    "women_safety": {
        "label": "Women Safety",
        "keywords": ["women safety", "women protection", "female safety", "ladies safety",
                     "personal safety women", "women security", "girl safety"],
        "slugs": ["women-safety-app", "best-women-safety-app"],
    },
    "kids_safety": {
        "label": "Kids Safety",
        "keywords": ["kids safety", "child safety", "child tracking", "kids tracker",
                     "child monitoring", "kid protection", "school safety", "student safety"],
        "slugs": ["kids-safety-app"],
    },
    "family_safety": {
        "label": "Family Safety",
        "keywords": ["family safety", "family tracking", "family protection",
                     "elderly safety", "senior safety", "family security"],
        "slugs": ["family-safety-app"],
    },
    "personal_safety": {
        "label": "Personal Safety",
        "keywords": ["personal safety", "safety app", "sos app", "emergency app",
                     "panic button", "distress alert"],
        "slugs": ["personal-safety-app"],
    },
    "campus_safety": {
        "label": "Campus Safety",
        "keywords": ["campus safety", "university safety", "college safety",
                     "hostel safety", "campus security"],
        "slugs": ["campus-safety-app"],
    },
    "corporate_safety": {
        "label": "Corporate Safety",
        "keywords": ["corporate safety", "employee safety", "workplace safety",
                     "office safety", "company safety"],
        "slugs": ["corporate-safety-app"],
    },
}

CITY_NEARBY = {
    "Mumbai": ["Thane", "Navi Mumbai", "Pune"],
    "Delhi": ["Noida", "Gurugram", "Gwalior"],
    "Bangalore": ["Mysore", "Chennai", "Mangalore"],
    "Chennai": ["Coimbatore", "Madurai", "Bangalore"],
    "Hyderabad": ["Visakhapatnam", "Warangal", "Vijayawada"],
    "Kolkata": ["Patna", "Ranchi", "Bhubaneswar"],
    "Pune": ["Mumbai", "Nagpur", "Aurangabad"],
    "Ahmedabad": ["Surat", "Vadodara", "Rajkot"],
    "Jaipur": ["Jodhpur", "Udaipur", "Kota"],
    "Lucknow": ["Varanasi", "Agra", "Gorakhpur"],
}

VARIANT_PREFIXES = ["", "best-", "personal-"]

# In-memory stores
_generated_pages: Dict[str, dict] = {}
_authority_map: dict = {}

# ═══════════════════════════════════════════════════════════════
# CITY CONTENT TEMPLATES (unique per city for no-duplicate rule)
# ═══════════════════════════════════════════════════════════════

CITY_CONTEXT = {
    "Mumbai": {"challenge": "dense urban sprawl and late-night commuting", "strength": "extensive local train network coverage"},
    "Delhi": {"challenge": "high-density areas and nighttime safety concerns", "strength": "metro connectivity and police helpline integration"},
    "Bangalore": {"challenge": "rapid tech corridor expansion and IT park late shifts", "strength": "tech-savvy population and quick emergency response"},
    "Chennai": {"challenge": "monsoon-affected commutes and coastal hazards", "strength": "strong community networks and women helpline adoption"},
    "Hyderabad": {"challenge": "old city navigation and mixed-traffic zones", "strength": "growing smart city infrastructure and CCTV coverage"},
    "Kolkata": {"challenge": "congested heritage zones and crowded public transit", "strength": "community policing model and neighborhood watch systems"},
    "Pune": {"challenge": "expanding IT zones and student safety in campus areas", "strength": "proactive police tech adoption and safety-focused culture"},
}
DEFAULT_CONTEXT = {"challenge": "urban safety concerns and growing population density", "strength": "increasing smartphone adoption and demand for safety technology"}


# ═══════════════════════════════════════════════════════════════
# PYDANTIC MODELS
# ═══════════════════════════════════════════════════════════════

class ClusterInput(BaseModel):
    keywords: List[str]


class AuthorityInput(BaseModel):
    clusters: Optional[Dict[str, List[str]]] = None


class PageGenInput(BaseModel):
    city: str
    category: str
    variant: str = "default"


class LinksInput(BaseModel):
    pages: List[str]


class ScaleInput(BaseModel):
    cities: Optional[List[str]] = None
    categories: Optional[List[str]] = None
    variants: Optional[List[str]] = None
    limit: int = 100


# ═══════════════════════════════════════════════════════════════
# MODULE 1: KEYWORD CLUSTERING ENGINE
# ═══════════════════════════════════════════════════════════════

def _classify_keyword(kw: str) -> str:
    """Classify a keyword into a category by word overlap."""
    kw_lower = kw.lower()
    best_cat = "general_safety"
    best_score = 0
    for cat_id, cat in CATEGORIES.items():
        score = sum(1 for seed in cat["keywords"] if any(w in kw_lower for w in seed.split()))
        if score > best_score:
            best_score = score
            best_cat = cat_id
    return best_cat


@router.post("/cluster")
def cluster_keywords(payload: ClusterInput):
    """Cluster input keywords into intent-based groups."""
    if not payload.keywords:
        raise HTTPException(status_code=400, detail="Keywords list is empty")

    clusters = defaultdict(list)
    for kw in payload.keywords:
        cat = _classify_keyword(kw)
        clusters[cat].append(kw)

    # Detect city mentions and tag them
    city_tags = defaultdict(list)
    for kw in payload.keywords:
        kw_lower = kw.lower()
        for city in ALL_CITIES:
            if city.lower() in kw_lower:
                city_tags[city].append(kw)

    return {
        "clusters": dict(clusters),
        "cluster_count": len(clusters),
        "keyword_count": len(payload.keywords),
        "city_mentions": dict(city_tags),
    }


# ═══════════════════════════════════════════════════════════════
# MODULE 2: TOPICAL AUTHORITY MAP
# ═══════════════════════════════════════════════════════════════

@router.post("/authority-map")
def build_authority_map(payload: AuthorityInput):
    """Convert keyword clusters into pillar → cluster → page hierarchy."""
    global _authority_map

    # Use provided clusters or default categories
    if payload.clusters:
        clusters_data = payload.clusters
    else:
        clusters_data = {cat_id: cat["keywords"][:3] for cat_id, cat in CATEGORIES.items()}

    authority = {
        "pillar": "AI Safety",
        "pillar_url": "/",
        "clusters": [],
    }

    for cluster_id, keywords in clusters_data.items():
        cat = CATEGORIES.get(cluster_id, {"label": cluster_id.replace("_", " ").title(), "slugs": []})

        pages = []
        for city in TIER_1:
            city_slug = city.lower().replace(" ", "-")
            for slug_base in cat.get("slugs", [f"{cluster_id.replace('_', '-')}-app"]):
                pages.append({
                    "title": f"{cat['label']} App in {city}",
                    "slug": f"{slug_base}-{city_slug}",
                    "city": city,
                    "category": cluster_id,
                })

        authority["clusters"].append({
            "id": cluster_id,
            "name": cat["label"],
            "keywords": keywords,
            "page_count": len(pages),
            "pages": pages,
        })

    authority["total_pages"] = sum(c["page_count"] for c in authority["clusters"])
    _authority_map = authority

    return authority


# ═══════════════════════════════════════════════════════════════
# MODULE 3: PROGRAMMATIC SEO PAGE GENERATOR
# ═══════════════════════════════════════════════════════════════

def _generate_page_content(city: str, category: str, variant: str) -> dict:
    """Generate a complete SEO page with unique content per city/category."""
    cat = CATEGORIES.get(category, {"label": category.replace("_", " ").title()})
    label = cat["label"]
    ctx = CITY_CONTEXT.get(city, DEFAULT_CONTEXT)
    city_slug = city.lower().replace(" ", "-")

    # Variant-specific title
    if variant == "best":
        title = f"Best {label} App in {city} | NISCHINT"
        slug = f"best-{category.replace('_', '-')}-app-{city_slug}"
    elif variant == "personal":
        title = f"Personal Safety App in {city} | NISCHINT"
        slug = f"personal-safety-app-{city_slug}"
    else:
        title = f"{label} App in {city} | NISCHINT {label}"
        slug = f"{category.replace('_', '-')}-app-{city_slug}"

    meta = f"NISCHINT provides AI-powered {label.lower()} in {city}. Real-time GPS tracking, voice distress detection, and instant alerts for {city} residents."

    h1 = f"{label} App in {city}"
    if variant == "best":
        h1 = f"Best {label} App in {city}"

    # Unique content (city-specific)
    content = (
        f"{city} faces {ctx['challenge']}. NISCHINT addresses this with AI-powered {label.lower()} technology "
        f"that provides real-time protection for residents across the city. "
        f"With {ctx['strength']}, NISCHINT integrates seamlessly into daily life in {city}.\n\n"
        f"Key features of NISCHINT {label} in {city}:\n"
        f"- Real-time GPS tracking optimized for {city}'s geography\n"
        f"- AI-powered voice distress detection that works in noisy {city} environments\n"
        f"- Instant guardian alerts with sub-3-second response time\n"
        f"- Geofencing for safe zones across {city} neighborhoods\n"
        f"- 24/7 monitoring with predictive risk assessment\n\n"
        f"Whether commuting through {city}'s busiest areas or traveling at night, "
        f"NISCHINT ensures continuous protection. Our AI safety engine processes over "
        f"10,000 signals per second, providing proactive safety for every user in {city}.\n\n"
        f"Join thousands of {city} residents who trust NISCHINT for {label.lower()}. "
        f"Download now and experience the difference that AI-powered safety makes."
    )

    # Internal links
    nearby = CITY_NEARBY.get(city, TIER_1[:3])
    links = []
    for nc in nearby[:3]:
        nc_slug = nc.lower().replace(" ", "-")
        links.append({"text": f"{label} in {nc}", "url": f"/{category.replace('_', '-')}-app-{nc_slug}"})

    # Cross-category links
    other_cats = [c for c in CATEGORIES if c != category][:2]
    for oc in other_cats:
        oc_label = CATEGORIES[oc]["label"]
        links.append({"text": f"{oc_label} App", "url": f"/{oc.replace('_', '-')}-app"})

    # Pillar link
    links.append({"text": "NISCHINT AI Safety Platform", "url": "/"})

    return {
        "slug": slug,
        "title": title,
        "meta_description": meta,
        "h1": h1,
        "content": content,
        "word_count": len(content.split()),
        "internal_links": links,
        "city": city,
        "category": category,
        "variant": variant,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/generate-page")
def generate_page(payload: PageGenInput):
    """Generate a single SEO-optimized page."""
    if payload.city not in ALL_CITIES:
        raise HTTPException(status_code=400, detail=f"Unknown city: {payload.city}")
    if payload.category not in CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Unknown category: {payload.category}. Valid: {list(CATEGORIES.keys())}")

    page = _generate_page_content(payload.city, payload.category, payload.variant)
    _generated_pages[page["slug"]] = page

    return page


@router.get("/pages")
def list_generated_pages(category: Optional[str] = None, city: Optional[str] = None):
    """List all generated pages. Optionally filter by category or city."""
    pages = list(_generated_pages.values())
    if category:
        pages = [p for p in pages if p["category"] == category]
    if city:
        pages = [p for p in pages if p["city"] == city]

    return {
        "pages": [{"slug": p["slug"], "title": p["title"], "city": p["city"], "category": p["category"], "variant": p["variant"]} for p in pages],
        "count": len(pages),
        "total_generated": len(_generated_pages),
    }


# ═══════════════════════════════════════════════════════════════
# MODULE 4: INTERNAL LINKING ENGINE
# ═══════════════════════════════════════════════════════════════

@router.post("/links")
def generate_links(payload: LinksInput):
    """Generate internal links between pages."""
    if not payload.pages:
        raise HTTPException(status_code=400, detail="Pages list is empty")

    # Parse each slug to extract city and category
    parsed = []
    for slug in payload.pages:
        city_match = re.search(r"app-(.+?)(?:\.html)?$", slug)
        city = city_match.group(1).replace("-", " ").title() if city_match else None
        cat = None
        for cat_id in CATEGORIES:
            if cat_id.replace("_", "-") in slug:
                cat = cat_id
                break
        parsed.append({"slug": slug, "city": city, "category": cat})

    link_map = {}
    for page in parsed:
        links = []
        slug = page["slug"]
        city = page["city"]
        cat = page["category"]

        # 1. Same category, nearby cities
        if city:
            nearby = CITY_NEARBY.get(city, [])
            for nc in nearby[:3]:
                nc_slug = nc.lower().replace(" ", "-")
                for other in parsed:
                    if nc_slug in other["slug"] and other["slug"] != slug and other["category"] == cat:
                        links.append({"slug": other["slug"], "reason": "nearby_city"})
                        break

        # 2. Same city, different category
        for other in parsed:
            if other["city"] == city and other["category"] != cat and other["slug"] != slug:
                links.append({"slug": other["slug"], "reason": "related_category"})
                if len(links) >= 8:
                    break

        # 3. Pillar link
        links.append({"slug": "/", "reason": "pillar"})

        # Cap at 10
        link_map[slug] = links[:10]

    return {"link_map": link_map, "total_pages": len(link_map)}


# ═══════════════════════════════════════════════════════════════
# MODULE 5: GEO PAGE SCALING ENGINE
# ═══════════════════════════════════════════════════════════════

@router.post("/scale-generate")
def scale_generate(payload: ScaleInput):
    """Bulk-generate SEO pages at scale."""
    cities = payload.cities or (TIER_1 + TIER_2)
    categories = payload.categories or list(CATEGORIES.keys())[:4]
    variants = payload.variants or ["default", "best"]
    limit = min(payload.limit, 2000)

    created = []
    skipped = []
    count = 0

    for city in cities:
        if city not in ALL_CITIES:
            skipped.append({"city": city, "reason": "unknown_city"})
            continue
        for cat in categories:
            if cat not in CATEGORIES:
                skipped.append({"category": cat, "reason": "unknown_category"})
                continue
            for variant in variants:
                if count >= limit:
                    break
                page = _generate_page_content(city, cat, variant)
                if page["slug"] in _generated_pages:
                    skipped.append({"slug": page["slug"], "reason": "already_exists"})
                    continue
                _generated_pages[page["slug"]] = page
                created.append({"slug": page["slug"], "title": page["title"], "city": city, "category": cat, "variant": variant})
                count += 1
            if count >= limit:
                break
        if count >= limit:
            break

    return {
        "status": "ok",
        "created_count": len(created),
        "skipped_count": len(skipped),
        "total_pages_in_store": len(_generated_pages),
        "created": created,
        "skipped": skipped[:20],
    }


# ═══════════════════════════════════════════════════════════════
# STATS + CONFIG ENDPOINTS
# ═══════════════════════════════════════════════════════════════

@router.get("/config")
def get_seo_config():
    """Return available cities, categories, variants."""
    return {
        "cities": {"tier_1": TIER_1, "tier_2": TIER_2, "tier_3": TIER_3, "total": len(ALL_CITIES)},
        "categories": {k: v["label"] for k, v in CATEGORIES.items()},
        "variants": ["default", "best", "personal"],
    }


@router.get("/stats")
def get_seo_stats():
    """Return system-wide SEO generation stats."""
    pages = list(_generated_pages.values())
    by_cat = defaultdict(int)
    by_city = defaultdict(int)
    by_variant = defaultdict(int)
    for p in pages:
        by_cat[p["category"]] += 1
        by_city[p["city"]] += 1
        by_variant[p["variant"]] += 1

    return {
        "total_pages": len(pages),
        "by_category": dict(by_cat),
        "by_city": dict(sorted(by_city.items(), key=lambda x: x[1], reverse=True)[:20]),
        "by_variant": dict(by_variant),
        "authority_map_built": bool(_authority_map),
        "available_cities": len(ALL_CITIES),
        "max_possible_pages": len(ALL_CITIES) * len(CATEGORIES) * 3,
    }


# ═══════════════════════════════════════════════════════════════
# MODULE 6: SEO FACTORY PIPELINE
# ═══════════════════════════════════════════════════════════════

import os
import subprocess
import time

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_GEOPAGES_JS = os.path.join(_BASE_DIR, "frontend", "src", "data", "geoPages.js")
_INJECT_SEO_JS = os.path.join(_BASE_DIR, "frontend", "scripts", "inject-seo.js")
_BLOG_PY = os.path.join(_BASE_DIR, "backend", "app", "api", "blog.py")
_BUILD_DIR = os.path.join(_BASE_DIR, "frontend", "build")

CITY_STATES = {
    "Mumbai": "Maharashtra", "Delhi": "Delhi", "Bangalore": "Karnataka",
    "Chennai": "Tamil Nadu", "Hyderabad": "Telangana", "Pune": "Maharashtra",
    "Kolkata": "West Bengal", "Ahmedabad": "Gujarat", "Jaipur": "Rajasthan",
    "Lucknow": "Uttar Pradesh", "Chandigarh": "Chandigarh", "Indore": "Madhya Pradesh",
    "Nagpur": "Maharashtra", "Surat": "Gujarat", "Coimbatore": "Tamil Nadu",
    "Kochi": "Kerala", "Thiruvananthapuram": "Kerala", "Visakhapatnam": "Andhra Pradesh",
    "Bhopal": "Madhya Pradesh", "Patna": "Bihar", "Guwahati": "Assam",
    "Dehradun": "Uttarakhand", "Ranchi": "Jharkhand", "Bhubaneswar": "Odisha",
    "Mysore": "Karnataka", "Vadodara": "Gujarat", "Noida": "Uttar Pradesh",
    "Gurugram": "Haryana", "Thane": "Maharashtra", "Navi Mumbai": "Maharashtra",
    "Agra": "Uttar Pradesh", "Varanasi": "Uttar Pradesh", "Ludhiana": "Punjab",
    "Amritsar": "Punjab", "Jodhpur": "Rajasthan", "Raipur": "Chhattisgarh",
    "Gwalior": "Madhya Pradesh", "Mangalore": "Karnataka", "Tiruchirappalli": "Tamil Nadu",
    "Madurai": "Tamil Nadu", "Vijayawada": "Andhra Pradesh", "Jabalpur": "Madhya Pradesh",
    "Aurangabad": "Maharashtra", "Hubli": "Karnataka", "Salem": "Tamil Nadu",
    "Warangal": "Telangana", "Guntur": "Andhra Pradesh", "Rajkot": "Gujarat",
    "Meerut": "Uttar Pradesh", "Bareilly": "Uttar Pradesh", "Aligarh": "Uttar Pradesh",
    "Moradabad": "Uttar Pradesh", "Gorakhpur": "Uttar Pradesh", "Bikaner": "Rajasthan",
    "Jamnagar": "Gujarat", "Bhavnagar": "Gujarat", "Udaipur": "Rajasthan",
    "Kota": "Rajasthan", "Ajmer": "Rajasthan",
}


class FullDeployInput(BaseModel):
    categories: Optional[List[str]] = None
    city_tiers: Optional[List[str]] = None  # ["tier_1", "tier_2", "tier_3"]
    variants: Optional[List[str]] = None
    limit: int = 1062
    dry_run: bool = False


def _resolve_cities(tiers: Optional[List[str]]) -> List[str]:
    if not tiers:
        return TIER_1 + TIER_2
    cities = []
    if "tier_1" in tiers:
        cities += TIER_1
    if "tier_2" in tiers:
        cities += TIER_2
    if "tier_3" in tiers:
        cities += TIER_3
    return cities or TIER_1


def _write_geopages_js(pages: list) -> int:
    """Rewrite geoPages.js with full page list."""
    lines = ["export const geoPages = ["]
    for p in pages:
        state = CITY_STATES.get(p["city"], "India")
        lines.append(f'  {{ slug: "{p["slug"]}", city: "{p["city"]}", state: "{state}", type: "{p["type"]}", variant: "{p["variant"]}" }},')
    lines.append("];")
    lines.append("")
    with open(_GEOPAGES_JS, "w") as f:
        f.write("\n".join(lines))
    return len(pages)


def _patch_inject_seo_geo_pages(pages: list) -> int:
    """Rewrite the GEO_PAGES array inside inject-seo.js."""
    with open(_INJECT_SEO_JS, "r") as f:
        content = f.read()

    new_entries = []
    for p in pages:
        state = CITY_STATES.get(p["city"], "India")
        new_entries.append(f'  {{ slug: "{p["slug"]}", city: "{p["city"]}", state: "{state}", type: "{p["type"]}", variant: "{p["variant"]}" }},')

    new_block = "const GEO_PAGES = [\n" + "\n".join(new_entries) + "\n];"

    pattern = r"const GEO_PAGES = \[[\s\S]*?\];"
    if re.search(pattern, content):
        content = re.sub(pattern, new_block, content, count=1)
    else:
        logger.error("[SEO_FACTORY] Could not find GEO_PAGES in inject-seo.js")
        return 0

    with open(_INJECT_SEO_JS, "w") as f:
        f.write(content)
    return len(pages)


def _patch_sitemap(slugs: list) -> int:
    """Rewrite the geo_pages list in blog.py."""
    with open(_BLOG_PY, "r") as f:
        content = f.read()

    slug_lines = "\n".join(f'        "{s}",' for s in slugs)
    new_block = f"    geo_pages = [\n{slug_lines}\n    ]"

    pattern = r"    geo_pages = \[[\s\S]*?\]"
    if re.search(pattern, content):
        content = re.sub(pattern, new_block, content, count=1)
    else:
        logger.warning("[SEO_FACTORY] Could not find geo_pages list in blog.py")
        return 0

    with open(_BLOG_PY, "w") as f:
        f.write(content)
    return len(slugs)


def _run_seo_inject() -> dict:
    """Run inject-seo.js to generate static HTML."""
    script = os.path.join(_BASE_DIR, "frontend", "scripts", "inject-seo.js")
    if not os.path.isdir(_BUILD_DIR):
        return {"ok": False, "error": "Build directory not found"}
    try:
        result = subprocess.run(
            ["node", script],
            capture_output=True, text=True, timeout=60,
            cwd=os.path.join(_BASE_DIR, "frontend"),
        )
        output = result.stdout[-500:] if result.stdout else ""
        if result.returncode != 0:
            return {"ok": False, "error": result.stderr[-300:], "output": output}
        return {"ok": True, "output": output}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _validate_build(slugs: list) -> dict:
    """Check that generated HTML files exist in build/."""
    found = 0
    missing = []
    for slug in slugs:
        flat = os.path.join(_BUILD_DIR, f"{slug}.html")
        folder = os.path.join(_BUILD_DIR, slug, "index.html")
        if os.path.isfile(flat) or os.path.isfile(folder):
            found += 1
        else:
            missing.append(slug)

    return {
        "total_expected": len(slugs),
        "found": found,
        "missing_count": len(missing),
        "missing_sample": missing[:10],
        "pass": len(missing) == 0,
    }


@router.post("/full-deploy")
def full_deploy(payload: FullDeployInput):
    """
    Full SEO Factory Pipeline:
    Generate → Write files → Build HTML → Validate → Report.
    """
    start = time.time()
    pipeline_log = []

    def log(step, msg, **extra):
        entry = {"step": step, "message": msg, "time": round(time.time() - start, 1), **extra}
        pipeline_log.append(entry)
        logger.info(f"[SEO_FACTORY] Step {step}: {msg}")

    # ── Step 1: Generate pages ──
    log(1, "Generating pages")
    cities = _resolve_cities(payload.city_tiers)
    categories = payload.categories or ["women_safety", "kids_safety", "family_safety", "personal_safety"]
    variants = payload.variants or ["default", "best"]
    limit = min(payload.limit, 2000)

    pages_data = []
    seen_slugs = set()
    for city in cities:
        if city not in ALL_CITIES:
            continue
        for cat in categories:
            if cat not in CATEGORIES:
                continue
            for variant in variants:
                if len(pages_data) >= limit:
                    break
                page = _generate_page_content(city, cat, variant)
                if page["slug"] in seen_slugs:
                    continue
                seen_slugs.add(page["slug"])
                # Map category to supported inject-seo.js types (women/kids/family)
                TYPE_MAP = {"women": "women", "kids": "kids", "family": "family", "personal": "women", "campus": "women", "corporate": "women"}
                type_key = TYPE_MAP.get(cat.replace("_safety", "").replace("_", "-"), "women")
                pages_data.append({
                    "slug": page["slug"],
                    "city": city,
                    "type": type_key,
                    "variant": variant,
                    "title": page["title"],
                })
                _generated_pages[page["slug"]] = page
            if len(pages_data) >= limit:
                break
        if len(pages_data) >= limit:
            break

    log(1, f"Generated {len(pages_data)} pages", count=len(pages_data))

    if payload.dry_run:
        return {
            "status": "dry_run",
            "pages_generated": len(pages_data),
            "sample": [p["slug"] for p in pages_data[:10]],
            "pipeline_log": pipeline_log,
            "elapsed_seconds": round(time.time() - start, 1),
        }

    # ── Step 2: Write geoPages.js ──
    log(2, "Writing geoPages.js")
    geo_count = _write_geopages_js(pages_data)
    log(2, f"Wrote {geo_count} entries to geoPages.js", count=geo_count)

    # ── Step 3: Patch inject-seo.js ──
    log(3, "Patching inject-seo.js GEO_PAGES")
    inject_count = _patch_inject_seo_geo_pages(pages_data)
    log(3, f"Patched {inject_count} entries", count=inject_count)

    # ── Step 4: Update sitemap ──
    log(4, "Updating blog.py sitemap")
    all_slugs = [p["slug"] for p in pages_data]
    sitemap_count = _patch_sitemap(all_slugs)
    log(4, f"Sitemap updated with {sitemap_count} slugs", count=sitemap_count)

    # ── Step 5: Run inject-seo.js ──
    log(5, "Running inject-seo.js (static HTML generation)")
    build_result = _run_seo_inject()
    if not build_result["ok"]:
        log(5, f"BUILD FAILED: {build_result.get('error', 'unknown')}", status="failed")
        return {
            "status": "failed",
            "failed_at": "build",
            "error": build_result.get("error"),
            "pages_generated": len(pages_data),
            "pipeline_log": pipeline_log,
            "elapsed_seconds": round(time.time() - start, 1),
        }
    log(5, "Build completed", status="success")

    # ── Step 6: Validate build ──
    log(6, "Validating build files")
    validation = _validate_build(all_slugs)
    log(6, f"Found {validation['found']}/{validation['total_expected']} files", **validation)

    if not validation["pass"]:
        log(6, f"VALIDATION FAILED: {validation['missing_count']} files missing", status="failed")
        return {
            "status": "partial",
            "pages_generated": len(pages_data),
            "build_status": "success",
            "validation": validation,
            "pipeline_log": pipeline_log,
            "elapsed_seconds": round(time.time() - start, 1),
        }

    log(6, "All files validated", status="success")

    elapsed = round(time.time() - start, 1)
    log(7, f"Pipeline complete in {elapsed}s")

    return {
        "status": "success",
        "pages_generated": len(pages_data),
        "build_status": "success",
        "validation": validation,
        "deployment": "completed",
        "sitemap_updated": sitemap_count,
        "pipeline_log": pipeline_log,
        "elapsed_seconds": elapsed,
    }
