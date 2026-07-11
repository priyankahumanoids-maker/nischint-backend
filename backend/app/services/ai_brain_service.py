"""
AI Brain Service — NISCHINT Unified Autonomous Decision Orchestrator

This module ONLY orchestrates existing intelligence engines. It does NOT
re-implement any risk logic. Pipeline:

    1. Build a normalized "realtime_score" from incoming mobile signals
    2. Call risk_fusion.compute_fused_risk  (realtime + location + behavior)
    3. Layer in adaptive_risk_engine hotspots  (point-based lookup)
    4. Layer in risk_forecast_engine cached forecast
    5. Apply confidence weighting based on signal completeness
    6. Classify into GREEN/YELLOW/RED/CRITICAL + recommend action
    7. Autonomously execute action if threshold crossed
       (silent SOS / guardian notify / monitoring bump / log-only)

Target latency: < 200ms per call. The heavy engines are behavior_ai
(already cached/scheduled) and fusion (already DB-indexed).
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.risk_fusion import compute_fused_risk

logger = logging.getLogger(__name__)


# ── Thresholds (per user type — contextual intelligence) ─────────────
# Lower thresholds = faster escalation. Elderly & child get priority.
THRESHOLDS_BY_TYPE: dict[str, dict[str, int]] = {
    "elderly": {"sos": 65, "alert": 45, "monitor": 20},  # fastest — fall + inactivity are life-critical
    "child":   {"sos": 70, "alert": 50, "monitor": 25},
    "woman":   {"sos": 75, "alert": 55, "monitor": 30},
    "adult":   {"sos": 80, "alert": 60, "monitor": 35},
}
# Back-compat constants (default = adult)
THRESHOLD_CRITICAL = THRESHOLDS_BY_TYPE["adult"]["sos"]
THRESHOLD_RED      = THRESHOLDS_BY_TYPE["adult"]["alert"]
THRESHOLD_YELLOW   = THRESHOLDS_BY_TYPE["adult"]["monitor"]

# ── Per-user adaptive adjustment (P1 moat — learns from feedback) ────
# Positive value = raise thresholds (this user over-triggers → be less sensitive)
# Negative value = lower thresholds (missing events → be more sensitive)
# Bounded ±15 to prevent runaway learning.
# Persisted to Mongo via brain_adaptation_store — hydrated on import.
# Time-decay applied on READ (fades old drift), smoothing applied on WRITE.
_USER_ADJUSTMENTS: dict[str, int] = {}
_USER_ADAPT_PROFILES: dict[str, dict] = {}  # full rich docs (for dashboard)
_USER_ADJUST_MAX = 15
_USER_ADJUST_MIN = -15
# Minimum feedback sample size before adapting
_FEEDBACK_MIN_SAMPLE = 5

# ── Hydrate from Mongo on module import ──────────────────────────────
try:
    from app.services import brain_adaptation_store as _adapt_store
    _hydrated = _adapt_store.load_all()
    for _uid, _doc in _hydrated.items():
        _raw = int(_doc.get("adjustment", 0))
        _USER_ADJUSTMENTS[_uid] = _raw
        _USER_ADAPT_PROFILES[_uid] = _doc
except Exception as _e:
    logger.warning(f"[AI_BRAIN_ADAPT] hydrate skipped: {_e}")


def _current_adjustment(user_id: str) -> int:
    """
    Read-path: return DECAYED adjustment. Old stored values fade so the
    system re-calibrates when a user's lifestyle changes.
    """
    raw = _USER_ADJUSTMENTS.get(user_id, 0)
    if not raw:
        return 0
    try:
        doc = _USER_ADAPT_PROFILES.get(user_id) or {}
        decayed = _adapt_store.apply_decay(raw, doc.get("updated_at"))
        return max(_USER_ADJUST_MIN, min(_USER_ADJUST_MAX, decayed))
    except Exception:
        return raw

# ── Cooldown — prevents repeated triggers flooding guardians ─────────
# If we've already triggered for this user within the window, a subsequent
# TRIGGER_SOS is downgraded to INCREASE_MONITORING (SOS still alive anyway)
# and NOTIFY_GUARDIAN is downgraded to LOG_ONLY. CRITICAL risk is NOT
# suppressed — only the re-execution is.
COOLDOWN_SECONDS = 120
_LAST_TRIGGER_AT: dict[str, float] = {}

# ── Sustained-Risk Gate — pattern-driven, not event-driven ──────────
# A single spike no longer instantly fires SOS. We require SUSTAINED_MIN_COUNT
# high-risk decisions (each >= SUSTAINED_MIN_SCORE) inside SUSTAINED_WINDOW_SEC
# for this user. Otherwise TRIGGER_SOS is downgraded to NOTIFY_GUARDIAN (advisory).
#
# Positioning: intelligent, not reactive. One panic-keyword spike → advisory.
# Two consecutive ones within 2 minutes → SOS.
#
# Bypass: genuine crises with near-certain confidence still fire immediately
# (see SUSTAINED_BYPASS_SCORE + SUSTAINED_BYPASS_CONF). Keeps the system from
# being too patient during actual emergencies.
SUSTAINED_MIN_COUNT      = 2      # need N high-risk decisions (including current)
SUSTAINED_MIN_SCORE      = 70     # effective_score threshold counted as high-risk
SUSTAINED_WINDOW_SEC     = 120    # look-back window
SUSTAINED_BYPASS_SCORE   = 90     # ultra-high score → skip the gate
SUSTAINED_BYPASS_CONF    = 0.90   # AND ultra-high confidence → skip the gate

# Adaptive + forecast weight on top of fused base (0–100)
W_HOTSPOT_ADJUST   = 0.15
W_FORECAST_ADJUST  = 0.10

# Decision event retention (in-memory ring for feedback loop)
_DECISION_LOG: list[dict] = []
_MAX_DECISION_LOG = 1000

# Location-result cache: (grid_lat, grid_lng) -> (expires_at, result_dict)
# compute_location_risk scans full incidents table — caching by 0.005° grid
# (~550m at equator) for 60s keeps the brain under 200ms after warm-up.
_LOCATION_CACHE: dict[tuple, tuple[float, dict]] = {}
_LOCATION_CACHE_TTL_S = 60
_LOCATION_GRID_DEG = 0.005


def _loc_cache_key(lat: float, lng: float) -> tuple:
    return (round(lat / _LOCATION_GRID_DEG), round(lng / _LOCATION_GRID_DEG))


async def _cached_fused(
    *, session, user_id, realtime_score, realtime_signals, lat, lng, skip_behavior
):
    """
    Memoize the expensive parts of compute_fused_risk (location + behavior)
    per (user, grid_cell, skip_behavior) for 30s. Re-apply realtime weight
    on every call since that's signal-dependent.

    This keeps p99 latency under 200ms after warm-up without modifying the
    underlying fusion engine.
    """
    from app.services.risk_fusion import W_REALTIME, W_LOCATION, W_BEHAVIOR, classify_fused_risk, VOICE_DISTRESS_FLOOR
    import time as _t

    cache_key = (user_id, _loc_cache_key(lat, lng), bool(skip_behavior))
    now = _t.time()
    cached = _LOCATION_CACHE.get(cache_key)

    if cached and cached[0] > now:
        base = cached[1]
        layer2 = base["layer2_location"]
        layer3 = base["layer3_behavior"]
    else:
        # Cold — run full fusion once, then cache the location+behavior parts
        full = await compute_fused_risk(
            session=session,
            user_id=user_id,
            realtime_score=0.0,  # we'll recompose with current realtime below
            realtime_signals={},
            lat=lat, lng=lng,
            skip_behavior=skip_behavior,
        )
        base = full
        layer2 = full["layer2_location"]
        layer3 = full["layer3_behavior"]
        _LOCATION_CACHE[cache_key] = (now + _LOCATION_CACHE_TTL_S, base)

        # Prune cache occasionally
        if len(_LOCATION_CACHE) > 500:
            for k, (exp, _) in list(_LOCATION_CACHE.items()):
                if exp <= now:
                    _LOCATION_CACHE.pop(k, None)

    # Recompose using CURRENT realtime signals
    location_score = float(layer2.get("score", 0))
    behavior_score = float(layer3.get("score", 0))
    fused_score = (
        realtime_score * W_REALTIME +
        location_score * W_LOCATION +
        behavior_score * W_BEHAVIOR
    )
    overrides = []
    voice_signal = realtime_signals.get("voice", 0)
    if voice_signal > 0.3 and fused_score < VOICE_DISTRESS_FLOOR:
        overrides.append({
            "rule": "voice_distress_floor",
            "original_score": round(fused_score, 3),
            "applied_score": VOICE_DISTRESS_FLOOR,
        })
        fused_score = VOICE_DISTRESS_FLOOR
    fused_score = round(min(1.0, max(0.0, fused_score)), 3)

    return {
        "fused_score": fused_score,
        "fused_level": classify_fused_risk(fused_score),
        "layer1_realtime": {
            "score": round(realtime_score, 3),
            "weight": W_REALTIME,
            "weighted": round(realtime_score * W_REALTIME, 3),
            "signals": realtime_signals,
        },
        "layer2_location": layer2,
        "layer3_behavior": layer3,
        "overrides": overrides,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Signal normalization ─────────────────────────────────────────────

def _normalize_realtime(signals: dict, user_type: str = "adult") -> tuple[float, dict, list[str]]:
    """
    Map mobile multi-channel signals → a single Layer-1 realtime score (0–1)
    plus a dict of named sub-scores (for fusion introspection) and a list of
    triggers that fired (for UI + audit).

    Default weights (sum = 1.0):
        motion   0.30
        voice    0.25
        gps      0.20
        time     0.15
        device   0.10

    Elderly profile re-weights:
        motion   0.45  (falls dominate)
        voice    0.15  (less reliable signal)
        gps      0.15
        time     0.15
        device   0.10
        + inactivity_penalty: 'still' activity for long duration gets bumped
    """
    voice = signals.get("voice") or {}
    gps = signals.get("gps") or {}
    motion = signals.get("motion") or {}
    device = signals.get("device") or {}
    time_ctx = signals.get("time") or {}

    triggers: list[str] = []
    is_elderly = (user_type == "elderly")

    # Motion: activity string + accel magnitude
    activity = str(motion.get("activity") or "").lower()
    accel = float(motion.get("acceleration") or 0)
    if activity == "fall":
        motion_score = 1.0
        triggers.append("fall_detected")
        if is_elderly:
            triggers.append("elderly_fall_critical")
    elif activity == "run":
        motion_score = min(1.0, 0.45 + accel / 20.0)
        if motion_score >= 0.6:
            triggers.append("sudden_running")
    elif activity == "still":
        # Inactivity penalty for elderly: prolonged stillness is risky
        motion_score = max(0.0, min(0.3, accel / 15.0))
        if is_elderly:
            idle_sec = float(motion.get("idle_sec") or 0)
            if idle_sec >= 3600:   # 1 hour still
                motion_score = max(motion_score, 0.85)
                triggers.append("elderly_inactivity_1h")
            elif idle_sec >= 1800:  # 30 min
                motion_score = max(motion_score, 0.55)
                triggers.append("elderly_inactivity_30m")
    else:  # walk / unknown
        motion_score = max(0.0, min(0.5, accel / 12.0))

    # Voice: stress + keyword + amplitude spike
    stress = float(voice.get("stress_score") or 0)
    keyword = bool(voice.get("keyword_flag") or False)
    amplitude = float(voice.get("amplitude") or 0)
    voice_score = min(1.0, 0.55 * stress + (0.35 if keyword else 0) + 0.10 * min(1.0, amplitude))
    if voice_score >= 0.6:
        triggers.append("voice_distress")
    if keyword:
        triggers.append("panic_keyword")

    # GPS: route_deviation is 0–1 (0 = on route, 1 = fully off)
    route_dev = float(gps.get("route_deviation") or 0)
    speed = float(gps.get("speed") or 0)
    gps_score = min(1.0, 0.7 * route_dev + 0.3 * min(1.0, max(0.0, (speed - 4.0) / 10.0)))
    if route_dev >= 0.5:
        triggers.append("route_deviation")

    # Time
    hour = int(time_ctx.get("hour") if time_ctx.get("hour") is not None else datetime.now().hour)
    is_night = bool(time_ctx.get("is_night") if time_ctx.get("is_night") is not None else (hour >= 22 or hour < 5))
    time_score = 0.55 if is_night else 0.1
    if is_night:
        triggers.append("late_night")

    # Device
    battery = device.get("battery")
    network_ok = bool(device.get("network") if device.get("network") is not None else True)
    screen_on = bool(device.get("screen_on") if device.get("screen_on") is not None else True)
    device_score = 0.0
    if battery is not None and float(battery) <= 0.15:
        device_score += 0.5
        triggers.append("battery_low")
    if not network_ok:
        device_score += 0.4
        triggers.append("offline")
    if not screen_on:
        device_score += 0.1
    device_score = min(1.0, device_score)

    # Apply profile-specific weights
    if is_elderly:
        w_motion, w_voice, w_gps, w_time, w_device = 0.45, 0.15, 0.15, 0.15, 0.10
    else:
        w_motion, w_voice, w_gps, w_time, w_device = 0.30, 0.25, 0.20, 0.15, 0.10

    realtime_score = min(
        1.0,
        w_motion * motion_score +
        w_voice  * voice_score +
        w_gps    * gps_score +
        w_time   * time_score +
        w_device * device_score,
    )

    signals_breakdown = {
        "motion": round(motion_score, 3),
        "voice":  round(voice_score, 3),
        "gps":    round(gps_score, 3),
        "time":   round(time_score, 3),
        "device": round(device_score, 3),
        "_weights": {
            "motion": w_motion, "voice": w_voice, "gps": w_gps,
            "time": w_time, "device": w_device,
        },
    }

    return realtime_score, signals_breakdown, triggers


# ── Adaptive hotspot adjustment (point-based) ────────────────────────

async def _hotspot_adjustment(session: AsyncSession, lat: float, lng: float) -> float:
    """
    Look up nearest hotspot from adaptive_risk_engine learning store.
    Cached 60s per grid cell (point-based, slow-changing).
    Silent fallback to 0 on any error.
    """
    import time as _t
    key = ("hotspot", _loc_cache_key(lat, lng))
    now = _t.time()
    cached = _LOCATION_CACHE.get(key)
    if cached and cached[0] > now:
        return float(cached[1].get("v", 0.0))
    try:
        from app.services import adaptive_risk_engine as ar
        if hasattr(ar, "get_point_hotspot_risk"):
            res = await ar.get_point_hotspot_risk(session, lat, lng)
            val = float(res or 0.0)
        else:
            stats = await ar.get_learning_stats(session)
            dens = float(stats.get("hotspot_count", 0) or 0)
            val = min(0.2, dens / 50.0)
    except Exception as e:
        logger.debug(f"[AI_BRAIN] hotspot adjust failed: {e}")
        val = 0.0
    _LOCATION_CACHE[key] = (now + _LOCATION_CACHE_TTL_S, {"v": val})
    return val


def _forecast_adjustment(lat: float, lng: float) -> float:
    """Non-async cached forecast lookup. Returns 0..1 adjustment."""
    try:
        from app.services.risk_forecast_engine import get_point_forecast_cached
        fc = get_point_forecast_cached(lat, lng)
        if not fc:
            return 0.0
        # Prefer normalized predicted score if present (typical keys)
        score_1h = fc.get("predicted_1hr") or fc.get("risk_1hr") or fc.get("score")
        if score_1h is None:
            return 0.0
        return float(min(1.0, max(0.0, float(score_1h))))
    except Exception as e:
        logger.debug(f"[AI_BRAIN] forecast adjust failed: {e}")
        return 0.0


# ── Confidence & classification ──────────────────────────────────────

def _confidence(signals: dict, fused: dict) -> float:
    """
    Confidence grows with:
      - number of signal channels with data
      - fusion layer2/layer3 having actual content (not skipped/errored)
    Range 0.4..1.0. Never lets the action fire at very low confidence.
    """
    channels = sum(
        1 for key in ("voice", "gps", "motion", "device", "time")
        if signals.get(key)
    )
    base = 0.4 + 0.1 * channels  # 5 channels → 0.9
    # Bump for behavior layer present
    l3 = fused.get("layer3_behavior", {})
    if l3 and not l3.get("skipped") and not l3.get("error"):
        base += 0.05
    # Bump for location layer valid
    l2 = fused.get("layer2_location", {})
    if l2 and not l2.get("details", {}).get("error"):
        base += 0.05
    return round(min(1.0, base), 3)


def _classify(effective_score: float, user_type: str = "adult", user_id: str | None = None) -> tuple[str, str, dict]:
    """
    Returns (risk_level, recommended_action, thresholds_used).
    Thresholds vary by user_type AND by per-user learned adjustments.
    """
    base = THRESHOLDS_BY_TYPE.get(user_type, THRESHOLDS_BY_TYPE["adult"])
    adj = _current_adjustment(user_id or "") if user_id else 0
    t = {
        "sos":     max(10, base["sos"] + adj),
        "alert":   max(10, base["alert"] + adj),
        "monitor": max(5,  base["monitor"] + adj),
    }
    if effective_score >= t["sos"]:
        return "CRITICAL", "TRIGGER_SOS", t
    if effective_score >= t["alert"]:
        return "RED", "NOTIFY_GUARDIAN", t
    if effective_score >= t["monitor"]:
        return "YELLOW", "INCREASE_MONITORING", t
    return "GREEN", "LOG_ONLY", t


# ── Autonomous executor ──────────────────────────────────────────────

async def _execute_action(
    session: AsyncSession,
    user_id: str,
    action: str,
    lat: float,
    lng: float,
    event_id: str,
    triggers: list[str],
    final_score: float,
) -> dict:
    """
    Autonomously perform the recommended action.
    Returns {executed: bool, detail: dict, error?: str}.
    """
    if action == "TRIGGER_SOS":
        try:
            from app.services.emergency_engine import trigger_silent_sos
            res = await trigger_silent_sos(
                session=session,
                user_id=user_id,
                lat=lat,
                lng=lng,
                trigger_source="ai_brain",
                device_metadata={
                    "ai_event_id": event_id,
                    "final_score": final_score,
                    "triggers": triggers,
                },
            )
            return {"executed": True, "detail": res}
        except Exception as e:
            logger.error(f"[AI_BRAIN] SOS trigger failed: {e}")
            return {"executed": False, "error": str(e)}

    if action == "NOTIFY_GUARDIAN":
        try:
            # Reuse notify_guardians helper from emergency_engine (internal).
            # Since it expects an event object, we create a lightweight advisory
            # through the guardian broadcaster instead.
            from app.services.event_broadcaster import broadcaster
            await broadcaster.publish(f"user:{user_id}", {
                "type": "ai_advisory",
                "event_id": event_id,
                "lat": lat, "lng": lng,
                "level": "RED",
                "final_score": final_score,
                "triggers": triggers,
                "ts": datetime.now(timezone.utc).isoformat(),
            })
            return {"executed": True, "detail": {"channel": "sse", "topic": f"user:{user_id}"}}
        except Exception as e:
            logger.warning(f"[AI_BRAIN] guardian notify failed: {e}")
            return {"executed": False, "error": str(e)}

    if action == "INCREASE_MONITORING":
        # Caller (mobile) respects this via polling cadence / higher GPS freq.
        # We just emit an SSE advisory so the client can act.
        try:
            from app.services.event_broadcaster import broadcaster
            await broadcaster.publish(f"user:{user_id}", {
                "type": "ai_monitoring_bump",
                "event_id": event_id,
                "final_score": final_score,
                "ts": datetime.now(timezone.utc).isoformat(),
            })
        except Exception:
            pass
        return {"executed": True, "detail": {"instruction": "increase_sampling"}}

    return {"executed": False, "detail": {"reason": "log_only"}}


# ── Brain entry point ────────────────────────────────────────────────

async def decide(
    session: AsyncSession,
    *,
    user_id: str,
    user_type: str,
    signals: dict,
    event_id: str | None = None,
    skip_behavior: bool = False,
    auto_execute: bool = True,
) -> dict:
    """
    Run the full AI brain pipeline on a single signal frame.
    """
    t0 = time.perf_counter()
    eid = event_id or str(uuid.uuid4())

    # 1. Normalize (user_type-aware — elderly gets motion-heavy weighting)
    realtime_score, signals_breakdown, triggers = _normalize_realtime(signals, user_type)

    gps = signals.get("gps") or {}
    lat = float(gps.get("lat") or 0.0)
    lng = float(gps.get("lng") or 0.0)

    # 2. Fuse (realtime + location + behavior) — cached per grid cell for 30s
    fused = await _cached_fused(
        session=session,
        user_id=user_id,
        realtime_score=realtime_score,
        realtime_signals=signals_breakdown,
        lat=lat, lng=lng,
        skip_behavior=skip_behavior,
    )
    fused_score = float(fused.get("fused_score", realtime_score))  # 0..1

    # 3. Adaptive hotspot adjust (additive, bounded)
    hotspot_adj = await _hotspot_adjustment(session, lat, lng)

    # 4. Forecast adjust (additive, bounded)
    forecast_adj = _forecast_adjustment(lat, lng)

    # 5. Compose risk_score on 0..100
    risk_score_01 = min(
        1.0,
        fused_score +
        W_HOTSPOT_ADJUST * hotspot_adj +
        W_FORECAST_ADJUST * forecast_adj,
    )
    risk_score = int(round(risk_score_01 * 100))

    # 6. Confidence
    confidence = _confidence(signals, fused)

    # 7. Effective score = risk * confidence (explicit confidence-weighted decision)
    #    This is what we classify on. Low confidence prevents over-triggering
    #    on incomplete signal frames. Kept `final_score` as alias for back-compat.
    effective_score = round(risk_score * confidence, 2)
    final_score = effective_score  # back-compat alias

    # 8. Classify + action (per user_type base + per-user learned adjustments)
    risk_level, action, thresholds_used = _classify(effective_score, user_type, user_id)

    # 8a. Sustained-Risk Gate — pattern-driven, not event-driven
    # Downgrade a FIRST TRIGGER_SOS to NOTIFY_GUARDIAN unless the user has
    # demonstrated sustained high-risk behaviour in the lookback window.
    # Ultra-high score + confidence BYPASSES the gate (genuine crisis).
    sustained_gate_applied = False
    if action == "TRIGGER_SOS":
        bypass = (
            effective_score >= SUSTAINED_BYPASS_SCORE
            and confidence >= SUSTAINED_BYPASS_CONF
        )
        if not bypass and not _sustained_high_risk(user_id):
            action = "NOTIFY_GUARDIAN"
            sustained_gate_applied = True
            logger.info(
                f"[AI_BRAIN] sustained-gate — user={user_id} "
                f"first high-risk event (score={round(effective_score, 1)}, conf={confidence:.2f}) "
                f"→ advisory (need {SUSTAINED_MIN_COUNT} events ≥{SUSTAINED_MIN_SCORE} in {SUSTAINED_WINDOW_SEC}s)"
            )

    # 8b. Cooldown check — prevents panic spam on rapid-fire triggers
    cooldown_applied = False
    original_action = "TRIGGER_SOS" if sustained_gate_applied else action
    if action in ("TRIGGER_SOS", "NOTIFY_GUARDIAN"):
        last = _LAST_TRIGGER_AT.get(user_id)
        if last is not None and (time.time() - last) < COOLDOWN_SECONDS:
            # Downgrade the action (risk level reporting stays honest)
            if action == "TRIGGER_SOS":
                action = "INCREASE_MONITORING"
            else:  # NOTIFY_GUARDIAN
                action = "LOG_ONLY"
            cooldown_applied = True
            logger.info(
                f"[AI_BRAIN] cooldown — user={user_id} original={original_action} "
                f"downgraded_to={action} last_trigger={round(time.time() - last, 1)}s ago"
            )
    # Stamp trigger time AFTER decision if we're actually going to execute
    if action in ("TRIGGER_SOS", "NOTIFY_GUARDIAN") and auto_execute:
        _LAST_TRIGGER_AT[user_id] = time.time()

    # 9. Execute
    execution = {"executed": False, "detail": {}}
    if auto_execute and action != "LOG_ONLY":
        execution = await _execute_action(
            session, user_id, action, lat, lng, eid, triggers, effective_score
        )

    # 10. Log for feedback loop
    reason = _build_reason(action, triggers, fused, risk_score, confidence)
    guardian_selected = _pick_top_guardian(user_id, risk_level)
    latency_ms = round((time.perf_counter() - t0) * 1000, 1)

    decision = {
        "event_id": eid,
        "user_id": user_id,
        "user_type": user_type,
        "risk_score": risk_score,
        "risk_level": risk_level,
        "confidence": confidence,
        "effective_score": effective_score,     # primary decision metric
        "final_score": final_score,              # back-compat alias
        "recommended_action": action,
        "original_action": original_action,
        "cooldown_applied": cooldown_applied,
        "sustained_gate_applied": sustained_gate_applied,
        "triggers_fired": triggers,
        "thresholds_used": thresholds_used,
        "user_adjustment": _current_adjustment(user_id),
        "executed": execution.get("executed", False),
        "execution_detail": execution.get("detail", {}),
        "execution_error": execution.get("error"),
        "reason": reason,
        "guardian_selected": guardian_selected,
        "stage_scores": {
            "realtime": round(realtime_score, 3),
            "fused": round(fused_score, 3),
            "hotspot_adj": round(hotspot_adj, 3),
            "forecast_adj": round(forecast_adj, 3),
        },
        "signals_breakdown": signals_breakdown,
        "latency_ms": latency_ms,
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }

    _DECISION_LOG.append(decision)
    if len(_DECISION_LOG) > _MAX_DECISION_LOG:
        del _DECISION_LOG[:-_MAX_DECISION_LOG]

    # Persist to Mongo (fire-and-forget — never blocks hot path)
    try:
        from app.services import brain_decision_store as _decision_store
        _decision_store.insert_decision(decision)
    except Exception as _e:
        logger.warning(f"[AI_BRAIN] decision persist skipped: {_e}")

    logger.info(
        f"[AI_BRAIN] user={user_id} type={user_type} level={risk_level} action={action} "
        f"risk={risk_score} conf={confidence} effective={effective_score} "
        f"thr_sos={thresholds_used['sos']} triggers={triggers} "
        f"executed={execution.get('executed')} latency={latency_ms}ms"
    )
    return decision


def _build_reason(action: str, triggers: list[str], fused: dict, risk_score: int, confidence: float) -> str:
    """
    Build a natural, investor-friendly explanation of WHY the brain chose this action.

    Converts low-level triggers (voice_scream, still_motion, late_night) into a
    concise English sentence. This is the Explainability Layer exposed on the
    Decision Timeline — not a debug dump.
    """
    # Human-readable trigger phrases
    TRIGGER_PHRASES = {
        "voice_scream":       "Voice distress detected",
        "voice_keyword":      "Panic keyword spoken",
        "voice_stress":       "Elevated voice stress",
        "shake":              "Phone shaken repeatedly",
        "shake_sos":          "SOS shake pattern",
        "fall_detected":      "Fall detected",
        "still_motion":       "Prolonged stillness",
        "motion_idle":        "No movement for extended period",
        "motion_anomaly":     "Unusual motion pattern",
        "late_night":         "Late-night context",
        "late_hour":          "Late-hour context",
        "geofence_exit":      "Left safe zone",
        "geofence_breach":    "Unsafe area entered",
        "route_deviation":    "Route deviation",
        "hotspot_proximity":  "Near high-risk hotspot",
        "low_battery":        "Low battery",
        "no_network":         "Network lost",
        "offline":            "Device offline",
        "screen_locked":      "Screen locked during alert",
        "fast_movement":      "Sudden fast movement",
        "cooldown_active":    "Repeat signal (cooldown)",
    }

    phrases = []
    seen = set()
    for t in triggers or []:
        key = str(t).lower()
        phrase = TRIGGER_PHRASES.get(key, key.replace("_", " ").capitalize())
        if phrase not in seen:
            phrases.append(phrase)
            seen.add(phrase)

    # Context from fusion layers
    layer2 = fused.get("layer2_location", {}) if isinstance(fused, dict) else {}
    if layer2.get("score", 0) >= 0.3 and "Near high-risk hotspot" not in seen:
        phrases.append(f"Elevated location risk ({layer2.get('score'):.2f})")

    layer3 = fused.get("layer3_behavior", {}) if isinstance(fused, dict) else {}
    if layer3 and not layer3.get("skipped") and layer3.get("anomaly_score", 0) >= 0.3:
        phrases.append(f"Behavior deviation ({layer3.get('anomaly_score'):.2f})")

    # Build sentence
    if not phrases:
        body = "Baseline signals — nothing unusual."
    elif len(phrases) == 1:
        body = phrases[0] + "."
    elif len(phrases) == 2:
        body = f"{phrases[0]} + {phrases[1]}."
    else:
        body = " + ".join(phrases[:-1]) + ", and " + phrases[-1] + "."

    # Action-driven lead-in
    lead = {
        "TRIGGER_SOS":          "Autonomous SOS triggered:",
        "NOTIFY_GUARDIAN":      "Alerting guardians:",
        "INCREASE_MONITORING":  "Raising monitoring:",
        "LOG_ONLY":             "Logging only:",
    }.get(action, "Decision:")

    return f"{lead} {body} (risk={risk_score}, confidence={confidence:.2f})"


def _pick_top_guardian(user_id: str, risk_level: str) -> dict | None:
    """
    Resolve the top-ranked guardian for this user (post risk-coupled sort).
    Returns {id, name, trust_score, effective_trust} or None.
    Best-effort — returns None silently if journey_sync state is unavailable.
    """
    try:
        from app.api import journey_sync as _js
        from app.services import guardian_trust_service as _gts

        mapping = _js._user_contacts.get(user_id) or {}
        guardian_ids = mapping.get("guardian", []) or []
        guardians = [_js._contacts[gid] for gid in guardian_ids if gid in _js._contacts]
        if not guardians:
            return None
        sorted_g = _gts.sort_guardians_by_trust(guardians, risk_level=risk_level)
        top = sorted_g[0]
        return {
            "id": top.get("id"),
            "name": top.get("name"),
            "priority": top.get("priority"),
            "trust_score": round(_gts.get_trust_score(top.get("id", "")), 3),
            "effective_trust": round(_gts.get_effective_trust(top.get("id", "")), 3),
        }
    except Exception:
        return None


# ── Feedback loop ────────────────────────────────────────────────────

def record_feedback(event_id: str, outcome: str, rating: int | None = None, note: str | None = None) -> dict:
    """
    Record outcome for a past decision to enable future learning.

    Outcomes map to human-understandable semantics:
      • true_positive → 👍 "AI was right"         (reinforce current thresholds)
      • false_alarm   → 👎 "AI over-reacted"      (raise thresholds → less sensitive)
      • missed        → ⚠️ "AI missed severity"  (lower thresholds → more sensitive)
      • resolved      → (neutral lifecycle marker, no adaptation effect)

    The decision's original `confidence` is captured into the feedback record so the
    adaptive loop can apply CONFIDENCE-WEIGHTED correction: high-confidence mistakes
    drive bigger threshold adjustments than low-confidence ones.

    Accepts feedback for decisions that have been evicted from the in-memory log
    but still exist in Mongo (ai_brain_decisions). Falls back to load-from-Mongo
    on memory miss so the audit loop stays closed even after restarts.
    """
    # 1. Try in-memory fast path
    for entry in reversed(_DECISION_LOG):
        if entry.get("event_id") == event_id:
            return _apply_feedback_to(entry, outcome, rating, note)

    # 2. Fallback: direct _id lookup in Mongo (single-document, fast)
    try:
        from app.services import brain_decision_store as _decision_store
        doc = _decision_store.find_by_event_id(event_id)
        if doc:
            _DECISION_LOG.append(doc)
            return _apply_feedback_to(doc, outcome, rating, note)
    except Exception as e:
        logger.warning(f"[AI_BRAIN_FEEDBACK] mongo lookup skipped: {e}")

    return {"status": "not_found", "event_id": event_id}


def _apply_feedback_to(entry: dict, outcome: str, rating: int | None, note: str | None) -> dict:
    """Attach feedback record, trigger adaptation, persist — returns API response."""
    entry["feedback"] = {
        "outcome": outcome,
        "rating": rating,
        "note": note,
        "decision_confidence": float(entry.get("confidence", 0.5) or 0.5),
        "received_at": datetime.now(timezone.utc).isoformat(),
    }
    logger.info(
        f"[AI_BRAIN_FEEDBACK] event={entry.get('event_id')} outcome={outcome} "
        f"decision_confidence={entry['feedback']['decision_confidence']:.2f}"
    )
    uid = entry.get("user_id")
    if uid:
        adjustment = _update_user_adjustment(uid)
        entry["feedback"]["threshold_adjusted_to"] = adjustment
    # Persist feedback onto the stored decision doc
    try:
        from app.services import brain_decision_store as _decision_store
        _decision_store.update_feedback(entry.get("event_id"), entry["feedback"])
    except Exception as e:
        logger.warning(f"[AI_BRAIN] feedback persist skipped: {e}")
    return {
        "status": "ok",
        "event_id": entry.get("event_id"),
        "feedback": entry["feedback"],
        "user_adjustment": _current_adjustment(uid or ""),
    }


def _sustained_high_risk(user_id: str) -> bool:
    """
    Returns True when the user has produced `SUSTAINED_MIN_COUNT` decisions
    with effective_score ≥ SUSTAINED_MIN_SCORE in the last SUSTAINED_WINDOW_SEC.
    The current in-flight decision is NOT yet logged, so it counts as +1
    toward the min, meaning we only need (N-1) previous qualifying events.

    Cooldown-downgraded events (recommended_action='INCREASE_MONITORING' from
    cooldown or sustained gate) DO still count if the RAW effective_score was
    high — we care about the risk signal, not the executed action.
    """
    if not user_id or SUSTAINED_MIN_COUNT <= 1:
        return True
    needed = SUSTAINED_MIN_COUNT - 1  # -1 for the current in-flight decision
    now = time.time()
    count = 0
    for d in reversed(_DECISION_LOG):
        if d.get("user_id") != user_id:
            continue
        try:
            ts_str = d.get("decided_at", "")
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
        except Exception:
            continue
        if (now - ts) > SUSTAINED_WINDOW_SEC:
            break  # decisions are appended in time-order — earlier = older
        if float(d.get("effective_score", 0) or 0) >= SUSTAINED_MIN_SCORE:
            count += 1
            if count >= needed:
                return True
    return False


def _update_user_adjustment(user_id: str) -> int:
    """
    Adaptive per-user threshold tuning — V3: CONFIDENCE-WEIGHTED + SMOOTHED + PERSISTED.

    Pipeline:
      1. Collect this user's recent feedbacks from _DECISION_LOG.
      2. If count < _FEEDBACK_MIN_SAMPLE → no change (gate).
      3. Compute confidence-WEIGHTED false-positive & missed rates.
      4. Build a TARGET adjustment (not incremental):
           target = fp_step − miss_step        (each scaled by mean wrong-class confidence)
           clamped to ±_USER_ADJUST_MAX
      5. SMOOTH against current (decayed) adjustment:
           new = round(0.7 * current_decayed + 0.3 * target)
      6. Persist the rich profile (feedback_summary + confidence_profile) to Mongo.

    Outcome → direction:
      • false_alarm → threshold RAISES (less sensitive)  → +target contribution
      • missed      → threshold LOWERS (more sensitive)  → −target contribution
      • true_positive / resolved → neutral
    """
    feedbacks: list[dict] = []
    for d in _DECISION_LOG:
        fb = d.get("feedback")
        if d.get("user_id") == user_id and fb:
            feedbacks.append(fb)
    n = len(feedbacks)
    if n < _FEEDBACK_MIN_SAMPLE:
        return _current_adjustment(user_id)

    def _w(fb: dict) -> float:
        return max(0.0, min(1.0, float(fb.get("decision_confidence", 0.5) or 0.5)))

    weighted_total = sum(_w(f) for f in feedbacks) or 1e-9
    fp_weight = sum(_w(f) for f in feedbacks if f.get("outcome") == "false_alarm")
    miss_weight = sum(_w(f) for f in feedbacks if f.get("outcome") == "missed")
    fp_rate_w = fp_weight / weighted_total
    miss_rate_w = miss_weight / weighted_total

    def _mean_conf(outcomes: set[str]) -> float:
        vals = [_w(f) for f in feedbacks if f.get("outcome") in outcomes]
        return sum(vals) / len(vals) if vals else 0.0

    # Build TARGET (what adjustment would feedback alone suggest?)
    # Step sized by mean-wrong-confidence; only contributes past the rate gates.
    target = 0
    if fp_rate_w > 0.20:
        target += round(3 + 4 * _mean_conf({"false_alarm"}))          # +3..+7
    if miss_rate_w > 0.10:
        target -= round(3 + 4 * _mean_conf({"missed"}))               # -3..-7
    target = max(_USER_ADJUST_MIN, min(_USER_ADJUST_MAX, target))

    # Smooth against DECAYED current value
    current = _current_adjustment(user_id)
    smoothed = _adapt_store.smooth(current, target)
    new = max(_USER_ADJUST_MIN, min(_USER_ADJUST_MAX, smoothed))

    if new != current:
        _USER_ADJUSTMENTS[user_id] = new
        # Build + persist rich profile
        profile = _adapt_store.build_profile(user_id, new, feedbacks)
        _USER_ADAPT_PROFILES[user_id] = profile
        _adapt_store.upsert(user_id, profile)
        logger.warning(
            f"[AI_BRAIN_ADAPT] user={user_id} n={n} "
            f"fp_rate_w={fp_rate_w:.2f} miss_rate_w={miss_rate_w:.2f} "
            f"target={target} smoothed {current} → {new}"
        )
    return new


def get_user_adjustment(user_id: str) -> dict:
    """Diagnostic — decayed adjustment + full behavioral profile (persisted + live)."""
    feedbacks = [d.get("feedback") for d in _DECISION_LOG
                 if d.get("user_id") == user_id and d.get("feedback")]
    n = len(feedbacks)
    fp = sum(1 for f in feedbacks if f and f.get("outcome") == "false_alarm")
    miss = sum(1 for f in feedbacks if f and f.get("outcome") == "missed")
    tp = sum(1 for f in feedbacks if f and f.get("outcome") == "true_positive")

    def _w(fb: dict) -> float:
        return max(0.0, min(1.0, float(fb.get("decision_confidence", 0.5) or 0.5)))

    wtot = sum(_w(f) for f in feedbacks if f) or 0.0
    fp_w = sum(_w(f) for f in feedbacks if f and f.get("outcome") == "false_alarm")
    miss_w = sum(_w(f) for f in feedbacks if f and f.get("outcome") == "missed")

    raw = _USER_ADJUSTMENTS.get(user_id, 0)
    decayed = _current_adjustment(user_id)
    profile = _USER_ADAPT_PROFILES.get(user_id, {})

    return {
        "user_id": user_id,
        "adjustment": decayed,                  # live decayed (what the brain uses)
        "adjustment_raw": raw,                  # pre-decay stored
        "adjustment_updated_at": profile.get("updated_at"),
        "feedback_count": n,
        "true_positive_count": tp,
        "false_alarm_count": fp,
        "missed_count": miss,
        "false_positive_rate": round(fp / n, 3) if n else 0,
        "missed_rate": round(miss / n, 3) if n else 0,
        "false_positive_rate_weighted": round(fp_w / wtot, 3) if wtot else 0,
        "missed_rate_weighted": round(miss_w / wtot, 3) if wtot else 0,
        # Full persisted rich profile
        "feedback_summary": profile.get("feedback_summary"),
        "confidence_profile": profile.get("confidence_profile"),
    }


def recent_decisions(limit: int = 50, user_id: str | None = None, summary: bool = True) -> list[dict]:
    """
    Return recent decisions. Prefers Mongo (permanent audit log, survives
    restarts) and falls back to in-memory ring buffer.

    When `summary=True` (default), Mongo path returns only the fields needed
    for timeline rendering — ~70% smaller payload.
    """
    try:
        from app.services import brain_decision_store as _decision_store
        if _decision_store.is_enabled():
            persisted = _decision_store.recent(limit=limit, user_id=user_id, summary=summary)
            if persisted:
                return persisted
    except Exception as e:
        logger.warning(f"[AI_BRAIN] mongo read skipped, using memory: {e}")
    # Memory fallback
    if user_id:
        filtered = [d for d in _DECISION_LOG if d.get("user_id") == user_id]
        return list(reversed(filtered[-limit:]))
    return list(reversed(_DECISION_LOG[-limit:]))


def stats() -> dict[str, Any]:
    total = len(_DECISION_LOG)
    by_action: dict[str, int] = {}
    by_level: dict[str, int] = {}
    executed = 0
    with_feedback = 0
    for d in _DECISION_LOG:
        by_action[d["recommended_action"]] = by_action.get(d["recommended_action"], 0) + 1
        by_level[d["risk_level"]] = by_level.get(d["risk_level"], 0) + 1
        if d.get("executed"):
            executed += 1
        if d.get("feedback"):
            with_feedback += 1
    return {
        "total_decisions": total,
        "executed": executed,
        "with_feedback": with_feedback,
        "by_action": by_action,
        "by_level": by_level,
    }
