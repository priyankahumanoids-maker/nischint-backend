# NISCHINT Wearable Integration Readiness Audit
## P0 System Design — Engineering Assessment
---

## 1. READINESS STATUS

**Are we READY for wearable integration? PARTIAL — ~72% ready**

### What works OUT-OF-THE-BOX (zero changes):
| Component | Status | Notes |
|---|---|---|
| Emergency/SOS API | READY | `trigger_silent_sos()` accepts any `trigger_source` incl. `"wearable"` |
| Sequential Escalation Engine | READY | Voice(3x retry) → SMS blast → Command Center. Event-agnostic |
| SSE Broadcasting | READY | `broadcast_to_user()`, `broadcast_to_operators()`, `broadcast_escalation_update()` — all wearable-compatible |
| Fall Detection Pipeline (backend) | READY | 5-stage confidence scoring, Auto-SOS at 30s, `FallEvent` model, SSE events |
| Telemetry Ingestion | READY | `ingest_telemetry()` → incident rules → SSE broadcast. Generic `metric_type` + `metric_value` JSON |
| Device Model + Registration | READY | `Device` table (id, device_identifier, device_type, status, last_seen) + telemetry FK |
| Guardian Notification Flow | READY | SSE + FCM Push + Twilio SMS + Voice calling — fully multi-channel |
| Check-in System | READY | Backend check-in APIs work for any trigger source |
| Risk Scoring Engine | READY | `dynamic_risk_engine.py`, `adaptive_risk_engine.py`, `risk_fusion.py` — accept external signals |
| Zustand State Management | READY | `alertStore.ts`, `escalationStore.ts`, `riskStore.ts` — composable |
| Twilio Failsafe | READY | Sequential calls with callback webhooks, idempotent, kill switch |

### What does NOT work (gaps):
| Component | Status | Gap |
|---|---|---|
| BLE scanning/pairing | MISSING | No BLE library installed in mobile app |
| Wearable-to-User mapping | PARTIAL | `Device` model links to `Senior`, NOT to `User` — needs new FK |
| Wearable event normalization | MISSING | No `wearable_event` table or normalization layer |
| BLE reconnection lifecycle | MISSING | No connection state management for BLE |
| Background BLE (Android/iOS) | MISSING | No background task for BLE — `expo-location` bg exists but not BLE |
| Device heartbeat from wearable | PARTIAL | Heartbeat exists in telemetry_service but not wired for BLE devices |
| Wearable battery monitoring | MISSING | No battery state SSE events |

---

## 2. REUSABLE COMPONENTS (Exact Files)

### A. Emergency / SOS Pipeline
| File | What it does | Wearable use |
|---|---|---|
| `/app/backend/app/services/emergency_engine.py` | `trigger_silent_sos(session, user_id, lat, lng, trigger_source, device_metadata)` | **Direct reuse.** Wearable panic button → call `trigger_silent_sos(trigger_source="wearable_panic")`. Already broadcasts `emergency_triggered` via SSE to all guardians. |
| `/app/backend/app/api/sos.py` | `POST /api/sos/trigger` endpoint | Wearable events can hit this directly with `trigger_type: "wearable"` |

### B. Sequential Escalation Engine
| File | What it does | Wearable use |
|---|---|---|
| `/app/backend/app/services/sequential_escalation.py` | `intelligent_escalation()` — priority-sorted sequential calls → SMS blast | **Direct reuse.** Called automatically when no guardian acknowledges within 60s. Zero changes needed. |
| `/app/backend/app/services/auto_escalation_engine.py` | `schedule_guardian_failsafe()` — 60s timer → Tier 2 escalation | **Direct reuse.** Wearable panic triggers same failsafe chain. |
| `/app/backend/app/services/sms_service.py` | Twilio SMS + Voice with 3x retry + callback | Already integrated. |

### C. SSE Broadcasting
| File | What it does | Wearable use |
|---|---|---|
| `/app/backend/app/services/event_broadcaster.py` | `broadcast_to_user()`, `broadcast_to_operators()`, `broadcast_escalation_update()`, `broadcast_emergency_triggered()` | **Direct reuse.** New wearable events just call existing broadcast methods. |
| `/app/backend/app/api/stream.py` | SSE stream endpoint — delivers any event type | Already handles arbitrary event types. Add `wearable_trigger`, `fall_detected`, `wearable_heartbeat` — zero changes needed. |

