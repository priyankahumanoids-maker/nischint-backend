"""Broadcast-before-persist audit — catches the inverse of the
NISCH-AUDIT-001 bug class.

THE PATTERN BEING AUDITED
─────────────────────────
A function does:

    await broadcaster.broadcast_to_user(...)   # ← side effect FIRES
    session.add(GuardianAlert(...))
    await session.commit()                     # ← may roll back

If the persist fails, the broadcast has already gone out. Guardian
sees an alert in their app; the audit row never lands. Same
operational failure mode as the silent-missing-row bug, but the
*cause* is ordering, not error handling.

TIER MODEL (locked from operator review)
────────────────────────────────────────
Not all side effects are equal:

    Tier A  =  un-undo-able external effects
               push notifications, SMS, email, voice calls,
               webhook outbound
               → MUST appear after `session.flush()` in the same
                 function body. No allow-list rationale gate;
                 these are hard fails.

    Tier B  =  same-session real-time delivery
               WebSocket / SSE / metrics counters
               → flagged at WARN level; allow-listable WITHOUT a
                 rationale gate because the same-session WebSocket
                 layer is itself observable from operators (a
                 broadcast-without-row is visibly weird in the UI).

The tiering is what keeps the audit actionable. Without it, the
audit would generate so many Tier B findings during
`shadow_rollout.py` extraction that engineers start ignoring it.

THIS PR ships the audit in REPORT-ONLY mode:
- Tier A findings → printed loudly to pytest output for review.
- Tier B findings → counted only.
- The test ALWAYS PASSES initially (baseline capture). Once the
  baseline is reviewed, the enforcement flag flips and Tier A
  findings start failing CI.

This is the same shadow-first pattern the system uses for V2
dispatch: observe → diff → enforce.
"""
from __future__ import annotations

import ast
import pathlib
from dataclasses import dataclass

import pytest


# ── Tier classification — locked from operator review ──────────────
# Function names (last attribute / bare name) treated as Tier A.
_TIER_A_CALL_NAMES = frozenset({
    # Push
    "send_push_to_user", "send_push", "send_push_to_token",
    # SMS / voice via Twilio + our wrappers
    "send_sms", "send_sms_to_guardian",
    "make_voice_call_with_callback", "make_voice_call",
    "intelligent_escalation",
    # Email
    "send_email", "send_digest_email",
    # Guardian-notification dispatcher (umbrella for push+sms)
    "dispatch_guardian_alert",
    # Outbound webhooks
    "post_webhook", "send_webhook",
})

# Function names treated as Tier B (same-session WS/SSE/metrics).
_TIER_B_CALL_NAMES = frozenset({
    "broadcast_to_user", "broadcast_to_operators",
    "publish", "emit",   # generic SSE / event bus
    "record",            # metrics
    "incr", "bump",      # counter ops
})


def _call_name(node: ast.Call) -> str | None:
    fn = node.func
    if isinstance(fn, ast.Attribute):
        return fn.attr
    if isinstance(fn, ast.Name):
        return fn.id
    return None


def _classify_call(node: ast.Call) -> str | None:
    n = _call_name(node)
    if n is None:
        return None
    if n in _TIER_A_CALL_NAMES:
        return "A"
    if n in _TIER_B_CALL_NAMES:
        return "B"
    return None


# ── INSERT detection (mirrors swallow audit) ────────────────────────
def _is_insert_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    fn = node.func
    if isinstance(fn, ast.Attribute) and fn.attr in (
        "add", "add_all", "commit", "flush",
    ):
        return True
    if (
        isinstance(fn, ast.Attribute) and fn.attr == "execute"
        and node.args
    ):
        first = node.args[0]
        if isinstance(first, ast.Call):
            ifn = first.func
            if isinstance(ifn, ast.Name) and ifn.id == "insert":
                return True
    return False


