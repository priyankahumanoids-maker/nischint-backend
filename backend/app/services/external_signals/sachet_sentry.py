"""REL-09 — Sentry observability hooks for SACHET (NDMA) outages.

Single place for every Sentry call we make on behalf of the SACHET
provider/prewarmer. Why a dedicated module:
  • Keeps the Sentry SDK out of the hot HTTP path in `sachet_provider`
    — that module stays unit-testable without a Sentry stub.
  • Gives us ONE patch target in tests (`monkeypatch.setattr` here
    instead of chasing imports across two files).
  • Every helper is defensive: if Sentry isn't configured / its SDK
    raises / its metrics module is absent in this runtime, the call
    becomes a silent no-op. The SACHET path must NEVER fail because
    of telemetry.

Conventions:
  • All warnings carry the tag `provider=sachet` and `via_proxy=...`
    so a single Sentry filter shows the NDMA outage timeline.
  • The transition event uses a stable `fingerprint = ["sachet-degraded"]`
    so repeat outages group into ONE Sentry issue with hit count +
    duration, instead of one issue per occurrence.
  • Recovery emits a separate `level=info` message — Sentry treats
    these as auto-resolving and they show up in the timeline of the
    grouped issue.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


# Stable issue grouping for repeated NDMA outages. We deliberately
# use one fingerprint regardless of HTTP code so a 504 streak and a
# 502 streak land on the same issue — the operator wants the trend,
# not five identical-looking tickets.
_DEGRADED_FINGERPRINT = ["sachet-degraded"]


def _sentry():
    """Lazy import — `sentry_sdk` is heavyweight and only needed when
    the runtime actually has Sentry configured. Returns `None` if the
    import fails."""
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
) -> None:
    """Capture a single failed NDMA fetch.

    Severity is `warning` (not `error`) — NDMA failure is degraded,
    not broken; the operator dashboard already conveys it. We want
    the Sentry timeline for trend analysis, not pager noise.

    A counter metric is also incremented (best-effort) so the Sentry
    dashboard can chart fetch-failure-rate by status_code +
    via_proxy tag.
    """
    sdk = _sentry()
    if sdk is None:
        return

    # ── 1. Capture a contextual warning ──────────────────────────
    try:
        with sdk.push_scope() as scope:
            scope.set_tag("provider", "sachet")
            scope.set_tag("via_proxy", "true" if is_proxy else "false")
            scope.set_tag("status_code", str(status_code) if status_code is not None else "exception")
            if colo:
                scope.set_tag("cf_colo", colo)
            scope.set_context("sachet_fetch", {
                "upstream_url":     upstream_url,
                "status_code":      status_code,
                "response_time_ms": round(response_time_ms, 2) if response_time_ms is not None else None,
                "is_proxy":         is_proxy,
                "colo":             colo,
                "error":            error,
            })
            # Sentry's default grouping key is the message + stack; we
            # don't fingerprint per-failure to avoid drowning the
            # `sachet-degraded` grouping above. Repeated identical
            # status codes group naturally on message text.
            msg = (
                f"SACHET fetch failed status={status_code} via_proxy={is_proxy}"
                if status_code is not None
                else f"SACHET fetch exception via_proxy={is_proxy}"
            )
            sdk.capture_message(msg, level="warning")
    except Exception as e:  # pragma: no cover — best-effort
        logger.debug(f"[sentry] capture failure (ignored): {e}")

    # ── 2. Custom metric — `sachet.fetch.failure` ────────────────
    try:
        metrics = getattr(sdk, "metrics", None)
        if metrics is not None and hasattr(metrics, "incr"):
            metrics.incr(
                "sachet.fetch.failure",
                tags={
                    "status_code": str(status_code) if status_code is not None else "exception",
                    "via_proxy":   "true" if is_proxy else "false",
                },
            )
    except Exception as e:  # pragma: no cover
        logger.debug(f"[sentry-metrics] incr failed (ignored): {e}")


def report_health_transition(
    prior_state: str,
    new_state: str,
    telemetry: dict[str, Any],
) -> None:
    """Capture prewarmer health-state transitions on the SACHET source.

    Two interesting edges:
      • `* → degraded` : an outage just opened. Capture with
        `fingerprint = ["sachet-degraded"]` so all opens group into
        one Sentry issue. Sentry shows the count + first-seen +
        last-seen automatically.
      • `degraded → healthy` : the outage just closed. Emit an
        `info` message tagged with the same fingerprint so it appears
        on the same issue's timeline — gives the duration "for free".

    Every other transition (`unknown ↔ stale` etc.) is a no-op here —
    we don't want operational noise for in-window flaps.
    """
    sdk = _sentry()
    if sdk is None:
        return

    try:
        if new_state == "degraded" and prior_state != "degraded":
            with sdk.push_scope() as scope:
                scope.set_tag("provider", "sachet")
                scope.set_tag("transition", f"{prior_state}->{new_state}")
                scope.fingerprint = _DEGRADED_FINGERPRINT
                scope.set_context("sachet_health", _telemetry_context(telemetry))
                sdk.capture_message(
                    "SACHET prewarmer flipped to degraded",
                    level="warning",
                )
        elif new_state == "healthy" and prior_state == "degraded":
            with sdk.push_scope() as scope:
                scope.set_tag("provider", "sachet")
                scope.set_tag("transition", f"{prior_state}->{new_state}")
                # Same fingerprint so Sentry groups the recovery
                # message under the open outage issue → operators
                # see the resolution event on that issue's timeline
                # without having to hunt for it.
                scope.fingerprint = _DEGRADED_FINGERPRINT
                scope.set_context("sachet_health", _telemetry_context(telemetry))
                sdk.capture_message(
                    "SACHET prewarmer recovered to healthy",
                    level="info",
                )
    except Exception as e:  # pragma: no cover
        logger.debug(f"[sentry] transition capture failed (ignored): {e}")


def _telemetry_context(telemetry: dict[str, Any]) -> dict[str, Any]:
    """Project the prewarmer telemetry down to the fields a responder
    actually wants on the Sentry context tab. Excluding the rest
    keeps issue diffs readable (Sentry highlights changed context
    fields between issue events).
    """
    keys_we_care_about = (
        "health_state",
        "active_alert_count",
        "consecutive_failures",
        "consecutive_successes",
        "last_success_ts",
        "last_failure_ts",
        "last_fetch_ts",
        "cache_age_seconds",
        "parse_failure_rate",
        "recovery_progress",
    )
    return {k: telemetry.get(k) for k in keys_we_care_about if k in telemetry}


__all__ = [
    "report_fetch_failure",
    "report_health_transition",
]