### D. Fall Detection
| File | What it does | Wearable use |
|---|---|---|
| `/app/backend/app/services/fall_detection_service.py` | 5-stage pipeline (Impact → Freefall → Orientation → Post-impact → Immobility), confidence scoring, auto-SOS | **Direct reuse.** Wearable IMU data → same `report_fall(signals)` function. Just change input source from phone accelerometer to wearable IMU. |
| `/app/backend/app/models/fall_event.py` | `FallEvent` DB model (lat, lng, confidence, stages, status, emergency_event_id) | Already wearable-compatible. |
| `/app/mobile/services/fallDetection.ts` | Client-side 5-stage pipeline (accelerometer + gyroscope) | **Replaceable by wearable.** Wearable sends raw IMU → backend processes. Mobile pipeline can run in parallel as redundancy. |
| `/app/mobile/services/sensorService.ts` | Orchestrates fall detection + countdown + auto-SOS | Can be extended to handle wearable fall events. |

### E. Telemetry Ingestion
| File | What it does | Wearable use |
|---|---|---|
| `/app/backend/app/services/telemetry_service.py` | `ingest_telemetry()` — stores metric, triggers incidents (SOS/fall rules), updates device status, broadcasts SSE | **Direct reuse.** Wearable heartbeat, battery, motion data → `ingest_telemetry(metric_type="heartbeat", metric_value={...})` |
| `/app/backend/app/models/telemetry.py` | Generic telemetry model: `device_id`, `metric_type`, `metric_value` (JSON) | Already supports any metric type — heart rate, temperature, battery, motion |
| `/app/backend/app/models/device.py` | Device model with `device_identifier`, `device_type`, `status`, `last_seen` | Needs FK update: `senior_id` → `user_id` (or add `user_id` alongside) |

### F. Guardian Linking + Notifications
| File | What it does | Wearable use |
|---|---|---|
| `/app/backend/app/models/guardian_network.py` | `GuardianRelationship`, `EmergencyContact` with phones + priority | Already used by escalation engine. Wearable events flow through same chain. |
| `/app/backend/app/services/push_service.py` | FCM push notifications (VOICE_DISTRESS, ESCALATION, SOS) | Add `WEARABLE_PANIC` push type |
| `/app/backend/app/services/notification_formatter.py` | Formats push notification titles/bodies | Add wearable-specific messages |

### G. Risk Scoring
| File | What it does | Wearable use |
|---|---|---|
| `/app/backend/app/services/dynamic_risk_engine.py` | Computes risk scores: lastSeen, nightTime, erraticMovement, recentAlerts | **Extend** to include wearable signals: heart rate anomaly, inactivity duration |
| `/app/backend/app/services/risk_fusion.py` | Multi-source risk fusion | Add wearable signal weight |

---

## 3. GAP ANALYSIS

### A. Mobile Gaps

| Gap | Severity | Detail |
|---|---|---|
| **BLE Library** | CRITICAL | No BLE library installed. `expo-sensors` provides accelerometer/gyro for the PHONE only. Need `react-native-ble-plx` for wearable communication. |
| **BLE Background Handling** | HIGH | Android kills BLE scans in background after ~10min. iOS requires explicit `bluetooth-central` UIBackgroundModes. Current `expo-location` background task exists but doesn't cover BLE. |
| **Device Pairing UI** | HIGH | No pairing/scanning screen exists. Need: scan → select → pair → bond → persist connection. |
| **Connection Lifecycle** | HIGH | No BLE reconnect-on-disconnect logic. Wearable BLE drops frequently (range, interference). Need auto-reconnect with exponential backoff. |
| **Battery State from Wearable** | MEDIUM | No battery level characteristic read. Need BLE characteristic subscription for battery service (UUID `0x180F`). |
| **Expo SDK 55 + New Architecture** | MEDIUM | Expo 55 removed Legacy Architecture. `react-native-ble-plx` compatibility with New Architecture is unconfirmed. May need `expo-ble` (if available) or custom dev client. **Does NOT require ejecting.** EAS custom dev builds work. |

