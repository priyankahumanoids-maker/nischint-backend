"""Swallow-audit: surface the next instance of the silent-missing-row
bug class at CI time, not at incident-review time.

THE PATTERN BEING AUDITED
─────────────────────────
A try/except block that wraps a DB-INSERT-ish operation
(`session.add(...)`, `session.commit()`, `session.flush()`,
`session.execute(insert(...))`) AND catches broadly
(`except:`, `except Exception:`, `except BaseException:`) AND
swallows the failure (logs + continues, no `raise`). When the
INSERT target has a `NOT NULL` constraint that the caller forgot
to populate, this pattern silently rolls back the audit row WHILE
upstream broadcasts (SSE, push, SMS, voice calls) have already
fired. The system appears healthy. The audit trail is incomplete.

This was the exact failure mode of NISCH-AUDIT-001
(`guardian_alerts.user_id` omitted in 5 sites). Adding this test
prevents the *next* engineer from reintroducing it.

ALLOW-LIST DESIGN (locked)
──────────────────────────
Every entry MUST carry:
  * `reason`   — operational semantics that make the swallow safe
                 (≥ 20 chars, no `legacy/todo/wip/fixme/later`).
  * `category` — one of:
       `idempotency_race`           — DB constraint is the guard;
                                      duplicate-write fails by design.
       `compensating_action_exists` — separate code path reconciles
                                      / retries / re-derives the row.
       `unresolved_debt`            — neither; legacy code awaiting
                                      hardening. This number is the
                                      reliability-hardening backlog
                                      metric.
  * `compensating_ref` — REQUIRED when category is
                         `compensating_action_exists`. Must be of the
                         shape `path/to/file.py:line_or_symbol` and the
                         file must exist. Pure declaration of intent
                         without a real reference is not accepted —
                         the proof-required design prevents
                         `requires_compensating_action` from becoming a
                         semantic escape hatch.

Tagging existing entries this way produces a debt map *before* any
refactor touches these sites, so unresolved_debt entries that get
touched during a refactor can be fixed in the same PR.
"""
from __future__ import annotations

import ast
import pathlib
from dataclasses import dataclass

import pytest


# ── What counts as "INSERT-ish" ──────────────────────────────────────
_INSERT_METHOD_NAMES = frozenset({
    "add",       # session.add(...)
    "add_all",   # session.add_all(...)
    "commit",    # session.commit() — flushes pending INSERTs
    "flush",     # session.flush()
})


def _is_insert_call(node: ast.AST) -> bool:
    """Heuristic: does this call execute / queue an SQLAlchemy INSERT?"""
    if not isinstance(node, ast.Call):
        return False
    fn = node.func

    # session.add(...) | session.commit() | session.flush() | session.add_all(...)
    if isinstance(fn, ast.Attribute) and fn.attr in _INSERT_METHOD_NAMES:
        return True

    # session.execute(insert(Model)...) — look for an `insert(...)` call
    # in the first positional argument (asyncpg-style SQLAlchemy 2.x).
    if (
        isinstance(fn, ast.Attribute) and fn.attr == "execute"
        and node.args
    ):
        first = node.args[0]
        if isinstance(first, ast.Call):
            ifn = first.func
            if isinstance(ifn, ast.Name) and ifn.id == "insert":
                return True
            if isinstance(ifn, ast.Attribute) and ifn.attr == "insert":
                return True

    return False


def _is_broad_except(handler: ast.ExceptHandler) -> bool:
    """True for `except:` / `except Exception:` / `except BaseException:`.

    Narrow handlers (e.g. `except SQLAlchemyError as e: raise`) are
    NOT swallowers — they're intentional, surfaced failures."""
    t = handler.type
    if t is None:
        return True
    if isinstance(t, ast.Name) and t.id in ("Exception", "BaseException"):
        return True
    if isinstance(t, ast.Tuple) and any(
        isinstance(e, ast.Name) and e.id in ("Exception", "BaseException")
        for e in t.elts
    ):
        return True
    return False


def _handler_swallows(handler: ast.ExceptHandler) -> bool:
    """A handler swallows if its body does NOT re-raise."""
    for sub in ast.walk(handler):
        if isinstance(sub, ast.Raise):
            return False
    return True


