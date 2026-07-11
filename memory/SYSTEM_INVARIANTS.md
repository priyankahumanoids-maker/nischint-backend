# SYSTEM_INVARIANTS.md

> The soul of the system. Read this first.
> Every engineer and every agent touching this codebase reads this
> before writing a single line. These rules are non-negotiable.
> Violating them silently breaks safety guarantees that took multiple
> sessions to design.

---

## Invariant #1 — `guardian_sessions` is the SOLE lifecycle state owner

**Rule**: All session lifecycle state lives in `guardian_sessions`. No other table or service is allowed to mutate session lifecycle state. Other tables (alerts, journey_points, shadow_location_pings, system_incidents, push_tokens) reference `guardian_sessions(id)` as a foreign key — they never own a parallel state machine.

**Why**: When a parallel state machine exists (e.g. a separate `journeys` table), GPS pings can route through paths that bypass shadow tracking, the 24h zombie cap, and the ACK engine's `tracking_mode` context. The result is a system that *appears* to work but silently degrades safety guarantees under failure.

**Enforcement**:
- Any new feature touching session-like state must extend `guardian_sessions` columns, not create a new state table.
- Derived projections (e.g. polylines, audit trails, behavior timelines) live in append-only event-log tables. They are NOT state sources.

**Where this rule was first locked**: Apr 28, 2026 — during the Journey Intelligence integration design review.

---

## Invariant #2 — Device timestamps are UNTRUSTED. Server session clock is the authority.

**Rule**: All timestamp comparisons in safety-critical paths MUST use `guardian_sessions.previous_update_at` (server session clock) as the reference, never raw device time (`gps_recorded_at`, `client_ts`, etc.). When comparing an incoming GPS packet to recorded state, a device timestamp that's *ahead* of server time is treated as **stale** (clock skew), not as "from the future."

**Why**: Three time axes coexist:
- `gps_recorded_at` — device time. Drifts. Jumps on time-zone changes. Can be deliberately wrong (rooted phones, debug tools).
- `previous_update_at` — server session time. Monotonic per session.
- watchdog tick time — system inference time. Used for absolute "how long since last seen" math.

If safety logic ever uses device time as truth, two failure modes appear:
1. **Phantom recovery events** under poor mobile networks — out-of-order packets register as "fresh" because their device timestamps land slightly ahead.
2. **False shadow-mode dropouts** when a guardian's phone clock is briefly wrong — the system flips to offline even though the device is actively pinging.

**Enforcement**:
- The stale-packet guard in `update_location` is the **first line of logic**, before zombie cap, before resurrection, before any side effects.
- The watchdog uses `now() - previous_update_at` for gap math, never anything derived from device payloads.
- New safety features adding clock-based logic must explicitly state which time axis they use and pass review against this invariant.

**Where this rule was first locked**: Apr 28, 2026 — during the Journey Intelligence integration design review (timestamp normalization rule).

---

## Invariant #3 — Asymmetric write authority on session state

**Rule**: The GPS path can transition a session → ACTIVE. The watchdog can ONLY transition a session → PAUSED / OFFLINE. The watchdog **never** transitions a session → ACTIVE. Recovery is the GPS path's exclusive responsibility.

**Why**: The watchdog has no information about whether the device is *currently* alive. It only knows "no GPS in N seconds." Allowing it to upgrade state means a stale check could resurrect a session whose device has been offline for hours. Recovery is a *positive event* — only a fresh ping can prove it. The watchdog is read-only-inference on the negative side: it can detect the absence of signal, never the presence.

**Enforcement**:
- `tick_gap_watchdog()` in `journey_gap_watchdog` ONLY sets `is_offline = True`, increments `offline_gaps`, updates `max_gap_seconds`. It does not set `is_offline = False` or set `status = 'active'`. Ever.
- Recovery path lives in `update_location`: when an incoming ping clears the offline state, `journey_resumed` fires from the GPS path.
- Code review must reject any watchdog-side path that flips state in the positive direction.

**Where this rule was first locked**: Apr 28, 2026 — during the Journey Intelligence integration design review.

---

## How to add a new invariant

When you discover a new system-level rule that, if violated, silently breaks safety:
1. Add it as a new section here with the same structure: **Rule / Why / Enforcement / Where first locked**
2. Reference it in the next session's handoff brief
3. Add at least one regression test that fails if the invariant is violated

Invariants compound. Each one you lock down is one fewer category of bug a future engineer can introduce by accident.
