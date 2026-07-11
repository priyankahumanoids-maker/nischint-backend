# NISCHINT FUSION ARCHITECTURE

**Sprint:** SF-01 v2 (completed 21–22 May 2026)
**Owner:** Feroz Shaikh · Founder & CEO
**Compliance:** DPDP Act 2023 · Draft DPDP Rules 2026

---

## Executive summary

NISCHINT is the first **multimodal sensor fusion safety OS** built ground-up for India. Where competitors stop at GPS + manual SOS, NISCHINT fuses six independent sensor layers into a single composite safety score that fires alerts in **under one second** from event to guardian notification.

This document maps the 6-layer ambient-intelligence architecture to the exact code paths shipping in production today.

---

## The 6-Layer Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│  Layer 6 — Action Engine                                            │
│  Notification · SOS · Guardian Alert · Auto-Escalation              │
└────────────────────────────────────────────────────────────────────┘
                                ▲
┌────────────────────────────────────────────────────────────────────┐
│  Layer 5 — Risk Engine (Safety Brain)                               │
│  Composite = Σ(signal × weight) + bonus × env multiplier            │
└────────────────────────────────────────────────────────────────────┘
                                ▲
┌────────────────────────────────────────────────────────────────────┐
│  Layer 4 — Context Engine                                           │
│  Time · Location · User Baseline · Behavioural Twin                 │
└────────────────────────────────────────────────────────────────────┘
                                ▲
┌────────────────────────────────────────────────────────────────────┐
│  Layer 3 — AI Inference                                             │
│  Fall · Voice Distress · Route Dev · Wandering · Pickup Anomaly     │
└────────────────────────────────────────────────────────────────────┘
                                ▲
┌────────────────────────────────────────────────────────────────────┐
│  Layer 2 — Edge Processing                                          │
│  Noise filter · Feature extraction · 60s windows · 5min batches     │
└────────────────────────────────────────────────────────────────────┘
                                ▲
┌────────────────────────────────────────────────────────────────────┐
│  Layer 1 — Sensor Collection                                        │
│  Accelerometer · Gyroscope · GPS · Audio                            │
└────────────────────────────────────────────────────────────────────┘
```

---

## Layer-by-layer mapping (shipped code)

### Layer 1 — Sensor Collection

| Sensor | Sample rate | Mobile module |
|---|---|---|
| Accelerometer | 5 Hz (subsampled from 20 Hz native) | `mobile/services/motionTelemetryService.ts` |
| Gyroscope | 5 Hz | `mobile/services/motionTelemetryService.ts` |
| GPS | Adaptive (1–60 s) | `mobile/services/locationService.ts` |
| Audio | On-demand (safety-session-gated) | `mobile/services/audioMonitorService.ts` |

**Privacy contract**: All sensor reads are gated by explicit per-session consent. Audio is processed on-device and never uploaded unless a distress event is confirmed by the user.

### Layer 2 — Edge Processing

- **60 s feature windows** per the NISCH-012 contract (`window_started_at`, mean/peak/stddev of accel magnitude, gyro variance, activity_class).
- **5 min batched uploads** to `POST /api/sensors/motion/features` (audit ledger, immutable, `ON CONFLICT (idempotency_key) DO NOTHING`).
- **30 s live heartbeat** to `POST /api/signals/motion` for composite recalc — bandwidth-guarded (skips baseline frames where accel stddev ≤ 0.04 AND peak ≤ 1.30 g).

### Layer 3 — AI Inference

Five independent detection layers, each gated by its own confidence threshold:

| Detector | Mobile module | Backend wire-up | Confidence threshold |
|---|---|---|---|
| Fall Detection | `mobile/services/fallDetection.ts` (5-stage pipeline) | `POST /api/sensors/fall` + `POST /api/signals/motion` | 0.75 |
| Route Deviation | `live_deviation_engine.py` (server-side) | SSE `route_deviation_alert` | corridor-based |
| Voice Distress | `mobile/services/voiceDistression.ts` + `audioMonitorService.ts` | `POST /api/sensors/voice-distress` | 0.65 |
| Wandering Detection | server-side baseline anomaly detector | `behavioral_anomalies` table | `sample_count ≥ 5` |
| Pickup Anomaly | server-side guardian-link validator | `POST /api/sensors/pickup-validate` | binary |

**Day 1 fall FP guards** (SF-01 v2):
- **Gyro confirmation**: angular velocity must hit ≥ 2.094 rad/s (120 °/s) within 500 ms of the accel impact. Rejects sitting-down / phone-dropped / running false positives.
- **GPS-speed suppression**: device ≥ 20 km/h with a < 10 s old GPS fix → impact path never arms. Rejects pothole / vehicle-deceleration FPs.

### Layer 4 — Context Engine

- **Behavioural baselines**: `backend/app/services/behavioral/baseline.py` — per-user `mobility_signature`, `zone_affinity`, `motion_telemetry` sub-key. Enriched additively; never blocks GPS-derived baseline.
- **Digital twin**: `backend/app/services/behavioral/detector.py` — immutable anomaly ledger. Cold-start gracefully when `sample_count < 5`.
- **Twin trust calibration**: `backend/app/services/behavioral/trust.py` — `MOTION_FRESHNESS_MEDIUM_RED_S = 1800 s`. Motion staleness is observational — never alone-pushes the trust band to LOW.

### Layer 5 — Risk Engine (Safety Brain)

The composite score that drives all alert decisions:

```
score = Σ(signal_i × weight_i)
      + simultaneous_bonus     (if fall ≥ 0.5 AND voice ≥ 0.5)
      × env_hazard_multiplier  (if NDMA / OpenWeather red flag matches)
