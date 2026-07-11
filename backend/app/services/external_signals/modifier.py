"""NISCH-012.0 — Confidence modifier math.

Pure function over a list of `ExternalSignal`s. Owns:
  * The threshold (HIGH_SIGNAL_THRESHOLD = 0.6) — sub-threshold
    signals are noise and contribute zero.
  * The freshness decay — applied per-signal before contribution.
  * The additive cap (CONFIDENCE_BUMP_CAP = 0.20) — multiplicative
    compounding rejected by design (compounds badly when 3+ signals
    fire). Hard cap is bounded and explainable.
  * The full audit envelope persisted into safety_incidents.extra
    so the timeline can show "confidence 0.78 → 0.93 because…".

Audit shape (locked — UI consumes this):
    {
        "fetched_at":          ISO8601 UTC,
        "confidence_before":   float,
        "confidence_after":    float,
        "modifier_applied":    float,    # confidence_after - confidence_before
        "modifier_capped":     bool,
        "providers": [
            {
                "provider":     "weather",
                "signal_type":  "heavy_rain",
                "factors":      ["heavy_rain", "low_visibility"],
                "raw_risk":     0.50,
                "freshness":    0.92,
                "effective":    0.46,    # raw_risk * freshness
                "delta":        0.046,   # actual contribution (post-cap)
                "applied":      true,
                "ttl_s":        600,
                "raw_url":      null
            },
            ...
        ]
    }
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.services.external_signals import (
    ExternalSignal, freshness_decay,
)


# Tunables — locked by tests so an accidental tweak fails CI.
HIGH_SIGNAL_THRESHOLD       = 0.6   # below this, signals are dropped
CONFIDENCE_BUMP_PER_SIGNAL  = 0.10  # max single-signal contribution
CONFIDENCE_BUMP_CAP         = 0.20  # max total bump regardless of signal count
CONFIDENCE_FLOOR            = 0.0
CONFIDENCE_CEIL             = 0.99


def apply_external_modifiers(
    base_confidence: float,
    signals: list[ExternalSignal],
    *,
    now: Optional[datetime] = None,
) -> tuple[float, dict]:
    """Return (modified_confidence, audit_envelope).

    Pure function. Order of `signals` does not matter — internally we
    sort by descending effective risk so the strongest signal claims
    its share of the bump cap first.
    """
    n = now or datetime.now(timezone.utc)
    base = float(base_confidence or 0.0)

    audit_envelope: dict = {
        "fetched_at":        n.isoformat(),
        "confidence_before": round(base, 4),
        "confidence_after":  round(base, 4),
        "modifier_applied":  0.0,
        "modifier_capped":   False,
        "providers":         [],
    }
    if not signals:
        return base, audit_envelope

    # Compute (effective, signal) pairs, dropping sub-threshold up front.
    scored: list[tuple[float, ExternalSignal, float, float]] = []
    for sig in signals:
        fresh = freshness_decay(sig, n)
        effective = float(sig.risk_0_1) * fresh
        scored.append((effective, sig, fresh, float(sig.risk_0_1)))

    scored.sort(key=lambda t: -t[0])

    bump_total = 0.0
    capped = False
    for effective, sig, fresh, raw in scored:
        provider_row = {
            "provider":    sig.provider,
            "signal_type": sig.signal_type,
            "factors":     list(sig.factors),
            "raw_risk":    round(raw, 4),
            "freshness":   round(fresh, 4),
            "effective":   round(effective, 4),
            "delta":       0.0,
            "applied":     False,
            "ttl_s":       int(sig.ttl_s),
            "raw_url":     sig.raw_url,
        }

        if effective < HIGH_SIGNAL_THRESHOLD:
            provider_row["reason_skipped"] = (
                "stale" if fresh == 0.0 else "below_threshold"
            )
            audit_envelope["providers"].append(provider_row)
            continue

        if bump_total >= CONFIDENCE_BUMP_CAP:
            capped = True
            provider_row["reason_skipped"] = "cap_reached"
            audit_envelope["providers"].append(provider_row)
            continue

        # Per-signal contribution: scale the per-signal max by the
        # effective risk so a 0.6 effective contributes less than a
        # 0.95 effective. Then clamp to the remaining headroom.
        per_signal = CONFIDENCE_BUMP_PER_SIGNAL * effective
        headroom = CONFIDENCE_BUMP_CAP - bump_total
        contribution = min(per_signal, headroom)
        if contribution + bump_total >= CONFIDENCE_BUMP_CAP:
            capped = True

        bump_total += contribution
        provider_row["delta"] = round(contribution, 4)
        provider_row["applied"] = True
        audit_envelope["providers"].append(provider_row)

    new_conf = max(CONFIDENCE_FLOOR,
                   min(CONFIDENCE_CEIL, base + bump_total))
    audit_envelope["confidence_after"]  = round(new_conf, 4)
    audit_envelope["modifier_applied"]  = round(new_conf - base, 4)
    audit_envelope["modifier_capped"]   = capped
    return new_conf, audit_envelope


__all__ = [
    "HIGH_SIGNAL_THRESHOLD",
    "CONFIDENCE_BUMP_PER_SIGNAL",
    "CONFIDENCE_BUMP_CAP",
    "CONFIDENCE_CEIL",
    "apply_external_modifiers",
]
