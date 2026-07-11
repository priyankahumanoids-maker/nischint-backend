"""
HC-01 Day 2 — Wearable health-signal ingestion endpoint.

Receives a batch of HeartRate / SpO2 / Steps / Fall samples synced from
the mobile client's Health Connect bridge and persists them to a Redis
sorted-set per (user, signal-type). Threshold breaches are emitted as
structured log entries that the AI Brain can later subscribe to (the
actual risk-fusion wiring is HC-01 Day 3+).

Deviations from the spec template:
  • Auth dep: `app.api.deps.get_current_user` (returns the User model);
    template's `app.core.auth.get_current_user` does not exist in this
    codebase.
  • Redis: `redis_service._get_client()` returns the sync `redis.Redis`
    client; we use it synchronously (no `await`). Pipeline still batches.
  • Pydantic v2 — `field_validator` (not deprecated `validator`).
  • `evaluate_risk` brain hook is intentionally deferred; this endpoint
    only logs threshold breaches structurally. Brain integration is
    Day 3 work and needs proper signal-weight calibration.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session
from app.models.user import User
from app.services import redis_service
from app.services.safety_brain_service import evaluate_risk

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health-signals", tags=["wearable", "health-connect"])


# ── Schemas ────────────────────────────────────────────────────────────

SignalType = Literal["heart_rate", "spo2", "steps", "fall"]

_VALUE_LIMITS: dict[str, tuple[float, float]] = {
    "heart_rate": (20.0, 300.0),
    "spo2": (70.0, 100.0),
    "steps": (0.0, 100_000.0),
    "fall": (0.0, 1.0),
}


class HealthSignal(BaseModel):
    type: SignalType
    value: float
    unit: str = Field(..., max_length=16)
    source: str = Field(..., max_length=128)
    timestamp: str  # ISO-8601

    @field_validator("value")
    @classmethod
    def _validate_range(cls, v: float, info) -> float:
        sig_type = info.data.get("type")
        if sig_type in _VALUE_LIMITS:
            lo, hi = _VALUE_LIMITS[sig_type]
            if not lo <= v <= hi:
                raise ValueError(f"{sig_type} value {v} out of range [{lo}, {hi}]")
        return v

    @field_validator("timestamp")
    @classmethod
    def _validate_iso(cls, v: str) -> str:
        # Accept "Z" suffix as UTC.
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError as e:
            raise ValueError(f"timestamp not ISO-8601: {v}") from e
        return v


class HealthSignalBatch(BaseModel):
    signals: list[HealthSignal] = Field(..., max_length=500)


# ── Threshold detection ────────────────────────────────────────────────

def _detect_breach(sig: HealthSignal) -> str | None:
    """Return a breach tag if the sample crosses a configured threshold."""
    if sig.type == "heart_rate" and sig.value > 120:
        return "HR_HIGH"
    if sig.type == "spo2" and sig.value < 94:
        return "SPO2_LOW"
    if sig.type == "fall" and sig.value >= 1.0:
        return "FALL_DETECTED"
    return None


# Wearable-breach → safety-brain signal mapping.
#
# We reuse the existing WEIGHTS (fall=0.35, voice=0.30, …) instead of
# introducing a new "wearable" weight key, which would require
# re-calibrating the locked SF-01 v2 thresholds. The semantic mapping:
#   FALL_DETECTED → fall=1.0           (literally a fall)
#   HR_HIGH       → voice=0.60         (sustained tachycardia is a
#                                       distress-grade signal, on par
#                                       with mid-confidence voice)
#   SPO2_LOW      → voice=0.70         (hypoxia is a stronger distress
#                                       signal than tachycardia)
#
# We ALSO include a typed "wearable_*" key in the signals dict — the
# brain ignores unknown keys for scoring (`WEIGHTS.get(k, 0)`) but the
# SafetyEvent row persists the full dict, so investigators see what
# really fired.
_BREACH_SIGNAL_MAP: dict[str, dict[str, float]] = {
    "FALL_DETECTED": {"fall": 1.0, "wearable_fall": 1.0},
    "HR_HIGH":       {"voice": 0.60, "wearable_hr": 1.0},
    "SPO2_LOW":      {"voice": 0.70, "wearable_spo2": 1.0},
}


def _epoch_score(ts_iso: str) -> int:
    """Convert ISO-8601 timestamp to integer epoch seconds (Redis ZSET score)."""
    return int(datetime.fromisoformat(ts_iso.replace("Z", "+00:00")).timestamp())


# ── Endpoint ───────────────────────────────────────────────────────────

@router.post("/wearable")
async def ingest_wearable_signals(
    batch: HealthSignalBatch,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    x_device_id: str | None = Header(default=None, alias="X-Device-Id"),
    x_device_model: str | None = Header(default=None, alias="X-Device-Model"),
):
    """
    Ingest a batch of wearable health signals.

    Persists each sample in a Redis sorted-set
    `nischint:wearable:{user_id}:{type}` with epoch-seconds as score and
    a deterministic member string for idempotency. Threshold breaches
    are logged structurally for downstream consumers.

    HC-02: ALSO writes a mirror row to `health_signals_pg` per sample
    so operator dashboards can join across device timelines. The PG
    write is BEST-EFFORT — a PG outage logs + drops, the Redis path
    succeeds, and the client never sees a 500.

    `X-Device-Id` (UUID) and `X-Device-Model` (vendor string) are
    sent by the mobile client. Both are optional — older clients
    pre-HC-02 don't send them; their rows will have NULL device_id
    and 'unknown' device_model.
    """
    user_id = str(user.id)
    client = redis_service._get_client()

    # Normalize the device headers exactly once. Stripped + length-bounded.
    device_id_clean = (x_device_id or "").strip() or None
    device_model_clean = ((x_device_model or "").strip() or "unknown")[:100]

    breaches: list[dict] = []
    persisted = 0

    if client is None:
        logger.warning(
            "[wearable_ingest] redis unavailable user_id=%s signals=%d — accepting but not persisting",
            user_id, len(batch.signals),
        )

    pipe = client.pipeline() if client is not None else None
    now_ms = int(time.time() * 1000)

    # HC-02 — accumulate one mirror row per sample. Written to PG in
    # a single batched INSERT at the end of the loop (or skipped on
    # PG outage — never a 500 to the mobile client).
    pg_rows: list[dict] = []

    for sig in batch.signals:
        # Deterministic member = sha1(type|timestamp|value) — same sample
        # re-sent within the TTL window is deduplicated by ZADD.
        member_seed = f"{sig.type}|{sig.timestamp}|{sig.value}"
        idem = hashlib.sha1(member_seed.encode()).hexdigest()[:16]
        # HC-02: device_id + device_model carried in the Redis payload
        # so the existing Redis read path surfaces them without a
        # separate fetch. Older clients omit both fields entirely.
        payload = json.dumps({
            "type": sig.type,
            "value": sig.value,
            "unit": sig.unit,
            "source": sig.source,
            "timestamp": sig.timestamp,
            "idem": idem,
            "device_id":    device_id_clean,
            "device_model": device_model_clean,
        })
        member = f"{idem}:{payload}"

        if pipe is not None:
            key = redis_service._key("wearable", f"{user_id}:{sig.type}")
            pipe.zadd(key, {member: _epoch_score(sig.timestamp)})
            # 8-day rolling window so the HC-02 /history endpoint can
            # serve the full 7-day chart even at the trailing edge.
            pipe.expire(key, 8 * 86400)
            persisted += 1

        breach = _detect_breach(sig)
        # HC-02 mirror row — built once per sample, even when there's
        # no breach. `breach_tag=None` is fine; the partial index on
        # `breach_tag IS NOT NULL` keeps storage cheap.
        # asyncpg requires a real datetime instance for TIMESTAMPTZ —
        # coerce the ISO-8601 string here so the executemany batch
        # doesn't blow up on string→timestamptz mismatch.
        try:
            ts_dt = datetime.fromisoformat(sig.timestamp.replace("Z", "+00:00"))
        except ValueError:
            ts_dt = datetime.now(timezone.utc)
        pg_rows.append({
            "user_id":      user_id,
            "device_id":    device_id_clean,
            "device_model": device_model_clean,
            "signal_type":  sig.type,
            "value":        float(sig.value),
            "unit":         sig.unit,
            "source":       sig.source,
            "ts":           ts_dt,
            "breach_tag":   breach,
        })
        if breach:
            breach_entry = {
                "tag": breach,
                "type": sig.type,
                "value": sig.value,
                "timestamp": sig.timestamp,
                "source": sig.source,
            }
            breaches.append(breach_entry)
            logger.warning(
                "[HC-01 threshold_breach] user_id=%s tag=%s value=%s ts=%s source=%s",
                user_id, breach, sig.value, sig.timestamp, sig.source,
            )

            # ── Brain hook ─────────────────────────────────────────
            # Wearable alerts have no GPS context, so pass last-known
            # if present, else (0.0, 0.0) per spec. The brain still
            # creates a SafetyEvent row (which guardians can act on)
            # and runs the env-hazard multiplier — that's a no-op
            # when lat/lng are 0,0 since no hazard polygon matches.
            brain_signals = _BREACH_SIGNAL_MAP[breach]
            brain_lat = float(user.last_known_lat or 0.0)
            brain_lng = float(user.last_known_lng or 0.0)
            try:
                await evaluate_risk(
                    session=session,
                    user_id=user_id,
                    signals=brain_signals,
                    lat=brain_lat,
                    lng=brain_lng,
                    source_event_id=f"wearable:{breach}:{sig.timestamp}",
                )
            except Exception as e:
                # Brain failures must not kill ingestion — log and
                # continue so the rest of the batch still persists.
                logger.exception(
                    "[HC-01 threshold_breach] evaluate_risk failed user_id=%s tag=%s err=%s",
                    user_id, breach, e,
                )

    if pipe is not None:
        try:
            pipe.execute()
        except Exception as e:
            logger.exception("[wearable_ingest] redis pipeline execute failed: %s", e)
            persisted = 0

    # HC-02 — best-effort PG mirror. Wrapped in its own try block so
    # a transient DB outage doesn't fail the request: the Redis hot
    # path already succeeded, the mobile client already has its 200.
    pg_mirrored = 0
    if pg_rows:
        try:
            await session.execute(
                text("""
                    INSERT INTO health_signals_pg
                        (user_id, device_id, device_model, signal_type,
                         value, unit, source, ts, breach_tag)
                    VALUES
                        (:user_id, :device_id, :device_model, :signal_type,
                         :value, :unit, :source, :ts, :breach_tag)
                """),
                pg_rows,
            )
            await session.commit()
            pg_mirrored = len(pg_rows)
        except Exception as e:
            await session.rollback()
            logger.warning(
                "[HC-02 pg_mirror] write failed user_id=%s rows=%d err=%r",
                user_id, len(pg_rows), e,
            )

    logger.info(
        "[wearable_ingest] user_id=%s ingested=%d breaches=%d pg_mirrored=%d window_ms=%s",
        user_id, persisted, len(breaches), pg_mirrored, now_ms,
    )

    return {
        "ingested":     persisted,
        "breaches":     breaches,
        "user_id":      user_id,
        "pg_mirrored":  pg_mirrored,
    }



# ── Guardian read of dependent vitals (Day 4) ──────────────────────────


def _read_latest_zset(client, namespace_key: str) -> tuple[float | None, str | None]:
    """
    Return (value, timestamp_iso) for the most-recent sample in a
    Redis ZSET (highest score = newest epoch-seconds).

    Returns (None, None) when the key is empty or the stored payload
    can't be parsed.
    """
    try:
        rows = client.zrevrange(namespace_key, 0, 0)
    except Exception as e:
        logger.warning("[dependent_vitals] zrevrange failed key=%s err=%s", namespace_key, e)
        return None, None
    if not rows:
        return None, None
    raw = rows[0]
    # Members are stored as "{idem}:{json_payload}". Strip the 16-char
    # idem prefix + ":" separator.
    _, _, payload_json = raw.partition(":")
    try:
        payload = json.loads(payload_json)
        return float(payload["value"]), str(payload["timestamp"])
    except (ValueError, KeyError, TypeError) as e:
        logger.warning("[dependent_vitals] payload parse failed err=%s", e)
        return None, None


async def _is_guardian_of(session, caller_id: str, dependent_id: str) -> bool:
    """Return True if `caller_id` is a registered guardian of `dependent_id`."""
    from app.services.geofence_alerts import _resolve_guardian_ids
    try:
        guardians = await _resolve_guardian_ids(session, dependent_id)
    except Exception as e:
        logger.exception("[dependent_vitals] guardian-resolve failed: %s", e)
        return False
    return caller_id in guardians


@router.get("/dependent/{dependent_id}/latest")
async def get_dependent_latest_vitals(
    dependent_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Read the most-recent heart-rate and SpO₂ sample for `dependent_id`
    from Redis. The caller must be a registered guardian of the
    dependent — enforced via the existing `_resolve_guardian_ids`
    cache (TTL 10 min) so we don't burn DB on every poll.

    Self-read is also allowed: a user can always query their own ID.
    """
    from fastapi import HTTPException

    caller_id = str(user.id)
    is_self = caller_id == dependent_id

    if not is_self:
        ok = await _is_guardian_of(session, caller_id, dependent_id)
        if not ok:
            raise HTTPException(status_code=403, detail="Not a guardian of this user")

    client = redis_service._get_client()
    if client is None:
        return {
            "dependent_id": dependent_id,
            "hr": None,
            "spo2": None,
            "last_sync": None,
        }

    hr_key = redis_service._key("wearable", f"{dependent_id}:heart_rate")
    spo2_key = redis_service._key("wearable", f"{dependent_id}:spo2")

    hr_val, hr_ts = _read_latest_zset(client, hr_key)
    spo2_val, spo2_ts = _read_latest_zset(client, spo2_key)

    last_sync: str | None = None
    for ts in (hr_ts, spo2_ts):
        if ts is None:
            continue
        if last_sync is None or ts > last_sync:
            last_sync = ts

    return {
        "dependent_id": dependent_id,
        "hr": hr_val,
        "spo2": spo2_val,
        "last_sync": last_sync,
    }


