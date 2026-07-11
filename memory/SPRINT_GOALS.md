# Nischint — Sprint Goals (Master Strategic Map)

> **Master goal:** convert Nischint from a *silent intelligence system* into a *real-time, visible, responsive safety system*.
>
> **Sprint mantra:** "We are not building new features this week. We are turning ON what we already built."

This is the canonical sprint plan. Updated 2026-05-04 after the NISCH-001 + NISCH-002 audit spikes (see `/app/memory/SPIKE_*.md`).

Pair with `ROADMAP.md` (raw priority queue) and `CHANGELOG.md` (delivery log).

---

## 🧭 What changed in this revision

Two 30-minute spikes (`SPIKE_NISCH-001_TRIGGER.md`, `SPIKE_NISCH-002_RADIUS.md`) inverted the original sequencing:

| Discovery | Implication |
|---|---|
| `guardian_notification_dispatcher` already exists; only 2 of ~15 alert sites use it. | NISCH-001 isn't "build new"; it's "thin wrapper + adopt at 13 sites". |
| 371 haversine hits live in **risk computation**, not **fan-out**. The "radius filter" gap is actually a **co-location suppression** + missing guardian-location schema. | NISCH-002 splits into 3 interpretations; only Interpretation B is Sprint 1 work. |
| Risk emitter Redis dedup already solves the generic dedup problem. | NISCH-005 collapses to "expose `risk_emitter`'s pattern as a helper" — automatic if NISCH-001 ships first. |
| Operator-side incident feed exists; guardian-side doesn't. | NISCH-007 is a frontend-only effort once the lifecycle table from NISCH-006 lands. |

**Net effect:** Sprint 1 ordering must lead with NISCH-001. Without it, NISCH-003/004/005/006 each become 13-site refactors. With it, they become 1-line additions inside one function.

---

## 🎯 Goals at a glance

| # | Goal | Tickets | State (post-spike) |
|---|---|---|---|
| 1 | **Activate System** | 001, 002, 004 | 🟡 foundation strong; adoption gap |
| 2 | **Speed** | 003 | 🟡 pipeline built; instrumentation missing |
| 3 | **Trust** | 005 | 🟡 pattern shipped (risk_emitter); not generalized |
| 4 | **Visibility** | 006, 007 | 🟡 operator side ✅; guardian side ❌ |
| 5 | **Emergency** | 008 | 🔴 not started; depends on Twilio P0 unblock |
| 6 | **Learning** | 009 | 🔴 not started |
| 7 | **Moat** | 010, 011, 012 | 🔴 P2; foundation laid by `risk_emitter` |

---

## 📐 Sprint principle — "spike before activate"

Lock this as a team rule:

> Before any NISCH-* ticket starts coding, the owner runs a 30-min audit on every existing callsite that touches the relevant primitive. The deliverable is a 1-page spike doc in `/app/memory/SPIKE_<TICKET>_<TOPIC>.md` classifying what exists vs. what's missing.

The two spikes above already paid for themselves: NISCH-001 was hypothesized at "build a unified trigger surface" → discovered to be "adopt the existing one". NISCH-002 was hypothesized at "wire the radius" → discovered to need schema + product-decision first. Both would have wasted 3 days each without the audit.

---

## 🔴 GOAL 1 — Activate the System (visibility layer)

**Outcome:** "Something is happening near your child."

### NISCH-001 — Unified `trigger_alert` Front Door ⭐ FIRST TO SHIP
- **Spike:** `/app/memory/SPIKE_NISCH-001_TRIGGER.md`
- **Reality:** `guardian_notification_dispatcher.py` exists, called by 2 of 15+ sites. The other 13 each roll their own.
- **Plan (3 phases, 2.5 dev-days):**
  1. **Build** `services/alert_trigger.py::trigger_alert(...)` — wraps existing dispatcher, adds GuardianAlert creation + SSE broadcast + Redis dedup + TTFA hook.
  2. **Adopt** at the 3 highest-traffic P0 sites: `emergency_engine`, `voice_distress_service`, `child.py:help-request`. Behind a feature flag.
  3. **Test** — 1 test per migrated site + dedup test + TTFA log assertion.
- **Done when:** P0 events flow through one function. Other 10 sites migrate in subsequent sprints.
- **Owner:** TBD

### NISCH-002 — Radius / Proximity Intelligence ⚠️ RE-SCOPED
- **Spike:** `/app/memory/SPIKE_NISCH-002_RADIUS.md`
- **Three competing interpretations exist. Decision:**
  - **A (trusted-contact radius)**: re-classify as 2-sprint *new feature*. Out of Sprint 1.
  - **B (co-location suppression)**: ship in Sprint 1 *after* NISCH-001 (applies at exactly 1 boundary instead of 13).
  - **C (risk-input radius filter)**: ✅ **already shipped** in `dynamic_risk_engine` and `location_safety_score_engine`. Mark done.
