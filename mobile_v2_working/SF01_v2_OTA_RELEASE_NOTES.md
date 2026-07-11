# SF-01 v2 — Mobile OTA Release Notes (Preview channel)

**Build:** SF-01 v2 (Days 1+2+3+4+5 complete)
**Channel:** `preview`
**Date:** 22 May 2026
**Author:** Feroz Shaikh

---

## TL;DR for the 3-account smoke test

```bash
cd /app/mobile
eas update --channel preview --message "SF-01 v2 — fusion sprint complete (fall FP guards, motion heartbeat, env multiplier, demo button row)"
```

After the EAS publish completes (≈2 min), launch the app on each of the three preview-channel test accounts and confirm the Validation Matrix below.

---

## What's shipping

### Day 1 — Fall-detection FP guards
- `mobile/services/fallDetection.ts`
  - **Gyro-confirm guard**: peak angular velocity must reach ≥ 2.094 rad/s (120 °/s) within 500 ms of the accel impact. Locks `GYRO_CONFIRM_THRESHOLD_RAD_S` and `GYRO_CONFIRM_WINDOW_MS`.
  - **GPS-speed vehicle suppression**: device ≥ 20 km/h AND GPS fix < 10 s old → impact path never arms. Locks `GPS_SPEED_SUPPRESS_KMH = 20`.
  - New export: `updateGpsSpeed(speed_kmh)` — fed from `locationService.onLocationUpdate` on every GPS tick.

### Day 2 — Live motion heartbeat
- `mobile/services/motionTelemetryService.ts`
  - New 30 s heartbeat `_emitLiveHeartbeat()` → `POST /api/signals/motion`. Bandwidth-guarded — skips baseline frames (accel stddev ≤ 0.04 AND peak ≤ 1.30 g).
  - New export: `setLatestLocation(lat, lng)` — cached from `locationService` so the heartbeat doesn't take its own GPS fix.
- `mobile/services/sensorService.ts`
  - Emits `POST /api/signals/motion` alongside the existing `/sensors/fall` report on `FALL_DETECTED`. Both run; additive contract.
- `mobile/services/locationService.ts`
  - Calls `updateGpsSpeed(speed * 3.6)` + `setLatestLocation(lat, lng)` on every fix. Lazy imports so the start-up contract is unchanged.

### Days 3-5 are backend-only — no mobile code touched
The mobile build sees the new behaviour transparently via:
- Backend env multiplier (×1.30) when NDMA/OpenWeather red flags match — surfaced on the same `safety_risk_alert` SSE event.
- New `alert_fired` flag on the response envelope.
- New `cooldown_suppressed` field for dedup awareness.

---

## Pre-publish checklist

Run from `/app/mobile`:

```bash
# 1. Verify TypeScript is clean
yarn tsc --noEmit

# 2. Verify the EAS channel config
cat eas.json | grep -A1 '"preview"'
# expected: "channel": "preview"

# 3. (Optional) sanity-build for development first
eas update --channel development --message "smoke build SF-01 v2"

# 4. Publish to preview
eas update --channel preview \
  --message "SF-01 v2 — fusion sprint complete (fall FP guards, motion heartbeat, env multiplier, demo button row)"
```

If you want a no-op dry run first:

```bash
eas update --channel preview --message "..." --non-interactive --json | jq '.'
```

---

## Validation Matrix (3 preview accounts)

Run each step on **all three** preview-channel devices. ✓ = pass, ✗ = fail.

| Step | Action | Expected | A | B | C |
|---|---|---|---|---|---|
| 1 | Cold-boot the app after OTA | `Updates.isEmbeddedLaunch === false` (OTA applied) — visible in dev menu | ☐ | ☐ | ☐ |
| 2 | Start a safety session | Session UI loads; no console errors | ☐ | ☐ | ☐ |
| 3 | Walk normally for 60 s | `motionTelemetryService` heartbeat fires (check network log: `POST /api/signals/motion` at 30 s + 60 s) | ☐ | ☐ | ☐ |
| 4 | Sit on a chair quickly | **No fall detected** (gyro-confirm guard rejects) | ☐ | ☐ | ☐ |
| 5 | Drop the phone on a desk from 30 cm | **No fall detected** (gyro tumble < 120 °/s) | ☐ | ☐ | ☐ |
| 6 | Jog in place for 30 s | **No fall detected** (gyro confirm + voice = 0 — no simultaneous bonus) | ☐ | ☐ | ☐ |
| 7 | Simulate a vehicle: walk briskly while phone reports GPS speed > 20 km/h (use dev-menu `setGpsSpeed(25)` if needed) | **GPS-speed suppression** rejects any spike. Console log: `[FALL] suppressed by GPS speed guard` | ☐ | ☐ | ☐ |
| 8 | Simulate a fall (controlled drop with body-axis tumble) | Fall detected. Vibration triggers. `/sensors/fall` + `/signals/motion` both posted. | ☐ | ☐ | ☐ |
| 9 | Stay in airplane mode for 60 s | App keeps queueing motion windows; on reconnect, batch upload at `POST /api/sensors/motion/features` succeeds idempotently | ☐ | ☐ | ☐ |
| 10 | Operator (one tester) opens Command Center → selects this user → fires `Himalaya Landslide` dev scenario | On the **device**, an SSE `safety_risk_alert` arrives → in-app banner. On the **operator browser**, the row glows amber for 3 s + the result chip shows `composite 0.793 · ALERT`. | ☐ | ☐ | ☐ |

**Pass criteria**: all three accounts pass steps 1-10 ✓. Any ✗ on steps 4-7 is a P0 — the FP guards regressed.

---

## Rollback plan

If any step 4-7 ✗ on more than one account, roll back immediately:

```bash
# 1. List recent updates on the preview channel
eas update:list --channel preview --limit 5

# 2. Republish the last known good update by its id
eas channel:edit preview --branch <last-good-branch-name>
```

Last known good build before this OTA: the SF-01 v1 build published on 18 May 2026 (pre-fusion-sprint).

---

## Investor-demo gate

After the OTA validation matrix passes on all 3 accounts:

1. Run the **CLI smoke** from your laptop:
   ```bash
   cd /app/backend
   python scripts/inject_himalaya_scenario.py
   ```
   Expected: `✓ HIMALAYA SCENARIO PASSED — demo arc is live`.

2. Open `https://gps-mic-restart.preview.emergentagent.com/command-center` as the operator account, select a test user, click **Fire: Himalaya Landslide**.
   Expected (in this exact order):
   - Button shows spinner
   - Result chip appears: `base 0.610 · ×1.30 env → 0.793 · ALERT`
   - The selected user's row in **AI Risk Intelligence** glows amber for 3 s (`data-flashing="true"`)
   - On the test device, an in-app safety alert banner fires within 3 s

3. Both gates green ⇒ the Himalaya demo is on-stage ready. Record the screen capture per the Day 4 plan.

---

## Files touched by this OTA

```
mobile/services/fallDetection.ts          (Day 1 — gyro confirm + GPS speed guard)
mobile/services/motionTelemetryService.ts (Day 2 — 30s heartbeat + setLatestLocation)
mobile/services/sensorService.ts          (Day 2 — emit /signals/motion on fall)
mobile/services/locationService.ts        (Day 1+2 — feed GPS speed + location cache)
```

All four files lint-clean (`yarn tsc --noEmit` + ESLint passed locally before publish).

---

*Document version: 1.0 · Generated 22 May 2026 by SF-01 v2 Day 5 close-out.*
