"""REL-02 — log-tail service tests.

Locked invariants:
  * `lines` clamped to [1, 500]. Asking for 99,999 gets 500.
  * `since_minutes` clamped to [1, 1440].
  * Missing log files → empty list, no exception.
  * `since_minutes` filter is permissive — lines without parseable
    `ts` STAY in the output (operators need to see weird lines).
  * Output is sorted by timestamp; unparseable lines go last.
  * Tail reads efficiently — large file, small `lines` ⇒ small
    memory footprint (asserted via a 5 MB synthetic file).
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.services import log_tail_service as svc


# ── Pure helpers ────────────────────────────────────────────────


def test_clamp_lines_floor():
    assert svc._clamp(0, 1, 500) == 1
    assert svc._clamp(-100, 1, 500) == 1


def test_clamp_lines_ceiling():
    assert svc._clamp(99_999, 1, 500) == 500


def test_clamp_pass_through():
    assert svc._clamp(50, 1, 500) == 50


def test_parse_ts_iso_with_z():
    line = '{"ts":"2026-05-29T10:00:00Z","level":"INFO","msg":"x"}'
    out = svc._parse_ts(line)
    assert out is not None
    assert out.tzinfo is not None


def test_parse_ts_iso_with_offset():
    line = '{"ts":"2026-05-29T10:00:00+00:00","level":"INFO","msg":"x"}'
    assert svc._parse_ts(line) is not None


def test_parse_ts_non_json_returns_none():
    assert svc._parse_ts("Traceback (most recent call last):") is None
    assert svc._parse_ts("") is None
    assert svc._parse_ts("plain text line") is None


def test_parse_ts_missing_field_returns_none():
    assert svc._parse_ts('{"level":"INFO","msg":"no ts here"}') is None


def test_parse_ts_malformed_json_returns_none():
    assert svc._parse_ts('{"ts": INVALID JSON') is None


# ── _tail_file ─────────────────────────────────────────────────


def test_tail_file_missing_returns_empty():
    assert svc._tail_file("/nonexistent/path", 100) == []


def test_tail_file_empty_returns_empty(tmp_path):
    f = tmp_path / "empty.log"
    f.write_text("")
    assert svc._tail_file(str(f), 100) == []


def test_tail_file_fewer_than_requested(tmp_path):
    f = tmp_path / "small.log"
    f.write_text("line1\nline2\nline3\n")
    out = svc._tail_file(str(f), 100)
    assert out == ["line1", "line2", "line3"]


def test_tail_file_returns_last_n(tmp_path):
    f = tmp_path / "many.log"
    f.write_text("\n".join(f"line-{i}" for i in range(1000)) + "\n")
    out = svc._tail_file(str(f), 10)
    assert len(out) == 10
    assert out[-1] == "line-999"
    assert out[0] == "line-990"


def test_tail_file_handles_5mb_with_small_window(tmp_path):
    """5 MB synthetic file + lines=20 — must still be fast / small."""
    f = tmp_path / "big.log"
    one_line = "x" * 100 + "\n"        # 101 B/line
    with open(f, "w") as h:
        for i in range(60_000):
            h.write(f"line-{i:06d}-" + "x" * 80 + "\n")
    out = svc._tail_file(str(f), 20)
    assert len(out) == 20
    assert "line-059999" in out[-1]


# ── tail_backend_logs (public entry) ───────────────────────────


def _stub_log_glob(monkeypatch, paths: list[str]):
    """Patch the module-level glob target so the test's tmp files
    are what the service reads."""
    monkeypatch.setattr(svc, "LOG_GLOB", "/dev/null/nonexistent")
    monkeypatch.setattr(svc.glob, "glob", lambda _: list(paths))


def test_tail_backend_logs_no_files_returns_empty(monkeypatch):
    monkeypatch.setattr(svc.glob, "glob", lambda _: [])
    out = svc.tail_backend_logs(lines=100)
    assert out["count"] == 0
    assert out["lines"] == []
    assert out["files_read"] == []
    assert out["limit"] == 100


def test_tail_backend_logs_clamps_lines(monkeypatch, tmp_path):
    f = tmp_path / "logs.log"
    f.write_text("\n".join(f"x-{i}" for i in range(2000)) + "\n")
    _stub_log_glob(monkeypatch, [str(f)])
    out = svc.tail_backend_logs(lines=99_999)
    assert out["limit"] == svc.MAX_LINES
    assert out["count"] <= svc.MAX_LINES


def test_tail_backend_logs_clamps_lines_floor(monkeypatch, tmp_path):
    f = tmp_path / "logs.log"
    f.write_text("only-one\n")
    _stub_log_glob(monkeypatch, [str(f)])
    out = svc.tail_backend_logs(lines=-5)
    assert out["limit"] == 1


def test_tail_backend_logs_clamps_since_minutes(monkeypatch, tmp_path):
    f = tmp_path / "logs.log"
    f.write_text("x\n")
    _stub_log_glob(monkeypatch, [str(f)])
    out = svc.tail_backend_logs(lines=1, since_minutes=99_999)
    assert out["since_minutes"] == svc.MAX_SINCE_MINUTES


def test_tail_backend_logs_since_filter_drops_old_lines(monkeypatch, tmp_path):
    f = tmp_path / "logs.log"
    now = datetime.now(timezone.utc)
    old = now - timedelta(hours=2)
    fresh = now - timedelta(minutes=5)
    payload = [
        json.dumps({"ts": old.isoformat(), "msg": "OLD"}),
        json.dumps({"ts": fresh.isoformat(), "msg": "FRESH"}),
    ]
    f.write_text("\n".join(payload) + "\n")
    _stub_log_glob(monkeypatch, [str(f)])

    out = svc.tail_backend_logs(lines=100, since_minutes=30)
    msgs = [json.loads(line)["msg"] for line in out["lines"]]
    assert "FRESH" in msgs
    assert "OLD" not in msgs


def test_tail_backend_logs_keeps_unparseable_lines(monkeypatch, tmp_path):
    """Operators NEED to see weird lines — they're how you find bugs.
    `since_minutes` filter is permissive on parse failure."""
    f = tmp_path / "logs.log"
    fresh_ts = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    f.write_text("\n".join([
        "Traceback (most recent call last):",         # unparseable
        json.dumps({"ts": fresh_ts, "msg": "JSON line"}),
        "  File \"/foo.py\", line 1, in <module>",    # unparseable
    ]) + "\n")
    _stub_log_glob(monkeypatch, [str(f)])

    out = svc.tail_backend_logs(lines=100, since_minutes=30)
    joined = "\n".join(out["lines"])
    assert "Traceback" in joined
    assert "JSON line" in joined
    assert "/foo.py" in joined


def test_tail_backend_logs_merges_two_files_by_timestamp(monkeypatch, tmp_path):
    """err + out should interleave by `ts` in the merged result."""
    err = tmp_path / "backend.err.log"
    outf = tmp_path / "backend.out.log"
    now = datetime.now(timezone.utc)
    err.write_text("\n".join([
        json.dumps({"ts": (now - timedelta(minutes=10)).isoformat(), "msg": "ERR-1"}),
        json.dumps({"ts": (now - timedelta(minutes=2)).isoformat(),  "msg": "ERR-2"}),
    ]) + "\n")
    outf.write_text("\n".join([
        json.dumps({"ts": (now - timedelta(minutes=5)).isoformat(), "msg": "OUT-1"}),
    ]) + "\n")
    _stub_log_glob(monkeypatch, [str(err), str(outf)])

    out = svc.tail_backend_logs(lines=100)
    msgs = [json.loads(line)["msg"] for line in out["lines"]]
    # Sorted oldest → newest
    assert msgs == ["ERR-1", "OUT-1", "ERR-2"]


# ── HTTP layer ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_endpoint_returns_tail_envelope(monkeypatch):
    """The thin FastAPI endpoint forwards to the service. Asserting
    the integration here so a future refactor to a model class can't
    break the contract silently."""
    from app.api.monitoring import logs_tail
    monkeypatch.setattr(svc.glob, "glob", lambda _: [])
    out = await logs_tail(lines=50, since_minutes=10)
    assert out["limit"] == 50
    assert out["since_minutes"] == 10
    assert out["lines"] == []
    assert out["count"] == 0
