"""NISCH-011 — `dlq:ml_predictions` append-only ledger.

Per the locked design constraint from ROADMAP.md:

  > `dlq:ml_predictions` is a prediction *ledger*, not a retry
  > queue. Stores (inputs, would-have-predicted output,
  > timestamp) on every inference attempt — successes AND
  > failures. The shape diverges from the audit-row DLQs because
  > a silent prediction drop during an incident is unrecoverable
  > from a post-mortem perspective. No 3-strike poison
  > semantics — append-only ring-buffer bounded at 10 000
  > entries (~24 h of predictions at expected throughput).

Compensating action: on `behavioral_anomalies` write failure,
the writer falls back to this DLQ. A future operator can pull
the ring-buffer contents to reconstruct what the detector saw
during a Postgres outage. The buffer is bounded so a long
outage can't blow Redis memory.

Strict contract:
  * `append_anomaly_ledger` NEVER raises.
  * LTRIM keeps the buffer at `LEDGER_MAX_ENTRIES` newest items.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.services import redis_service

logger = logging.getLogger(__name__)


DLQ_KEY = "dlq:ml_predictions"
LEDGER_MAX_ENTRIES = 10_000


def append_anomaly_ledger(
    entry: dict[str, Any],
    *,
    reason: str = "behavioral_anomaly_write_failed",
) -> bool:
    """Append a serialised entry to the ML-predictions ring
    buffer. Returns True on success, False on any failure — but
    never raises. Best-effort: a Redis outage drops the entry."""
    payload = {
        "ts": time.time(),
        "reason": reason,
        "entry": entry,
    }
    try:
        r = redis_service._get_client()
        if r is None:
            return False
        r.lpush(DLQ_KEY, json.dumps(payload, default=str))
        # Trim so a long outage can't blow Redis memory.
        r.ltrim(DLQ_KEY, 0, LEDGER_MAX_ENTRIES - 1)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "ml_predictions_ledger_append_failed",
            extra={"event": "ml_predictions_ledger_append_failed",
                   "error_type": type(e).__name__},
        )
        return False


def read_recent(limit: int = 100) -> list[dict]:
    """Operator-introspection read. Returns at most `limit`
    newest entries. Empty on any failure."""
    try:
        r = redis_service._get_client()
        if r is None:
            return []
        raw = r.lrange(DLQ_KEY, 0, max(0, limit - 1))
    except Exception:  # noqa: BLE001
        return []
    out: list[dict] = []
    for m in raw or []:
        try:
            if isinstance(m, bytes):
                m = m.decode("utf-8")
            out.append(json.loads(m))
        except Exception:  # noqa: BLE001
            continue
    return out


def ledger_depth() -> int:
    """Current ring-buffer depth — surfaced on the operator chip
    as `ml_predictions_dlq_depth`."""
    try:
        r = redis_service._get_client()
        if r is None:
            return 0
        return int(r.llen(DLQ_KEY) or 0)
    except Exception:  # noqa: BLE001
        return 0


__all__ = [
    "DLQ_KEY", "LEDGER_MAX_ENTRIES",
    "append_anomaly_ledger", "read_recent", "ledger_depth",
]