# ── HC-02: device-grain timeline from PG mirror ───────────────────


@router.get("/dependent/{dependent_id}/by-device")
async def get_dependent_signals_by_device(
    dependent_id: str,
    hours: int = 24,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """HC-02 — read the `health_signals_pg` mirror, grouped by device.

    Returns the dependent timeline split by `device_id` so the
    caregiver UI can distinguish multiple paired devices on the
    same chart. Falls through to a single `'unknown'` bucket for
    legacy rows missing `device_id` (older mobile clients pre-HC-02).

    Guardianship gate matches the legacy `/latest` endpoint — self
    OR registered guardian. `hours` clamped to [1, 168] (7 days) to
    match the existing 7-day chart contract.
    """
    from fastapi import HTTPException

    caller_id = str(user.id)
    is_self = caller_id == dependent_id
    is_privileged = getattr(user, "role", None) in {"admin", "operator"}
    if not is_self and not is_privileged:
        ok = await _is_guardian_of(session, caller_id, dependent_id)
        if not ok:
            raise HTTPException(status_code=403, detail="Not a guardian of this user")

    h = max(1, min(168, int(hours)))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=h)

    try:
        rows = (await session.execute(
            text("""
                SELECT device_id, device_model, signal_type, value, unit,
                       ts, breach_tag
                  FROM health_signals_pg
                 WHERE user_id = :uid AND ts >= :cutoff
                 ORDER BY ts ASC
            """),
            {"uid": dependent_id, "cutoff": cutoff},
        )).fetchall()
    except Exception as e:
        logger.warning("[HC-02 by_device] read failed user_id=%s err=%r",
                       dependent_id, e)
        return {"dependent_id": dependent_id, "hours": h, "devices": []}

    # Group by device_id (NULL → 'unknown' bucket so the UI can
    # render a single chip for legacy samples instead of dropping them).
    by_dev: dict[str, dict] = {}
    for r in rows:
        key = str(r.device_id) if r.device_id else "unknown"
        if key not in by_dev:
            by_dev[key] = {
                "device_id":    str(r.device_id) if r.device_id else None,
                "device_model": r.device_model or "unknown",
                "sample_count": 0,
                "breach_count": 0,
                "first_seen":   r.ts.isoformat() if r.ts else None,
                "last_seen":    None,
                "samples":      [],
            }
        bucket = by_dev[key]
        bucket["sample_count"] += 1
        if r.breach_tag:
            bucket["breach_count"] += 1
        if r.ts and (bucket["last_seen"] is None or r.ts.isoformat() > bucket["last_seen"]):
            bucket["last_seen"] = r.ts.isoformat()
        bucket["samples"].append({
            "ts":         r.ts.isoformat() if r.ts else None,
            "type":       r.signal_type,
            "value":      float(r.value),
            "unit":       r.unit,
            "breach_tag": r.breach_tag,
        })

    return {
        "dependent_id": dependent_id,
        "hours":        h,
        "devices":      list(by_dev.values()),
    }


