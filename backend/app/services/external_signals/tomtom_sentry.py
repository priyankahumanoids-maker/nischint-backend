"""Sentry observability hooks for the TomTom Traffic Flow provider.

Mirrors `sachet_sentry.py` exactly so a single Sentry filter
(`provider=tomtom`) renders the TomTom degradation timeline the
same way the operator already reads the NDMA one.

Stable fingerprint `["tomtom-degraded"]` groups repeat outages into
one Sentry issue (count + first-seen + last-seen) instead of one
issue per failure spike.

Tests monkeypatch `_sentry` here — same hook point pattern as
`sachet_sentry._sentry`.
"""
from __future__ import annotations

from typing import Any, Optional

from app.services.external_signals import _provider_sentry_base as _base


_DEGRADED_FINGERPRINT = ["tomtom-degraded"]
_CONTEXT_KEY = "tomtom_fetch"
_HEALTH_CONTEXT_KEY = "tomtom_health"
_METRIC_NAME = "tomtom.fetch.failure"
_PROVIDER_TAG = "tomtom"

# Fields a responder actually wants on the Sentry context tab for
# TomTom health transitions. Mirrors `sachet_sentry._telemetry_context`.
_TELEMETRY_KEYS = (
    "health_state",
    "active_zone_count",
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
    """Lazy import — kept module-local so tests can monkeypatch it
    the same way they do `sachet_sentry._sentry`."""
    try:
        import sentry_sdk
        return sentry_sdk
    except Exception:  # pragma: no cover — import guard
        return None


def report_fetch_failure(
    *,
    status_code: Optional[int],
    upstream_url: str,
    response_time_ms: Optional[float],
    is_proxy: bool,
    colo: Optional[str] = None,
    error: Optional[str] = None,
    zone: Optional[str] = None,
) -> None:
    """Capture a single failed TomTom Flow probe.

    `zone` is the only TomTom-specific extra — surfaced as a tag AND
    context field so operators can see whether one specific city is
    flapping or it's a global outage.
    """
    extra_tags = {"zone": zone} if zone else None
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
        extra_tags=extra_tags,
    )


def report_health_transition(
    prior_state: str,
    new_state: str,
    telemetry: dict[str, Any],
) -> None:
    """Capture TomTom prewarmer health-state transitions. Same
    fingerprint-based grouping as SACHET; only `* → degraded` and
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
