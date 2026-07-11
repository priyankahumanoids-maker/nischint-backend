# Journey Intelligence — Integration Handoff (DEFERRED)

> **Status:** Deferred to a fresh session. Decision locked Apr 28, 2026.
> The integration must layer onto existing `guardian_sessions`, NOT
> replace it with a parallel `journeys` table. This document holds
> everything the next session needs to integrate in one clean pass.

---

## 🔒 AUTHORITATIVE EXECUTION PROMPT (final, locked by user)

**JOURNEY INTELLIGENCE — EXECUTION SESSION**

**MANDATORY PRECONDITION**: Read this file in full before writing or modifying any code. That document is the system design authority. The 7-step plan below is the execution contract.

### Load these files first (in order)
1. `journey_service.py` (user will upload)
2. `journey_router.py` (user will upload)
3. `guardian_mode_engine.py`
4. `alert_ack_engine.py`
5. `guardian_sessions` table schema (in `app/models/guardian.py`)

### SYSTEM INVARIANTS — NEVER VIOLATE
1. `guardian_sessions` is the ONLY lifecycle state owner
2. `journey_points` = append-only event log, never a state source
3. GPS path → ACTIVE only. Watchdog → PAUSED/OFFLINE only. Recovery is GPS path's responsibility exclusively.

### ⏱️ TIMESTAMP NORMALIZATION RULE (enforced throughout)
Three time axes exist in this system:
- `gps_recorded_at` — **device time** (untrusted; clocks drift, jump, lie)
- `previous_update_at` — **server session time** (the authority)
- watchdog tick time — **system inference time**

All timestamp comparisons MUST use `previous_update_at` (server-side session clock) as the primary reference — **never raw device time**. If any comparison uses device time as truth, stale-packet drops and recovery suppression will produce false results under clock skew.

### EXECUTION ORDER — DO NOT REORDER

**Step 1 — Schema patch**: Add exactly 5 columns to `guardian_sessions`: `is_offline`, `last_seen_online_at`, `total_points`, `offline_gaps`, `max_gap_seconds`.

**Step 2 — Event log table**: Create `journey_points` with FK → `guardian_sessions.id`, append-only, `UNIQUE(session_id, seq)`, seq monotonic per session. `total_points` on the session row is the next seq value.

**Step 3 — Stale packet guard (FIRST CHECK, NO EXCEPTIONS)**: The very first operation inside `update_location`, before zombie cap, before resurrection, before any side effects. Compare `gps_recorded_at` against `guardian_sessions.previous_update_at` using server clock as reference. If stale → silently drop. **No logging, no state mutation, no SSE events.** If this check is placed anywhere other than first, phantom recovery events will occur under poor network conditions.

> Implementation note: existing column is named `previous_update_at`, not `last_update_at`. Same column, just confirm naming in `guardian.py:34`.

**Step 4 — Gap detection**: Inside `update_location` after stale guard. 15s → `unstable`, 30s → `offline`. Update session fields only — no new state system.

**Step 5 — ACK engine integration**: Hook into `_capture_context` in `alert_ack_engine.py:83`. If `is_offline=true` OR gap ≥ 30s → enforce 10s fast-path ACK timeout. Must respect zombie-cap ordering, no bypass of escalation chain.

**Step 6 — Watchdog**: Downgrade only (ACTIVE → PAUSED/OFFLINE). Cannot upgrade state. Must never emit ACTIVE. Uses server-side session clock (`previous_update_at` vs `now()`) for all gap calculations — **not device time**.

**Step 7 — Mobile layer (LAST)**: Polyline rendering only. Solid blue = good, dashed amber = unstable, dashed gray = offline. Backend projection only, no state mutation from client.

### SUCCESS CRITERIA — ALL MUST PASS
- Exactly 1 active session per user
- Stale GPS packet arriving after OFFLINE → silently dropped, no state change, no events
- **Clock skew test**: device timestamp ahead of server time → treated as stale, dropped correctly
- 15s → unstable, 30s → offline, recovery closes cleanly
- SSE events carry `session_id` + `seq`, client detects missing sequences
- Offline gap triggers 10s ACK fast-path (not 15s)
- Zero regression: shadow tracking, zombie cap, push delivery all intact

