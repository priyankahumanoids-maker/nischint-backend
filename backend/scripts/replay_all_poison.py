"""replay_all_poison.py — operator one-shot drain of every DLQ
poison list.

Walks each registered DLQ in `_DLQS` once with a per-DLQ rate
limit, routing entries through their replay function (default
mode) or hard-discarding (`--discard`). Dry-run flag echoes what
WOULD happen without touching Redis.

Typical post-incident reflex:
    1. Incident clean-up complete; DB paths healthy again.
    2. SSH to the scheduler container.
    3. `python -m backend.scripts.replay_all_poison`
    4. Tail logs for `poison_drained` / `poison_replay_requeued`
       structured events.

Same admin-only safety as the API endpoint — script imports the
service-layer helper, which itself rejects unknown DLQ keys and
enforces the `POISON_MAX` upper bound. The script adds:

  * Per-DLQ rate limit (default 50 entries per DLQ, configurable).
  * Inter-DLQ pause (default 0.5 s) so a long replay queue doesn't
    starve the regular reconciler tick.
  * Dry-run mode that reports poison depth without draining.
  * Structured JSON summary on stdout for log aggregation.

Exit codes:
  0   all DLQs drained (or dry-run completed).
  1   one or more DLQs encountered a Redis-unavailable error.
  2   bad CLI args.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from typing import Optional

logger = logging.getLogger("replay_all_poison")


async def _run(
    *,
    max_per_dlq: int,
    discard: bool,
    dry_run: bool,
    inter_dlq_pause_s: float,
) -> int:
    """Returns process exit code."""
    from app.services.dlq_reconciler import (
        _DLQS, _poison_key, POISON_MAX, drain_poison_list,
    )
    try:
        from app.services.redis_service import _get_client
    except Exception:  # noqa: BLE001
        _get_client = None  # type: ignore[assignment]

    summary: dict = {
        "mode":         "discard" if discard else "replay",
        "dry_run":      dry_run,
        "max_per_dlq":  max_per_dlq,
        "dlqs":         [],
        "total_attempted": 0,
        "total_drained":   0,
        "total_requeued":  0,
        "total_discarded": 0,
        "any_redis_unavailable": False,
    }

    if max_per_dlq < 1 or max_per_dlq > POISON_MAX:
        print(
            f"--max-per-dlq must be 1..{POISON_MAX}, got {max_per_dlq}",
            file=sys.stderr,
        )
        return 2

    for idx, (dlq_key, _max_size, _fn) in enumerate(_DLQS):
        pkey = _poison_key(dlq_key)

        # Probe depth first — useful for both dry-run and live runs.
        depth: Optional[int] = None
        if _get_client is not None:
            c = _get_client()
            if c is None:
                summary["any_redis_unavailable"] = True
            else:
                try:
                    depth = int(c.llen(pkey) or 0)
                except Exception:  # noqa: BLE001
                    summary["any_redis_unavailable"] = True

        entry: dict = {
            "dlq":          dlq_key,
            "poison_depth": depth,
        }

        if dry_run:
            entry["action"] = "would_drain" if depth else "would_skip_empty"
            summary["dlqs"].append(entry)
            continue

        # Skip cleanly when depth is zero — avoids a wasted Redis
        # call inside `drain_poison_list`.
        if depth == 0:
            entry["action"] = "skipped_empty"
            entry["attempted"] = 0
            summary["dlqs"].append(entry)
            continue

        try:
            result = await drain_poison_list(
                dlq_key,
                replay=not discard,
                max_drain=max_per_dlq,
            )
        except ValueError as e:
            entry["action"] = "error"
            entry["error"] = str(e)
            summary["dlqs"].append(entry)
            continue

        if result.get("error") == "redis_unavailable":
            summary["any_redis_unavailable"] = True
        attempted = int(result.get("attempted", 0) or 0)
        drained = int(result.get("drained", 0) or 0)
        requeued = int(result.get("requeued", 0) or 0)
        discarded = int(result.get("discarded", 0) or 0)

        entry["action"]    = result.get("mode")
        entry["attempted"] = attempted
        if not discard:
            entry["drained"]  = drained
            entry["requeued"] = requeued
        else:
            entry["discarded"] = discarded
        summary["dlqs"].append(entry)

        summary["total_attempted"] += attempted
        summary["total_drained"]   += drained
        summary["total_requeued"]  += requeued
        summary["total_discarded"] += discarded

        # Don't starve the regular reconciler tick — short pause
        # between DLQs lets the 60 s scheduler interleave.
        if idx < len(_DLQS) - 1 and inter_dlq_pause_s > 0:
            await asyncio.sleep(inter_dlq_pause_s)

    print(json.dumps(summary, indent=2))
    return 1 if summary["any_redis_unavailable"] else 0


def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "One-shot drain of every registered DLQ poison list. "
            "Replays by default; pass --discard to hard-delete and "
            "echo payloads, --dry-run to report depth without touching."
        ),
    )
    p.add_argument(
        "--max-per-dlq", type=int, default=50,
        help="Max entries to drain per DLQ in one pass (1..POISON_MAX).",
    )
    p.add_argument(
        "--discard", action="store_true",
        help="Hard-discard mode (echoes payloads). Default is replay.",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Report poison depth per DLQ without draining.",
    )
    p.add_argument(
        "--inter-dlq-pause-s", type=float, default=0.5,
        help="Seconds to pause between DLQs so the scheduler can interleave.",
    )
    p.add_argument(
        "--log-level", default="INFO",
        help="Python logging level (default INFO).",
    )
    return p.parse_args()


def main() -> int:
    args = _parse()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if args.dry_run and args.discard:
        print(
            "--dry-run and --discard are mutually exclusive",
            file=sys.stderr,
        )
        return 2
    return asyncio.run(_run(
        max_per_dlq=args.max_per_dlq,
        discard=args.discard,
        dry_run=args.dry_run,
        inter_dlq_pause_s=args.inter_dlq_pause_s,
    ))


if __name__ == "__main__":
    raise SystemExit(main())
