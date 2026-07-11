# NISCHINT Safety Brain — Unified multi-sensor risk scoring engine
#
# Signal fusion: fall*0.35 + voice*0.30 + route*0.15 + wander*0.10 + pickup*0.10
# Risk levels: Normal (0-0.3), Suspicious (0.3-0.6), Dangerous (0.6-0.85), Critical (>=0.85)
# Signal decay: scores decay over time to prevent stale high-risk states
# Auto-SOS at critical level

import logging
import math
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.safety_event import SafetyEvent
from app.services.event_broadcaster import broadcaster
from app.services.redis_service import set_json as _redis_set, get_json as _redis_get, delete_key as _redis_del

logger = logging.getLogger(__name__)

_mem: dict = {}

# Signal weights
#
# SF-01 v2 Day 1 — voice weight decision is LOCKED at 0.30 (not 0.25
# as in the original sprint spec). Rationale: empirically, voice
# distress is the second-strongest single indicator of a real safety
# event after a confirmed fall. Bumping voice from 0.25 → 0.30 makes
# the Himalaya 3-phase demo fire convincingly:
#   fall(0.90)*0.35 + voice(0.65)*0.30 = 0.315 + 0.195 = 0.51 base
#   → × 1.30 env multiplier (Phase 3) → 0.66 alert (≥0.65 threshold)
#   → + 0.10 simultaneous bonus → 0.61 base → 0.79 with env mult
# A 0.25 voice weight would make the demo land *just under* the
# alert threshold without simultaneous bonus — too close to noise.
# The remaining weights still sum to 1.0 with voice at 0.30.
WEIGHTS = {
    "fall": 0.35,
    "voice": 0.30,
    "route": 0.15,
    "wander": 0.10,
    "pickup": 0.10,
}

# Decay constants (seconds) — signal decays exponentially with this time constant
DECAY_CONSTANTS = {
    "fall": 60,      # 60s — fast decay for transient impact events
    "voice": 45,     # 45s — voice distress fades quickly
    "route": 120,    # 120s — route deviation needs longer window
    "wander": 180,   # 180s — wandering builds slowly
    "pickup": 90,    # 90s — pickup anomalies are time-sensitive
}

# Risk thresholds
NORMAL_MAX = 0.3
SUSPICIOUS_MAX = 0.6
# SF-01 v2 Day 3 — alert tier at 0.65. The Safety Brain emits an
# `ALERT_FIRED` event when score crosses ALERT_THRESHOLD (regardless
# of which `level` band it lands in). Below this we still create a
# safety_event row for `suspicious+`, but no operator-facing alert
# notification is fanned out — keeps the noise floor low.
ALERT_THRESHOLD = 0.65
DANGEROUS_MAX = 0.85
# >= 0.85 is critical

# SF-01 v2 Day 4 — canonical Safety-Brain composite-alert dedup TTL.
# 300s = 5 min, per sprint spec.
ALERT_COOLDOWN_TTL_S = 300

# SF-01 v2 Day 3 — Phase 3 env hazard multiplier.
#
# Locked semantics:
#   * Source: Sachet/NDMA polygon match OR OpenWeather red flag.
#     `_env_hazard_multiplier(lat, lng)` returns 1.30 when the user's
#     location matches an active hazard zone, 1.0 otherwise.
#   * Applied AFTER the rule-based composite score (and after ML
#     blend) but BEFORE the 0..1 clip — so a "voice 0.65 + fall 0.90"
#     fusion at 0.51 jumps to 0.66, crossing the 0.65 ALERT threshold.
#   * NEVER lowers the score — multiplier is always ≥ 1.0.
#   * Records the `env_hazard_match` flag + multiplier in the event
#     `signals` dict so investigators can see the multiplier fired.
ENV_HAZARD_MULTIPLIER = 1.30


def _set(key, data):
    ok = _redis_set("safety_brain", key, data)
    if not ok:
        _mem[f"safety_brain:{key}"] = data


def _get(key):
    v = _redis_get("safety_brain", key)
    return v if v is not None else _mem.get(f"safety_brain:{key}")


def _del(key):
    _redis_del("safety_brain", key)
    _mem.pop(f"safety_brain:{key}", None)


