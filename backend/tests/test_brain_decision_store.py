"""
Unit tests for the AI Brain Decision Store (Mongo persistence layer).

Validates the pure-logic surface of `brain_decision_store`:
    1. _to_doc projects decision → Mongo schema correctly
    2. _serialize strips _id and converts datetime → ISO
    3. insert/update/recent silently no-op when Mongo disabled
    4. TTL + user_id index constants are sane

Does NOT require a live Mongo — exercises only the code paths that are
independent of the DB connection. A live integration check is covered by
the E2E curl run performed by the main agent.

Run:  pytest -q backend/tests/test_brain_decision_store.py
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from app.services import brain_decision_store as store


def test_to_doc_projects_fields_correctly():
    decision = {
        "event_id": "evt_1",
        "user_id": "u_1",
        "user_type": "child",
        "risk_score": 73,
        "risk_level": "RED",
        "confidence": 0.81,
        "effective_score": 58.2,
        "final_score": 58.2,
        "recommended_action": "NOTIFY_GUARDIAN",
        "original_action": "NOTIFY_GUARDIAN",
        "cooldown_applied": False,
        "executed": True,
        "triggers_fired": ["voice_scream", "late_night"],
        "reason": "Alerting guardians: Voice distress + Late-night context.",
        "guardian_selected": {"id": "g_mom", "name": "Mom", "trust_score": 0.92, "effective_trust": 0.85},
        "signals_breakdown": {"voice": {"amplitude": 0.9}},
        "latency_ms": 42.3,
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }
    doc = store._to_doc(decision)

    assert doc["_id"] == "evt_1"
    assert doc["event_id"] == "evt_1"
    assert doc["user_id"] == "u_1"
    assert doc["risk_level"] == "RED"
    assert doc["recommended_action"] == "NOTIFY_GUARDIAN"
    # decided_at must be a datetime (for TTL) not a string
    assert isinstance(doc["decided_at"], datetime)
    assert doc["triggers_fired"] == ["voice_scream", "late_night"]
    assert doc["guardian_selected"]["name"] == "Mom"
    # feedback should be absent or None (not set yet)
    assert doc.get("feedback") is None


def test_to_doc_handles_datetime_and_invalid_ts():
    # datetime object input
    d1 = store._to_doc({"event_id": "e", "decided_at": datetime.now(timezone.utc)})
    assert isinstance(d1["decided_at"], datetime)
    # invalid string input → falls back to now()
    d2 = store._to_doc({"event_id": "e2", "decided_at": "not-a-date"})
    assert isinstance(d2["decided_at"], datetime)
    # None input → falls back to now()
    d3 = store._to_doc({"event_id": "e3"})
    assert isinstance(d3["decided_at"], datetime)


def test_serialize_strips_id_and_isoifies_datetime():
    now = datetime.now(timezone.utc) - timedelta(minutes=5)
    raw = {"_id": "abc", "event_id": "abc", "decided_at": now, "user_id": "u"}
    out = store._serialize(dict(raw))  # copy because serialize mutates
    assert "_id" not in out
    assert isinstance(out["decided_at"], str)
    # Round-trip to verify ISO format
    parsed = datetime.fromisoformat(out["decided_at"].replace("Z", "+00:00"))
    assert abs((parsed - now).total_seconds()) < 1


def test_insert_update_recent_noop_when_mongo_unavailable(monkeypatch):
    """When Mongo is unavailable, all ops must be silent no-ops."""
    monkeypatch.setattr(store, "_db", lambda: None)
    # Should not raise
    store.insert_decision({"event_id": "e", "user_id": "u"})
    store.update_feedback("e", {"outcome": "true_positive"})
    assert store.recent(limit=5) == []
    assert store.is_enabled() is False


def test_ttl_is_ninety_days():
    assert store.DECISION_TTL_DAYS == 90
    assert store._TTL_SECONDS == 90 * 86400


# ── Small-improvements batch ───────────────────────────────────────────

def test_summary_projection_has_essential_fields():
    """Timeline needs these; heavy fields (signals, guardian_selected) are dropped."""
    p = store.SUMMARY_PROJECTION
    assert p.get("event_id") == 1
    assert p.get("user_id") == 1
    assert p.get("decided_at") == 1
    assert p.get("risk_score") == 1
    assert p.get("risk_level") == 1
    assert p.get("recommended_action") == 1
    assert p.get("reason") == 1
    assert p.get("feedback") == 1
    assert p.get("_id") == 0
    # Heavy fields MUST NOT be listed (so they get dropped)
    assert "signals" not in p
    assert "guardian_selected" not in p


def test_max_limit_is_hundred():
    assert store.MAX_LIMIT == 100


def test_recent_clamps_oversized_limit(monkeypatch):
    """Caller passing limit=1000 must be clamped server-side to MAX_LIMIT."""
    captured = {}

    class FakeCursor:
        def sort(self, *a, **kw): return self
        def limit(self, n): captured["limit"] = n; return self
        def __iter__(self): return iter([])

    class FakeCol:
        def find(self, *a, **kw): return FakeCursor()
    class FakeDb:
        def __getitem__(self, _): return FakeCol()

    monkeypatch.setattr(store, "_db", lambda: FakeDb())
    store.recent(limit=1000, user_id="u_any")
    assert captured["limit"] == 100  # clamped


def test_find_by_event_id_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(store, "_db", lambda: None)
    assert store.find_by_event_id("anything") is None
    assert store.find_by_event_id("") is None
