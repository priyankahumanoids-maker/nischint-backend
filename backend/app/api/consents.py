"""DPDP-04: Consent service + HTTP API.

Endpoints (mounted at `/api/privacy/consents` by `api/main.py`):

  POST   /api/privacy/consents/me              → grant a category
  GET    /api/privacy/consents/me              → list current state
  DELETE /api/privacy/consents/me/{category}   → revoke a category

The grant endpoint is upsert-style: re-granting an existing category
updates `granted_at`, `consent_text_version`, `ip_address`,
`user_agent`, and clears `revoked_at`. This mirrors the typical UX
where toggling a previously-revoked category back ON should re-grant
without complaint.

Categories are enumerated in `CATEGORIES` below. Adding a new category
is code-only — no schema migration needed.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Final

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session
from app.models.consent import Consent
from app.models.user import User

logger = logging.getLogger(__name__)


# ── The 5 categories per DPDP-04 spec ────────────────────────────────
# Adding here is sufficient — no migration needed. The string value is
# what gets stored in `consents.category`.

CATEGORY_LOCATION:     Final = "location_tracking"
CATEGORY_AUDIO:        Final = "audio_recording"
CATEGORY_HEALTH:       Final = "health_vitals"
CATEGORY_PUSH:         Final = "push_notifications"
CATEGORY_BIOMETRIC:    Final = "biometric_sensors"

# Order matters — surfaces this order to clients (e.g. mobile settings
# screen renders in declared order).
CATEGORIES: tuple[str, ...] = (
    CATEGORY_LOCATION,
    CATEGORY_AUDIO,
    CATEGORY_HEALTH,
    CATEGORY_PUSH,
    CATEGORY_BIOMETRIC,
)

# Human-readable purpose for each category — surfaced in the GET
# response so clients don't hardcode strings. Update both the English
# and Hindi keys when changing copy.
CATEGORY_METADATA: dict[str, dict[str, str]] = {
    CATEGORY_LOCATION: {
        "label_en": "Location tracking",
        "label_hi": "स्थान ट्रैकिंग",
        "purpose_en": (
            "Always-on background GPS so guardians see where you are "
            "during an SOS. Disabling stops live-map updates."
        ),
        "purpose_hi": (
            "एसओएस के दौरान संरक्षक आपकी स्थिति देख सकें इसके लिए "
            "हमेशा-चालू पृष्ठभूमि जीपीएस।"
        ),
        "required_for": "live_map,sos,geofence",
    },
    CATEGORY_AUDIO: {
        "label_en": "Audio recording",
        "label_hi": "ऑडियो रिकॉर्डिंग",
        "purpose_en": (
            "Voice distress detection during emergency. Audio never "
            "leaves the device; only severity score is uploaded."
        ),
        "purpose_hi": (
            "आपातकाल के दौरान आवाज़ से संकट का पता लगाना। ऑडियो डिवाइस "
            "से बाहर नहीं जाता।"
        ),
        "required_for": "voice_distress,sos_audio_stream",
    },
    CATEGORY_HEALTH: {
        "label_en": "Health vitals",
        "label_hi": "स्वास्थ्य संकेत",
        "purpose_en": (
            "Read heart-rate, SpO2, steps from your wearable to detect "
            "medical anomalies and silent SOS triggers."
        ),
        "purpose_hi": (
            "चिकित्सीय असामान्यताओं का पता लगाने के लिए आपके पहनने वाले "
            "उपकरण से हृदय गति, एसपीओ2, कदम पढ़ें।"
        ),
        "required_for": "health_anomaly,silent_sos",
    },
    CATEGORY_PUSH: {
        "label_en": "Push notifications",
        "label_hi": "पुश सूचनाएँ",
        "purpose_en": (
            "Delivery of SOS, geofence, and health alerts to your "
            "device. Without consent, you will not receive emergency "
            "notifications."
        ),
        "purpose_hi": (
            "आपके डिवाइस पर एसओएस, जियोफ़ेंस और स्वास्थ्य अलर्ट देना।"
        ),
        "required_for": "alerts,sos_callback",
    },
    CATEGORY_BIOMETRIC: {
        "label_en": "Biometric sensors",
        "label_hi": "बायोमेट्रिक सेंसर",
        "purpose_en": (
            "Read accelerometer and gyroscope for fall detection. "
            "Raw motion data stays on-device."
        ),
        "purpose_hi": (
            "गिरने का पता लगाने के लिए एक्सेलेरोमीटर और जायरोस्कोप पढ़ें।"
        ),
        "required_for": "fall_detection",
    },
}

# Bump when consent text changes materially. Clients must re-prompt the
# user when this changes (compare with the stored consent_text_version).
CURRENT_CONSENT_TEXT_VERSION: Final = "1.0"


# ── Schemas ──────────────────────────────────────────────────────────


class ConsentGrantBody(BaseModel):
    category: str = Field(..., description="One of CATEGORIES")
    consent_text_version: str = Field(
        default=CURRENT_CONSENT_TEXT_VERSION,
        max_length=20,
    )
    app_version: str | None = Field(default=None, max_length=40)


class ConsentOut(BaseModel):
    category: str
    label_en: str
    label_hi: str
    purpose_en: str
    purpose_hi: str
    required_for: str
    granted: bool
    granted_at: datetime | None = None
    revoked_at: datetime | None = None
    consent_text_version: str | None = None
    app_version: str | None = None


# ── Router ───────────────────────────────────────────────────────────

router = APIRouter(prefix="/privacy/consents", tags=["privacy", "dpdp"])

# Separate router for the admin-only audit endpoint. Mounted at
# /api/admin/consents via api/main.py so the prefix tree stays clean.
admin_router = APIRouter(
    prefix="/admin/consents",
    tags=["admin", "privacy", "dpdp"],
)


@router.get("/me", response_model=list[ConsentOut])
async def get_my_consents(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Return the consent state for every supported category.

    Always returns one row per declared category — un-granted ones have
    `granted=false`, `granted_at=null`. This lets the client render the
    full settings screen without a second lookup of category metadata.
    """
    q = await session.execute(
        select(Consent).where(Consent.user_id == user.id)
    )
    by_cat = {c.category: c for c in q.scalars().all()}

    out: list[ConsentOut] = []
    for cat in CATEGORIES:
        meta = CATEGORY_METADATA[cat]
        row = by_cat.get(cat)
        if row is not None:
            granted = row.revoked_at is None
        else:
            granted = False
        out.append(ConsentOut(
            category=cat,
            label_en=meta["label_en"],
            label_hi=meta["label_hi"],
            purpose_en=meta["purpose_en"],
            purpose_hi=meta["purpose_hi"],
            required_for=meta["required_for"],
            granted=granted,
            granted_at=row.granted_at if row else None,
            revoked_at=row.revoked_at if row else None,
            consent_text_version=row.consent_text_version if row else None,
            app_version=row.app_version if row else None,
        ))
    return out