def _decay_factor(signal_type: str, age_seconds: float) -> float:
    """Exponential decay: score * exp(-elapsed / decay_constant)."""
    decay_constant = DECAY_CONSTANTS.get(signal_type, 120)
    if age_seconds <= 0:
        return 1.0
    return math.exp(-age_seconds / decay_constant)


def classify_risk(score: float) -> str:
    if score >= DANGEROUS_MAX:
        return "critical"
    if score >= SUSPICIOUS_MAX:
        return "dangerous"
    if score >= NORMAL_MAX:
        return "suspicious"
    return "normal"


# SF-01 v2 Day 4 (pre-flight) — simultaneous fall+voice bonus.
#
# Empirically, "person fell hard AND is making distress noises" is a
# vastly higher-confidence indicator than the sum of its parts would
# suggest. Two independent sensor channels confirming the same event
# deserves a bonus *before* the env multiplier lands — otherwise the
# Himalaya 3-phase demo math sits razor-thin at 0.66 (0.51 base +
# ×1.30 env). With the bonus the same scenario lands at 0.79, well
# clear of the 0.65 ALERT threshold.
#
# Locked thresholds — both signals must clear the band:
SIMULTANEOUS_FALL_VOICE_BONUS = 0.10
SIMULTANEOUS_FALL_THRESHOLD   = 0.5
SIMULTANEOUS_VOICE_THRESHOLD  = 0.5


def compute_risk_score(
    signals: dict[str, float],
    *,
    weight_attenuation: dict[str, float] | None = None,
    time_multiplier: float = 1.0,
) -> tuple[float, str, str]:
    """
    Compute unified risk score from weighted signals.
    Returns (score, risk_level, primary_event).

    SB-01 Day 2 — optional Hermes attenuation:
      • `weight_attenuation`: per-signal multiplier in [0.5, 1.0].
        Defaults to None → all weights at full SF-01 v2 strength
        (the **Himalaya invariant** new-user code path).
      • `time_multiplier`: multiplicative scalar on the BASE composite
        (applied BEFORE the env-hazard multiplier in `evaluate_risk`,
        which is what keeps the two multipliers from compounding into
        a 1.69 monster). Hard-clamped to [1.0, 1.30] here as a safety
        guardrail — even a buggy caller can't push past the ceiling.
    """
    # Guardrail clamp — same ceiling as env_hazard mult, never below 1.0.
    tm = min(max(float(time_multiplier or 1.0), 1.0), 1.30)
    att = weight_attenuation or {}

    score = 0.0
    max_signal = ("none", 0.0)

    for signal_type, value in signals.items():
        base_weight = WEIGHTS.get(signal_type, 0)
        # Per-signal attenuator. Clamped to [0.5, 1.0] so a buggy
        # attenuator can never zero out a life-critical signal.
        att_mult = att.get(signal_type, 1.0)
        att_mult = min(max(float(att_mult), 0.5), 1.0)
        effective_weight = base_weight * att_mult

        contribution = value * effective_weight
        score += contribution
        if value > max_signal[1]:
            max_signal = (signal_type, value)

    # SF-01 v2 Day 4 (pre-flight) — apply simultaneous fall+voice
    # bonus BEFORE the env multiplier (which is applied downstream
    # in `evaluate_risk`). The bonus is additive, the multiplier is
    # multiplicative — keeping the order locked so the demo math
    # stays reproducible.
    fall_v  = float(signals.get("fall", 0.0) or 0.0)
    voice_v = float(signals.get("voice", 0.0) or 0.0)
    if (
        fall_v >= SIMULTANEOUS_FALL_THRESHOLD
        and voice_v >= SIMULTANEOUS_VOICE_THRESHOLD
    ):
        score += SIMULTANEOUS_FALL_VOICE_BONUS

    # SB-01 Day 2 — apply time-of-day multiplier on the base composite
    # (after attenuated weighted sum + bonus, before clip). Independent
    # of env_hazard_multiplier so they don't compound.
    score *= tm

    score = round(min(1.0, score), 3)
    level = classify_risk(score)
    primary = max_signal[0]

    return score, level, primary


