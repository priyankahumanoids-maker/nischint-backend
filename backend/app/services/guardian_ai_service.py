# Guardian AI Service — Predictive intelligence engine
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guardian_ai import GuardianAIConfig, GuardianAIPrediction
from app.services.event_broadcaster import broadcaster
from app.services.location_intelligence import compute_location_risk
from app.services.behavior_analyzer import analyze_behavior
from app.services.safety_brain_service import get_user_risk_status

logger = logging.getLogger(__name__)

SENSITIVITY_MULTIPLIERS = {
    "low": 0.8,
    "medium": 1.0,
    "high": 1.2,
}

DEFAULT_CONFIG = {
    "enabled": True,
    "sensitivity": "medium",
    "notification_threshold": 0.6,
    "call_threshold": 0.75,
    "sos_threshold": 0.85,
    "auto_trigger": False,
    "cooldown_minutes": 30,
}


def _config_to_dict(cfg: GuardianAIConfig) -> dict:
    return {
        "id": str(cfg.id),
        "user_id": str(cfg.user_id),
        "enabled": cfg.enabled,
        "sensitivity": cfg.sensitivity,
        "notification_threshold": cfg.notification_threshold,
        "call_threshold": cfg.call_threshold,
        "sos_threshold": cfg.sos_threshold,
        "auto_trigger": cfg.auto_trigger,
        "cooldown_minutes": cfg.cooldown_minutes,
        "updated_at": cfg.updated_at.isoformat(),
    }


def _prediction_to_dict(p: GuardianAIPrediction) -> dict:
    return {
        "id": str(p.id),
        "user_id": str(p.user_id),
        "risk_score": p.risk_score,
        "risk_level": p.risk_level,
        "confidence": p.confidence,
        "recommended_action": p.recommended_action,
        "action_detail": p.action_detail,
        "risk_factors": p.risk_factors,
        "layer_scores": p.layer_scores,
        "narrative": p.narrative,
        "status": p.status,
        "user_response": p.user_response,
        "lat": p.lat,
        "lng": p.lng,
        "created_at": p.created_at.isoformat(),
        "responded_at": p.responded_at.isoformat() if p.responded_at else None,
    }


async def get_or_create_config(session: AsyncSession, user_id: uuid.UUID) -> dict:
    result = await session.execute(
        select(GuardianAIConfig).where(GuardianAIConfig.user_id == user_id)
    )
    cfg = result.scalar_one_or_none()
    if not cfg:
        cfg = GuardianAIConfig(user_id=user_id, **DEFAULT_CONFIG)
        session.add(cfg)
        await session.flush()
    return _config_to_dict(cfg)


async def update_config(session: AsyncSession, user_id: uuid.UUID, data: dict) -> dict:
    result = await session.execute(
        select(GuardianAIConfig).where(GuardianAIConfig.user_id == user_id)
    )
    cfg = result.scalar_one_or_none()
    if not cfg:
        cfg = GuardianAIConfig(user_id=user_id, **DEFAULT_CONFIG)
        session.add(cfg)
        await session.flush()

    updatable = (
        "enabled", "sensitivity", "notification_threshold", "call_threshold",
        "sos_threshold", "auto_trigger", "cooldown_minutes",
    )
    for key in updatable:
        if key in data:
            setattr(cfg, key, data[key])
    cfg.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return _config_to_dict(cfg)


def _classify_risk(score: float) -> str:
    if score >= 0.85:
        return "critical"
    if score >= 0.6:
        return "high"
    if score >= 0.35:
        return "moderate"
    return "low"


