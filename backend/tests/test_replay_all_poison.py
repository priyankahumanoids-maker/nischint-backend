"""replay_all_poison.py — operator script contract tests.

Locks the script's per-DLQ rate-limit + dry-run + discard
semantics. The drain itself is exercised by
`test_dlq_poison_drain.py`; this file only verifies the
orchestration around it.
"""
from __future__ import annotations

import json
import sys

import pytest

from app.services import dlq_reconciler as dlq
# Import the script via path manipulation since `backend/scripts`
# isn't a package on sys.path by default.
sys.path.insert(0, "/app/backend/scripts")
import replay_all_poison as script  # noqa: E402


class _RedisDouble:
    def __init__(self):
        self.lists: dict[str, list[str]] = {}

    def rpop(self, key):
        lst = self.lists.get(key)
        return lst.pop() if lst else None

    def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)
        return len(self.lists[key])

    def ltrim(self, key, start, stop):
        lst = self.lists.get(key)
        if not lst:
            return True
        self.lists[key] = lst[start:stop + 1]
        return True

    def llen(self, key):
        return len(self.lists.get(key, []))


@pytest.fixture
def redis_double(monkeypatch):
    d = _RedisDouble()
    monkeypatch.setattr(
        "app.services.redis_service._get_client", lambda: d,
    )
    return d


@pytest.mark.asyncio
async def test_dry_run_reports_depth_without_touching(redis_double):
    """Dry-run probes every DLQ's depth but MUST NOT pop anything.
    Operators use this as a pre-flight before --discard."""
    pkey = dlq._poison_key("dlq:failsafe_audit")
    redis_double.lists[pkey] = [
        json.dumps({"event_id": "e1"}),
        json.dumps({"event_id": "e2"}),
    ]
    rc = await script._run(
        max_per_dlq=10, discard=False, dry_run=True,
        inter_dlq_pause_s=0,
    )
    assert rc == 0
    # Untouched.
    assert redis_double.llen(pkey) == 2


