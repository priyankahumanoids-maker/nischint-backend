"""Abstract `ProviderPrewarmer` — common plumbing for every
external-signal pre-warmer.

Extracted before the third provider (News/Social) ships so all
sources share one tested implementation of:

  * cache-preservation rule
  * 4-state health machine + asymmetric hysteresis (3 clean reads
    to recover)
  * telemetry write (last_fetch_ts, last_success_ts,
    parse_failure_rate, active_count, attempt_history)
  * transition-only `system_health_delta` broadcast (silent on
    no-op ticks)
  * SSE-replay history mirroring
  * APScheduler lifecycle (start / stop, idempotent)
  * disabled-mode handling (subclass overrides `is_enabled()` →
    scheduler refuses to register, no Redis writes)

Subclasses declare a handful of class attributes (cache namespace
+ key, jitter bounds, history source name) and one method
(`fetch()`). Everything else is inherited.

The legacy module-level `_emit_<source>_delta` functions in
`sachet_prewarmer.py` and `tomtom_prewarmer.py` are still patchable
by tests — `emit_health_transition` does a runtime lookup through
`sys.modules[type(self).__module__]` so `monkeypatch.setattr(mod,
"_emit_<source>_delta", fake)` wins.
"""
from __future__ import annotations

import logging
import random
import sys
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.services import redis_service

logger = logging.getLogger(__name__)


# ── State machine constants (shared) ─────────────────────────────
STATE_HEALTHY = "healthy"
STATE_STALE = "stale"
STATE_DEGRADED = "degraded"
STATE_UNKNOWN = "unknown"
STATE_DISABLED = "disabled"

# Severity ordering — higher = worse. Regressions snap;
# recoveries gate behind `recovery_reads_required` clean reads.
_SEVERITY: dict[str, int] = {
    STATE_HEALTHY:  0,
    STATE_UNKNOWN:  1,
    STATE_STALE:    2,
    STATE_DEGRADED: 3,
}


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        t = datetime.fromisoformat(s)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return t
    except Exception:
        return None


