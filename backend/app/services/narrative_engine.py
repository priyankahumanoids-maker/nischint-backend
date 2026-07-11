# AI Incident Narrative Engine
# Two-stage generation: Facts Pack → AI Narrative (with schema enforcement + template fallback)
# Immutable, versioned, auditable narrative log.

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

NARRATIVE_MODEL = "gpt-5.2"
NARRATIVE_PROVIDER = "openai"

NARRATIVE_SCHEMA = {
    "title": str,
    "one_line_summary": str,
    "what_happened": list,
    "why_it_happened": list,
    "evidence": list,
    "recommended_actions": list,
    "confidence": float,
    "safety_note": (str, type(None)),
}

SYSTEM_PROMPT = """You are an AI safety analyst for NISCHINT, an elderly and child care monitoring platform.
Your role: convert raw incident data into clear, actionable narratives for operators.

STRICT RULES:
- Use ONLY the provided facts JSON. Do NOT invent or assume any information.
- If information is missing, say "unknown" or "data not available".
- Cite evidence entries by their timestamps.
- Output MUST be valid JSON matching the exact schema below.
- Be concise, professional, and action-oriented.
- Prioritize safety-critical information first.

OUTPUT JSON SCHEMA (follow exactly):
{
  "title": "Brief incident title (max 15 words)",
  "one_line_summary": "One sentence summary of what happened and current status",
  "what_happened": ["Bullet 1: chronological event", "Bullet 2: ..."],
  "why_it_happened": ["Bullet 1: contributing factor or root cause indicator", "..."],
  "evidence": [{"timestamp": "ISO timestamp", "fact": "What was observed at this time"}],
  "recommended_actions": [{"priority": 1, "action": "What to do", "owner": "operator|guardian|system"}],
  "confidence": 0.85,
  "safety_note": "Any safety caveat or null if confident"
}"""


async def build_facts_pack(session: AsyncSession, incident_id: str) -> dict | None:
    """
    Assemble a deterministic facts-only JSON from all relevant tables.
    No interpretation -- just raw facts for the AI to narrate.
    """
    # 1. Incident core data from `incidents` table joined with device + senior
    incident = (await session.execute(text("""
        SELECT i.id, i.device_id, i.incident_type, i.severity,
               i.escalation_level, i.status, i.acknowledged_at, i.resolved_at,
               i.created_at, i.is_test, i.escalated, i.escalated_at,
               d.device_identifier, s.full_name AS senior_name
        FROM incidents i
        JOIN devices d ON i.device_id = d.id
        JOIN seniors s ON i.senior_id = s.id
        WHERE i.id = :iid
    """), {"iid": incident_id})).fetchone()

    if not incident:
        return None

    device_id = incident.device_id
    created_at = incident.created_at

    facts = {
        "incident": {
            "id": str(incident.id),
            "device_identifier": incident.device_identifier,
            "senior_name": incident.senior_name,
            "incident_type": incident.incident_type,
            "severity": incident.severity,
            "escalation_level": incident.escalation_level,
            "status": incident.status,
            "escalated": incident.escalated,
            "escalated_at": incident.escalated_at.isoformat() if incident.escalated_at else None,
            "acknowledged_at": incident.acknowledged_at.isoformat() if incident.acknowledged_at else None,
            "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else None,
            "created_at": created_at.isoformat(),
            "is_test": incident.is_test,
        },
        "mode": "test" if incident.is_test else "live",
    }

    # 2. Audit trail from incident_events table
    event_rows = (await session.execute(text("""
        SELECT event_type, event_channel, event_metadata, created_at
        FROM incident_events
        WHERE incident_id = :iid
        ORDER BY created_at ASC
        LIMIT 20
    """), {"iid": incident_id})).fetchall()

    facts["audit_trail"] = [
        {
            "event_type": e.event_type,
            "channel": e.event_channel,
            "metadata": e.event_metadata if isinstance(e.event_metadata, dict) else {},
            "timestamp": e.created_at.isoformat(),
        }
        for e in event_rows
    ]

    # 3. Device health anomalies around incident time (+/- 30 min window)
    anomaly_window_start = created_at - timedelta(minutes=30)
    anomaly_window_end = created_at + timedelta(minutes=30)

    anomalies = (await session.execute(text("""
        SELECT metric, score, reason_json, created_at
        FROM device_anomalies
        WHERE device_id = :did
          AND created_at BETWEEN :start AND :end
        ORDER BY created_at
        LIMIT 20
    """), {"did": device_id, "start": anomaly_window_start, "end": anomaly_window_end})).fetchall()

    facts["device_anomalies"] = [
        {
            "metric": a.metric,
            "score": float(a.score),
            "reason": a.reason_json if isinstance(a.reason_json, dict) else {},
            "timestamp": a.created_at.isoformat(),
        }
        for a in anomalies
    ]

    # 4. Behavior anomalies
    behavior_anomalies = (await session.execute(text("""
        SELECT behavior_score, anomaly_type, reason, created_at
        FROM behavior_anomalies
        WHERE device_id = :did
          AND created_at BETWEEN :start AND :end
          AND is_simulated = false
        ORDER BY created_at DESC
        LIMIT 10
    """), {"did": device_id, "start": anomaly_window_start, "end": anomaly_window_end})).fetchall()

    facts["behavior_anomalies"] = [
        {
            "score": float(b.behavior_score),
            "type": b.anomaly_type,
            "reason": b.reason,
            "timestamp": b.created_at.isoformat(),
        }
        for b in behavior_anomalies
    ]

    # 5. Digital Twin context
    twin = (await session.execute(text("""
        SELECT confidence_score, wake_hour, sleep_hour, peak_activity_hour,
               typical_inactivity_max_minutes, profile_summary
        FROM device_digital_twins
        WHERE device_id = :did
    """), {"did": device_id})).fetchone()

    if twin:
        facts["digital_twin"] = {
            "confidence": round(twin.confidence_score, 3),
            "wake_hour": twin.wake_hour,
            "sleep_hour": twin.sleep_hour,
            "peak_activity": twin.peak_activity_hour,
            "max_inactivity_minutes": twin.typical_inactivity_max_minutes,
            "personality_tag": (twin.profile_summary or {}).get("personality_tag"),
        }
    else:
        facts["digital_twin"] = None

    # 6. Predictive signals
    predictions = (await session.execute(text("""
        SELECT prediction_type, prediction_score, prediction_window_hours,
               confidence, explanation
        FROM predictive_risks
        WHERE device_id = :did AND is_active = true
        ORDER BY prediction_score DESC
        LIMIT 5
    """), {"did": device_id})).fetchall()

    facts["predictive_signals"] = [
        {
            "type": p.prediction_type,
            "score": round(p.prediction_score, 3),
            "window_hours": p.prediction_window_hours,
            "confidence": round(p.confidence, 3),
            "explanation": p.explanation,
        }
        for p in predictions
    ]

    # 7. Recent telemetry snapshot
    recent_telemetry = (await session.execute(text("""
        SELECT metric_value, created_at
        FROM telemetries
        WHERE device_id = :did AND metric_type = 'heartbeat' AND is_simulated = false
        ORDER BY created_at DESC
        LIMIT 5
    """), {"did": device_id})).fetchall()

    facts["recent_telemetry"] = [
        {
            "battery": t.metric_value.get("battery_level") if isinstance(t.metric_value, dict) else None,
            "signal": t.metric_value.get("signal_strength") if isinstance(t.metric_value, dict) else None,
            "timestamp": t.created_at.isoformat(),
        }
        for t in recent_telemetry
    ]

    return facts


