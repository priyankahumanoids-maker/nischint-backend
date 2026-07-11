"""Sentry observability hooks for the News (NewsAPI + RSS) provider.

Two upstream channels — NewsAPI (paid, when key is set) and RSS
(always-on fallback). Each call site tags `channel` so operators
can tell which channel is degrading even when the overall provider
state machine still reads healthy (RSS can mask a NewsAPI outage
in the combined view).

Stable fingerprint `["news-degraded"]` groups repeat outages into
one Sentry issue.

Tests monkeypatch `_sentry` here — same hook point pattern as
`sachet_sentry._sentry`.
"""
from __future__ import annotations

from typing import Any, Optional

from app.services.external_signals import _provider_sentry_base as _base


_DEGRADED_FINGERPRINT = ["news-degraded"]
_CONTEXT_KEY = "news_fetch"
_HEALTH_CONTEXT_KEY = "news_health"
_METRIC_NAME = "news.fetch.failure"
_PROVIDER_TAG = "news"

_TELEMETRY_KEYS = (
    "health_state",
    "active_news_count",
    "consecutive_failures",
    "consecutive_successes",
    "last_success_ts",
    "last_failure_ts",
    "last_fetch_ts",
    "cache_age_seconds",
    "parse_failure_rate",
    "recovery_progress",
)


def _sentry():
    """Lazy import — module-local so tests can monkeypatch."""
    try:
        import sentry_sdk
        return sentry_sdk
    except Exception:  # pragma: no cover
        return None


def report_fetch_failure(
    *,
    status_code: Optional[int],
    upstream_url: str,
    response_time_ms: Optional[float],
    is_proxy: bool = False,
    colo: Optional[str] = None,
    error: Optional[str] = None,
    channel: Optional[str] = None,
    feed: Optional[str] = None,
) -> None:
    """Capture a single failed news fetch.

    `channel` ∈ `newsapi` | `rss` — required tag.
    `feed` is set on RSS failures so the operator can see which
    specific feed (`ndtv` | `toi`) is degrading.
    """
    extra: dict[str, str] = {}
    if channel:
        extra["channel"] = channel
    if feed:
        extra["feed"] = feed
    _base.emit_fetch_failure(
        sentry_factory=_sentry,
        provider_tag=_PROVIDER_TAG,
        context_key=_CONTEXT_KEY,
        metric_name=_METRIC_NAME,
        status_code=status_code,
        upstream_url=upstream_url,
        response_time_ms=response_time_ms,
        is_proxy=is_proxy,
        colo=colo,
        error=error,
        extra_tags=extra or None,
    )


def report_health_transition(
    prior_state: str,
    new_state: str,
    telemetry: dict[str, Any],
) -> None:
    """Capture news prewarmer health-state transitions. Same
    fingerprint-grouping as SACHET; only `* → degraded` and
    `degraded → healthy` emit."""
    _base.emit_health_transition(
        sentry_factory=_sentry,
        provider_tag=_PROVIDER_TAG,
        context_key=_HEALTH_CONTEXT_KEY,
        fingerprint=_DEGRADED_FINGERPRINT,
        telemetry_keys=_TELEMETRY_KEYS,
        prior_state=prior_state,
        new_state=new_state,
        telemetry=telemetry,
    )


__all__ = [
    "report_fetch_failure",
    "report_health_transition",
]