### POST-INTEGRATION (only after all criteria pass)
1. Twilio call escalation (`ack_type IS NULL` gate, zombie-cap ordering respected)
2. Live Risk Panel (Command Center docked tile)
3. Android `critical_safety` notification channel patch

---

## Why we deferred

1. The artifact bundle delivered was incomplete — `journey_service.py` and `journey_router.py` were referenced by the watchdog but not present in the artifact bucket I could read.
2. The original spec creates a parallel session system that **silently bypasses** safety guarantees shipped in this session:
   - `update_location` shadow-tracking failsafe
   - 24-hour zombie-session cap
   - GPS resurrection on `expired/stale`
   - ACK engine `tracking_mode` context (drives risk-weighted ACK timeout)
3. Context budget at the time was tight — risk of half-shipping was real.

## Decision (locked)

Use **option (a) layered approach**:
- Extend `guardian_sessions` with offline tracking columns
- Create `journey_points` as a NEW table (no conflict — pure trail)
- Hook gap detector into existing `update_location` path
- Feed `is_offline` into ACK engine `tracking_mode` so offline gaps automatically halve critical-alert ACK timeouts

## What to upload to the next session
1. The 2 missing files: `journey_service.py` + `journey_router.py`
2. This document (`/app/memory/JOURNEY_INTELLIGENCE_INTEGRATION.md`)
3. Reference the existing files below — they're already in the codebase

---

## Reference 1 — existing `GuardianSession` model
**File**: `backend/app/models/guardian.py:24`

Already has: `id, user_id, status (active|stale|expired|ended|completed), destination, route_points, current_location, previous_location, previous_update_at, zone_id, risk_level, risk_score, zone_name, eta_minutes, speed_mps, total_distance_m, location_updates, escalation_level, is_night, route_deviated, route_deviation_m, is_idle, idle_since, idle_duration_s, alert_count, last_alert_at, safety_check_pending, safety_check_sent_at, started_at, ended_at`

**Columns to ADD via migration** (mirror the journey_intelligence.sql but on the existing table):
- `is_offline BOOLEAN NOT NULL DEFAULT FALSE`
- `last_seen_online_at TIMESTAMPTZ` (defaults to `started_at` for existing rows)
- `total_points INT NOT NULL DEFAULT 0`
- `offline_gaps INT NOT NULL DEFAULT 0`
- `max_gap_seconds INT NOT NULL DEFAULT 0`

**New table to CREATE** (no conflict, pure trail — append-only event log, NOT a state table):
```sql
CREATE TABLE journey_points (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES guardian_sessions(id) ON DELETE CASCADE,
    user_id UUID NOT NULL,
    seq INT NOT NULL,                     -- monotonic per-session sequence number
    lat DOUBLE PRECISION NOT NULL,
    lng DOUBLE PRECISION NOT NULL,
    accuracy DOUBLE PRECISION,
    speed_mps DOUBLE PRECISION,
    quality TEXT NOT NULL DEFAULT 'good', -- good | unstable | offline
    gap_before_s INT,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (session_id, seq)              -- locks monotonicity at the DB
);
CREATE INDEX idx_journey_points_session_id ON journey_points(session_id);
CREATE INDEX idx_journey_points_recorded_at ON journey_points(recorded_at DESC);
```

> Note: `session_id` references `guardian_sessions(id)` — NOT a new `journeys.id`. There is no `journeys` table.
> `seq` is mandatory — every SSE event MUST carry both `session_id` (= journey_id in the projection) and `seq` so client-side replay can detect dropped events. `total_points` on the session row IS the next seq.

---

## Reference 2 — `update_location` integration point
**File**: `backend/app/services/guardian_mode_engine.py:221`

