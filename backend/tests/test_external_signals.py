"""NISCH-012.0 — External signal modifier + freshness decay tests.

Pure-unit + integration. Modifier and decay are pure functions — no
DB, no network — so we test the math first, then exercise the
end-to-end persistence through `open_incident_for_alert`.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import (
    AsyncSession, async_sessionmaker, create_async_engine,
)

from app.models.safety_incident import SafetyIncident
from app.models.safety_incident_event import SafetyIncidentEvent
from app.services.external_signals import (
    FRESHNESS_FLOOR, PROVIDER_TIMEOUT_S,
    ExternalSignal, ExternalSignalProvider, freshness_decay,
)
from app.services.external_signals.modifier import (
    CONFIDENCE_BUMP_CAP, CONFIDENCE_BUMP_PER_SIGNAL,
    HIGH_SIGNAL_THRESHOLD, apply_external_modifiers,
)
from app.services.external_signals.registry import (
    _reset_providers_to_default, _set_providers_for_test,
    fetch_all_signals,
)


def _db_url() -> str:
    from app.core.config import settings
    url = settings.database_url or ""
    if not url:
        pytest.skip("database_url not set")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://") and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if "sslmode=" in url:
        url = url.split("?")[0]
    return url


@pytest_asyncio.fixture
async def db():
    eng = create_async_engine(_db_url(), poolclass=NullPool,
                              connect_args={"ssl": True})
    factory = async_sessionmaker(eng, expire_on_commit=False)
    yield factory
    await eng.dispose()


def _sig(provider="weather", risk=0.8, ttl=600,
         age_s=0, factors=None, signal_type="storm_risk"):
    return ExternalSignal(
        provider=provider,
        signal_type=signal_type,
        risk_0_1=risk,
        factors=factors or ["heavy_rain"],
        confidence=0.9,
        fetched_at=datetime.now(timezone.utc) - timedelta(seconds=age_s),
        ttl_s=ttl,
    )


# ════════════════════════════════════════════════════════════════════
# Constants locked
# ════════════════════════════════════════════════════════════════════

def test_constants_locked():
    """Defends against accidental tuning that would let a single weak
    signal bump confidence by 50%."""
    assert HIGH_SIGNAL_THRESHOLD       == 0.6
    assert CONFIDENCE_BUMP_PER_SIGNAL  == 0.10
    assert CONFIDENCE_BUMP_CAP         == 0.20
    assert PROVIDER_TIMEOUT_S          == 1.5
    assert FRESHNESS_FLOOR             == 0.05


# ════════════════════════════════════════════════════════════════════
# Freshness decay
# ════════════════════════════════════════════════════════════════════

def test_freshness_full_when_fresh():
    sig = _sig(age_s=0, ttl=600)
    assert freshness_decay(sig) == 1.0


def test_freshness_zero_when_expired():
    sig = _sig(age_s=601, ttl=600)
    assert freshness_decay(sig) == 0.0


def test_freshness_linear_at_midpoint():
    sig = _sig(age_s=300, ttl=600)
    fresh = freshness_decay(sig)
    assert 0.49 <= fresh <= 0.51, f"got {fresh}"


def test_freshness_clamps_below_floor():
    """Stale rain alerts must NOT silently poison confidence — the
    floor (5%) snaps to 0 once we approach the TTL boundary."""
    # 99% expired → 1% remaining → below 5% floor → must be 0.
    sig = _sig(age_s=int(600 * 0.99), ttl=600)
    assert freshness_decay(sig) == 0.0


# ════════════════════════════════════════════════════════════════════
# Modifier math
# ════════════════════════════════════════════════════════════════════

def test_modifier_no_signals_returns_base():
    new_conf, audit = apply_external_modifiers(0.50, [])
    assert new_conf == 0.50
    assert audit["modifier_applied"] == 0.0
    assert audit["confidence_before"] == 0.50
    assert audit["confidence_after"] == 0.50
    assert audit["providers"] == []


def test_modifier_below_threshold_does_not_bump():
    """Sub-0.6 effective signals are noise — must not contribute."""
    new_conf, audit = apply_external_modifiers(0.50, [_sig(risk=0.55)])
    assert new_conf == 0.50
    assert audit["providers"][0]["applied"] is False
    assert audit["providers"][0]["reason_skipped"] == "below_threshold"


def test_modifier_strong_signal_bumps():
    """A 0.8 effective risk should produce a contribution proportional
    to the per-signal max (0.10) × effective."""
    new_conf, audit = apply_external_modifiers(0.50, [_sig(risk=0.80)])
    assert new_conf > 0.50
    assert audit["providers"][0]["applied"] is True
    # 0.10 × 0.80 = 0.08 contribution.
    assert abs(audit["modifier_applied"] - 0.08) < 1e-3


def test_modifier_caps_total_bump_at_0_20():
    """Three strong signals (0.95, 0.95, 0.95) → individual contributions
    sum > 0.20; the cap must clamp."""
    sigs = [_sig(risk=0.95), _sig(provider="x"), _sig(provider="y")]
    new_conf, audit = apply_external_modifiers(0.50, sigs)
    assert audit["modifier_capped"] is True
    assert abs(audit["modifier_applied"] - CONFIDENCE_BUMP_CAP) < 1e-3
    assert new_conf == 0.50 + CONFIDENCE_BUMP_CAP


def test_modifier_ceiling_at_0_99():
    """Even at base 0.95, modified confidence must not exceed 0.99."""
    new_conf, _ = apply_external_modifiers(
        0.95, [_sig(risk=0.99) for _ in range(3)],
    )
    assert new_conf == 0.99


def test_modifier_stale_signal_does_not_bump():
    """A signal old enough to decay below the floor produces no bump
    even if its raw_risk is high."""
    sig = _sig(risk=0.99, age_s=600, ttl=600)  # fully expired
    new_conf, audit = apply_external_modifiers(0.50, [sig])
    assert new_conf == 0.50
    assert audit["providers"][0]["applied"] is False
    assert audit["providers"][0]["reason_skipped"] == "stale"


def test_modifier_audit_envelope_shape():
    """Lock the wire shape — UI consumes these field names."""
    new_conf, audit = apply_external_modifiers(0.50, [_sig(risk=0.80)])
    for key in ("fetched_at", "confidence_before", "confidence_after",
                "modifier_applied", "modifier_capped", "providers"):
        assert key in audit, f"missing audit key {key}"
    p = audit["providers"][0]
    for key in ("provider", "signal_type", "factors", "raw_risk",
                "freshness", "effective", "delta", "applied",
                "ttl_s", "raw_url"):
        assert key in p, f"missing provider audit key {key}"


def test_modifier_strongest_signal_claims_cap_first():
    """Order-independent: when cap is hit before the weakest signal
    can contribute, the strongest one must be the one with `applied=True`."""
    weak = _sig(provider="weak", risk=0.65, signal_type="weak_t")
    strong1 = _sig(provider="s1", risk=0.95, signal_type="s1_t")
    strong2 = _sig(provider="s2", risk=0.95, signal_type="s2_t")
    strong3 = _sig(provider="s3", risk=0.95, signal_type="s3_t")
    # weak first → strong should still claim the cap
    new_conf, audit = apply_external_modifiers(
        0.50, [weak, strong1, strong2, strong3],
    )
    applied_providers = [p["provider"] for p in audit["providers"] if p["applied"]]
    # Strong signals must all be in the applied list (or capped); weak
    # must NOT have claimed any of the budget.
    assert "weak" not in applied_providers


# ════════════════════════════════════════════════════════════════════
# Registry — fail-quiet + hard timeout
# ════════════════════════════════════════════════════════════════════

class _RaisingProvider(ExternalSignalProvider):
    name = "boom"
    async def _fetch_unsafe(self, lat, lng, when=None):
        raise RuntimeError("upstream exploded")


class _SlowProvider(ExternalSignalProvider):
    name = "slow"
    async def _fetch_unsafe(self, lat, lng, when=None):
        await asyncio.sleep(PROVIDER_TIMEOUT_S + 0.5)
        return _sig()


class _FastProvider(ExternalSignalProvider):
    name = "fast"
    async def _fetch_unsafe(self, lat, lng, when=None):
        return _sig(provider="fast", risk=0.9)


class _DisabledProvider(ExternalSignalProvider):
    name = "disabled"
    def is_enabled(self) -> bool:
        return False
    async def _fetch_unsafe(self, lat, lng, when=None):
        raise AssertionError("must not be called when disabled")


@pytest.mark.asyncio
async def test_registry_swallows_provider_exceptions():
    """One provider raising must not fail the batch."""
    _set_providers_for_test([_RaisingProvider(), _FastProvider()])
    try:
        out = await fetch_all_signals(19.07, 72.87)
        names = [s.provider for s in out]
        assert "fast" in names
        assert "boom" not in names
    finally:
        _reset_providers_to_default()


@pytest.mark.asyncio
async def test_registry_enforces_hard_timeout():
    """A slow provider must be dropped at PROVIDER_TIMEOUT_S, never
    block the alert hot-path."""
    import time
    _set_providers_for_test([_SlowProvider(), _FastProvider()])
    try:
        t0 = time.monotonic()
        out = await fetch_all_signals(19.07, 72.87)
        elapsed = time.monotonic() - t0
        names = [s.provider for s in out]
        # Concurrent fan-out → total budget bounded by single timeout
        # (with a small slack for asyncio scheduling).
        assert elapsed < PROVIDER_TIMEOUT_S + 0.4, f"took {elapsed}s"
        assert "fast" in names
        assert "slow" not in names
    finally:
        _reset_providers_to_default()


@pytest.mark.asyncio
async def test_registry_skips_disabled_providers():
    _set_providers_for_test([_DisabledProvider(), _FastProvider()])
    try:
        out = await fetch_all_signals(19.07, 72.87)
        names = [s.provider for s in out]
        assert names == ["fast"]
    finally:
        _reset_providers_to_default()


@pytest.mark.asyncio
async def test_registry_returns_empty_on_no_location():
    out = await fetch_all_signals(None, 72.87)  # type: ignore
    assert out == []


# ════════════════════════════════════════════════════════════════════
# End-to-end through open_incident_for_alert
# ════════════════════════════════════════════════════════════════════

async def _seed_user(s, role="user"):
    uid = uuid.uuid4()
    await s.execute(text("""
        INSERT INTO users (id, email, full_name, role, password_hash,
                           preferred_channels, created_at)
        VALUES (:id, :email, :name, :role, 'x',
                '["push"]'::json, now())
    """), {"id": str(uid),
           "email": f"ext+{uid}@nischint.test",
           "name": f"User {uid.hex[:8]}", "role": role})
    return uid


async def _cleanup(s, **ids):
    for iid in ids.get("incident_ids", []):
        await s.execute(text(
            "DELETE FROM safety_incident_events WHERE incident_id = :id"
        ), {"id": str(iid)})
        await s.execute(text(
            "DELETE FROM safety_incidents WHERE id = :id"
        ), {"id": str(iid)})
    for uid in ids.get("user_ids", []):
        await s.execute(text("DELETE FROM users WHERE id = :id"),
                        {"id": str(uid)})
    await s.commit()


@pytest.mark.asyncio
async def test_open_incident_persists_external_audit(db):
    """When a strong signal is returned, the new incident must carry
    `external_signals` JSONB AND `confidence_pre_external`, AND a
    forensic event row must fire with `actor_type='external_signal'`."""
    from app.services import safety_incident_engine as _sie

    _set_providers_for_test([_FastProvider()])
    try:
        async with db() as s:
            child = await _seed_user(s)
            await s.commit()

        async with db() as s:
            inc = await _sie.open_incident_for_alert(
                s,
                child_id=str(child),
                kind="voice_distress",
                severity="high",
                confidence=0.50,
                location={"lat": 19.07, "lng": 72.87},
            )
            await s.commit()

        assert inc is not None
        async with db() as s:
            row = (await s.execute(
                select(SafetyIncident).where(SafetyIncident.id == inc.id)
            )).scalar_one()
            events = (await s.execute(
                select(SafetyIncidentEvent)
                .where(SafetyIncidentEvent.incident_id == inc.id)
                .order_by(SafetyIncidentEvent.created_at)
            )).scalars().all()

        assert row.confidence_pre_external == 0.50
        assert row.external_signals is not None
        assert row.external_signals["modifier_applied"] > 0
        # Confidence on the row must be the post-modifier value.
        assert row.confidence > 0.50

        actor_types = [e.actor_type for e in events]
        assert "external_signal" in actor_types, (
            f"missing forensic external_signal event — got {actor_types}"
        )
        ext_evt = [e for e in events if e.actor_type == "external_signal"][0]
        assert ext_evt.extra is not None
        assert ext_evt.extra["confidence_before"] == 0.50
        assert ext_evt.extra["confidence_after"] > 0.50

        async with db() as s:
            await _cleanup(s, incident_ids=[inc.id], user_ids=[child])
    finally:
        _reset_providers_to_default()


@pytest.mark.asyncio
async def test_open_incident_skips_audit_when_no_signals(db):
    """Empty signal set → no audit envelope, no forensic external_signal
    row. Backwards-compat path for incidents created without location."""
    from app.services import safety_incident_engine as _sie

    _set_providers_for_test([])  # no providers at all
    try:
        async with db() as s:
            child = await _seed_user(s)
            await s.commit()

        async with db() as s:
            inc = await _sie.open_incident_for_alert(
                s, child_id=str(child),
                kind="voice_distress", severity="high", confidence=0.50,
                location={"lat": 19.07, "lng": 72.87},
            )
            await s.commit()

        assert inc is not None
        async with db() as s:
            row = (await s.execute(
                select(SafetyIncident).where(SafetyIncident.id == inc.id)
            )).scalar_one()
            events = (await s.execute(
                select(SafetyIncidentEvent)
                .where(SafetyIncidentEvent.incident_id == inc.id)
            )).scalars().all()
        assert row.external_signals is None
        assert row.confidence_pre_external is None
        assert row.confidence == 0.50
        actor_types = [e.actor_type for e in events]
        assert "external_signal" not in actor_types

        async with db() as s:
            await _cleanup(s, incident_ids=[inc.id], user_ids=[child])
    finally:
        _reset_providers_to_default()


@pytest.mark.asyncio
async def test_open_incident_no_location_skips_modifier(db):
    """No `location` arg → modifier path is short-circuited entirely.
    Locks the contract that pre-12.0 callers (no location) still work."""
    from app.services import safety_incident_engine as _sie

    # Even with strong providers registered, missing location means
    # we never call them.
    class _MustNotBeCalled(ExternalSignalProvider):
        name = "must_not_be_called"
        async def _fetch_unsafe(self, lat, lng, when=None):
            raise AssertionError("modifier path ran without location")

    _set_providers_for_test([_MustNotBeCalled()])
    try:
        async with db() as s:
            child = await _seed_user(s)
            await s.commit()

        async with db() as s:
            inc = await _sie.open_incident_for_alert(
                s, child_id=str(child),
                kind="voice_distress", severity="high", confidence=0.50,
                # location=None
            )
            await s.commit()

        assert inc is not None
        async with db() as s:
            row = (await s.execute(
                select(SafetyIncident).where(SafetyIncident.id == inc.id)
            )).scalar_one()
        assert row.external_signals is None
        assert row.confidence_pre_external is None
        assert row.confidence == 0.50

        async with db() as s:
            await _cleanup(s, incident_ids=[inc.id], user_ids=[child])
    finally:
        _reset_providers_to_default()
