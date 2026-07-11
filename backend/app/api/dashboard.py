# Dashboard Router
import logging
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.models.user import User
from app.schemas.dashboard import GuardianSummary
from app.services import dashboard_service
from app.services.redis_service import get_json, set_json

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=GuardianSummary)
async def get_guardian_summary(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Get aggregated dashboard summary for the logged-in guardian.
    
    Returns counts for:
    - total_seniors
    - total_devices
    - active_incidents (open status)
    - critical_incidents (critical severity + open)
    - devices_online
    - devices_offline
    """
    summary = await dashboard_service.get_guardian_summary(session, current_user.id)
    return summary


@router.get("/sla")
async def get_sla_metrics(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Get SLA metrics (avg acknowledgment time, avg resolution time) for the guardian."""
    return await dashboard_service.get_sla_metrics(session, current_user.id)


@router.get("/overview")
async def get_dashboard_overview(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Batch endpoint that returns summary + SLA + response metrics in one call.
    Cached in Redis with 10-second TTL for fast Command Center loads.
    """
    cache_key = f"overview:{current_user.id}"
    cached = get_json("dashboard", cache_key)
    if cached:
        return cached

    import asyncio
    summary_task = dashboard_service.get_guardian_summary(session, current_user.id)
    sla_task = dashboard_service.get_sla_metrics(session, current_user.id)
    metrics_task = dashboard_service.get_response_metrics(session)

    summary, sla, metrics = await asyncio.gather(summary_task, sla_task, metrics_task)

    result = {
        "summary": summary,
        "sla": sla,
        "metrics": metrics,
    }

    set_json("dashboard", cache_key, result, ttl=10)
    return result


@router.get("/family-users")
async def get_family_users(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Get all protected users in the family scope for drill-down.
    Combines:
      • Elderly seniors (Senior table) that the guardian monitors — test/seed rows excluded
      • Real child/woman users linked via the guardians table (via get_loved_ones)
    """
    from app.services.dashboard_service import _get_family_senior_ids, is_test_senior_name
    from app.services.guardian_dashboard_engine import get_loved_ones as _get_loved_ones
    from app.models.senior import Senior
    from sqlalchemy import select

    results: list[dict] = []

    # ── Real monitored users (child / woman) via guardians table — FIRST (richer metadata) ──
    seen_names: set[str] = set()
    seen_emails: set[str] = set()
    lo: dict = {}
    try:
        role = getattr(current_user, "role", None)
        lo = await _get_loved_ones(session, current_user.email, str(current_user.id), user_role=role)
    except Exception as e:  # noqa: BLE001 — enrichment fallback
        # Non-fatal — enrichment failure must not block the seniors
        # fallback below. Structured log so a regression in
        # `_get_loved_ones` doesn't disappear silently. The audit
        # picks this up only because `set.add` shares its method
        # name with `session.add` — see test_swallow_audit allow-list.
        logger.warning(
            "dashboard_loved_ones_lookup_failed",
            extra={
                "event":      "dashboard_loved_ones_lookup_failed",
                "user_id":    str(current_user.id),
                "error_type": type(e).__name__,
            },
        )
        lo = {}
    for m in (lo.get("monitored_users") or []):
        name = (m.get("name") or "").strip()
        email = (m.get("email") or "").strip().lower()
        results.append({
            "id": str(m.get("user_id") or m.get("id") or ""),
            "full_name": m.get("name"),
            "age": None,
            "medical_notes": None,
            "status": m.get("status") or "monitored",
            "email": m.get("email"),
            "phone": m.get("phone"),
            "role": m.get("role"),
            "relationship": m.get("relationship"),
            "location": m.get("location"),
            "last_updated": m.get("last_updated"),
            "has_active_session": m.get("has_active_session", False),
            "kind": m.get("role") or "monitored_user",
        })
        if name:
            seen_names.add(name.lower())
        if email:
            seen_emails.add(email)

    # ── Elderly seniors — appended after, excluding duplicates already shown as monitored users ──
    senior_ids = await _get_family_senior_ids(session, current_user.id)
    if senior_ids:
        senior_rows = await session.execute(
            select(Senior).where(Senior.id.in_(senior_ids))
        )
        for s in senior_rows.scalars().all():
            if is_test_senior_name(s.full_name):
                continue  # defensive: belt + suspenders
            nm = (s.full_name or "").strip().lower()
            if nm and nm in seen_names:
                continue  # already represented by the richer loved-ones entry
            results.append({
                "id": str(s.id),
                "full_name": s.full_name,
                "age": s.age,
                "medical_notes": s.medical_notes,
                "status": "monitored",
                "kind": "senior",
            })

    return results


@router.get("/family-devices")
async def get_family_devices(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Get all devices in the family scope for drill-down."""
    from app.services.dashboard_service import _get_family_senior_ids
    from app.models.device import Device
    from app.models.senior import Senior
    from sqlalchemy import select

    senior_ids = await _get_family_senior_ids(session, current_user.id)
    if not senior_ids:
        return []

    result = await session.execute(
        select(Device, Senior.full_name).join(Senior, Device.senior_id == Senior.id).where(
            Device.senior_id.in_(senior_ids)
        )
    )
    rows = result.all()
    return [
        {
            "id": str(d.id),
            "device_identifier": d.device_identifier,
            "device_type": d.device_type,
            "status": d.status,
            "last_seen": d.last_seen.isoformat() if d.last_seen else None,
            "senior_name": name,
        }
        for d, name in rows
    ]
