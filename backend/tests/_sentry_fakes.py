"""REL-09 fan-out — shared fake Sentry SDK fixtures.

Used by the per-provider sentry tests (tomtom / weather / news /
owm_alerts) to assert what got captured. Mirrors the in-test
`_FakeSentry` defined in `test_sachet_sentry.py` but lives in a
shared module so we don't drift between providers.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any


class _FakeScope:
    def __init__(self, recorder: dict[str, Any]):
        self._rec = recorder
        self._rec["scope_tags"] = {}
        self._rec["scope_contexts"] = {}
        self._rec["scope_fingerprint"] = None

    def set_tag(self, k, v):
        self._rec["scope_tags"][k] = v

    def set_context(self, k, v):
        self._rec["scope_contexts"][k] = v

    @property
    def fingerprint(self):
        return self._rec["scope_fingerprint"]

    @fingerprint.setter
    def fingerprint(self, v):
        self._rec["scope_fingerprint"] = v


class _FakeMetrics:
    def __init__(self):
        self.counters: list[tuple[str, dict]] = []

    def incr(self, name, *, tags=None, **_):
        self.counters.append((name, dict(tags or {})))


class FakeSentry:
    """Minimal Sentry SDK stand-in. Records every captured event +
    every metric counter call. Compatible with the production
    `sentry_sdk` surface we use (push_scope / capture_message /
    metrics.incr)."""

    def __init__(self):
        self.events: list[dict[str, Any]] = []
        self.metrics = _FakeMetrics()
        self._pending: dict[str, Any] = {}

    @contextmanager
    def push_scope(self):
        rec: dict[str, Any] = {}
        scope = _FakeScope(rec)
        self._pending = rec
        try:
            yield scope
        finally:
            self._pending = rec

    def capture_message(self, msg, level="warning"):
        snap = {
            "msg": msg,
            "level": level,
            "tags": dict(self._pending.get("scope_tags", {})),
            "contexts": dict(self._pending.get("scope_contexts", {})),
            "fingerprint": self._pending.get("scope_fingerprint"),
        }
        self.events.append(snap)
