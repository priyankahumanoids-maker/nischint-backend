# NISCH-008 Mobile WebRTC Sprint — Prerequisites & Decisions

> Generated: Feb 2026, end of NISCH-008 backend + Phase C sprint.
> Read this BEFORE starting the WebRTC mobile sprint so there's no
> archaeology phase. Backend signalling layer is already complete
> and live (17/17 tests against Neon, migration `dk1a2b3c4dz01` applied).

---

## ✅ What's already shipped (no work needed)

- `safety_incidents` lifecycle state machine + ESCALATED auto-offer hook
- `stream_sessions` table (`offered → connecting → live → ended | declined`)
- `POST /api/stream/initiate`, `GET /api/stream/{id}/join`,
  `POST /api/stream/{id}/accept`, `POST /api/stream/{id}/end`,
  `GET /api/stream/{id}`
- `WS /api/stream/{id}/signal` — opaque per-stream relay
- Twilio NTS ICE-server credential generation with STUN-only fallback
- `auto_decline_stale_offers` wired into the scheduler (10s tick)
- `stream` block on `GET /api/incidents/{id}/timeline` for forensic replay
- `StreamRecordingChip.tsx` mobile component (uses `expo-audio`)
- 19 backend tests covering the above (17 streaming + 2 timeline)

---

## 📦 Mobile environment snapshot (Feb 2026)

| Item | Version | Notes |
|------|---------|-------|
| `expo` | `~55.0.5` | SDK 55 |
| `react-native` | `0.83.2` | RN 0.83 (Expo SDK 55 default) |
| `expo-audio` | `~55.0.14` | already used for recording + TTS playback |
| `expo-router` | (in deps) | file-based routing |

**Currently registered Expo config plugins** (`/app/mobile/app.json` `expo.plugins`):
1. `expo-router`
2. `expo-secure-store`
3. `expo-location`
4. `expo-notifications`
5. `expo-task-manager`
6. `expo-audio`
7. `expo-asset`

**Not yet installed (the WebRTC sprint must add):**
- `react-native-webrtc` (latest compatible with RN 0.83 / Expo SDK 55)
- `@config-plugins/react-native-webrtc` (the Expo config plugin)
- `@react-native-community/slider` (only needed if scrub UX upgrades
  beyond the no-dep progress bar in `StreamRecordingChip.tsx`)

---

## 🧱 SDK 55 + react-native-webrtc compatibility check

`react-native-webrtc` `124.0.5+` supports React Native 0.76+, which
includes RN 0.83 used here. Verify before installing:
```bash
yarn info react-native-webrtc peerDependencies
```

The Expo config plugin is community-maintained:
```bash
yarn add @config-plugins/react-native-webrtc
```
After install, append to `app.json` `expo.plugins`:
```json
[
  "@config-plugins/react-native-webrtc",
  {
    "cameraPermission": "Allow Nischint to access your camera during emergencies",
    "microphonePermission": "Allow Nischint to access your microphone during emergencies"
  }
]
```

> Reasoning lock: don't add the camera plugin until the *audio*
> happy path is verified end-to-end on an EAS dev build. Microphone
> alone is enough for v1.

---

## 🛡️ Permissions to add to `app.json`

iOS (`expo.ios.infoPlist`):
- `NSMicrophoneUsageDescription` — "Nischint streams audio to your
  guardians during emergencies."
- `NSCameraUsageDescription` — only when video lands (Phase 2)

Android (`expo.android.permissions`):
- `RECORD_AUDIO`
- `MODIFY_AUDIO_SETTINGS`
- `INTERNET` (already present via Expo defaults)

These do NOT need to be added until the WebRTC sprint actually
installs `react-native-webrtc` — premature permission requests
spook reviewers.

---

## 🧪 EAS build profile baseline

Recommended `eas.json` `development` profile (no WebRTC yet, just
the current native deps):
```json
"development": {
  "developmentClient": true,
  "distribution": "internal",
  "ios": { "resourceClass": "m-medium" },
  "android": { "buildType": "apk" }
}
```

Bake an EAS dev build with the *current* native deps FIRST, run the
24h soak, promote to TestFlight. Only THEN add `react-native-webrtc`
in a separate sprint — that way a crash on WebRTC won't be confused
with anything from NISCH-006/007/009/Phase C.

---

## 🔌 Mobile pieces the WebRTC sprint will build

Already scaffolded by backend, awaiting mobile counterparts:

| Component | Purpose | API surface ready? |
|-----------|---------|--------------------|
| `useWebRTC.ts` hook | RTCPeerConnection lifecycle | ✅ Twilio ICE returned by `/join` |
| `useStreamSignaling.ts` hook | WebSocket signaling | ✅ `WS /api/stream/{id}/signal` |
| `StreamBanner.tsx` | Child-side non-blocking offer banner | ✅ `stream_offer` SSE + `/accept` |
| `StreamListenerScreen.tsx` | Guardian audio listener with waveform | ✅ `/join` returns ICE + ws_url |
| Auto-accept gate (`confidence > 0.90`) | Skip the banner for high-confidence distress | ✅ `confidence` is on `safety_incidents` |
| Stream-end → auto-navigate | Pop back to feed on `ended` event | ✅ `stream_state` SSE wired |

The signalling WS is **opaque** — server forwards `offer`/`answer`/
`ice_candidate`/`end_stream` between peers without inspecting SDP.
That keeps the mobile side dead-simple: standard `RTCPeerConnection`
flow, no custom protocol layer to learn.

---

## 🚨 Blockers / gotchas to expect

1. **EAS native build time.** First `react-native-webrtc` build will
   take 25-40 minutes for both platforms. Plan the sprint with that
   wall-clock cost in mind.
2. **Symmetric NAT on Jio/Airtel** — direct P2P will fail for ~80%
   of Indian mobile users. TURN relay (Twilio NTS) is mandatory in
   prod. The fallback STUN-only servers in `stream_initiator.py`
   exist for dev resilience, NOT prod traffic.
3. **iOS background audio.** `RTCPeerConnection` audio in background
   requires the `audio` background mode in `app.json`
   (`expo.ios.infoPlist.UIBackgroundModes`). Without it, iOS will
   silence the stream within ~3s of screen lock.
4. **Recording uploader.** Backend's `recording_url` column is
   currently null on every ended stream. The WebRTC sprint must
   add either:
   - On-device recorder → S3/R2 upload on stream end, OR
   - Server-side recording via mediasoup/pion (heavier infra cost)
   The on-device approach keeps server costs down and works even
   when TURN relay drops.

---

## 🗂 Test bar for the WebRTC sprint (not just code)

Before merging the WebRTC sprint, the following must all pass:
- [ ] EAS dev build completes for both iOS + Android
- [ ] Audio call between two physical devices on different
      Jio/Airtel SIMs (forces TURN relay)
- [ ] Audio call survives Wi-Fi → 4G handover (ICE restart)
- [ ] Stream survives screen lock for ≥30s
- [ ] `[STREAM_WS]` logs show no token re-validation storm
- [ ] `safety_incident_events` correctly logs `stream` actor entries
      from the relay observers
- [ ] Recording upload completes within 10s of `end_stream` for a
      90s audio capture