clipped to [0, 1]
```

Locked constants in `backend/app/services/safety_brain_service.py`:

| Constant | Value | Rationale |
|---|---|---|
| `WEIGHTS["fall"]`               | 0.35 | strongest single-channel indicator |
| `WEIGHTS["voice"]`              | 0.30 | second-strongest; locked at 0.30 (not 0.25) for Himalaya demo margin |
| `WEIGHTS["route"]`              | 0.15 | |
| `WEIGHTS["wander"]`             | 0.10 | |
| `WEIGHTS["pickup"]`             | 0.10 | |
| `SIMULTANEOUS_FALL_VOICE_BONUS` | +0.10 | both ≥ 0.5 → "two channels confirming one event" |
| `SIMULTANEOUS_FALL_THRESHOLD`   | 0.5  | |
| `SIMULTANEOUS_VOICE_THRESHOLD`  | 0.5  | |
| `ENV_HAZARD_MULTIPLIER`         | ×1.30 | NDMA / OpenWeather red flag — multiplicative, not additive |
| `ALERT_THRESHOLD`               | 0.65 | composite-alert tier (fans out FCM, locks `alert_cooldown` key) |
| `ALERT_COOLDOWN_TTL_S`          | 300 s | canonical `safety_brain:alert_cooldown:{user_id}` dedup key |

Locked tier ladder:
- `< 0.30` → **normal**     (no event row)
- `0.30 – 0.65` → **suspicious** (audit row, no fan-out)
- `0.65 – 0.85` → **alert**       (FCM + SSE fan-out, `alert_fired = true`)
- `≥ 0.85` → **emergency**  (auto-escalation, SMS via Twilio + email via SendGrid)

### Layer 6 — Action Engine

| Channel | Provider | Cooldown |
|---|---|---|
| FCM push | Firebase | per-channel `cooldown:{user_id}` (60 s) + composite `alert_cooldown:{user_id}` (300 s) |
| SMS | Twilio | rate-limited per emergency contact |
| Voice call | Twilio | emergency-only (composite ≥ 0.85) |
| Email | SendGrid | guardian digest (hourly) |
| Operator alert | SSE | `safety_risk_alert` + `env_hazard_match` (distinct events) |

---

## The Himalaya demo arc (locked math invariant)

```
Phase 1 — Motion + Voice
  fall(0.90) × 0.35 + voice(0.65) × 0.30 = 0.510 base

Phase 2 — Simultaneous-event bonus (both ≥ 0.5)
  + 0.10 bonus                            = 0.610 base

Phase 3 — Environmental hazard match (Uttarakhand landslide CAP alert)
  × 1.30 ENV multiplier                   = 0.793 composite

  → action = ALERT (≥ 0.65)
  → alert_fired = true
  → safety_brain:alert_cooldown:{user_id} set, TTL = 300 s
  → SSE: safety_risk_alert + env_hazard_match
  → FCM dispatched to linked guardians