@pytest.mark.asyncio
async def test_empty_poison_skipped_cleanly(redis_double, capsys):
    """Empty poison lists must be skipped without burning an RPOP
    call — the JSON summary marks them `skipped_empty`."""
    rc = await script._run(
        max_per_dlq=10, discard=False, dry_run=False,
        inter_dlq_pause_s=0,
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    actions = {d["dlq"]: d["action"] for d in out["dlqs"]}
    # Every registered DLQ should be in the summary.
    assert set(actions.keys()) == {k for k, _m, _fn in dlq._DLQS}
    # All actions are 'skipped_empty' because nothing's queued.
    assert all(v == "skipped_empty" for v in actions.values())


@pytest.mark.asyncio
async def test_discard_mode_routes_through_service_layer(
        redis_double, capsys):
    """Discard mode must produce the same payload-echo shape as the
    API endpoint — the script is a thin shell around the same
    `drain_poison_list` call."""
    pkey = dlq._poison_key("dlq:failsafe_audit")
    redis_double.lists[pkey] = [
        json.dumps({"event_id": "e1"}),
        json.dumps({"event_id": "e2"}),
        json.dumps({"event_id": "e3"}),
    ]
    rc = await script._run(
        max_per_dlq=10, discard=True, dry_run=False,
        inter_dlq_pause_s=0,
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    fs_row = next(
        d for d in out["dlqs"] if d["dlq"] == "dlq:failsafe_audit"
    )
    assert fs_row["attempted"] == 3
    assert fs_row["discarded"] == 3
    assert redis_double.llen(pkey) == 0


@pytest.mark.asyncio
async def test_per_dlq_cap_respects_max_per_dlq(redis_double, capsys):
    """Per-DLQ rate limit — even if a single DLQ has 200 poisoned
    entries, the script only drains `max_per_dlq` of them per
    invocation. Multiple runs needed to drain a deep backlog —
    intentional; one run shouldn't starve the regular reconciler."""
    pkey = dlq._poison_key("dlq:failsafe_audit")
    redis_double.lists[pkey] = [
        json.dumps({"i": i}) for i in range(200)
    ]
    rc = await script._run(
        max_per_dlq=20, discard=True, dry_run=False,
        inter_dlq_pause_s=0,
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    fs_row = next(
        d for d in out["dlqs"] if d["dlq"] == "dlq:failsafe_audit"
    )
    assert fs_row["attempted"] == 20
    assert redis_double.llen(pkey) == 180


@pytest.mark.asyncio
async def test_redis_unavailable_returns_nonzero_exit(monkeypatch, capsys):
    """Operator script convention: exit code 1 when ANY DLQ probe
    hits Redis-unavailable so the calling shell can branch on it."""
    monkeypatch.setattr(
        "app.services.redis_service._get_client", lambda: None,
    )
    rc = await script._run(
        max_per_dlq=10, discard=False, dry_run=False,
        inter_dlq_pause_s=0,
    )
    assert rc == 1
    out = json.loads(capsys.readouterr().out)
    assert out["any_redis_unavailable"] is True


@pytest.mark.asyncio
async def test_max_per_dlq_bounds_validation(redis_double, capsys):
    """Out-of-bounds --max-per-dlq returns exit 2 (CLI arg error)."""
    rc = await script._run(
        max_per_dlq=0, discard=False, dry_run=False,
        inter_dlq_pause_s=0,
    )
    assert rc == 2
    rc = await script._run(
        max_per_dlq=dlq.POISON_MAX + 1, discard=False, dry_run=False,
        inter_dlq_pause_s=0,
    )
    assert rc == 2


@pytest.mark.asyncio
async def test_replay_mode_aggregates_drained_and_requeued(
        redis_double, monkeypatch, capsys):
    """Summary aggregates drained + requeued across all DLQs so an
    operator gets a single total. Mock one replay fn to succeed
    and another to fail — verify both buckets contribute."""
    fs_pkey = dlq._poison_key("dlq:failsafe_audit")
    vd_pkey = dlq._poison_key("dlq:voice_distress_audit")
    redis_double.lists[fs_pkey] = [
        json.dumps({"event_id": "fs1"}),
    ]
    redis_double.lists[vd_pkey] = [
        json.dumps({"event_id": "vd1"}),
    ]

    async def _ok(_p):
        return True
    async def _fail(_p):
        return False

    def _route(key):
        return _ok if key == "dlq:failsafe_audit" else _fail

    monkeypatch.setattr(dlq, "_replay_fn_for", _route)
    rc = await script._run(
        max_per_dlq=10, discard=False, dry_run=False,
        inter_dlq_pause_s=0,
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["total_attempted"] == 2
    assert out["total_drained"]   == 1   # failsafe drained
    assert out["total_requeued"]  == 1   # voice_distress requeued


# ════════════════════════════════════════════════════════════════════
# dlq:rag_reindex producer-side tests
# ════════════════════════════════════════════════════════════════════

def test_rag_reindex_dlq_bounded_with_ltrim():
    """Memory-safety: same bound enforcement as the other 4 DLQs."""
    from unittest.mock import MagicMock, patch
    from app.api import rag as rag_api

    fake_client = MagicMock()
    with patch(
        "app.services.redis_service._get_client",
        return_value=fake_client,
    ):
        result = rag_api._push_rag_reindex_dlq({"post_id": "p1"})
    assert result is True
    fake_client.lpush.assert_called_once()
    fake_client.ltrim.assert_called_once()
    args = fake_client.ltrim.call_args[0]
    assert args[2] == rag_api._RAG_REINDEX_DLQ_MAX - 1


def test_rag_reindex_dlq_in_reconciler_registry():
    """The new DLQ MUST be registered. Same lock as the other four —
    a producer with no reconciler entry would silently accumulate."""
    keys = {entry[0] for entry in dlq._DLQS}
    assert "dlq:rag_reindex" in keys


def test_rag_reindex_max_size_matches_producer():
    """Producer-side `_RAG_REINDEX_DLQ_MAX` must match the
    reconciler's `max_size` for this DLQ. A drift here misreports
    pressure % to operators."""
    from app.api.rag import _RAG_REINDEX_DLQ_MAX
    by_key = {entry[0]: entry[1] for entry in dlq._DLQS}
    assert by_key["dlq:rag_reindex"] == _RAG_REINDEX_DLQ_MAX
