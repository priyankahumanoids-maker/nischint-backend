"""NISCH-011 — Behavioral baseline learner.

Builds the per-entity 14-day baseline that the detector compares
against. Pure aggregation; no model training. Idempotent — running
the builder twice in a row writes the same baseline_version row
content (with a refreshed `updated_at`).

Phase 1 features (deliberately small):

  * `dwell_duration`        — mean + stddev of GPS-stationary
                              durations across the window
  * `temporal_signature`    — hourly activity histogram
  * `mobility_signature`    — mean speed + speed stddev
  * `route_entropy`         — Shannon entropy over unique
                              zones visited

`risk_exposure_averages` and `rolling_deviation_thresholds` are
populated from the same source so the detector reads ONE table,
not five.

Phase 2 will add `interaction_cadence` (notifications + SOS +
inter-guardian comms) and `ambient_profile` (weather + crowd
density). Those columns are nullable on purpose.
"""
from __future__ import annotations

import logging
import math
import statistics
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.behavioral import BASELINE_VERSION

logger = logging.getLogger(__name__)


BASELINE_WINDOW_DAYS = 14
MIN_SAMPLES_FOR_BASELINE = 30


def _shannon_entropy(counts: list[int]) -> float:
    """Shannon entropy in nats. 0 when all observations are the
    same; ln(n) when uniformly distributed."""
    total = sum(counts)
    if total <= 0:
        return 0.0
    entropy = 0.0
    for c in counts:
        if c <= 0:
            continue
        p = c / total
        entropy -= p * math.log(p)
    return entropy


def build_baseline_features(samples: list[dict]) -> dict:
    """Pure-function aggregator. Inputs are dicts with `speed_mps`,
    `dwell_s`, `hour`, `zone_id`. Missing keys → that sample is
    skipped for the corresponding feature, NOT failed."""
    speeds = [float(s["speed_mps"]) for s in samples
              if s.get("speed_mps") is not None]
    dwells = [float(s["dwell_s"]) for s in samples
              if s.get("dwell_s") is not None]
    hours = [int(s["hour"]) for s in samples
             if s.get("hour") is not None and 0 <= int(s["hour"]) < 24]
    zones = [str(s["zone_id"]) for s in samples
             if s.get("zone_id")]

    hourly = [0] * 24
    for h in hours:
        hourly[h] += 1

    zone_counts: dict[str, int] = {}
    for z in zones:
        zone_counts[z] = zone_counts.get(z, 0) + 1

    features: dict = {
        "mobility_signature": {
            "mean_speed_mps":  statistics.fmean(speeds) if speeds else 0.0,
            "stdev_speed_mps": statistics.pstdev(speeds) if len(speeds) >= 2 else 0.0,
        },
        "dwell_duration": {
            "mean_s":  statistics.fmean(dwells) if dwells else 0.0,
            "stdev_s": statistics.pstdev(dwells) if len(dwells) >= 2 else 0.0,
        },
        "temporal_signature": {
            "hourly_histogram": hourly,
        },
        "route_entropy": _shannon_entropy(list(zone_counts.values())),
        "zone_affinity": zone_counts,
        # Risk exposure proxy — share of samples falling in any
        # zone vs no zone. Phase 2 should replace with risk-band
        # weighting once `safety_incidents` zone metadata is
        # consistently populated.
        "risk_exposure_averages": {
            "in_zone_share": (len(zones) / max(1, len(samples))),
        },
    }
    # Rolling deviation thresholds — locked at 2× stddev for now.
    # The detector reads these so changing them only needs a
    # baseline rebuild + pipeline-version bump.
    features["rolling_deviation_thresholds"] = {
        "mobility_speed":    2.0 * features["mobility_signature"]["stdev_speed_mps"],
        "dwell_duration":    2.0 * features["dwell_duration"]["stdev_s"],
    }
    return features