- **Plan for B (2.5 dev-days, depends on NISCH-001):**
  1. Add `User.last_known_lat / lng / at` columns; mobile heartbeat already runs, extend payload.
  2. `services/alert_proximity.py::is_co_located(guardian, child, threshold_m=150)`.
  3. Apply filter inside `trigger_alert`'s SSE broadcast loop — never on SOS / voice-distress path.
- **Owner:** TBD

### NISCH-004 — Alert Formatting (centralize)
- **Reality:** every alert producer formats inline. Inconsistent titles, no i18n hook.
- **Plan (1 day, depends on NISCH-001):** `services/alert_formatter.py::format_alert(kind, ctx) -> {title, body, priority}`. Called inside `trigger_alert`. Existing inline formatters delete themselves.
- **Owner:** TBD

---

## ⚡ GOAL 2 — Reduce Response Time (speed layer)

**Outcome:** "Faster than human intuition." KRA target: SOS → guardian push < 5s p95.

### NISCH-003 — TTFA Instrumentation + Priority Routing
- **Reality:** push pipeline is ⚠ WEAK on the board because we *can't measure it*. Pipeline itself is built (`push_service.py` + `pushService.ts` + `critical_safety` channel + Twilio fallback).
- **Plan (1.5 dev-days, ride on NISCH-001):**
  1. `[ALERT_TTFA]` log line inside `trigger_alert` — 1 line, 13 sites covered for free.
  2. `/api/_dev/alert-ttfa/stats` admin endpoint surfacing p50/p95/p99 by `kind`.
  3. Priority routing: SOS-class events skip the regular dispatch queue (already partially there in `auto_escalation_engine`; just needs the TTFA stamp to confirm).
- **Owner:** TBD

---

## 🔇 GOAL 3 — Build Trust (noise + clarity)

**Outcome:** "Every alert matters."

### NISCH-005 — Generic Dedup Gate
- **Reality:** `risk_emitter.py` already implements the right pattern (Redis-backed `_LAST_RISK` + atomic INCR + emit_key). It's per-emitter, not generic.
- **Plan (½ day if NISCH-001 lands first):** lift the Redis dedup pattern into `services/event_dedup.py::dedup_gate(kind, idempotency_key, cooldown_s) -> (should_emit, reason)`. Inject inside `trigger_alert`. Done.
- **Owner:** TBD

---

## 👁️ GOAL 4 — Make System Visible (UX)

**Outcome:** "I can see what's happening around my child."

### NISCH-006 — Alert Lifecycle Tracking
- **Reality:** journey lifecycle tracked. Per-event lifecycle (`pending → delivered → ack'd → resolved → false_positive`) is not.
- **Plan (2 dev-days, depends on NISCH-001):**
  1. New `alert_lifecycle` table (alembic migration).
  2. `trigger_alert` writes 'pending' on creation; ACK endpoint writes 'ack'd'; auto-resolve worker writes 'resolved' / 'false_positive'.
  3. Lifecycle update event on SSE for live UI.
- **Owner:** TBD

### NISCH-007 — Guardian Incident Feed
- **Reality:** operator-side `CommandCenterPage.jsx` exists. Guardian-side (`/family`) does not.
- **Plan (3 days, depends on NISCH-006):** `/family/incidents` route, reuses lifecycle table, swipe-to-dismiss, paginated history.
- **Owner:** TBD

---

## 🆘 GOAL 5 — Real-time Emergency Control

**Outcome:** "Guardian doesn't guess — they see."

### NISCH-008 — WebRTC Live Streaming (during active SOS only)
- **Reality:** confirmed not built. Privacy-gated to active SOS only — never on idle.
- **Pre-req:** Twilio voice E2E (P0 currently blocked) ships first as fallback for bad mobile networks.
- **Plan:** child-side audio publish via `react-native-webrtc`, guardian-side play, signaling on existing SSE channel, STUN/TURN via Twilio Network Traversal Service or Cloudflare Calls.
- **Effort:** 2-week feature. Not Sprint 1.
- **Owner:** TBD

---

## 🤝 GOAL 6 — Learning System

**Outcome:** "System gets smarter every day."

### NISCH-009 — Guardian Feedback Loop
- **Reality:** not built.
- **Plan (3 dev-days, depends on NISCH-006):**
  - On every alert ACK screen: "Was this useful? [Yes / Not relevant / False alarm]".
  - Backend stores `(kind, ctx_hash, score_at_emit, verdict, ts)` in `alert_feedback`.
  - Weekly aggregation tunes `dedup_gate` cooldowns + `risk_emitter` score weights.
- **Owner:** TBD

---

## 🧬 GOAL 7 — Build Moat (P2)

### NISCH-010 — Predictive Risk Engine v1 (rule-based, shadow mode first)
- **Reality:** foundation already laid by `risk_emitter` (disciplined emitter, Redis state, idempotency). v1 plugs into it.
- **Plan:** rule-based predictor logs `[RISK_PREDICT_SHADOW]` for one full sprint without broadcasting. Flip env flag once shadow accuracy ≥ 60% on 1000 labeled events (KRA from `VENDOR_HANDOFF.md` §6.3). NISCH-009 feedback drives the labeling.