class ProviderPrewarmer(ABC):
    """Subclass interface (locked):
        * `name` — short label used in log lines
        * `cache_namespace`, `cache_key`, `cache_ttl_s` — parsed-feed
          cache location
        * `telemetry_namespace` — Redis namespace for telemetry +
          state keys (kept separate from the cache so an operator
          flushing the cache namespace doesn't lose health context)
        * `history_source_name` — the bucket name in
          `system_health_history.KNOWN_SOURCES` AND the `source`
          field in the `system_health_delta` envelope. Must appear
          in KNOWN_SOURCES for replay.
        * `jitter_base_s`, `jitter_range_s` — interval and uniform
          jitter range. Subclasses MUST pick values that don't
          collide with sibling providers (tested explicitly).
        * `scheduler_job_id` — unique APScheduler job id.
        * `active_count_field` — name of the per-cycle item count
          stored in telemetry (legacy: `active_alert_count` for
          Sachet, `active_zone_count` for TomTom).
        * `fetch()` — async method returning a non-empty list on
          success or `[]`/`None` on failure. MUST NOT raise; the
          base class wraps anyway as defence-in-depth.
        * `is_enabled()` — defaults True. Subclasses override when
          they require an API key.
    """

    # Subclass MUST set
    name: str = ""
    cache_namespace: str = ""
    cache_key: str = ""
    cache_ttl_s: int = 300
    telemetry_namespace: str = ""
    history_source_name: str = ""
    jitter_base_s: int = 0
    jitter_range_s: int = 0
    scheduler_job_id: str = ""

    # Subclass MAY override
    active_count_field: str = "active_count"
    telemetry_key: str = "telemetry"
    state_key: str = "health_state"
    telemetry_ttl_s: int = 86_400
    history_window: int = 10
    healthy_max_age_s: int = 600
    stale_max_age_s: int = 1800
    failure_rate_threshold: float = 0.20
    recovery_reads_required: int = 3

    # Per-fetch wall-clock budget (seconds). Surfaces as the
    # `timeout_budget_ms` field on `get_telemetry()` and drives the
    # `budget_warning` flag once p95 exceeds 80 % of the budget.
    # Subclasses MUST set this to the *expected per-cycle* timeout
    # — for parallel fan-outs (TomTom) it's the per-zone HTTP
    # timeout; for chains (News NewsAPI+RSS) it's the wall-clock
    # ceiling the operator should care about.
    fetch_timeout_s: float = 0.0

    # Latency rolling window — same size as `history_window` so the
    # two move together. Only successful fetches contribute; a
    # failed fetch has no meaningful latency. p50/p95/p99 are
    # derived at read time in `get_telemetry()`.
    latency_history_key: str = "latency_history"
    BUDGET_WARNING_PCT: float = 80.0          # p95/budget threshold

    def __init__(self):
        self._scheduler: Optional[AsyncIOScheduler] = None

    # ── Subclass hooks ────────────────────────────────────────
    @abstractmethod
    async def fetch(self) -> list[dict] | None:
        """One pre-warm fetch. Non-empty list → success path.
        None/empty list → failure path (cache preserved). Must
        never raise — base wraps as defence-in-depth."""
        raise NotImplementedError

    def is_enabled(self) -> bool:
        """Subclass overrides for API-key-gated providers."""
        return True

    # ── Jitter helper (testable seam) ─────────────────────────
    def compute_next_interval_seconds(
        self, rng: Optional[random.Random] = None,
    ) -> float:
        r = rng or random
        return self.jitter_base_s + r.uniform(
            -self.jitter_range_s, self.jitter_range_s,
        )

    # ── Telemetry I/O ─────────────────────────────────────────
    def _record_attempt(self, success: bool, item_count: int,
                        latency_ms: Optional[float] = None) -> None:
        """Cache-preserving rolling telemetry write. Failure path
        keeps `last_success_ts` and `active_count` from the prior
        successful run — operator UI relies on this asymmetry.

        `latency_ms` semantics: the *caller* decides whether the
        wall-clock is a meaningful signal. `run_cycle` passes
        `None` on the actual failure path (where the wall-clock is
        dominated by the timeout) and a real value on the cache-
        write-failed path (where the fetch succeeded — the latency
        signal is real even though the side effect failed). The
        rolling list is bounded to `history_window` entries."""
        try:
            prior = redis_service.get_json(
                self.telemetry_namespace, self.telemetry_key,
            ) or {}
            history = list(prior.get("attempt_history") or [])
            history.append(bool(success))
            if len(history) > self.history_window:
                history = history[-self.history_window:]
            fails = sum(1 for h in history if not h)
            failure_rate = round(fails / len(history), 4) if history else 0.0

            # Latency window — appended whenever the caller hands
            # us a real wall-clock measurement, regardless of the
            # success bool. Decoupled deliberately so a fetch that
            # succeeded but had its side effect fail still feeds
            # the percentile window.
            lat_history = list(prior.get(self.latency_history_key) or [])
            if latency_ms is not None and latency_ms >= 0:
                lat_history.append(float(latency_ms))
                if len(lat_history) > self.history_window:
                    lat_history = lat_history[-self.history_window:]

            now_iso = datetime.now(timezone.utc).isoformat()
            payload = {
                "last_fetch_ts":      now_iso,
                "last_success_ts":    (
                    now_iso if success
                    else prior.get("last_success_ts")
                ),
                "parse_failure_rate": failure_rate,
                self.active_count_field: (
                    int(item_count) if success
                    else int(prior.get(self.active_count_field, 0) or 0)
                ),
                "attempt_history":    history,
                self.latency_history_key: lat_history,
            }
            redis_service.set_json(
                self.telemetry_namespace, self.telemetry_key,
                payload, ttl=self.telemetry_ttl_s,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "[%s_PREWARMER] telemetry write failed: %r", self.name, e,
            )

    @staticmethod
    def _percentile(sorted_vals: list[float], pct: float) -> Optional[float]:
        """Nearest-rank percentile against a sorted list. None on
        empty input. `pct` is in [0, 100]."""
        if not sorted_vals:
            return None
        n = len(sorted_vals)
        # Ceiling of (pct/100) * n, then clamp to [1, n]; index = that - 1.
        from math import ceil
        rank = max(1, min(n, ceil((pct / 100.0) * n)))
        return float(sorted_vals[rank - 1])

    def _latency_summary(self, lat_history: list[float]) -> dict:
        """Computes p50/p95/p99 + budget-pressure flags at read time.
        Returns a shape with `None` percentiles when there's not
        enough data yet (cold start). `budget_warning` is False
        until at least 3 samples have accumulated — protects
        against a single slow request tripping a false amber on
        an otherwise-healthy provider.

        Malformed entries (None, strings, NaN, negative) are filtered
        — Redis blobs can be tampered with or carry rotted schema
        across deploys; the exporter MUST never raise."""
        clean: list[float] = []
        for v in lat_history or []:
            try:
                f = float(v)
            except (TypeError, ValueError):
                continue
            # Reject NaN/inf and negative latencies — both poison
            # percentile math without surfacing a real signal.
            if f != f or f < 0 or f == float("inf"):
                continue
            clean.append(f)
        if not clean:
            return {
                "latency_p50_ms":      None,
                "latency_p95_ms":      None,
                "latency_p99_ms":      None,
                "latency_sample_size": 0,
                "timeout_budget_ms":   round(self.fetch_timeout_s * 1000, 1)
                                       if self.fetch_timeout_s else None,
                "budget_pressure_pct": None,
                "budget_warning":      False,
            }
        sorted_vals = sorted(clean)
        p50 = self._percentile(sorted_vals, 50)
        p95 = self._percentile(sorted_vals, 95)
        p99 = self._percentile(sorted_vals, 99)
        budget_ms = (
            self.fetch_timeout_s * 1000.0 if self.fetch_timeout_s else None
        )
        pressure_pct = None
        warning = False
        if budget_ms and p95 is not None:
            pressure_pct = round(p95 / budget_ms * 100.0, 1)
            # 3-sample minimum suppresses a single-spike false alarm.
            warning = (
                len(clean) >= 3
                and pressure_pct >= self.BUDGET_WARNING_PCT
            )
        return {
            "latency_p50_ms":      round(p50, 1) if p50 is not None else None,
            "latency_p95_ms":      round(p95, 1) if p95 is not None else None,
            "latency_p99_ms":      round(p99, 1) if p99 is not None else None,
            "latency_sample_size": len(clean),
            "timeout_budget_ms":   round(budget_ms, 1) if budget_ms else None,
            "budget_pressure_pct": pressure_pct,
            "budget_warning":      warning,
        }

    def get_telemetry(self) -> dict:
        """Operator-facing snapshot. `cache_age_seconds` derived at
        read time so a paused scheduler immediately shows growing
        staleness."""
        if not self.is_enabled():
            return {
                "health_state":       STATE_DISABLED,
                "reason":             "no_api_key",
                "last_fetch_ts":      None,
                "last_success_ts":    None,
                "parse_failure_rate": 0.0,
                self.active_count_field: 0,
                "cache_age_seconds":  None,
                "cache_ttl_s":        self.cache_ttl_s,
                "jitter_base_s":      self.jitter_base_s,
                "jitter_range_s":     self.jitter_range_s,
                **self._latency_summary([]),
            }
        raw = redis_service.get_json(
            self.telemetry_namespace, self.telemetry_key,
        ) or {}
        last_success = raw.get("last_success_ts")
        last_success_dt = _parse_iso(last_success)
        cache_age = None
        if last_success_dt is not None:
            cache_age = max(
                0.0,
                (datetime.now(timezone.utc) - last_success_dt).total_seconds(),
            )
        state_blob = redis_service.get_json(
            self.telemetry_namespace, self.state_key,
        ) or {}
        history = raw.get("attempt_history") or []
        return {
            "last_fetch_ts":       raw.get("last_fetch_ts"),
            "last_success_ts":     last_success,
            "parse_failure_rate":  float(raw.get("parse_failure_rate", 0.0)),
            self.active_count_field: int(
                raw.get(self.active_count_field, 0) or 0
            ),
            "cache_age_seconds":   cache_age,
            "cache_ttl_s":         self.cache_ttl_s,
            "attempt_history_size": len(history),
            "history_window":      self.history_window,
            "jitter_base_s":       self.jitter_base_s,
            "jitter_range_s":      self.jitter_range_s,
            "health_state":        state_blob.get("state", STATE_UNKNOWN),
            "recovery_progress":   int(
                state_blob.get("consecutive_better", 0) or 0
            ),
            "recovery_required":   self.recovery_reads_required,
            "last_transition_at":  state_blob.get("last_transition_at"),
            "healthy_max_age_s":   self.healthy_max_age_s,
            "stale_max_age_s":     self.stale_max_age_s,
            "failure_rate_threshold": self.failure_rate_threshold,
            **self._latency_summary(list(raw.get(self.latency_history_key) or [])),
        }

    # ── State machine ─────────────────────────────────────────
    def compute_raw_state(self, telemetry: dict,
                          now: Optional[datetime] = None) -> str:
        last_success_dt = _parse_iso(telemetry.get("last_success_ts"))
        if last_success_dt is None:
            return STATE_UNKNOWN
        failure_rate = float(
            telemetry.get("parse_failure_rate", 0.0) or 0.0
        )
        n = now or datetime.now(timezone.utc)
        age_s = max(0.0, (n - last_success_dt).total_seconds())

        if age_s > self.stale_max_age_s or \
                failure_rate >= self.failure_rate_threshold:
            return STATE_DEGRADED
        if age_s > self.healthy_max_age_s:
            return STATE_STALE
        return STATE_HEALTHY

    def evaluate_state_transition(
        self,
        prior_state: str,
        prior_consecutive: int,
        raw_state: str,
    ) -> tuple[str, int, bool]:
        """Asymmetric hysteresis — regressions snap, recoveries gate
        behind `recovery_reads_required` consecutive clean reads.
        `STATE_UNKNOWN` as the prior treats any transition as
        immediate (first-ever observation from cold start)."""
        prior_sev = _SEVERITY.get(prior_state, _SEVERITY[STATE_UNKNOWN])
        raw_sev = _SEVERITY.get(raw_state, _SEVERITY[STATE_UNKNOWN])

        if raw_state == prior_state:
            return prior_state, 0, False

        if raw_sev >= prior_sev or prior_state == STATE_UNKNOWN:
            return raw_state, 0, True

        new_counter = prior_consecutive + 1
        if new_counter >= self.recovery_reads_required:
            return raw_state, 0, True
        return prior_state, new_counter, False

    def _read_state(self) -> tuple[str, int]:
        blob = redis_service.get_json(
            self.telemetry_namespace, self.state_key,
        ) or {}
        return (
            blob.get("state", STATE_UNKNOWN),
            int(blob.get("consecutive_better", 0) or 0),
        )

    def _write_state(self, state: str, consecutive: int,
                     transitioned: bool, prior_state: str) -> None:
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            prior_blob = redis_service.get_json(
                self.telemetry_namespace, self.state_key,
            ) or {}
            payload = {
                "state":              state,
                "consecutive_better": int(consecutive),
                "last_transition_at": (
                    now_iso if transitioned
                    else prior_blob.get("last_transition_at")
                ),
                "prior_state":        (
                    prior_state if transitioned
                    else prior_blob.get("prior_state")
                ),
            }
            redis_service.set_json(
                self.telemetry_namespace, self.state_key,
                payload, ttl=self.telemetry_ttl_s,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "[%s_PREWARMER] state write failed: %r", self.name, e,
            )

    def get_health_state(self) -> dict:
        if not self.is_enabled():
            return {
                "state":               STATE_DISABLED,
                "reason":              "no_api_key",
                "consecutive_better":  0,
                "recovery_required":   self.recovery_reads_required,
                "last_transition_at":  None,
                "prior_state":         None,
            }
        state, counter = self._read_state()
        blob = redis_service.get_json(
            self.telemetry_namespace, self.state_key,
        ) or {}
        return {
            "state":              state,
            "consecutive_better": counter,
            "recovery_required":  self.recovery_reads_required,
            "last_transition_at": blob.get("last_transition_at"),
            "prior_state":        blob.get("prior_state"),
        }

    # ── Broadcast (transition-only) ───────────────────────────
    def _build_health_payload(self, prior_state: str, new_state: str,
                              telemetry: dict) -> dict:
        """Standard envelope. Subclasses MAY override only to add
        provider-specific fields inside the nested block — must keep
        the outer envelope shape stable for the operator UI."""
        nested = {
            "state":              new_state,
            "previous_state":     prior_state,
            "cache_age_seconds":  telemetry.get("cache_age_seconds"),
            "parse_failure_rate": telemetry.get("parse_failure_rate"),
            self.active_count_field: telemetry.get(self.active_count_field),
            "last_success_ts":    telemetry.get("last_success_ts"),
        }
        return {
            "type":              "system_health_delta",
            "ts":                int(datetime.now(timezone.utc).timestamp()),
            "iso":               datetime.now(timezone.utc).isoformat(),
            "source":            self.history_source_name,
            "severity":          (
                "warning" if new_state in (STATE_STALE, STATE_UNKNOWN)
                else ("critical" if new_state == STATE_DEGRADED else "healthy")
            ),
            "previous_severity": (
                "warning" if prior_state in (STATE_STALE, STATE_UNKNOWN)
                else ("critical" if prior_state == STATE_DEGRADED
                      else "healthy")
            ),
            self.history_source_name: nested,
        }

    def default_emit_health_delta(self, prior_state: str, new_state: str,
                                  telemetry: dict) -> None:
        """Canonical broadcast: builds the envelope, mirrors to the
        replay-tail history, schedules the WS broadcast. Called by
        the module-level `_emit_<source>_delta` shim so tests that
        `monkeypatch.setattr(mod, "_emit_<source>_delta", ...)` still
        intercept the call."""
        payload = self._build_health_payload(
            prior_state, new_state, telemetry,
        )
        # Mirror to history (best-effort, never blocks).
        try:
            from app.services.system_health_history import record_transition
            record_transition(self.history_source_name, payload)
        except Exception:
            logger.debug("%s history write skipped", self.history_source_name)

        # Broadcast over WS.
        try:
            from app.services.event_broadcaster import broadcaster
        except Exception:
            return

        async def _send():
            try:
                await broadcaster.broadcast_to_operators(
                    "system_health_delta", payload,
                )
            except Exception:
                logger.exception(
                    "%s delta broadcast failed", self.history_source_name,
                )

        try:
            import asyncio as _asyncio
            loop = _asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_send())
            else:
                _asyncio.run(_send())
        except RuntimeError:
            try:
                import asyncio as _asyncio
                _asyncio.new_event_loop().run_until_complete(_send())
            except Exception:
                logger.debug(
                    "%s delta emit could not schedule send",
                    self.history_source_name,
                )

    def emit_health_transition(self, prior_state: str, new_state: str,
                               telemetry: dict) -> None:
        """Indirection that lets module-level shims (and test
        monkeypatches) intercept the broadcast. Looks up
        `_emit_<source>_delta` in the subclass's defining module
        and calls it; falls back to `default_emit_health_delta`."""
        module = sys.modules.get(type(self).__module__)
        fn_name = f"_emit_{self.history_source_name}_delta"
        fn = getattr(module, fn_name, None)
        if callable(fn):
            fn(prior_state, new_state, telemetry)
        else:
            self.default_emit_health_delta(
                prior_state, new_state, telemetry,
            )

    # ── Orchestration ─────────────────────────────────────────
    def _evaluate_and_persist_health(self) -> tuple[str, str, bool]:
        """Compute raw state from the just-written telemetry, apply
        hysteresis, persist, broadcast on transition. Returns
        (prior_state, new_state, transitioned)."""
        telemetry = self.get_telemetry()
        raw = self.compute_raw_state(telemetry)
        prior_state, prior_counter = self._read_state()
        new_state, new_counter, transitioned = self.evaluate_state_transition(
            prior_state, prior_counter, raw,
        )
        self._write_state(new_state, new_counter, transitioned, prior_state)
        if transitioned:
            self.emit_health_transition(prior_state, new_state, telemetry)
            logger.info(
                "[%s_PREWARMER] state %s → %s (raw=%s)",
                self.name, prior_state, new_state, raw,
            )
        return prior_state, new_state, transitioned

    async def run_cycle(self) -> dict:
        """One pre-warm cycle. Never raises. Contract:
          * non-empty fetch → overwrite cache, mark success
          * empty / raised → cache untouched, mark failure
          * provider disabled → no-op, no Redis writes

        Wall-clock of `self.fetch()` is measured and recorded as
        `latency_ms` on the success path so the operator chip can
        surface budget pressure BEFORE failures start."""
        import time as _time

        if not self.is_enabled():
            return {"status": "disabled", "reason": "no_api_key"}

        items: list = []
        raised = False
        t0 = _time.monotonic()
        try:
            result = await self.fetch()
            items = list(result) if result else []
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "[%s_PREWARMER] fetch raised: %r", self.name, e,
            )
            raised = True
            items = []
        latency_ms = (_time.monotonic() - t0) * 1000.0

        if items:
            try:
                redis_service.set_json(
                    self.cache_namespace, self.cache_key,
                    items, ttl=self.cache_ttl_s,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "[%s_PREWARMER] cache write failed: %r",
                    self.name, e,
                )
                # Cache write failure is NOT a fetch-latency event —
                # the fetch already succeeded. Record latency, but
                # mark the attempt as failure so the cache-write
                # failure surfaces in `parse_failure_rate`.
                self._record_attempt(
                    success=False, item_count=0, latency_ms=latency_ms,
                )
                self._evaluate_and_persist_health()
                return {
                    "status": "cache_write_failed",
                    "item_count": len(items),
                }
            self._record_attempt(
                success=True, item_count=len(items), latency_ms=latency_ms,
            )
            self._evaluate_and_persist_health()
            logger.info(
                "[%s_PREWARMER] cache refreshed items=%d latency_ms=%.0f",
                self.name, len(items), latency_ms,
            )
            return {"status": "success", "item_count": len(items)}

        # Failure path — DO NOT record latency. A failed fetch's
        # wall-clock is dominated by the timeout itself, which
        # would poison the rolling p95.
        self._record_attempt(success=False, item_count=0, latency_ms=None)
        self._evaluate_and_persist_health()
        logger.info(
            "[%s_PREWARMER] cache preserved (no fresh items, raised=%s)",
            self.name, raised,
        )
        return {
            "status": "no_fresh_items",
            "item_count": 0,
            "raised": raised,
        }

    # ── Scheduler lifecycle ───────────────────────────────────
    def start(self) -> None:
        if not self.is_enabled():
            logger.info(
                "[%s_PREWARMER] not starting — disabled (e.g. no API key)",
                self.name,
            )
            return
        if self._scheduler is not None:
            logger.info("[%s_PREWARMER] already running", self.name)
            return
        self._scheduler = AsyncIOScheduler()
        trigger = IntervalTrigger(
            seconds=self.jitter_base_s,
            jitter=self.jitter_range_s,
        )
        self._scheduler.add_job(
            self.run_cycle,
            trigger=trigger,
            id=self.scheduler_job_id,
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        self._scheduler.start()
        logger.info(
            "[%s_PREWARMER] started — interval=%ds ± %ds",
            self.name, self.jitter_base_s, self.jitter_range_s,
        )

    def stop(self) -> None:
        if self._scheduler is None:
            return
        try:
            self._scheduler.shutdown(wait=False)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "[%s_PREWARMER] shutdown failed: %r", self.name, e,
            )
        finally:
            self._scheduler = None


__all__ = [
    "STATE_HEALTHY", "STATE_STALE", "STATE_DEGRADED", "STATE_UNKNOWN",
    "STATE_DISABLED",
    "ProviderPrewarmer",
]
