"""NISCH-011 — BehavioralBaselinePrewarmer.

Subclass of `ProviderPrewarmer` per the locked design constraint
(see ROADMAP.md). Same surface as `RiskPredictionPrewarmer`:

  * 1-hour cadence (`jitter_base_s=3600`)
  * 2.0 s fetch budget (DB probe — light query)
  * Surfaces DB health on the prewarmer rollup chip via
    inherited 4-state hysteresis machine
  * Per-cycle measurement → operator capsule (latency exporter)

What it probes:
  Count of `behavioral_baselines` rows older than 24 h. A
  growing number means the baseline learner is falling behind
  — surfaces as `stale_baseline_count` on the rollup chip.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.services.behavioral import BASELINE_VERSION
from app.services.external_signals.base_prewarmer import ProviderPrewarmer

logger = logging.getLogger(__name__)


class BehavioralBaselinePrewarmer(ProviderPrewarmer):
    name = "behavioral_baseline"
    cache_namespace = "behavioral_baseline"
    cache_key = "warm_context"
    cache_ttl_s = 3600

    telemetry_namespace = "behavioral_baseline"
    history_source_name = "behavioral_baseline"

    # Distinct jitter base from risk_prediction (3600+60) so the
    # two engines don't co-fire on identical cadences.
    jitter_base_s = 3600
    jitter_range_s = 90
    scheduler_job_id = "behavioral_baseline_prewarm"

    active_count_field = "warm_baseline_count"

    fetch_timeout_s = 2.0

    healthy_max_age_s = 7200
    stale_max_age_s = 10800

    async def fetch(self) -> list[dict] | None:
        """One warm cycle — count warm baselines + identify
        stale ones. Same defensive contract as
        RiskPredictionPrewarmer: return None on any DB failure
        so the base class treats it as cache-preserved."""
        from app.db.session import async_session
        try:
            async with async_session() as session:
                cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
                row = (await session.execute(text("""
                    SELECT
                        COUNT(*)::int FILTER (WHERE updated_at >= :c)::int AS warm,
                        COUNT(*)::int FILTER (WHERE updated_at <  :c)::int AS stale
                      FROM behavioral_baselines
                """), {"c": cutoff})).first()
                warm = int(row[0] or 0) if row else 0
                stale = int(row[1] or 0) if row else 0
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "behavioral_baseline_prewarm_db_failed",
                extra={"event": "behavioral_baseline_prewarm_db_failed",
                       "error_type": type(e).__name__},
            )
            return None

        return [{
            "warm_baseline_count":   warm,
            "stale_baseline_count":  stale,
            "baseline_version":      BASELINE_VERSION,
            "queried_at":            datetime.now(timezone.utc).isoformat(),
        }]


_INSTANCE: BehavioralBaselinePrewarmer | None = None


def _get_instance() -> BehavioralBaselinePrewarmer:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = BehavioralBaselinePrewarmer()
    return _INSTANCE


def start_behavioral_baseline_prewarmer() -> None:
    _get_instance().start()


def stop_behavioral_baseline_prewarmer() -> None:
    if _INSTANCE is not None:
        _INSTANCE.stop()


__all__ = [
    "BehavioralBaselinePrewarmer",
    "start_behavioral_baseline_prewarmer",
    "stop_behavioral_baseline_prewarmer",
]