def _try_contains_insert(node: ast.Try) -> ast.AST | None:
    """Return the first INSERT-ish call found in the try body, or None."""
    for child in node.body:
        for sub in ast.walk(child):
            if _is_insert_call(sub):
                return sub
    return None


# ── Findings collector ─────────────────────────────────────────────
@dataclass(frozen=True)
class Finding:
    file:    str
    line:    int
    snippet: str

    def key(self) -> tuple[str, int]:
        return (self.file, self.line)


def _scan_file(path: pathlib.Path, root: pathlib.Path) -> list[Finding]:
    text = path.read_text()
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return []

    findings: list[Finding] = []
    rel = str(path.relative_to(root))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        # Skip if no INSERT inside the try body.
        insert_node = _try_contains_insert(node)
        if insert_node is None:
            continue
        # Find any broad-except + swallowing handler.
        for h in node.handlers:
            if _is_broad_except(h) and _handler_swallows(h):
                snippet = ast.unparse(h)[:140].replace("\n", " ")
                findings.append(Finding(
                    file=rel, line=h.lineno, snippet=snippet,
                ))
                break
    return findings


# ── Allow-list ─────────────────────────────────────────────────────
# Categories
IDEMPOTENCY_RACE           = "idempotency_race"
COMPENSATING_ACTION_EXISTS = "compensating_action_exists"
UNRESOLVED_DEBT            = "unresolved_debt"
_VALID_CATEGORIES = frozenset({
    IDEMPOTENCY_RACE, COMPENSATING_ACTION_EXISTS, UNRESOLVED_DEBT,
})

# Helpers to keep the table compact + the shape uniform.
def _race(reason: str) -> dict:
    return {"reason": reason, "category": IDEMPOTENCY_RACE}

def _comp(reason: str, ref: str) -> dict:
    return {
        "reason": reason,
        "category": COMPENSATING_ACTION_EXISTS,
        "compensating_ref": ref,
    }

def _debt(reason: str) -> dict:
    return {"reason": reason, "category": UNRESOLVED_DEBT}


