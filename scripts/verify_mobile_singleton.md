# Mobile Realtime Singleton — QA Build Verification Runbook

**Audience:** QA, RM, on-call validating a new mobile build (TestFlight / internal track).
**Time:** 5 minutes wall-clock.
**Build flag:** Dev/Staging only — production builds tree-shake the badge out, so this runbook does NOT apply to App Store / Play Store releases.

This runbook validates that the May-7 realtime architecture audit
(singleton SSE + GPS + geofence loop, polling-coordinated-with-SSE,
exponential backoff with jitter) actually holds at runtime. The
`RealtimeStatusBadge` floating overlay surfaces the truth — your
job is to verify the badge matches each step's expected state.

## Prerequisites

- Mobile build installed on a physical device (simulator works for steps 1–4; airplane-mode steps 5–6 need real device)
- Network reachable, then disable-able (toggle airplane mode)
- Test credentials from `/app/memory/test_credentials.md`:
  - Guardian: `mothernischint@gmail.com` / `nischint123`
  - Child:    `kidnischint@gmail.com`    / `nischint123`
- Backend: production (`https://nischint.care`) — no preview URL needed for badge verification

## What the badge looks like

Bottom-right floating pill. Color-coded left border + status dot:

| State            | Border / dot color | Title format                              |
|------------------|--------------------|--------------------------------------------|
| Idle (no subs)   | red                | `RT · IDLE · IDLE`                          |
| Connected        | green              | `RT · GUARDIAN · CONNECTED`                |
| Stale            | red                | `RT · GUARDIAN · STALE`                    |
| Disconnected     | red                | `RT · GUARDIAN · DISCONNECTED`             |
| Reconnecting     | amber              | `RT · GUARDIAN · RECONNECTING (#N)`         |

Tap the badge to expand. Long-press to dismiss for the rest of the session.

Expanded view (Connected example):

```
RT · GUARDIAN · CONNECTED
─────────────────────────
role        guardian
sse         alive  age=4s
subs        1
retry       —
polling     IDLE (sse healthy)
tap to collapse · long-press to dismiss
```

## Verification Steps

### ✅ Step 1 — Cold launch

**Action:** Force-quit, relaunch app. Stay on the auth/login screen.

**Expected badge:**
- Title: `RT · IDLE · IDLE`
- Border + dot: red

**Pass criterion:** Badge is visible with `IDLE` text. (Confirms the badge file is mounted; no SSE has connected yet because no consumer is mounted.)

**Fail signal:** Badge missing → `RealtimeStatusBadge` not mounted in `_layout.tsx` OR build is non-DEV (`__DEV__ === false`).

---

### ✅ Step 2 — Login as guardian

**Action:** Login with guardian credentials. Wait until the home dashboard loads.

**Expected badge (within ~1s):**
- Title: `RT · GUARDIAN · CONNECTED`
- Border + dot: green
- Tap to expand → `subs` row reads `1`

**Pass criteria (all must hold):**
1. Title flips from IDLE to GUARDIAN
2. Color flips from red to green within 2 seconds
3. `subs = 1` (one consumer attached, singleton holds one connection)
4. `polling = IDLE (sse healthy)`

**Fail signals:**
- `subs > 1` with only home dashboard mounted → ref-counting broken
- Color stays red beyond 5s → SSE not connecting (check device network OR `OPS_SLACK_WEBHOOK_URL` regression)
- `polling = ACTIVE` while badge shows green → polling-coordination gate broken

---

### ✅ Step 3 — Singleton stress: rapid tab switching

**Action:** Tap each bottom-tab in sequence (Home → Map → Profile → Home → Map → ...) **30 times in 30 seconds**.

**Expected badge throughout:**
- Title stays `RT · GUARDIAN · CONNECTED`
- `subs` row stays at `1` (or briefly `2` during the millisecond between effect-mount and effect-unmount, never higher)
- Color stays green; no `RECONNECTING` flicker

**Pass criterion:** `subs` never climbs to `3` or higher. The badge never shows the amber `⚠ check singleton` warning.

**Fail signals:**
- `subs` climbing past 2 → useEffect cleanup not firing on unmount → memory leak
- `subs` showing the amber `⚠ check singleton` warning text → singleton ref-counting broken; **block the release**

---

### ✅ Step 4 — Reconnect ladder

**Action:** With app foregrounded and badge green, kill SSE by toggling **airplane mode ON for 5 seconds**, then airplane mode OFF.

**Expected badge sequence:**
1. Within 1s of airplane ON: title flips to `RT · GUARDIAN · RECONNECTING (#1)`, border amber
2. Backoff ladder visible in `retry` row: `#1 → #2 → #3 → ...` as attempts fire (1s → 2s → 5s → 10s → 30s → 60s with ±25% jitter)
3. `polling` row flips to `ACTIVE (fallback)` (since SSE is no longer alive)
4. After airplane OFF: within ~5s, title returns to `CONNECTED`, color returns to green, `retry` returns to `—`, `polling` returns to `IDLE`

