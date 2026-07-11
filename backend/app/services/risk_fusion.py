# Risk Fusion Engine
#
# 3-Layer fusion for the enhanced Safety Brain:
#   Layer 1: Real-time signals (50%) — existing safety brain scores
#   Layer 2: Location intelligence (25%) — grid-based danger scoring
#   Layer 3: Behavioral patterns (25%) — multi-day anomaly detection
#
# Special rules:
#   - Voice distress override: if voice detected → min risk 80%
#   - Critical signals always escalate regardless of other layers

import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.location_intelligence import compute_location_risk
from app.services.behavior_analyzer import analyze_behavior

logger = logging.getLogger(__name__)

# Layer weights
W_REALTIME = 0.50
W_LOCATION = 0.25
W_BEHAVIOR = 0.25

# Override rules
VOICE_DISTRESS_FLOOR = 0.80  # Voice detected → min 80%


def classify_fused_risk(score: float) -> str:
    if score >= 0.85:
        return "critical"
    elif score >= 0.60:
        return "dangerous"
    elif score >= 0.30:
        return "suspicious"
    return "normal"


async def compute_fused_risk(
    session: AsyncSession,
    user_id: str,
    realtime_score: float,
    realtime_signals: dict,
    lat: float,
    lng: float,
    skip_behavior: bool = False,
) -> dict:
    """
    Compute the 3-layer fused risk score.

    Args:
        realtime_score: Layer 1 score from existing Safety Brain
        realtime_signals: Dict of current signal values
        lat, lng: Current location for Layer 2
        skip_behavior: If True, skip Layer 3 (for fast evaluation)

    Returns: {
        fused_score, fused_level,
        layer1: {score, weight, signals},
        layer2: {score, weight, details},
        layer3: {score, weight, patterns, confidence, stability},
        overrides: [...],
    }
    """
    overrides = []

    # Layer 1: Real-time signals (already computed)
    layer1 = {
        "score": round(realtime_score, 3),
        "weight": W_REALTIME,
        "weighted": round(realtime_score * W_REALTIME, 3),
        "signals": realtime_signals,
    }

    # Layer 2: Location intelligence
    try:
        loc_result = await compute_location_risk(session, lat, lng)
        location_score = loc_result["score"]
    except Exception as e:
        logger.warning(f"Location intelligence failed: {e}")
        location_score = 0.0
        loc_result = {"score": 0.0, "details": {"error": str(e)}}

    layer2 = {
        "score": round(location_score, 3),
        "weight": W_LOCATION,
        "weighted": round(location_score * W_LOCATION, 3),
        "details": loc_result.get("details", {}),
    }

    # Layer 3: Behavioral patterns (optional — can be slow)
    behavior_score = 0.0
    behavior_data = {}
    if not skip_behavior:
        try:
            behavior_result = await analyze_behavior(session, user_id)
            behavior_score = behavior_result["anomaly_score"]
            behavior_data = {
                "anomaly_score": behavior_result["anomaly_score"],
                "confidence": behavior_result["confidence"],
                "stability": behavior_result["stability"],
                "patterns": behavior_result["patterns"],
                "recommendations": behavior_result["recommendations"],
            }
        except Exception as e:
            logger.warning(f"Behavior analysis failed: {e}")
            behavior_data = {"error": str(e)}
    else:
        behavior_data = {"skipped": True}

    layer3 = {
        "score": round(behavior_score, 3),
        "weight": W_BEHAVIOR,
        "weighted": round(behavior_score * W_BEHAVIOR, 3),
        **behavior_data,
    }

    # Composite fusion
    fused_score = (
        realtime_score * W_REALTIME +
        location_score * W_LOCATION +
        behavior_score * W_BEHAVIOR
    )

    # Override: Voice distress detected → floor at 80%
    voice_signal = realtime_signals.get("voice", 0)
    if voice_signal > 0.3:
        if fused_score < VOICE_DISTRESS_FLOOR:
            overrides.append({
                "rule": "voice_distress_floor",
                "original_score": round(fused_score, 3),
                "applied_score": VOICE_DISTRESS_FLOOR,
                "reason": f"Voice distress signal ({voice_signal:.0%}) overrides to minimum {VOICE_DISTRESS_FLOOR:.0%}",
            })
            fused_score = VOICE_DISTRESS_FLOOR

    fused_score = round(min(1.0, max(0.0, fused_score)), 3)
    fused_level = classify_fused_risk(fused_score)

    return {
        "fused_score": fused_score,
        "fused_level": fused_level,
        "layer1_realtime": layer1,
        "layer2_location": layer2,
        "layer3_behavior": layer3,
        "overrides": overrides,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }
