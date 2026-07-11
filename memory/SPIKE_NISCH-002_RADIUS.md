# NISCH-002 Audit Spike — Radius Intelligence

**Date:** 2026-05-04
**Scope:** Map every haversine/radius/proximity callsite. Classify wired-vs-orphan. Recommend smallest patch.
**Result:** Hypothesis (`80% built, 20% wired`) was **wrong**. The board's `❌` is actually correct, but the fix is **not** wiring — it's a missing schema + product decision.

---

## 🎯 Headline finding

> **There is no proximity filter on alert fan-out today.** Every alert (risk update, voice distress, emergency, geofence) is broadcast to **every linked guardian, unconditionally**.
>
> The 371 haversine/radius hits are real, but they all live in **risk computation** and **per-zone geofence checks** — none of them filter the *guardian fan-out path*.

This is actually a slightly different problem from what the board implies, which makes the spike valuable: we'd have wasted 3 days "wiring radius filters" that have nothing to wire.

---

## 📊 The 371 callsites — classified into 4 buckets

| Class | Purpose | Files | Status |
|---|---|---|---|
| **A. Per-zone geofence** | "Is the child inside their safe zone?" `haversine(child, zone) vs zone.radius_m`. | `services/geofence_alerts.py`, `api/geofence.py`, `api/zones.py`, `api/pickup.py` | ✅ Wired correctly. SAFE/WARNING/BREACH state machine triggers alerts. |
| **B. Risk computation** | Heatmap cells, hotspot trends, location safety score. `haversine(point, incident)` for nearby-density. | `services/dynamic_risk_engine.py`, `location_safety_score_engine.py`, `hotspot_trend_engine.py` | ✅ Wired correctly. Powers `risk_emitter` indirectly. |
| **C. Journey distance metrics** | `total_distance_m` accumulators on a session. | `safety_events.py`, `replay.py`, `guardian_live.py`, `location_sharing.py` | ✅ Logging-only. Not a filter. |
| **D. Guardian proximity fan-out filter** | "Don't notify guardians who are 800 km away from where the alert fired." | **NONE** | ❌ **Does not exist.** |

---

## 🔍 What the alert-fan-out path actually does today

Every fan-out site walks the same path:

```python
# Pattern repeated in:
#   services/risk_emitter.py            (risk_update SSE)
#   services/voice_distress_service.py  (voice distress)
#   services/emergency_engine.py        (SOS)
#   services/guardian_mode_engine.py    (location_update)
#   services/geofence_alerts.py         (boundary breach)

guardian_ids = await _resolve_guardian_ids(session, child_id)  # SQL → list of UUIDs
for gid in guardian_ids:
    await broadcaster.broadcast_to_user(gid, event_type, payload)   # ← unconditional
```

There is **no** `if distance(guardian.location, event.location) <= radius_m:` check anywhere.
There is **no** `guardian.last_known_lat / .last_known_lng` column to compute that distance from.

The schema stores `Guardian.current_location` (line 32 of `models/guardian.py`) — but that's the **child's** live location, not the guardian's. Confirmed.

---

## ❓ Three competing interpretations of "NISCH-002 Radius Filter"

The board's checkbox is correctly `❌`, but it could mean one of three different products. We must pick before building.

### Interpretation A — "Notify only nearby trusted contacts during public emergencies"
**Use case:** elderly user falls in a public area; the system broadcasts to trusted neighbors within 500 m who opted in.

**What's missing:** trusted-contact relationship type, contact-location storage, opt-in flow, proximity filter, privacy gates.

**Effort:** ~2 sprints (schema + UI + privacy review).

**Verdict:** valuable but a *new feature*, not an activation task. Doesn't belong in Sprint 1.

### Interpretation B — "Suppress alerts when guardian is co-located with child"
**Use case:** mom is walking *with* the child. The child's idle/off-route alerts shouldn't ping mom's phone — she's already there.

**What's missing:** guardian's own location signal (mobile already has GPS — just send it up), a co-location detector, suppression rule.

**Effort:** ~1 week. High UX impact, low risk.

**Verdict:** strong candidate for "activation" framing — turns *off* a noise source rather than building anything new.

### Interpretation C — "Filter risk computation inputs by radius"
**Use case:** when computing a child's risk, only count incidents within `radius_km` of the child's current location.

**Already done.** This is exactly what `dynamic_risk_engine` and `location_safety_score_engine` do (Class B above). The `radius_km` query param on `/api/ai/hotspot-trends` is also this.

**Verdict:** if the board author meant this, the box should be `✅`.

---

## 🛠 Recommended smallest patch (if we ship NISCH-002)

Pick **Interpretation B** — it's the activation move. Here's the smallest path:

### Phase 1 — Wire guardian location into the schema (½ day)
- Add `User.last_known_lat`, `User.last_known_lng`, `User.last_known_at` (3 nullable columns).
- Mobile already calls `POST /api/guardian/heartbeat` periodically — extend payload with `lat/lng/ts`.

### Phase 2 — Add a single proximity helper (½ day)
```python
# app/services/alert_proximity.py
def is_co_located(guardian_lat, guardian_lng, child_lat, child_lng, threshold_m=150) -> bool:
    if None in (guardian_lat, guardian_lng): return False
    return haversine_m(guardian_lat, guardian_lng, child_lat, child_lng) <= threshold_m
```

### Phase 3 — Filter fan-out at exactly TWO sites (1 day)
- `risk_emitter.maybe_emit_risk_update`: drop guardians where `is_co_located()`.
- `geofence_alerts.evaluate_breach`: same.

**Skip** SOS / voice distress fan-out — those are P0 events; co-location is irrelevant ("I'm WITH my child and someone's attacking us — please ping me anyway").

### Phase 4 — Lock with a regression test (½ day)
- Test asserts: co-located guardian gets risk_update suppressed; SOS still goes through.

**Total effort: 2.5 dev-days for a product-meaningful win.**

---

## 🚫 What we should NOT do

- **Don't add a generic `radius_m` filter on every fan-out path.** P0 events (SOS, voice distress) must always reach every guardian regardless of distance. A blanket filter would be a safety regression.
- **Don't build trusted-contact radius (Interpretation A) in this sprint.** It needs a privacy-impact assessment and product rollout strategy, not a wiring patch.
- **Don't refactor the four duplicate `_haversine` implementations.** They're locally-scoped, internally consistent, and refactoring them adds zero user value. Consolidate when you next touch one of those services.

---

## 📋 Decision needed from product

Which interpretation does NISCH-002 mean? Pick one:

- **A.** Trusted-contact radius broadcast → re-scope to a 2-sprint feature, not Sprint 1.
- **B.** Co-location suppression → 2.5 days, ship in Sprint 1.
- **C.** Risk-input radius filter → already done. Mark NISCH-002 ✅ and move on.

My recommendation: **B + C.** Mark C done in the board (it's already shipped). Estimate B at 2.5 days and slot it into Sprint 1 between NISCH-001 and NISCH-003.

---

## 🧠 Strategic takeaway

The spike paid for itself: had we built generic radius filtering blindly, we would have:
1. Spent 3 days writing code that already exists in 4 places (duplicate Class B work), and
2. Introduced a safety regression by silently dropping SOS notifications to "far-away" guardians.

This is exactly why the "audit before activate" pattern matters. Recommend repeating it for NISCH-001 and NISCH-005 before any code is cut on those tickets.