async def _query_recent_samples(
    session: AsyncSession,
    entity_id: uuid.UUID,
    window_days: int = BASELINE_WINDOW_DAYS,
) -> list[dict]:
    """Source samples from `location_trail_points` if present,
    else fall back to an empty list. The detector handles
    cold-start gracefully via `sample_count` so an empty fetch
    is fine."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    try:
        rows = (await session.execute(text("""
            SELECT EXTRACT(HOUR FROM ts)::int AS hour,
                   COALESCE(speed_mps, 0)::float AS speed_mps,
                   COALESCE(dwell_s, 0)::float AS dwell_s,
                   zone_id::text AS zone_id
              FROM location_trail_points
             WHERE user_id = :uid
               AND ts >= :cutoff
             ORDER BY ts ASC
             LIMIT 5000
        """), {"uid": str(entity_id), "cutoff": cutoff})).all()
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "behavioral_baseline_sample_query_failed",
            extra={"event": "behavioral_baseline_sample_query_failed",
                   "entity_id": str(entity_id),
                   "error_type": type(e).__name__},
        )
        return []

    return [{
        "hour":      r[0],
        "speed_mps": r[1],
        "dwell_s":   r[2],
        "zone_id":   r[3],
    } for r in rows]


async def upsert_baseline(
    session: AsyncSession,
    entity_id: uuid.UUID,
    *,
    samples_override: Optional[list[dict]] = None,
) -> dict:
    """Rebuild a single entity's baseline and persist. Idempotent
    via the unique index on `entity_id`."""
    samples = (samples_override
               if samples_override is not None
               else await _query_recent_samples(session, entity_id))
    n = len(samples)
    features = build_baseline_features(samples)

    # NISCH-012 — additive motion-telemetry dimension. The GPS-
    # derived `mobility_signature` covers speed/dwell, but it
    # can't tell apart "stationary inside a moving bus" from
    # "stationary on a bench". Motion features close that gap.
    # If the entity has no motion uploads yet (cold start), this
    # block is a silent no-op — backwards-compatible with all
    # existing rows.
    try:
        from app.api.motion_features import fetch_recent_motion_aggregate
        agg = await fetch_recent_motion_aggregate(
            session, entity_id, since_hours=24 * 14,
        )
        if agg:
            features["mobility_signature"]["motion_telemetry"] = {
                "window_count":           agg["window_count"],
                "mean_g":                 agg["mean_g"],
                "stddev_g":               agg["stddev_g"],
                "peak_g":                 agg["peak_g"],
                "gyro_variance":          agg["gyro_variance"],
                "activity_distribution":  agg["activity_distribution"],
                "latest_window":          agg["latest_window"],
                "telemetry_pipeline_version":
                    agg["telemetry_pipeline_version"],
            }
    except Exception as e:  # noqa: BLE001
        # Additive-only contract — a motion-aggregate failure must
        # NEVER block the baseline rebuild. The existing GPS-derived
        # mobility signature is preserved untouched.
        logger.warning(
            "behavioral_baseline_motion_enrich_failed",
            extra={"event": "behavioral_baseline_motion_enrich_failed",
                   "entity_id": str(entity_id),
                   "error_type": type(e).__name__},
        )

    try:
        await session.execute(text("""
            INSERT INTO behavioral_baselines
              (entity_id, zone_affinity, route_entropy,
               dwell_duration, temporal_signature, mobility_signature,
               risk_exposure_averages, rolling_deviation_thresholds,
               baseline_version, sample_count, computed_at, updated_at)
            VALUES
              (:entity_id, CAST(:zone_aff AS JSONB), :route_entropy,
               CAST(:dwell AS JSONB), CAST(:temp AS JSONB),
               CAST(:mob AS JSONB),
               CAST(:risk AS JSONB), CAST(:thresh AS JSONB),
               :ver, :n, now(), now())
            ON CONFLICT (entity_id) DO UPDATE SET
              zone_affinity                = EXCLUDED.zone_affinity,
              route_entropy                = EXCLUDED.route_entropy,
              dwell_duration               = EXCLUDED.dwell_duration,
              temporal_signature           = EXCLUDED.temporal_signature,
              mobility_signature           = EXCLUDED.mobility_signature,
              risk_exposure_averages       = EXCLUDED.risk_exposure_averages,
              rolling_deviation_thresholds = EXCLUDED.rolling_deviation_thresholds,
              baseline_version             = EXCLUDED.baseline_version,
              sample_count                 = EXCLUDED.sample_count,
              updated_at                   = now()
        """), {
            "entity_id": str(entity_id),
            "zone_aff":  __json(features["zone_affinity"]),
            "route_entropy": features["route_entropy"],
            "dwell":     __json(features["dwell_duration"]),
            "temp":      __json(features["temporal_signature"]),
            "mob":       __json(features["mobility_signature"]),
            "risk":      __json(features["risk_exposure_averages"]),
            "thresh":    __json(features["rolling_deviation_thresholds"]),
            "ver":       BASELINE_VERSION,
            "n":         n,
        })
        await session.commit()
    except Exception as e:  # noqa: BLE001
        await session.rollback()
        logger.warning(
            "behavioral_baseline_persist_failed",
            extra={"event": "behavioral_baseline_persist_failed",
                   "entity_id": str(entity_id),
                   "error_type": type(e).__name__},
        )

    return {
        "entity_id":         str(entity_id),
        "sample_count":      n,
        "baseline_version":  BASELINE_VERSION,
        "is_warm":           n >= MIN_SAMPLES_FOR_BASELINE,
        "features":          features,
    }


def __json(obj) -> str:
    import json
    return json.dumps(obj, default=str)


__all__ = [
    "build_baseline_features", "upsert_baseline",
    "BASELINE_WINDOW_DAYS", "MIN_SAMPLES_FOR_BASELINE",
]