### B. Backend Gaps

| Gap | Severity | Detail |
|---|---|---|
| **Wearable-to-User Mapping** | HIGH | `Device.senior_id` → should be `Device.user_id` (or add new FK). Current model links to Senior table, not User. |
| **`POST /api/wearable/event` Endpoint** | HIGH | Need a dedicated wearable event ingestion API that: validates device ownership, normalizes events, routes to correct pipeline (SOS/fall/inactivity). Currently no such endpoint. |
| **Device Authentication** | MEDIUM | Current device.py uses user JWT. Wearable can't authenticate via JWT. Need device-token-based auth (shared secret provisioned during pairing). |
| **Wearable Event Normalization** | MEDIUM | Need a service that maps raw BLE characteristics to system events (button_press → emergency_triggered, fall → fall_detected). |
| **Heart Rate Ingestion** | LOW | No heart rate telemetry type defined. Need `metric_type: "heart_rate"` incident rule for anomaly detection. |

### C. Data Model Gaps

| Gap | Severity | Detail |
|---|---|---|
| **`wearable_devices` Table** | HIGH | Need: `id`, `user_id` (FK→users), `device_mac`, `device_name`, `device_type` (band/pendant/watch), `firmware_version`, `battery_level`, `is_connected`, `last_seen`, `paired_at` |
| **`wearable_events` Table** | HIGH | Need: `id`, `device_id` (FK→wearable_devices), `event_type` (panic_press, fall_detected, inactivity, heart_anomaly, low_battery), `raw_data` (JSON), `processed`, `lat`, `lng`, `created_at` |
| **New Event Types** | MEDIUM | System needs: `wearable_panic`, `wearable_fall`, `wearable_inactivity`, `wearable_heart_anomaly`, `wearable_low_battery`, `wearable_disconnected` |

### D. Infrastructure Gaps

| Gap | Severity | Detail |
|---|---|---|
| **High-Frequency Ingestion** | LOW | Current telemetry endpoint can handle wearable data. Redis + PostgreSQL are sufficient for <100 devices. At scale (>1000), need time-series DB (TimescaleDB) or batch ingestion. **Not a blocker for MVP.** |
| **BLE Relay Latency** | LOW | Phone-to-backend latency is ~200ms via HTTPS. Acceptable for panic button (target <2s end-to-end). |

---

## 4. CRITICAL RISKS / BLOCKERS