# ── HC-02 operator helper — list dependents with health signals ──────


@router.get("/admin/dependents")
async def list_dependents_with_signals(
    hours: int = 168,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Return distinct users who have written to `health_signals_pg`
    in the last `hours` window, enriched with name/email and a few
    summary counters. Admin or operator only — gated by `user.role`.

    Used by the operator Device Health page to seed the picker that
    drives `DependentVitalsCard` (HC-02 by-device timeline).
    """
    from fastapi import HTTPException

    role = getattr(user, "role", None)
    if role not in {"admin", "operator"}:
        raise HTTPException(status_code=403, detail="admin or operator required")

    h = max(1, min(720, int(hours)))  # cap at 30 days
    cutoff = datetime.now(timezone.utc) - timedelta(hours=h)

    try:
        rows = (await session.execute(
            text("""
                SELECT  hs.user_id,
                        COUNT(*)                    AS sample_count,
                        COUNT(DISTINCT hs.device_id) FILTER (WHERE hs.device_id IS NOT NULL) AS device_count,
                        SUM(CASE WHEN hs.breach_tag IS NOT NULL THEN 1 ELSE 0 END) AS breach_count,
                        MAX(hs.ts)                  AS last_seen,
                        COALESCE(u.full_name, '')   AS full_name,
                        COALESCE(u.email, '')       AS email
                  FROM health_signals_pg hs
             LEFT JOIN users u ON u.id = hs.user_id
                 WHERE hs.ts >= :cutoff
              GROUP BY hs.user_id, u.full_name, u.email
              ORDER BY MAX(hs.ts) DESC
                 LIMIT 200
            """),
            {"cutoff": cutoff},
        )).fetchall()
    except Exception as e:
        logger.warning("[HC-02 dependents_list] read failed err=%r", e)
        return {"hours": h, "dependents": []}

    return {
        "hours": h,
        "dependents": [
            {
                "user_id":      str(r.user_id),
                "full_name":    r.full_name or "(unknown)",
                "email":        r.email or "",
                "sample_count": int(r.sample_count or 0),
                "device_count": int(r.device_count or 0),
                "breach_count": int(r.breach_count or 0),
                "last_seen":    r.last_seen.isoformat() if r.last_seen else None,
            }
            for r in rows
        ],
    }


# ── HC-02: 7-day history with anomaly flagging ───────────────────────


# Threshold contract — kept consistent with HC-01 ingestion breach
# detector (`_detect_breach`) so the chart annotation lines up with
# the same alert the Brain reacts to.
_HR_ANOMALY_HIGH = 120.0
_SPO2_ANOMALY_LOW = 94.0


def _read_zset_range(client, key: str, since_epoch: float) -> list[dict]:
    """Return [{timestamp, value}, ...] for samples in the ZSET since
    `since_epoch`, ordered oldest→newest. Best-effort — returns [] on
    failure so the chart can render an empty state instead of erroring."""
    try:
        rows = client.zrangebyscore(key, since_epoch, "+inf")
    except Exception as e:
        logger.warning("[health_history] zrangebyscore failed key=%s err=%s", key, e)
        return []
    out: list[dict] = []
    for raw in rows:
        _, _, payload_json = raw.partition(":")
        try:
            payload = json.loads(payload_json)
            out.append({
                "timestamp": str(payload["timestamp"]),
                "value":     float(payload["value"]),
            })
        except (ValueError, KeyError, TypeError):
            continue
    return out


@router.get("/history/{user_id}")
async def get_health_history(
    user_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """7-day HR + SpO2 history + anomaly flagging for `user_id`.

    Same RBAC as `/dependent/{id}/latest` — self or registered
    guardian. Returns `{hr, spo2, anomalies}` where each list is
    ordered chronologically (oldest first) so the chart can render
    without a re-sort. `anomalies` carries the same samples that
    crossed the HC-01 alert thresholds so the chart can mark them
    inline.
    """
    from fastapi import HTTPException

    caller_id = str(user.id)
    if caller_id != user_id:
        ok = await _is_guardian_of(session, caller_id, user_id)
        if not ok:
            raise HTTPException(status_code=403, detail="Not a guardian of this user")

    client = redis_service._get_client()
    if client is None:
        return {"user_id": user_id, "hr": [], "spo2": [], "anomalies": []}

    since = time.time() - 7 * 86400
    hr_key   = redis_service._key("wearable", f"{user_id}:heart_rate")
    spo2_key = redis_service._key("wearable", f"{user_id}:spo2")

    hr   = _read_zset_range(client, hr_key,   since)
    spo2 = _read_zset_range(client, spo2_key, since)

    anomalies: list[dict] = []
    for s in hr:
        if s["value"] > _HR_ANOMALY_HIGH:
            anomalies.append({"timestamp": s["timestamp"], "type": "hr_high",
                              "value": s["value"]})
    for s in spo2:
        if s["value"] < _SPO2_ANOMALY_LOW:
            anomalies.append({"timestamp": s["timestamp"], "type": "spo2_low",
                              "value": s["value"]})

    return {
        "user_id":   user_id,
        "hr":        hr,
        "spo2":      spo2,
        "anomalies": anomalies,
    }