def _recommend_action(score: float, cfg_dict: dict) -> tuple[str, dict]:
    sensitivity = SENSITIVITY_MULTIPLIERS.get(cfg_dict.get("sensitivity", "medium"), 1.0)
    adjusted = score * sensitivity

    if adjusted >= cfg_dict.get("sos_threshold", 0.85):
        return "sos_prearm", {
            "action": "Pre-arm SOS with chain escape",
            "chain_notification": True,
            "chain_call": True,
            "urgency": "critical",
        }
    if adjusted >= cfg_dict.get("call_threshold", 0.75):
        return "fake_call", {
            "action": "Trigger escape call",
            "caller_name": "Boss",
            "delay_seconds": 30,
            "urgency": "high",
        }
    if adjusted >= cfg_dict.get("notification_threshold", 0.6):
        return "fake_notification", {
            "action": "Send escape notification",
            "title": "Team Meeting in 5 min",
            "delay_seconds": 10,
            "urgency": "medium",
        }
    return "monitor", {
        "action": "Continue monitoring",
        "urgency": "low",
    }


async def predict_risk(
    session: AsyncSession,
    user_id: uuid.UUID,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
) -> dict:
    """Run the Guardian AI prediction pipeline."""

    # 1. Get config
    cfg_dict = await get_or_create_config(session, user_id)
    await session.commit()

    # 2. Gather data from Safety Brain layers
    risk_factors = []
    layer_scores = {}

    # Layer 1: Real-time signals
    try:
        rt_status = await get_user_risk_status(session, str(user_id))
        rt_score = rt_status.get("risk_score", 0.0)
        layer_scores["realtime"] = {
            "score": rt_score,
            "level": rt_status.get("risk_level", "normal"),
            "primary_event": rt_status.get("primary_event", "none"),
        }
        if rt_score > 0.3:
            risk_factors.append({
                "type": "realtime_signals",
                "severity": "high" if rt_score > 0.6 else "medium",
                "detail": f"Active safety signals detected (score: {rt_score:.2f})",
            })
    except Exception as e:
        logger.warning(f"Failed to get real-time status: {e}")
        layer_scores["realtime"] = {"score": 0.0, "level": "unknown", "error": str(e)}

    # Layer 2: Location intelligence
    loc_score = 0.0
    if lat and lng:
        try:
            loc_data = await compute_location_risk(session, str(user_id), lat, lng)
            loc_score = loc_data.get("danger_score", 0.0)
            layer_scores["location"] = {
                "score": loc_score,
                "incident_density": loc_data.get("incident_density", 0.0),
                "night_risk": loc_data.get("night_time_risk", 0.0),
                "nearby_incidents": loc_data.get("nearby_incidents", 0),
            }
            if loc_score > 0.3:
                risk_factors.append({
                    "type": "location_risk",
                    "severity": "high" if loc_score > 0.6 else "medium",
                    "detail": f"High-risk zone detected (density: {loc_data.get('incident_density', 0):.2f}, nearby: {loc_data.get('nearby_incidents', 0)})",
                })
        except Exception as e:
            logger.warning(f"Failed to compute location risk: {e}")
            layer_scores["location"] = {"score": 0.0, "error": str(e)}

    # Layer 3: Behavioral patterns
    try:
        behavior = await analyze_behavior(session, str(user_id))
        beh_score = behavior.get("anomaly_score", 0.0)
        layer_scores["behavioral"] = {
            "score": beh_score,
            "stability": behavior.get("stability", "low"),
            "confidence": behavior.get("confidence", 0.0),
            "patterns": behavior.get("patterns", [])[:3],
        }
        if beh_score > 0.3:
            patterns = behavior.get("patterns", [])
            top_pattern = patterns[0]["type"] if patterns else "behavioral_anomaly"
            risk_factors.append({
                "type": "behavioral_anomaly",
                "severity": "high" if beh_score > 0.6 else "medium",
                "detail": f"Pattern deviation detected: {top_pattern.replace('_', ' ')} (score: {beh_score:.2f})",
            })
    except Exception as e:
        logger.warning(f"Failed to analyze behavior: {e}")
        beh_score = 0.0
        layer_scores["behavioral"] = {"score": 0.0, "error": str(e)}

    # 3. Fuse scores (same 50/25/25 weighting as Safety Brain)
    rt_score_val = layer_scores.get("realtime", {}).get("score", 0.0)
    fused_score = (rt_score_val * 0.50) + (loc_score * 0.25) + (beh_score * 0.25)
    fused_score = min(fused_score, 1.0)

    # Apply non-linear escalation for multiple high factors
    high_factors = sum(1 for f in risk_factors if f["severity"] == "high")
    if high_factors >= 2:
        fused_score = min(fused_score * 1.3, 1.0)

    risk_level = _classify_risk(fused_score)
    confidence = min(
        0.4 + (len(risk_factors) * 0.15) + (beh_score * 0.2) + (0.1 if lat else 0),
        0.98,
    )

    # 4. Determine recommended action
    action_type, action_detail = _recommend_action(fused_score, cfg_dict)

    # 5. Generate narrative
    narrative = _build_narrative(fused_score, risk_level, risk_factors, layer_scores, action_type)

    # 6. Save prediction
    prediction = GuardianAIPrediction(
        user_id=user_id,
        risk_score=round(fused_score, 4),
        risk_level=risk_level,
        confidence=round(confidence, 4),
        recommended_action=action_type,
        action_detail=action_detail,
        risk_factors=risk_factors,
        layer_scores=layer_scores,
        narrative=narrative,
        status="pending" if action_type != "monitor" else "completed",
        lat=lat,
        lng=lng,
    )
    session.add(prediction)
    await session.flush()

    result = _prediction_to_dict(prediction)

    # 7. Broadcast if actionable
    if action_type != "monitor":
        await broadcaster.broadcast_to_user(str(user_id), "guardian_ai_alert", result)
        await broadcaster.broadcast_to_operators("guardian_ai_alert", result)
        logger.info(f"Guardian AI alert for user {user_id}: {risk_level} ({fused_score:.2f}) → {action_type}")

    return result