### RISK 1: `react-native-ble-plx` + Expo SDK 55 New Architecture
- **Risk Level: HIGH**
- Expo SDK 55 removed Legacy Architecture entirely. `react-native-ble-plx` may not support New Architecture yet (open issue #1322). 
- **Mitigation:** Test with EAS dev build immediately. If incompatible, use `expo-modules` to write a thin BLE native module, or downgrade to SDK 54 temporarily.

### RISK 2: Background BLE on Android
- **Risk Level: HIGH**
- Android aggressively kills background services. BLE scanning stops after ~10min in background. Wearable connection will drop.
- **Mitigation:** Use Android Foreground Service with persistent notification ("NISCHINT is protecting you"). This keeps BLE alive. Expo supports this via `expo-task-manager` + custom native module.

### RISK 3: BLE Reconnection Reliability
- **Risk Level: MEDIUM**
- BLE disconnects are frequent (range ~10m, walls, interference). If phone is in pocket, wearable may lose connection.
- **Mitigation:** Auto-reconnect with exponential backoff (1s → 2s → 4s → max 30s). Bond the device (not just pair) for faster reconnection. Show "wearable disconnected" warning on guardian dashboard.

### RISK 4: Battery Drain
- **Risk Level: MEDIUM**
- Continuous BLE scanning drains phone battery. 20Hz sensor streaming from wearable makes it worse.
- **Mitigation:** Use BLE notifications (push from wearable) instead of polling. Only scan when disconnected. Reduce sensor rate to 1Hz for heartbeat, event-driven for panic.

### RISK 5: False Positive Falls from Wearable
- **Risk Level: MEDIUM**
- Wearable IMU on wrist has different dynamics than phone in pocket. Current thresholds (2.7g impact, 60° orientation) may not work.
- **Mitigation:** Calibrate thresholds for wrist-mounted IMU. Add "wearable" flag to fall_detection_service.py to use different thresholds.

---

## 5. RECOMMENDED ARCHITECTURE

```
┌─────────────────────────────────────────────────────────────┐
│                     WEARABLE DEVICE                         │
│  [Panic Button] [IMU Sensor] [Heart Rate] [Battery]        │
│         │              │           │           │            │
│         └──── BLE GATT Characteristics ────────┘            │
└─────────────────────────┬───────────────────────────────────┘
                          │ BLE (Bluetooth Low Energy)
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                     MOBILE APP (Expo)                        │
│                                                             │
│  bleService.ts                                              │
│  ├── scan() → discover wearable                             │
│  ├── pair() → bond + persist MAC                            │
│  ├── subscribe() → listen to characteristics                │
│  │   ├── PANIC_CHAR → onPanicPress()                        │
│  │   ├── IMU_CHAR → onMotionData()                          │
│  │   ├── HR_CHAR → onHeartRate()                            │
│  │   └── BATTERY_CHAR → onBattery()                         │
│  └── reconnect() → auto-reconnect on disconnect             │
│                                                             │
│  wearableEventRouter.ts                                     │
│  ├── onPanicPress() → POST /api/wearable/event              │
│  │                  → trigger local SOS UI                   │
│  ├── onMotionData() → fallDetection.ts (shared pipeline)    │
│  ├── onHeartRate() → POST /api/wearable/telemetry (batch)   │
│  └── onBattery() → update local state + POST if low         │
└─────────────────────────┬───────────────────────────────────┘
                          │ HTTPS (POST)
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                     BACKEND (FastAPI)                        │
│                                                             │
│  /api/wearable/event  ←─── Panic / Fall / Inactivity        │
│  │                                                          │
│  wearable_event_service.py                                  │
│  ├── validate_device(device_token)                          │
│  ├── normalize_event(raw → system event)                    │
│  │   ├── button_press → emergency_engine.trigger_silent_sos │
│  │   ├── fall_data → fall_detection_service.report_fall     │
│  │   ├── inactivity → checkin_service (create check-in)     │
│  │   └── heart_anomaly → safety_alert SSE                   │
│  └── broadcast via event_broadcaster.py                     │
│                                                             │
│  Existing pipelines (ZERO CHANGES):                         │
│  ├── auto_escalation_engine.py → 60s failsafe              │
│  ├── sequential_escalation.py → voice calls → SMS blast     │
│  ├── push_service.py → FCM notifications                    │
│  └── event_broadcaster.py → SSE to guardians + operators    │
└─────────────────────────┬───────────────────────────────────┘
                          │ SSE / Push / Twilio
                          ▼
┌─────────────────────────────────────────────────────────────┐
│           GUARDIAN (Mobile) + COMMAND CENTER (Web)           │
│                                                             │
│  [Alert Banner] [EscalationTracker] [RiskOverlayMap]        │
│  [Wearable Status Widget] — connected/disconnected/battery  │
└─────────────────────────────────────────────────────────────┘
```

### Where validation happens:
1. **Mobile (bleService.ts):** Raw BLE data validation, debounce button press (prevent double-tap), filter noise
2. **Backend (wearable_event_service.py):** Device ownership verification, rate limiting, event deduplication, confidence scoring
3. **Backend (fall_detection_service.py):** 5-stage fall confidence pipeline (already built)

### Where escalation triggers:
- `wearable_event_service.py` → calls `emergency_engine.trigger_silent_sos()` → existing 60s failsafe → `sequential_escalation.intelligent_escalation()` → Twilio voice/SMS

---

## 6. BLE INTEGRATION PLAN (MOBILE)

### Library: `react-native-ble-plx`
- **Do we need to eject from Expo? NO**
- Expo SDK 55 supports custom native modules via **EAS Dev Builds** (you already use EAS). No ejection needed.
- Install: `npx expo install react-native-ble-plx` + config plugin in `app.json`

### Alternative if `react-native-ble-plx` fails New Architecture:
- `expo-ble` (Expo's own BLE module, if available for SDK 55)
- Or write a minimal Expo Module wrapping Android/iOS BLE APIs

### Implementation:

```typescript
// bleService.ts — Core BLE Service

import { BleManager, Device, Characteristic } from 'react-native-ble-plx';

// Standard BLE UUIDs
const PANIC_SERVICE_UUID = 'custom-uuid-here';  // Wearable-specific
const PANIC_CHAR_UUID = 'custom-uuid-here';
const IMU_SERVICE_UUID = 'custom-uuid-here';
const BATTERY_SERVICE_UUID = '0000180f-0000-1000-8000-00805f9b34fb';
const BATTERY_CHAR_UUID = '00002a19-0000-1000-8000-00805f9b34fb';

// Scanning
async function scanForWearables(onFound: (device) => void) {
  manager.startDeviceScan([PANIC_SERVICE_UUID], null, (error, device) => {
    if (device?.name?.startsWith('NISCHINT-')) onFound(device);
  });
}

// Pairing
async function pairDevice(deviceId: string) {
  const device = await manager.connectToDevice(deviceId, { autoConnect: true });
  await device.discoverAllServicesAndCharacteristics();
  // Bond for faster reconnection
  return device;
}

// Subscribe to panic button characteristic
async function subscribeToPanic(device: Device, onPress: () => void) {
  device.monitorCharacteristicForService(
    PANIC_SERVICE_UUID, PANIC_CHAR_UUID,
    (error, char) => {
      if (char?.value) onPress();  // Button pressed
    }
  );
}

// Auto-reconnect with exponential backoff
function setupAutoReconnect(deviceId: string) {
  manager.onDeviceDisconnected(deviceId, (error, device) => {
    let delay = 1000;
    const tryReconnect = async () => {
      try {
        await manager.connectToDevice(deviceId, { autoConnect: true });
      } catch {
        delay = Math.min(delay * 2, 30000);
        setTimeout(tryReconnect, delay);
      }
    };
    tryReconnect();
  });
}
```

---

## 7. API DESIGN REQUIRED

### `POST /api/wearable/register`
Register a wearable device after BLE pairing.
```json
// Request
{
  "device_mac": "AA:BB:CC:DD:EE:FF",
  "device_name": "NISCHINT-Band-001",
  "device_type": "panic_band",           // panic_band | smartwatch | pendant
  "firmware_version": "1.2.0"
}
// Response  
{
  "device_id": "uuid",
  "device_token": "secret-token-for-device-auth",
  "status": "paired"
}
```

### `POST /api/wearable/event`
Ingest a wearable event (panic press, fall, inactivity).
```json
// Request
{
  "device_token": "secret-token",
  "event_type": "panic_press",           // panic_press | fall_detected | inactivity | heart_anomaly
  "lat": 28.6139,
  "lng": 77.2090,
  "raw_data": {                           // Optional sensor payload
    "impact_g": 3.2,
    "heart_rate_bpm": 120,
    "battery_pct": 45
  },
  "timestamp": "2026-03-28T12:00:00Z"
}
// Response
{
  "status": "processed",
  "event_id": "uuid",
  "action_taken": "emergency_triggered",  // What pipeline was activated
  "escalation_id": "uuid"                 // If escalation was started
}
```

### `POST /api/wearable/telemetry` (Batch)
Periodic telemetry upload (heart rate, battery, motion summary).
```json
// Request
{
  "device_token": "secret-token",
  "metrics": [
    { "type": "heart_rate", "value": 72, "timestamp": "..." },
    { "type": "battery", "value": 85, "timestamp": "..." },
    { "type": "steps", "value": 1200, "timestamp": "..." }
  ]
}
// Response
{ "status": "ok", "ingested": 3 }
```

### `GET /api/wearable/status`
Get wearable device status for the current user.
```json
// Response
{
  "device_id": "uuid",
  "device_name": "NISCHINT-Band-001",
  "is_connected": true,
  "battery_pct": 85,
  "last_seen": "2026-03-28T12:00:00Z",
  "firmware_version": "1.2.0"
}
```

### `DELETE /api/wearable/unpair`
Unpair and remove wearable device.

---

## 8. EVENT MAPPING

| Wearable Event | System Event | Pipeline Triggered | SSE Event Type |
|---|---|---|---|
| `button_press` (single) | `emergency_triggered` | `trigger_silent_sos()` → 60s failsafe → sequential escalation | `emergency_triggered` |
| `button_press` (double) | `checkin_help` | `checkin_service.create_checkin(status="help")` | `checkin_help` |
| `button_press` (long hold 3s) | `fake_call_incoming` | `fake_call_service.trigger()` | `fake_call_incoming` |
| `fall_detected` (IMU) | `fall_detected` | `fall_detection_service.report_fall()` → 30s auto-SOS | `fall_detected` |
| `inactivity` (>15min no motion) | `checkin_pending` | `checkin_service.create_checkin()` → 5min expiry | `checkin_pending` |
| `heart_rate_anomaly` (>160 or <40 bpm) | `safety_alert` | SSE broadcast + push notification | `safety_alert` |
| `low_battery` (<15%) | `wearable_low_battery` | SSE broadcast to guardians | `wearable_low_battery` |
| `disconnected` (BLE lost) | `wearable_disconnected` | SSE broadcast + push notification after 5min | `wearable_disconnected` |
| `reconnected` (BLE restored) | `wearable_connected` | SSE broadcast (clear warning) | `wearable_connected` |

---

## 9. EXACT FILES TO CREATE / MODIFY

### NEW Files:
| File | Purpose |
|---|---|
| `mobile/services/bleService.ts` | BLE scanning, pairing, characteristic subscriptions, auto-reconnect |
| `mobile/services/wearableEventRouter.ts` | Routes BLE events to correct handlers (panic → SOS, fall → fallDetection, etc.) |
| `mobile/stores/wearableStore.ts` | Zustand store: connected, battery, deviceId, deviceName |
| `mobile/components/WearableStatus.tsx` | UI widget showing wearable connection state + battery |
| `mobile/app/(tabs)/wearable.tsx` | Pairing screen: scan, select, pair, manage device |
| `backend/app/api/wearable.py` | `POST /event`, `POST /register`, `GET /status`, `POST /telemetry`, `DELETE /unpair` |
| `backend/app/services/wearable_event_service.py` | Event normalization + routing to existing pipelines |
| `backend/app/models/wearable_device.py` | `WearableDevice` model (user_id FK, device_mac, battery, etc.) |
| `backend/app/models/wearable_event.py` | `WearableEvent` model (device_id FK, event_type, raw_data, etc.) |

### MODIFY (Existing Files):
| File | Change |
|---|---|
| `mobile/app.json` | Add `react-native-ble-plx` plugin + `bluetooth-central` UIBackgroundModes |
| `mobile/package.json` | Add `react-native-ble-plx` dependency |
| `mobile/app/(tabs)/home.tsx` | Add `<WearableStatus />` widget + handle `wearable_*` SSE events |
| `mobile/hooks/useGuardianSSE.ts` | Add `wearable_*` event types to `EVENT_TYPES` array |
| `backend/app/api/main.py` | Register `wearable_router` |
| `backend/app/services/event_broadcaster.py` | Add `broadcast_wearable_event()` convenience method |
| `backend/app/services/fall_detection_service.py` | Add `source="wearable"` param with wrist-calibrated thresholds |
| `backend/app/services/push_service.py` | Add `WEARABLE_PANIC` push notification type |
| `backend/app/services/notification_formatter.py` | Add wearable-specific push messages |
| `backend/app/services/dynamic_risk_engine.py` | Add wearable signal weight to risk scoring |
| `frontend/src/components/command-center/` | Add WearableStatusPanel for operator dashboard |

---

## 10. IMPLEMENTATION PLAN

### Phase 1: MVP — Panic Button (10-12 days)
| Day | Task |
|---|---|
| 1-2 | Install `react-native-ble-plx`, configure `app.json`, verify EAS build with BLE |
| 3-4 | Build `bleService.ts`: scan, pair, subscribe to panic characteristic, auto-reconnect |
| 5-6 | Build backend `wearable.py` API + `wearable_event_service.py` + DB models |
| 7-8 | Wire panic_press → `trigger_silent_sos()` → full escalation chain |
| 9 | Build `wearable.tsx` pairing screen + `WearableStatus.tsx` widget |
| 10 | Integration test: BLE → panic → SOS → Twilio call → guardian alert |
| 11-12 | Edge cases: reconnection, background mode, battery alerts, deduplication |

**Deliverable:** Child presses wearable panic button → guardian gets call within 5 seconds.

### Phase 2: Motion Detection + Fall (8-10 days)
| Day | Task |
|---|---|
| 1-3 | Subscribe to wearable IMU characteristic, stream to `fallDetection.ts` pipeline |
| 4-5 | Calibrate fall thresholds for wrist-mounted sensor (different from phone-in-pocket) |
| 6-7 | Add inactivity detection (>15min no motion → check-in) |
| 8-9 | Heart rate monitoring (if wearable supports): anomaly detection + alert |
| 10 | Testing: real fall simulations, false positive tuning |

**Deliverable:** Wearable detects falls with <5% false positive rate.

### Phase 3: AI Sensor Fusion (12-15 days)
| Day | Task |
|---|---|
| 1-4 | Fuse wearable sensors + phone GPS + voice distress + location risk into unified risk score |
| 5-8 | ML model for personalized risk baseline (per-child) using behavioral patterns |
| 9-11 | Predictive alerts: "unusual heart rate + unexpected location + late hour → elevated risk" |
| 12-15 | Command center wearable dashboard + historical analytics |

**Deliverable:** AI-powered risk scoring that combines all sensor sources.

---

## 11. TESTING STRATEGY

### Panic Button Test
1. Pair wearable → press button → verify `emergency_triggered` SSE within 2s
2. Press button while BLE disconnected → verify reconnect + delayed trigger
3. Double-press within 500ms → verify deduplication (only 1 SOS)
4. Press while phone in background → verify foreground service handles it

### BLE Disconnect Test
1. Move wearable out of range → verify `wearable_disconnected` SSE after 5min
2. Return to range → verify auto-reconnect within 30s
3. Kill app → reopen → verify auto-reconnect to bonded device
4. Airplane mode on phone → verify graceful degradation

### Background Scenarios
1. Phone locked, screen off → press panic → verify SOS triggers
2. App in background for 1 hour → press panic → verify still works
3. Phone reboot → verify BLE service restarts automatically

### False Positive Prevention
1. Drop wearable on table → should NOT trigger fall (below threshold)
2. Vigorous exercise → should NOT trigger SOS
3. Child takes off wearable → should trigger "disconnected" after 5min, NOT panic
4. Low battery → should warn guardian, NOT trigger SOS

---

## 12. FINAL VERDICT

### Can we build wearable MVP in 30 days? **YES**

Phase 1 (Panic Button MVP): **10-12 days** — this is the fastest path to launch.

### FASTEST PATH TO LAUNCH:
1. **Day 1:** Verify `react-native-ble-plx` works with Expo SDK 55 New Architecture (EAS dev build test)
2. **Day 2-4:** `bleService.ts` + pairing screen
3. **Day 5-7:** Backend wearable APIs + wire to existing SOS/escalation
4. **Day 8-10:** Integration testing on physical device
5. **Day 11-12:** Edge cases + polish

### WHY 72% READY:
- The **hard problems** are solved: escalation engine, SSE broadcasting, fall detection, risk scoring, guardian notifications, Twilio voice/SMS
- What's missing is **BLE plumbing** (scanning, pairing, characteristic subscription) — well-documented, standard BLE programming
- The backend needs only a thin **normalization layer** between wearable events and existing pipelines
- Zero changes to the escalation engine, zero changes to SSE, zero changes to push notifications

### THE ONE BLOCKER TO VALIDATE FIRST:
`react-native-ble-plx` + Expo SDK 55 New Architecture compatibility. **Test this on Day 1 before committing to the BLE library.**
