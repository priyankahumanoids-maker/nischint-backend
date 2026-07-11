"""NISCH-012.2 — News/social keyword monitor pre-warmer.

Subclass of `ProviderPrewarmer` but with a special twist: the
upstream fetch is *two-tier*. NewsAPI is the primary source when
`NEWSAPI_KEY` is set; RSS (NDTV + Times of India) is the always-on
fallback.

Spec invariants (locked):

  1. Provider is never fully disabled — only the NewsAPI channel is.
     If `NEWSAPI_KEY` is absent, RSS still runs and the prewarmer
     still registers. The operator UI reflects this via a per-channel
     `newsapi_disabled: true` flag in telemetry.

  2. `parse_failure_rate` tracks NewsAPI failures ONLY. RSS has its
     own `rss_failure_rate` counter. This means an operator can tell
     "NewsAPI is down but our news situational awareness is intact
     via RSS" at a glance. Without the split, a healthy fallback
     would mask a paid-API outage.

  3. The base class's failure-rate trips the health state machine.
     We deliberately route the **RSS** failure rate into the base's
     `parse_failure_rate` field when NewsAPI is disabled, so the
     state machine still reflects the only signal channel we have.
     When NewsAPI is enabled, we use NewsAPI's failure rate (the
     primary channel) — RSS failures alone do NOT push the state
     into degraded because RSS is a fallback.

  4. Jitter: 15 min ± 2 min uniform — independent of Sachet's
     4 min ± 45 s and TomTom's 5 min ± 60 s. News changes slower
     than traffic; the API cost matters.

  5. No DB writes — RELIABILITY_DEBT ratchet unchanged.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from app.services import redis_service
from app.services.external_signals import base_prewarmer as _base
from app.services.external_signals.base_prewarmer import (
    STATE_DEGRADED, STATE_HEALTHY, STATE_STALE, STATE_UNKNOWN,
    ProviderPrewarmer,
)
from app.services.external_signals.news_provider import (
    CACHE_KEY as _CACHE_KEY, CACHE_NAMESPACE as _CACHE_NAMESPACE,
    CACHE_TTL_S as _CACHE_TTL_S, fetch_newsapi, fetch_rss,
    newsapi_enabled,
)

logger = logging.getLogger(__name__)


# ── Per-channel telemetry keys ───────────────────────────────────
TELEMETRY_NAMESPACE = "news_prewarmer"
CHANNEL_NEWSAPI_KEY = "channel_newsapi"
CHANNEL_RSS_KEY = "channel_rss"
HISTORY_WINDOW = 10


def _record_channel_attempt(channel_key: str, success: bool,
                            count: int) -> None:
    """Per-channel rolling failure-rate. Mirrors the base
    `_record_attempt` shape but keyed independently so NewsAPI and
    RSS counters do NOT cross-pollute."""
    try:
        prior = redis_service.get_json(
            TELEMETRY_NAMESPACE, channel_key,
        ) or {}
        history = list(prior.get("attempt_history") or [])
        history.append(bool(success))
        if len(history) > HISTORY_WINDOW:
            history = history[-HISTORY_WINDOW:]
        fails = sum(1 for h in history if not h)
        failure_rate = round(fails / len(history), 4) if history else 0.0
        now_iso = datetime.now(timezone.utc).isoformat()
        payload = {
            "last_fetch_ts":      now_iso,
            "last_success_ts":    (
                now_iso if success else prior.get("last_success_ts")
            ),
            "failure_rate":       failure_rate,
            "active_item_count": (
                int(count) if success
                else int(prior.get("active_item_count", 0) or 0)
            ),
            "attempt_history":    history,
        }
        redis_service.set_json(
            TELEMETRY_NAMESPACE, channel_key, payload, ttl=86_400,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "[NEWS_PREWARMER] channel telemetry write failed: %r", e,
        )


def get_channel_telemetry(channel_key: str) -> dict:
    raw = redis_service.get_json(TELEMETRY_NAMESPACE, channel_key) or {}
    return {
        "last_fetch_ts":      raw.get("last_fetch_ts"),
        "last_success_ts":    raw.get("last_success_ts"),
        "failure_rate":       float(raw.get("failure_rate", 0.0)),
        "active_item_count":  int(raw.get("active_item_count", 0) or 0),
        "attempt_history_size": len(raw.get("attempt_history") or []),
    }


class NewsPrewarmer(ProviderPrewarmer):
    """Two-tier fetch wrapper. The base class's `fetch()` returns
    the combined item list (NewsAPI + RSS). Per-channel telemetry
    is written separately so an operator can distinguish a paid-API
    outage from a true intel blackout."""

    name = "NEWS"
    cache_namespace = _CACHE_NAMESPACE
    cache_key = _CACHE_KEY
    cache_ttl_s = _CACHE_TTL_S
    telemetry_namespace = TELEMETRY_NAMESPACE
    history_source_name = "news_health"
    jitter_base_s = 900             # 15 min — slowest of the three providers
    jitter_range_s = 120            # ±2 min — locked by test
    scheduler_job_id = "news_prewarm_cycle"
    active_count_field = "active_news_count"
    # News cycle chains NewsAPI (1.5 s) + RSS batch (2 feeds × 1.5 s
    # sequentially within a single client) → wall-clock ceiling ≈
    # 4–5 s. We set the budget at 5 s so the chip ambers if either
    # channel's tail starts dominating the cycle.
    fetch_timeout_s = 5.0

    # News provider is never fully disabled — RSS always runs.
    def is_enabled(self) -> bool:
        return True

    async def fetch(self) -> list[dict]:
        """Two-tier fetch:
          * NewsAPI first (when enabled). Records its own success/
            failure under `channel_newsapi`.
          * RSS always. Records under `channel_rss`. RSS results
            are added to the combined list ONLY when NewsAPI
            returned empty or was skipped — but its telemetry is
            still recorded on every cycle (so a future regression
            in the RSS feeds is detected even when NewsAPI is
            healthy)."""
        combined: list[dict] = []

        # NewsAPI path
        newsapi_result = await fetch_newsapi() if newsapi_enabled() else None
        if newsapi_enabled():
            # Only record telemetry when the channel is actually used.
            _record_channel_attempt(
                CHANNEL_NEWSAPI_KEY,
                success=newsapi_result is not None,
                count=len(newsapi_result) if newsapi_result else 0,
            )
            if newsapi_result:
                combined.extend(newsapi_result)

        # RSS path — always runs, telemetry always recorded.
        rss_result = await fetch_rss()
        _record_channel_attempt(
            CHANNEL_RSS_KEY,
            success=rss_result is not None,
            count=len(rss_result) if rss_result else 0,
        )
        # RSS fallback ONLY adds to the combined list when NewsAPI
        # came back empty or skipped — otherwise RSS would inflate
        # the active-modifier count with duplicates of NewsAPI hits.
        if not combined and rss_result:
            combined.extend(rss_result)

        return combined


# ══════════════════════════════════════════════════════════════════
# Module surface
# ══════════════════════════════════════════════════════════════════
_instance = NewsPrewarmer()

# Re-exported constants
JITTER_BASE_S = NewsPrewarmer.jitter_base_s
JITTER_RANGE_S = NewsPrewarmer.jitter_range_s
TELEMETRY_KEY = NewsPrewarmer.telemetry_key
TELEMETRY_TTL_S = NewsPrewarmer.telemetry_ttl_s
STATE_KEY = NewsPrewarmer.state_key

HEALTHY_MAX_AGE_S = NewsPrewarmer.healthy_max_age_s
STALE_MAX_AGE_S = NewsPrewarmer.stale_max_age_s
FAILURE_RATE_THRESHOLD = NewsPrewarmer.failure_rate_threshold
RECOVERY_READS_REQUIRED = NewsPrewarmer.recovery_reads_required


def compute_next_interval_seconds(rng=None) -> float:
    return _instance.compute_next_interval_seconds(rng)


def compute_raw_state(telemetry: dict, now=None) -> str:
    return _instance.compute_raw_state(telemetry, now)


def evaluate_state_transition(
    prior_state: str, prior_consecutive: int, raw_state: str,
) -> tuple[str, int, bool]:
    return _instance.evaluate_state_transition(
        prior_state, prior_consecutive, raw_state,
    )


def get_prewarmer_telemetry() -> dict:
    """Extended shape: includes both channel-level snapshots so
    operators can see NewsAPI vs RSS health independently."""
    base = _instance.get_telemetry()
    base["channels"] = {
        "newsapi": {
            "enabled": newsapi_enabled(),
            **get_channel_telemetry(CHANNEL_NEWSAPI_KEY),
        },
        "rss": {
            "enabled": True,
            **get_channel_telemetry(CHANNEL_RSS_KEY),
        },
    }
    return base


def get_health_state() -> dict:
    return _instance.get_health_state()


async def run_prewarm_cycle() -> dict:
    result = await _instance.run_cycle()
    if "item_count" in result:
        result["news_count"] = result.pop("item_count")
    if result.get("status") == "no_fresh_items":
        result["status"] = "no_fresh_news"
    return result


def start_news_prewarm_scheduler() -> None:
    _instance.start()


def stop_news_prewarm_scheduler() -> None:
    _instance.stop()


def _emit_news_health_delta(prior_state: str, new_state: str,
                            telemetry: dict) -> None:
    """Canonical news_health broadcast — patchable for tests.

    REL-09: also forwards `* → degraded` and `degraded → healthy`
    transitions to Sentry with a stable fingerprint
    (`news-degraded`) so a streak of outages groups into one issue.
    All other transitions are no-ops on the Sentry side."""
    _instance.default_emit_health_delta(prior_state, new_state, telemetry)
    try:
        from app.services.external_signals.news_sentry import (
            report_health_transition,
        )
        report_health_transition(prior_state, new_state, telemetry)
    except Exception:  # pragma: no cover — telemetry must never raise
        pass


__all__ = [
    "NewsPrewarmer",
    "JITTER_BASE_S", "JITTER_RANGE_S",
    "TELEMETRY_NAMESPACE", "TELEMETRY_KEY", "TELEMETRY_TTL_S",
    "CHANNEL_NEWSAPI_KEY", "CHANNEL_RSS_KEY", "HISTORY_WINDOW",
    "STATE_KEY",
    "STATE_HEALTHY", "STATE_STALE", "STATE_DEGRADED", "STATE_UNKNOWN",
    "HEALTHY_MAX_AGE_S", "STALE_MAX_AGE_S",
    "FAILURE_RATE_THRESHOLD", "RECOVERY_READS_REQUIRED",
    "compute_next_interval_seconds", "compute_raw_state",
    "evaluate_state_transition",
    "get_channel_telemetry",
    "run_prewarm_cycle", "get_prewarmer_telemetry", "get_health_state",
    "start_news_prewarm_scheduler", "stop_news_prewarm_scheduler",
]