Current path (preserve all of this — it's safety-critical):
1. Load session
2. **24h zombie cap** — auto-complete if started_at + 24h < now
3. Reject `ended/completed`; resurrect `expired/stale` to `active`
4. Compute speed/dist via `_haversine`
5. Zone check + alert generation
6. Idle detection
7. Update `current_location, previous_update_at, location_updates`
8. Commit

**Insert two new things into `update_location`**:

### A. Stale packet guard — MUST be the FIRST check, before EVERYTHING else
Before the zombie cap, before the resurrection check — the very first line of logic. Out-of-order GPS packets under poor mobile network conditions (and untrusted device clocks) will otherwise produce phantom recovery events.

**Timestamp normalization rule applies here**: use `previous_update_at` (server session time) as the reference, never raw device time. A packet with a device timestamp ahead of `previous_update_at` is treated as stale (clock skew defense), not as "from the future" — clocks lie.

```python
# Step 3 of the brief — stale guard. FIRST. NO EXCEPTIONS.
# If the incoming packet's gps_recorded_at is at or before what we've
# already accepted on the SERVER session clock, drop silently.
# No log, no state mutation, no SSE event.
gps_ts = timestamp                       # device time, untrusted
server_ref = gs.previous_update_at       # server session clock — the authority
if gps_ts is not None and server_ref is not None and gps_ts <= server_ref:
    return {"stale": True}               # API layer maps to 200 OK + no broadcast

# All subsequent gap math uses server clock too:
ts = datetime.now(timezone.utc) if gps_ts is None else gps_ts
# (gps_ts is only used for ordering vs prior packet; gap_s is server-clock based.)
```

### B. Gap detector — AFTER stale guard, AFTER resurrection, BEFORE speed/dist compute
```python
# After resurrection logic, before speed compute:
now = timestamp or datetime.now(timezone.utc)
prev_ts = gs.previous_update_at or gs.started_at
gap_s = (now - prev_ts).total_seconds() if prev_ts else 0

# Quality classification (locked thresholds):
if gap_s < 15:
    quality = "good"
elif gap_s < 30:
    quality = "unstable"
else:
    quality = "offline"
    gs.offline_gaps = (gs.offline_gaps or 0) + 1
    gs.max_gap_seconds = max(gs.max_gap_seconds or 0, int(gap_s))

# Coming back online from offline:
was_offline = gs.is_offline
gs.is_offline = (quality == "offline")
gs.last_seen_online_at = now if quality != "offline" else gs.last_seen_online_at
if was_offline and not gs.is_offline:
    # journey_resumed event — broadcast on session channel
    await _broadcast_journey_resumed(gs, gap_s, lat, lng)
elif not was_offline and gs.is_offline:
    # journey_paused event
    await _broadcast_journey_paused(gs, gap_s, auto=True)

# Persist the trail point:
await session.execute(
    text("""INSERT INTO journey_points (session_id, user_id, lat, lng,
                  accuracy, speed_mps, quality, gap_before_s, recorded_at)
            VALUES (:sid, :uid, :lat, :lng, :acc, :spd, :q, :gap, :ts)"""),
    {"sid": gs.id, "uid": gs.user_id, "lat": lat, "lng": lng,
     "acc": accuracy, "spd": speed, "q": quality,
     "gap": int(gap_s) if prev_ts else None, "ts": now},
)
gs.total_points = (gs.total_points or 0) + 1
```

The accuracy parameter needs to be added to `update_location`'s signature. The mobile already sends it.

---

## Reference 3 — ACK engine `_capture_context` integration point
**File**: `backend/app/services/alert_ack_engine.py:83`

Current `tracking_mode` derivation (lines 106-111):
```python
if gs.status == "active":
    out["tracking_mode"] = "active"
elif gs.status in ("stale", "expired"):
    out["tracking_mode"] = "shadow"
else:
    out["tracking_mode"] = "ended"
```

**Replace with offline-aware logic**:
```python
if gs.status in ("ended", "completed"):
    out["tracking_mode"] = "ended"
elif gs.is_offline:
    # GPS hasn't reported in >30s — treat as shadow even if status=active.
    # This is what triggers the 10s fast-path ACK timeout in
    # _compute_ack_timeout(severity, context).
    out["tracking_mode"] = "shadow"
elif gs.status == "active":
    out["tracking_mode"] = "active"
elif gs.status in ("stale", "expired"):
    out["tracking_mode"] = "shadow"
else:
    out["tracking_mode"] = "ended"
out["last_seen_online_at"] = (
    gs.last_seen_online_at.isoformat() if gs.last_seen_online_at else None
)
out["offline_gaps"] = int(gs.offline_gaps or 0)
out["max_gap_seconds"] = int(gs.max_gap_seconds or 0)
```

This is the high-leverage move. A guardian who clicks `seen` on a critical alert during an offline gap now gets **a 10s window to commit to `acting`**, not 30s — because the system knows tracking is unreliable.

---

## Watchdog adaptation
**File**: `journey_gap_watchdog.py` (artifact)

**Write-authority rule (LOCKED)**: GPS updates may transition session → ACTIVE. Watchdog may ONLY transition session → PAUSED/OFFLINE. Watchdog **must never** transition a session → ACTIVE. Recovery is the GPS path's responsibility (the next ping clears `is_offline`, fires `journey_resumed`).

The watchdog calls `_journey_service.tick_gap_watchdog()`. In the layered approach, this becomes:

```python
async def tick_gap_watchdog():
    """Mark sessions as offline when no GPS in >30s, broadcast journey_paused.

    READ-ONLY-INFERENCE: this function is NOT allowed to set is_offline=False
    or revive any session. It is the negative-side of the state machine only.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=30)
    rows = (await session.execute(
        select(GuardianSession).where(
            GuardianSession.status == "active",
            GuardianSession.is_offline == False,  # noqa
            GuardianSession.previous_update_at < cutoff,
        ).with_for_update(skip_locked=True)
    )).scalars().all()
    for gs in rows:
        gs.is_offline = True                                  # ↓ downgrade only
        gs.offline_gaps = (gs.offline_gaps or 0) + 1
        gap = (now - gs.previous_update_at).total_seconds()
        gs.max_gap_seconds = max(gs.max_gap_seconds or 0, int(gap))
        await _emit_session_event(gs, "journey_paused",
                                   {"gap_seconds": int(gap), "auto": True,
                                    "session_id": str(gs.id),
                                    "seq": int(gs.total_points or 0)})
    await session.commit()
```

Register in `scheduler_runner.py` next to the other 14 schedulers (will be the 16th now that `alert_ack` is also in the list).

---

## Mobile (artifacts as-shipped, minor wiring)
- `mobile/services/journeyIntelligence.ts` — Zustand store + `buildPolylineSegments()`. Drop in as-is, but rename `startJourney` to call the existing `/api/guardian/start` endpoint (NOT a new `/journey/start`). Same for `recordLocation` → existing `/api/guardian/update-location`. `endJourney` → existing `/api/guardian/end`.
- `mobile/components/JourneyPolyline.tsx` — drop in as-is, no changes.
- SSE event names stay the same (`journey_started, journey_paused, journey_resumed, journey_ended`) — these are NEW events emitted from `update_location` and the watchdog.

## Test bundle
Create `backend/tests/test_journey_intelligence.py` with:
- `test_gap_detector_classifies_good_under_15s`
- `test_gap_detector_classifies_unstable_15_to_30s`
- `test_gap_detector_classifies_offline_over_30s`
- `test_offline_recovery_emits_journey_resumed`
- `test_offline_increments_offline_gaps_counter`
- `test_max_gap_seconds_only_grows`
- `test_journey_points_inserted_with_quality`
- `test_ack_engine_offline_session_gets_shadow_tracking_mode` ← **the high-value test**
- `test_watchdog_marks_stale_sessions_offline`

## Risk checks
- **Don't break the 24h cap**: zombie cap runs BEFORE gap detection. Order matters.
- **Don't double-write trail**: `journey_points` is the only trail table. Don't also write to legacy `location_logs` or `gps_pings` if those exist.
- **Don't break shadow tracking**: if a session is rejected (ended/completed/24h cap), the API path STILL routes to `shadow_ping`. Gap detector only runs on ACCEPTED pings.

## One-pass execution order for next session
1. Read this doc + the 3 reference files
2. Migration: add 5 cols to `guardian_sessions`, create `journey_points`
3. Patch `guardian_mode_engine.update_location` (+accuracy param + gap detector + trail insert)
4. Patch `alert_ack_engine._capture_context` (offline-aware tracking_mode)
5. Adapt watchdog (`tick_gap_watchdog` reads from `guardian_sessions`)
6. Register watchdog in scheduler_runner
7. Add SSE event emitters for `journey_paused/resumed`
8. Create `GET /api/guardian/{session_id}/polyline` endpoint (reads `journey_points`)
9. Drop in mobile artifacts as-is, repoint URLs to existing `/api/guardian/*` routes
10. Run test bundle
11. Live e2e: simulate >30s gap, verify offline event, verify ACK engine receives `tracking_mode=shadow`