### NISCH-011 — Behavioral Intelligence
- Personal baselines (route patterns, timing, speed). Deviation detection.

### NISCH-012 — External Data Layer
- Crime statistics overlay, weather, public-event proximity.

---

## 📊 Re-sequenced execution plan

### 🟢 Sprint 1 — "Build the front door"

| Order | Ticket | Effort | Status |
|---|---|---|---|
| 1 | **NISCH-001** Unified `trigger_alert` | 2.5d | ✅ SHIPPED 2026-05-04 (Phase 1) + voice_distress migrated |
| 2 | **NISCH-002C** Mark already-shipped ✅ | 0d | ✅ Closed by spike |
| 3 | **NISCH-004** Centralize formatter | 1d | ✅ SHIPPED 2026-05-06 |
| 4 | **NISCH-003** TTFA instrumentation | 1.5d | ✅ SHIPPED 2026-05-06 |
| 5 | **NISCH-005** Generic dedup gate | 0.5d | ✅ SHIPPED 2026-05-06 |
| 6 | P0 migrations (`emergency_engine`, `help-request`) | 1d | ✅ SHIPPED 2026-05-06 (flag-gated) |
| 7 | **NISCH-002B** Co-location suppression | 2.5d | ✅ SHIPPED 2026-05-06 |

**Sprint 1 status:** 7/7 items shipped 🟢 ✅ Sprint 1 COMPLETE.

### 🟡 Sprint 2 — "Make it visible + learning" (NEXT)

| Order | Ticket | Effort | Notes |
|---|---|---|---|
| 1 | **NISCH-006** Lifecycle table | 2d | Schema + writes from `trigger_alert` |
| 2 | **NISCH-007** Guardian incident feed | 3d | Frontend-only, uses NISCH-006 |
| 3 | **NISCH-009** Feedback loop | 3d | ACK screen + storage |
| 4 | Migrate remaining 10 alert callsites to `trigger_alert` | 2d | Cleanup; behind feature flag |

### 🟡 Sprint 2 — "Make it visible + learning" — moved up to top

| Order | Ticket | Effort | Notes |
|---|---|---|---|
| 1 | **NISCH-006** Lifecycle table | 2d | Schema + writes from `trigger_alert` |
| 2 | **NISCH-007** Guardian incident feed | 3d | Frontend-only, uses NISCH-006 |
| 3 | **NISCH-009** Feedback loop | 3d | ACK screen + storage |
| 4 | Migrate remaining 10 alert callsites to `trigger_alert` | 2d | Cleanup; behind feature flag |

### 🔵 Sprint 3+ — Strategic

- Twilio P0 unblock → re-validate full escalation chain
- NISCH-008 WebRTC (2-week feature)
- NISCH-010 Predictive v1 (shadow mode first)

---

## 📋 One-line ticket summary (post-spike)

| Goal | Ticket | One-line |
|---|---|---|
| Activate | 001 | Adopt existing `dispatch_guardian_alert` via `trigger_alert` wrapper at 13 sites. |
| Activate | 002C | Mark "risk-input radius" done. ✅ |
| Activate | 002B | Add `User.last_known_*` + co-location suppression at SSE boundary. |
| Activate | 004 | Pull alert formatting into `format_alert` helper. |
| Speed | 003 | `[ALERT_TTFA]` log + admin stats endpoint. |
| Trust | 005 | Lift `risk_emitter`'s Redis dedup into a generic `dedup_gate`. |
| Visibility | 006 | New `alert_lifecycle` table + lifecycle states from `trigger_alert`. |
| Visibility | 007 | Guardian incident feed at `/family/incidents`. |
| Emergency | 008 | WebRTC audio publish during active SOS. |
| Learning | 009 | Per-alert feedback collection drives threshold tuning. |
| Moat | 010 | Rule-based predictive in shadow mode; flip on ≥60% accuracy. |

---

## 🔥 Team alignment line

> "We are not building new features this week. We are **turning ON** what we already built — through one front door."

The spikes proved this isn't motivational language — it's literal architectural truth. The dispatcher exists. The dedup pattern exists. The risk computation exists. The job is **wiring**, not invention.

Use this as the standup opener for every day of Sprint 1.

---

## 📎 Supporting documents

- `/app/memory/SPIKE_NISCH-001_TRIGGER.md` — full audit of 50+ broadcast sites and the 8 GuardianAlert callers
- `/app/memory/SPIKE_NISCH-002_RADIUS.md` — full audit of 371 haversine/radius hits in 4 buckets
- `/app/memory/SYSTEM_INVARIANTS.md` — non-negotiable architecture rules
- `/app/memory/CHANGELOG.md` — delivery log (most recent: `risk_emitter` shipped 2026-05-04)
- `/app/memory/VENDOR_HANDOFF.md` — outsourcing scope + KRAs (references this doc as "ROADMAP source of truth")