**Pass criteria:**
- Backoff `#N` increments visibly (no stuck `#1` looping forever)
- Recovery happens within 5s of network return
- After recovery, `subs` is still `1` (no orphan connections from failed attempts)

**Fail signals:**
- Multiple parallel `RECONNECTING (#1)` events without `#2 #3` progression → backoff timer leaking, multiple in-flight reconnects
- `subs > 1` after recovery → reconnect path created a second EventSource without closing the first
- Polling row stays `IDLE` while badge shows red → polling-coordination broken (polling won't fall back to fetch the live data)

---

### ✅ Step 5 — Background / foreground

**Action:** With badge green, send app to background (home button) for **5 seconds**, then foreground.

**Expected:**
- During background: badge state is frozen (you can't see it anyway)
- On foreground: badge stays `CONNECTED` green; `subs = 1`; `retry` stays `—`
- The connection should NOT have been torn down because the bg-disconnect grace is 10s

**Now repeat with 15 seconds in background:**

**Expected:**
- On foreground: badge briefly shows `RECONNECTING (#1)` then returns to `CONNECTED` within 1–2s
- `subs` ends at `1`

**Fail signal:** Multiple sequential `RECONNECTING` cycles after foreground → AppState listener not deduping; check `[APPSTATE_LISTENER]` log only appears ONCE per launch.

---

### ✅ Step 6 — Long-press dismiss

**Action:** Long-press the badge for ~1s.

**Expected:** Badge disappears for the rest of the session. Will reappear on next app launch.

**Pass criterion:** Badge dismisses cleanly with no visual glitch.

---

## Cross-checks (optional but recommended)

These don't require the badge — they're log-based confirmations for the same singleton properties.

Connect Metro / native logs and grep:

```
[SSE_SINGLETON] guardian first subscriber — opening connection
```
- Should appear EXACTLY ONCE per app launch per role.

```
[SSE_SINGLETON] guardian subscriber count=N (reusing)
```
- Should appear on every subsequent subscription. The `(reusing)` is the proof.

```
[APPSTATE_LISTENER] guardian registered
```
- Should appear EXACTLY ONCE per app launch.

```
[POLLING_FALLBACK_DISABLED] guardian — SSE healthy
```
- Should appear within ~5s of login.

```
[POLLING_FALLBACK_ENABLED] guardian — SSE stale/down
```
- Should appear within ~10s of airplane mode going on.

If any of those grep counts is unexpectedly off (e.g. `[APPSTATE_LISTENER]` appears 4 times), it's a regression — file a bug.

## Pass / Fail Decision Matrix

| Step | If badge shows expected state ✅ | If badge shows unexpected state ❌ |
|------|----------------------------------|-------------------------------------|
| 1    | continue                          | re-check that build is dev/staging  |
| 2    | continue                          | block release; check SSE wiring     |
| 3    | continue                          | **block release**; ref-counting bug |
| 4    | continue                          | block release; backoff timer leak   |
| 5    | continue                          | file bug; AppState listener leak    |
| 6    | runbook complete                  | file UI bug                         |

**Release decision:** ALL six steps must pass. Steps 3 and 4 are the critical singleton-correctness signals; failures there are immediate blockers.

## Common Failure Modes (and what to do)

| Symptom                                       | Likely cause                                            | Action |
|------------------------------------------------|----------------------------------------------------------|--------|
| Badge missing entirely                         | `__DEV__ === false` OR not mounted in `_layout.tsx`      | Verify build channel is dev/staging |
| `subs` shows ⚠ amber warn                     | Singleton ref-counting regressed                          | Block; revert hook changes; report |
| `RECONNECTING (#1)` looping forever            | Backoff timer leak — multiple in-flight reconnects        | Block; check `_retryTimer` guard |
| Badge stays red after network restored         | EventSource error event not firing reconnect schedule     | Check Metro logs for `[SSE_BACKOFF]` |
| `subs` jumps on every screen visit             | useEffect cleanup not firing — likely missing dep array   | Block; trace `_subscribe` / `_unsubscribe` calls |

## Reporting Template

Paste into the build-verification ticket:

```
Build: <build-id>
Device: <model> / <OS version>
Tester: <name>
Date/time: <ISO>

Step 1 (cold launch):     ✅ / ❌  notes:
Step 2 (login):           ✅ / ❌  notes:
Step 3 (tab stress):      ✅ / ❌  subs peak=<N>
Step 4 (airplane mode):   ✅ / ❌  highest #attempt seen=<N>
Step 5 (background):      ✅ / ❌  notes:
Step 6 (dismiss):         ✅ / ❌  notes:

Verdict: SHIP / BLOCK
```

---

**Maintainer note:** the badge code lives in `mobile/components/dev/RealtimeStatusBadge.tsx`. If new SSE singletons are added (e.g. for a future operator role), extend the badge's `inferRole` function and the public getter exports. Keep this runbook in lockstep with badge state strings — copy edits to the title/labels need a runbook revision.
