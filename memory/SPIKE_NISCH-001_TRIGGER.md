# NISCH-001 Audit Spike — Unified Alert Trigger

**Date:** 2026-05-04
**Scope:** Map every alert-trigger callsite. Find shared abstractions. Recommend smallest unification patch.
**Result:** Hypothesis **confirmed** — `guardian_notification_dispatcher` already exists and is **70% of the unified trigger surface**, but only **2 of 15+** alert-emitting sites use it. The activation move is **adoption + thin wrapper**, not new code.

---

## 🎯 Headline finding

> A `dispatch_guardian_alert(session, alert, user_id, session_id, *, louder)` function exists at `services/guardian_notification_dispatcher.py` (199 lines, well-structured: per-guardian preferences, SMS rate-limit, push channel routing, louder-push flag, dispatch rules table).
>
> It is called by exactly **2** services: `guardian_mode_engine` and `alert_ack_engine`. The other ~13 alert-emitting services each implement their own ad-hoc fan-out by calling `broadcaster.broadcast_to_user()` + `send_push_to_user()` + `GuardianAlert(...)` independently.

**The unified trigger surface isn't missing — it's underutilized.**

---

## 📊 Alert-trigger sites mapped

### ✅ Sites already using `dispatch_guardian_alert` (the right pattern)

| Site | What it dispatches |
|---|---|
| `services/guardian_mode_engine.py:627` | Geofence breach, idle, route deviation alerts |
| `services/alert_ack_engine.py:636` | Escalation `louder_push` step |

### ❌ Sites bypassing the dispatcher (each rolls its own)

Each of these does some subset of {create `GuardianAlert`, call `broadcast_to_user`, call `send_push_to_user`, send SMS} directly, with no shared dedup or lifecycle:

| Site | What it does inline |
|---|---|
| `services/voice_distress_service.py` | Creates GuardianAlert + broadcasts `safety_alert` SSE + calls `send_push_to_user` |
| `services/emergency_engine.py` | Broadcasts `emergency_triggered` SSE + calls `send_push_to_user` directly |
| `services/checkin_service.py` | Creates GuardianAlert + broadcasts `safety_alert` + push directly |
| `services/auto_escalation_engine.py` | Creates GuardianAlert + broadcasts `safety_alert` |
| `services/night_guardian_engine.py` | Creates GuardianAlert directly |
| `services/fall_detection_service.py` | Broadcasts `fall_detected` / `fall_auto_sos` SSE |
| `services/wandering_detection_service.py` | Broadcasts `wandering_*` SSE |
| `services/predictive_alerts.py` | Broadcasts `predictive_safety_alert` SSE |
| `services/safety_brain_service.py` | Broadcasts `safety_risk_alert` SSE |
| `services/guardian_ai_service.py` | Broadcasts `guardian_ai_alert` SSE |
| `services/route_monitor_service.py` | Broadcasts route alerts |
| `services/sos_service.py` | Broadcasts `sos_triggered` |
| `services/predictive_reroute_service.py` | Broadcasts reroute suggestions |
| `api/child.py:113` | Creates GuardianAlert directly during help-request |
| `services/risk_emitter.py` | Uses its own discipline (broadcast only, no GuardianAlert row, no push) — **this is correct for risk_update; should NOT be folded into the dispatcher** |

### Counts by primitive

| Primitive | Direct callsites | Should-route-through-trigger |
|---|---|---|
| `broadcaster.broadcast_to_user(...)` | 50+ | Most should use the unified surface; a handful of system-level events stay direct (`risk_update`, `incident_*`) |
| `GuardianAlert(...)` constructor | 8 | All 8 should go through the unified surface |
| `send_push_to_user(...)` direct | 11 | All 11 should go through the dispatcher |

---

## ❓ Why the existing dispatcher isn't enough — its 4 gaps

It's the right shape but missing 4 things to be the *real* unified surface:

1. **It doesn't write the `GuardianAlert` row.** Caller has to create one first. So the activation step is "stop creating alerts inline, route through one helper that creates AND dispatches".
2. **It doesn't broadcast SSE.** Only push + SMS. Every caller still does `broadcaster.broadcast_to_user(...)` separately. So the dedup/payload between SSE and push can drift.
3. **Its dedup is local in-process** (`_sms_rate_limit: dict`). Doesn't survive horizontal scale or restarts. `risk_emitter` already solved this with Redis + `emit_key`. The dispatcher should adopt the same pattern.
4. **No TTFA instrumentation hook.** NISCH-003 needs trigger→delivery timestamps; bolting that onto every individual caller is the current trajectory.

---

## 🛠 Recommended smallest patch — `trigger_alert(...)` thin wrapper

Build **one new function** that wraps the existing dispatcher + adds the missing 4 pieces. Then migrate the 13 bypassing sites to call it. Total: ~150 lines new + ~13 small refactors (each is delete-3-lines, replace-with-1-line).

