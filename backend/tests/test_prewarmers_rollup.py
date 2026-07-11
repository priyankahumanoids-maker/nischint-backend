"""Roll-up endpoint contract — single-call snapshot of every
external-signal pre-warmer. Operators rely on this shape;
keys are additive (never renamed)."""
from __future__ import annotations

import asyncio


def test_rollup_returns_all_four_provider_keys():
    """Locked shape: roll-up MUST contain `v2_parity`, `sachet`,
    `tomtom`, `news`. Missing any key is a breaking change for
    the operator capsule."""
    from app.api.monitoring import get_all_prewarmers_rollup
    out = asyncio.run(get_all_prewarmers_rollup())
    assert set(out.keys()) == {"v2_parity", "sachet", "tomtom", "news"}


def test_rollup_v2_parity_shape():
    """V2 block must carry the fields operators key off during the
    eventual phased rollout: aggregate `tier`, total `critical_count`,
    weighted-avg `match_pct`, and per-kind `by_kind` drill-down."""
    from app.api.monitoring import get_all_prewarmers_rollup
    out = asyncio.run(get_all_prewarmers_rollup())
    v2 = out["v2_parity"]
    for k in ("tier", "critical_count", "match_pct", "by_kind"):
        assert k in v2, f"missing v2_parity field: {k}"


def test_rollup_provider_blocks_carry_health_state():
    """Every external-signal block must surface `health_state` so
    the capsule can render a colour-coded chip without further
    requests. Channels block is news-specific but must be present."""
    from app.api.monitoring import get_all_prewarmers_rollup
    out = asyncio.run(get_all_prewarmers_rollup())
    for src in ("sachet", "tomtom", "news"):
        assert "health_state" in out[src], f"{src} missing health_state"
        assert "cache_age_seconds" in out[src]
        assert "recovery_progress" in out[src]
        assert "recovery_required" in out[src]
    assert "channels" in out["news"]
    assert set(out["news"]["channels"].keys()) >= {"newsapi", "rss"}