def _is_flush_or_commit(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    fn = node.func
    return (
        isinstance(fn, ast.Attribute)
        and fn.attr in ("flush", "commit")
    )


# ── Per-function scanner ───────────────────────────────────────────
@dataclass(frozen=True)
class Finding:
    file:     str
    line:     int          # line of the broadcast call
    tier:     str          # "A" | "B"
    call:     str
    function: str

    def key(self) -> tuple[str, int]:
        return (self.file, self.line)


def _scan_function(
    fn_node: ast.FunctionDef | ast.AsyncFunctionDef,
    rel_file: str,
) -> list[Finding]:
    """Within a single function body, find every Tier-A/B broadcast
    that appears in source order BEFORE the next flush()/commit()
    that follows an INSERT. We also flag broadcasts where there is
    NO flush at all in the same function body — the row is
    not persisted before the broadcast fires."""
    insert_lines: list[int] = []
    flush_lines:  list[int] = []
    broadcasts:   list[tuple[int, str, str]] = []  # (lineno, tier, name)
    for sub in ast.walk(fn_node):
        if isinstance(sub, ast.Call):
            if _is_insert_call(sub):
                insert_lines.append(sub.lineno)
            if _is_flush_or_commit(sub):
                flush_lines.append(sub.lineno)
            tier = _classify_call(sub)
            if tier is not None:
                broadcasts.append(
                    (sub.lineno, tier, _call_name(sub) or "?")
                )

    findings: list[Finding] = []
    for bc_line, tier, call in broadcasts:
        # Only relevant if there's an INSERT in the same function.
        if not insert_lines:
            continue
        first_insert = min(insert_lines)
        # Broadcast happened BEFORE any INSERT in this fn? That's a
        # different pattern (broadcast-without-row); we still flag it
        # because the persist below it may fail and leave the
        # broadcast unsupported.
        last_flush_before_bc = max(
            (fl for fl in flush_lines if fl < bc_line),
            default=None,
        )
        if last_flush_before_bc is None:
            # No flush has run before this broadcast.
            findings.append(Finding(
                file=rel_file, line=bc_line, tier=tier,
                call=call, function=fn_node.name,
            ))
        elif last_flush_before_bc < first_insert:
            # The flush we found was for an earlier INSERT — the
            # most-recent INSERT (after that flush) is still pending
            # when the broadcast fires.
            if any(il > last_flush_before_bc and il < bc_line
                   for il in insert_lines):
                findings.append(Finding(
                    file=rel_file, line=bc_line, tier=tier,
                    call=call, function=fn_node.name,
                ))
    return findings


def _scan_file(path: pathlib.Path, root: pathlib.Path) -> list[Finding]:
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except SyntaxError:
        return []
    rel = str(path.relative_to(root))
    out: list[Finding] = []
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.extend(_scan_function(n, rel))
    return out


# ── Allow-list (Tier A AND Tier B) ─────────────────────────────────
#
# Tier A allow-list entry schema (locked from operator review):
#   {
#     "reason":              str   # ≥ 20 chars, no legacy/todo/wip
#     "category":            "compensating_action_exists" | "unresolved_debt"
#     "compensating_ref":    "app/services/x.py:symbol"
#     "reconciliation_state": "automatic" | "operator_manual" | "none"
#   }
#
# Contradiction guard (enforced by test): you CANNOT have
#   category = "compensating_action_exists" AND reconciliation_state = "none"
# That combination is rejected — `compensating_action_exists` requires
# a named, real, code-referenced reconciliation mechanism. If no such
# mechanism exists, the correct category is `unresolved_debt`.

_RECONCILIATION_STATES = frozenset({"automatic", "operator_manual", "none"})


# ── Constants ──────────────────────────────────────────────────────
# Local copies of the category strings — must match the swallow-audit
# enum exactly. Tests below validate the values.
COMPENSATING_ACTION_EXISTS = "compensating_action_exists"
UNRESOLVED_DEBT            = "unresolved_debt"
_VALID_CATEGORIES = frozenset({
    COMPENSATING_ACTION_EXISTS, UNRESOLVED_DEBT,
})

# ── Enforcement flag ───────────────────────────────────────────────
# ENFORCED per locked Step 3. The 7 baseline Tier A findings are
# allow-listed below with the full schema (reason + category +
# compensating_ref + reconciliation_state). Any NEW Tier A finding
# introduced in subsequent PRs will fail CI unless it lands in
# `_ALLOWED_TIER_A` AND passes the contradiction-guard test.
_ENFORCE_TIER_A = True


_ALLOWED_TIER_A: dict[tuple[str, int], dict] = {
    ("app/services/sms_service.py", 366): {
        "reason":
            "Voice-call retry loop in `escalation_flow`. EscalationEvent "
            "row IS the audit-of-record for the call lifecycle (created "
            "earlier upstream); GuardianAlert row that may roll back is "
            "supplementary. Twilio CallSid is logged before the call "
            "attempt so operators can correlate against Twilio's audit "
            "log if reconciliation is needed.",
        "category": COMPENSATING_ACTION_EXISTS,
        "compensating_ref": "app/services/sequential_escalation.py:save_call_state",
        "reconciliation_state": "automatic",
    },
    ("app/services/checkin_service.py", 412): {
        "reason":
            "Stale-checkin sweeper push. The sweeper itself IS the "
            "reconciliation: if the SafetyEvent row creation fails, "
            "the next sweeper tick re-detects the still-pending "
            "check-in and retries the whole sequence.",
        "category": COMPENSATING_ACTION_EXISTS,
        "compensating_ref": "app/services/checkin_service.py:expire_stale_checkins",
        "reconciliation_state": "automatic",
    },
    ("app/services/auto_escalation_engine.py", 142): {
        "reason":
            "Failsafe push #1 inside `_trigger_guardian_failsafe`. "
            "No separate audit-of-record exists for the escalation "
            "lifecycle — GuardianAlert IS the audit row, and if its "
            "commit rolls back the only trace is in Twilio's logs / "
            "FCM delivery receipts. Genuine debt: should reorder to "
            "persist-then-broadcast.",
        "category": UNRESOLVED_DEBT,
        "compensating_ref": "app/services/auto_escalation_engine.py:_trigger_guardian_failsafe",
        "reconciliation_state": "none",
    },
    ("app/services/auto_escalation_engine.py", 174): {
        "reason":
            "Failsafe push #2 inside `_trigger_guardian_failsafe`. "
            "Same situation as :142 — GuardianAlert IS the audit row, "
            "no separate EscalationEvent model exists. Genuine debt.",
        "category": UNRESOLVED_DEBT,
        "compensating_ref": "app/services/auto_escalation_engine.py:_trigger_guardian_failsafe",
        "reconciliation_state": "none",
    },
    ("app/services/auto_escalation_engine.py", 323): {
        "reason":
            "Sequential intelligent_escalation kick-off inside "
            "`_trigger_guardian_failsafe`. EscalationEvent row IS "
            "audit-of-record; sequential_escalation persists per-leg "
            "state via save_call_state.",
        "category": COMPENSATING_ACTION_EXISTS,
        "compensating_ref": "app/services/sequential_escalation.py:save_call_state",
        "reconciliation_state": "automatic",
    },
    ("app/services/auto_escalation_engine.py", 518): {
        "reason":
            "Auto-escalated push inside `_trigger_escalation`. "
            "EscalationEvent row IS audit-of-record; per-leg state "
            "saved by sequential_escalation.",
        "category": COMPENSATING_ACTION_EXISTS,
        "compensating_ref": "app/services/sequential_escalation.py:save_call_state",
        "reconciliation_state": "automatic",
    },
    ("app/services/sequential_escalation.py", 209): {
        "reason":
            "Voice call inside `intelligent_escalation`. CallState row "
            "is persisted before this call site; Twilio webhook "
            "callback updates state by CallSid lookup, which is "
            "the canonical reconciliation path for voice lifecycle.",
        "category": COMPENSATING_ACTION_EXISTS,
        "compensating_ref": "app/services/sequential_escalation.py:save_call_state",
        "reconciliation_state": "automatic",
    },
}


# Tier B allow-list — same shape but `compensating_ref` /
# `reconciliation_state` are optional (per locked tiering: Tier B is
# allow-listable without a rationale gate because operators see WS
# oddities directly in the UI).
_ALLOWED_TIER_B: dict[tuple[str, int], dict] = {
    # Baseline left empty for this PR — Tier B findings are counted
    # only; allow-listing happens organically when operator review
    # determines a specific WS broadcast is legitimately ahead of
    # its row.
}


# ── Tests ──────────────────────────────────────────────────────────
_AUDIT_ROOTS = [
    "app/services",
    "app/api",
]


def _collect_findings() -> list[Finding]:
    root = pathlib.Path(__file__).resolve().parents[1]
    out: list[Finding] = []
    for sub in _AUDIT_ROOTS:
        for p in (root / sub).rglob("*.py"):
            out.extend(_scan_file(p, root))
    return out


def test_broadcast_before_persist_report(capsys):
    """REPORT-ONLY phase: surface Tier A + Tier B findings to pytest
    output so the operator review can baseline them.

    Once the baseline is reviewed and Tier A findings are either
    fixed or known-safe, `_ENFORCE_TIER_A` flips to True and the
    audit enters enforcement mode (Tier A becomes a hard fail)."""
    findings = _collect_findings()
    tier_a = [f for f in findings if f.tier == "A"]
    tier_b = [f for f in findings if f.tier == "B"]

    with capsys.disabled():
        print()
        print(f"[broadcast-before-persist] tier_a={len(tier_a)} tier_b={len(tier_b)} enforce_tier_a={_ENFORCE_TIER_A}")
        if tier_a:
            print("[broadcast-before-persist] TIER A (un-undo-able side effects before persist):")
            for f in tier_a:
                print(f"  {f.file}:{f.line}  in `{f.function}`  call={f.call}()")
        if tier_b:
            print("[broadcast-before-persist] TIER B (real-time delivery, allow-listable):")
            for f in tier_b[:10]:
                print(f"  {f.file}:{f.line}  in `{f.function}`  call={f.call}()")
            if len(tier_b) > 10:
                print(f"  … and {len(tier_b) - 10} more.")

    # Enforcement (locked Step 3 — ON).
    if _ENFORCE_TIER_A:
        unsanctioned_a = [
            f for f in tier_a if f.key() not in _ALLOWED_TIER_A
        ]
        assert not unsanctioned_a, (
            "TIER A broadcast-before-persist findings (un-undo-able "
            "side effects firing before the row is flushed). Each "
            "MUST land in `_ALLOWED_TIER_A` with the full schema:\n"
            "  reason / category / compensating_ref / reconciliation_state\n\n"
            + "\n".join(
                f"  {f.file}:{f.line}  in `{f.function}`  call={f.call}()"
                for f in unsanctioned_a
            )
        )


def test_tier_a_allow_list_schema_complete():
    """Every Tier A allow-list entry MUST carry all four required
    fields: reason / category / compensating_ref /
    reconciliation_state. Missing any field is a test failure."""
    required = {"reason", "category", "compensating_ref",
                "reconciliation_state"}
    offenders = []
    for key, entry in _ALLOWED_TIER_A.items():
        missing = required - set(entry.keys())
        if missing:
            offenders.append((key, "missing fields", sorted(missing)))
            continue
        if (entry.get("reason") or "").strip() == "":
            offenders.append((key, "empty reason", ""))
        if len(entry.get("reason", "")) < 20:
            offenders.append((key, "reason too short", entry.get("reason")))
        if entry.get("category") not in _VALID_CATEGORIES:
            offenders.append((key, "invalid category", entry.get("category")))
        if entry.get("reconciliation_state") not in _RECONCILIATION_STATES:
            offenders.append((key, "invalid reconciliation_state",
                              entry.get("reconciliation_state")))
    assert not offenders, (
        f"Tier A allow-list entries with incomplete schema. Required: "
        f"{sorted(required)}. Categories: {sorted(_VALID_CATEGORIES)}. "
        f"Reconciliation states: {sorted(_RECONCILIATION_STATES)}.\n"
        f"Offenders: {offenders}"
    )


def test_tier_a_compensating_ref_points_to_real_file():
    """`compensating_ref` must be of shape
    `path/to/file.py:symbol_or_line` AND the file must exist on
    disk. Pure declaration of intent without a real reference is
    rejected — this is the proof requirement from operator review."""
    root = pathlib.Path(__file__).resolve().parents[1]
    offenders = []
    for key, entry in _ALLOWED_TIER_A.items():
        ref = entry.get("compensating_ref", "")
        if ":" not in ref:
            offenders.append((key, "missing ':' in compensating_ref", ref))
            continue
        ref_path = ref.split(":", 1)[0]
        if not (root / ref_path).exists():
            offenders.append((key, "compensating_ref file not found", ref_path))
    assert not offenders, (
        "Tier A entries with unverifiable compensating_ref. Each must "
        "point to `path/to/file.py:symbol_or_line` where the actual "
        "reconciliation mechanism lives.\n"
        f"Offenders: {offenders}"
    )


def test_tier_a_contradiction_guard():
    """Locked contradiction: `category = compensating_action_exists`
    REQUIRES `reconciliation_state != "none"`. The combination
    'compensated' + 'no reconciliation' is a semantic escape hatch
    — if there's no reconciliation, the correct category is
    `unresolved_debt`. The validator catches the contradiction so
    'safety justifies it' cannot stand in for a named mechanism."""
    offenders = []
    for key, entry in _ALLOWED_TIER_A.items():
        cat = entry.get("category")
        recon = entry.get("reconciliation_state")
        if cat == COMPENSATING_ACTION_EXISTS and recon == "none":
            offenders.append((key, cat, recon))
    assert not offenders, (
        "Tier A entries with contradictory schema: "
        "category=compensating_action_exists + reconciliation_state=none "
        "is forbidden. If no reconciliation mechanism exists, the "
        "correct category is `unresolved_debt`.\n"
        f"Offenders: {offenders}"
    )


def test_tier_a_allow_list_entries_match_real_findings():
    """Stale Tier A allow-list entries (no longer matching a real
    finding) must be removed — same anti-stale rule as the swallow
    audit."""
    findings = _collect_findings()
    keys = {f.key() for f in findings if f.tier == "A"}
    stale = [k for k in _ALLOWED_TIER_A if k not in keys]
    assert not stale, (
        "Stale Tier A allow-list entries — remove them from "
        "_ALLOWED_TIER_A as the underlying code has changed.\n"
        f"Stale: {stale}"
    )


def test_audit_classifies_known_tier_a_names():
    """Sanity: the classifier must know the major Tier A names from
    the operator-locked taxonomy."""
    required = {
        "send_push_to_user", "send_sms", "send_email",
        "dispatch_guardian_alert", "make_voice_call_with_callback",
    }
    missing = required - _TIER_A_CALL_NAMES
    assert not missing, (
        f"Tier A classifier missing names from the locked taxonomy: "
        f"{missing}"
    )


def test_audit_classifies_known_tier_b_names():
    """Sanity: WS/SSE primitives must be Tier B."""
    required = {"broadcast_to_user", "broadcast_to_operators"}
    missing = required - _TIER_B_CALL_NAMES
    assert not missing, (
        f"Tier B classifier missing names: {missing}"
    )


@pytest.mark.parametrize("required_module", [
    "app/services/alert_trigger.py",
    "app/services/auto_escalation_engine.py",
])
def test_audit_scans_high_risk_modules(required_module: str):
    root = pathlib.Path(__file__).resolve().parents[1]
    p = root / required_module
    assert p.exists(), f"audit target missing: {p}"