def compute_input_hash(facts: dict) -> str:
    """Deterministic hash of the facts pack to detect staleness."""
    serialized = json.dumps(facts, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()[:32]


async def generate_narrative(facts: dict) -> dict:
    """
    Two-stage narrative generation:
    Stage A: Build deterministic facts summary
    Stage B: AI generates human-readable narrative
    Fallback: Template narrative if AI fails
    """
    # Stage A: Deterministic template (always built as fallback)
    template_narrative = _build_template_narrative(facts)

    # Stage B: AI generation
    try:
        ai_narrative = await _generate_ai_narrative(facts)
        if ai_narrative and _validate_narrative_schema(ai_narrative):
            return ai_narrative
        logger.warning("AI narrative failed schema validation, using template fallback")
    except Exception as e:
        logger.warning(f"AI narrative generation failed: {e}, using template fallback")

    return template_narrative


async def _generate_ai_narrative(facts: dict) -> dict | None:
    """Call GPT-5.2 to generate narrative from facts pack."""
    from emergentintegrations.llm.chat import LlmChat, UserMessage

    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        # Fallback to config
        from app.core.config import settings
        api_key = settings.emergent_llm_key
    if not api_key:
        logger.warning("EMERGENT_LLM_KEY not set, skipping AI generation")
        return None

    chat = LlmChat(
        api_key=api_key,
        session_id=f"narrative-{uuid.uuid4().hex[:8]}",
        system_message=SYSTEM_PROMPT,
    ).with_model(NARRATIVE_PROVIDER, NARRATIVE_MODEL)

    user_prompt = f"""Generate an incident narrative from the following facts pack.
Return ONLY valid JSON matching the schema in your instructions. No markdown, no explanation, just JSON.

FACTS PACK:
{json.dumps(facts, indent=2, default=str)}"""

    from app.services.ai_metrics import track
    async with track("narrative_engine.compose"):
        response = await chat.send_message(UserMessage(text=user_prompt))

    # Parse JSON from response - handle various wrapping formats
    response_text = response.strip()

    # Handle markdown code blocks (```json ... ``` or ``` ... ```)
    if "```" in response_text:
        # Extract content between first ``` and last ```
        parts = response_text.split("```")
        if len(parts) >= 3:
            inner = parts[1]
            # Remove language identifier if present (e.g., "json\n")
            if inner.startswith("json"):
                inner = inner[4:]
            response_text = inner.strip()

    # Try to find JSON object in the response
    start_idx = response_text.find("{")
    end_idx = response_text.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        response_text = response_text[start_idx:end_idx + 1]

    return json.loads(response_text)


def _validate_narrative_schema(narrative: dict) -> bool:
    """Validate that the narrative matches the expected schema."""
    required_keys = ["title", "one_line_summary", "what_happened", "why_it_happened",
                     "evidence", "recommended_actions", "confidence"]
    for key in required_keys:
        if key not in narrative:
            return False
    if not isinstance(narrative["what_happened"], list):
        return False
    if not isinstance(narrative["evidence"], list):
        return False
    if not isinstance(narrative["recommended_actions"], list):
        return False
    if not isinstance(narrative.get("confidence", 0), (int, float)):
        return False
    return True


def _build_template_narrative(facts: dict) -> dict:
    """
    Deterministic template fallback -- no AI needed.
    Builds a structured narrative from raw facts.
    """
    inc = facts["incident"]
    device = inc["device_identifier"]
    incident_type = inc["incident_type"]
    severity = inc["severity"]
    status = inc["status"]
    esc_level = inc.get("escalation_level", 1)
    created = inc["created_at"]

    # What happened
    what_happened = [
        f"{severity.upper()} {incident_type.replace('_', ' ')} incident detected on device {device} at {created}",
    ]
    if esc_level and esc_level > 1:
        what_happened.append(f"Escalated to level {esc_level}")
    if inc.get("acknowledged_at"):
        what_happened.append(f"Acknowledged at {inc['acknowledged_at']}")
    if inc.get("resolved_at"):
        what_happened.append(f"Resolved at {inc['resolved_at']}")
    if inc.get("is_test"):
        what_happened.append("[TEST MODE] This is a test incident")

    for a in facts.get("audit_trail", [])[:5]:
        what_happened.append(f"{a['event_type']}: {a.get('channel', '-')} at {a['timestamp']}")

    # Why it happened
    why = []
    for anom in facts.get("device_anomalies", [])[:3]:
        reason = anom.get("reason", {})
        if isinstance(reason, dict) and reason.get("type"):
            why.append(f"{anom['metric']} anomaly (score {anom['score']:.0f}): {reason.get('type', 'unknown')}")
        else:
            why.append(f"{anom['metric']} anomaly detected with score {anom['score']:.0f}")

    for b in facts.get("behavior_anomalies", [])[:2]:
        why.append(f"Behavioral anomaly: {b['type']} (score {b['score']:.2f}) -- {str(b['reason'])[:80]}")

    twin = facts.get("digital_twin")
    if twin:
        why.append(f"Digital Twin ({twin.get('personality_tag', 'profile')}, confidence {twin['confidence']:.0%})")

    if not why:
        why.append("Root cause analysis requires more data")

    # Evidence
    evidence = [
        {"timestamp": created, "fact": f"Incident {incident_type} created with severity {severity}"}
    ]
    for anom in facts.get("device_anomalies", [])[:3]:
        evidence.append({"timestamp": anom["timestamp"], "fact": f"{anom['metric']} score: {anom['score']:.0f}"})
    for b in facts.get("behavior_anomalies", [])[:2]:
        evidence.append({"timestamp": b["timestamp"], "fact": f"Behavior: {b['type']} (score {b['score']:.2f})"})

    # Actions
    actions = []
    if status != "resolved":
        actions.append({"priority": 1, "action": f"Verify device {device} status and user safety", "owner": "operator"})
        if esc_level and esc_level >= 2:
            actions.append({"priority": 1, "action": "Contact guardian immediately", "owner": "operator"})
        actions.append({"priority": 2, "action": "Review device telemetry for ongoing issues", "owner": "operator"})
    else:
        actions.append({"priority": 3, "action": "Archive -- incident resolved", "owner": "system"})

    # Predictive context
    for p in facts.get("predictive_signals", [])[:2]:
        if p["score"] >= 0.7:
            actions.append({"priority": 2, "action": f"Monitor: {p['explanation'][:60]} (predicted in {p['window_hours']}h)", "owner": "operator"})

    confidence = 0.6 if len(facts.get("device_anomalies", [])) > 0 else 0.4
    if twin:
        confidence = min(1.0, confidence + 0.1)

    safety_note = None
    if inc.get("is_test"):
        safety_note = "This narrative is based on test data and should not be used for real safety decisions."
    elif confidence < 0.5:
        safety_note = "Limited data available -- narrative confidence is low. Manual verification recommended."

    return {
        "title": f"{severity.title()} {incident_type.replace('_', ' ').title()} on {device}",
        "one_line_summary": f"A {severity} {incident_type.replace('_', ' ')} incident was detected on {device}, currently {status}" +
                            (f" at escalation level {esc_level}" if esc_level else ""),
        "what_happened": what_happened,
        "why_it_happened": why,
        "evidence": evidence,
        "recommended_actions": actions,
        "confidence": round(confidence, 2),
        "safety_note": safety_note,
    }
