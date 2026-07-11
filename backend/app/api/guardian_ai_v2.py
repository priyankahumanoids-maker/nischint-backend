# Guardian AI Refinement API — baselines, risk scores, predictions, explainability
import os
import json
import uuid as uuid_mod
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.core.roles import require_role
from app.models.user import User
from app.services.guardian_ai_refinement import (
    get_or_create_baseline,
    compute_risk_score,
    generate_predictions,
    compute_all_baselines,
    get_high_risk_users,
    get_risk_history,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/guardian-ai", tags=["Guardian AI"])

# ── Threat Assessment Cache ──
_threat_cache = {"data": None, "expires_at": 0}
THREAT_CACHE_TTL = 60  # seconds


@router.get("/{user_id}/baseline")
async def get_baseline(
    user_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("admin", "operator")),
):
    """Get or create behavioral baseline for a user."""
    uid = uuid_mod.UUID(user_id)
    baseline = await get_or_create_baseline(session, uid)
    await session.commit()
    return baseline


@router.get("/{user_id}/risk-score")
async def get_risk_score(
    user_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("admin", "operator")),
):
    """Compute real-time multi-factor risk score with explainability."""
    uid = uuid_mod.UUID(user_id)
    result = await compute_risk_score(session, uid)
    await session.commit()
    return result


@router.get("/{user_id}/predictions")
async def get_predictions(
    user_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("admin", "operator")),
):
    """Generate forward-looking risk predictions for a user."""
    uid = uuid_mod.UUID(user_id)
    predictions = await generate_predictions(session, uid)
    await session.commit()
    return {"user_id": user_id, "predictions": predictions}


@router.get("/{user_id}/risk-history")
async def get_user_risk_history(
    user_id: str,
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("admin", "operator")),
):
    """Get risk event log for a user (audit/ML training data)."""
    uid = uuid_mod.UUID(user_id)
    events = await get_risk_history(session, uid, limit)
    return {"user_id": user_id, "events": events, "total": len(events)}


@router.post("/compute-baselines")
async def batch_compute_baselines(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("admin")),
):
    """Batch compute/update baselines for all users with guardian sessions."""
    result = await compute_all_baselines(session)
    await session.commit()
    return result


@router.get("/insights/high-risk")
async def high_risk_users(
    limit: int = Query(10, ge=1, le=50),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("admin", "operator")),
):
    """Get users with highest current risk scores."""
    users = await get_high_risk_users(session, limit)
    return {"high_risk_users": users, "total": len(users)}


