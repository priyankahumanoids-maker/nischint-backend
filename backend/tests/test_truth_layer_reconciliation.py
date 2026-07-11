"""3-source reconciliation truth-table test for getDisplayState.

Mirrors the production logic in LiveSafetyMap.jsx so any drift between
the backend heartbeat semantics and the frontend display rule is caught
immediately. Run via:  python3 -m pytest backend/tests/test_truth_layer_reconciliation.py
"""
from datetime import datetime, timezone, timedelta


# ── Mirror constants from LiveSafetyMap.jsx ──────────────────────────
FRESHNESS_LIVE_MS = 5 * 60 * 1000
FRESHNESS_RECENT_MS = 6 * 60 * 60 * 1000
PING_LIVE_MS = 60 * 1000
PING_GAP_MS = 30 * 60 * 1000


def _ms_ago(iso: str | None) -> float:
    if not iso:
        return float('inf')
    return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() * 1000


def get_freshness_tier(last_seen_iso: str | None) -> str:
    if not last_seen_iso:
        return 'stale'
    ms = _ms_ago(last_seen_iso)
    if ms < 0 or ms <= FRESHNESS_LIVE_MS:
        return 'live'
    if ms <= FRESHNESS_RECENT_MS:
        return 'recent'
    return 'stale'


def get_connection_state(last_ping_iso: str | None) -> str:
    if not last_ping_iso:
        return 'LAST_KNOWN'
    ms = _ms_ago(last_ping_iso)
    if ms < 0 or ms <= PING_LIVE_MS:
        return 'LIVE_WS'
    if ms <= PING_GAP_MS:
        return 'DATA_GAP'
    return 'LAST_KNOWN'


def get_display_state(last_seen_iso, last_ping_iso, location_source) -> str:
    if (
        location_source == 'session'
        and last_seen_iso
        and _ms_ago(last_seen_iso) <= FRESHNESS_LIVE_MS
    ):
        return 'live'
    if get_connection_state(last_ping_iso) == 'DATA_GAP':
        return 'data_gap'
    return get_freshness_tier(last_seen_iso)


# ── Helpers ──────────────────────────────────────────────────────────
def _ago(seconds: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


# ── Truth table ──────────────────────────────────────────────────────
def test_live_when_session_gps_is_fresh():
    """Strongest signal — WS live_location from active session."""
    assert get_display_state(_ago(10), _ago(10), 'session') == 'live'


def test_live_overrides_data_gap_when_gps_is_fresher_than_heartbeat():
    """The false-anxiety bug we just closed.

    Heartbeat is in the 60 s – 30 min DATA_GAP window, but a fresh
    live_location stream is still arriving. Strongest signal wins.
    """
    assert get_display_state(_ago(10), _ago(120), 'session') == 'live'


def test_data_gap_when_heartbeat_silent_and_no_fresh_gps():
    """The genuine anomaly DATA_GAP is reserved for."""
    assert get_display_state(_ago(7200), _ago(120), 'baseline') == 'data_gap'
    # Even with no last_seen_at, a recent-but-silent heartbeat still flags.
    assert get_display_state(None, _ago(120), None) == 'data_gap'


def test_recent_when_heartbeat_fresh_but_only_baseline_gps():
    """Pipeline alive, but the location origin is baseline-only.

    Honest depiction: pipeline-connected popup line, but the rendered
    pin position falls back to whatever freshness tier the location
    age dictates. 2 h baseline → RECENT (5 min – 6 h window).
    """
    # 2 h baseline → RECENT
    assert get_display_state(_ago(7200), _ago(10), 'baseline') == 'recent'
    # 1 day baseline → STALE
    assert get_display_state(_ago(86400), _ago(10), 'baseline') == 'stale'


def test_stale_when_heartbeat_fresh_and_no_location_at_all():
    """No last_seen_at falls through to STALE (no false LIVE)."""
    assert get_display_state(None, _ago(10), None) == 'stale'


def test_recent_when_session_gps_is_5_to_10_min_old():
    """RECENT band — pipeline ok, GPS not bleeding-edge fresh."""
    assert get_display_state(_ago(600), _ago(10), 'session') == 'recent'


def test_stale_when_everything_is_old():
    """LAST_KNOWN baseline-only never triggers DATA_GAP."""
    assert get_display_state(_ago(86400), _ago(86400), 'baseline') == 'stale'
    assert get_display_state(_ago(86400), None, 'baseline') == 'stale'


def test_data_gap_does_not_persist_after_30_min_silence():
    """After 30 min of silence we accept that the pipeline is gone and
    fall through to whichever freshness tier the location age dictates."""
    # 2 h location + 40 min silence → RECENT (no false DATA_GAP)
    assert get_display_state(_ago(7200), _ago(2400), 'baseline') == 'recent'
    # 1 day location + 40 min silence → STALE
    assert get_display_state(_ago(86400), _ago(2400), 'baseline') == 'stale'


def test_session_source_with_stale_gps_does_not_force_live():
    """A session with a 10-min-old last GPS no longer counts as LIVE."""
    assert get_display_state(_ago(600), _ago(120), 'session') == 'data_gap'
    # Without a fresh heartbeat, drops to RECENT freshness tier:
    assert get_display_state(_ago(600), None, 'session') == 'recent'
