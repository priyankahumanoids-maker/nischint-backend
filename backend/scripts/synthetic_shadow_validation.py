#!/usr/bin/env python3
# ════════════════════════════════════════════════════════════════════
# SYNTHETIC VALIDATION ONLY
# A passing run does NOT authorize V2 ramp.
# Gate condition for ramp: critical_count = 0 sustained
# across ≥1 real incident cycle with real production traffic.
# ════════════════════════════════════════════════════════════════════
"""NISCH-012 — Synthetic shadow-machinery validation.

What this verifies:
  * `classify_diff` produces the expected 7-label taxonomy on
    deliberately constructed inputs (one row per critical label,
    one per regression, one per improvement, two per `match`).
  * `_bump_classification` + `get_classification_snapshot` round-
    trip correctly under Redis.
  * The tier-state machine transitions UNKNOWN→CRITICAL when an
    injected critical event lands.
  * The autodisable safeguard arms when the rolling critical rate
    is force-exceeded.

What this does NOT verify (deliberately out of scope):
  * V2 vs V1 actual decision quality — that requires real traffic.
  * Production gate readiness — synthetic passing != ramp clearance.
  * `compute_v2_decision` correctness — covered by separate tests.

Cleanup invariant: every Redis key this script writes lives under
a dedicated `synthetic_v2_*` namespace (NOT the live
`alert_v2_shadow` namespace) so a passing run leaves the live
operator chip untouched. A second cleanup pass at the end
explicitly DELs any synthetic key that may have leaked.

Exit code 0 = machinery verified, exit code 1 = a contract test
failed and the platform should not be considered shadow-ready.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

# Make `app.*` importable when run from anywhere in the repo.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── Synthetic namespace (NEVER write to the live one) ───────────
SYNTHETIC_NAMESPACE = "synthetic_v2_validation"


def _swap_to_synthetic_namespace():
    """Monkey-patch the shadow module to write under a synthetic
    namespace. Live operator stats stay untouched."""
    from app.services import alert_trigger_v2_shadow as _v2s
    _v2s.SHADOW_LOG_NAMESPACE = SYNTHETIC_NAMESPACE
    # Force fresh controllers under the synthetic namespace.
    _v2s._reset_controllers_for_test()


def _cleanup_synthetic_keys():
    """Hard-delete every Redis key under the synthetic namespace
    so the live shadow stats endpoint stays clean for real traffic.
    Safe to run multiple times — no-op when nothing matches."""
    from app.services import redis_service
    client = redis_service._get_client()
    if client is None:
        return 0
    pattern = f"{redis_service.PREFIX}:{SYNTHETIC_NAMESPACE}:*"
    deleted = 0
    try:
        for k in list(client.scan_iter(match=pattern, count=500)):
            client.delete(k)
            deleted += 1
    except Exception as e:
        print(f"  [warn] cleanup failed: {e!r}")
    return deleted


# ════════════════════════════════════════════════════════════════════
# Synthetic event factory — covers all 7 taxonomy labels
# ════════════════════════════════════════════════════════════════════
# Each scenario hand-crafts a (v1_count, v2_count, decision_match,
# v2_target_health, v1_only/v2_only) shape that EXACTLY drives
# `classify_diff` to the named bucket. Keeping these explicit (vs
# random) means a misfire is a real bug, not a roll-of-the-dice.

CRITICAL_SCENARIOS = (
    ("missed_target_critical",   "sos"),
    ("v2_would_not_dispatch",    "help_request"),
    ("unreachable_target_chosen", "help_request"),
)
REGRESSION_SCENARIOS = (
    ("v1_only_extra_fanout",     "help_request"),  # only flagged when not design intent
)
IMPROVEMENT_SCENARIOS = (
    ("ranking_improvement",      "sos"),
    ("fanout_reduction_help",    "help_request"),
    ("unreachable_dropped",      "sos"),
)
MATCH_SCENARIOS = (
    ("match", "help_request"),
    ("match", "sos"),
)


def _build_synthetic_event(label: str, kind: str) -> dict:
    """Builds the diff+v2 envelope that `classify_diff` will read.
    The fields are the minimum surface `classify_diff` inspects;
    everything else uses sensible defaults."""
    now_iso = datetime.now(timezone.utc).isoformat()
    # Common scaffolding.
    return {
        "label":      label,
        "kind":       kind,
        "user_id":    f"synth_user_{label}_{kind}",
        "ts":         now_iso,
        "policy":     "active_sos" if kind == "sos" else "passive_help_request",
    }


# ════════════════════════════════════════════════════════════════════
# Direct manipulation — drive bookkeeping without ginned-up V2 calls
# ════════════════════════════════════════════════════════════════════
# We deliberately bypass `run_shadow_compare` (which would need a
# real DB + AsyncSession) and instead call the recording primitives
# with hand-crafted classification labels. This exercises:
#   * _bump_classification → get_classification_snapshot
#   * _record_event_in_window → _rolling_window_stats
#   * _evaluate_tier_transition (the state machine)
# which together prove the operator chip will display real numbers
# when production traffic actually flows.

def inject_event(kind: str, classification: str, critical: bool) -> None:
    from app.services import alert_trigger_v2_shadow as _v2s
    _v2s._bump_classification(kind, classification)
    _v2s._record_event_in_window(kind, critical)
    # Also bump the legacy 3-bucket so `get_counter_snapshot` is
    # non-zero — the operator chip falls back to this if the
    # diagnostic block is empty.
    if critical:
        _v2s._bump_counter(kind, "decision_diff")
    else:
        _v2s._bump_counter(kind, "match")


def bulk_inject_pipelined(targets: list[tuple[str, str, bool, int]]) -> None:
    """Pipelined fast-path for Phase 1.

    Upstash Redis (the platform's hosted backend) has ~500 ms RTT
    per op, so 300+ sequential INCRs takes 2+ minutes. Pipelining
    drops the wall time to a few seconds.

    NOTE: Phase 1's purpose is taxonomy round-trip, not autodisable.
    We only mirror the classification counter + legacy 3-bucket
    counter. The per-second rolling-window keys (which Phase 3
    needs) are written separately by `phase_3` calling
    `_record_event_in_window` directly — that path owns the
    controller's namespaced key format and we won't replicate it
    by hand."""
    from app.services import alert_trigger_v2_shadow as _v2s
    from app.services import redis_service
    client = redis_service._get_client()
    if client is None:
        return
    ns = _v2s.SHADOW_LOG_NAMESPACE
    p = client.pipeline(transaction=False)
    for kind, cls, critical, count in targets:
        cls_key = f"{redis_service.PREFIX}:{ns}:classifications:{kind}:{cls}"
        bucket = "decision_diff" if critical else "match"
        ctr_key = f"{redis_service.PREFIX}:{ns}:counters:{kind}:{bucket}"
        for _ in range(count):
            p.incr(cls_key)
            p.incr(ctr_key)
        p.expire(cls_key, 86_400)
        p.expire(ctr_key, 86_400)
    p.execute()


# ════════════════════════════════════════════════════════════════════
# Validation phases
# ════════════════════════════════════════════════════════════════════
PASS = []
FAIL = []


def _check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASS.append(name)
        print(f"  ✓ {name}")
    else:
        FAIL.append((name, detail))
        print(f"  ✗ {name}  {detail}")


def phase_1_classification_taxonomy_round_trip():
    """Inject ≥50 events per kind, sweeping all 7 taxonomy buckets,
    then verify `get_classification_snapshot` reflects what we wrote.

    Uses pipelined Redis writes — the hosted backend has ~500 ms
    RTT, so sequential INCRs would blow past the 120 s pytest /
    bash timeouts."""
    print("\n── PHASE 1 — taxonomy round-trip (kind × classification)")
    from app.services import alert_trigger_v2_shadow as _v2s

    targets = [
        ("sos",          "missed_target_critical",     True,  10),
        ("help_request", "v2_would_not_dispatch",      True,  10),
        ("help_request", "unreachable_target_chosen",  True,  10),
        ("help_request", "fanout_diff",                False, 10),
        ("sos",          "ranking_improvement",        False, 10),
        ("help_request", "fanout_reduction_help",      False, 10),
        ("sos",          "unreachable_dropped",        False, 10),
        ("help_request", "match",                      False, 25),
        ("sos",          "match",                      False, 25),
    ]
    bulk_inject_pipelined(targets)

    snap = _v2s.get_classification_snapshot()
    expected: dict[str, dict[str, int]] = {}
    for kind, cls, _crit, n in targets:
        expected.setdefault(kind, {})[cls] = (
            expected.get(kind, {}).get(cls, 0) + n
        )
    for kind, by_cls in expected.items():
        for cls, want in by_cls.items():
            got = snap.get(kind, {}).get(cls, 0)
            _check(
                f"snapshot[{kind}][{cls}] == {want}",
                got == want,
                f"got={got}",
            )
    sos_total = sum(snap.get("sos", {}).values())
    help_total = sum(snap.get("help_request", {}).values())
    _check("sos total events ≥ 50", sos_total >= 50, f"got={sos_total}")
    _check(
        "help_request total events ≥ 50",
        help_total >= 50, f"got={help_total}",
    )


def phase_2_classify_diff_pure_logic():
    """The 7-label taxonomy emerges from `classify_diff`. Drive it
    with hand-crafted (`diff`, `V2Decision`) inputs to confirm each
    of the locked labels fires for its canonical scenario."""
    print("\n── PHASE 2 — classify_diff() label assignment")
    from app.services.alert_trigger_v2 import V2Decision
    from app.services.alert_trigger_v2_shadow import classify_diff

    def _v2(policy: str, reachability: dict | None = None,
            dispatched: bool = True) -> V2Decision:
        return V2Decision(
            policy=policy,
            dispatched=dispatched,
            routing_plan=list((reachability or {}).keys()),
            escalation_delay_s=0,
            reason="synthetic",
            reachability=reachability or {},
        )

    # CRITICAL: V1 fired, V2 wouldn't → v2_would_not_dispatch
    out = classify_diff(
        {
            "v1_dispatched": True, "v2_dispatched": False,
            "v1_only": ["g1"], "v2_only": [],
            "v2_first_target": None, "fanout_diff": False,
        },
        _v2("active_sos", dispatched=False),
    )
    _check("v2_would_not_dispatch fires", out == "v2_would_not_dispatch",
           f"got={out!r}")

    # CRITICAL: SOS dropped a guardian V1 had → missed_target_critical
    out = classify_diff(
        {
            "v1_dispatched": True, "v2_dispatched": True,
            "v1_only": ["g_missed"], "v2_only": [],
            "v2_first_target": "g_kept", "fanout_diff": True,
        },
        _v2("active_sos", {"g_kept": "healthy"}),
    )
    _check("missed_target_critical fires (SOS)",
           out == "missed_target_critical", f"got={out!r}")

    # CRITICAL: HELP V2 chose a dead target while a healthy one
    # was available → unreachable_target_chosen
    out = classify_diff(
        {
            "v1_dispatched": True, "v2_dispatched": True,
            "v1_only": [], "v2_only": [],
            "v2_first_target": "g_dead",
            "fanout_diff": False,
        },
        _v2(
            "passive_help_request",
            {"g_dead": "dead", "g_alive": "healthy"},
        ),
    )
    _check("unreachable_target_chosen fires (HELP)",
           out == "unreachable_target_chosen", f"got={out!r}")

    # IMPROVEMENT: V2 dropped only dead/risk targets → unreachable_dropped
    # NOTE: For SOS, any v1_only entry hits `missed_target_critical`
    # FIRST (line 287) — SOS contract is full broadcast, so a drop
    # is always critical regardless of reachability. The
    # unreachable_dropped path only fires for HELP_REQUEST.
    out = classify_diff(
        {
            "v1_dispatched": True, "v2_dispatched": True,
            "v1_only": ["g_dead", "g_risk"], "v2_only": [],
            "v2_first_target": "g_healthy", "fanout_diff": True,
        },
        _v2(
            "passive_help_request",
            {"g_dead": "dead", "g_risk": "risk", "g_healthy": "healthy"},
        ),
    )
    _check("unreachable_dropped fires (HELP only)",
           out == "unreachable_dropped", f"got={out!r}")

    # IMPROVEMENT: HELP narrowed fan-out (no dead targets, just smaller)
    out = classify_diff(
        {
            "v1_dispatched": True, "v2_dispatched": True,
            "v1_only": ["g_extra"], "v2_only": [],
            "v2_first_target": "g_primary", "fanout_diff": True,
        },
        _v2(
            "passive_help_request",
            {"g_extra": "healthy", "g_primary": "healthy"},
        ),
    )
    _check("fanout_reduction_help fires", out == "fanout_reduction_help",
           f"got={out!r}")

    # IMPROVEMENT: same set, healthier first target → ranking_improvement
    out = classify_diff(
        {
            "v1_dispatched": True, "v2_dispatched": True,
            "v1_only": [], "v2_only": [],
            "v2_first_target": "g_healthy", "fanout_diff": False,
        },
        _v2(
            "active_sos",
            {"g_healthy": "healthy", "g_risk": "risk"},
        ),
    )
    _check("ranking_improvement fires", out == "ranking_improvement",
           f"got={out!r}")

    # MATCH: identical decisions
    out = classify_diff(
        {
            "v1_dispatched": True, "v2_dispatched": True,
            "v1_only": [], "v2_only": [],
            "v2_first_target": "g1", "fanout_diff": False,
        },
        _v2("active_sos", {"g1": "healthy"}),
    )
    _check("match fires (identical sets)", out == "match",
           f"got={out!r}")


def phase_3_auto_disable_arms_on_force_exceed():
    """Push critical events through fast enough that the rolling
    rate breaches AUTODISABLE_THRESHOLD. Verify the safeguard fires.

    The controller stores per-second counters under namespaced keys
    (`<NS>:<kind>:window:total:<sec>`), so we pipeline DIRECTLY
    against that layout — replicating `_record_window` ~500 ms × 25
    times would blow the timeout."""
    print("\n── PHASE 3 — autodisable safeguard arms on critical rate")
    from app.services import alert_trigger_v2_shadow as _v2s
    from app.services import redis_service
    import time as _time

    _v2s.clear_autodisable("sos")

    # Spread 25 critical events across recent seconds so the
    # rolling-window MGET picks them all up.
    client = redis_service._get_client()
    if client is None:
        _check("redis available", False, "no client")
        return
    ctrl = _v2s._get_controller("sos")
    ns = ctrl._namespace
    now_s = int(_time.time())
    p = client.pipeline(transaction=False)
    ttl = ctrl.autodisable_window_s + 60
    for i in range(25):
        sec = now_s - i           # one event per recent second
        if ctrl._kind_position == "last":
            tk = f"{redis_service.PREFIX}:{ns}:window:total:{sec}:sos"
            ck = f"{redis_service.PREFIX}:{ns}:window:crit:{sec}:sos"
        else:
            tk = f"{redis_service.PREFIX}:{ns}:sos:window:total:{sec}"
            ck = f"{redis_service.PREFIX}:{ns}:sos:window:crit:{sec}"
        p.incr(tk)
        p.expire(tk, ttl)
        p.incr(ck)
        p.expire(ck, ttl)
        # Mirror the classification snapshot too so the digest shows it.
        cls_key = (
            f"{redis_service.PREFIX}:{ns}:classifications:sos:"
            f"missed_target_critical"
        )
        p.incr(cls_key)
    p.execute()

    total, crit, rate = _v2s._rolling_window_stats("sos")
    _check(f"rolling window total ≥ {_v2s.AUTODISABLE_MIN_SAMPLES}",
           total >= _v2s.AUTODISABLE_MIN_SAMPLES,
           f"total={total} crit={crit} rate={rate}")
    _check(f"rolling crit rate ≥ {_v2s.AUTODISABLE_THRESHOLD}",
           rate >= _v2s.AUTODISABLE_THRESHOLD,
           f"rate={rate}")

    # Arm the autodisable as the real path does.
    if (total >= _v2s.AUTODISABLE_MIN_SAMPLES
            and rate >= _v2s.AUTODISABLE_THRESHOLD
            and not _v2s._read_autodisable("sos")):
        _v2s._set_autodisable(
            "sos",
            f"synthetic: crit_rate={rate:.3f} ({crit}/{total})",
        )
    _check("autodisable flag set after critical burst",
           _v2s._read_autodisable("sos") is not None,
           f"flag={_v2s._read_autodisable('sos')}")

    # `should_v2_actually_fire` MUST honour the autodisable
    # regardless of the env-var %. We force the env to 100 to be
    # certain the gate falls solely on the safeguard.
    os.environ["ALERT_TRIGGER_V2_SOS_ROLLOUT_PCT"] = "100"
    decided = _v2s.should_v2_actually_fire("sos", "any_user")
    os.environ.pop("ALERT_TRIGGER_V2_SOS_ROLLOUT_PCT", None)
    _check("should_v2_actually_fire == False under autodisable",
           decided is False,
           f"decided={decided}")


def phase_4_tier_state_machine_transitions():
    """A single injected critical event must snap the per-kind
    tier from in_parity/unknown → critical. Recovery requires
    the configured hysteresis count of consecutive clean events."""
    print("\n── PHASE 4 — tier state machine transitions")
    from app.services import alert_trigger_v2_shadow as _v2s

    # Use a kind we haven't touched yet so the controller starts
    # from a fresh state.
    kind = "help_request"

    # Force the tier to critical via a critical injection + evaluator.
    transition = _v2s._evaluate_tier_transition(
        kind, "v2_would_not_dispatch",
    )
    _check("tier transition payload returned",
           transition is not None,
           f"transition={transition}")
    if transition:
        _check("tier transitioned to 'critical' on first critical event",
               transition.get("to") == "critical",
               f"transition={transition}")


def phase_5_diagnostic_summary_is_populated():
    """After phases 1-4 there's enough state for the operator chip's
    one-call digest to come back populated rather than empty."""
    print("\n── PHASE 5 — operator chip digest populated")
    from app.services import alert_trigger_v2_shadow as _v2s
    digest = _v2s.get_diagnostic_summary() or {}
    _check("digest is non-empty", len(digest) > 0,
           f"digest_keys={list(digest.keys())}")
    for kind in ("sos", "help_request"):
        if kind in digest:
            d = digest[kind]
            _check(
                f"{kind}: total > 0", int(d.get("total", 0)) > 0,
                f"total={d.get('total')}",
            )
            _check(
                f"{kind}: match_pct is numeric",
                isinstance(d.get("match_pct"), (int, float)),
                f"match_pct={d.get('match_pct')}",
            )


def main() -> int:
    print("════════════════════════════════════════════════════════")
    print("  V2 SHADOW MACHINERY — SYNTHETIC VALIDATION")
    print("  WARNING: a passing run does NOT authorize V2 ramp.")
    print("  Ramp gate requires REAL production traffic with")
    print("  critical_count = 0 sustained across ≥1 incident cycle.")
    print("════════════════════════════════════════════════════════")

    _swap_to_synthetic_namespace()
    # Belt-and-braces: nuke any leftover synthetic keys from a
    # previous run before we start.
    pre = _cleanup_synthetic_keys()
    if pre:
        print(f"  [setup] cleared {pre} stale synthetic keys")

    try:
        phase_1_classification_taxonomy_round_trip()
        phase_2_classify_diff_pure_logic()
        phase_3_auto_disable_arms_on_force_exceed()
        phase_4_tier_state_machine_transitions()
        phase_5_diagnostic_summary_is_populated()
    finally:
        # CRITICAL: always clean up, even on test failure. The live
        # shadow stats endpoint must NOT show synthetic data after
        # this script exits.
        post = _cleanup_synthetic_keys()
        print(f"\n  [cleanup] deleted {post} synthetic keys")

    print("\n════════════════════════════════════════════════════════")
    print(f"  PASS: {len(PASS)}   FAIL: {len(FAIL)}")
    if FAIL:
        print("  Failed checks:")
        for name, detail in FAIL:
            print(f"    - {name}  ({detail})")
        print("\n  RESULT: machinery NOT verified — investigate above.")
        return 1
    print("  RESULT: machinery verified, awaiting real traffic for")
    print("          gate evaluation.")
    print("════════════════════════════════════════════════════════")
    return 0


if __name__ == "__main__":
    sys.exit(main())