@router.get("/insights/threat-assessment")
async def threat_assessment(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("admin", "operator")),
):
    """Generate AI-powered operational threat assessment briefing."""
    global _threat_cache
    now = time.time()
    if _threat_cache["data"] and now < _threat_cache["expires_at"]:
        return _threat_cache["data"]

    from app.models.guardian_ai_v2 import GuardianRiskScore
    from app.models.incident import Incident
    from app.models.senior import Senior
    from app.services.dynamic_risk_engine import get_live_heatmap
    from datetime import datetime, timezone, timedelta

    # 1. Gather heatmap signals from cache
    heatmap = get_live_heatmap()
    cells = heatmap.get("cells", []) if heatmap else []
    zones = [{"zone": c.get("grid_id", "?"), "risk": c.get("risk_level", "low"), "score": round(c.get("composite_score", 0), 1)} for c in cells[:10]]

    critical_zones = sum(1 for c in cells if c.get("risk_level", "").lower() == "critical")
    high_zones = sum(1 for c in cells if c.get("risk_level", "").lower() == "high")
    rising_zones = sum(1 for c in cells if c.get("composite_score", 0) > 5.5)

    # 2. High-risk users
    hr_users = await get_high_risk_users(session, 5)
    user_signals = []
    for u in hr_users:
        status = "behavior anomaly" if u.get("risk_level") in ("high", "critical") else "elevated risk"
        top_f = u.get("top_factors", [])
        if top_f:
            status = top_f[0].get("description", status)
        user_signals.append({
            "name": u.get("user_name", "Unknown"),
            "risk": round(u.get("final_score", 0), 2),
            "status": status,
        })

    # 3. Recent incidents (last 2 hours)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
    recent_incidents = (await session.execute(
        select(func.count()).where(and_(
            Incident.created_at >= cutoff,
            Incident.is_test == False,
        ))
    )).scalar() or 0

    # 4. Predictive alerts count
    pred_alerts = len([u for u in hr_users if u.get("final_score", 0) > 0.5])

    # Determine threat level
    max_risk = max([u.get("final_score", 0) for u in hr_users], default=0)
    if critical_zones > 0 or max_risk >= 0.8:
        threat_level = "CRITICAL"
    elif high_zones > 3 or max_risk >= 0.6:
        threat_level = "HIGH"
    elif high_zones > 0 or max_risk >= 0.35:
        threat_level = "MODERATE"
    else:
        threat_level = "SAFE"

    top_zone = zones[0]["zone"] if zones else "N/A"

    # 5. Build signal payload for GPT
    signal_payload = {
        "heatmap": zones[:5],
        "zone_summary": {"critical": critical_zones, "high": high_zones, "rising": rising_zones},
        "users": user_signals[:3],
        "predictive_alerts": pred_alerts,
        "recent_incidents": recent_incidents,
        "threat_level": threat_level,
    }

    # 6. Call GPT for narrative
    narrative = await _generate_threat_narrative(signal_payload)

    result = {
        "threat_level": threat_level,
        "summary": narrative,
        "zones_escalating": critical_zones + high_zones,
        "users_anomaly": len([u for u in hr_users if u.get("final_score", 0) > 0.5]),
        "top_zone": top_zone,
        "recent_incidents": recent_incidents,
        "recommended_action": _get_recommended_action(threat_level, top_zone),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    _threat_cache = {"data": result, "expires_at": now + THREAT_CACHE_TTL}
    return result


def _get_recommended_action(threat_level: str, top_zone: str) -> str:
    if threat_level == "CRITICAL":
        return f"Immediate patrol deployment to Zone {top_zone}. Alert all guardians."
    elif threat_level == "HIGH":
        return f"Increase patrol coverage in Zone {top_zone}. Notify guardian network."
    elif threat_level == "MODERATE":
        return f"Monitor Zone {top_zone}. Standard patrol protocols."
    return "All zones within normal parameters. Continue standard monitoring."


async def _generate_threat_narrative(signals: dict) -> str:
    """Generate operational threat briefing via GPT-5.2."""
    fallback = _template_narrative(signals)
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage

        api_key = os.environ.get("EMERGENT_LLM_KEY")
        if not api_key:
            return fallback

        chat = LlmChat(
            api_key=api_key,
            session_id=f"threat-{uuid_mod.uuid4().hex[:8]}",
            system_message=(
                "You are Guardian AI, a safety intelligence engine for a city monitoring platform. "
                "Generate concise operational threat assessments for command center operators. "
                "Be direct, factual, and actionable. 2-3 sentences max. "
                "Mention specific zones, user anomalies, and recommended actions."
            ),
        ).with_model("openai", "gpt-5.2")

        prompt = (
            "Generate a short operational safety briefing based on these risk signals. "
            "2-3 sentences. Mention zones, users, and actions.\n\n"
            f"SIGNALS:\n{json.dumps(signals, indent=2, default=str)}"
        )

        from app.services.ai_metrics import track
        async with track("guardian_ai_v2.assess"):
            response = await chat.send_message(UserMessage(text=prompt))
        text = response.strip()
        if len(text) > 20:
            return text
    except Exception as e:
        logger.warning(f"Threat narrative GPT call failed: {e}")

    return fallback


def _template_narrative(signals: dict) -> str:
    """Fallback template-based narrative."""
    zones = signals.get("zone_summary", {})
    users = signals.get("users", [])
    high = zones.get("high", 0) + zones.get("critical", 0)
    anomaly_users = [u for u in users if u.get("risk", 0) > 0.5]
    top_zone = signals.get("heatmap", [{}])[0].get("zone", "N/A") if signals.get("heatmap") else "N/A"

    parts = []
    if high > 0:
        parts.append(f"{high} zones showing escalating risk patterns.")
    if anomaly_users:
        parts.append(f"{len(anomaly_users)} monitored user{'s' if len(anomaly_users) > 1 else ''} showing behavioral anomalies.")
    if not parts:
        parts.append("All monitored zones within normal parameters.")

    parts.append(f"Recommended: {'Increase patrol visibility in Zone ' + top_zone if high > 0 else 'Continue standard monitoring protocols'}.")
    return " ".join(parts)
