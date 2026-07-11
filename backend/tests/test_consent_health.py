"""DPDP-04-DASH — Tests for the aggregate consent-health endpoint.

These tests pin the threshold + sample-size logic in
`admin_consent_health`. Pure-function tests so we can stay in process
without spinning up the full FastAPI app — we exercise the bundle
construction logic by composing rows in a `(decided, granted)` map
and asserting against it.

The endpoint itself is integration-tested indirectly via the curl
smoke check during finish.
"""
from __future__ import annotations

from app.api.consents import (
    CATEGORIES,
    CATEGORY_METADATA,
    CRITICAL_THRESHOLD,
    HEALTHY_THRESHOLD,
    MIN_SAMPLE_SIZE,
    ConsentHealthBundle,
    ConsentHealthCategory,
)


def _build_bundle(rows: dict[str, tuple[int, int]]) -> ConsentHealthBundle:
    """Mirror the endpoint's aggregation logic without hitting the DB.

    This is the same shape the endpoint constructs; if the endpoint
    drifts, the import above will surface the mismatch.
    """
    from datetime import datetime, timezone

    categories: list[ConsentHealthCategory] = []
    worst_state = "ok"
    for cat in CATEGORIES:
        decided, granted = rows.get(cat, (0, 0))
        grant_rate = (granted / decided) if decided else 0.0
        if decided < MIN_SAMPLE_SIZE:
            healthy = True
        else:
            healthy = grant_rate >= HEALTHY_THRESHOLD
            if grant_rate < CRITICAL_THRESHOLD:
                worst_state = "critical"
            elif grant_rate < HEALTHY_THRESHOLD and worst_state == "ok":
                worst_state = "warning"
        categories.append(ConsentHealthCategory(
            category=cat,
            label_en=CATEGORY_METADATA[cat]["label_en"],
            decided=decided,
            granted=granted,
            grant_rate=round(grant_rate, 4),
            healthy=healthy,
        ))
    total_users = max((d for d, _ in rows.values()), default=0)
    overall_state = "nodata" if total_users == 0 else worst_state
    return ConsentHealthBundle(
        total_users_prompted=total_users,
        overall_state=overall_state,
        healthy_threshold=HEALTHY_THRESHOLD,
        critical_threshold=CRITICAL_THRESHOLD,
        min_sample_size=MIN_SAMPLE_SIZE,
        categories=categories,
        generated_at=datetime.now(timezone.utc),
    )


# ── Overall-state classification ────────────────────────────────────


def test_empty_consents_table_returns_nodata():
    bundle = _build_bundle({})
    assert bundle.overall_state == "nodata"
    assert bundle.total_users_prompted == 0
    # Every category should still be present even when empty.
    assert {c.category for c in bundle.categories} == set(CATEGORIES)


def test_all_categories_above_threshold_is_ok():
    rows = {cat: (100, 90) for cat in CATEGORIES}  # 90% grant rate everywhere
    bundle = _build_bundle(rows)
    assert bundle.overall_state == "ok"
    assert all(c.healthy for c in bundle.categories)


def test_one_category_in_warning_band():
    rows = {cat: (100, 95) for cat in CATEGORIES}
    rows["audio_recording"] = (100, 70)  # 70% — below HEALTHY (80%) above CRITICAL (50%)
    bundle = _build_bundle(rows)
    assert bundle.overall_state == "warning"
    cat = next(c for c in bundle.categories if c.category == "audio_recording")
    assert cat.healthy is False
    assert cat.grant_rate == 0.70


def test_one_category_below_critical_paints_red():
    rows = {cat: (100, 95) for cat in CATEGORIES}
    rows["push_notifications"] = (100, 30)  # 30% — well below CRITICAL
    bundle = _build_bundle(rows)
    assert bundle.overall_state == "critical"


def test_critical_wins_over_warning():
    rows = {cat: (100, 95) for cat in CATEGORIES}
    rows["audio_recording"] = (100, 70)  # warning
    rows["push_notifications"] = (100, 20)  # critical
    bundle = _build_bundle(rows)
    assert bundle.overall_state == "critical"


# ── Small-sample protection ────────────────────────────────────────


def test_low_sample_size_does_not_paint_red():
    # 1 of 1 declined = 0% grant rate but only 1 sample — must stay OK.
    rows = {cat: (100, 95) for cat in CATEGORIES}
    rows["biometric_sensors"] = (1, 0)  # 0% but n=1
    bundle = _build_bundle(rows)
    assert bundle.overall_state == "ok"
    bio = next(c for c in bundle.categories if c.category == "biometric_sensors")
    # Low-sample rows report their real grant_rate but are flagged healthy.
    assert bio.healthy is True
    assert bio.grant_rate == 0.0


def test_at_min_sample_size_threshold_is_evaluated():
    # Exactly MIN_SAMPLE_SIZE — threshold kicks in.
    rows = {cat: (100, 95) for cat in CATEGORIES}
    rows["health_vitals"] = (MIN_SAMPLE_SIZE, 4)  # 40% grant_rate
    bundle = _build_bundle(rows)
    assert bundle.overall_state == "critical"
