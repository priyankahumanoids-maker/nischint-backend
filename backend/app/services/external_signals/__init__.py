"""NISCH-012.0 — External signal provider abstraction.

Strict scope:
  * `ExternalSignal` — the on-the-wire shape every provider returns.
  * `ExternalSignalProvider` — abstract base class (fail-quiet contract).
  * `freshness_decay()` — pure decay function. Stale rain alerts must
    NOT silently poison confidence; this is enforced here.

Engineering rules locked at this layer:
  1. **Fail-quiet** — every method returns `Optional`, never raises.
     The alert pipeline must never block on external infra outages.
  2. **Hard timeout** — `PROVIDER_TIMEOUT_S = 1.5`. Any provider that
     can't answer in 1.5s gets dropped from the batch. External
     intelligence must enhance reliability, never reduce it.
  3. **TTL is mandatory** — every signal carries `ttl_s` so the
     consumer can decay it. There is no "permanent" external signal.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


# Hard timeout for any single provider. Wrapped at the registry layer
# with `asyncio.wait_for`. Tuned so even if 4 providers run in parallel
# and ALL time out, total budget on the alert hot-path is < 1.6s
# (concurrent fan-out, not serial).
PROVIDER_TIMEOUT_S = 1.5

# Below this freshness fraction, a signal is treated as having zero
# influence regardless of its raw risk. Defends against a Sachet
# alert that fired 18 hours ago and was technically still in its
# `expires` window at last fetch.
FRESHNESS_FLOOR = 0.05


class ExternalSignal(BaseModel):
    """One observation from one provider. The contract is intentionally
    narrow: a normalised 0..1 risk + the human-readable factors that
    drove it + the freshness window."""
    provider:    str = Field(..., description="weather|traffic|sachet|news")
    signal_type: str = Field(..., description="storm_risk|congestion|cyclone|...")
    risk_0_1:    float = Field(..., ge=0.0, le=1.0)
    factors:     list[str] = Field(default_factory=list)
    confidence:  float = Field(0.9, ge=0.0, le=1.0,
                               description="how much we trust this provider's data right now")
    fetched_at:  datetime
    ttl_s:       int = Field(..., gt=0,
                             description="seconds until this signal is fully decayed")
    raw_url:     Optional[str] = None  # forensic linkback


def freshness_decay(signal: ExternalSignal,
                    now: Optional[datetime] = None) -> float:
    """Return a 0..1 decay multiplier based on signal age.

    Linear decay from 1.0 at fetch_time to 0.0 at fetch_time + ttl_s.
    Below FRESHNESS_FLOOR the multiplier is clamped to 0 — a stale
    signal must NOT silently poison confidence with a sliver of bump.

    Pure function — no I/O — locked behaviour for the modifier tests."""
    n = now or datetime.now(timezone.utc)
    fetched = signal.fetched_at
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    age_s = max(0.0, (n - fetched).total_seconds())
    if age_s >= signal.ttl_s:
        return 0.0
    fresh = 1.0 - (age_s / float(signal.ttl_s))
    if fresh < FRESHNESS_FLOOR:
        return 0.0
    return round(fresh, 4)


class ExternalSignalProvider(ABC):
    """Subclass once per upstream feed.

    Subclasses must:
      * set `name` (matches the `provider` field on ExternalSignal)
      * implement `_fetch_unsafe()` — may raise; the registry wraps
        it in a fail-quiet boundary.

    Subclasses MUST NOT:
      * directly call asyncio.wait_for or set their own timeout —
        the registry owns the timeout boundary so a misbehaving
        provider can't bypass it.
      * raise from `is_enabled()` — return False silently if the
        env var is missing."""

    name: str = ""

    def is_enabled(self) -> bool:
        """Defaults to True. Override in providers that require an
        env-var key (return False when the key is missing)."""
        return True

    @abstractmethod
    async def _fetch_unsafe(
        self, lat: float, lng: float,
        when: Optional[datetime] = None,
    ) -> Optional[ExternalSignal]:
        """May raise; the registry will swallow any exception and
        log it. Returning None is the explicit "no signal here" path."""
        ...


__all__ = [
    "PROVIDER_TIMEOUT_S",
    "FRESHNESS_FLOOR",
    "ExternalSignal",
    "ExternalSignalProvider",
    "freshness_decay",
]