@router.post("/me", response_model=ConsentOut, status_code=200)
async def grant_consent(
    request: Request,
    body: ConsentGrantBody,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Grant consent for a category. Idempotent: re-granting refreshes
    `granted_at`, clears `revoked_at`, and updates the audit metadata."""
    if body.category not in CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"unknown category '{body.category}'. supported: {list(CATEGORIES)}",
        )

    now = datetime.now(timezone.utc)
    ip = _client_ip(request)
    ua = (request.headers.get("user-agent") or "")[:1000]

    q = await session.execute(
        select(Consent).where(
            Consent.user_id == user.id,
            Consent.category == body.category,
        )
    )
    row = q.scalar_one_or_none()

    if row is None:
        row = Consent(
            user_id=user.id,
            category=body.category,
            granted_at=now,
            revoked_at=None,
            ip_address=ip,
            app_version=body.app_version,
            consent_text_version=body.consent_text_version,
            user_agent=ua,
        )
        session.add(row)
    else:
        row.granted_at = now
        row.revoked_at = None
        row.ip_address = ip
        row.app_version = body.app_version
        row.consent_text_version = body.consent_text_version
        row.user_agent = ua

    await session.flush()
    logger.info(
        "[consent] GRANT user_id=%s category=%s text_version=%s",
        user.id, body.category, body.consent_text_version,
    )

    meta = CATEGORY_METADATA[body.category]
    return ConsentOut(
        category=row.category,
        label_en=meta["label_en"],
        label_hi=meta["label_hi"],
        purpose_en=meta["purpose_en"],
        purpose_hi=meta["purpose_hi"],
        required_for=meta["required_for"],
        granted=True,
        granted_at=row.granted_at,
        revoked_at=None,
        consent_text_version=row.consent_text_version,
        app_version=row.app_version,
    )


@router.delete("/me/{category}", response_model=ConsentOut)
async def revoke_consent(
    category: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Revoke a previously-granted consent. Keeps the row for audit;
    only sets `revoked_at`. Idempotent for already-revoked categories.
    """
    if category not in CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"unknown category '{category}'. supported: {list(CATEGORIES)}",
        )

    q = await session.execute(
        select(Consent).where(
            Consent.user_id == user.id,
            Consent.category == category,
        )
    )
    row = q.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"no consent record for category '{category}'",
        )

    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        await session.flush()
        logger.info(
            "[consent] REVOKE user_id=%s category=%s",
            user.id, category,
        )

    meta = CATEGORY_METADATA[category]
    return ConsentOut(
        category=row.category,
        label_en=meta["label_en"],
        label_hi=meta["label_hi"],
        purpose_en=meta["purpose_en"],
        purpose_hi=meta["purpose_hi"],
        required_for=meta["required_for"],
        granted=False,
        granted_at=row.granted_at,
        revoked_at=row.revoked_at,
        consent_text_version=row.consent_text_version,
        app_version=row.app_version,
    )