_ALLOWED_SWALLOWERS: dict[tuple[str, int], dict] = {
    # ── idempotency_race ───────────────────────────────────────────
    ("app/services/system_incident_engine.py", 109): _race(
        "Partial-unique index `ix_system_incidents_active_singleton` "
        "intentionally raises when a second process tries to open a "
        "duplicate active row. Rollback + log + return None is the "
        "desired idempotent no-op (see inline comment)."
    ),

    # ── compensating_action_exists ─────────────────────────────────
    ("app/services/safety_incident_engine.py", 300): _comp(
        "Top-level safety net for `open_incident_for_alert`. "
        "Contract: alert pipeline must still deliver. GuardianAlert "
        "row IS the audit-of-record; SafetyIncident is supplementary "
        "lifecycle metadata.",
        "app/services/alert_trigger.py:trigger_alert",
    ),
    ("app/services/safety_incident_engine.py", 292): _comp(
        "Forensic SafetyIncidentEvent write — parent SafetyIncident "
        "(line 141, BEFORE this try) is already persisted and IS the "
        "audit-of-record. Event row is timeline supplementary.",
        "app/services/safety_incident_engine.py:open_incident_for_alert",
    ),
    # ── NISCH-010 risk-prediction persistence swallowers ───────────
    ("app/services/risk_prediction/predictor.py", 266): _comp(
        "Prediction ledger insert is supplementary — the alert "
        "pipeline already received the in-memory prediction dict and "
        "applies the confidence modifier regardless. Rollback + log "
        "preserves the alert hot-path; the prediction shows up in "
        "logs even when ledger persistence fails.",
        "app/services/risk_prediction/predictor.py:predict",
    ),
    ("app/services/risk_prediction/reconciler.py", 216): _comp(
        "Reconciler commit safety net. Per-row updates already "
        "succeeded inside their own try blocks; this commit groups "
        "them. A commit failure leaves the rows unreconciled (NULL "
        "delta) — the next 15-min cycle picks them up via "
        "`idx_rp_pending_outcome`. No data loss, just latency.",
        "app/services/risk_prediction/reconciler_scheduler.py:_run_once",
    ),
    # ── NISCH-011 behavioural-anomaly persistence swallowers ───────
    ("app/services/behavioral/detector.py", 209): _comp(
        "Behavioural anomaly INSERT swallow — compensating action is "
        "the `dlq:ml_predictions` append-only ring buffer (10k cap, "
        "see ROADMAP). On Postgres failure the payload lands in the "
        "DLQ so a post-mortem can reconstruct what the detector saw. "
        "Dispatch path NEVER blocks on behavioural anomaly persistence.",
        "app/services/behavioral/dlq.py:append_anomaly_ledger",
    ),
    ("app/services/behavioral/baseline.py", 239): _comp(
        "Behavioural baseline upsert swallow. The detector handles "
        "cold-start (baseline missing OR `sample_count < 5`) by "
        "returning a `cold_start` result with no anomaly fired, so a "
        "baseline-persist failure degrades gracefully to "
        "no-anomaly-recorded — same safety contract as the alert "
        "pipeline non-blocking guarantee.",
        "app/services/behavioral/detector.py:assess_and_record",
    ),
    # ── NISCH-012 motion-telemetry batch-commit swallower ─────────
    ("app/api/motion_features.py", 166): _comp(
        "Motion-telemetry batch-commit swallow. Per-window INSERTs "
        "use `ON CONFLICT (idempotency_key) DO NOTHING` so each row "
        "is independently idempotent; on commit failure the mobile "
        "uploader retries the same batch next cycle (same idempotency "
        "keys collapse to duplicate). Additive-only contract — "
        "telemetry NEVER blocks the dispatch pipeline.",
        "app/api/motion_features.py:ingest_motion_features",
    ),
    ("app/services/alert_trigger.py", 311): _comp(
        "Inner try around `incident.extra['alert_id']` backfill. The "
        "GuardianAlert and SafetyIncident rows are both already "
        "persisted; ACK lookup degrades to the primary alert_id "
        "query path.",
        "app/services/safety_incident_engine.py:find_by_alert_id",
    ),
    ("app/services/alert_trigger.py", 313): _comp(
        "Unified-front-door GuardianAlert persist swallow. The "
        "contract (docstring) explicitly chooses 'better one "
        "redundant delivery than a missed alert'. SSE has already "
        "fanned out by the time we reach this try.",
        "app/services/event_broadcaster.py:broadcast_to_user",
    ),
    ("app/services/alert_trigger.py", 368): _comp(
        "Co-location proximity suppression (NISCH-002B) is an "
        "optimisation: when uncertain, fail-safe to 'notify "
        "everyone'. Line 371 explicitly clears suppressed_gids on "
        "failure.",
        "app/services/alert_trigger.py:trigger_alert",
    ),
    ("app/services/stream_initiator.py", 153): _comp(
        "WebRTC stream-event log write is supplementary; the "
        "stream_sessions row IS the canonical record.",
        "app/models/stream_session.py:StreamSession",
    ),
    ("app/services/stream_initiator.py", 249): _comp(
        "offer_stream_for_incident is OPTIONAL (mocked when "
        "STREAM_RECORDING_BUCKET env var is absent). Returns None to "
        "signal 'streaming unavailable' without breaking the pipeline.",
        "app/services/alert_trigger.py:trigger_alert",
    ),
    ("app/services/alert_ack_engine.py", 331): _comp(
        "SafetyIncident → guardian-ACK linkage is supplementary; "
        "GuardianAlert.ack_status IS the audit-of-record. Lookup "
        "degrades via the alert_id query path.",
        "app/services/safety_incident_engine.py:find_by_alert_id",
    ),
    ("app/services/incident_state_machine.py", 165): _comp(
        "SafetyIncidentEvent write — parent SafetyIncident transition "
        "is already committed. Event row is timeline-only.",
        "app/services/incident_state_machine.py:transition",
    ),
    ("app/services/geofence_context.py", 380): _comp(
        "Zone-event SSE broadcast is real-time UX, not an audit row. "
        "Canonical state lives in the SafeZone rows + the in-process "
        "zone-state machine, not in this broadcast.",
        "app/models/safe_zone.py:SafeZone",
    ),
    ("app/services/shadow_tracking.py", 161): _comp(
        "Shadow-tracking ping is best-effort GEO telemetry; ping "
        "retries on the next interval.",
        "app/services/shadow_tracking.py:shadow_ping",
    ),
    ("app/api/streaming.py", 579): _comp(
        "Stream-end transition; stream_sessions row IS the canonical "
        "record. WS transition log is supplementary.",
        "app/models/stream_session.py:StreamSession",
    ),
    ("app/api/streaming.py", 597): _comp(
        "Stream-live transition; stream_sessions row IS the canonical "
        "record. WS transition log is supplementary.",
        "app/models/stream_session.py:StreamSession",
    ),
    ("app/api/streaming.py", 603): _comp(
        "WS-loop top-level crash handler — connection drops and the "
        "client reconnects; canonical state is in the DB.",
        "app/models/stream_session.py:StreamSession",
    ),
    ("app/services/notification_worker.py", 140): _comp(
        "Notification worker loop — rolls back, logs, continues with "
        "the next queued item. Each item is independently retried.",
        "app/services/notification_worker.py:run_worker_loop",
    ),
    ("app/services/whisper_verification_service.py", 344): _comp(
        "Whisper verification status update — marks the event as "
        "'failed' so the retry path picks it up.",
        "app/services/whisper_verification_service.py:retry_failed_verifications",
    ),
    ("app/services/journey_watchdog.py", 70): _comp(
        "Watchdog tick top-level safety net — each tick is "
        "independent; failed tick retries on the next interval.",
        "app/services/journey_watchdog.py:run_watchdog_loop",
    ),
    ("app/services/predictive_engine.py", 43): _comp(
        "Predictive engine cycle — background analytic job; rollback "
        "+ log + retry next tick.",
        "app/services/predictive_engine.py:run_predictive_loop",
    ),
    ("app/services/behavior_ai.py", 38): _comp(
        "Behavior AI cycle — background analytic job; rollback + log "
        "+ retry next tick.",
        "app/services/behavior_ai.py:run_behavior_cycle",
    ),
    ("app/services/digital_twin_builder.py", 36): _comp(
        "Digital twin builder cycle — background analytic job; "
        "rollback + log + retry.",
        "app/services/digital_twin_builder.py:run_twin_builder",
    ),
    ("app/services/safety_incident_scheduler.py", 71): _comp(
        "Stream-stale sweep tick — best-effort cleanup; rollback + "
        "retry on next interval.",
        "app/services/safety_incident_scheduler.py:start_scheduler",
    ),
    ("app/services/escalation_scheduler.py", 493): _comp(
        "Escalation scheduler — top-level loop safety net; rollback + "
        "log + continue with next job. Jobs are retried.",
        "app/services/escalation_scheduler.py:run_scheduler_loop",
    ),
    ("app/services/escalation_scheduler.py", 528): _comp(
        "Session-lifecycle job — supplementary housekeeping; core "
        "escalation flow is unaffected by individual job failures.",
        "app/services/escalation_scheduler.py:run_scheduler_loop",
    ),
    ("app/services/user_seed.py", 115): _comp(
        "User seed script — per-user create failures are collected "
        "into an `errors` list and logged at error level. Seed is "
        "idempotent + bootstrap-only.",
        "app/services/user_seed.py:seed_users",
    ),
    ("app/services/push_service.py", 84): _comp(
        "FCM token purge — token cleanup is best-effort; the next "
        "send attempt re-validates token health.",
        "app/services/push_service.py:send_push_to_user",
    ),
    ("app/services/push_service.py", 104): _comp(
        "FCM health-success update — token reachability metric; "
        "failure to bump the counter does not affect delivery.",
        "app/services/push_service.py:send_push_to_user",
    ),
    ("app/services/push_service.py", 126): _comp(
        "FCM health-failure update — token reachability metric; "
        "failure to bump the counter does not affect delivery.",
        "app/services/push_service.py:send_push_to_user",
    ),
    ("app/services/auto_escalation_engine.py", 268): _comp(
        "Sequential-contact collection from GuardianRelationship; "
        "fail-soft fanout — caller still has Relationship + legacy "
        "Guardian sources.",
        "app/services/auto_escalation_engine.py:_collect_sequential_contacts",
    ),
    ("app/services/auto_escalation_engine.py", 294): _comp(
        "Sequential-contact collection from Relationship; fail-soft "
        "fanout to next source.",
        "app/services/auto_escalation_engine.py:_collect_sequential_contacts",
    ),
    ("app/services/auto_escalation_engine.py", 321): _comp(
        "Sequential-contact collection from legacy Guardian; "
        "fail-soft — caller has contacts from earlier sources.",
        "app/services/auto_escalation_engine.py:_collect_sequential_contacts",
    ),
    ("app/services/auto_escalation_engine.py", 342): _comp(
        "Sequential-contact collection from EmergencyContact; "
        "fail-soft fanout to next source.",
        "app/services/auto_escalation_engine.py:_collect_sequential_contacts",
    ),
    ("app/services/auto_escalation_engine.py", 443): _comp(
        "Top-level safety net for `_trigger_guardian_failsafe`. "
        "Rollback + log + return; SSE + push + SMS already fired.",
        "app/services/event_broadcaster.py:broadcast_to_operators",
    ),
    ("app/services/auto_escalation_engine.py", 609): _comp(
        "Top-level safety net for `_trigger_escalation`. Rollback + "
        "log + return; SSE + push + SMS already fired.",
        "app/services/event_broadcaster.py:broadcast_to_user",
    ),
    ("app/services/guardian_mode_engine.py", 676): _comp(
        "Guardian-resolution Path 1 (Relationship); on failure, "
        "Path 2 + Path 3 still run.",
        "app/services/guardian_mode_engine.py:resolve_guardians",
    ),
    ("app/services/guardian_mode_engine.py", 691): _comp(
        "Guardian-resolution Path 2 (Guardian-contact); on failure, "
        "Path 3 still runs.",
        "app/services/guardian_mode_engine.py:resolve_guardians",
    ),
    ("app/services/guardian_mode_engine.py", 705): _comp(
        "Guardian-resolution Path 3 (legacy contact email lookup); "
        "fail-soft — returns whatever guardians earlier paths found.",
        "app/services/guardian_mode_engine.py:resolve_guardians",
    ),

    # ── unresolved_debt — these become the reliability-hardening
    # ── backlog. Touching any of these files during shadow_rollout
    # ── extraction or any future refactor is the trigger to fix them.
    ("app/api/child.py", 211): _debt(
        "Legacy help-request path (V2 owns the new path behind the "
        "ALERT_TRIGGER_V2_HELP_REQUEST flag). Once V2 is at 100 % "
        "rollout, this entire legacy block is scheduled for deletion."
    ),
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


def test_no_unsanctioned_insert_swallowers(capsys):
    """An INSERT inside a broad-except that doesn't re-raise is the
    silent-missing-row failure mode (NISCH-AUDIT-001). Any new
    occurrence must be either (a) replaced with explicit error
    handling, or (b) added to `_ALLOWED_SWALLOWERS` with a written
    reason + category. There is no third option."""
    findings = _collect_findings()
    unsanctioned = [
        f for f in findings if f.key() not in _ALLOWED_SWALLOWERS
    ]
    assert not unsanctioned, (
        "Unsanctioned INSERT-swallowers found — broadcast may fire "
        "while the audit row silently rolls back.\n\n"
        "Each entry below either:\n"
        "  (a) replace the broad-except with narrow error handling "
        "that re-raises after logging, OR\n"
        "  (b) add (file, line) → entry to _ALLOWED_SWALLOWERS in "
        "tests/test_swallow_audit.py with reason + category.\n\n"
        + "\n".join(
            f"  {f.file}:{f.line}  {f.snippet}" for f in unsanctioned
        )
    )

    # Debt-map metric — surfaced in the pytest live output so the
    # reliability-hardening backlog is visible without a separate dashboard.
    counts: dict[str, int] = {}
    for entry in _ALLOWED_SWALLOWERS.values():
        c = entry.get("category", "unknown")
        counts[c] = counts.get(c, 0) + 1
    with capsys.disabled():
        print(
            "\n[swallow-audit-debt-map]"
            f" idempotency_race={counts.get(IDEMPOTENCY_RACE, 0)}"
            f" compensating_action_exists={counts.get(COMPENSATING_ACTION_EXISTS, 0)}"
            f" unresolved_debt={counts.get(UNRESOLVED_DEBT, 0)}"
        )

    # Refresh the deterministic /app/memory/RELIABILITY_DEBT.md so the
    # debt map is a checked-in artifact whose PR diff shows the delta.
    _write_reliability_debt_md(counts)


# ── RELIABILITY_DEBT.md ratchet ────────────────────────────────────
_DEBT_MD = pathlib.Path("/app/memory/RELIABILITY_DEBT.md")
_RATCHET_TAG = "# RATCHET: unresolved_debt must not exceed "


def _read_previous_counts() -> dict[str, int]:
    """Parse the existing RELIABILITY_DEBT.md table to recover the
    previous per-category counts. Returns empty when the file is
    missing or unparseable (first run / corrupted)."""
    if not _DEBT_MD.exists():
        return {}
    prev: dict[str, int] = {}
    for line in _DEBT_MD.read_text().splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        cat, count_s = cells[0], cells[1]
        if cat in _VALID_CATEGORIES:
            try:
                prev[cat] = int(count_s)
            except ValueError:
                pass
    return prev


def _read_ratchet_limit() -> int | None:
    """Parse the inline RATCHET comment from the file."""
    if not _DEBT_MD.exists():
        return None
    for line in _DEBT_MD.read_text().splitlines():
        if _RATCHET_TAG in line:
            tail = line.split(_RATCHET_TAG, 1)[1].strip()
            # Strip trailing punctuation / words.
            num = "".join(ch for ch in tail if ch.isdigit())
            if num:
                return int(num)
    return None


def _delta(prev: int | None, curr: int) -> str:
    if prev is None:
        return "—"
    d = curr - prev
    if d == 0:
        return "0"
    return f"{d:+d}"


def _write_reliability_debt_md(counts: dict[str, int]) -> None:
    """Write the deterministic debt map. Format is locked so PR diffs
    show only real movement — no timestamps, sorted entries, fixed
    column widths."""
    if not _DEBT_MD.parent.exists():
        return
    prev = _read_previous_counts()
    ratchet = _read_ratchet_limit()
    if ratchet is None:
        # First-run bootstrap: lock the limit at the current
        # `unresolved_debt` count so subsequent runs ratchet down.
        ratchet = counts.get(UNRESOLVED_DEBT, 0)

    cats_sorted = sorted(_VALID_CATEGORIES)
    debt_entries = sorted(
        k for k, v in _ALLOWED_SWALLOWERS.items()
        if v.get("category") == UNRESOLVED_DEBT
    )

    rows = []
    for cat in cats_sorted:
        n = counts.get(cat, 0)
        rows.append((cat, n, _delta(prev.get(cat), n)))

    md = [
        "# RELIABILITY DEBT MAP",
        f"# RATCHET: unresolved_debt must not exceed {ratchet}",
        "# (generated by tests/test_swallow_audit.py — do not edit by hand)",
        "#",
        "# This file is deterministic (sorted by key, no timestamps) so PR",
        "# diffs only show real movement: a `-` line means the count went",
        "# down (celebrate); a `+` line means it went up (block the merge).",
        "#",
        "# Only `unresolved_debt` is ratcheted. `idempotency_race` and",
        "# `compensating_action_exists` are reported but not gated — moving",
        "# work from \"debt\" → \"compensated\" is progress and should not be",
        "# punished by the ratchet.",
        "",
        "## Counts",
        "",
        "| Category                    | Count | Δ |",
        "|-----------------------------|-------|---|",
    ]
    for cat, n, d in rows:
        md.append(f"| {cat:<27} | {n:>5} | {d} |")
    md.append("")
    md.append("## Unresolved debt entries")
    md.append("")
    for file, line in debt_entries:
        md.append(f"- {file}:{line}")
    md.append("")

    _DEBT_MD.write_text("\n".join(md))


def test_ratchet_enforced_against_unresolved_debt():
    """The ratchet limit lives inside RELIABILITY_DEBT.md as an
    inline comment. The current `unresolved_debt` count is taken
    from the live audit. If current > limit, fail CI — that means
    a PR introduced new unresolved debt and the limit should be
    *lowered* over time, never raised silently.

    Only `unresolved_debt` is ratcheted. Moving an entry from
    `unresolved_debt` → `compensating_action_exists` is allowed
    (progress) and ratchets the limit DOWN; the test does NOT block
    that direction."""
    counts: dict[str, int] = {}
    for entry in _ALLOWED_SWALLOWERS.values():
        c = entry.get("category", "unknown")
        counts[c] = counts.get(c, 0) + 1
    current = counts.get(UNRESOLVED_DEBT, 0)
    limit = _read_ratchet_limit()
    assert limit is not None, (
        "RELIABILITY_DEBT.md missing inline RATCHET line. The file "
        "should carry `# RATCHET: unresolved_debt must not exceed N`."
    )
    assert current <= limit, (
        f"Reliability ratchet breached: unresolved_debt={current} "
        f"exceeds RATCHET limit of {limit}.\n\n"
        "Either (a) bring a debt entry to "
        "`compensating_action_exists` (with a real "
        "`compensating_ref`) or (b) fix the underlying swallow.\n"
        "Do NOT raise the limit silently — that defeats the ratchet."
    )


def test_allow_list_entries_must_have_reasons():
    """Every allow-list entry MUST carry a non-trivial reason
    describing the operational semantics that make this swallow
    safe."""
    bad_reasons = ("", "todo", "wip", "legacy", "fixme", "later")
    offenders = []
    for (file, line), entry in _ALLOWED_SWALLOWERS.items():
        reason = (entry.get("reason") or "").strip().lower()
        if reason in bad_reasons or len(reason) < 20:
            offenders.append((file, line, entry.get("reason")))
    assert not offenders, (
        "Allow-list entries with vague / missing reasons. Reasons "
        "must describe the operational semantics that make the "
        "swallow safe.\n"
        f"Offenders: {offenders}"
    )


def test_allow_list_entries_have_valid_categories():
    """Every allow-list entry MUST have a category from the locked
    set. Tagging existing entries by category produces a debt map
    that's visible BEFORE any refactor touches these sites."""
    offenders = []
    for (file, line), entry in _ALLOWED_SWALLOWERS.items():
        c = entry.get("category")
        if c not in _VALID_CATEGORIES:
            offenders.append((file, line, c))
    assert not offenders, (
        f"Allow-list entries with invalid / missing category. "
        f"Valid: {sorted(_VALID_CATEGORIES)}.\n"
        f"Offenders: {offenders}"
    )


def test_compensating_action_entries_have_real_reference():
    """The `requires_compensating_action` flag (here: category =
    compensating_action_exists) is ONLY valid when a real
    compensating mechanism is referenced in code — not as a
    declaration of intent. The `compensating_ref` must be of the
    shape `path/to/file.py:symbol_or_line` and the file must exist.

    This prevents the category from becoming a semantic escape hatch
    where engineers tag entries as compensated without proof."""
    root = pathlib.Path(__file__).resolve().parents[1]
    offenders = []
    for (file, line), entry in _ALLOWED_SWALLOWERS.items():
        if entry.get("category") != COMPENSATING_ACTION_EXISTS:
            continue
        ref = entry.get("compensating_ref", "")
        if not ref or ":" not in ref:
            offenders.append((file, line, "missing compensating_ref"))
            continue
        ref_path = ref.split(":", 1)[0]
        if not (root / ref_path).exists():
            offenders.append((file, line, f"compensating_ref file not found: {ref_path}"))
    assert not offenders, (
        "compensating_action_exists entries without a real reference. "
        "Each must point to `path/to/file.py:symbol_or_line` where the "
        "actual compensating mechanism lives.\n"
        f"Offenders: {offenders}"
    )


def test_allow_list_entries_match_real_findings():
    """Stale allow-list entries (no longer matching a real swallower)
    must be removed. Otherwise the allow-list grows monotonically
    and silently weakens the audit."""
    findings = _collect_findings()
    keys = {f.key() for f in findings}
    stale = [k for k in _ALLOWED_SWALLOWERS if k not in keys]
    assert not stale, (
        "Stale allow-list entries — remove them from "
        "_ALLOWED_SWALLOWERS as the underlying code has changed.\n"
        f"Stale: {stale}"
    )


@pytest.mark.parametrize("required_module", [
    "app/services/alert_trigger.py",
    "app/services/auto_escalation_engine.py",
    "app/services/voice_distress_service.py",
])
def test_audited_modules_actually_get_scanned(required_module: str):
    """Sanity: the audit must actually scan the high-risk modules."""
    root = pathlib.Path(__file__).resolve().parents[1]
    path = root / required_module
    assert path.exists(), f"audit target missing: {path}"
    in_scope = any(
        path.is_relative_to(root / sub) for sub in _AUDIT_ROOTS
    )
    assert in_scope, (
        f"{required_module} is not inside any _AUDIT_ROOTS — audit "
        "would silently skip it."
    )