```

**Demo gate**: `backend/scripts/inject_himalaya_scenario.py` — 7 assertions, all green. Operator-side trigger: `POST /api/operator/dev/scenario` (dual-gated by `DEV_SCENARIOS_ENABLED=true` + operator/admin role) plus the in-app `<DevScenarioPanel />` button row.

---

## False-positive guarantees (Day 5 regression-locked)

Three canonical "must-never-fire" fingerprints, each backed by a pytest test in `tests/test_sf01_v2_day5_fp_regression.py`:

| Scenario | Fingerprint | Expected composite | Locked test |
|---|---|---|---|
| **Jog**            | clean motion, voice = 0.20 | < 0.30 (normal)        | `test_jog_with_clean_motion_stays_normal` |
| **Car ride**       | fall = 0 (suppressed), voice = 0 | = 0.0 (normal)          | `test_car_ride_with_suppressed_fall_stays_normal` |
| **Offline mobile** | lat = 0, lng = 0, no env match | env mult = 1.0, no alert | `test_offline_no_gps_zero_zero_no_env_match` |

Plus 4 invariant-lock tests that fail if any of the demo-critical constants are silently relaxed (`ALERT_THRESHOLD`, `SIMULTANEOUS_*`, `WEIGHTS["voice"]`, `ENV_HAZARD_MULTIPLIER`).

---

## Reliability ratchet

A swallow-audit AST guard (`tests/test_swallow_audit.py`) ensures no silent `except Exception` blocks exist without compensating actions. Current state (locked):

- `unresolved_debt = 1`
- `compensating_action_exists = 41`
- `idempotency_race = 1`

Every new try/except for INSERT or external-side-effect paths must register a compensating action OR an idempotency mechanism in the `_ALLOWED_SWALLOWERS` table. The CI gate fails if the count drifts upward.

---

## DPDP compliance posture

- **Data Fiduciary**: NISCHINT Technology Private Limited
- **Database**: AWS Mumbai (ap-south-1) ✓ (migrated from Singapore on 2026-05-22 — Supabase Mumbai pooler)
- **Auth/Compute**: AWS Mumbai (ap-south-1) ✓
- **Data Hosting note**: All personal data stored and processed in India. SMS delivery via Twilio, push via Firebase FCM.
- **Grievance Officer**: Feroz Shaikh · privacy@nischint.app · 72 h SLA · 30-day resolution
- **Children's data**: Section 9 DPDP — verifiable parental consent + Guardian Dashboard review + session-level audio consent
- **Anticipated Significant Data Fiduciary**: building DPIA + annual audit infrastructure per Draft DPDP Rules 2026
- **Public surfaces**: `nischint.care/about`, `nischint.care/privacy-policy`

---

## Phase 4 — Health Signal Integration (HC-01, shipped 2026-05-24)

Sources: Apple Health / Google Health Connect via `react-native-health-connect`
Signals: HeartRate, OxygenSaturation, Steps, Falls
Thresholds: HR > 120 bpm → `HR_HIGH`, SpO₂ < 94% → `SPO2_LOW`, fall=1.0 → `FALL_DETECTED`
SF-01 v2 weight mapping: fall → 0.35, voice proxy → 0.18–0.21
Guardian dashboard: `DependentVitalsCard` polls `/health-signals/dependent/:id/latest`
Background sync: 10 min interval via `expo-background-fetch`
Android-only: Day 3 ships Android. iOS HealthKit entitlements ready for App Store build.

### Implementation specifics
- Mobile reads delta samples from Health Connect every 10 minutes (`expo-background-fetch` task `WEARABLE_SYNC`), `POST /api/health-signals/wearable`.
- Backend persists each sample in a Redis ZSET (`nischint:wearable:{user_id}:{type}`) with 24 h TTL, sha1-deterministic members for idempotency.
- Threshold breaches feed the existing SF-01 v2 brain via `evaluate_risk` — `FALL` → `fall=1.0` channel; `HR_HIGH` / `SPO2_LOW` → `voice` channel (no new weight keys; we deliberately did not re-calibrate the locked thresholds).
- Guardian sees a per-dependent card on the dashboard (`GET /api/health-signals/dependent/{id}/latest`, gated by the same `_resolve_guardian_ids` cache as geofence alerts). Amber border at HR > 120, red at SpO₂ < 94 — the visual semantic matches the backend brain semantic.
- 7-day deny cool-off prevents nag-prompts; AsyncStorage flags (`hc_permissions_granted`, `hc_permissions_denied_until`) drive the onboarding card visibility.
- Test coverage: 7-case backend pytest E2E + 7-case mobile `node --test` fallback suite; both green.

iOS HealthKit bridge deferred to HC-03.

---

## AIL-01 — Adaptive Intelligence Layer (SB-01, shipped 2026-05-25)

### The Hermes Learning Loop

Three compounding systems that turn every SafetyEvent into evidence for the next one:

**1. Persistent Safety Memory**
- `safety_event_feedback` table captures **guardian / user / operator** verdicts (`confirmed | false_positive | unsure`), one row per `(safety_event_id, feedback_source)` (UNIQUE index — UPSERT on re-grade).
- `device_baselines`: 5-min rolling window per device for `battery_level`, `battery_slope`, `signal_strength` (the existing `baseline_scheduler.py` infrastructure).
- `POST /api/safety-events/{id}/feedback` — auth-gated, three-way ACL (self / guardian / operator) reusing the same `_resolve_guardian_ids` 10-min cache as the geofence-alert path.

**2. Behavioral Safety Twin**
- `get_user_attenuation(session, user_id)` returns per-`primary_event` multipliers in `[0.5, 1.0]`.
- Formula: `multiplier = 1.0 − min(fp_rate × confidence_factor, 0.5)` where `confidence_factor = min(total / 20, 1.0)`.
- Activation gate: `MIN_FEEDBACK_SAMPLES = 5` (confirmed + false_positive; `unsure` excluded). Below this → multiplier 1.0 (per-signal new-user path).
- **Floor: 0.5** — life-critical signals (fall, voice) never zero out, no matter how chronic the FP rate.

**3. Operator Confidence Engine**
- `evaluate_risk()` response envelope: `weight_attenuation`, `time_multiplier`, `attenuation_source`, `attenuation_meta`.
- Command Center "⚙️ Adaptive" chip rendered per high-risk row when any multiplier < 1.0 (e.g. `Fall -26% · 5v`).
- Guardian feedback bottom sheet: surfaces **30 s after the guardian acknowledges any alert**, three-button verdict UI, AsyncStorage-dedup'd per event_id so the prompt fires AT MOST ONCE per event no matter how many ack taps land.
- `GET /api/admin/sb01/attenuation-summary` — system-wide telemetry (active users, per-event drop %, top-5 FP rates, current tunables).

### Math contract (locked)

| Scenario | Composite | Notes |
|---|---|---|
| **Himalaya, new user (no feedback)** | **0.793** | `0.61 base × 1.30 env` — the invariant, proven by code construction (empty dict → SF-01 v2 math unchanged) |
| Heavy-FP user, fall attenuated 0.5, same signals | 0.453 | `0.157 (fall) + 0.195 (voice) + 0.10 (bonus) = 0.453` |
| Off-hours nudge (1.15× on base composite) | 0.701 | Independent of env mult — they don't compound into `1.30 × 1.30 = 1.69` |
| Voice attenuated to worst case (clamped to 0.5) | 0.15 contribution at value=1.0 | Floor enforced inside `compute_risk_score` as defense-in-depth |

### Regression coverage
- 12 SF-01 v2 FP-regression tests ✅
- 12 SB-01 Hermes data-capture tests ✅
- 12 SB-01 attenuator math tests ✅
- 7 HC-01 wearable E2E tests ✅
- **43/43 green** + live `inject_himalaya_scenario.py` confirms `composite = 0.793` on the new-user code path.

---

## What's next (SF-02 sprint)

Already specced, ready to execute:

1. **PostGIS `ST_Within`** polygon-radius hazard matching (replaces v1 state-bbox approach).
2. **Health Connect wearables** — HR / SpO₂ / HRV-stress / palpitation / hypothermia.
3. **Phase 4 health-additive layer** — `+0.15 HR > 120` / `+0.12 SpO₂ < 94` / `+0.10 palpitation` / `+0.08 HRV-stress` / `+0.10 hypothermia` additives in the safety-brain composite.
4. **DPDP Data Rights Request form** — operator-routed `/api/privacy/rights-request` with a 72-h SLA clock.

---

*Document version: 1.0 · Last updated 22 May 2026*
