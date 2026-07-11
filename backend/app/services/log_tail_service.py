"""REL-02 — backend log-tail service.

Read-only access to the last N lines of `/var/log/supervisor/backend.*.log`
for operator/admin debug. Designed for the operator console's
inline "Tail Logs" capsule.

Locked invariants:
  * `lines` clamped to [1, 500]. The 500 ceiling protects the
    capsule from accidentally pulling 50 MB if an operator types
    `lines=99999`.
  * `since_minutes` clamped to [1, 1440] (24 h). Anything older
    than a day should go through the persistent log store, not
    the rolling supervisor file.
  * Reads are tail-efficient — we seek to the file end and walk
    backward in 64 KB chunks, never loading the whole log into
    memory. A typical 100-line tail reads <16 KB.
  * `since_minutes` filter is best-effort on the JSON `ts` field.
    Lines that fail to parse are KEPT in the output (filtering
    is permissive — operators see weird lines so they can
    diagnose them).
  * NEVER raises. A missing log file → empty list, not 500.
    The supervisor file genuinely doesn't exist in CI / fresh
    Docker pods.
"""
from __future__ import annotations

import glob
import io
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


# Hard ceilings — locked.
MAX_LINES = 500
MAX_SINCE_MINUTES = 1440        # 24 h


# Where supervisor writes the backend logs. Globbed so `backend.err.log`
# AND `backend.out.log` are both surfaced — operators usually want both
# streams interleaved by timestamp.
LOG_GLOB = "/var/log/supervisor/backend.*.log"


def _clamp(v: int, lo: int, hi: int) -> int:
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def _tail_file(path: str, max_lines: int) -> list[str]:
    """Read the last `max_lines` lines from `path` without loading
    the whole file. Walks backward in 64 KB chunks.

    Returns the lines oldest-first (so a caller can append other
    files and re-sort by timestamp).
    """
    if not os.path.exists(path):
        return []
    try:
        size = os.path.getsize(path)
        if size == 0:
            return []
    except OSError:
        return []

    chunk = 64 * 1024
    lines: list[str] = []
    try:
        with open(path, "rb") as f:
            pos = size
            buf = b""
            while pos > 0 and len(lines) <= max_lines:
                read_size = min(chunk, pos)
                pos -= read_size
                f.seek(pos)
                buf = f.read(read_size) + buf
                # Newline-delimited; convert ONLY when we have enough
                # to know we won't slice mid-line.
                if pos == 0 or buf.count(b"\n") >= max_lines + 1:
                    raw = buf.decode("utf-8", errors="replace").splitlines()
                    # Take the last `max_lines` lines (most recent end of file).
                    lines = raw[-max_lines:]
                    break
    except OSError as e:
        logger.warning("[REL-02] tail failed for %s: %r", path, e)
        return []
    return lines


def _parse_ts(line: str) -> datetime | None:
    """Try to extract the JSON `ts` field. Return None on any failure
    so the line still surfaces in the output (permissive filter)."""
    # Hot path — JSON lines start with `{"ts":`. Cheap prefix check
    # before the JSON parse to skip non-JSON tracebacks.
    line = line.lstrip()
    if not line.startswith("{"):
        return None
    try:
        obj = json.loads(line)
        ts = obj.get("ts")
        if not ts:
            return None
        # Tolerate trailing 'Z'.
        if isinstance(ts, str) and ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts)
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


def tail_backend_logs(
    *,
    lines: int = 100,
    since_minutes: int | None = None,
) -> dict[str, Any]:
    """Public entry point. Returns:
        {
          "lines":         list[str],     # JSON or plain text, newline-stripped
          "count":         int,
          "files_read":    list[str],     # glob hits at read time
          "since_minutes": int | None,
          "limit":         int,           # the clamped `lines`
          "generated_at":  ISO8601,
        }
    """
    limit = _clamp(int(lines), 1, MAX_LINES)
    since_min: int | None = None
    cutoff: datetime | None = None
    if since_minutes is not None:
        since_min = _clamp(int(since_minutes), 1, MAX_SINCE_MINUTES)
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=since_min)

    files = sorted(glob.glob(LOG_GLOB))
    if not files:
        return {
            "lines":         [],
            "count":         0,
            "files_read":    [],
            "since_minutes": since_min,
            "limit":         limit,
            "generated_at":  datetime.now(timezone.utc).isoformat(),
        }

    # Read enough from EACH file to satisfy the merge — if we have
    # 2 files and the operator wants 100 lines, we tail 100 from
    # each, then sort + clip. Cheap (max ~200 KB).
    pool: list[tuple[datetime | None, str]] = []
    for f in files:
        for ln in _tail_file(f, limit):
            ts = _parse_ts(ln)
            if cutoff is not None and ts is not None and ts < cutoff:
                continue
            pool.append((ts, ln))

    # Sort by timestamp. Lines with no parseable ts go to the END
    # (operator sees them but they don't push real recent lines off).
    sentinel = datetime.min.replace(tzinfo=timezone.utc)
    pool.sort(key=lambda x: x[0] or sentinel)
    out_lines = [ln for _ts, ln in pool[-limit:]]

    return {
        "lines":         out_lines,
        "count":         len(out_lines),
        "files_read":    files,
        "since_minutes": since_min,
        "limit":         limit,
        "generated_at":  datetime.now(timezone.utc).isoformat(),
    }


__all__ = [
    "MAX_LINES",
    "MAX_SINCE_MINUTES",
    "LOG_GLOB",
    "tail_backend_logs",
]