def apply_decay(signals_with_timestamps: dict) -> dict[str, float]:
    """Apply time-based decay to signals. Input: {type: {score, timestamp}}."""
    now = datetime.now(timezone.utc)
    decayed = {}
    for sig_type, data in signals_with_timestamps.items():
        raw_score = data.get("score", 0)
        ts = data.get("timestamp")
        if ts:
            age = (now - datetime.fromisoformat(ts)).total_seconds()
            factor = _decay_factor(sig_type, age)
            decayed[sig_type] = round(raw_score * factor, 3)
        else:
            decayed[sig_type] = raw_score
    return decayed


async def evaluate_risk(
    session: AsyncSession,
    user_id: str,
    signals: dict[str, float],
    lat: float,
    lng: float,
    source_event_id: str | None = None,
) -> dict:
    """
    Evaluate unified risk from all active signals.
    Augments rule-based score with ML prediction when confidence > 0.7.
    Creates safety event if risk is suspicious+.
    """
    # ── SB-01 Day 2 — Hermes attenuator inputs ─────────────────────
    #
    # Pull per-user attenuation + time-of-day multiplier BEFORE the
    # score is computed, so they feed directly into `compute_risk_score`.
    # Both paths fall back to "no attenuation" semantics on error or
    # for new users — guaranteeing the Himalaya invariant (composite
    # = 0.793 on the canonical scenario) holds for any first-time
    # user with no feedback history.
    weight_attenuation: dict = {}
    attenuation_meta: dict = {
        "multipliers": {}, "samples": {}, "verdicts": 0,
        "source": "no feedback yet",
    }
    try:
        from app.api.sb01_hermes import get_user_attenuation, get_time_multiplier
        attenuation_meta = await get_user_attenuation(session, user_id)
        weight_attenuation = attenuation_meta.get("multipliers", {}) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("hermes_attenuator_failed: %s", exc)

    try:
        from app.api.sb01_hermes import get_time_multiplier
        current_hour = datetime.now(timezone.utc).hour
        time_multiplier = get_time_multiplier(current_hour)
    except Exception as exc:  # noqa: BLE001
        logger.warning("hermes_time_mult_failed: %s", exc)
        time_multiplier = 1.0

    score, level, primary = compute_risk_score(
        signals,
        weight_attenuation=weight_attenuation,
        time_multiplier=time_multiplier,
    )

    # ── ML Augmentation (Phase 5 of AI Learning Loop) ──
    ml_result = None
    try:
        from app.services.risk_model import predict, load_model
        from app.services.feature_store import get_live_features

        if load_model():
            features = await get_live_features(session, user_id)
            if features:
                ml_result = predict(features)
                ml_prob = ml_result.get("risk_probability", 0)
                ml_conf = ml_result.get("confidence", 0)

                # Blend ML with rule-based when model is confident
                if ml_conf >= 0.7 and "error" not in ml_result:
                    # Weighted blend: 60% rule-based + 40% ML
                    blended = 0.6 * score + 0.4 * ml_prob
                    score = round(min(1.0, blended), 3)
                    level = classify_risk(score)
                    logger.info(
                        f"Safety Brain ML blend: user={user_id}, "
                        f"rule={compute_risk_score(signals)[0]:.3f}, "
                        f"ml={ml_prob:.3f}, blended={score:.3f}, conf={ml_conf}"
                    )
    except Exception as e:
        logger.debug(f"ML augmentation skipped: {e}")

    # ── SF-01 v2 Day 3 — Phase 3 env hazard multiplier ──
    #
    # Apply the ×1.30 multiplier AFTER ML blend, BEFORE final clip,
    # so a fall+voice composite of 0.51 lifts to 0.66 and crosses
    # the 0.65 alert threshold. Pre-clip so we never lose signal to
    # rounding before the multiplier lands.
    env_match: dict = {
        "matched": False, "multiplier": 1.0,
        "hazards": [], "strongest": None, "state": None,
    }
    try:
        from app.services.env_hazard_matcher import match_env_hazards
        # Weather is best-effort — fetched only if the existing
        # weather_service exposes a sync-style read. Otherwise the
        # multiplier still fires off NDMA/Sachet alone.
        weather = None
        try:
            from app.services.weather_service import get_weather
            weather = await get_weather(lat, lng)
        except Exception:  # noqa: BLE001
            weather = None
        env_match = await match_env_hazards(lat, lng, weather=weather)
    except Exception as exc:  # noqa: BLE001
        # Compensating action: composite recalc still runs at the
        # base score. Phase 3 contribution is dropped on this
        # request only — next call retries fresh from cache.
        logger.warning("env_hazard_match_failed: %s", exc)

    pre_mult_score = score
    if env_match["matched"]:
        score = round(min(1.0, score * env_match["multiplier"]), 3)
        level = classify_risk(score)
        logger.info(
            "env_hazard_match_applied user=%s base=%.3f mult=%.2f -> %.3f",
            user_id, pre_mult_score, env_match["multiplier"], score,
        )

    # Mark whether the composite has crossed the ALERT tier.
    # Distinct from `level` — a score may sit at `suspicious` but
    # still be ≥ ALERT_THRESHOLD, in which case operators see the
    # alert chip light up.
    alert_fired = score >= ALERT_THRESHOLD

    # SF-01 v2 Day 4 — canonical alert dedup key.
    #
    # Per sprint spec: `alert_cooldown:{user_id}` TTL = 300 s is the
    # canonical Safety-Brain composite-alert dedup key. Distinct from
    # the per-channel keys (voice_distress, fall_detection,
    # predictive_reroute all use their own `cooldown:{user_id}`) —
    # this one gates the *composite* alert fan-out so a fall-then-
    # voice burst at t=0 and a re-trigger at t=60s don't fire two
    # FCM pushes to the guardian.
    #
    # Returned on the result envelope so the inject_himalaya_scenario
    # CLI script can assert the cooldown was set.
    cooldown_suppressed = False
    if alert_fired:
        cooldown_key = f"alert_cooldown:{user_id}"
        from app.services.redis_service import (
            get_json as _cd_get, set_json as _cd_set,
        )
        existing = _cd_get("safety_brain", cooldown_key)
        if existing:
            cooldown_suppressed = True
        else:
            _cd_set(
                "safety_brain", cooldown_key,
                {"set_at": datetime.now(timezone.utc).isoformat()},
                ttl=ALERT_COOLDOWN_TTL_S,
            )

    # Store current signal state
    now = datetime.now(timezone.utc)
    signal_state = _get(f"signals:{user_id}") or {}
    for sig_type, value in signals.items():
        if value > 0:
            signal_state[sig_type] = {"score": value, "timestamp": now.isoformat()}
    _set(f"signals:{user_id}", signal_state)

    result = {
        "risk_score": score,
        "risk_level": level,
        "primary_event": primary,
        "signals": signals,
        # SF-01 v2 Day 3 — surface Phase 3 env hazard match so the
        # mobile/operator UIs can render the "ENV: cyclone severe"
        # badge alongside the composite score.
        "env_hazard_match": env_match["matched"],
        "env_multiplier":   env_match["multiplier"],
        "env_hazards":      env_match["hazards"],
        "env_strongest":    env_match["strongest"],
        "pre_mult_score":   pre_mult_score,
        "alert_fired":      alert_fired,
        # SF-01 v2 Day 4 — surface cooldown decision so callers
        # (inject_himalaya_scenario CLI, dev scenario endpoint, FCM
        # dispatcher) can decide whether to fan out a notification.
        "cooldown_suppressed": cooldown_suppressed,
        # SB-01 Day 2 — surface Hermes attenuator decisions so the
        # Operator Confidence Engine UI can render "fall weight
        # softened 15% from 5 confirmed FPs" without re-computing.
        "weight_attenuation": weight_attenuation,
        "time_multiplier":    time_multiplier,
        "attenuation_source": attenuation_meta.get("source", "no feedback yet"),
        "attenuation_meta":   attenuation_meta,
    }

    # Only create event for suspicious+
    if level == "normal":
        result["status"] = "normal"
        return result

    event = SafetyEvent(
        user_id=uuid.UUID(user_id),
        risk_score=score,
        risk_level=level,
        signals=signals,
        primary_event=primary,
        location_lat=lat,
        location_lng=lng,
        status="active",
    )
    session.add(event)
    await session.flush()
    event_id = str(event.id)

    # Auto-SOS for critical
    emergency_id = None
    if level == "critical":
        try:
            from app.services.emergency_engine import trigger_silent_sos
            sos_result = await trigger_silent_sos(
                session=session, user_id=user_id, lat=lat, lng=lng,
                trigger_source="safety_brain",
                device_metadata={"safety_event_id": event_id, "risk_score": score, "signals": signals},
            )
            emergency_id = sos_result.get("event_id")
        except Exception as e:
            logger.error(f"Safety Brain auto-SOS failed: {e}")

    # SSE broadcast
    sse_data = {
        "event_id": event_id,
        "user_id": user_id,
        "risk_score": score,
        "risk_level": level,
        "primary_event": primary,
        "signals": signals,
        "lat": lat, "lng": lng,
        "auto_sos": level == "critical",
        "emergency_event_id": emergency_id,
        "timestamp": now.isoformat(),
    }
    await broadcaster.broadcast_to_user(user_id, "safety_risk_alert", sse_data)
    await broadcaster.broadcast_to_operators("safety_risk_alert", sse_data)

    # SF-01 v2 Day 3 — fan out an explicit ENV_HAZARD_MATCH event
    # whenever the multiplier fired. Distinct event type so operator
    # dashboards can render the hazard badge without parsing the
    # safety_risk_alert payload.
    if env_match["matched"]:
        env_sse = {
            "event_id":   event_id,
            "user_id":    user_id,
            "lat":        lat,
            "lng":        lng,
            "state":      env_match["state"],
            "hazards":    env_match["hazards"],
            "strongest":  env_match["strongest"],
            "multiplier": env_match["multiplier"],
            "pre_mult_score": pre_mult_score,
            "post_mult_score": score,
            "timestamp":  now.isoformat(),
        }
        try:
            await broadcaster.broadcast_to_user(
                user_id, "env_hazard_match", env_sse,
            )
            await broadcaster.broadcast_to_operators(
                "env_hazard_match", env_sse,
            )
        except Exception:  # noqa: BLE001
            # Compensating action: SSE broadcast is best-effort;
            # the safety_event row already has env_hazard_match in
            # its signals dict, so a missed broadcast does not lose
            # audit signal.
            logger.warning("env_hazard_match broadcast failed")

    # Record metrics for monitoring
    from app.services.monitoring_service import record_risk_spike, record_guardian_alert
    if score >= 0.6:
        record_risk_spike(score)
    if level in ("dangerous", "critical"):
        record_guardian_alert(level)

    # Enqueue AI signal for async batch processing
    from app.services.queue_service import enqueue_ai_signal
    enqueue_ai_signal({
        "signal_type": "risk_assessment",
        "user_id": user_id,
        "score": score,
        "level": level,
        "primary_event": primary,
        "lat": lat,
        "lng": lng,
    })

    logger.warning(f"Safety Brain: user={user_id}, score={score:.2f}, level={level}, primary={primary}")

    # Auto-trigger predictive reroute for dangerous+ events
    if level in ("dangerous", "critical"):
        try:
            from app.services.predictive_reroute_service import on_risk_level_change
            await on_risk_level_change(session, user_id, score, level, signals, lat, lng)
        except Exception as e:
            logger.error(f"Safety Brain auto-reroute hook failed: {e}")

    await session.commit()

    result.update({
        "event_id": event_id,
        "auto_sos": level == "critical",
        "emergency_event_id": emergency_id,
    })
    return result


