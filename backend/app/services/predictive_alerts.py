# Predictive Alerts Engine
#
# Generates proactive guardian alerts based on behavioral patterns + location risk.
# Confidence tiers:
#   Low (<50)     — dashboard only
#   Medium (50-75) — guardian notification
#   High (>75)    — proactive alert + live monitoring suggestion
#
# Also generates AI safety narratives using GPT-5.2 (Emergent LLM Key).

import os
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.behavior_analyzer import analyze_behavior
from app.services.location_intelligence import compute_location_risk
from app.services.event_broadcaster import broadcaster

logger = logging.getLogger(__name__)


async def generate_safety_narrative(
    behavior_data: dict,
    location_data: dict,
    fused_data: dict | None = None,
) -> str:
    """
    Generate human-readable safety narrative using GPT-5.2.
    The LLM NEVER calculates risk — it only explains algorithmic findings.
    """
    from dotenv import load_dotenv
    load_dotenv()

    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        return _fallback_narrative(behavior_data, location_data, fused_data)

    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage

        chat = LlmChat(
            api_key=api_key,
            session_id=f"narrative-{uuid.uuid4().hex[:8]}",
            system_message=(
                "You are NISCHINT Safety AI, a guardian safety assistant. "
                "Generate a clear, empathetic safety summary for a family guardian. "
                "RULES: 1) Only explain what the algorithm detected — never calculate scores. "
                "2) Be specific about times, counts, and patterns. "
                "3) Suggest actionable steps. "
                "4) Keep it under 150 words. "
                "5) Use a warm but urgent tone appropriate to the risk level."
            ),
        ).with_model("openai", "gpt-5.2")

        # Build context from algorithm outputs
        patterns = behavior_data.get("patterns", [])
        pattern_text = "\n".join(
            f"- {p['type'].replace('_', ' ').title()}: {p.get('count', 0)} events in {p.get('window', 'recent')} window"
            + (f", peak hour: {p.get('peak_hour', '?')}:00" if p.get('peak_hour') is not None else "")
            + f" (severity: {p.get('severity', 'medium')})"
            for p in patterns
        ) or "No significant patterns detected."

        window_text = ""
        for wname, wdata in behavior_data.get("window_data", {}).items():
            window_text += f"\n  {wname} ({wdata['days']}d): wander={wdata['wandering']}, falls={wdata['falls']}, voice={wdata['voice_distress']}, safety={wdata['safety_events']}"

        loc = location_data.get("details", {})
        loc_text = (
            f"Location risk: {location_data.get('score', 0):.0%} "
            f"(incidents nearby: {loc.get('nearby_incidents', 0)}, "
            f"recent: {loc.get('recent_incidents', 0)}, "
            f"time-of-day risk: {loc.get('night_time_risk', 0):.0%})"
        )

        fused_text = ""
        if fused_data:
            fused_text = f"\nOverall fused risk: {fused_data.get('fused_score', 0):.0%} ({fused_data.get('fused_level', 'unknown')})"
            if fused_data.get("overrides"):
                fused_text += f"\nOverrides applied: {', '.join(o['rule'] for o in fused_data['overrides'])}"

        prompt = (
            f"Generate a safety summary for the guardian based on these algorithm findings:\n\n"
            f"BEHAVIORAL PATTERNS:\n{pattern_text}\n"
            f"EVENT COUNTS BY WINDOW:{window_text}\n\n"
            f"LOCATION ANALYSIS:\n{loc_text}\n"
            f"{fused_text}\n\n"
            f"Anomaly score: {behavior_data.get('anomaly_score', 0):.0%}, "
            f"Confidence: {behavior_data.get('confidence', 0):.0%}, "
            f"Stability: {behavior_data.get('stability', 'low')}\n\n"
            f"Recommendations from algorithm: {', '.join(behavior_data.get('recommendations', ['None']))}"
        )

        from app.services.ai_metrics import track
        async with track("predictive_alerts.generate"):
            response = await chat.send_message(UserMessage(text=prompt))
        return response.strip() if response else _fallback_narrative(behavior_data, location_data, fused_data)

    except Exception as e:
        logger.error(f"AI narrative generation failed: {e}")
        return _fallback_narrative(behavior_data, location_data, fused_data)


def _fallback_narrative(behavior_data: dict, location_data: dict, fused_data: dict | None) -> str:
    """Deterministic fallback when GPT is unavailable."""
    parts = []
    patterns = behavior_data.get("patterns", [])

    if not patterns:
        return "No significant behavioral patterns detected in the analysis period. Continue monitoring."

    for p in patterns[:3]:
        ptype = p["type"].replace("_", " ")
        count = p.get("count", 0)
        window = p.get("window", "recent")
        peak = p.get("peak_hour")
        parts.append(f"{ptype.capitalize()}: {count} events in the {window} window" + (f", peaking around {peak}:00" if peak is not None else ""))

    loc_score = location_data.get("score", 0)
    if loc_score > 0.3:
        parts.append(f"Current location has elevated risk ({loc_score:.0%})")

    recommendations = behavior_data.get("recommendations", [])
    if recommendations:
        parts.append("Recommended: " + recommendations[0])

    return ". ".join(parts) + "."


async def evaluate_predictive_alert(
    session: AsyncSession,
    user_id: str,
    lat: float | None = None,
    lng: float | None = None,
) -> dict:
    """
    Run full predictive analysis and generate alert if warranted.

    Returns: {
        alert_level, confidence, stability,
        anomaly_score, narrative,
        patterns, recommendations,
        location_risk, behavior_analysis,
    }
    """
    # Run behavior analysis
    behavior = await analyze_behavior(session, user_id)

    # Run location analysis if coordinates provided
    location = {"score": 0.0, "details": {}}
    if lat is not None and lng is not None:
        location = await compute_location_risk(session, lat, lng)

    # Compute predictive confidence
    anomaly_score = behavior["anomaly_score"]
    confidence = behavior["confidence"]
    stability = behavior["stability"]

    # Determine alert level based on confidence tiers
    confidence_pct = confidence * 100
    if confidence_pct >= 75:
        alert_level = "high"
    elif confidence_pct >= 50:
        alert_level = "medium"
    else:
        alert_level = "low"

    # Generate AI narrative
    narrative = await generate_safety_narrative(behavior, location)

    result = {
        "user_id": user_id,
        "alert_level": alert_level,
        "anomaly_score": anomaly_score,
        "confidence": confidence,
        "confidence_pct": round(confidence_pct),
        "stability": stability,
        "narrative": narrative,
        "patterns": behavior["patterns"],
        "recommendations": behavior["recommendations"],
        "window_data": behavior["window_data"],
        "location_risk": location,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Broadcast SSE for medium+ alerts
    if alert_level in ("medium", "high") and anomaly_score > 0.2:
        sse_data = {
            "user_id": user_id,
            "alert_level": alert_level,
            "anomaly_score": anomaly_score,
            "confidence": confidence,
            "stability": stability,
            "narrative": narrative[:200],
            "patterns": behavior["patterns"][:3],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await broadcaster.broadcast_to_user(user_id, "predictive_safety_alert", sse_data)
        await broadcaster.broadcast_to_operators("predictive_safety_alert", sse_data)

        logger.warning(
            f"Predictive alert: user={user_id}, level={alert_level}, "
            f"anomaly={anomaly_score:.2f}, confidence={confidence:.2f}"
        )

    return result