def _build_narrative(score, level, factors, layers, action):
    parts = [f"Risk Assessment: {level.upper()} ({score:.0%})"]

    rt = layers.get("realtime", {})
    if rt.get("score", 0) > 0:
        parts.append(f"Real-time signals active (primary: {rt.get('primary_event', 'unknown')})")

    loc = layers.get("location", {})
    if loc.get("score", 0) > 0.1:
        parts.append(f"Location risk elevated — {loc.get('nearby_incidents', 0)} nearby incidents")

    beh = layers.get("behavioral", {})
    if beh.get("score", 0) > 0.1:
        stability = beh.get("stability", "unknown")
        parts.append(f"Behavioral patterns show {stability} stability")

    for f in factors[:3]:
        parts.append(f"Factor: {f['detail']}")

    action_labels = {
        "sos_prearm": "RECOMMENDED: Pre-arm SOS with full chain escape sequence",
        "fake_call": "RECOMMENDED: Trigger escape call from trusted contact",
        "fake_notification": "RECOMMENDED: Send discreet escape notification",
        "monitor": "Continue standard monitoring",
    }
    parts.append(action_labels.get(action, "Continue monitoring"))

    return "\n".join(parts)


async def respond_to_prediction(
    session: AsyncSession,
    user_id: uuid.UUID,
    prediction_id: uuid.UUID,
    response: str,
) -> Optional[dict]:
    result = await session.execute(
        select(GuardianAIPrediction)
        .where(GuardianAIPrediction.id == prediction_id, GuardianAIPrediction.user_id == user_id)
    )
    pred = result.scalar_one_or_none()
    if not pred:
        return None

    pred.status = "accepted" if response == "accept" else "dismissed"
    pred.user_response = response
    pred.responded_at = datetime.now(timezone.utc)
    await session.flush()

    return _prediction_to_dict(pred)


async def get_history(session: AsyncSession, user_id: uuid.UUID, limit: int = 20) -> list[dict]:
    result = await session.execute(
        select(GuardianAIPrediction)
        .where(GuardianAIPrediction.user_id == user_id)
        .order_by(GuardianAIPrediction.created_at.desc())
        .limit(limit)
    )
    return [_prediction_to_dict(p) for p in result.scalars().all()]