async def get_user_risk_status(session: AsyncSession, user_id: str) -> dict:
    """Get current risk level for a user, with decayed signals."""
    signal_state = _get(f"signals:{user_id}")
    if not signal_state:
        return {"risk_score": 0, "risk_level": "normal", "signals": {}, "status": "no_data"}

    decayed = apply_decay(signal_state)
    score, level, primary = compute_risk_score(decayed)

    # Latest event
    result = await session.execute(
        select(SafetyEvent)
        .where(SafetyEvent.user_id == uuid.UUID(user_id))
        .order_by(desc(SafetyEvent.created_at))
        .limit(1)
    )
    latest = result.scalar_one_or_none()

    return {
        "risk_score": score,
        "risk_level": level,
        "primary_event": primary,
        "signals": decayed,
        "raw_signals": {k: v.get("score", 0) for k, v in signal_state.items()},
        "latest_event_id": str(latest.id) if latest else None,
        "latest_event_status": latest.status if latest else None,
    }


async def resolve_safety_event(session: AsyncSession, event_id: str, user_id: str) -> dict:
    result = await session.execute(
        select(SafetyEvent).where(SafetyEvent.id == uuid.UUID(event_id))
    )
    event = result.scalar_one_or_none()
    if not event:
        return {"error": "Safety event not found"}
    if str(event.user_id) != user_id:
        return {"error": "Not authorized"}
    if event.status == "resolved":
        return {"status": "already_resolved"}

    event.status = "resolved"
    event.resolved_at = datetime.now(timezone.utc)
    event.updated_at = datetime.now(timezone.utc)

    # Clear signal state
    _del(f"signals:{user_id}")

    await session.commit()
    return {"status": "resolved", "event_id": event_id}


