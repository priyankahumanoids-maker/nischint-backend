"""
GEO Auto-Scaling Engine — Manual-trigger system that expands high-performing GEO pages.
Reads analytics data, selects cities/variants to scale, updates geoPages.js + inject-seo.js + sitemap,
and triggers static HTML generation.
"""
import json
import logging
import os
import re
import subprocess
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session

logger = logging.getLogger(__name__)
router = APIRouter(tags=["GEO Scaling"])

# File paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
GEO_PAGES_JS = os.path.join(BASE_DIR, "frontend", "src", "data", "geoPages.js")
INJECT_SEO_JS = os.path.join(BASE_DIR, "frontend", "scripts", "inject-seo.js")
BLOG_PY = os.path.join(BASE_DIR, "backend", "app", "api", "blog.py")

# City-to-state mapping (Indian cities)
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
}

VARIANT_SLUGS = {
    "default": "{type}-safety-app-{city_slug}",
    "best": "best-{type}-safety-app-{city_slug}",
    "personal": "personal-safety-app-{city_slug}",
}

# Which new variant to try when the winner is known
EXPANSION_MAP = {
    "best": ["personal", "default"],
    "default": ["best", "personal"],
    "personal": ["best", "default"],
}


class GeoScaleRequest(BaseModel):
    mode: str = "expand"
    limit: int = 10


def _read_existing_slugs():
    """Read all existing slugs from geoPages.js."""
    slugs = set()
    if os.path.isfile(GEO_PAGES_JS):
        with open(GEO_PAGES_JS, "r") as f:
            content = f.read()
        for m in re.finditer(r'slug:\s*"([^"]+)"', content):
            slugs.add(m.group(1))
    return slugs


def _make_slug(city, stype, variant):
    """Generate a URL slug for a city/type/variant combo."""
    city_slug = city.lower().replace(" ", "-")
    template = VARIANT_SLUGS.get(variant, VARIANT_SLUGS["default"])
    return template.format(type=stype, city_slug=city_slug)


def _append_to_geopages_js(entries):
    """Append new entries to geoPages.js."""
    if not entries:
        return
    with open(GEO_PAGES_JS, "r") as f:
        content = f.read()

    # Build new lines
    new_lines = []
    for e in entries:
        new_lines.append(
            f'  {{ slug: "{e["slug"]}", city: "{e["city"]}", state: "{e["state"]}", type: "{e["type"]}", variant: "{e["variant"]}" }},'
        )
    insert_block = "\n  // Auto-scaled pages\n" + "\n".join(new_lines) + "\n"

    # Insert before the closing ];
    content = content.rstrip()
    if content.endswith("];"):
        content = content[:-2] + insert_block + "];\n"
    else:
        content = content.rstrip().rstrip(";").rstrip("]") + insert_block + "];\n"

    with open(GEO_PAGES_JS, "w") as f:
        f.write(content)
    logger.info(f"[GEO_SCALE] Updated geoPages.js with {len(entries)} new entries")


def _append_to_inject_seo_js(entries):
    """Append new entries to inject-seo.js GEO_PAGES array."""
    if not entries:
        return
    with open(INJECT_SEO_JS, "r") as f:
        content = f.read()

    new_lines = []
    for e in entries:
        new_lines.append(
            f'  {{ slug: "{e["slug"]}", city: "{e["city"]}", state: "{e["state"]}", type: "{e["type"]}", variant: "{e["variant"]}" }},'
        )
    insert_block = "\n  // Auto-scaled\n" + "\n".join(new_lines) + "\n"

    # Find the GEO_PAGES closing ];
    pattern = r"(const GEO_PAGES = \[[\s\S]*?)(];\s*\nfunction generateGeoSEO)"
    match = re.search(pattern, content)
    if match:
        content = content[:match.end(1)] + insert_block + match.group(2) + content[match.end(2):]
    else:
        logger.warning("[GEO_SCALE] Could not find GEO_PAGES array end in inject-seo.js")
        return

    with open(INJECT_SEO_JS, "w") as f:
        f.write(content)
    logger.info(f"[GEO_SCALE] Updated inject-seo.js with {len(entries)} new entries")