def _client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()[:45]
    if request.client and request.client.host:
        return request.client.host[:45]
    return None


# ── Admin: audit-trail endpoint ──────────────────────────────────────


class AdminConsentRow(BaseModel):
    """Full consent row with audit fields — admin view only.

    Differs from `ConsentOut` (which is for the user's own settings
    screen): omits the bilingual labels/purposes (admin already knows
    what each category is), and ADDS the audit-trail fields the user
    doesn't need to see — ip_address, user_agent.
    """
    category: str
    granted: bool
    granted_at: datetime
    revoked_at: datetime | None = None
    consent_text_version: str
    app_version: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None


class AdminConsentBundle(BaseModel):
    user_id: str
    user_email: str | None = None
    rows: list[AdminConsentRow]


@admin_router.get("", response_model=AdminConsentBundle)
async def admin_get_consents(
    user_id: str,
    admin: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Audit-trail view: return every consent row Nischint has for the
    given `user_id`, including revoked ones. Used by the operator
    dashboard during a DPDP audit to demonstrate "evidence of consent
    for this user as of this moment".

    RBAC: admin or operator only. Re-implemented here (instead of using
    the `require_role` factory) so we can permit BOTH admin and
    operator in a single check — the existing helper only accepts one
    role at a time.
    """
    # Inline RBAC: admin OR operator may call. Anything else → 403.
    roles_attr = getattr(admin, "roles", None) or []
    if isinstance(roles_attr, str):
        roles_attr = [roles_attr]
    role_attr = getattr(admin, "role", None)
    user_roles = set(roles_attr) | ({role_attr} if role_attr else set())
    if not user_roles & {"admin", "operator"}:
        raise HTTPException(status_code=403, detail="admin or operator role required")

    # Validate user_id is a parseable UUID — anything else short-circuits
    # to 400 (don't leak that the user doesn't exist).
    import uuid as _uuid
    try:
        target_uuid = _uuid.UUID(user_id)
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail="invalid user_id") from e

    # Pull target user's email (audit context) without failing if
    # they've already been DPDP-erased — the consent rows are gone in
    # that case too (FK CASCADE), so an empty result is correct.
    user_email: str | None = None
    user_q = await session.execute(
        select(User).where(User.id == target_uuid)
    )
    target_user = user_q.scalar_one_or_none()
    if target_user is not None:
        user_email = target_user.email

    q = await session.execute(
        select(Consent)
        .where(Consent.user_id == target_uuid)
        .order_by(Consent.granted_at.desc())
    )
    rows = q.scalars().all()
    return AdminConsentBundle(
        user_id=user_id,
        user_email=user_email,
        rows=[
            AdminConsentRow(
                category=r.category,
                granted=(r.revoked_at is None),
                granted_at=r.granted_at,
                revoked_at=r.revoked_at,
                consent_text_version=r.consent_text_version,
                app_version=r.app_version,
                ip_address=r.ip_address,
                user_agent=r.user_agent,
            )
            for r in rows
        ],
    )


# ── Admin: aggregate consent health (DPDP-04-DASH) ────────────────────


class ConsentHealthCategory(BaseModel):
    """Aggregate consent state for a single category."""
    category: str
    label_en: str
    decided: int      # users with any row (granted or revoked)
    granted: int      # users with revoked_at IS NULL
    grant_rate: float  # granted / decided; 0.0 when decided == 0
    healthy: bool      # grant_rate >= HEALTHY_THRESHOLD (or sample too small)


class ConsentHealthBundle(BaseModel):
    """Snapshot used by the operator-dashboard ConsentHealthCapsule.

    `overall_state` collapses the per-category signal into a single
    chip colour:
      • "critical" — at least one category below CRITICAL_THRESHOLD
                     AND its sample is statistically meaningful.
      • "warning"  — at least one category below HEALTHY_THRESHOLD
                     with a meaningful sample.
      • "ok"       — every category at or above HEALTHY_THRESHOLD,
                     OR no category yet has a meaningful sample.
      • "nodata"   — nobody has been prompted for anything yet.
    """
    total_users_prompted: int
    overall_state: str  # 'ok' | 'warning' | 'critical' | 'nodata'
    healthy_threshold: float
    critical_threshold: float
    min_sample_size: int
    categories: list[ConsentHealthCategory]
    generated_at: datetime


# Thresholds — locked here, surfaced in the API response so the frontend
# never hardcodes them. Tuned for DPDP §6 expectations: grant rates
# above 80% are typical for safety apps where each category maps to a
# concrete user-visible feature. Below 50% suggests a copy regression
# or a buggy permission flow that needs immediate operator attention.
HEALTHY_THRESHOLD: Final = 0.80
CRITICAL_THRESHOLD: Final = 0.50
# Below this sample size, treat the category as `healthy=True` so a
# single declining user doesn't paint the dashboard red.
MIN_SAMPLE_SIZE: Final = 10


@admin_router.get("/health", response_model=ConsentHealthBundle)
async def admin_consent_health(
    admin: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ConsentHealthBundle:
    """Aggregate grant rate per consent category — operator-only.

    The capsule on the Command Center polls this every 60s. Used to
    detect copy regressions (a UX change drops grant rate from 90% →
    60%) before they erode feature adoption.

    RBAC mirrors `admin_get_consents`: admin or operator role.
    """
    # Inline RBAC — same pattern as admin_get_consents above.
    roles_attr = getattr(admin, "roles", None) or []
    if isinstance(roles_attr, str):
        roles_attr = [roles_attr]
    role_attr = getattr(admin, "role", None)
    user_roles = set(roles_attr) | ({role_attr} if role_attr else set())
    if not user_roles & {"admin", "operator"}:
        raise HTTPException(status_code=403, detail="admin or operator role required")

    return await compute_consent_health(session)


async def compute_consent_health(session: AsyncSession) -> ConsentHealthBundle:
    """Pure data-fetch + classification — no RBAC, no HTTP.

    Extracted so the weekly DPDP digest scheduler (and any future
    headless caller) can reuse the same aggregation logic without
    re-implementing it. The HTTP route layer above is the only place
    where RBAC is enforced.
    """
    # Single round-trip aggregation. We can't rely on COUNT DISTINCT
    # user_id because (user_id, category) is already unique — so a
    # plain COUNT(*) gives the same answer with less work.
    q = await session.execute(
        select(
            Consent.category,
            func.count(Consent.id).label("decided"),
            func.count(Consent.id)
                .filter(Consent.revoked_at.is_(None))
                .label("granted"),
        ).group_by(Consent.category)
    )
    rows = {r.category: (r.decided, r.granted) for r in q.all()}

    # Distinct users who have been prompted for *any* category — used
    # as the global denominator for the "% of users engaging" summary.
    total_users_q = await session.execute(
        select(func.count(func.distinct(Consent.user_id)))
    )
    total_users_prompted = total_users_q.scalar() or 0

    categories: list[ConsentHealthCategory] = []
    worst_state = "ok"  # downgraded as we find unhealthy categories
    for cat in CATEGORIES:
        decided, granted = rows.get(cat, (0, 0))
        grant_rate = (granted / decided) if decided else 0.0
        # Below MIN_SAMPLE_SIZE we deliberately mark healthy=True so a
        # cold-start project (with 1 declining user) doesn't paint the
        # capsule red. The frontend can still inspect the raw numbers.
        if decided < MIN_SAMPLE_SIZE:
            healthy = True
        else:
            healthy = grant_rate >= HEALTHY_THRESHOLD
            if grant_rate < CRITICAL_THRESHOLD:
                worst_state = "critical"
            elif grant_rate < HEALTHY_THRESHOLD and worst_state == "ok":
                worst_state = "warning"
        categories.append(ConsentHealthCategory(
            category=cat,
            label_en=CATEGORY_METADATA[cat]["label_en"],
            decided=decided,
            granted=granted,
            grant_rate=round(grant_rate, 4),
            healthy=healthy,
        ))

    if total_users_prompted == 0:
        overall_state = "nodata"
    else:
        overall_state = worst_state

    return ConsentHealthBundle(
        total_users_prompted=total_users_prompted,
        overall_state=overall_state,
        healthy_threshold=HEALTHY_THRESHOLD,
        critical_threshold=CRITICAL_THRESHOLD,
        min_sample_size=MIN_SAMPLE_SIZE,
        categories=categories,
        generated_at=datetime.now(timezone.utc),
    )