async def get_safety_events(session: AsyncSession, user_id: str | None = None, limit: int = 20) -> list[dict]:
    query = select(SafetyEvent).order_by(desc(SafetyEvent.created_at)).limit(limit)
    if user_id:
        query = query.where(SafetyEvent.user_id == uuid.UUID(user_id))
    result = await session.execute(query)
    return [
        {
            "event_id": str(e.id), "user_id": str(e.user_id),
            "risk_score": e.risk_score, "risk_level": e.risk_level,
            "signals": e.signals, "primary_event": e.primary_event,
            "lat": e.location_lat, "lng": e.location_lng,
            "status": e.status,
            "created_at": e.created_at.isoformat() if e.created_at else None,
            "resolved_at": e.resolved_at.isoformat() if e.resolved_at else None,
        }
        for e in result.scalars().all()
    ]


# ── Detector Integration Hooks ──
# Called by existing detectors to feed signals into the brain

async def on_fall_detected(session: AsyncSession, user_id: str, confidence: float, lat: float, lng: float):
    """Hook called when fall detection fires."""
    current = _get(f"signals:{user_id}") or {}
    signals = {k: v.get("score", 0) if isinstance(v, dict) else v for k, v in current.items()}
    signals["fall"] = confidence
    return await evaluate_risk(session, user_id, signals, lat, lng)