def _append_to_sitemap(slugs):
    """Append new slugs to the sitemap list in blog.py."""
    if not slugs:
        return
    with open(BLOG_PY, "r") as f:
        content = f.read()

    # Find the geo_pages list closing ]
    pattern = r'(    geo_pages = \[[\s\S]*?)(    \]\n    for slug in geo_pages)'
    match = re.search(pattern, content)
    if match:
        new_lines = "\n".join(f'        "{s}",' for s in slugs)
        insert = f"\n        # Auto-scaled\n{new_lines}\n"
        content = content[:match.end(1)] + insert + match.group(2) + content[match.end(2):]
    else:
        logger.warning("[GEO_SCALE] Could not find geo_pages list in blog.py")
        return

    with open(BLOG_PY, "w") as f:
        f.write(content)
    logger.info(f"[GEO_SCALE] Updated blog.py sitemap with {len(slugs)} new slugs")


def _run_inject_seo():
    """Run inject-seo.js to generate static HTML for new pages."""
    build_dir = os.path.join(BASE_DIR, "frontend", "build")
    script = os.path.join(BASE_DIR, "frontend", "scripts", "inject-seo.js")
    if not os.path.isdir(build_dir):
        logger.warning("[GEO_SCALE] Frontend build dir not found — skipping static generation (will run on next deploy)")
        return False
    try:
        result = subprocess.run(
            ["node", script],
            capture_output=True, text=True, timeout=30,
            cwd=os.path.join(BASE_DIR, "frontend"),
        )
        logger.info(f"[GEO_SCALE] inject-seo.js output: {result.stdout[-200:]}")
        return result.returncode == 0
    except Exception as e:
        logger.warning(f"[GEO_SCALE] inject-seo.js failed: {e}")
        return False


@router.post("/geo-scale")
async def scale_geo_pages(req: GeoScaleRequest, db: AsyncSession = Depends(get_db_session)):
    """
    Auto-scaling engine: expand high-performing GEO pages with new variants.
    Reads analytics, picks winners, generates new page targets, updates all files.
    """
    limit = min(req.limit, 10)  # Safety cap

    # Step 1: Get analytics
    from app.api.geo_analytics import geo_analytics
    analytics = await geo_analytics(days=30, db=db)

    benchmarking = analytics.get("city_benchmarking", [])
    vp_by_city = analytics.get("variant_performance_by_city", {})

    # Step 2: Read existing slugs
    existing_slugs = _read_existing_slugs()

    # Step 3: Select expansion targets
    created = []
    skipped = []

    for cb in benchmarking:
        if len(created) >= limit:
            break

        city = cb["city"]
        category = cb["category"]
        winner = cb["best_variant"]

        # Skip weak or insufficient
        if category not in ("high_performer", "above_average"):
            skipped.append({"city": city, "reason": f"category={category} — not eligible"})
            continue

        state = CITY_STATES.get(city)
        if not state:
            skipped.append({"city": city, "reason": "unknown city — no state mapping"})
            continue

        # Get existing variants for this city
        city_data = vp_by_city.get(city, {})
        existing_variants = {k for k in city_data if k not in ("winner", "action")}

        # Determine which new variants to create
        new_variants = EXPANSION_MAP.get(winner, ["best", "personal"])

        for new_variant in new_variants:
            if len(created) >= limit:
                break
            if new_variant in existing_variants:
                continue

            # Determine types to expand (use the type from analytics if available)
            types_to_expand = ["women"]  # Default expansion type
            # Check which types this city already has data for
            city_all = analytics.get("variant_performance_by_city", {}).get(city, {})
            for v_key, v_data in city_all.items():
                if isinstance(v_data, dict) and "views" in v_data:
                    pass  # Type info not stored per variant, use women as primary

            for stype in types_to_expand:
                if len(created) >= limit:
                    break
                slug = _make_slug(city, stype, new_variant)
                if slug in existing_slugs:
                    skipped.append({"slug": slug, "reason": "already exists"})
                    continue

                entry = {
                    "slug": slug,
                    "city": city,
                    "state": state,
                    "type": stype,
                    "variant": new_variant,
                }
                created.append(entry)
                existing_slugs.add(slug)

    # Step 4: Update files
    if created:
        _append_to_geopages_js(created)
        _append_to_inject_seo_js(created)
        _append_to_sitemap([e["slug"] for e in created])
        build_ok = _run_inject_seo()
    else:
        build_ok = None

    return {
        "status": "ok",
        "mode": req.mode,
        "created_pages": created,
        "created_count": len(created),
        "skipped": skipped,
        "skipped_count": len(skipped),
        "build_triggered": build_ok,
        "total_geo_pages": len(existing_slugs),
    }