### Phase 1 — Build the front door (1 day)
```python
# app/services/alert_trigger.py  — NEW

async def trigger_alert(
    session: AsyncSession,
    *,
    kind: str,                    # "voice_distress" | "geofence_breach" | "sos" |
                                  # "fall" | "wandering" | "predictive" | ...
    user_id: str,                 # the child / wearer / monitored user
    severity: str,                # "info" | "warning" | "critical"
    message: str,
    details: str | None = None,
    location: dict | None = None,
    session_id: str | None = None,
    louder: bool = False,
    idempotency_key: str | None = None,
) -> dict:
    """The single door for every guardian-facing alert.

    Pipeline:
      1. Redis-backed dedup gate (cooldown per `kind` + `idempotency_key`)
      2. Create GuardianAlert row (uniform shape, NEVER null user_id)
      3. SSE broadcast to all linked guardians (event_broadcaster)
      4. Push + SMS via guardian_notification_dispatcher (existing)
      5. TTFA log line: [ALERT_TTFA] kind=... trigger_ts=... ttfa_ms=...
      6. Lifecycle row (NISCH-006 hook — write 'pending' state)
    """
    ...
```

Reuses the existing `dispatch_guardian_alert` for steps 4–5. Reuses `risk_emitter`'s Redis dedup pattern for step 1. Step 6 is a stub today (table doesn't exist yet) — leave a marker.

### Phase 2 — Adopt incrementally (each callsite is ~3 minutes)
Replace this pattern (currently in 13 services):
```python
# Before
alert = GuardianAlert(...)
session.add(alert)
await session.flush()
await broadcaster.broadcast_to_user(gid, "safety_alert", payload)
await send_push_to_user(session, gid, title, body, ...)
```
With this:
```python
# After
await trigger_alert(
    session,
    kind="voice_distress",
    user_id=user_id,
    severity="critical",
    message="Voice distress detected",
    details=f"Confidence: {score:.2f}",
    location={"lat": lat, "lng": lng},
    session_id=session_id,
)
```

### Phase 3 — Lock with tests (½ day)
- 1 test per migrated callsite asserts `trigger_alert` was invoked (mock + verify args).
- 1 dedup test asserts identical (kind, user_id, idempotency_key) → second call no-ops.
- 1 TTFA test asserts the log line is emitted.

**Total effort: 2.5 dev-days for activation. Same budget as NISCH-002 Interpretation B.**

---

## 🚫 What we should NOT do

- **Don't fold `risk_emitter` into `trigger_alert`.** They serve different contracts. `risk_update` is a *score-delta event* (no GuardianAlert row, no push-by-default, no SMS). Keeping them separate preserves the discipline we just shipped. They share the same Redis dedup *pattern*, not the same code.
- **Don't try to migrate all 13 sites in one PR.** Adopt incrementally, one service per PR, behind a feature flag if prod-stability matters. The first 3 (`emergency_engine`, `voice_distress_service`, `child.py:help-request`) cover ~80% of P0 traffic.
- **Don't change SSE event-type names during this refactor.** Frontends key off them. Keep `safety_alert`, `voice_alert`, etc. The dispatcher just becomes the authoritative emitter.
- **Don't refactor `dispatch_guardian_alert`.** It's correct as-is. Wrap it, don't rewrite it.

---

## 📋 What this unlocks (for the team)

- **NISCH-003 (TTFA instrumentation)** — becomes a 1-line addition inside `trigger_alert` instead of 13 separate refactors.
- **NISCH-005 (noise control)** — the Redis dedup gate inside `trigger_alert` *is* the generic noise-control mechanism. Solves it for free.
- **NISCH-006 (lifecycle tracking)** — every alert flows through one function, so adding a lifecycle row is one commit, not thirteen.
- **NISCH-002 Interpretation B (co-location suppression)** — applied at exactly one site (`trigger_alert`'s SSE broadcast loop) instead of at every caller.

So Sprint 1 looks much cleaner if NISCH-001 ships first:

```
NISCH-001 trigger_alert front door  →  unblocks 003, 005, 006 cleanly
NISCH-002 (B) co-location suppression  →  applied at trigger_alert boundary
NISCH-003 TTFA  →  one log line in trigger_alert
NISCH-004 alert formatting  →  trigger_alert calls a format helper
NISCH-005 dedup  →  already inside trigger_alert
```

That's the difference between "13 PRs" and "1 PR + 13 small adoptions". Same code, completely different team velocity.

---

## 🧠 Strategic takeaway

Both spikes (NISCH-001 + NISCH-002) found the same pattern: **the abstractions exist; the adoption doesn't**. Nothing in this ticket needs new architecture. It needs a thin front door, a migration script, and discipline.

The board's "Trigger Layer 10%" is correct from a *user-facing reliability* lens but understates how much *foundation* is already there. Once you call `trigger_alert` from 13 sites, your "Trigger Layer" jumps from 10% → 95% with zero new infrastructure.