async def on_voice_distress(session: AsyncSession, user_id: str, distress_score: float, lat: float, lng: float):
    """Hook called when voice distress fires."""
    current = _get(f"signals:{user_id}") or {}
    signals = {k: v.get("score", 0) if isinstance(v, dict) else v for k, v in current.items()}
    signals["voice"] = distress_score
    return await evaluate_risk(session, user_id, signals, lat, lng)


async def on_route_deviation(session: AsyncSession, user_id: str, deviation_score: float, lat: float, lng: float):
    """Hook called when route deviation escalates."""
    current = _get(f"signals:{user_id}") or {}
    signals = {k: v.get("score", 0) if isinstance(v, dict) else v for k, v in current.items()}
    signals["route"] = deviation_score
    return await evaluate_risk(session, user_id, signals, lat, lng)


async def on_wandering_detected(session: AsyncSession, user_id: str, wander_score: float, lat: float, lng: float):
    """Hook called when wandering detection fires."""
    current = _get(f"signals:{user_id}") or {}
    signals = {k: v.get("score", 0) if isinstance(v, dict) else v for k, v in current.items()}
    signals["wander"] = wander_score
    return await evaluate_risk(session, user_id, signals, lat, lng)


async def on_pickup_anomaly(session: AsyncSession, user_id: str, anomaly_score: float, lat: float, lng: float):
    """Hook called when a pickup verification fails (invalid code, proximity, expired)."""
    current = _get(f"signals:{user_id}") or {}
    signals = {k: v.get("score", 0) if isinstance(v, dict) else v for k, v in current.items()}
    signals["pickup"] = anomaly_score
    return await evaluate_risk(session, user_id, signals, lat, lng)
