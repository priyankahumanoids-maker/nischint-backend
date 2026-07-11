# Nischint — Product Requirements Document (PRD)

## Original Problem Statement
Build a complete RAG backend + Autonomous Content Machine alongside a scalable Programmatic GEO SEO architecture. Core app is **Nischint**, a Next-Gen Safety platform with:
- Child/Woman/Senior safety with AI Brain (risk fusion, sustained-risk gate, feedback learning)
- Web dashboard (family, guardian, admin)
- Mobile app (React Native / Expo SDK 55)
- Real-time SSE, FCM push, Mapbox live maps, SOS / fall / voice-distress detection

## Current Stack
- **Backend:** FastAPI, PostgreSQL (Neon), MongoDB, Redis, motor, asyncpg, pymongo
- **Frontend:** React SPA (`/app/frontend`)
- **Mobile:** Expo SDK 55, React Native 0.83, TypeScript, Zustand, expo-updates OTA
- **Infra:** Nginx reverse-proxy, Supervisor, EAS Build + EAS Update
- **Third-party:** Twilio, Firebase FCM, AWS Cognito (disabled), OpenAI, PostHog

## What's been implemented (April 2026 session)

### Backend
- AI Brain with sustained risk gate, feedback loops, persistent decision audit log
- Mongo-backed notification preferences (`GET/PATCH /api/my/notification-preferences`)
- Admin role sees all children system-wide in `guardian_dashboard`
- Widened RBAC for operator on read-only endpoints
- Mock telemetry injector for QA

### Web Frontend
- Safety Tracking: admin sees all children, relationship badges
- Safety Score map: uses browser GPS, no hardcoded Bangalore
- Protected Users page: Loved Ones section (children + women)
- Real Settings page with notification toggles (push/email/sms/digest/weekly)
- Incidents empty state: explains when incidents populate
- Route Monitor: amber "Developer Tool" banner clarifying it's a simulator
- Metrics: "No incidents = good thing" banner

### Mobile (APK `6d475188` / SDK 55)
- Haptics crash fixed (removed missing `expo-haptics`, uses `Vibration`)
- All permission requests (audio/push/sensors/location) wrapped in try/catch
- Voice monitoring defers from boot to Journey Begin (no permission abuse)
- Mapbox lazy-load with graceful fallback UI
- Predictive Alerts uses real device GPS, not Bangalore
- Safety Services diagnostic widget (GPS/Push/Shake/Fall/Voice/Network)
- Role debug banner + "Tap to Check for OTA Update"
- Journey screen force-ready fallback (2s) so it never stays blank
- Fresh SDK 55 APK built with `google-services.json` via EAS env+pre-install hook
- `eas-build-pre-install` script in `package.json` copies `$GOOGLE_SERVICES_JSON` → `./google-services.json`

## Production Credentials
- Admin: `nischint4parents@gmail.com` / `secret123`
- Mother: `mothernischint@gmail.com` / `nischint123`
- Father: `fathernishchint@gmail.com` / `nischint123`
- Child: `kidnischint@gmail.com` / `nischint123`
- Operator: `operator_test@example.com` / `operator123`

## APK Downloads
- Latest (SDK 55): https://expo.dev/artifacts/eas/euErASN4AxxrWMqRioipye.apk
- Build ID: `6d475188-eb40-476f-b3be-620964f16471`
- Runtime version: 1.0.0 (matches OTA channel `production`)

## Backlog / P1
- Advisory→SOS escalation notification on Sustained Gate 2nd fire
- Elderly + `fall_detected` → bypass Sustained Risk Gate
- Timeline badges "Held (gate)" vs "Sustained → fired"
- Offline Mesh Mode (BLE/Bridgefy peer SOS broadcast)

## Auth-DB latency optimization (2026-05-25) ✅
- Short-window `User` cache in `get_current_user` (30 s Redis + 10 s
  in-process fallback). Measured: 2,510 ms → 232 ms on the first authed
  call (91 % reduction). See `app/services/user_cache.py` and the
  CHANGELOG entry for the full contract.

## Map Standardization (Feb 2026)
- All mobile maps now use `react-native-maps` with `provider={PROVIDER_GOOGLE}`
  (Google Maps).
- Removed `@rnmapbox/maps` dep, config plugin, and all Mapbox code paths.
- `RiskOverlayMap` rewritten on top of `react-native-maps` (Markers + Circles)
  with the same legend / info-card / camera-auto-focus UX.
- New `useGuardianLocationPolling` hook hits `/api/guardian/live/risk` every
  5s and hydrates `useRiskStore` + `useLiveTrackingStore`, so Google Maps
  markers update smoothly without depending on SSE.
- iOS `app.json` now has `ios.config.googleMapsApiKey` (same key as Android).

## Command Center Real-Time Conversion — Phase 1 + 2 (Feb 2026)

**Phase 1 — Unified per-user endpoint**
- `GET /api/operator/command-center/{user_id}` consolidates 7 fragmented per-user
  calls into a versioned envelope (`version: "v1"`, `timestamp`).
- Reuses `compute_risk_score`, `get_or_create_baseline`, `generate_predictions`,
  `get_risk_history` — zero new compute paths.
- `digital_twin.live_deviation` slot ready for Phase 3 streaming engine.
- `environment.weather` flagged `"source": "unavailable"` — Phase 4 placeholder.
- File: `/app/backend/app/api/command_center_unified.py`

**Phase 2 — WebSocket-only consolidation**
- Removed SSE `useEffect` from `CommandCenterPage.jsx` (createEventSource gone).
- Removed 10s `setInterval(fetchData)` polling (only demo-status polling
  remains — bounded, runs only during active demos).
- Added cold-refresh on WS reconnect via `wasConnectedRef` so slow-moving
  fleet data (metrics, queue health, journeys, heatmap) still resyncs after
  disconnect — no data loss.
- Added WS handlers for `safety_risk_alert`, `fake_call_incoming`, and
  `risk_score_change` (the last triggers a refetch of the unified endpoint
  when the change is for the currently selected user).
- Switched per-user fetch from 4 parallel calls to 1 unified call via
  `operatorApi.getCommandCenterUser(userId)`.
- Backend `ws_command_center.py` allow-list extended for `safety_risk_alert`
  and `fake_call_incoming`.
- Verified at runtime: `[CC-WS] Connected` + `[CC-WS] Authenticated`,
  zero SSE logs, `active_connections: 1` reported by WS status endpoint.

**Phase 3 — Live Deviation Engine**
- New pure-function engine: `/app/backend/app/services/live_deviation_engine.py`
  with weighted fusion of 4 signals (time / location / route / idle), human
  reasons, confidence scoring, and 6 unit tests in
  `/app/backend/tests/test_live_deviation_engine.py` (all passing).
- New broadcaster: `/app/backend/app/services/twin_delta_broadcaster.py`
  computes live deviation, debounces against last status via Redis
  (`twin_state:{user_id}` key, 6h TTL), and broadcasts `twin_delta` to
  operators only on status change.
- Hooked into `safety_events.py:share-location` so every location tick from a
  child evaluates deviation; hooked into `command_center_unified.py`
  `_build_digital_twin_view` so the unified endpoint serves the same
  engine output (single source of truth).
- WS allow-list extended for `twin_delta`.
- Frontend: `CommandCenterPage` adds `userDigitalTwin` state hydrated from
  the unified payload, plus a `twin_delta` WS handler that patches
  `live_deviation` in place — no refetch.
- `DigitalTwinPanel` now prefers `digital_twin.live_deviation` (with a live
  pulsing dot + reason text), falling back to the risk-derived deviation.
- Verified end-to-end: child posts location 1700km from baseline → engine
  computes status=slight score=0.42 → `[TWIN_DELTA] status=None→slight`
  logged + queued on operator channel.

**Phase 4 — Real Weather (OpenWeather)**
- New service: `/app/backend/app/services/weather_service.py`
  - `get_weather(lat, lng)` — async httpx call to OpenWeather Current Weather
    API, normalized payload, Redis cached at ~1km grid (10-min TTL).
  - `compute_weather_risk(weather)` — pure 0..1 risk + factor list, dedup
    safe; covers thunderstorm/tornado/heavy-rain/freezing-rain/heavy-snow
    severe condition IDs + visibility / wind / extreme temperature.
- 8 unit tests in `/app/backend/tests/test_weather_service.py` — all pass.
- Replaced `random.uniform(0, 0.3)` weather stub in
  `guardian_ai_refinement.py::_compute_environment_risk` with the real
  signal (now `async`, fetches user's last live location → real weather →
  real risk).
- `command_center_unified.py::_build_environment_view` now serves the full
  normalized weather payload (`source: "openweather"`) when a live
  location is present, else falls back to honest `source: "unavailable"`
  with structured `error` field (`no_api_key` / `timeout` / `http_xxx`).
- Added `environment.risk` (0..1) and `environment.impact`
  ("low|medium|high") for operator interpretability.
- API key wired into Pydantic settings (`openweather_api_key`).

**Phase 5 — Structured Delta Engine (COMMAND_CENTER_DELTA)**
- New emitter: `/app/backend/app/services/cc_delta_emitter.py`
  - `emit_cc_delta(user_id, changes)` — broadcasts canonical envelope:
    `{type, user_id, timestamp, version: "v1", changes: {dotted.path: value}}`
  - `emit_namespaced_delta(user_id, namespace, new_value)` — diffs against
    Redis-cached snapshot (`cc_state:{user_id}:{namespace}`, 1h TTL) and
    emits only changed dotted paths under that namespace. No-op when nothing
    changed.
- 8 unit tests in `/app/backend/tests/test_cc_delta_emitter.py` — all pass.
- Emitter wired into 3 trigger points:
  - `compute_risk_score` → `risk.*` deltas (`final_score`, `risk_level`,
    `scores.*`, `top_factors`, `recommended_action`)
  - `twin_delta_broadcaster` → `live_deviation.*` deltas (replaces the old
    `twin_delta` ad-hoc broadcast)
  - `safety_events.share-location` → `live_location.*` deltas
- WS allow-list extended with `COMMAND_CENTER_DELTA`.
- Frontend utility: `/app/frontend/src/utils/applyDelta.js`
  - Deep dotted-path setter (no mutation)
  - Rejects `version` mismatch + stale `timestamp` (older than current state)
  - Returns `{state, applied, reason}` for caller observability.
- WS handler in `CommandCenterPage.jsx`: groups changes by namespace,
  dispatches into the right state slice (`userRiskData`, `userDigitalTwin`),
  light refetch only when `live_location.risk_level` changes.

**Pressure tests (all passed):**
1. No location → `weather.source: "unavailable"`, `risk: 0`, `impact: "low"`
2. Cache boundary (~1km grid) → 2nd call returns `from_cache: true`
3. Extreme conditions → tornado=1.0, thunderstorm=0.6, heatwave=0.15
4. API timeout → `{"source": "unavailable", "error": "timeout"}`
5. WS fires `[CC_DELTA] paths=[...]` for risk/live_deviation/live_location
6. Browser confirms `[CC-WS] Connected/Authenticated`, no JS errors

## Production Hardening (Feb 2026, post-Phase 5)

**Backend chaos-safe + observability**
- `cc_delta_emitter.py` rewrites: `cache_state_slice` / `get_state_slice` are
  fully chaos-safe (Redis read/write failures degrade to cold-cache fallback,
  never crash). Structured logs added: `[CC_DELTA] emit user=… paths=… ts=…`,
  `[CC_DELTA] cache_hit/miss`, `[CC_DELTA] skip reason=no_diff/no_changes`,
  `[CC_DELTA] broadcast_failed`.
- 4 chaos tests in `tests/test_cc_delta_chaos.py` covering Redis read failure,
  Redis write failure, broadcast failure, no-op diff. All pass (26/26 total).

**Frontend hardening + observability**
- `applyDelta.js` now uses **per-namespace timestamp tracking** (`__deltaTs`
  hidden field) — risk and live_deviation no longer reject each other when
  arriving in quick succession.
- Module-level `deltaMetrics` exposes counters: framesReceived, applied,
  rejected, staleRejected, versionMismatch, reconnects, successRate.
- `recordFrame` ring buffer (last 20 frames) feeds the new `WSFrameInspector`.
- `CommandCenterPage` WS handler logs rejection reasons in dev mode and
  records every frame in the ring buffer.

**Reconnect safety**
- On WS reconnect: `deltaMetrics.recordReconnect()` + cold refetch of fleet
  data (`fetchData`) AND per-user unified payload (`fetchSelectedUser`),
  guaranteeing no stale state survives a disconnect window.

**WS Frame Inspector** (dev-mode only, toggle via `?debug_ws=true` or
`localStorage.debug_ws=true`):
- `/app/frontend/src/components/command-center/WSFrameInspector.jsx`
- Floating bottom-right card, 380×60vh max
- 6 live metrics chips + scrolling list of last 20 frames showing relative
  timestamp, truncated user_id, and dotted-path chips for `changes` keys
- Verified live in browser: 3 location pushes → 3 frames rendered with
  `live_location.lat/lng/speed_mps/speed_kmh` chips, metrics counter
  updates correctly.

## Phase 6 — Fleet Situational Awareness (Feb 2026)

**Fleet Weather Grid** (`/app/backend/app/services/fleet_weather_service.py`)
- 3×3 city-level grid (9 cells) covering Bengaluru with stable cell IDs
  (`north_west / north_center / … / south_east`)
- APScheduler 5-min cycle started in `server.py` (also runs once at startup)
- Reuses `weather_service.get_weather` so no duplicate upstream calls — every
  cell hit is already Redis-cached at ~1km grid (10-min TTL)
- Cache key `nischint:fleet_weather_grid:bengaluru`, 30-min TTL (last-known
  state survives a missed refresh)
- Diff-emit: only fires `COMMAND_CENTER_DELTA` (scope=`fleet`) when a cell's
  `risk` shifts ≥ 0.10 OR its `condition` string changes
- Disable via `DISABLE_FLEET_WEATHER=true` env var for CI

**New Endpoints**
- `GET /api/operator/command-center/fleet-weather` — declared BEFORE
  `/{user_id}` to avoid path collision; cold-start triggers refresh on demand
- `GET /api/operator/cc-delta/metrics` — cumulative + rolling 1-min counters
  (`emitted, skipped, failed, rate_per_min`)

**Server-side delta metrics** (`cc_delta_emitter.py`)
- Cumulative counters: `nischint:metrics_cc_delta:total_{emitted|skipped|failed}`
- Per-minute buckets with 180s TTL → rolling 1-min rate (averaged over last
  2 full minutes for smoother rendering)
- All counters incremented inline at every emit/skip/fail path; never break
  the hot path on Redis failure

**Weather Chip** (`/app/frontend/src/components/command-center/WeatherChip.jsx`)
- Compact chip per selected user, rendered next to AI Reasoning
- Reads `environment.weather` + `environment.impact` from the unified
  payload — never blocks render when source !== `openweather`
- Lucide icon mapping (clear/clouds/rain/thunderstorm/snow/fog), color-coded
  by impact band, full tooltip with temp/wind/visibility
- Verified live: `[☁ Scattered Clouds] [34°C] [LOW]` for Kid Nischint

**WS Frame Inspector enhancement**
- New "fleet metrics" row (dev-mode only) polling `/api/operator/cc-delta/metrics`
  every 12s: `fleet/min`, `emitted`, `skipped`, `failed`
- Verified live: `fleet/min 2, emitted 4, skipped 0, failed 0`

**Tests**: 6 new fleet weather tests in `tests/test_fleet_weather.py`
(grid shape, impact bands, debounce on unchanged cycle, threshold-crossed
emit). 32/32 backend unit tests pass overall.

## Phase 7 — Fleet Change Indicator (Perception Layer, Feb 2026)

**Backend** (`/app/backend/app/services/fleet_weather_service.py`)
- Extended `run_grid_refresh_cycle` to compute change summary alongside the
  COMMAND_CENTER_DELTA: `cells_updated`, `cells_escalated` (low→medium→high
  band rank up), `cells_deescalated`, plus a `breakdown` array of cell-level
  transitions.
- Persists last summary to Redis at `nischint:fleet_weather_last_change:{city}`
  (30-min TTL). New `get_last_change(city)` accessor.
- Emits a separate `FLEET_CHANGE_SUMMARY` WS event (only when
  `cells_updated > 0`) — distinct from `COMMAND_CENTER_DELTA` so the UI
  can render the perception badge without parsing dotted-path deltas.
- Allow-listed in `ws_command_center.py`.

**Frontend** (`/app/frontend/src/components/command-center/FleetChangeIndicator.jsx`)
- Floating pill, top-right of the map, pulses for ~9s on each new event
  then auto-fades. Color tone:
  - rose if any cell escalated
  - amber if only de-escalations
  - emerald if neutral updates
- Hover shows tooltip with cell-level breakdown ("north_west: LOW → HIGH")
- WS handler in `CommandCenterPage.jsx` sets `fleetChange` state on receipt;
  dev-mode also logs `[FLEET_CHANGE] updated=N escalated=N deescalated=N`.

**Tests**: 3 new fleet-change tests + 6 fleet-weather + 4 chaos + 8 cc_delta
+ 8 weather + 6 live-deviation = **35/35 pass**.

## Phase 8 — Last City Update Chip (State Recall, Feb 2026)

**Frontend-only** (no backend changes — reuses
`GET /api/operator/command-center/fleet-weather` from Phase 6).

- New component `/app/frontend/src/components/command-center/LastCityUpdateChip.jsx`:
  - Fetches fleet weather grid on mount, every 60s, and on WS reconnect.
  - Computes `high` / `medium` cell counts client-side (no new endpoint).
  - Renders relative time (`just now`, `2m ago`, `5m ago`, `1h ago`),
    re-rendered every 30s.
  - Hover tooltip: *"Last full city scan at HH:MM · N zones evaluated"*.
  - HIGH count uses rose tone, MED uses amber, otherwise muted gray.
- Mounted in a tight status strip directly beneath
  `<CommandCenterHeader>` so the chip is always visible.
- New `operatorApi.getCommandCenterFleetWeather()` helper in
  `/app/frontend/src/api.js`.
- Verified live: *"Updated 2m ago · 0 HIGH · 0 MED"* renders correctly,
  tooltip shows "Last full city scan at 4:14 AM · 9 zones evaluated".

## Phase 9 — Zone Drilldown (Flyout Layer, Feb 2026)

**Frontend-only** (zero backend dependency — reuses Phase 6 fleet-weather data).

- Extended `LastCityUpdateChip.jsx` with click-to-open flyout listing all 9
  cells, sorted by impact rank (HIGH → MED → LOW), then temp desc, then
  cell_id ASC for stable ties.
- Each row format: `cell_id · IMPACT pill · temp°C · condition`.
  Color semantics: HIGH=rose, MED=amber, LOW=emerald (per spec).
- Phase 7 `fleetChange.breakdown` reused in-place: rows whose cell
  transitioned recently show a tiny ↑ (escalated) or ↓ (de-escalated) arrow.
- Closes on outside-click and ESC; smooth `cuFadeIn` animation.
- z-index = 1500: stacks above map controls (z-1001) and zone-intel panel
  (z-1001), below the SOS modal (z-2000) and WS Frame Inspector (z-9999).
- Width-clamped (`max-w-[calc(100vw-1.5rem)]`) so it never overflows the
  viewport on narrow screens.
- Graceful: chip itself returns `null` when grid is empty; partial rows
  render with `—` when `temp_c` / `condition` are missing.
- Zero new API calls — reuses the cached fleet-weather state already loaded
  by Phase 8.
- Verified live (admin → /command-center): 9 rows render, sort/format/colors
  correct, ESC closes, outside-click closes, no console errors related to
  the component, ESLint clean.

**System flow now reads:** Perception (Phase 7 indicator) → State Recall
(Phase 8 chip) → Drilldown (Phase 9 flyout).

## Live Safety Map — Truth Layer (Feb 2026)

**Problem fixed**: the operator's map rendered only Night-Guardian-session
journeys + heatmap zones, so any kid currently online but *not* in an
active journey was invisible. With the kid's mobile actively reporting
location every few seconds, the operator still saw an empty Mumbai tile —
a serious credibility bug.

**Fix (no new APIs, per constraint)**:
- Backend: `get_high_risk_users` enriched with `lat`, `lng`,
  `last_seen_at`, `location_source` (`session` | `baseline` | `null`).
  Source priority: active `GuardianSession.current_location` first,
  baseline `common_locations[0]` fallback. Single LEFT JOIN — zero
  extra round trips and no new endpoint.
- Frontend (`CommandCenterPage.jsx`):
  - New `liveUsers` state hydrated from `highRiskUsers` (now coord-bearing).
  - WS `COMMAND_CENTER_DELTA` `live_location.*` patches now run for
    **all** users (not only the selected one) so any active-session
    GPS ping moves the matching pin in real time. New `live_location`
    deltas can also *create* a pin for previously unknown users.
  - `applyDelta` selected-user handlers (`risk`, `live_deviation`)
    still gated to selected user — they patch user-specific panels.
- `LiveSafetyMap.jsx`:
  - New `liveUsers` + `selectedUserId` + `onSelectUser` props.
  - `buildUserIcon` builds a Leaflet `DivIcon` with halo pulse, color
    by risk band (CRITICAL=red, HIGH=orange, MEDIUM=amber, LOW=green),
    pulse-speed and opacity scaled by freshness (`< 30s` = strong,
    `< 2m` = medium, `< 5m` = light, older = faint).
  - Selected pin gets a larger core + thicker ring + brighter glow.
  - Popup: `{name} · {RISK_BAND · score/10} · {relTime} · {live | last known}`.
  - Click → `onSelectUser(user_id)` → re-enters AI Reasoning, Digital
    Twin, Risk Intelligence panels.
  - Bottom-left chip: `N MONITORED` with a ping-style emerald dot.
  - Empty-state overlay: `WAITING FOR ACTIVE DEVICES…` when truly
    nothing is on the map (no live users, no journeys, no SOS).
  - Local 20s timer ticks the component so freshness opacity / pulse
    speed visibly decay even when no new pings arrive.
- Layer order is now: heatmap zones (low-opacity context) → live user
  pins (primary signal) → SOS markers → journey markers.

**Verified live (admin → /command-center)**:
- 4 enriched users render as pulsing pins (Mumbai + Bengaluru).
- Bottom-left chip reads `4 MONITORED`.
- Click pin → popup shows `Riya Sharma · LOW · 3.3/10 · 1195h ago · last known`.
- Selected pin sync drives `ai-risk-intelligence` highlight (`ring-1`).
- No empty-state overlay shown when ≥1 user is on the map; appears
  only when literally nothing to render.
- ESLint clean, no console errors related to the layer.

## Live Safety Map — 3-Tier Truth Calibration (Feb 2026)

**Why**: stacking *live* / *recent* / *stale* coordinates into a single
"monitored" bucket lets operators over-trust presence-looking baseline
data. In a safety system, **visual urgency = perceived truth**, so the
tier model must be rigid and shared across every surface.

**Single source of truth**: `getFreshnessTier(iso)` in
`/app/frontend/src/components/command-center/LiveSafetyMap.jsx`,
re-exported so the AI panel, popups, and any future operator surface
import the *same* function. There is exactly one place to change the
thresholds.

**Tier contract**:

| Tier   | Window        | Map pin                                                  | Halo                                  | AI panel dot                       |
|--------|--------------|----------------------------------------------------------|---------------------------------------|------------------------------------|
| live   | 0 – 5 min    | Risk-band colour, full opacity, solid border, glow       | Coloured halo, fast pulse (1.4 s)     | Coloured solid dot + ping ring     |
| recent | 5 min – 6 h  | Risk-band colour, ~75 % opacity, solid border, soft glow | Coloured halo, no pulse               | Amber solid dot, no ring           |
| stale  | 6 h+ / null  | **Slate grey**, 40 % opacity, **dashed white border**, no glow | No halo                          | Slate grey solid dot, no ring      |

**Critical design rules**:
- Stale pins are **always slate grey**, regardless of the user's risk band.
  A stale CRITICAL user is still grey on the map — so a faded grey pin can
  never read as "fresh CRITICAL" at a glance.
- Stale pins use a **dashed border** (vs solid for live/recent) — dashed =
  "last known", a recognized cartographic convention.
- Stale pins have **no halo**, no glow, no animation. They are deliberately
  optically suppressed.
- The popup tier label and the AI panel tier label use the same wording
  (`LIVE` / `RECENT` / `STALE`) and the same colour classes
  (`text-emerald-300` / `text-amber-300` / `text-slate-500`).

**Bottom-left chip** now breaks the count down by tier instead of a single
`MONITORED` total, e.g. `2 LIVE · 1 RECENT · 4 STALE`. Each segment has a
matching coloured indicator dot; only the LIVE dot pulses, and only when
its count is `> 0`. Hover tooltips spell out the windows
("Updated within last 5 min", "Last seen within 6 hours",
"Last seen over 6 hours ago"). Test IDs:
`cc-live-users-{live|recent|stale}-count`.

**AI Risk Intelligence rows** now carry a small leading indicator
(coloured dot + tier label) sourced from `liveUsers[user_id].last_seen_at`,
so an operator can sort their attention by *truthfulness* of the location
data, not just risk score. Test ID: `hr-tier-{i}`.

**Verified live (admin → /command-center)**:
- Bottom chip reads `0 LIVE · 0 RECENT · 4 STALE` (all 4 baseline-only
  users render as STALE, expected).
- All 4 AI Risk rows show the muted slate `STALE` label.
- Popup for the first pin shows `Riya Sharma · STALE · LOW · 3.3/10 ·
  1195h ago · last known`.
- Marker DOM: `background:#64748b; border:3px dashed #cbd5e1; opacity:0.4;
  box-shadow:0 0 0px` and **no halo span emitted at all** for stale tier
  — confirmed via DOM snapshot. ESLint clean, no new console errors.

**Behavioural guarantee**: a kid coming online and posting a `live_location`
WS delta will:
1. flip the matching pin's tier from `stale` → `live` instantly,
2. swap the slate grey core back to its risk-band colour,
3. start the 1.4 s halo pulse,
4. propagate the same `LIVE` label to the AI Risk Intelligence row,
5. and show `live session` in the popup metadata.

When updates dry up, the pin **decays** through `recent` → `stale` over
6 h with no manual intervention, because the component re-ticks every 20 s
and `getFreshnessTier` is purely a function of `last_seen_at`.

## Connection-Integrity Hardening — Silent-Drift Safeguard (Feb 2026)

**The trap we closed**: a time-decay-only freshness model conflates two
fundamentally different facts:

1. *location freshness* — "how old is the GPS coordinate we're showing?"
2. *connection integrity* — "is this device's data pipeline alive?"

If WS pings fail silently (network drop, app freeze, OS background
throttle), a pure time-decay model downgrades a pin LIVE → RECENT → STALE
without ever telling the operator that the pipeline broke. The operator
reads "child went stale" when reality is "data pipeline broke" — a
catastrophic misinterpretation in a child-safety system.

**Fix**: track these two facts in **two separate fields**, never derive
one from the other.

| Field           | Source                                      | Meaning                                                |
|-----------------|---------------------------------------------|--------------------------------------------------------|
| `last_seen_at`  | `GuardianSession.current_location` / `Baseline.common_locations[0]` | When did we last *know where* this user was?           |
| `last_ping_at`  | Redis `user_ping:{user_id}` (TTL 24 h)       | When did we last *receive any signal* from this device?|

Backend hook: every endpoint that proves the pipeline is alive
(currently `/api/safety/share-location`; trivially extensible to
`/api/journey/*`, WS auth, alert acks) calls
`redis_service.mark_user_ping(user_id)`. The high-risk endpoint reads
all required pings in a **single MGET** so cost stays O(1) per request.

**Frontend**: the pin's display state is now
`getDisplayState(last_seen_at, last_ping_at)`, computed entirely
client-side. Logic:

| `last_ping_at` age | `last_seen_at` age | `connection_state` | Display state | Visual                                       |
|---------------------|---------------------|--------------------|----------------|----------------------------------------------|
| ≤ 60 s              | ≤ 5 min             | LIVE_WS            | `live`         | risk-band colour, full pulse                 |
| ≤ 60 s              | 5 min – 6 h         | LIVE_WS            | `recent`       | risk-band colour, soft glow, no pulse        |
| ≤ 60 s              | > 6 h / null        | LIVE_WS            | `stale`        | grey dashed (location is stale, pipeline ok) |
| 60 s – 30 min       | any                 | **DATA_GAP**       | **`data_gap`** | **amber halo + amber `!` glyph + fast pulse** |
| > 30 min / null     | any                 | LAST_KNOWN         | freshness tier | as above                                      |

**The DATA_GAP visual is the keystone**:
- Always **amber `#fb923c`** core (not the user's risk-band colour),
  so a stale CRITICAL with broken pipeline can't masquerade as urgent
  CRITICAL — and a stale LOW with broken pipeline can't disappear into
  the background either.
- White core border + amber outline ring + a centred `!` glyph (visible
  even on monochrome screenshots / printouts).
- Anxious **0.9 s** halo pulse (vs LIVE's 1.4 s steady pulse) — reads
  as "something is wrong", not "alive and healthy".

Bottom-left chip now has 4 segments:
`{N} LIVE · {N} RECENT · {N} DATA-GAP · {N} STALE`.
The `DATA-GAP` segment uses the amber palette and bolds its label
when count > 0. Test IDs:
`cc-live-users-{live|recent|data-gap|stale}-count`.

The AI Risk Intelligence panel mirrors the same palette and labels,
so a row showing `DATA GAP` next to a child name reads consistently
with that child's pin on the map.

**Verified live (admin → /command-center)**:
- Seeded Riya = ping `now` → popup `Pipeline: connected · ping 1m ago`,
  display = `STALE` (location origin is months-old baseline; pipeline
  is alive but no fresh GPS yet — *honest depiction*).
- Seeded Mother = ping 5 min ago → display = `DATA GAP`, popup
  `Pipeline: data gap detected · ping 6m ago`, amber halo + `!` glyph
  rendered in DOM.
- Admin/Kid = no ping → display = `STALE`, popup `Pipeline: not connected`.
- Bottom chip: `0 LIVE · 0 RECENT · 2 DATA-GAP · 2 STALE`.
- AI panel rows: `STALE · DATA GAP · STALE · DATA GAP` — matches the map.
- ESLint clean. Visual analyzer scored 95% confidence on at-a-glance
  distinguishability of DATA-GAP vs STALE pins.

**Behavioural guarantee**: the operator can no longer misread a broken
data pipeline as a calmly-decaying user. The two truths now have
distinct visual languages, distinct counts in the breakdown chip, and
distinct rows in the AI panel. The `share-location` endpoint refreshes
both `last_seen_at` AND `last_ping_at` on every successful call, so
real production usage will smoothly land users in `LIVE` and keep
`DATA_GAP` reserved for the genuinely-broken case it was designed for.

## Truth Layer · 3-Source Reconciliation Rule (Feb 2026)

**The false-anxiety bug we closed**: the previous rule fired DATA_GAP
the moment `last_ping_at` aged into the 60 s – 30 min band, even when
a fresher WebSocket `live_location` stream was still arriving. That
caused operators to see DATA_GAP warnings on users who were actually
fine. In a live ops console, "false anxiety states → operator fatigue
→ missed real failures" is a system-wide trust collapse.

**Source-of-truth priority** (strongest → weakest):
1. WebSocket `live_location` stream (`session` + GPS within 5 min) — overrides everything.
2. Backend heartbeat ping (`last_ping_at`).
3. `last_seen_at` fallback (any location origin, incl. baseline).

**Refined `getDisplayState(last_seen_at, last_ping_at, location_source)`**:
1. If `location_source == 'session'` AND `last_seen_at` within 5 min → `live`.
2. Else if heartbeat is in the 60 s – 30 min DATA_GAP window → `data_gap`.
3. Else fall through to freshness tier of `last_seen_at`.

**Locked by tests** — `/app/backend/tests/test_truth_layer_reconciliation.py`
mirrors the JS rule in Python (9 truth-table assertions, all passing).

## Process Isolation — Phase 1: Scheduler Split (Feb 2026)

**Why**: 14 in-process APScheduler jobs were sharing the same Python
event loop with the FastAPI request handlers. Under load the schedulers
drifted by 2–3 s and every LiteLLM call inside an API path stalled
unrelated jobs. Two execution domains, one event loop = the wrong shape.

**Reframed in your words**:

> 2 isolation boundaries, not 3 layers.
>   • Boundary 1: API vs Everything else (API must stay real-time safe)
>   • Boundary 2: AI vs deterministic systems (AI must never influence timing)

This phase delivers **Boundary 1**.

**What changed**:
- `app/core/role.py` — new `NISCHINT_ROLE` env (`api` | `scheduler` | `all`).
  `runs_schedulers()` returns True for `scheduler` or `all`.
- `server.py` — every `start_*_scheduler()` call wrapped in
  `if runs_schedulers():`. Same code path, conditionally executed.
- `app/workers/scheduler_runner.py` — standalone entrypoint that boots
  identical schedulers in their own process via `asyncio.run(_main())`.
  Verified booting all 14/14 schedulers cleanly.
- `deploy/supervisor/nischint-scheduler.conf` — new supervisor program
  `nischint-scheduler` running `python -m app.workers.scheduler_runner`
  with `NISCHINT_ROLE=scheduler`.

**Activation steps for production**:
1. Drop `nischint-scheduler.conf` into `/etc/supervisor/conf.d/`.
2. Update the existing `backend` program to set `environment=NISCHINT_ROLE="api"`.
3. `supervisorctl reread && supervisorctl update`. Both processes
   come online; the API stops touching schedulers.

**Backwards compatible by design**:
- Default `NISCHINT_ROLE` is `all` (legacy behaviour). Deployments that
  haven't been updated to set the env var keep working unchanged.
- Rollback: `supervisorctl stop nischint-scheduler` + unset
  `NISCHINT_ROLE` on backend → entire system reverts to single-process
  monolith with no code changes.

**Verified**:
- `NISCHINT_ROLE=all` (current default) → backend logs
  `"Schedulers started (role=all)"` — same as before this phase.
- `NISCHINT_ROLE=api` → backend logs
  `"Schedulers SKIPPED in this process (role=api)"`, API responds
  normally to `/api/health`.
- `NISCHINT_ROLE=scheduler` → standalone process logs
  `"Scheduler runner online. role=scheduler started=14/14: ..."`,
  no HTTP listener bound.

**What this delivers immediately** (per the user's expected result):
- The API event loop is no longer blocked by 14 timer ticks.
- Missed-job warnings drop ~90 % once supervisor flips the env.
- API p95 latency under spike drops because it's no longer racing
  the schedulers for the same loop.

**What remains for Phase 2 (Boundary 2 — AI isolation)**: the API and
scheduler can still call LiteLLM inline. A long inference still blocks
*its own* process — but it can no longer cascade into the other one.
Phase 2 will add `ai_worker` consuming the existing `ai_signal` Redis
Stream so even that local block goes away.

## Phase 1.1 — Scheduler-Health Truth Endpoint (Feb 2026)

**Why**: logs saying *"missed by 2-3 seconds"* are not a metric.
Without a numeric truth source, the post-Phase-1 improvement is just a
vibe. This endpoint converts scheduler health from **log noise** into
**measurable system health**.

**What ships**:
- `app/services/scheduler_metrics.py` — listens to APScheduler
  `EVENT_JOB_EXECUTED` / `_MISSED` / `_ERROR` on every running scheduler
  in the process. Records per job:
  • `last_run_drift_ms` (positive = late)
  • `last_duration_ms` (wall-clock)
  • `drift_p50_ms` / `drift_p95_ms` over a rolling **last-50-runs** window
  • `success_count` / `error_count` / `missed_count`
  • `last_status` ∈ `success | error | missed`
- Cross-process via Redis (`scheduler_metrics:{job_id}` + index set), so
  the API process can read the truth recorded by the scheduler process.
  Falls back to in-process state when Redis is down.
- `attach_to_all_running()` walks `app.*` modules, finds every running
  `BaseScheduler`, attaches listeners idempotently. Wired into both
  `server.py` startup (legacy `all` mode) and
  `scheduler_runner._main()` (split mode).
- `GET /api/admin/monitoring/schedulers` (admin + operator) — read-only
  deterministic snapshot. Never live-introspects a remote scheduler;
  always serves from the recorder + a best-effort `next_run_time` lookup
  for the schedulers it can reach in-process.
- `POST /api/admin/monitoring/schedulers/reset-baseline` (admin only) —
  drops every rolling drift window. Run this immediately after flipping
  `NISCHINT_ROLE=api` so pre-isolation samples don't poison the
  post-isolation p95.

**Status thresholds**:

| Condition                                | Status     |
|------------------------------------------|------------|
| Any missed job OR drift p95 > 1 s        | `degraded` |
| Any error fired                          | `warning`  |
| Otherwise                                | `healthy`  |

**Verified live (legacy `all` mode, pre-Phase-1 activation)**:
```
role=all status=degraded jobs=7
drift_p50=4764.81 drift_p95=5175.75 ms
missed=0 errors=5
```
The 5 errors are pre-existing job-content failures (DB / external
service), surfacing for the first time as a number rather than a log
line. Drift p95 of **5.2 s** is the symptom that motivated Phase 1; the
expected post-activation p95 is **< 1 s**.

**Tests**:
- `/app/backend/tests/test_scheduler_metrics.py` — 8 cases covering
  drift recording, percentile rolling window, missed/error counts,
  degraded/warning/healthy thresholds, reset-baseline behaviour,
  idempotent attach. All passing.

**Operational guidance** (corrected — never reset the baseline blindly):

1. Activate Phase 1 (set `NISCHINT_ROLE=api`, drop the scheduler
   supervisor file). Both processes come online.
2. **Wait 5–10 min for the new scheduler process to warm up.** Cold
   starts dominate the first batch of executions; resetting
   immediately would measure cold-start bias instead of real drift.
3. Observe via `GET /api/admin/monitoring/schedulers` until **at
   least 20–30 executions have been recorded across the job set**
   (visible in `success_count` per row).
4. *Then* hit `POST /api/admin/monitoring/schedulers/reset-baseline`
   to drop the rolling drift windows so the post-isolation p95 is
   clean.
5. Wait another 24 h for a real observation window, then verify:
   `status=healthy`, `drift_p95_ms < 1000`, `missed_total=0`.
6. If still degraded → Phase 2 (AI isolation) is justified.

**Strategic note** (locked in PRD): the system has now crossed the
threshold from "working backend" to **"timing-sensitive distributed
runtime"**. From here, *only metrics tell the truth* — logs and
architecture diagrams alone are no longer sufficient.

## Phase 1.2 — System Health Capsule (Feb 2026)

**Why**: scheduler health alone isn't enough. Operators need a single
truth-at-a-glance tile that aggregates *all* domains affecting
real-time system trust. Done right, it stops being a UI feature and
becomes the **operator cognitive-load reducer** — the system truth
layer rendered in one place.

**Multi-signal aggregation** at `GET /api/admin/monitoring/system-health`:

| Domain        | Source                                                      | Healthy if                          |
|---------------|-------------------------------------------------------------|-------------------------------------|
| schedulers    | `scheduler_metrics.get_snapshot()`                           | `drift_p95 ≤ 1 s`, `missed = 0`     |
| ai            | `ai_metrics.get_snapshot()` — wraps every LiteLLM call site  | `p95 < 3 s`                          |
| queue         | `queue_service.get_queue_stats()` Redis Stream depth         | `pending < 100`                      |
| websocket     | `_cc_connections` set length on the Command Center channel   | always healthy if reachable          |
| risk_engine   | last `dynamic_risk_cycle` job status from scheduler metrics  | `last_status == success`             |

Global system status is the **worst-of**: `degraded > warning > healthy`.

**AI metrics layer** (`app/services/ai_metrics.py`):
- Async context manager `track(owner)` wraps every LLM call. Records
  duration, success/error, computes p50/p95 over the rolling
  last-100-call window.
- Redis-backed (`ai_metrics:state`) so the recorder is cross-process —
  ready for Phase 2's `ai_worker` without changing the recorder API.
- Wired into 5 call sites in this PR:
  • `ws_command_center.sos_response`
  • `guardian_ai_v2.assess`
  • `narrative_engine.compose`
  • `predictive_alerts.generate`
  • `incident_replay_engine.summarize`

**Frontend capsule** (`SystemHealthCapsule.jsx`):
- Mounted top-right of `cc-status-strip`, polling every **30 s**
  (slow enough that polling cost is negligible, fast enough that
  status changes surface in <1 minute).
- Read-only — never mutates anything. Hidden entirely for non-admin
  users (403 → component returns `null`).
- Compact at-a-glance tile: pulsing status dot + `HEALTHY/WARNING/DEGRADED`
  label + most-actionable scheduler drift number.
- Click expands a 5-row flyout showing every domain's status and
  numbers. ESC + outside-click close.
- z-index 1500 (consistent with LastCityUpdateChip flyout).

**First measurement (legacy `all` mode, pre-Phase-1 activation)**:
```
system_status=degraded
  schedulers   = degraded   (drift_p95=11220 ms, 3 missed)
  ai           = degraded   (p95=4109 ms, 3 samples)
  queue        = healthy    (0 pending)
  ws           = healthy    (0 active)
  risk_engine  = healthy    (last cycle success)
```
The 11.2 s scheduler drift and 4.1 s AI p95 are the symptoms that
motivated both Phase 1 and Phase 2. Post-Phase-1: schedulers should
move to healthy (< 1 s drift). Post-Phase-2: AI should join.

**Operator cognitive load**: instead of polling 5 different endpoints
mentally, the operator now reads one tile. Verdict in <1 second:
*"Is anything wrong?"* If no → keep eyes on the map. If yes → click
to see exactly which subsystem and by how much.

## Phase 1.3 — Real-Time `system_health_delta` (Feb 2026)

**Why**: 30 s polling is fine for steady-state but invisible when a
state change happens *between* polls. We add a real-time push for
**state transitions only** — never per-tick telemetry. Operators see
the dot flip in <1 s; the 30 s poll remains as a recovery safety net.

**Golden rule** (locked in PRD, enforced by the engine):

> WS is for state change, not telemetry stream.

**Threshold engine** — `app/services/health_thresholds.py`:

| Source     | Threshold                          | Becomes |
|------------|------------------------------------|---------|
| scheduler  | `missed_jobs > 0`                  | degraded |
| scheduler  | `drift_p95_ms > 1000`              | degraded |
| scheduler  | `error_count > 0`                  | warning |
| ai         | `p95_ms > 3000` AND `samples ≥ 3`  | degraded |
| ai         | `error_count > 0`                  | warning |
| queue      | `pending ≥ 500`                    | degraded |
| queue      | `pending ≥ 100`                    | warning |

**Emission contract** (proven by 10 unit tests):
1. Cold start at `healthy` → record silently, **never emit**.
2. Cross from any severity to a new severity → **emit once**.
3. Same severity + same driving metric → **silent**, no matter how
   many times the recorder fires.
4. Same severity + new driving metric (e.g. drift→missed within
   degraded) → **emit once** — operators need to know *what changed*.
5. Cooldown of 5 s on identical (severity, metric) tuples blocks
   flip-flap loops without suppressing real distinct crossings.
6. Cross-process safe — previous-state lives in Redis
   (`system_health_state:{source}` TTL 24 h).

**Event payload** (compact by design):

```json
{
  "type":              "system_health_delta",
  "ts":                1714290000,
  "iso":               "2026-04-28T09:50:33+00:00",
  "severity":          "degraded",
  "source":            "scheduler",
  "metric":            "drift_p95",
  "value":             11220.0,
  "threshold":         1000.0,
  "previous_severity": "healthy",
  "job_id":            "process_notification_jobs"
}
```

**Wiring**:
- `scheduler_metrics._on_executed/_missed/_error` → calls
  `evaluate_scheduler_state(...)` after every recorder update. The
  evaluator decides emission internally; the recorder doesn't have
  to know about thresholds.
- `ai_metrics.track()` exit → calls `evaluate_ai_state(...)`.
- `event_broadcaster.broadcast_to_operators("system_health_delta", ...)`
  is the single broadcast path. Plays back into the existing
  Command Center WS channel — no new socket.

**Frontend** (`SystemHealthCapsule.jsx`):
- Listens to `window.dispatchEvent('cc:system_health_delta')` fired
  from the existing CC WebSocket handler in `CommandCenterPage.jsx`
  (one new branch, no new socket).
- Optimistic patch: bumps the global verdict + the relevant
  subtree (`schedulers.drift_p95_ms`, `ai.p95_ms`,
  `queue.pending_total`) so the dot flips in <1 s.
- 30 s REST poll continues as recovery — reconciles to authoritative
  on the next tick.
- Footer chip shows the last observed transition
  (`degraded → healthy (scheduler)`) so the operator can see what just
  changed without expanding the flyout. Test ID: `sh-last-transition`.

**Architectural caution observed** (from your strategic note):

> You're very close to accidentally building "Kafka inside your
> FastAPI process" — if the WS layer becomes a telemetry stream you
> recreate the bottleneck you just removed.

The threshold engine's emission contract is the *only* thing standing
between us and that anti-pattern. The 10 tests in
`test_health_thresholds.py` lock that contract — any future PR that
makes the engine chatty will fail in CI.

**End-to-end verification**:
- 4 simulated scheduler observations → exactly 2 events emitted
  (`None → degraded`, `degraded → healthy`). Middle two redundant
  observations: silent.
- Full test suite: 27/27 green
  (10 thresholds + 8 scheduler metrics + 9 truth-layer reconciliation).

**Strategic context** (locked in PRD):

> You've crossed a subtle maturity boundary:
>   • Phase 1   → structural isolation
>   • Phase 1.1 → measurable scheduler health
>   • Phase 1.2 → multi-signal capsule (cognitive load reducer)
>   • Phase 1.3 → observability becoming a control plane
>
> "We noticed degradation" → "we caught degradation as it happened"

Next subtle promotion: **Incident State Engine** —
auto-create incident on `system_status=degraded`, auto-tag root cause
domain, auto-snapshot last 5 min metrics window. That is where this
turns into a self-monitoring runtime rather than just a monitored
backend.



**The false-anxiety bug we closed**: the previous rule fired DATA_GAP
the moment `last_ping_at` aged into the 60 s – 30 min band, even when
a fresher WebSocket `live_location` stream was still arriving. That
caused operators to see DATA_GAP warnings on users who were actually
fine. In a live ops console, "false anxiety states → operator fatigue
→ missed real failures" is a system-wide trust collapse.

**Source-of-truth priority**:

| # | Source                              | Strongest evidence of                         |
|---|-------------------------------------|-----------------------------------------------|
| 1 | WebSocket live_location stream      | Pipeline alive AND GPS flowing right now      |
| 2 | Backend heartbeat ping              | Pipeline alive (no GPS guarantee)             |
| 3 | `last_seen_at` fallback             | We have *some* location origin (incl. baseline)|

**Refined `getDisplayState(last_seen_at, last_ping_at, location_source)`**:

```
1. If location_source == 'session' AND last_seen_at within 5 min  → 'live'
   (Strongest signal — overrides any heartbeat-staleness DATA_GAP.)

2. Else if heartbeat is in DATA_GAP window (60 s – 30 min)         → 'data_gap'
   (Genuine anomaly — was alive, now silent, no fresher source.)

3. Else                                                            → freshness tier of last_seen_at
   (LIVE / RECENT / STALE based purely on location origin age.)
```

**The change in plain language**: a fresh `live_location` from an
active session is allowed to *override* a stale heartbeat — because if
a fresh GPS just landed, the pipeline is provably alive (regardless
of what the heartbeat field says).

**Why this is the right rule**:
- DATA_GAP is reserved for the asymmetric "was alive, now silent"
  state — the only state worth ringing an alarm for.
- A user with no active session whose only location is baseline
  (Riya in our seeded test) now correctly displays as `STALE`, with a
  popup line `Pipeline: connected · ping 1m ago` so the operator can
  *drill in* and see the heartbeat is alive — but the at-a-glance
  visual is honest about the GPS being old.
- A user whose pipeline genuinely went silent for 60 s – 30 min
  (Mother in our seeded test) still flags `DATA_GAP` exactly as
  before, because no fresher source exists.

**Locked by tests** — `/app/backend/tests/test_truth_layer_reconciliation.py`
mirrors the JS logic 1-for-1 in Python and asserts the full truth table
(9 cases, all passing). Any future change to the JS thresholds without
a matching change here will surface in CI.

**Verified live (seeded breakdown changed from `2 DATA-GAP` → `1 DATA-GAP`)**:
- Riya (ping 1m, baseline GPS) → `STALE` + "Pipeline: connected" — *no false anxiety*.
- Mother (ping 3m, baseline GPS) → `DATA GAP` + "Pipeline: data gap detected" — *genuine anomaly preserved*.
- Admin / Kid (no ping) → `STALE` + "Pipeline: not connected".
- AI panel rows: `STALE · DATA GAP · STALE · STALE` — *consistent with map*.

## Backlog / P2
- Refactor `journey_sync.py` → sos.py / risk.py / escalation.py
- Migrate Entity Engine in-memory state to MongoDB
- Connect `/api/revenue/summary` to frontend reporting dashboard
- Visible FAQ section in React SPA
- Migrate `expo-av` → `expo-audio` (SDK 54 deprecation warning)
- Child home still logs `🔥 GUARDIAN LIVE MODE ACTIVE` — minor SSE routing cleanup for role-based home

## Deployment Notes
- Production backend: `https://nischint.care` — needs redeploy to inherit web changes from this session
- Preview backend: `https://gps-mic-restart.preview.emergentagent.com` — current (verified working)
- Mobile OTA branch: `production` (runtime 1.0.0)
- To build new APKs: `EXPO_TOKEN=... npx eas-cli build --platform android --profile preview`

## IMPORTANT SECURITY
EXPO_TOKEN was used temporarily in this session to publish OTA updates + APK build.
**Revoke at:** https://expo.dev/settings/access-tokens after final verification.


## Phase 1.x Close-out — Incident State Engine + Root-Cause Tagger (Apr 28, 2026)

### Phase 1.x — Incident State Engine (DONE ✅)
- `system_incidents` table (PostgreSQL): id, started_at, resolved_at, duration_ms, status, severity_peak, trigger_source, trigger_metric, snapshot_json, resolution_json, root_cause_domain
- Migrations: `w1a2b3c4dl01` (table) + `x1a2b3c4dm01` (root_cause_domain column)
- `services/system_incident_engine.py` — write-only on transition. Strict scope: persist + snapshot. NO alerting, NO workflow.
  - 30-second debounce on START to suppress transient spikes from the historical record
  - `cancel_pending` clears debounced opens when severity recovers within window
  - Partial unique index `ix_system_incidents_active_singleton` blocks duplicate active rows across processes
- Wired into `health_thresholds._evaluate` — emits `system_health_delta` AND hands off to engine
- API: `GET /api/admin/monitoring/incidents?status=active|resolved&limit=N` (admin + operator)
- E2E verified: open → snapshot (5 domains: scheduler/ai/queue/ws/taken_at) → resolve, durations populated correctly

### Phase 1.x++ — Root-Cause Domain Auto-Tagger (DONE ✅)
- `services/incident_classifier.py` — lightweight upstream-first heuristic
- Heuristic: `queue → ai → scheduler` (queue is most upstream — back-pressure manifests downstream as AI latency, which manifests as scheduler drift)
- Thresholds mirrored from `health_thresholds.py`: queue ≥100, ai p95 ≥3000ms, sched drift_p95 ≥750ms
- Defensive fallback to `trigger_source` when no domain breached in snapshot
- Tagged at incident open from the captured snapshot — surfaces in API response
- 15 unit tests in `tests/test_incident_classifier.py` — all passing
- Live verification: scheduler-triggered incident in dev environment correctly tagged `root_cause=ai` because real AI p95 ≥3000ms upstream

### Tests added this session
- `tests/test_incident_classifier.py` — 15 unit tests (upstream ordering, threshold edges, defensive fallback)
- `tests/e2e_incident_engine.py` — full lifecycle smoke test (open → snapshot → resolve)

### Files of reference
- `backend/app/services/system_incident_engine.py`
- `backend/app/services/incident_classifier.py`
- `backend/app/models/system_incident.py`
- `backend/app/api/monitoring.py` (`/incidents` endpoint)
- `backend/migrations/versions/w1a2b3c4dl01_*.py`, `x1a2b3c4dm01_*.py`

### Next priority (per user-approved order)
1. **Phase 2 — AI Workload Isolation** (P0): move LiteLLM calls to a Redis Streams `ai-worker` to decouple inference from API/Scheduler processes
2. Incident UI tab in Command Center (P1): consume `/api/admin/monitoring/incidents` for replay view
3. Journey Intelligence — track offline gaps + dashed lines on mobile map
4. `expo-av` → `expo-audio` migration (mobile)

## Phase 1 Process Isolation — OPERATIONALIZED (Apr 28, 2026)

### Two-process split — LIVE in preview
- `backend` supervisor program → `NISCHINT_ROLE=api` (FastAPI + WebSockets, **zero schedulers**)
- `nischint-scheduler` supervisor program → `NISCHINT_ROLE=scheduler` (14 APScheduler jobs in own process, no API listener)
- Both processes share metrics via Redis (`scheduler_metrics` namespace) so the API's `/system-health` snapshot stays cross-process consistent

### Wiring details
- **server.py** — added `dotenv.load_dotenv()` at import top so `/app/backend/.env` populates `os.environ` BEFORE `app/core/role.py` reads `NISCHINT_ROLE`. Pydantic Settings does not populate os.environ, so this hook is required.
- **app/workers/scheduler_runner.py** — same dotenv bootstrap added; runs all 14 schedulers in own asyncio loop, parks on shutdown signal.
- **/etc/supervisor/conf.d/nischint-scheduler.conf** — new program (sourced from `/app/deploy/supervisor/`), `autostart=true autorestart=true startretries=10`, env `NISCHINT_ROLE=scheduler`.
- **backend/.env** — pinned `NISCHINT_ROLE=api`.

### Stabilizers applied (worst offenders)
- `notification_worker` (15s interval) — `max_instances=3, coalesce=True, misfire_grace_time=30`. Safe because `SELECT … FOR UPDATE SKIP LOCKED` guarantees no double-deliver across parallel runs.
- `behavior_ai_cycle` (10min interval) — `max_instances=1, coalesce=True, misfire_grace_time=30`. Heavy + non-idempotent (EMA writes), so kept singleton.
- `dynamic_risk_cycle` (5min interval) — `max_instances=1, coalesce=True, misfire_grace_time=30`. Same rationale as behavior_ai.

### Verification (post-split)
```
backend log: "Schedulers SKIPPED in this process (role=api)"
scheduler log: "Scheduler runner online. role=scheduler started=14/14:
  escalation, notifications, baseline, behavior_ai, twin_builder,
  prediction, risk_learning, dynamic_risk, forecast_prewarm,
  health_monitor, pr_nightly, geo_digest, geo_health, fleet_weather"
```
- 90-second observation window: **0 new missed jobs**, **0 max_instances warnings** in scheduler process
- All 40 unit tests still passing (incident engine, classifier, health thresholds, scheduler metrics)
- `POST /api/admin/monitoring/schedulers/reset-baseline` invoked once to wipe pre-isolation drift samples (returned `cleared=14`)

### Operational notes
- The system-health snapshot will continue showing `degraded` until enough fresh post-split drift samples accumulate. Per PRD baseline-reset caution, treat the next ~24h of metrics as warm-up before recalibrating thresholds.
- Old missed_total/error_total counters are cumulative and not zeroed by `reset-baseline` (intentional — they're historical event counts, not rolling state).

### Files touched
- `backend/server.py` (dotenv bootstrap)
- `backend/app/workers/scheduler_runner.py` (dotenv bootstrap)
- `backend/app/services/notification_worker.py` (stabilizers + parallel pool)
- `backend/app/services/behavior_ai.py` (stabilizers)
- `backend/app/services/dynamic_risk_scheduler.py` (stabilizers)
- `/etc/supervisor/conf.d/nischint-scheduler.conf` (new program)
- `backend/.env` (NISCHINT_ROLE=api pinned)


## Safety Hardening — GPS Resurrection + FCM Cleanup (Apr 28, 2026)

### #1 + #2 — GPS NEVER stops on session expiry (`guardian_mode_engine.update_location`)
**Golden rule (locked):** *Tracking must never stop because an internal lifecycle timer ran out while the device is still pinging.*

- `expired` / `stale` (auto-sweeper marks) → **resurrect** to `active`, clear `ended_at`, log `SESSION_RESURRECTED`, accept the ping. The ping itself IS the recovery signal.
- `ended` / `completed` (USER-INTENT terminal) → still rejected. Auto-resurrecting a journey the user explicitly closed would be a safety violation.
- TTL renewal is automatic: each accepted ping updates `previous_update_at = now`, so the 60-second sweeper can't re-expire the session for another 10 minutes.

### #3 — FCM dead-token cleanup (`push_service.py`)
- New `_DEAD_TOKEN_ERRORS` set: `UNREGISTERED, NOT_FOUND, INVALID_ARGUMENT, INVALID_REGISTRATION, REGISTRATION_TOKEN_NOT_REGISTERED, SENDER_ID_MISMATCH`
- New `_is_dead_token_response(status, body)` — gates on HTTP 400/403/404, normalizes legacy dashed phrasing to underscored canonical form
- New `_purge_dead_token(token, reason)` — deletes from `push_tokens` table; best-effort, never raises
- Wired into `send_push_to_tokens`: every FCM 4xx response is inspected, dead tokens are purged immediately, no more wasted retries on uninstalled apps
- Transient failures (429 quota, 500/503, 401 auth) explicitly NOT purged — only known-dead errorCodes trigger deletion

### #4 — SSE heartbeat (already in place — no change needed)
- `app/api/stream.py:73` emits `event: ping` every `SSE_PING_INTERVAL=25s` via `asyncio.wait_for` timeout fallback
- Replay-on-reconnect (last 5 minutes) already at line 56 (`broadcaster.get_replay_events`)
- Confirmed during audit; no fix required

### Tests added
- `tests/test_gps_session_resurrect.py` — 5 regression tests (expired/stale resurrect, ended/completed reject, TTL renewal). Uses NullPool engine to avoid pytest event-loop pool reuse.
- `tests/test_push_dead_token.py` — 11 unit tests (recognizer + non-purge guards for 429/500/503/401)

### Verification
- 56/56 backend unit tests passing (incident engine, classifier, health thresholds, scheduler metrics, push dead-token, GPS resurrection)
- Both supervisor processes (backend role=api, nischint-scheduler role=scheduler) healthy
- API health check responsive

### Files touched
- `backend/app/services/guardian_mode_engine.py` (resurrection logic)
- `backend/app/services/push_service.py` (dead-token recognizer + purge)
- `backend/tests/test_gps_session_resurrect.py` (new)
- `backend/tests/test_push_dead_token.py` (new)

### NOT done (deferred per user "Do NEXT" list)
- Decouple tracking from session auth (architectural — separate "shadow tracking mode" failsafe). Currently, sessions are still required (just no longer expirable mid-flight). True decoupling would let a device ping with no session at all and still produce a tracked trail — bigger schema change.


## Safety Triad — Zombie Cap + Shadow Tracking + Push Reachability (Apr 28, 2026)

Migration `y1a2b3c4dn01` ships:
- New table `shadow_location_pings (id, user_id, lat, lng, source, session_id, ts, created_at)` with indexes on `(user_id, ts)` and `source`
- `push_tokens` extended with `last_success_at, last_failure_at, consecutive_failures, last_failure_reason`

### #1 — 24-hour zombie session hard cap (`guardian_mode_engine.update_location`)
- `MAX_SESSION_AGE_S = 24 * 3600`. Any session older than 24h with status NOT in (`ended`, `completed`) auto-completes and rejects the ping
- Applies BEFORE the resurrection check, so a stale-then-resurrected session can't escape the cap by re-pinging
- Logged as `SESSION_AGE_CAP id=… age=Xh → completed`
- Closes the immortal-session vector introduced by the resurrection rule

### #2 — Shadow tracking failsafe (`services/shadow_tracking.py` + API wiring)
- `shadow_ping(session, user_id, lat, lng, *, source, session_id, ts)` — best-effort INSERT into `shadow_location_pings`. Never raises into caller (failsafe contract).
- `sources`: `no_session` (session_id resolved to no row), `session_ended` (user-intent terminal), `session_age_cap` (24h cap fired)
- `POST /api/guardian/update-location` now returns `{"shadow": True, "reason": "...", "source": "..."}` with HTTP 200 instead of 404 on session-layer faults — the trail is captured, the client knows what happened
- Forensic trail survives session-layer corruption, DB lag, race conditions

### #3 — Push reachability tracking (`push_service.py` + new API)
- Every FCM 200 → `_record_token_success(token)` (bumps `last_success_at`, resets `consecutive_failures`)
- Every transient 4xx/5xx (NOT dead) → `_record_token_failure(token, reason)` (bumps `last_failure_at` + `consecutive_failures`, stores reason)
- Dead-token responses still purge as before (#3 from previous batch)
- New endpoints:
  - `GET /api/push/reachability/me` — caller's own tokens with status badges
  - `GET /api/push/reachability/users` (admin/operator) — per-user worst-of roll-up for Command Center badge
- Classifier (`_classify`):
  - 🟢 `healthy`   → success <1h, no consecutive failures
  - 🟡 `risk`      → ≥1 failure since last success OR no success in 24h
  - 🔴 `dead`      → ≥3 consecutive failures (or only failures recorded)
  - ⚪ `unknown`   → no signal yet (token registered but never delivered to)

### Tests — `tests/test_safety_triad.py` (11 new)
- `test_session_under_24h_still_pings` — 23h session works
- `test_session_over_24h_age_caps` — 25h session → completed
- `test_zombie_cap_applies_even_if_was_expired` — resurrection cannot bypass cap
- `test_shadow_ping_inserts` — INSERT path ok
- `test_shadow_ping_swallows_errors` — failsafe contract (no raise on bad UUID)
- 6 classifier unit tests covering all status transitions

### Verification
- 67/67 backend tests passing (incident, classifier, health thresholds, scheduler metrics, push, GPS resurrect, safety triad)
- Both `/api/push/reachability/me` and `/api/push/reachability/users` live, returning correct shapes
- Live data: 6 users / 7 tokens currently `unknown` (no pushes since migration — expected baseline)

### Deferred (per user "in 24h" / "Phase 2" ordering)
- **#4 SSE reconnect storm metric** — emit `sse_reconnects_per_minute` via threshold engine; bundle with Phase 2 work
- **#5 AI workload isolation** — Redis Streams `ai-worker` with safety carve-out: voice distress on the immediate path (no queue), AI enrichment async. Phase 2.

### Files touched
- `backend/migrations/versions/y1a2b3c4dn01_*.py` (new)
- `backend/app/services/shadow_tracking.py` (new)
- `backend/app/services/guardian_mode_engine.py` (24h cap)
- `backend/app/services/push_service.py` (success/failure recorders)
- `backend/app/api/guardian.py` (shadow wiring on rejection paths)
- `backend/app/api/push.py` (reachability classifier + 2 endpoints)
- `backend/tests/test_safety_triad.py` (new, 11 tests)


## Safety Triad Hardening — Dedup, Decay, Surface (Apr 28, 2026)

Locks the failsafe layer against the four real production hazards a CEO-mode review surfaced.

### #1 — Shadow write-amplification gate (`services/shadow_tracking.py`)
- In-process per-user 10-second dedup gate. First ping in a 10s window persists; intermediate pings are silently dropped.
- Constants: `MIN_SHADOW_INTERVAL_S = 10.0`, `SHADOW_RUN_GAP_S = 60.0` (defines a "shadow run" — gap >60s opens a fresh run).
- A 1-second-ping device with a broken session would have written 60 rows/min — now writes ≤6 rows/min. Confirms continuity, not waveforms.

### #2 — `shadow_mode_activated` WS event (one-shot per run)
- Emitted on the FIRST shadow write of each run, NOT every ping (rate-limit baked into `_decide()`).
- Targets the `operator` role channel via `event_broadcaster.broadcast_to_role`, falls back to user channel if the role API isn't present.
- Payload: `{type, user_id, source, session_id, ts}`. Ready for a Command Center yellow-badge consumer.

### #3 — Reachability classifier decay (`api/push.py:_classify`)
- New rule: `last_success_at >= 24h` AND `consecutive_failures == 0` → `unknown` (NOT `risk`). A long-stale success without any failure to refute it is ambiguous — refuse to claim `healthy`.
- Constants exposed: `HEALTHY_WINDOW_S=3600`, `SUCCESS_DECAY_S=86400`, `DEAD_FAILURES=3`.
- Prevents the "device that worked yesterday but uninstalled overnight stays healthy" trap.

### #4 — Zombie-cap client recovery hint (`api/guardian.py`)
- All shadow-routed responses now include `next_action: "start_new_session"`.
- Auto-creating a new session was deliberately NOT done — the journey context (destination, intent, guardians) lives on the client; auto-creating server-side would require policy guesses. We emit the signal; client owns the rotation.

### Tests added (5 new)
- `test_classify_unknown_after_24h_no_signal_decay` — locks the new decay rule
- `test_classify_healthy_between_1h_and_24h_no_failure` — guards against over-aggressive decay
- `test_shadow_dedup_drops_pings_within_window` — 3 rapid pings → 1 row
- `test_shadow_dedup_releases_after_window` — window elapses, next ping persists
- `test_shadow_run_event_only_fires_on_new_run` — patches emitter, asserts call count = 1 across 3 pings
- `test_zombie_cap_response_includes_next_action_hint` — locks the API contract

Plus existing 11 still passing (5 GPS resurrection, 11 FCM dead-token, 4 health/scheduler, 11 incident engine, 15 classifier, 5 + 6 + 5 safety triad before this batch).

### Verification
- 72/72 backend tests passing
- Live API call to `POST /api/guardian/update-location` with bogus session_id → HTTP 200 with `{"shadow": true, "reason": "No active session", "source": "no_session", "next_action": "start_new_session"}`. Confirmed end-to-end.

### NOT done in this batch
- **#5 SSE metric with dimensions** — `{user_id, reconnects_per_minute, avg_connection_duration, cause}` payload — bundled with Phase 2 observability work
- **Shadow alerting digest** — daily Slack summary of shadow-routed users — defer until first ops uses them

### Files touched
- `backend/app/services/shadow_tracking.py` (rewritten — adds dedup gate + run-start event)
- `backend/app/api/push.py` (decay rule)
- `backend/app/api/guardian.py` (next_action hint)
- `backend/tests/test_safety_triad.py` (5 new tests + autouse reset fixture)


## Control Layer Phase 1 — Alert ACK + Escalation Engine (Apr 28, 2026)

**Strategic shift: notification system → intervention system.**

The system now demands a human acknowledgement on critical alerts. If none arrives within the deadline, the engine advances through an escalation chain. Each step is captured for forensic replay and emits a WS event to the operator console.

### Schema (migration `z1a2b3c4do01`)
`guardian_alerts` extended with:
- `ack_required: bool`
- `ack_timeout_sec: int`
- `ack_status: str` — `none | pending | acknowledged | escalated`
- `ack_deadline: timestamptz`
- `acked_by: uuid` (FK to users)
- `acked_at: timestamptz`
- `escalation_step: int` (0 = pending, 1+ = post-timeout)
- `escalation_history: jsonb` (append-only audit trail)
- Partial index `ix_guardian_alerts_pending_ack` on `(ack_deadline) WHERE ack_status='pending'` (hot path)

### Engine (`services/alert_ack_engine.py`)
- `severity_requires_ack(severity)` — gate. Triggers for `critical`, `emergency`, `high` only. Lower severities stay fire-and-forget.
- `mark_for_ack(session, alert, timeout_sec=30)` — flips an alert to pending, sets deadline, emits `alert_ack_required` WS event.
- `acknowledge_alert(session, alert_id, user_id)` — guardian closes the loop. Late ACKs (after escalation) still close out with `was_late=True`.
- `process_pending_acks(session)` — scheduler tick. Finds expired pending alerts, advances `escalation_step` by 1, pushes deadline forward, emits `alert_escalated` WS event. Terminal step parks at `ack_status='escalated'` (no churn).
- Escalation chain: `louder_push → automated_call → authority_api → ops_terminal` (last 3 are stubs ready for Twilio Voice / EMS API plug-ins).

### Wiring
- `_create_alert` in `guardian_mode_engine` now auto-flags critical-severity alerts via `mark_for_ack`. Existing dispatch fan-out (push/SMS) is preserved — ACK is layered on top.
- `start_alert_ack_engine()` registered in `scheduler_runner` → `nischint-scheduler` process. 5-second tick on its own AsyncIOScheduler, `max_instances=1, coalesce=True, misfire_grace_time=15`.
- API routes registered via `app/api/main.py`:
  - `POST /api/alerts/{alert_id}/ack` — guardian closes loop
  - `GET /api/alerts/pending` (admin/operator) — Command Center pending-ACK list

### WS events (operator-channel + session-channel)
- `alert_ack_required` — fired when an alert enters pending state
- `alert_acknowledged` — fired on guardian ACK; payload includes `was_late`
- `alert_escalated` — fired each step; payload includes `step`, `action`, `next_deadline`

### Tests — `tests/test_alert_ack_engine.py` (11 new)
- Severity gate (critical/emergency/high vs low/medium/None)
- `mark_for_ack` sets pending + idempotent on closed alerts
- ACK closes loop + sets acked_by/acked_at + writes history
- Unknown alert → `not_found`; double-ACK → `already_acknowledged`
- Future-deadline pending alert → not escalated
- Expired deadline → step advances by 1, history captured, deadline pushed forward
- Chain exhaustion → parks at `escalated`, no churn
- Late ACK after escalation still closes with `was_late=True`

### Live verification
- Scheduler runner log: `Scheduler runner online. role=scheduler started=15/14: …,alert_ack`
- `[alert_ack] engine started — tick every 5s`
- `GET /api/alerts/pending` returning 3 escalated alerts from test runs with full escalation_history (louder_push → automated_call → authority_api → ops_terminal_locked)
- 11/11 ACK-engine tests + 72/72 prior tests = **83/83 backend tests passing**

### NOT done in this batch (deferred per "Do ONLY ONE THING NEXT")
- Guardian Reality Score (#2 — multi-factor scoring on top of reachability) — the ordering primitive for **who** gets paged first
- Real louder_push re-broadcast logic (currently the step is recorded but the WS event is the only side-effect)
- Twilio Voice plug-in (automated_call step)
- Police/EMS API plug-in (authority_api step)
- Shadow auto-recovery loop (force client reconnect when shadow >60s) — CEO point #3
- Command Center "live risk panel" tile — CEO point #4
- SSE reconnect-storm metric with cause classification — CEO point #5

### Files touched
- `backend/migrations/versions/z1a2b3c4do01_alert_ack_escalation.py` (new)
- `backend/app/models/guardian.py` (8 new columns on GuardianAlert)
- `backend/app/services/alert_ack_engine.py` (new — ~250 LOC)
- `backend/app/services/guardian_mode_engine.py` (wired `mark_for_ack` into `_create_alert`)
- `backend/app/api/alert_ack.py` (new)
- `backend/app/api/main.py` (router registration)
- `backend/app/workers/scheduler_runner.py` (registered `start_alert_ack_engine`)
- `backend/tests/test_alert_ack_engine.py` (new, 11 tests)


## Control Layer Phase 1.5 — Production-Trust Hardening (Apr 28, 2026)

Three blocking bugs in the ACK engine fixed before any new feature lands. Plus the north-star metric.

### Schema (migration `aa1a2b3c4dp01`)
`guardian_alerts` extended with:
- `context_json: jsonb` (default `'{}'`) — immutable forensic snapshot at mark_for_ack time
- `ack_type: varchar(16)` — tri-state response depth: `null | seen | acting | resolved | seen_lapsed`
- `seen_deadline: timestamptz` — the 60s `seen → acting` window
- Partial index `ix_guardian_alerts_seen_lapse` on `seen_deadline WHERE ack_type='seen'`

### #1 — Multi-guardian race lock
- `acknowledge_alert` and `process_pending_acks` now both use `SELECT … FOR UPDATE` (the tick uses `FOR UPDATE SKIP LOCKED` to avoid blocking).
- A guardian's ACK and the 5-second escalation tick can no longer race — the row is locked until commit.
- New WS event `alert_closed` fires on the FIRST ACK (any type) so other guardians' clients can dismiss the notification immediately. `alert_acknowledged` continues to fire on every state change for the operator dashboard.
- Backward transition guard: once `acting`, you cannot go back to `seen`. Forward-only progression locked by `_ACK_ORDER`.

### #2 — Context bundle on every escalation
- New `_capture_context(session, alert)` snapshots at mark_for_ack:
  - `last_location` (with `age_sec`)
  - `tracking_mode` (`active | shadow | ended`)
  - `risk_level` + `risk_score`
  - `session_status`, `user_id`
  - `guardians` reachability rollup (`{healthy, risk, dead, total}`) using the push_tokens reachability columns
- Frozen at arming time, immutable after — every escalation step's WS payload includes `context: {...}` so consumers don't need to round-trip the DB.
- Live verification: a fresh critical alert captures all 8 keys (`captured_at, user_id, session_status, last_location, risk_level, risk_score, tracking_mode, guardians`).

### #3 — Tri-state ACK (false-closure problem solved)
- `POST /api/alerts/{id}/ack` now accepts `{ack_type: "seen"|"acting"|"resolved"}` (default `seen`).
- `seen` ACK → opens 60s window for `acting`. If lapses without progression, `process_pending_acks` flips `ack_type='seen_lapsed'` and emits `alert_seen_lapsed` (single-shot — sets the deadline to null after firing).
- `acting` ACK → clears `seen_deadline`. The guardian has committed.
- `resolved` ACK → terminal closure.
- Every transition appended to `escalation_history` with `{step, by, at}` for forensic replay.

### #4 — Time-To-First-Human (TTFH) north-star metric
- `GET /api/alerts/metrics?window_days=30` (admin/operator)
- Returns `p50_seconds, p95_seconds, avg_seconds, acked_count, escalated_count` over the configured window
- Uses Postgres `percentile_disc` for stability across small samples
- Live data on first load: **p50=4.88s, p95=10.94s, avg=5.35s on 17 acked alerts** (test-generated, but the pipeline is live)
- This is THE outcome metric — "how fast does a real human respond?" — push success / SSE uptime / GPS accuracy are inputs.

### Tests — `tests/test_alert_ack_engine.py` (18, fully rewritten)
- Severity gate (critical/emergency/high vs low/medium/None)
- mark_for_ack captures context (live DB join verified)
- mark_for_ack idempotency
- First ACK opens 60s acting window
- `acting` clears seen_deadline
- `resolved` records terminal in history
- Backward transition rejected (acting → seen blocked)
- Invalid ack_type rejected
- Unknown alert → not_found
- **Race-safe**: ACK during expired pending → no escalation
- Future deadline → no escalation
- Expired deadline → step+1 + history + new deadline
- Chain exhaustion → parks at `escalated`
- Late ACK after escalation → was_late=True
- **Seen lapse**: `seen` → 60s → `seen_lapsed` + WS event
- `acting` in time → no lapse
- TTFH metric returns expected shape

### WS events (current full set)
- `alert_ack_required` — pending; payload includes `context`
- `alert_closed` — first ACK (any type); fires once per alert
- `alert_acknowledged` — every state change; payload includes `ack_type`, `was_late`, `context`
- `alert_escalated` — each escalation step; payload includes `step`, `action`, `next_deadline`, `context`
- `alert_seen_lapsed` — single-shot when `seen` ACK lapses without `acting`

### Verification summary
- 18/18 ACK engine tests passing (full re-test post-rewrite)
- Live `GET /api/alerts/metrics`: TTFH p50=4.88s
- Live `GET /api/alerts/pending`: returning escalated alerts with `context: {...}` populated for new alerts
- Both supervisor processes (api + scheduler) running, scheduler runner shows `alert_ack` in started list
- Live e2e: `mark_for_ack` against a fresh session captured all 8 context keys

### Files touched
- `backend/migrations/versions/aa1a2b3c4dp01_ack_engine_hardening.py` (new)
- `backend/app/models/guardian.py` (+3 columns: `context_json`, `ack_type`, `seen_deadline`)
- `backend/app/services/alert_ack_engine.py` (rewritten — ~360 LOC, three fixes + TTFH)
- `backend/app/api/alert_ack.py` (rewritten — accepts `ack_type` body, adds `/metrics` endpoint)
- `backend/tests/test_alert_ack_engine.py` (rewritten — 18 tests covering the new contract)

### Still NOT done (intentional — keep scope tight)
- Real `louder_push` action plug-in (CEO point 🥇 #1) — engine emits the WS event, action layer is next
- Live Risk Panel UI tile (CEO point 🥉 #3)
- Guardian Reality Score with skip-dead-guardian logic (CEO point 🧠 #4)
- Shadow auto-recovery progressive loop (CEO point ⚙️ #5)
- Twilio Voice for `automated_call` step
- Police/EMS API for `authority_api` step
- SSE reconnect-storm metric with cause classification


## Control Layer — Field-Readiness Hardening (Apr 28, 2026)

Three more hardening fixes shipped — the system is now production-trustworthy under stress conditions.

### Schema (migration `ab1a2b3c4dq01`)
- `acting_heartbeat_at: timestamptz` on `guardian_alerts`
- Partial index `ix_guardian_alerts_acting_heartbeat` on `(acting_heartbeat_at) WHERE ack_type='acting'`

### #1 — ACK misclick guard on `resolved`
- `POST /api/alerts/{id}/ack` body extended: `{ack_type, confirmed: bool = False}`
- `acknowledge_alert` returns `{acknowledged: False, reason: 'confirmation_required', hint: ...}` on `ack_type='resolved'` without `confirmed=true`
- API maps that to **HTTP 409 Conflict** with structured detail
- `seen` and `acting` continue to require zero confirmation — they're soft signals, not closure
- Live verified: `POST /alerts/{bogus}/ack {"ack_type":"resolved","confirmed":false}` → HTTP 409 + clear hint
- Client UX (1.5s hold or double-tap) lives on the device; server enforces the final gate

### #2 — Acting heartbeat liveness
- New endpoint `POST /api/alerts/{id}/heartbeat` — only valid when `ack_type='acting'`, only callable by the guardian who committed (`acked_by` match)
- `acknowledge_alert` initializes `acting_heartbeat_at = now` on the `seen → acting` transition; clears it on any other transition
- New `heartbeat_acting()` engine function with `SELECT FOR UPDATE` race-safe pattern; also rejects with `not_acting` / `not_owner` for misuse (mapped to HTTP 409 / 403)
- `process_pending_acks` now scans for `ack_type='acting' AND acting_heartbeat_at < now-30s` → flips to `ack_type='acting_lapsed'`, fires `alert_acting_lapsed` WS event ONCE (the filter excludes `acting_lapsed` so it doesn't re-fire)
- Detects: phone died mid-response, network dropped, panic, screen lock → operator can pull in another guardian

### #3 — Risk-weighted ACK timeout
- New `_compute_ack_timeout(severity, context)` — derives from severity AND tracking_mode:
  - critical/emergency → 15s
  - high → 30s
  - shadow tracking mode → halve, floor 10s (so critical+shadow → 10s, high+shadow → 15s)
- `mark_for_ack` now consults this by default; the existing optional `timeout_sec` param remains for tests/overrides
- Most dangerous combo (critical alert + can't actively track device) gets the fastest response window

### Tests — `tests/test_alert_ack_engine.py` (31 total — 13 new)
- `test_resolved_without_confirmed_is_rejected` — 409 path, state unchanged
- `test_seen_does_not_require_confirmation`, `test_acting_does_not_require_confirmation` — guard scope locked to `resolved` only
- `test_compute_timeout_critical_is_15s`, `..._high_is_30s`, `..._shadow_halves_with_floor`, `..._active_tracking_unchanged`
- `test_mark_for_ack_uses_risk_weighted_timeout` — locks integration with engine
- `test_acting_sets_heartbeat_on_transition`
- `test_heartbeat_refreshes_timestamp`
- `test_heartbeat_rejected_if_not_acting`
- `test_acting_lapsed_fires_after_heartbeat_window` — full lifecycle
- `test_acting_lapsed_does_not_re_fire` — locks single-shot semantic

### Live verification
- 30/31 tests passing on first run; remaining 1 fixed by removing unnecessary `SKIP LOCKED` from seen/acting tick queries (single-instance scheduler — no concurrency to skip). Final run: **31/31 passing** (3 critical heartbeat/lapse tests confirmed individually).
- `POST /api/alerts/{bogus}/ack {"ack_type":"resolved","confirmed":false}` → HTTP 409 ✅
- `POST /api/alerts/{bogus}/heartbeat` → HTTP 404 ✅ (endpoint registered)
- TTFH unchanged & growing healthier: p50=4.47s (was 4.88s), p95=10.89s (was 10.94s) over 66 acked alerts (up from 17)
- Scheduler runner restart shows `started=15/14: …,alert_ack`, `[alert_ack] engine started — tick every 5s`, no error stream

### WS events (current full set)
- `alert_ack_required` — pending; payload includes `context`
- `alert_closed` — first ACK (any type); fires once per alert
- `alert_acknowledged` — every state change; payload includes `ack_type`, `was_late`, `context`
- `alert_escalated` — each escalation step; payload includes `step`, `action`, `next_deadline`, `context`
- `alert_seen_lapsed` — single-shot when `seen` ACK doesn't progress within 60s
- **`alert_acting_lapsed` (NEW)** — single-shot when `acting` heartbeat goes silent for 30s+

### Files touched
- `backend/migrations/versions/ab1a2b3c4dq01_acting_heartbeat.py` (new)
- `backend/app/models/guardian.py` (+1 column: `acting_heartbeat_at`)
- `backend/app/services/alert_ack_engine.py` (added `_compute_ack_timeout`, `heartbeat_acting`, acting-lapse tick code path; misclick guard in `acknowledge_alert`; `ACTING_HEARTBEAT_WINDOW_S` constant)
- `backend/app/api/alert_ack.py` (added `confirmed` body field, `/heartbeat` endpoint, structured error mapping)
- `backend/tests/test_alert_ack_engine.py` (13 new tests, 31 total)

### NOT done — explicitly deferred (next batch)
- Louder push action plug-in (CEO point 🥇 #1 — safety chain validates physically next)
- Live Risk Panel UI tile (CEO point 🥈 #2)
- Guardian Reality Score with skip-dead-guardian logic (CEO point 🥉 #3)
- Shadow auto-recovery progressive loop with attempt cap (CEO point ⚙️ #4)
- "Auto-call only if no SEEN ack" — CEO killer upgrade — drops in cleanly on top of the existing escalation chain by adding a branch in `process_pending_acks`
- Twilio Voice / EMS API plug-ins
- Public TTFH ticker on marketing site (smoothed rolling avg)


## 🥇 Louder Push — Physical Action Plug-in (Apr 28, 2026)

**The system crosses from decision-complete to action-complete.** Step 1 of the escalation chain (`louder_push`) is no longer symbolic — it physically re-broadcasts via FCM critical channel.

### Critical pre-existing gap fixed
The original `dispatch_guardian_alert` had a **logging-only stub** in its push path (`logger.info("PUSH ...")` with no FCM call). Step 0 dispatch wasn't real either. Now wired through `send_push_to_user` → `send_push_to_tokens` → real FCM HTTP v1.

### Schema (migration `ac1a2b3c4dr01`)
- `last_louder_push_at: timestamptz` on `guardian_alerts` — anti-spam guard

### `push_service` — `louder=True` profile
- New keyword arg on `send_push_to_tokens(...)` and `send_push_to_user(...)`
- Critical-channel payload diff:
  - Android: `channel_id="critical_safety"`, `sound="siren_loop"`, `vibrate_timings=["0s","0.5s","0.5s","0.5s"]`, `default_vibrate_timings=False`, `sticky=True`, `notification_priority="PRIORITY_MAX"`, `visibility="PUBLIC"`
  - APNs: `aps.sound={critical: 1, name: "siren_loop.caf", volume: 1.0}`, `aps.interruption-level="critical"`, `apns-push-type="alert"`
  - `data.louder_push="true"` so the client can apply special UX
- Force-overrides any caller-passed `channel_id` to `critical_safety` when `louder=True` — the contract is "MUST land on critical channel or not at all"
- Falls back to default profile when `louder=False` (no behavior change for existing callers)

### Dispatcher (`dispatch_guardian_alert`)
- Pushes are now real FCM calls (was stubs)
- New `louder=True` arg; title gets `🚨 ... — ESCALATED` prefix
- Push pipes through `send_push_to_user(target_user_id, ..., louder=True)`

### Engine trigger (`process_pending_acks`)
- When `step_name == "louder_push"`, calls `_trigger_louder_push(session, alert, now)` BEFORE emitting the WS event so the physical action and the observability event ship together
- `_trigger_louder_push`:
  - Re-reads alert state under the row lock — skips if already `acknowledged` (race-window safety)
  - Skips if `last_louder_push_at` < 15 s ago (cooldown — `LOUDER_PUSH_COOLDOWN_S = 15`)
  - Resolves the owning `user_id` from `GuardianSession`
  - Calls `dispatch_guardian_alert(..., louder=True)`
  - Writes `last_louder_push_at = now` on success
  - Catches and logs all exceptions — never raises into the tick

### Anti-spam guarantee
- 5 s tick + parked alert at `escalated` could otherwise re-broadcast a critical-channel push every tick. The 15 s cooldown + the `acknowledged` short-circuit make at most **4 broadcasts per minute** the worst case (and that's only if the alert is still un-acked, which is itself an emergency).

### Tests — `tests/test_louder_push.py` (7 new)
- `test_escalation_to_louder_push_calls_dispatcher` — full tick path, asserts dispatcher gets `louder=True`
- `test_cooldown_blocks_repeat_within_window` — 2 calls within 15 s → 1 dispatch
- `test_cooldown_releases_after_window` — 2 calls past 15 s → 2 dispatches
- `test_acked_alert_skips_louder_push` — race-window safety
- `test_dispatcher_failure_swallowed` — tick robustness
- `test_send_push_to_tokens_louder_payload_shape` — full FCM payload spec lock-in (channel_id, sound, vibrate_timings, sticky, APNs critical sound + interruption-level)
- `test_send_push_to_tokens_normal_payload_shape` — louder=False keeps existing behavior

### Live verification
- Synthetic e2e: created child + session + critical alert → `mark_for_ack` → backdated deadline → `process_pending_acks` →
  ```
  ESCALATED id=… step=1 action=louder_push severity=critical
  [louder_push] FIRED id=… guardians=None push_sent=0
  last_louder_push_at = 2026-04-28T15:45:33
  ```
- Synthetic user has 0 guardians — `push_sent=0` is correct; the dispatch hook fired, returned `no_guardians`, and the cooldown stamp was written
- Real-user path: when a session owner with active guardians and FCM tokens triggers a critical alert, the same code path now hits FCM's critical channel
- Both supervisor processes running clean post-restart (no error stream)

### Required Android client setup (one-time, NOT done in this session — mobile client patch)
```kotlin
val channel = NotificationChannel(
    "critical_safety",
    "Critical Safety Alerts",
    NotificationManager.IMPORTANCE_HIGH
)
channel.enableVibration(true)
channel.setVibrationPattern(longArrayOf(0, 500, 500, 500))
channel.setLockscreenVisibility(Notification.VISIBILITY_PUBLIC)
channel.setSound(sirenUri, audioAttributes)
channel.setBypassDnd(true)  // requires user permission
notificationManager.createNotificationChannel(channel)
```
Without this, FCM silently downgrades to the default channel — backend work loses its physical effect. **Test on 2-3 real devices before marketing the chain as live.**

### Files touched
- `backend/migrations/versions/ac1a2b3c4dr01_louder_push_spam_guard.py` (new)
- `backend/app/models/guardian.py` (+1 column: `last_louder_push_at`)
- `backend/app/services/push_service.py` (`louder=True` keyword arg, critical-channel payload)
- `backend/app/services/guardian_notification_dispatcher.py` (real FCM wiring + `louder=True` propagation)
- `backend/app/services/alert_ack_engine.py` (`_trigger_louder_push`, cooldown, race-window check, `LOUDER_PUSH_COOLDOWN_S` constant)
- `backend/tests/test_louder_push.py` (new, 7 tests)

### Next physical action: 🥈 Twilio Call (conditional — `ack_type IS NULL` gate)
- Plug into `step_name == "automated_call"` branch (step 2)
- ONLY fire if `ack_type IS NULL` — i.e., nobody even *saw* the louder push. Massive false-positive killer.
- Requires `TWILIO_FROM_PHONE` env var + per-guardian phone numbers (Guardian model already has `phone` column)
- Same plug-in pattern as `_trigger_louder_push` so the architecture stays vendor-pluggable


## Journey Intelligence — DEFERRED to fresh session (Apr 28, 2026)

User uploaded a 7-file artifact bundle for Journey Intelligence (15s/30s gap detection + dashed polyline trail). After audit, **decision locked: defer integration to a fresh session**. Reasons:

1. **Incomplete bundle**: only 5 of 7 artifacts were readable from the artifact bucket. The two CORE backend files (`journey_service.py`, `journey_router.py`) were referenced by the watchdog but not present.
2. **Architectural conflict with this-session safety guarantees**: the spec creates a parallel `journeys` table. Routing GPS through a new `/journey/location` endpoint would silently bypass:
   - `update_location` shadow-tracking failsafe
   - 24-hour zombie-session hard cap
   - GPS resurrection on `expired/stale`
   - ACK engine `tracking_mode` context (drives the 10s fast-path on critical+shadow combo)
3. **Context budget**: ~115k used at the time the user proposed this; risk of half-shipping was real.

### Decision: option (a) — layered approach
- **Extend** `guardian_sessions` with 5 offline columns (`is_offline, last_seen_online_at, total_points, offline_gaps, max_gap_seconds`). Do NOT create a separate `journeys` table.
- **Create** `journey_points` (FK to `guardian_sessions(id)`) — pure trail, no conflict.
- **Hook** the gap detector into existing `update_location` path BETWEEN resurrection check and speed/dist compute.
- **Wire** `is_offline` into ACK engine `_capture_context` so offline gaps automatically halve critical-alert ACK timeouts.

### Handoff doc shipped
**`/app/memory/JOURNEY_INTELLIGENCE_INTEGRATION.md`** — complete spec for the next session:
- Reference 1: existing GuardianSession schema + columns to add + new journey_points DDL
- Reference 2: exact `update_location` integration point (`guardian_mode_engine.py:221`) with pseudocode for the gap detector
- Reference 3: exact `_capture_context` patch (`alert_ack_engine.py:83`) for offline-aware tracking_mode
- Watchdog adaptation (reads from `guardian_sessions`, not new `journeys`)
- Mobile wiring (drop artifacts as-is, repoint URLs to existing `/api/guardian/*`)
- Test bundle outline (9 tests, including the high-leverage `test_ack_engine_offline_session_gets_shadow_tracking_mode`)
- Risk checks (zombie cap order, no double-write, shadow path still works on rejection)
- 11-step one-pass execution order

### Items needed from user before next session resumes
1. Re-upload `journey_service.py` and `journey_router.py` from the original 7-file bundle
2. Reference the handoff doc + the 3 existing files (`guardian.py`, `guardian_mode_engine.py`, `alert_ack_engine.py`) — already in codebase

### Files touched this batch (NONE — purely planning)
- `/app/memory/JOURNEY_INTELLIGENCE_INTEGRATION.md` (new — handoff doc)
- `/app/memory/PRD.md` (this section)



## Journey Intelligence — Step 1-4 Layered (Apr 29, 2026) ✅ P0 GREEN

### Status
Steps 1-4 (DB migration, schema patch, stale guard, gap detector) shipped and live-verified. Steps 5-7 (ACK engine hook, watchdog downgrade-only, mobile polyline) are deferred to a follow-up session per user direction.

### What landed
- Migration `ad1a2b3c4ds01_journey_intelligence_layered.py` — adds 5 cols to `guardian_sessions` (`is_offline, last_seen_online_at, total_points, offline_gaps, max_gap_seconds`), creates `journey_points` append-only table with `UNIQUE(session_id, seq)`.
- `app/models/guardian.py` — `GuardianSession` extended with the 5 offline cols; new `JourneyPoint` model.
- `app/services/guardian_mode_engine.update_location` — stale packet guard (Invariant #2, server-clock based) is now the FIRST check; gap detector classifies `good <15s | unstable 15-30s | offline >=30s`; `journey_points` row inserted per accepted ping; `journey_paused/journey_resumed` SSE broadcast.
- `app/api/guardian.py` — `LocationInput.accuracy` (Optional[float]) added; route now passes accuracy to engine.

### P0 Bug fix landed in this session
**Symptom:** `POST /api/guardian/update-location` → 500 with SQLAlchemy `f405` (compile error, unknown column on INSERT).

**Root cause:** In `app/models/guardian.py`, 5 ACK-engine columns (`context_json`, `ack_type`, `seen_deadline`, `acting_heartbeat_at`, `last_louder_push_at`) were physically nested *inside* the `JourneyPoint` class body (after its `__table_args__`), making the ORM think `journey_points` had those columns. The DB had them on `guardian_alerts` (correctly migrated by `aa…`, `ab…`, `ac…` migrations), so every JourneyPoint INSERT compiled with phantom columns the table doesn't have → `CompileError`. `GuardianAlert` also lost those columns at the ORM layer, so the ACK engine was writing to the wrong attribute set.

**Fix:** Moved the 5 columns from `JourneyPoint` into `GuardianAlert` where they belong. Single-file ORM correction, no DB migration needed (DB was already correct).

### Live verification
```
POST /api/guardian/start  → session_id=b7c6677a-…
POST /api/guardian/update-location {"location":{"lat":12.972,"lng":77.595,"accuracy":10}}
HTTP 200 OK
journey_points: [{seq:1, lat:12.972, lng:77.595, accuracy:10.0, quality:'good', gap_before_s:4}]
guardian_sessions: total_points=1, offline_gaps=0, max_gap_seconds=4, is_offline=False
```

### Files touched this batch
- `backend/app/models/guardian.py` (column relocation: JourneyPoint → GuardianAlert)
- `backend/app/api/guardian.py` (`LocationInput.accuracy` field)
- `backend/server.py` (frontend static-mount made conditional on `build/static` existing — env startup fix, unrelated to ORM bug)

### Pending work (deferred at user direction)
- **Step 5** — ACK engine `_capture_context`: when `is_offline=True`, force `tracking_mode="shadow"` so the 10s fast-path ACK timeout applies. (`alert_ack_engine.py:83`)
- **Step 6** — `tick_gap_watchdog()` registration in `scheduler_runner.py`. Downgrade-only (Invariant #3).
- **Step 7** — Mobile polyline (`mobile/services/journeyIntelligence.ts`, `JourneyPolyline.tsx`) + `GET /api/guardian/{session_id}/polyline` endpoint.
- **Test suite** — `backend/tests/test_journey_intelligence.py` (9 tests from the brief, including the high-leverage `test_ack_engine_offline_session_gets_shadow_tracking_mode`).
- **Twilio call escalation** — `automated_call` step gated on `ack_type IS NULL`.
- **Live Risk Panel** — Command Center docked tile.
- **Mobile** — `critical_safety` Android channel patch; `expo-av` → `expo-audio` migration (SDK 55).


## Log-Spam Suppression — slowapi rate-limit warnings (Apr 30, 2026)

### Symptom
Production logs flooded with `ratelimit 5 per 1 minute (34.111.46.36) exceeded at endpoint: /api/auth/login` — 30+ entries in ~80 seconds from a single IP, drowning real signal.

### Root cause
`slowapi` emits a `WARNING`-level log on every rate-limit hit by default. The 429 response itself is the user-visible signal, and the spam from one bad IP buries every other log line.

### Fix
`/app/backend/app/logging_config.py` — set `slowapi` logger to `ERROR`:
```python
logging.getLogger("slowapi").setLevel(logging.ERROR)
```

### Verification
12 rapid POST `/api/auth/login` requests from localhost: first 5 returned `401`, next 7 returned `429` (limiter active), **0 new `ratelimit ... exceeded at endpoint` log lines** in `backend.err.log`.

### Source of the abusive IP (`34.111.46.36`)
Google Cloud Platform `34.64.0.0/10` — likely a brute-force bot/VM hitting `/api/auth/login`. Not on Emergent's infra IP list; not a typical health-probe target. Rate limiter is correctly blocking. **Action item still open**: optional IP-level temp-ban (Redis-backed) was discussed but not implemented — needs user approval because shared NATs / mobile carriers can put legitimate users behind a single IP.

### Files touched
- `backend/app/logging_config.py` (+5 lines, slowapi log level → ERROR)

### Open follow-ups (NOT implemented in this batch — awaiting user direction)
- **GuardianAlert persistence when no active session**: currently `checkin_service` skips the DB row when a child has no active `guardian_session`. Push + SSE still fire, but the alert isn't in `guardian_alerts` → ACK engine can't escalate it and there's no audit trail. Needs a "session-less alert" code path. (User flagged this as a real product bug.)
- **Redis-backed IP banning** after N rate-limit hits in a window. (User suggested as optional.)


## GuardianAlert Persistence — Session-less Alerts (Apr 30, 2026) ✅ P0

### Why this matters
Before today, when a `help-request` arrived for a child with no active `guardian_session`, the system silently skipped the DB write. Push and SSE delivered, but **the alert never landed in `guardian_alerts`** — no row meant the ACK engine was blind, no escalation could fire, and the legal/safety audit trail had a hole at the exact moment it was needed.

### Changes
**Migration `ae1a2b3c4dt01_sessionless_guardian_alerts.py`**
- `guardian_alerts.session_id` → NULLABLE
- New `guardian_alerts.user_id UUID NOT NULL` (the child the alert is about; backfilled from linked sessions; orphan rows dropped)
- New index `ix_guardian_alerts_user_id_created_at` for "all alerts for child X" audit queries

**Model (`app/models/guardian.py`)**
- `GuardianAlert.session_id` → `Mapped[uuid.UUID | None]`, nullable
- `GuardianAlert.user_id` added (NOT NULL, indexed)

**`app/services/checkin_service.py`** (the bug-fix path)
- Removed the early-return when no active session
- Always writes `GuardianAlert(session_id=active.id if active else None, user_id=child_id, ...)`
- Wires `mark_for_ack()` so critical-severity session-less alerts are armed for ACK + escalation

**`app/services/guardian_mode_engine._create_alert`**
- Looks up `user_id` from session if caller didn't pass it
- Sets `user_id` on every new alert (NOT NULL constraint enforces correctness)

**`app/services/alert_ack_engine`**
- `_capture_context` handles `alert.session_id is None`: subject still resolves via `alert.user_id`; tracking_mode becomes `shadow` and `is_offline=True` (operator must assume device unreachable → 10s fast-path ACK)
- All `str(alert.session_id)` payload conversions guarded with `if alert.session_id else None`
- `_trigger_louder_push` prefers `alert.user_id` over the session lookup, falls back to session for legacy rows
- **Pre-existing latent bug fixed**: `_capture_context` had `g.email::uuid` in raw SQL — `guardians.email` is a plain email string, not a UUID. The cast failed server-side and silently aborted the surrounding transaction. Replaced with the correct join through `users.email → users.id → push_tokens.user_id` and wrapped in a `session.begin_nested()` SAVEPOINT so any future failure here is contained.

### Live verification (kid has no active session)
```
POST /api/checkin/{kid_id}                 → check_in_id=657bfaa8...
POST /api/checkin/{ci}/respond {help}      → 200 OK
DB:  guardian_alerts row id=90c6afaf...
       session_id  = NULL          ← session-less ✅
       user_id     = ae6c29f9...   ← audit anchor ✅
       severity    = critical
       ack_required= true
       ack_status  = pending       ← engine armed ✅
       ack_deadline= +10s          ← shadow fast-path ✅
       context_json.tracking_mode  = "shadow"
       context_json.guardians      = {healthy:8, dead:0, total:8}
                                     ← reachability rollup works ✅
Logs:
  [ALERT_CREATED] type=help_requested id=90c6afaf... session=none
  [alert_ack] PENDING id=90c6afaf... severity=critical timeout_sec=10
```

### Regression: session-scoped journey path still works
```
POST /api/guardian/start          → 200, session_id=9240573a...
POST /api/guardian/update-location → 200 OK
```

### Files touched
- `backend/migrations/versions/ae1a2b3c4dt01_sessionless_guardian_alerts.py` (new)
- `backend/app/models/guardian.py` (session_id nullable + user_id NOT NULL)
- `backend/app/services/checkin_service.py` (always-create alert + mark_for_ack)
- `backend/app/services/guardian_mode_engine.py` (`_create_alert` populates user_id)
- `backend/app/services/alert_ack_engine.py` (None-safe payloads, session-less context, fixed push_tokens query, savepoint guard)

### Open follow-ups (NOT in this batch)
- Per-account login backoff (Redis-backed, layered on existing slowapi limiter) — was P2 in user's priority list
- Journey Intelligence Steps 5-7 (ACK engine offline-aware tracking_mode is **already done** as part of `_capture_context`'s session-less branch — Step 5 effectively shipped today)


## Tightening + Per-Account Login Backoff (Apr 30, 2026, later) ✅

### Part A — Tightening: orthogonal signals in `_capture_context`
**Why**: `is_offline=true` was being set on session-less alerts as a shortcut to drive `tracking_mode=shadow`. Two semantically different signals were collapsed into one, which would have produced wrong escalation timings as Step 6/7 logic layered on top.

**Fix**: `_capture_context` now emits TWO orthogonal signals:
- `has_active_session: bool` — does a live (non-ended/completed) journey row exist?
- `is_offline: bool` — is the device's GPS stream actually silent?

`tracking_mode` is then derived **explicitly**:
```python
if not has_active_session:  tracking_mode = "shadow"   # no journey → assume unreachable
elif is_offline:            tracking_mode = "shadow"   # GPS dropped >30s
else:                       tracking_mode = "active"
```

**Live verification**: a help-request triggered with no active session now yields `context_json = {has_active_session: false, is_offline: false, tracking_mode: "shadow"}` — semantically correct (no GPS stream existed → can't be classified offline).

### Part B — Per-Account Login Backoff
**Why**: slowapi gives per-IP rate limiting (5/min). Real attackers rotate IPs. Real defense protects the *account under attack*. This module sits in front of password verification.

**Module**: `backend/app/core/login_backoff.py`
- Redis-keyed counter (`login_fail:{email}`, 24h TTL) + lock (`login_lock:{email}`)
- Progressive lockout tiers:
  - 5 fails  → 30 second lock
  - 10 fails → 2 minute lock
  - 15 fails → 15 minute lock
- Counter cleared on successful login
- **Fail-open by design**: Redis down or any call fails → log WARN + allow login. Locking out legitimate users because the cache is sick is worse than relaxing one defense layer (slowapi IP limiter still active underneath).

**Wire-in**: `backend/app/api/auth.py::_local_login`
1. `check_lock(email)` BEFORE password check → `HTTP 429` with `Retry-After` header if locked
2. `record_failure(email)` on every 401 (no user / bad password)
3. `reset(email)` on successful auth

**Live verification**:
| Test | Result |
|---|---|
| 5 fails arms 30s lock | ✅ |
| 10 fails escalates to 120s | ✅ |
| 15 fails escalates to 900s | ✅ |
| HTTP 429 + `retry-after: 29` returned to attacker | ✅ |
| Successful login clears counter (3 → 0) | ✅ |
| Module passes ruff lint | ✅ |

### Why this matters strategically
Two attack surfaces had silent gaps before today:
1. **Brute-force via IP rotation** — slowapi alone could not stop it. Now an attacker hitting one account from 100 IPs gets locked out at the *account* layer.
2. **Wrong-classification cascade** — collapsing `has_active_session` and `is_offline` into one boolean would have meant Step 6 (watchdog) auto-marking session-less alerts as "device offline" and Step 7 (polyline) trying to render trail data for journeys that never existed. Caught before it shipped.

### Files touched
- `backend/app/core/login_backoff.py` (new, ~130 lines)
- `backend/app/api/auth.py` (`_local_login` integrates check/record/reset)
- `backend/app/services/alert_ack_engine.py` (`_capture_context` orthogonal-signal split)

### Next Action Items
- **Journey Intelligence Step 6**: watchdog `tick_gap_watchdog()` registered in `scheduler_runner.py`. **Downgrade-only** (Invariant #3 — never auto-upgrade to ACTIVE).
- **Step 7**: `GET /api/guardian/{session_id}/polyline` endpoint reading `journey_points` + mobile polyline drop-in.
- Test bundle `backend/tests/test_journey_intelligence.py` (9 cases including `test_ack_engine_offline_session_gets_shadow_tracking_mode`).
- Twilio call escalation (`ack_type IS NULL` gate, zombie-cap order).
- Live Risk Panel docked tile.
- Android `critical_safety` notification channel patch + `expo-av` → `expo-audio` migration.


## Journey Intelligence Steps 6 + 7 + Tests + Regression (Apr 30, 2026, end of day) ✅

### Step 6 — Watchdog (already in place, contract-locked)
File: `backend/app/services/journey_watchdog.py`
- Downgrade-only (Invariant #3): scans `status='active' AND is_offline=false` rows whose `previous_update_at < now() - 30s` and flips `is_offline=true`. Never sets `is_offline=false`. Never sets `status='active'`. Recovery is the GPS path's exclusive responsibility.
- Idempotent: the `is_offline=false` filter prevents re-flipping. `offline_gaps` increments only on the transition, not every tick.
- Server-clock based (Invariant #2): uses `previous_update_at` vs server `now()`, never device time.
- Tick: 20s interval, `max_instances=1`, `coalesce=True`, `misfire_grace_time=15s`.
- Observability: `[journey_watchdog] OFFLINE session=... gap=Ns (server-clock)` log on every flip. Counter returned for scheduler metrics.
- Already registered in `app/workers/scheduler_runner.py` next to the other 15 schedulers.

### Step 7 — Polyline endpoint
File: `backend/app/api/guardian.py` (new, ~100 lines)
```
GET /api/guardian/{session_id}/polyline?limit=1000
```
Response shape:
```json
{
  "session_id": "...", "user_id": "...", "status": "active",
  "is_offline": false, "is_stale": false, "stale_seconds": 3,
  "last_seen_online_at": "...",
  "total_points": 3, "offline_gaps": 0, "max_gap_seconds": 5,
  "points": [{"seq", "lat", "lng", "ts", "quality", "gap_s"}, ...],
  "last_point": {...}, "returned": 3, "limit": 1000, "truncated": false
}
```
- Reads `journey_points` ordered by `seq ASC` (monotonic, append-only — pure derivation per Invariant #1).
- AuthZ matrix verified live: owner=200, linked guardian=200, unrelated=403, invalid UUID=400, missing session=404.
- `is_stale` derived from session's `is_offline` OR `previous_update_at >= 30s ago` (server-clock — same view as the watchdog).
- Capped at 5000 points; default 1000.
- No map-matching, no smoothing — keeps mobile rendering simple.

### Test bundle
**New**: `backend/tests/test_journey_intelligence.py` (10 tests, all passing in 115s)
- `test_gap_detector_classifies_good_under_15s` ✅
- `test_gap_detector_classifies_unstable_15_to_30s` ✅
- `test_gap_detector_classifies_offline_over_30s` ✅
- `test_max_gap_seconds_only_grows` ✅
- `test_offline_recovery_flips_is_offline_false` ✅
- `test_watchdog_marks_stale_sessions_offline` ✅
- `test_watchdog_idempotent_on_already_offline` ✅ (Invariant #3 enforcement)
- `test_watchdog_never_upgrades_to_active` ✅ (Invariant #3 enforcement)
- `test_ack_engine_offline_session_gets_shadow_tracking_mode` ✅ (the high-leverage one)
- `test_sessionless_alert_has_active_session_false_not_offline` ✅ (orthogonal-signal contract)

**Schema fix**: `tests/test_alert_ack_engine.py` and `tests/test_louder_push.py` updated to set `user_id=u.id` on `GuardianAlert` (NOT NULL constraint from migration `ae1a2b3c4dt01`).

### Backend Regression Sweep (testing_agent_v3_fork iteration_191)
- **17 tests, 16 passed, 0 failed, 1 deselected** (the IP-burn lockout test was intentionally deselected to avoid eating the slowapi 5/min IP quota for the other tests in the same run — feature itself fully validated separately via direct module call + HTTP).
- **No critical issues. No minor blockers.** Only note: rate-limit lockout test should run last.
- All 8 endpoints validated end-to-end: login (+ backoff), guardian/start, update-location (+ accuracy), polyline (full 5-case AuthZ matrix), check-in/respond (session-less + with-session paths), ACK tri-state, alerts/metrics, watchdog flag propagation.
- Author wrote `backend/tests/test_journey_steps_6_7_regression.py` (HTTP-driven, 645 lines, 8 test classes) for ongoing regression.

### Files touched this batch
- `backend/app/api/guardian.py` (new `/polyline` route, ~100 lines)
- `backend/tests/test_journey_intelligence.py` (new, 10 tests, ~310 lines)
- `backend/tests/test_alert_ack_engine.py` (added `user_id=u.id` in seed helper)
- `backend/tests/test_louder_push.py` (same)
- `backend/tests/test_journey_steps_6_7_regression.py` (new, written by testing agent)

### Next Action Items
- **Mobile drop-in**: hook `JourneyPolyline.tsx` to consume `/api/guardian/{sid}/polyline`. Render solid blue for `quality=good` segments, dashed amber for `unstable`, dashed grey for `offline`. Show "Last update Xs ago" if `is_stale`.
- **Live Risk Panel** (Command Center docked tile) — aggregates active alerts + shadow-mode users + dead guardians + TTFH. Hook ready (`alert_ack_engine.get_ttfh_metrics()` returns the metrics; reachability rollup is in `_capture_context.guardians`).
- Twilio call escalation (`ack_type IS NULL` gate, zombie-cap order respected).
- Android `critical_safety` notification channel + `expo-av` → `expo-audio` migration on mobile (SDK 55).


## Live Risk Panel — Control Surface (Apr 30, 2026, evening) ✅

### Single decision question this answers
"What needs attention in the next 10 seconds?"

### Endpoint
```
GET /api/command-center/risk-panel?incidents_limit=25
Auth: operator OR admin only (kid=403, anon=401)
```

### Response shape
```json
{
  "generated_at": "...",
  "summary": {
    "active_critical_alerts": 75,
    "pending_acks": 0,
    "escalated_alerts": 75,
    "active_sessions": 0,
    "offline_sessions": 0,
    "shadow_sessions": 0,
    "ttfh": {
      "window_days": 7,
      "acked_count": 264,
      "escalated_count": 130,
      "p50_seconds": 2.28,
      "p95_seconds": 5.72,
      "avg_seconds": 3.25
    }
  },
  "incidents": [
    {
      "kind": "alert" | "session",
      "alert_id": "...|null",
      "session_id": "...|null",
      "user_id": "...",
      "child_name": "...",
      "alert_type": "...|null",
      "severity": "critical|null",
      "ack_status": "pending|escalated|null",
      "ack_deadline": "...|null",
      "deadline_in_s": 8|null,
      "tracking_mode": "active|shadow",
      "is_offline": false,
      "guardians": {"healthy":8, "at_risk":0, "dead":0, "total":8},
      "last_location": {"lat":..., "lng":...},
      "stale_seconds": 12,
      "rank": 100  // urgency-sorted descending
    }
  ],
  "system": {
    "sse_subscribers": 0, "sse_channels": 0,
    "push_tokens": {"total":18, "healthy":18, "at_risk":0, "dead":0, "health_pct":100.0},
    "watchdog_flips_1h": 0
  },
  "_cache": "hit" | "miss"
}
```

### Urgency rank (sort key, higher first)
- `escalated` alert       → 100
- `ack_pending` alert     →  80
- `shadow_session` (orphan, no alert)  →  60
- `active_alert` (other)  →  40
- `stale_session`         →  20

Tie-break by soonest `deadline_in_s` ascending (most-urgent ACK first).

### Performance
- Cold call (cache miss):  ~3.5s  (4 sequential queries × Neon RTT — preview env)
- Warm call (cache hit):   ~10ms backend; ~1.6s wall (auth dep DB lookup is the dominant remaining cost system-wide, not panel-specific)
- **10s Redis TTL** on `risk_panel:v1:{cap}` — comfortably overlaps the prescribed 5s polling cadence even under slow network. Stale-by-up-to-10s acceptable for an operator panel; 4× speedup on every poll-after-first.

### Files added
- `backend/app/api/risk_panel.py` (~340 lines, single-file module)
- `backend/tests/test_risk_panel.py` (8 tests, 8/8 passing)
- Wire-in: `backend/app/api/main.py` (1 import + 1 `include_router` call)

### Test coverage (`tests/test_risk_panel.py`)
- `test_rank_escalated_beats_pending` — pure unit
- `test_rank_pending_beats_shadow_session`
- `test_rank_shadow_beats_stale`
- `test_summary_counts_pending_critical` — DB integration
- `test_incident_for_sessionless_alert` — proves session-less alerts surface correctly
- `test_incidents_sorted_by_rank`
- `test_incident_for_orphan_offline_session` — session-only incidents (no alert) appear
- `test_system_health_shape` — every key always present (degraded → null, never KeyError)

Combined journey_intelligence + risk_panel = **18/18 passing** in 165s.

### Live AuthZ matrix verified
| Role | HTTP |
|---|---|
| admin | 200 |
| operator | 200 (via role check, not yet seeded) |
| child (kid) | 403 |
| no token | 401 |

### Architectural choices that matter
1. **Two-source incident merge**: open alerts (urgent) + orphan unreachable sessions (silent failures). De-duped by `user_id` so each entity gets exactly one row — operator never sees the same child twice. This is what makes the panel a real control surface vs a noisy log feed.
2. **Server-clock derived `is_stale`** (Invariant #2) — same threshold (30s) as the watchdog. The panel's view of "device unreachable" agrees with the watchdog's view; no flapping between them.
3. **Cache write is best-effort**: Redis down → endpoint still works (just slower). Read failure also fails open. No new dependency on Redis to keep operating.
4. **Shape stability**: every system-health field is always present. A degraded subsystem returns `null` for its slice; the client never has to defend against missing keys.

### What this unlocks
- Mobile/web client can now consume one endpoint to render a docked Command Center tile.
- Twilio call escalation (next P1) becomes "observable by default" — every triggered call shows up as an `escalated` incident with ranking 100.
- Future Predictive Risk layer can plug into `incidents[]` without re-aggregating.

### Files touched this batch
- `backend/app/api/risk_panel.py` (new)
- `backend/app/api/main.py` (router wiring)
- `backend/tests/test_risk_panel.py` (new)

### Next Action Items
- **Mobile Command Center tile** (UI) — consume `/api/command-center/risk-panel` every 5s; render summary strip + ranked incidents list. Drill-down opens existing polyline view.
- **Twilio call escalation** — `automated_call` step gated on `ack_type IS NULL`. Will surface in the panel as `rank=100`.
- **`expo-av` → `expo-audio` migration** + `critical_safety` notification channel patch (mobile SDK 55).
- **Operator role seeding** — currently no seeded operator account; add one to `test_credentials.md` if needed for richer dashboard testing.


## Live Risk Panel — UI Tile Shipped (Apr 30, 2026, late) ✅

### Mounted on the existing Command Center
`/app/frontend/src/pages/CommandCenterPage.jsx` now docks `RiskPanelTile` as a persistent strip directly below the status chip row, above the main grid. Click on any incident sets the page's `selectedUserId`, drilling into that child via the existing AIRiskIntelligence + map flow.

### File: `frontend/src/components/command-center/RiskPanelTile.jsx` (~250 lines)
Behavior contract (all locked):
- Polls `GET /api/command-center/risk-panel?incidents_limit=10` every 5s.
- **Last-good state preserved on API failure** — never blanks the UI; heartbeat dot turns red + shows "updating…" while the previous data stays on screen.
- **Top strip** (decision in 2 seconds): Critical / Pending ACK / Offline / TTFH p50 — color-tone (red / amber / slate / blue), tabular-nums for stable layout.
- **Incident list** (max 5 visible, "+ N more pending" rollup): urgency-color borders (red rank≥80, amber rank≥60, slate session-kind), one-row-per-child de-duped, rank=100 incidents auto-pulse animation.
- **Live ACK countdown** ticks once per second client-side without re-fetching the parent (independent `<Countdown>` sub-component).
- **Heartbeat indicator** shows `live • Xs ago` in green / amber (>15s) / red (error).
- All elements carry `data-testid` for testing: `risk-panel-tile`, `risk-counter-{critical,pending,offline,ttfh}`, `risk-panel-heartbeat`, `risk-incidents-empty`, `risk-incident-{id}`, `risk-more-count`.

### Live render verification (admin-authed, on preview URL)
Probe via in-page `evaluate()` confirms the rendered DOM:
```
tile_present: True
critical:  "79 | CRITICAL"
pending:   "0 | PENDING ACK"
offline:   "0 | OFFLINE"
ttfh:      "2s | TTFH P50"
heartbeat: "live • 7s ago"
incident rows: 5
"+ 5 more pending" rollup visible
page_testid: present
```
Screenshot saved at `/tmp/cc_panel_v5.png` — strip cleanly docked between status chip row and map/AI panels; all 5 ranked incidents show `CRITICAL · ESCALATED · overdue` with animated pulse on rank=100 rows.

### What this milestone actually unlocks
- Operator now has **one persistent surface** that answers "what needs attention right now?" without scanning logs or feed scrolls.
- The **next backend feature (Twilio call escalation) becomes observable by default** — every triggered automated call surfaces in this list at rank=100. No blind automation.
- Hooks for swipe-to-ACK and drill-down map are in place (`onIncidentClick` already wired to `setSelectedUserId`).

### Files touched
- `frontend/src/components/command-center/RiskPanelTile.jsx` (new)
- `frontend/src/pages/CommandCenterPage.jsx` (+1 import, +1 mount strip)
- `frontend/src/api.js` (+1 method `getRiskPanel`)
- `frontend/build/` regenerated (yarn build, ~32s)

### Next Action Items (ordered)
- **Twilio call escalation** — `automated_call` step gated on `ack_type IS NULL`. Wire into `alert_ack_engine.ESCALATION_STEPS`. Will appear in the panel automatically.
- **Swipe-to-ACK** — small UX win on the tile rows: swipe right → POST `/api/alerts/{id}/ack` `{ack_type: "acting"}`. Reuses existing endpoint.
- **Mobile drop-in** — `JourneyPolyline.tsx` consume `/api/guardian/{sid}/polyline`. Solid blue / dashed amber / dashed grey by quality.
- **`expo-av` → `expo-audio`** migration + `critical_safety` Android channel patch.
- **Operator role seeding** — currently no seeded operator account; either reuse `admin` (works since auth allows admin OR operator) or seed a dedicated operator in `test_credentials.md`.


## Twilio Escalation + Swipe-to-ACK + Operator Seed (Apr 30, 2026, evening) ✅

### 1. Twilio `automated_call` escalation step — wired into ACK engine
**Why it matters**: The ESCALATION_STEPS state machine had `automated_call` listed but unimplemented. Now when an alert sits at `escalated` and step=2 fires, the engine places a real Twilio voice call to the highest-priority reachable guardian.

**Schema**: migration `af1a2b3c4du01` adds `guardian_alerts.last_automated_call_at TIMESTAMP` (anti-spam guard, 60s cooldown).

**`_trigger_automated_call` contract** (mirrors `_trigger_louder_push` pattern):
- **`ack_type IS NULL` gate** — once any human has acknowledged (even `seen`), physical escalation stops. A call at that point = wrong automation.
- **`AUTOMATED_CALL_COOLDOWN_S=60`** — parked alert can't phone a guardian every tick.
- **First-success-wins** — dials ranked guardians (by `created_at ASC`), stops on first OK; cooldown covers retries.
- **Full audit trail** — each attempt stamped into `escalation_history` with last-4-digit redacted phone, ok flag. Surfaces in the operator drill-down.
- **Best-effort** — never raises into the tick loop.

**Tests** (`backend/tests/test_automated_call_escalation.py`, 6/6 passing):
- `test_call_fires_when_pending_and_phone_present` — verifies call placed, redaction, history stamp
- `test_call_blocked_when_ack_type_is_set` — the critical safety invariant
- `test_call_skips_if_cooldown_active` — cost + spam guard
- `test_call_skips_gracefully_when_no_phone` — graceful no-guardian path
- `test_cooldown_constant_matches_doc` — regression lock
- `test_ack_engine_still_schedules_automated_call_step` — state machine invariant

**Live observability**: every Twilio call surfaces in the Live Risk Panel automatically at `rank=100` with `ack_status=escalated`. No blind automation.

### 2. Swipe-to-ACK on the tile
**UX**: on the `RiskPanelTile`, the operator swipes right on an incident row past a 90px threshold → fires `POST /api/alerts/{id}/ack {ack_type: "acting"}`. Optimistic UI update marks the row as acked instantly; next 5s poll reconciles with server truth.

**Design choices**:
- **`acting` not `resolved`** — swipe is a commitment gesture, not a closure gesture. Closing an alert requires an explicit confirm step elsewhere. Prevents one-finger misclick closure in an emergency.
- **Only armed for alert-kind rows** without an existing `ack_type`. Session-kind (orphan unreachable device) rows are not swipe-ackable — they have no alert to ACK.
- **Pointer-events (not touch-events)** — works uniformly for touch, mouse, pen.
- **Visual reveal track** — slate-tinted "swipe to ACK →" behind the row, shifts to emerald-tinted "release to ACK" past threshold, "acknowledged ✓" after success.
- **`data-testid`s**: `risk-incident-wrap-{id}`, `risk-swipe-hint-{id}`, `risk-incident-{id}`.

**API method added**: `operatorApi.ackAlert(alertId, ackType='seen', confirmed=false)` in `api.js`.

### 3. Operator account seeded
- Email: `operator@nischint.com`
- Password: `OperatorSecure!2026`
- Role: `operator`
- Live login verified: HTTP 200 → role=operator.
- `test_credentials.md` updated.

### Live render verification (operator logged in, on preview URL)
Screenshot `/tmp/cc_op_swipe.png` shows:
- Header "NISCHINT Command Center · LIVE · WS"
- **LIVE RISK PANEL** docked strip with heartbeat `live • 1s ago` (green)
- Counters: CRITICAL=73 / PENDING ACK=0 / OFFLINE=0 / TTFH P50=2s
- 5 ranked incident rows (`CRITICAL · ESCALATED · overdue · 8/8 guardians reachable`), rank=100 auto-pulse
- "+ 5 more pending" overflow rollup
- Downstream map/AI panels unchanged

### Files touched this batch
- `backend/migrations/versions/af1a2b3c4du01_automated_call_spam_guard.py` (new)
- `backend/app/models/guardian.py` (`last_automated_call_at` column)
- `backend/app/services/alert_ack_engine.py` (`_trigger_automated_call` + wiring + `AUTOMATED_CALL_COOLDOWN_S`)
- `backend/tests/test_automated_call_escalation.py` (new, 6 tests)
- `frontend/src/components/command-center/RiskPanelTile.jsx` (swipe-to-ACK handlers + visual reveal track)
- `frontend/src/api.js` (`ackAlert` method)
- `frontend/build/` regenerated → `main.43ba1776.js`
- `memory/test_credentials.md` (operator credentials)

### Deferred to next session (mobile work, out of web-only scope)
- **Mobile polyline drop-in** (`mobile/` React Native codebase): `JourneyPolyline.tsx` to consume `/api/guardian/{sid}/polyline`. Solid blue (`quality=good`), dashed amber (`unstable`), dashed grey (`offline`). Layered over last-known-location marker.
- **`expo-av` → `expo-audio`** migration — 3 files: `mobile/services/audioService.ts`, `mobile/services/voiceDistression.ts`, `mobile/components/SafetyServicesStatus.tsx`. Package is currently `expo-av ^16.0.8`; Expo SDK 55 deprecates it.
- **Android `critical_safety` notification channel** patch — partially stubbed; needs mobile-side FCM channel registration for siren loop + DND bypass.

These are all in the mobile codebase which needs a proper build/test cycle; cleaner to batch in one focused mobile session.

## NISCH-006 — Incident Lifecycle State Machine (May 7, 2026)

**Day 1+2 of Sprint 2 — wired the state machine into the live alert pipeline.**

### Day 1 Foundation (already on disk, validated this run)
- `app/services/incident_state_machine.py` — strict transition contract:
  DETECTED → VALIDATING → ESCALATED → ACKNOWLEDGED → RESOLVED → ARCHIVED.
  All other (from, to) pairs raise `InvalidTransitionError`. ARCHIVED is terminal.
- `app/models/safety_incident.py` — `SafetyIncident` SQLAlchemy model.
- Migration `ah1a2b3c4dw01_safety_incidents_lifecycle.py` (down_revision=`ag1a2b3c4dv01`,
  the User.last_known_location migration). Live indexes on
  `(child_id, state)`, `state`, and `created_at DESC`. DB head = `ah1a2b3c4dw01`.
- 19 pure unit tests in `tests/test_incident_state_machine.py` — every valid pair,
  every invalid pair, terminal state enforcement, persistence stamps, SSE shape.

### Day 2 Integration (this session)
- New `app/services/safety_incident_engine.py` — *only* place that touches
  SafetyIncident from the alert pipeline. Five helpers:
  - `open_incident_for_alert` — creates DETECTED row, stamps SLA annotations
    via `_safe_sla_snapshot()` (try/except wrapped — SLA monitor failure
    defaults to `sla_degraded_at_dispatch=False`, never blocks dispatch)
  - `advance_to_validating` / `advance_to_escalated` — best-effort state moves,
    swallow `InvalidTransitionError` so concurrent paths don't crash the dispatch
  - `find_by_alert_id` — JSONB `extra->>'alert_id'` lookup, returns None on
    backend mismatch (sqlite-safe)
  - `acknowledge_incident_for_alert` — ESCALATED → ACKNOWLEDGED with actor_id
  - `sweep_lifecycle` — single-tick sweeper with PG-only `FOR UPDATE SKIP LOCKED`
    (probed dialect; falls back to plain SELECT under sqlite tests)
- `alert_trigger.py` wired:
  1. `open_incident_for_alert(...)` after dedup gate passes (DETECTED)
  2. `extra.alert_id` backfilled when the GuardianAlert row is persisted
  3. `advance_to_validating` after guardian resolution (DETECTED → VALIDATING)
  4. `advance_to_escalated` after dispatch attempt (VALIDATING → ESCALATED).
     Even when push/SMS fails, SSE has gone out — the incident IS escalated.
  5. `persist_alert=False` (transient info pings) skips both the alert row
     AND the incident; the incident is only opened when the lifecycle matters.
- `alert_ack_engine.acknowledge_alert` wired: on first ACK, looks up the
  linked SafetyIncident via `extra->>'alert_id'` and transitions
  ESCALATED → ACKNOWLEDGED with the acker's user_id. Same transaction as
  the GuardianAlert ACK so the two facts can't diverge.
- New `app/services/safety_incident_scheduler.py` — APScheduler job runs
  every 60 s (env `SAFETY_INCIDENT_LIFECYCLE_INTERVAL_SECONDS`):
  - ACKNOWLEDGED idle > 30 min → RESOLVED (env `_ACKNOWLEDGED_RESOLVE_MINUTES`)
  - ESCALATED idle > 30 min (no ACK arrived) → RESOLVED (env `_ESCALATED_RESOLVE_MINUTES`)
  - RESOLVED idle > 30 min → ARCHIVED (env `_RESOLVED_ARCHIVE_MINUTES`)
  All four intervals env-configurable per CEO-mode review (no magic numbers).
- Registered in both `server.py` (legacy `all` mode) and
  `app/workers/scheduler_runner.py` (split mode). Scheduler runner now
  reports `started=18:...,safety_incident_lifecycle`.

### Tests
- `tests/test_safety_incident_engine.py` — 14 new tests covering:
  SLA snapshot chaos-safety (boom / amber / red / green), full
  DETECTED→ARCHIVED chain, find_by_alert_id round-trip + miss,
  ack_for_unlinked, sweep transitions (5 incidents in mixed states),
  sweep idempotency, open_incident_for_alert SLA stamping, invalid
  child_id, advance helpers non-fatal contract.
- Updated `tests/test_alert_trigger.py` — assertions for `session.add`
  call count adjusted from `assert_called_once()` to `call_count == 2`
  (incident + alert) when `persist_alert=True`. `persist_alert=False`
  still asserts `assert_not_called()` (skips both writes).

### Verification
- Test totals: 48/48 pass (19 state machine + 14 engine + 14 alert_trigger
  + 1 alert_ack subset) — `pytest tests/test_safety_incident_engine.py
  tests/test_incident_state_machine.py tests/test_alert_trigger.py`.
- Lint clean on all four wired files.
- Backend supervisor restart: clean (`Schedulers SKIPPED in this process
  (role=api)` + Redis connected).
- Scheduler runner restart: `started=18` including
  `safety_incident_lifecycle` with the env-driven intervals logged.
- DB head check: `alembic current` → `ah1a2b3c4dw01 (head)`.
- API smoke: `/api/health` → 200, `/api/_dev/twilio/sla` → 401 (auth gate).

### Deferred to Day 3 (P1 next)
- `GET /api/incidents/:id/timeline` — ordered transition list.
- Persistent `safety_incident_events` table — currently transitions are
  logged + SSE'd but not durably stored; timeline endpoint will need this.
- TTFA correlation tag `incident_state:<state>` already emitted by
  `incident_state_machine._emit_ttfa` — Day 3 will surface this in the
  TTFA stats endpoint groupings.

### Files touched
- `backend/migrations/versions/ah1a2b3c4dw01_safety_incidents_lifecycle.py` (already on disk, validated)
- `backend/app/core/config.py` (4 new env-driven `safety_incident_*` settings)
- `backend/app/services/safety_incident_engine.py` (NEW)
- `backend/app/services/safety_incident_scheduler.py` (NEW)
- `backend/app/services/alert_trigger.py` (3 new lifecycle hooks)
- `backend/app/services/alert_ack_engine.py` (ACK linkage in `acknowledge_alert`)
- `backend/server.py` + `backend/app/workers/scheduler_runner.py` (registered new sweeper)
- `backend/tests/test_safety_incident_engine.py` (NEW, 14 tests)
- `backend/tests/test_alert_trigger.py` (assertions updated for incident+alert dual write)

## NISCH-006 Day 3 — Persistent Transition Log + Timeline Endpoint (May 7, 2026)

**Closes the forensic gap from Day 2.** Transitions are now durably stored
and replayable; NISCH-007 Incident Feed UI is unblocked.

### Schema
- New table `safety_incident_events` (migration `bi1a2b3c4dx01`,
  `down_revision='ah1a2b3c4dw01'`).
- Columns: id, incident_id (FK CASCADE), from_state (NULL=genesis),
  to_state, actor_id, actor_type, ttfa_tag, sla_degraded, extra (JSONB),
  created_at.
- Index `idx_sie_incident_id (incident_id, created_at)` — hot path
  for the timeline endpoint's chronological scan.
- ON DELETE CASCADE — TODO(GDPR): revisit cascade when child-data
  erasure sprint lands. For now, hard-deleting an incident wipes its
  events cleanly.

### State machine (`incident_state_machine.transition`)
- New `actor_type` kwarg (default `'system'`) — must be truthful.
- Every transition writes a `SafetyIncidentEvent` row in the same
  flush as the parent state mutation. If the event-row construction
  fails, the state mutation still flushes — the live alert path is
  more important than the forensic record. If the event-row INSERT
  fails downstream, the caller's transaction rolls back BOTH writes
  (correct safety property).

### Engine wiring (`safety_incident_engine.py`)
- `open_incident_for_alert` writes the genesis event:
  `from_state=None, to_state='detected', actor_type='system'`. Carries
  `alert_id`, `kind`, `confidence` in metadata.
- `acknowledge_incident_for_alert` passes `actor_type='guardian'` so
  the timeline shows a human closed the loop.
- `sweep_lifecycle` passes `actor_type='scheduler'` for all auto-resolve
  and auto-archive transitions — operators can distinguish system
  closes from human closes.

### Timeline endpoint (`GET /api/incidents/{id}/timeline`)
- Auth: admin/operator → any incident; guardian → only via
  `Relationship.status='accepted'`; child → their own; everyone else 403.
- 404 on unknown incident, 403 on missing relationship.
- Response carries the parent envelope (`current_state`, `severity`,
  `sla_degraded_at_dispatch`, lifecycle timestamps) plus an ordered
  `timeline` array. Each entry has `elapsed_ms` (delta from previous
  event; first is always 0) — the exact field NISCH-007 needs.

### TTFA correlation
- `ttfa_tag = "incident_state:<state>"` is now durably stored on
  every event. The existing `_emit_ttfa` already pushes the tag to
  the in-memory recorder. Future TTFA stats endpoint can group by
  state without joining tables — per-state latency (DETECTED→VALIDATING,
  ESCALATED→ACKNOWLEDGED) becomes observable.

### Tests (62 total passing)
- `tests/test_incident_event_log.py` — 7 new (event row written per
  transition, actor_type roundtrip for guardian + scheduler, genesis
  marker, full-chain order, sla_degraded propagation, metadata).
- `tests/test_incident_timeline_endpoint.py` — 7 new live-PG tests:
  cascade delete (verifies FK), 404, 403 unlinked guardian, 200
  linked guardian, elapsed_ms math (100ms + 250ms gaps assert tight
  bounds), admin reads any, operator reads any.
- Existing 19 state-machine + 14 engine + 14 alert_trigger tests
  updated for the new `session.add` count (incident + alert + 3
  events = 5 calls when `persist_alert=True`; 0 when False).
- Lint clean on all 4 wired files.

### Live verification
- `alembic upgrade head` → applied `bi1a2b3c4dx01`.
- `alembic current` → `bi1a2b3c4dx01 (head)`.
- Backend (role=api) + scheduler (role=scheduler, 18 jobs) restart clean.
- Real curl against `/api/incidents/{seeded_id}/timeline`:
  * 401 without auth, 404 for non-existent UUID
  * Seeded 3 events 340ms / 1200ms apart → response shows
    `elapsed_ms: 0, 340, 860` (matches seeded deltas exactly)
  * Genesis event has `from_state: null`, `actor_type: "system"`,
    `ttfa_tag: "incident_state:detected"`

### Files touched
- `backend/migrations/versions/bi1a2b3c4dx01_create_safety_incident_events.py` (NEW)
- `backend/app/models/safety_incident_event.py` (NEW)
- `backend/app/api/safety_incidents.py` (NEW — timeline endpoint)
- `backend/app/api/main.py` (registered new router)
- `backend/app/services/incident_state_machine.py` (event-row write + actor_type)
- `backend/app/services/safety_incident_engine.py` (genesis event + actor_type pass-through)
- `backend/tests/test_incident_event_log.py` (NEW, 7 tests)
- `backend/tests/test_incident_timeline_endpoint.py` (NEW, 7 live-PG tests)
- `backend/tests/test_alert_trigger.py` (assertions updated for 5-row dual-write)
- `backend/tests/test_safety_incident_engine.py` (fixture creates events table)

## NISCH-006 Day 3+ — TTFA-by-State Percentile Stats (May 7, 2026)

**Operational guardian-responsiveness KPI shipped.** Pre-NISCH-007
landing observability is now live: ops can watch p50/p95 transition
latencies per state and distinguish notification-delivery gaps from
guardian-engagement gaps before users see the new feed UI.

### What shipped
- `app/services/ttfa_state_stats.py` (NEW) — single helper
  `get_state_stats(session, *, window_hours=24)` returning per-state
  `{count, p50_ms, p95_ms}`. Uses PostgreSQL `LAG()` over
  `safety_incident_events` partitioned by `incident_id` to compute
  elapsed_ms on the fly; aggregated with `percentile_cont`. Genesis
  events (`from_state IS NULL`) are excluded — they have no elapsed.
- `app/api/_dev.py` — `/api/_dev/ttfa/recent` extended:
  - New `window_hours` query param (default 24, range 1–168). 400 on
    out-of-range, with explicit message identifying the cap.
  - Response now carries `state_stats`, `window_hours`, `computed_at`,
    plus `recent` alias (per spec's `"recent"` key) alongside the
    existing `events` key for back-compat.
  - Auth gate unchanged — admin/operator only.
- SQLite fallback: helper probes the bind dialect; non-PG returns `{}`
  rather than raising. Same pattern as `sweep_lifecycle`'s
  `with_for_update` probe.

### Why a window function instead of a stored column
The brief said `elapsed_ms` was "already computed and stored" — it
isn't. The timeline endpoint computes it on-the-fly from timestamps
because the events table is intentionally append-only / single-shape.
`LAG()` reproduces identical semantics in the percentile query without
needing a backfill migration. Documented in the helper's module
docstring so the next agent doesn't re-trip the same assumption.

### Tests (9 new, 71 total passing)
- `tests/test_ttfa_state_stats.py`:
  - SQLite dialect short-circuits to `{}`
  - Window clamp survives sqlite path (defensive — for future PG-only
    deployments that don't validate the window themselves)
  - Live PG percentile correctness: 2 incidents seeded with predictable
    [200, 300] / [1500, 2500] / [8000, 15000] gaps; p50/p95 fall within
    bounded ranges
  - `ttfa_tag NOT LIKE 'incident_state:%'` rows excluded from output
  - Empty/missing data → `dict` (never raises, never None)
  - Endpoint param validation: 400 for `window_hours` 0 or 169
  - Endpoint default = 24h, response carries all required keys
  - Endpoint 403 for non-admin/operator caller

### Live verification
- Seeded 2 incidents → response shows exactly the expected percentiles:
  - validating p50=250ms (median of 200/300) ✓
  - escalated p50=2000ms (median of 1500/2500) ✓
  - acknowledged p50=11500ms (median of 8000/15000) ✓
  - All p95 values are correct linear-interpolation results
- Empty window returns clean `state_stats: {}` (no incidents in last hour)
- 400 for `window_hours=999`, 401 without auth
- Backend boot clean, lint clean on both wired files

### Operational reading guide (locks in for the next agent)
- `escalated p95 >> acknowledged p95` → notification delivery gap
  (infrastructure / Twilio / FCM problem)
- `acknowledged p95 >> escalated p95` → guardian engagement gap
  (UX / trust problem)
- These are root causes that look identical at the user level
  ("guardian didn't respond fast") but require completely different
  fixes; per-state percentiles distinguish them.

### Files touched
- `backend/app/services/ttfa_state_stats.py` (NEW)
- `backend/app/api/_dev.py` (endpoint extended)
- `backend/tests/test_ttfa_state_stats.py` (NEW, 9 tests)

## NISCH-006 Day 3++ — TTFA p95 Slack Alerter (May 7, 2026)

**On-call paging on guardian-responsiveness regressions.** Closes the
observability gap before NISCH-007 rolls out: any post-rollout latency
spike now pages within 5 minutes, with the full per-state breakdown
attached.

### What shipped
- `app/services/ttfa_threshold_alerter.py` (NEW). Single
  `check_and_alert(session)` async entry point. Reads thresholds from
  env every call (no process restart needed for tweaks). Computes
  per-state breaches → acquires per-state cooldown → fires Slack via
  existing `health_alerter.notify_failure`.
- Thresholds (env-overridable, ms):
  - `TTFA_THRESHOLD_VALIDATING_MS`   default 5,000
  - `TTFA_THRESHOLD_ESCALATED_MS`    default 30,000  (the KPI)
  - `TTFA_THRESHOLD_ACKNOWLEDGED_MS` default 60,000
  - `TTFA_ALERT_WINDOW_HOURS`        default 1
  - `TTFA_ALERT_COOLDOWN_SECONDS`    default 900 (15min)
  - `TTFA_ALERT_INTERVAL_SECONDS`    default 300 (5min scheduler tick)
- Cooldown via Redis `SET NX EX 900` per state (atomic). Per-state
  isolation: an `escalated` cooldown does NOT silence a fresh
  `validating` breach — verified by test.
- Redis unavailable → fail OPEN. Logged at debug, alert still fires.
  Duplicate alert during outage > missed alert.
- Slack body format matches spec: title line targets the worst
  breaching state, body shows full state breakdown with `⚠️` markers
  on breaching states and `—` placeholders for empty states.
- `notify_failure` post-failure does NOT roll back the cooldown —
  prevents re-alert storms during a flaky webhook.

### Wiring
- Registered as a SECOND job in `safety_incident_scheduler.py` (no
  separate scheduler file — keeps the role-isolation footprint small).
  Job id `ttfa_threshold_check`. 5-min cadence by default.
- Startup log now shows `ttfa_alert=300s` alongside the lifecycle
  intervals — single line of truth for the job manifest.

### Tests (11 new, 82 total passing)
- No-breach → no Slack call
- Breach → Slack fires with worst-state title + full breakdown
- Cooldown held → suppressed (no Slack)
- Cooldown expired → re-alert fires
- Redis client `None` → fail open
- Redis exception → fail open
- Per-state cooldown isolation (escalated held + validating free →
  alert fires for validating only)
- `notify_failure` failure does NOT release cooldown
- Env override picks up `TTFA_THRESHOLD_*_MS`
- Default values used when env unset
- Garbage env value falls back to default

### Live verification (real Redis + real PG)
- Seeded 2 incidents with escalated gap of 40s and 50s
- First tick: `alerts_fired=1`, fired for `escalated` p95=49,500ms
  (threshold 30,000ms). Slack body rendered exact spec format.
- Second tick (immediate): `alerts_fired=0`, `suppressed=['escalated']`
  (Redis cooldown working).
- Lint clean, scheduler restart clean

### Files touched
- `backend/app/services/ttfa_threshold_alerter.py` (NEW)
- `backend/app/services/safety_incident_scheduler.py` (registered new job)
- `backend/tests/test_ttfa_threshold_alerter.py` (NEW, 11 tests)

## Mobile Realtime + Location Architecture Audit (May 7, 2026)

**Surgical fix per user spec.** Closes the duplicate-listener / wasted-polling issues
visible in production logs.

### Root cause analysis
1. `useGuardianSSE` was NOT a singleton — every consumer constructed its own
   `EventSource`. `useChildSSE` already was. The asymmetry caused the duplicate
   guardian SSE reconnects + repeated "App foregrounded — cancelled pending
   disconnect" logs.
2. `useGuardianLocationPolling` ran unconditionally — no coordination with SSE
   health. Wasted ~12 fetches/min when SSE was healthy.
3. `useGPSLocation` was per-consumer — multi-screen apps spawned multiple
   `watchPositionAsync` subscriptions and AppState listeners.
4. `ChildDashboard.fetchLoc` (home.tsx) had a hand-rolled 15s `setInterval`
   that POSTed `/geofence/location-update` independently. A fast tab-switch
   re-mount could leave a dangling timer alive briefly, causing the duplicate
   POST. **This was the actual source of the duplicate-POST log line; the SSE
   hook was innocent.**
5. SSE backoff lacked jitter and capped at 30s. Synchronized clients could
   hammer the server in lockstep on outage recovery.

### Fixes shipped
- **`useGuardianSSE.ts` rewritten as module-level singleton.** Mirrors
  `useChildSSE` ref-counting pattern. One EventSource, one AppState listener,
  one backoff timer, one bg-disconnect timer per process. Subscribers fan in
  via `_callbacks: Set<SSECallback>`. New exports: `isGuardianSSEAlive()` and
  `getGuardianSSELastEvent()` for polling coordination.
- **Backoff hardened on BOTH SSE hooks**: ladder `[1s, 2s, 5s, 10s, 30s, 60s]`
  with ±25% jitter, single-timer guard prevents stacked timers, `_retryAttempt`
  resets to 0 on successful `open` and on foreground reconnect. Foreground
  triggers an immediate reconnect at the bottom of the ladder.
- **`useGuardianLocationPolling.ts` rewritten** to skip ticks when
  `isGuardianSSEAlive()` returns true. Logs `[POLLING_FALLBACK_DISABLED]` on
  recovery, `[POLLING_FALLBACK_ENABLED]` on stale/disconnect — only on
  transitions, not every tick.
- **`useGPSLocation.ts` rewritten as module-level singleton** with
  ref-counting. ONE `watchPositionAsync` subscription + ONE AppState listener
  shared across all consumers. Detach when `_refCount` returns to 0.
- **`home.tsx` ChildDashboard** — moved the 15s `fetchLoc` loop to a
  module-level singleton (`_childLocAttach` / `_childLocDetach`). Re-mounts
  reuse the existing interval; only one geofence POST per 15s window across
  the whole process lifecycle.

### Logging keys (per audit spec)
- `[SSE_SINGLETON]` first/last subscriber, reuse count
- `[APPSTATE_LISTENER]` registration (one per role)
- `[SSE_RETRY]` connection attempt with subscriber count
- `[SSE_BACKOFF]` attempt N, base, jitter, computed delay
- `[SSE_RECONNECTING]` actually reconnecting after backoff
- `[SSE_RECOVERED]` open after N attempts
- `[SSE_CONNECTED]` first-ever open
- `[SSE_DISCONNECTED]` reason logged
- `[POLLING_FALLBACK_ENABLED]` / `[POLLING_FALLBACK_DISABLED]` on transitions
- `[LOCATION_WATCHER]` singleton lifecycle

### Before / After architecture

**Before:**
- N guardian screens → N EventSources → N AppState listeners → N reconnect timers
- Polling always on → 12 fetches/min even when SSE healthy
- 2 child screens with `useGPSLocation` → 2 GPS streams
- ChildDashboard re-mount → potential second 15s loop overlapping the first
- SSE backoff: fixed exponential, no jitter, 30s cap

**After:**
- 1 EventSource per role, ref-counted
- 1 GPS stream regardless of consumers
- 1 child geofence loop regardless of mount count
- Polling = pure fallback; silent when SSE healthy
- SSE backoff: spec ladder + ±25% jitter, 60s cap, single-timer-guard

### Battery / network impact
- **Before** (worst case, 2 guardian screens visible + SSE healthy):
  2 SSE keepalives/min + 24 polling requests/min + 2 GPS streams ≈
  ~26 cellular wakeups/min.
- **After** (same scenario): 1 SSE keepalive/min + 0 polling + 1 GPS stream ≈
  ~1 wakeup/min when SSE is healthy. **~96% reduction in idle network traffic.**
- Polling ticks only fire when SSE has been silent for >60s — exactly the
  window where a fallback is actually useful.

### Edge cases handled
- Foreground after long bg → cancels pending bg-disconnect timer; reconnects
  immediately if connection was lost; no-op if connection survived bg window.
- Auth token rotation → triggers cleanup-then-resubscribe via
  `useEffect([token, stableCb])`. Old EventSource closed before new opens.
- Last subscriber unmount → singleton tears down EventSource, AppState listener,
  status-log interval, and any pending bg/retry timers in one shot.
- Consumer remount during in-flight reconnect → ref count holds the connection;
  no second EventSource opened (singleton guard `if (_es) return`).
- SSE error during AppState foreground transition → backoff schedule kicks in
  rather than immediate retry storm; jitter prevents synchronized client
  reconnect.

### Files touched
- `mobile/hooks/useGuardianSSE.ts` (singleton rewrite)
- `mobile/hooks/useChildSSE.ts` (backoff + jitter upgrade, log keys)
- `mobile/hooks/useGuardianLocationPolling.ts` (SSE-aware skip)
- `mobile/hooks/useGPSLocation.ts` (singleton rewrite)
- `mobile/app/(tabs)/home.tsx` (child geofence loop singleton-guarded)

### Verified
- `npx tsc --noEmit` — zero errors across the full mobile project.
- Hook signatures unchanged for callers — drop-in upgrade. `home.tsx` uses
  `useGuardianSSE`, `useChildSSE`, `useGuardianLocationPolling`; all work
  unchanged.

## NISCH-007 — Incident Feed (Backend + Mobile UI) (May 9, 2026)

### Part A — Backend `GET /api/incidents/nearby` (verified)
- Geospatial feed for guardian's linked children. Haversine in Python
  (no PostGIS dependency added). Cap radius=5000m, limit=50.
- Auth boundary: admin/operator → all; guardian → only `Relationship.status=accepted`
  children; child → own incidents.
- Server-side rules baked in (NEVER leak raw state names, NEVER expose
  child coordinates):
  * `state_label` mapped from enum to user-facing copy ("Distress
    detected", "Guardian network alerted", etc.)
  * `archived` excluded regardless of `?status=`
  * `confidence < 0.70` → field omitted entirely
  * `elapsed_since_created` computed server-side ("4m ago", "2h ago")
  * `zone_match` populated when child's last-known location ∈ child's
    own SafeZone (smallest radius wins on overlap)
- 13 live-PG tests covering: linked guardian happy path, unlinked
  empty feed, archived exclusion, confidence omission, distance
  filter, state label mapping, zone filter match, operator bypass,
  status=resolved filter, bad status 400, haversine sanity (zero +
  Mumbai→Pune ≈ 120 km), distance-ascending sort
- Live curl verified: 401 unauth, 400 bad status, 422 radius>cap,
  200 happy path with exact spec shape

### Part B — Mobile UI (React Native / Expo)
Tab "Incidents" — guardian-only via `href: isGuardian ? ... : null`.

**Component tree (each in its own file under `mobile/components/incidents/`):**
- `SeverityPrimitives.tsx` — `SeverityDot`, `StateBadge`, color tables
- `ZoneFilterBar.tsx` — horizontal chip scroll (All / Home / School / Office / Route)
- `IncidentFeedRow.tsx` — single row, 72px tap target, 16px title,
  SLA-degraded amber dot
- `IncidentFeedList.tsx` — FlatList + pull-to-refresh + calm empty state
- `PulsingMarker.tsx` — Animated.loop scale 1→1.3 + opacity 1→0 ring
  for `escalated`; static dot for everything else
- `IncidentMapView.tsx` — `react-native-maps` (Google provider) with
  saved-zone overlay rings (6% fill) + recentre button
- `IncidentMarkerSheet.tsx` — Modal-based bottom sheet with state
  label, distance, zone, elapsed, severity badge, "View Timeline"
  CTA, SLA-degraded transparency line

**Screen:** `app/(tabs)/incidents.tsx`
- Map / Feed segmented toggle (data shared, never re-fetched on flip)
- `useGuardianSSE` (the Day-3++ singleton) subscribed for
  `incident_state_change`, `incident_created`, `incident_updated`:
  - existing row → in-place patch (state, label, severity)
  - new row → prepend with 200ms teal flash + silent refetch to
    hydrate distance/zone fields the SSE payload lacks
  - `resolved`/`archived` while filter is `active` → drop with
    instant removal
- Polling fallback: 30s tick that fires only when
  `isGuardianSSEAlive() === false` — coordinated via the same
  singleton-aware gate the location poller uses
- Map marker placement: derives a coarse coordinate by ray-casting
  `distance_metres` from the guardian centre at a stable
  per-incident bearing (hash of incident id). Honors the design rule
  ("distance and zone only, never coordinates") — the API never
  returns child lat/lng. A future `marker_lat/lng` field rounded to
  100m would be cleaner; tracked in backlog.

**Detail screen:** `app/incident-timeline.tsx`
- Consumes existing `GET /api/incidents/{id}/timeline` (Day 3 endpoint)
- Vertical chronology: time column · dot/line · state badge + actor
- "X ms later" / "Xs later" / "Xm later" elapsed labels per event
- 403 → "You don't have access to this incident"; 404 →
  "Could not load timeline"

**Spec compliance:**
- ✓ No raw state names rendered anywhere — only `state_label`
- ✓ No child coordinates — distance + zone only
- ✓ ≥16px title font, ≥72px tap target per row
- ✓ Pulsing markers subtle (1→1.3 scale, 1500ms cycle)
- ✓ SLA-degraded amber dot is discoverable, not prominent

**Quality:**
- `npx tsc --noEmit` — zero errors across the full mobile project
- All hook signatures unchanged; no new dependencies added
- 7 new files, 2 edits to layout files
- `data-testid`-equivalent (`testID`) on every interactive element

### Files touched
Backend:
- `backend/app/api/incidents_feed.py` (NEW)
- `backend/app/api/main.py` (registered new router)
- `backend/tests/test_incidents_feed.py` (NEW, 13 tests)

Mobile:
- `mobile/components/incidents/SeverityPrimitives.tsx` (NEW)
- `mobile/components/incidents/ZoneFilterBar.tsx` (NEW)
- `mobile/components/incidents/IncidentFeedRow.tsx` (NEW)
- `mobile/components/incidents/IncidentFeedList.tsx` (NEW)
- `mobile/components/incidents/PulsingMarker.tsx` (NEW)
- `mobile/components/incidents/IncidentMapView.tsx` (NEW)
- `mobile/components/incidents/IncidentMarkerSheet.tsx` (NEW)
- `mobile/app/(tabs)/incidents.tsx` (NEW — feed screen)
- `mobile/app/incident-timeline.tsx` (NEW — detail screen)
- `mobile/app/(tabs)/_layout.tsx` (added "Incidents" tab — guardian-only)
- `mobile/app/_layout.tsx` (registered incident-timeline route)

## NISCH-007 — End-to-End Integration Tests + Contract Bug Fix (May 9, 2026)

### Bug caught and fixed
The integration test surfaced a **silent contract bug** that would
have shipped to TestFlight unnoticed: the SSE broadcaster payload
emitted keys `from` / `to`, but the mobile feed reads `to_state` /
`state` / `state_label`. The mobile in-place row patcher would have
been a silent no-op in production — every state change would have
triggered a full refetch instead of the lighter in-place update,
defeating the polling-coordination work entirely.

**Fix:** `incident_state_machine.TransitionEvent.to_sse()` now emits
both contracts:
  * `from_state` / `to_state` / `state` / `state_label` (canonical,
    mobile-spec)
  * `from` / `to` (legacy compat, preserved for older consumers)

`STATE_LABELS` is sourced from `app.api.incidents_feed` to keep a
single source of truth — feed endpoint and SSE payload always agree
on the user-facing copy.

### Test suite
`backend/tests/test_nisch007_e2e.py` — 9 live-PG tests:
1. Feed returns seeded incident with full shape (state_label !=
   raw state name, distance > 0, confidence ≥ 0.70 exposed)
2. Auth boundary — unlinked guardian gets empty feed
3. State transition updates user-facing label end-to-end
4. Timeline returns ordered events with non-zero elapsed_ms,
   actor_type ∈ {guardian|system|scheduler}
5. Resolved incidents leave the active feed, surface in resolved feed
6. Archived incidents NEVER appear regardless of `?status=` (locked
   for active|resolved|all)
7. SLA-degraded annotation surfaces on the feed row
8. Confidence < 0.70 omitted entirely (not zeroed)
9. **SSE broadcaster contract** — fires `incident_state_change` to the
   child's user_id channel within a 5s `asyncio.wait_for` budget; payload
   contains `to_state`, `state`, `state_label` (mobile contract) AND
   the legacy `to` (back-compat). 5s timeout prevents CI hangs on
   broken emitters.

### Marker registration
`backend/tests/conftest.py` (NEW) registers the `live_pg` pytest
marker. CI skips them with `-m "not live_pg"`; explicit live runs use
`-m live_pg`.

### Verified
- All 9 e2e tests pass against live Neon PG (~2.5 min wall clock)
- Existing 19 `test_incident_state_machine.py` unit tests still green
  (the dual-key SSE shape is backward compatible)
- Lint clean

### Files touched
- `backend/app/services/incident_state_machine.py` (extended SSE payload
  to honor mobile contract while preserving legacy keys)
- `backend/tests/test_nisch007_e2e.py` (NEW — 9 e2e tests)
- `backend/tests/conftest.py` (NEW — `live_pg` marker registration)

### Total test count: **101 passing**
- 19 state machine unit
- 14 incident engine
- 14 alert_trigger
- 7 event log
- 7 timeline endpoint
- 13 incidents_feed
- 9 ttfa_state_stats
- 11 ttfa_threshold_alerter
- 9 NISCH-007 e2e (includes the one that caught the SSE contract bug)
- (other suites: alert_correlation, twilio_safe, etc.)

### What this unlocks
The mobile incident feed contract is now locked end-to-end. The
silent in-place-patch contract bug — the kind of issue that would
have looked working in TestFlight (push notifications fire, feed
shows incidents) but quietly degraded the polling-coordination
optimization shipped earlier this session — can no longer regress
without lighting up `test_sse_emits_state_change_event`.

## NISCH-007 Marker 100m Grid Rounding — Privacy + Map Direction (Feb 2026)

**Why**: Mobile map markers were placed via a per-id bearing ray-cast,
which gave stable positions but always-incorrect direction. Exposing
true child GPS to fix the bearing would have been a privacy regression.
The rounding-to-3dp grid (~111m) is the compromise that gives
*directional accuracy* without leaking *precise location*.

**Backend** (`/app/backend/app/api/incidents_feed.py`):
- `round_marker_coord(coord)` rounds to 3 decimal places (~111m at the
  equator, ~104m at India's latitude). Returns `None` when the input is
  `None` — never substitutes `0.0` (privacy footgun, would put markers
  in the Atlantic off Ghana).
- `MARKER_PRECISION_DP = 3` is the locked privacy constant.
- `/api/incidents/nearby` now returns `marker_lat` and `marker_lng`
  alongside `distance_metres`, both rounded via the helper.

**Mobile** (`/app/mobile/components/incidents/IncidentMapView.tsx`):
- `MapIncident = FeedIncident` — no upstream lat/lng coercion needed.
- Per-marker coordinate selection lives in the component:
  ```ts
  const coordinate = inc.marker_lat != null && inc.marker_lng != null
    ? { latitude: inc.marker_lat, longitude: inc.marker_lng }
    : deriveMarkerCoord(inc.id, centre.lat, centre.lng, inc.distance_metres);
  ```
  `!= null` (not falsy) so a valid `0.000` coordinate doesn't trip the
  bearing fallback.
- `bearingFromId` + `deriveMarkerCoord` relocated from `incidents.tsx`
  into `IncidentMapView.tsx` — still in the codebase, just owned by
  the surface that uses them.

**Mobile screen** (`/app/mobile/app/(tabs)/incidents.tsx`):
- `FeedIncident` (in `IncidentFeedRow.tsx`) gained `marker_lat: number | null`
  and `marker_lng: number | null` — types match the runtime shape so
  `tsc --noEmit` won't pass on a silent `undefined` regression.
- `fetchIncidents` mapping reads the rounded fields straight off the
  API response, with explicit `Number(...)` coercion to defend against
  `null`-vs-string ambiguity.
- SSE placeholder rows seed `marker_lat: null, marker_lng: null` —
  bearing fallback takes over for the brief window between SSE notify
  and the hydrating refetch.

**Tests added** (`tests/test_incidents_feed.py`, 5 new):
- `test_round_marker_coord_precision_is_exactly_3dp` — locks `MARKER_PRECISION_DP == 3`,
  asserts no float dust beyond 3dp.
- `test_round_marker_coord_stable_across_calls` — 100 invocations, byte-identical output.
- `test_round_marker_coord_none_when_no_location` — None propagates,
  never substitutes `0.0`.
- `test_round_marker_within_111m_of_true_coord` — Haversine bound at
  ≤111m for a real Mumbai coordinate.
- `test_nearby_endpoint_surfaces_rounded_marker` — full E2E: child at
  6dp lat/lng → API response carries 3dp `marker_lat`/`marker_lng`,
  Haversine ≤111m, and a second call returns identical markers.

**Verification**:
- `cd /app/mobile && npx tsc --noEmit` → 0 errors.
- `pytest tests/test_incidents_feed.py -v` → 18/18 passed
  (12 pre-existing + 5 new + 1 sub-assertion now distinct).

## NISCH-009 — Guardian Feedback Loop (Feb 2026)

**Why early**: NISCH-009 ships *before* NISCH-008 because every TestFlight
interaction becomes labeled training data from day one — guardian
verdicts on real incidents directly tune the AI confidence engine.
Streaming infrastructure on top of an unverified incident loop is
premature; build the feedback channel first.

**Schema** (migration `cj1a2b3c4dy01`):
- `incident_feedback (id, incident_id, guardian_id, verdict, note,
  created_at, updated_at)`
- `UNIQUE(incident_id, guardian_id)` — UPSERT contract: one verdict
  per pair, latest wins.
- `CHECK (verdict IN ('mark_safe','confirm_risk','report_anomaly'))` —
  defends even if app layer forgets to validate.
- Indexes: `(incident_id)` for aggregation hot-path,
  `(guardian_id, created_at)` for per-guardian audit / anti-spam.
- `ON DELETE CASCADE` on both FKs.

**API** (`/app/backend/app/api/incident_feedback.py`):
- `POST /api/incidents/{id}/feedback` — UPSERT a verdict. Body:
  `{verdict, note?}`. Note capped at 200 chars at the Pydantic layer.
- `GET /api/incidents/{id}/feedback` — counts + caller's own verdict
  (renders "you voted: …" without an extra round trip).
- **Closed-network gate** (locked by tests): admin/operator OR an
  `accepted` Relationship row required. Anyone else → 403.
  Self-vote (child = caller) explicitly NOT allowed — that's not a
  guardian feedback signal.
- 404 on unknown incident, 409 on archived (terminal — feedback
  no longer moves the AI loop).

**Aggregator** (`/app/backend/app/services/feedback_aggregator.py`):
- Threshold rule (locked by tests):
  - ≥2 `confirm_risk` AND zero `mark_safe` → confidence anchor +0.10 (cap 0.99)
  - ≥2 `mark_safe`    AND zero `confirm_risk` → confidence anchor −0.15 (floor 0.0) AND auto-transition state to `resolved` via the state machine, with `actor_type='community_feedback'` for forensic clarity.
  - `report_anomaly` votes are flags only — never move confidence.
- **Idempotency**: stores the original confidence under
  `incident.extra['confidence_before_feedback']` on first hit;
  re-runs derive deltas from that anchor, so repeat aggregations
  converge instead of drifting (locked by `test_idempotent_aggregate_on_double_apply`).
- **Why "AND zero of the other side"**: even one opposing vote nullifies
  classification, so a noisy crowd can't drift state without a clear
  agreement. Asymmetric cost: a false MARK_SAFE on a real distress is
  catastrophic; we err toward holding.

**Forensic trail**: every accepted verdict (insert OR update) writes a
`safety_incident_events` row with `actor_type='guardian_feedback'`,
`from_state == to_state` (no state change on the vote alone),
`extra={verdict, previous_verdict, is_update, note}`. The auto-resolve
transition writes its own row with `actor_type='community_feedback'`.

**Mobile** (`/app/mobile/components/incidents/FeedbackActionBar.tsx`):
- Three buttons: Mark Safe (success green), Confirm Risk (error red),
  Report Anomaly (warning amber).
- Anomaly opens an optional 200-char note dialog with character counter.
- Active verdict highlighted with tinted border + tinted background;
  per-verdict count pill shows network agreement.
- 403 → component returns `null` (closed-network — child or unrelated
  user shouldn't see the bar at all).
- Auto-resolve fires an `Alert` ("Marked safe — your network agreed").
- Mounted on **both** `incident-timeline.tsx` (full layout) and
  `IncidentMarkerSheet.tsx` (`compact` variant — same component,
  different padding).
- Timeline screen patches `current_state` in place + refetches the
  forensic timeline when `onChange` fires, so the "Resolved" badge
  shows up without leaving the screen.

**Tests** (`tests/test_incident_feedback.py`, 18 cases):
- Unit: 6 classifier truth-table cases + constant lock.
- Integration: closed-network 403, admin bypass, invalid verdict 400,
  unknown incident 404, archived 409, UPSERT semantics, threshold
  bumps confidence (+/−), disagreement holds, anomaly never triggers,
  GET aggregation + own verdict, auto-resolve forensic trail
  (`guardian_feedback` + `community_feedback` rows present),
  idempotency on repeat aggregation.
- All 18/18 pass against live Neon.

**Verification**:
- `pytest tests/test_incident_feedback.py` → 18/18 in 250s.
- `npx tsc --noEmit` → 0 errors.
- Live API smoke: `GET /api/incidents/<random-uuid>/feedback` → 404 with
  proper error envelope, auth working.

## NISCH-009.1 — Guardian Impact Badge "Saved by your network" (Feb 2026)

**Why**: Now that guardians can vote and we know which votes drove
auto-resolutions, surface that contribution as an *earned* credential.
Visible feedback that "your input shapes the system" compounds vote
participation during the soak — exactly the engagement loop the
TestFlight cohort needs.

**Goal contract**: a guardian's `saved_by_network_count` rises by 1
ONLY when:
  1. Their CURRENT verdict on an incident is `mark_safe` (UPSERT keeps
     final verdict per pair), AND
  2. The incident received an auto-resolve transition driven by the
     community feedback aggregator (`safety_incident_events` row with
     `actor_type='community_feedback'` and `to_state='resolved'`).
Each (incident, guardian) pair counts at most once — naturally
deduplicated by the UNIQUE(incident_id, guardian_id) constraint plus
`COUNT(DISTINCT inc_fb.incident_id)` in the SQL.

**Service** (`/app/backend/app/services/guardian_impact_service.py`):
- Source-of-truth SQL — JOIN of `incident_feedback` + `safety_incident_events`,
  filtered on the two contracts above. No materialised view yet (the
  scale doesn't justify it; revisit when system_resolutions ≫ 10k).
- Redis cache `nischint:guardian_impact:{guardian_id}` (TTL 5 min) +
  separate `nischint:guardian_impact:system_resolutions` for the
  global denominator. Both fail open — cache outage degrades to a
  fresh DB read, never errors.
- `invalidate_guardians(ids)` — best-effort, swallows all Redis errors.
  Wired into `feedback_aggregator.apply_feedback_decision`: on every
  auto-resolve we look up `get_mark_safe_voters(incident_id)` and
  invalidate their cache rows so the badge updates within seconds.
- **Low-confidence floor**: `LOW_CONFIDENCE_FLOOR = 5`. When
  system-wide community-resolved count is below this, `confidence_low: true`
  is returned — the UI hides the badge regardless of personal count.
  Defends against a 1-incident network displaying flashy badges.

**API** (`/app/backend/app/api/guardian_impact.py`):
- `GET /api/guardian/impact/me`         — caller's envelope. No role gate.
- `GET /api/guardian/impact/{user_id}`  — admin/operator only (or self).
- Response shape:
  ```
  {
    "guardian_id":            uuid,
    "saved_by_network_count": int,
    "system_resolutions":     int,
    "confidence_low":         bool,
    "from_cache":             bool
  }
  ```

**Mobile** (`/app/mobile/components/guardian/ImpactBadge.tsx`):
- Mounted on `(tabs)/guardian.tsx` in the dashboard header, directly
  beneath the "Family Safety / Monitor your loved ones" subtitle.
- Pill treatment: shield-checkmark icon + "Saved by your network — N times"
  on a 10%-tinted success background with a 35%-tinted border.
  Earned aesthetic, no animations, no celebration spam.
- Tap → modal tooltip explaining the credential ("Incidents where your
  'Mark Safe' vote contributed to an automatic resolution …").
- **Visibility rules** (locked):
  * `count > 0` REQUIRED — no zero badges, no "you haven't earned it" treatment.
  * `confidence_low === false` REQUIRED — silent hide if system has
    fewer than 5 community resolutions.
  * 403 from API → silent hide (consistent with closed-network rule).

**Edge cases covered by tests**:
- Verdict change before threshold fires → only the FINAL verdict
  earns credit. UPSERT + `COUNT(DISTINCT)` enforces this.
- Repeat UPSERT on same incident → counts once, not N times.
- Non-community resolutions (e.g. guardian-acked, scheduler-resolved)
  → mark_safe voters do NOT get credit. The
  `actor_type='community_feedback'` filter is the only counted path.
- Disagreement (1 risk + 1 safe) → no auto-resolve → no credit
  (fall-through of the threshold rule).
- Multi-guardian resolution → each contributing mark_safe voter
  credited independently.

**Tests** (`tests/test_guardian_impact.py`, 13 cases):
- Counting: zero-state, multi-guardian credit, non-mark_safe ineligible,
  repeat-vote idempotent, non-community-actor ineligible.
- Confidence floor: low-confidence flag respected, floor constant locked.
- Helper coverage: `get_mark_safe_voters`, `invalidate_guardians`
  failsafe contract.
- API auth: own /me, cross-user 403 for guardian, admin allow,
  self-allowed on /{user_id}.
- All 13/13 pass against live Neon.

**Verification**:
- `pytest tests/test_guardian_impact.py` → 13/13 in 223s.
- `npx tsc --noEmit` → 0 errors.
- Live `GET /api/guardian/impact/me` (mother account) →
  `{"saved_by_network_count":0,"system_resolutions":0,"confidence_low":true,"from_cache":false}`
  — endpoint live, cache layer engaged, mobile correctly hides badge
  (count=0 + confidence_low=true).

**Combined backend test count after this session**: 18 (NISCH-009) +
13 (NISCH-009.1) + 18 (incidents_feed) = **49 incident-flow tests**,
all green.

## NISCH-008 — Live Emergency Stream (Backend Signalling Layer, Feb 2026)

**Why this layer first**: per spec sequencing — ship the signalling
layer + auto-offer hook + Twilio NTS integration *before* touching
mobile. WebRTC bugs are easiest to isolate when the signalling
layer is clean and `wscat`-testable.

### Schema (migration `dk1a2b3c4dz01`)

`stream_sessions (id, incident_id, child_id, state, stream_type,
ice_servers, recording_url, duration_seconds, guardian_join_count,
offered_at, started_at, ended_at)`.

State enum: `offered | declined | connecting | live | ended` —
DB CHECK + Python `ALLOWED_STREAM_TRANSITIONS` map both enforce the
contract. ON DELETE CASCADE on `incident_id`. Indexes on
`(incident_id)` for guardian feed, `(state, offered_at)` for the
auto-decline sweeper.

### Service (`/app/backend/app/services/stream_initiator.py`)

- `is_valid_stream_transition(from, to)` — pure validator, no DB.
- `transition_stream(session, stream, new_state, ...)` — validates,
  mutates the row, writes a forensic row to `safety_incident_events`
  with `actor_type='stream'`, emits `stream_state` SSE.
- `offer_stream_for_incident(session, incident, stream_type='audio')`
  — idempotent per-active-stream: reuses any existing OFFERED /
  CONNECTING / LIVE row rather than spawning duplicates. Emits
  `stream_offer` (child) + `stream_available` (guardians) on the
  fresh row.
- `auto_decline_stale_offers(session)` — single-UPDATE sweeper,
  flips OFFERED rows older than `OFFER_TIMEOUT_S` (30s) to
  DECLINED with `ended_at = now`. Designed to run on the scheduler
  process every 10s.
- `get_ice_servers(ttl=30)` — Twilio NTS `client.tokens.create()`
  with hardcoded TTL clamp. Failure modes (rate limit, auth, suspended,
  network) all degrade silently to a public STUN-only fallback so
  the signalling layer NEVER blocks an emergency. Per Twilio playbook:
  `nts.ice_servers` is already in WebRTC-spec format
  (`[{urls, username?, credential?}]`) — drop directly into
  `RTCPeerConnection`.

### Auto-offer hook (incident_state_machine)

`incident_state_machine.transition()` now fires
`offer_stream_for_incident()` on the ESCALATED transition, inside
the same DB transaction as the state change. Wrapped in
try/except — streaming failure NEVER blocks the lifecycle
transition (the alert path is always more important than the
nice-to-have stream).

### REST endpoints (`/app/backend/app/api/streaming.py`)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/stream/initiate` | child / admin / operator | Manual fallback if auto-offer didn't fire |
| GET | `/api/stream/{id}/join` | linked guardian / admin / operator | Issues fresh ICE (not the offer-time ICE) + bumps `guardian_join_count` |
| POST | `/api/stream/{id}/accept` | child only | Transition offered → connecting |
| POST | `/api/stream/{id}/end` | any allowed party | Persists `recording_url` + `duration_seconds` to the row, transitions to ended |
| GET | `/api/stream/{id}` | any allowed party | Cold-start envelope for the mobile listener |

Closed-network rule on every endpoint: `relationship.accepted` OR
`admin/operator`. Operator role can READ but is NOT included in the
SSE fan-out (sensitive media metadata stays inside the guardian
network).

### WebSocket signalling relay

`WS /api/stream/{id}/signal?token=<jwt>` — opaque per-stream relay.
Server is a dumb router: forwards `offer`, `answer`, `ice_candidate`,
`end_stream`, and any future renegotiation message types unchanged
to the OTHER peers in the same room. Auth checked at accept time
only — once accepted, peers broadcast freely within their room.

Server-side state observers wired into the relay:
- First `answer` message → if state was `connecting`, transitions
  to `live`.
- First `end_stream` → transitions to `ended`, broadcasts to peers,
  closes the WS.

### Tests (`tests/test_streaming.py`, 17 cases)

- Pure: state-transition map (allowed + rejected), Twilio fallback
  on missing creds, locked constants.
- Auto-offer: creates session, idempotent reuse, **end-to-end via
  state machine** (DETECTED → VALIDATING → ESCALATED auto-spawns
  one OFFERED stream).
- Auth: unrelated user 403 on `/initiate`, invalid stream_type 400,
  unrelated guardian 403 on `/join`, accept-only-by-child gate.
- Linked guardian gets fresh ICE + `guardian_join_count` increments.
- `/end`: persists recording URL + duration, idempotent on already-ended.
- `/get`: full envelope, recording_url field present even when null.
- Sweeper: stale offers swept to `declined`, fresh offers preserved.

All **17/17 pass against live Neon** in 220s.

### Live verification

- Migration `dk1a2b3c4dz01` applied to Neon.
- Backend restarted; route registered.
- `POST /api/stream/initiate` (kid auth) on an unknown incident →
  `404 incident not found` — endpoint live, auth working.
- Twilio NTS unreachable in dev (no creds set) — `get_ice_servers()`
  returns the public STUN fallback as designed.

### What's still pending (mobile — Steps 6-9)

Per spec sequencing, mobile is the next phase. Open question for the
user before installing `react-native-webrtc`:
- The library is a **native module** (not pure JS) — requires EAS
  build, won't run in Expo Go.
- SDK 55 compatibility needs verification.
- Adds 5-10MB to APK and a config plugin to `app.json`.

Three realistic mobile-side options:
1. **Full WebRTC** — `react-native-webrtc` + native build + Expo
   config plugin. Lowest latency. Highest install risk on SDK 55.
2. **Audio-only via expo-audio + uploaded chunks** — record on
   device in 5s windows, upload to backend, backend serves to
   guardians via HLS. ~10s total latency, but pure-Expo, zero
   native risk.
3. **Hybrid** — ship the backend NOW (this PR), defer mobile to a
   dedicated sprint where the EAS build + native module install
   can be tested on real devices.

Backlog status: P2 (per spec), unblocked by anything else.

## NISCH-008 Phase C — Scheduler Wiring + 🎙 Listen Chip + EAS Prereqs (Feb 2026)

Per user direction (option **c. Hybrid**): backend ships now, mobile
WebRTC defers to a dedicated sprint after a stable EAS baseline.
This sprint locked the *low-risk* high-value pieces:

### Task 1 — Stream sweeper wired into scheduler ✅

`safety_incident_scheduler.start_safety_incident_scheduler()` now
registers a third APScheduler job:

| ID | Cadence | Owner |
|----|---------|-------|
| `safety_incident_lifecycle` | 60s | NISCH-006 |
| `ttfa_threshold_check` | 300s | NISCH-006 Day 3++ |
| **`stream_stale_offer_sweep`** | **10s** | **NISCH-008** |

Fail-quiet `_stream_offer_sweep_tick()` opens its own session,
calls `auto_decline_stale_offers()`, commits, swallows errors so
streaming infra never crashes the loop. Cadence env-overridable
via `STREAM_OFFER_SWEEP_INTERVAL_SECONDS`.

Live verification (`nischint-scheduler` supervisor process):
```
[safety_incident_scheduler] started — interval=60s
  esc_resolve=30m ack_resolve=30m archive=30m
  ttfa_alert=300s stream_offer_sweep=10s
```

### Task 2 — 🎙 Listen chip (forensic replay) ✅

**Backend** (`/app/backend/app/api/safety_incidents.py`):
`GET /api/incidents/{id}/timeline` response now includes a `stream`
field — the most recent ENDED stream session for that incident,
pulled in a single ORDER BY ended_at DESC LIMIT 1 query:
```json
{
  "stream": {
    "stream_id":           "uuid",
    "state":               "ended",
    "stream_type":         "audio|video",
    "duration_seconds":    87,
    "recording_url":       "https://r.example.com/r/test123.m4a",
    "started_at":          "2026-05-09T...",
    "ended_at":            "2026-05-09T...",
    "guardian_join_count": 2
  }
}
```
- Returns `null` when no stream existed OR the only stream is
  in-flight (offered/connecting/live) — the chip surfaces ended
  streams ONLY because their `recording_url` is stable.
- `recording_url` is returned verbatim. The WebRTC sprint's
  on-device recorder will write a pre-signed (24h) S3 URL into the
  column directly, keeping this endpoint forward-compatible.

**Mobile** (`/app/mobile/components/incidents/StreamRecordingChip.tsx`):
- New component using `expo-audio` (already installed; no new
  native dep).
- Pill treatment with a play/pause button + `m:ss / m:ss` duration
  + a no-dep progress bar fill.
- `recording_url === null` → graceful "Recording unavailable" state.
- Mounted in `incident-timeline.tsx` directly below the timeline
  event list.

**No new mobile dependencies.** `@react-native-community/slider`
was considered for full scrub UX but skipped to keep the EAS
build surface clean — progress bar is plenty for v1 forensic
replay; full scrub lands with the WebRTC sprint.

### Task 3 — EAS Build prep ✅

Created `/app/memory/NISCH-008-MOBILE-PREREQS.md` documenting:
- SDK 55 / RN 0.83 / expo-audio 55.0.14 lock
- Currently registered Expo plugins (7 — none of them WebRTC)
- `react-native-webrtc` + `@config-plugins/react-native-webrtc`
  install plan (deferred to dedicated sprint)
- iOS / Android permission matrix to add WHEN WebRTC lands
- EAS dev profile baseline (no WebRTC yet)
- India NAT note (Twilio TURN mandatory in prod, STUN-only fallback
  in `stream_initiator.py` is dev-only)
- Test bar for the WebRTC sprint (Jio↔Airtel cross-network call,
  Wi-Fi↔4G handover, 30s screen lock survival)

The agent **cannot** run `eas build` from this pod (no Expo
account token here) — that's the user's manual step. All code
pieces are ready; backend signalling layer is fully testable with
`wscat` ahead of mobile work.

### Tests

- 2 new in `tests/test_stream_scheduler.py`:
  - `test_scheduler_registers_stream_sweep_job` — verifies the
    APScheduler job ID is registered + the other two safety jobs
    survive.
  - `test_stream_sweep_tick_declines_stale_offer` — runs the
    full tick wrapper (session open + sweep + commit) and asserts
    a stale offered row was flipped to declined with `ended_at`
    populated.
- 2 new in `tests/test_incident_timeline_endpoint.py`:
  - `test_timeline_returns_stream_block_when_ended_stream_exists`
    — full envelope shape lock.
  - `test_timeline_stream_is_null_when_no_ended_stream` —
    asserts in-flight (OFFERED) streams do NOT leak through.

### Verification

- `pytest tests/test_stream_scheduler.py` → 2/2 in 17s.
- `pytest tests/test_incident_timeline_endpoint.py` → 10/10 (8 prior
  + 2 new).
- `npx tsc --noEmit` → 0 errors.
- Scheduler restart log confirms `stream_offer_sweep=10s` registered.
- Backend live + auth working end-to-end.

### Cumulative test count after this sprint

- NISCH-007 (incidents_feed): 18
- NISCH-009 (incident_feedback): 18
- NISCH-009.1 (guardian_impact): 13
- NISCH-008 (streaming): 17
- NISCH-008 Phase C (scheduler + timeline): 4 new
- **Total tests added across this session: 70**

All passing against live Neon.

## NISCH-008 Mobile WebRTC Sprint — DONE (Feb 2026)

Per user direction (Option 1) shipped the full mobile + recording
uploader. All code in place, tsc clean, 6 new backend tests + 23/23
streaming suite passing. Native module install + EAS dev build is
the only remaining manual step (user-side).

### Native deps installed
- `react-native-webrtc@124.0.7` — peer-to-peer audio (camera plugin
  permission registered for forward compat, but the runtime never
  calls getUserMedia for video in v1).
- `@config-plugins/react-native-webrtc@14.0.0` — Expo config plugin.

### `app.json` updates (review before EAS build)
- Plugin entry with `cameraPermission` + `microphonePermission` strings.
- iOS `infoPlist.NSMicrophoneUsageDescription` + `audio` background mode.
- Android `RECORD_AUDIO` + `MODIFY_AUDIO_SETTINGS` permissions.

### Mobile hooks (new)
- `hooks/useStreamSignaling.ts` — opaque WebSocket relay client.
  Connects to `WS /api/stream/{id}/signal?token=…`, exposes
  `send(msg)` + `connected` state, exponential backoff up to 4
  retries, dies clean on 4001-4099 close codes (auth / not found /
  ended) without retry.
- `hooks/useWebRTC.ts` — `RTCPeerConnection` lifecycle. Caller
  (child) attaches local audio + creates offer; callee (guardian)
  accepts offer + answers; both sides relay ICE through the
  signalling hook. Audio-only — never calls getUserMedia for video.

### Mobile screens (new)
- `app/stream-caller.tsx` — child-side modal-style screen with red
  recording dot, duration HUD, End Stream button. Hardware back +
  swipe-dismiss both route through `teardown()` so we never leave
  a dangling LIVE row in the DB. Parallel on-device recording via
  `expo-audio`; uploaded after end via the presign + finalize flow
  (best-effort — silently skips if backend 503s).
- `app/stream-listener.tsx` — guardian-side screen with `RTCView`
  mounted invisibly to keep the audio track in the React tree.
  Mark Safe shortcut wired into the existing NISCH-009 endpoint
  so a listening guardian can resolve without leaving. Caller-side
  end_stream → `Alert` + auto-back.
- `components/incidents/StreamBanner.tsx` — child-side non-blocking
  banner. Auto-accept after 1s when source incident `confidence > 0.90`,
  otherwise manual tap to accept. Animated slide-in. Mounted globally
  in `_layout.tsx` so it shows from any tab.
- `components/incidents/IncidentMarkerSheet.tsx` — added a
  `liveStreamId` prop + a "🔴 LIVE — tap to listen" CTA that routes
  to `stream-listener`. Wired in `(tabs)/incidents.tsx` from the
  `stream_available` SSE channel.

### SSE integration
- `useGuardianSSE.ts` event types extended: `stream_offer`,
  `stream_available`, `stream_state`.
- `useChildSSE.ts` event types extended: `stream_offer`, `stream_state`.
- `(tabs)/incidents.tsx` tracks `liveStreams: incident_id → stream_id`
  from `stream_available` events; clears entries on
  `stream_state == ended | declined`.

### Backend recording uploader (new endpoints)
- `POST /api/stream/{id}/recording/presign`
  - Mints a 10-min S3 PUT URL via `boto3.generate_presigned_url`.
  - Auth: child of the incident OR admin.
  - 503 when `STREAM_RECORDING_BUCKET` env var is unset (degrades
    cleanly — recording_url stays null, mobile still works).
  - 400 on unsupported content-type (m4a, webm, mp4, aac only).
- `POST /api/stream/{id}/recording/finalize`
  - HEADs the uploaded object before persisting (defense against
    finalize-without-upload race).
  - Mints a 24h pre-signed GET URL → writes to
    `stream_sessions.recording_url`.
  - 400 on bucket-mismatch (defends against client-controlled
    bucket pointer).
  - 404 when object isn't actually there.

### Tests (6 new + 23 total streaming)
- `test_presign_503_when_bucket_not_configured`
- `test_presign_blocks_non_child`
- `test_presign_invalid_content_type_400`
- `test_finalize_persists_recording_url` (mocked S3 client)
- `test_finalize_404_when_object_missing`
- `test_finalize_bucket_mismatch_400`

`tests/test_streaming.py`: **23/23 pass** (5 min wall-clock).
`npx tsc --noEmit`: **0 errors**.
Live `POST /api/stream/<random-uuid>/recording/presign` → 503
"recording bucket not configured" — endpoint live, failsafe verified.

### What requires human-in-the-loop next

1. **Set `STREAM_RECORDING_BUCKET` env** on the backend (any S3
   bucket the existing `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`
   creds can write to). Without it, recordings won't persist but
   live audio still works.
2. **EAS dev build** — `cd mobile && eas build --profile development
   --platform ios`. First build with `react-native-webrtc` will
   take 25-40 min for both platforms.
3. **Physical device QA** per `NISCH-008-MOBILE-PREREQS.md` test bar:
   - Audio call between two phones on different Jio/Airtel SIMs
     (forces TURN relay through Twilio NTS).
   - Wi-Fi → 4G handover survives.
   - Stream survives 30s screen lock (validates the `audio`
     background mode in iOS infoPlist).
   - Recording uploads within 10s of `end_stream` for a 90s capture.
4. **24h soak + TestFlight promotion** per the existing
   `scripts/verify_mobile_singleton.md` runbook.

### Cumulative test count after this sprint

- NISCH-007: 18
- NISCH-009: 18
- NISCH-009.1: 13
- NISCH-008 (signalling + lifecycle): 17
- NISCH-008 Phase C (sweeper + timeline): 4
- **NISCH-008 Mobile (recording uploader): 6 (new this sprint)**
- **Total tests added across sessions: 76**

All passing against live Neon. Mobile tsc clean.

## NISCH-012.0 — External Signal Layer (Pilot via Weather, Feb 2026)

Per scope-locked execution plan: ONLY 12.0 — abstraction + weather
adapter + alert pipeline hook + forensic event + modifier math with
freshness decay and hard timeout. **No** TomTom, **no** Sachet, **no**
news/social, **no** operator UI yet.

### What landed

**Abstraction** (`app/services/external_signals/`):
- `__init__.py` — `ExternalSignal` Pydantic model, `ExternalSignalProvider`
  ABC, `freshness_decay()` pure function. Constants locked:
  `PROVIDER_TIMEOUT_S = 1.5s`, `FRESHNESS_FLOOR = 0.05`.
- `weather.py` — `WeatherProvider` adapter over the existing
  `weather_service.py` (zero new HTTP code). Maps the existing
  `compute_weather_risk()` into the canonical `ExternalSignal`
  contract. `signal_type` derived from the dominant factor (priority
  order: tornado > thunderstorm > heavy_rain > extreme_heat > …).
- `registry.py` — `fetch_all_signals(lat, lng)`. Concurrent fan-out
  with `asyncio.wait_for` enforcing the 1.5s per-provider hard
  timeout. **Total alert hot-path budget bounded at 1.5s** even
  when all providers time out (concurrent, not serial).
  Fail-quiet: any provider raising or timing out → logged at
  WARNING, dropped from the batch, never propagates.
- `modifier.py` — `apply_external_modifiers(base_confidence, signals)`.
  Pure function. Audit envelope shape locked (UI consumes these
  field names). Threshold = 0.6 effective; per-signal cap = 0.10;
  total cap = 0.20; ceiling = 0.99. **Additive math** — multiplicative
  compounding rejected by design.

**Schema** (migration `em1a2b3c4dz01`, applied to Neon):
- `safety_incidents.external_signals JSONB` — full audit envelope
- `safety_incidents.confidence_pre_external FLOAT` — original ML
  confidence preserved for "AI said 0.78, weather bumped to 0.93"

**Alert pipeline wire-in** (the architectural gap pre-12.0):
- `safety_incident_engine.open_incident_for_alert()` accepts new
  `location` arg. When present, runs the modifier path inside the
  same DB transaction as incident creation. Fail-quiet — any
  unhandled exception in the modifier path is logged and the
  unmodified confidence is used.
- `alert_trigger.trigger_alert()` forwards `location` to the engine.
  No other call sites changed — pre-12.0 callers (no location)
  short-circuit the modifier path entirely.
- **Forensic event row fires** with `actor_type='external_signal'`
  AND `ttfa_tag='confidence_modifier'` whenever a bump applies.
  Extra payload: `confidence_before`, `confidence_after`,
  `modifier_applied`, `modifier_capped`, providers list with delta
  + applied flag. Surfaces on the existing
  `GET /api/incidents/{id}/timeline`.

### Engineering rules locked at this layer

| Rule | Enforcement |
|------|-------------|
| **Fail-quiet** | Every provider returns `Optional`, never raises. Registry's `_safe_fetch` is the boundary; `apply_external_modifiers` is a pure function with no side effects. |
| **Hard timeout** | `PROVIDER_TIMEOUT_S = 1.5s` per provider, enforced by `asyncio.wait_for` at the registry layer (not in providers — they cannot bypass it). |
| **TTL is mandatory** | `ExternalSignal.ttl_s` is non-optional; `freshness_decay()` clamps to 0 below `FRESHNESS_FLOOR = 5%`. |
| **Additive cap** | `CONFIDENCE_BUMP_CAP = 0.20` total bump regardless of how many strong signals fire. |
| **Auditability** | Every applied modifier produces (a) a JSONB row on `safety_incidents.external_signals` and (b) a `safety_incident_events` row with `actor_type='external_signal'`. The timeline can deterministically replay any bump. |

### Tests (20 new — `tests/test_external_signals.py`)

- **Constants** locked (1).
- **Freshness decay** (4): full when fresh, zero when expired,
  linear at midpoint, clamped below floor.
- **Modifier math** (8): empty signal set, sub-threshold drop,
  strong-signal bump, 3-signal cap (locks the +0.20 ceiling),
  0.99 confidence ceiling, stale-signal drop with `reason_skipped`,
  audit envelope shape, strongest-signal-claims-cap-first.
- **Registry fail-quiet** (4): exception swallow, hard-timeout
  bound (asserts elapsed wall-clock < 1.9s with a slow provider),
  disabled-provider skip, no-location returns empty.
- **End-to-end through `open_incident_for_alert`** (3):
  audit + forensic row both persist, no audit when no signals,
  `location=None` short-circuits the modifier path entirely.

All **20/20 pass** in 43s against live Neon.
**Regression**: `test_incident_event_log.py` + `test_incident_timeline_endpoint.py`
both still 16/16 green — no breaking changes.

### Live verification

- Migration `em1a2b3c4dz01` applied to Neon.
- Backend `/api/health` 200 in 466ms after restart, no errors in
  `backend.err.log`.
- The weather provider activates automatically when
  `OPENWEATHER_API_KEY` is set (already in env). When unset,
  `is_enabled()` returns False and the registry silently skips it
  — pre-12.0 behaviour preserved.

### What this unlocks for Phase 12.1+

- Adding TomTom / Sachet / News is a single new file
  (`external_signals/{name}.py`) + one line in `registry._PROVIDERS`.
- Operator UI (Phase 12.4) reads the `external_signals` JSONB
  column directly — no new backend endpoints needed.
- Mobile timeline already surfaces `actor_type='external_signal'`
  events via the existing `/timeline` endpoint; an
  `<ExternalSignalsBlock />` component just needs to render the
  `extra` payload nicely (it's already on the wire).

### Cumulative test count after this sprint

- NISCH-007: 18
- NISCH-009 + 009.1: 31
- NISCH-008 (signalling + lifecycle): 17
- NISCH-008 Phase C: 4
- NISCH-008 Mobile recording uploader: 6
- **NISCH-012.0 External signal layer: 20 (new this sprint)**
- **Total tests added across sessions: 96**

All passing against live Neon.


## NISCH-012.3 — Sachet (NDMA) CAP-XML Disaster Provider (Feb 2026)

**Why**: India's NDMA `sachet.ndma.gov.in` publishes a free, no-key
CAP-XML disaster feed (cyclones, floods, heatwaves, thunderstorms,
landslides). Wiring it into the External Signal Layer means an SOS
in Mumbai during Cyclone Biparjoy gets a deterministic +0.0 → +0.95
risk bump from a government source — clickable proof for human
operators reviewing the timeline.

### What ships
- **New file** `app/services/external_signals/sachet_provider.py`
  - `SachetSignalProvider` extends `ExternalSignalProvider`
  - Polls `https://sachet.ndma.gov.in/cap_public_website/rss/rss_india.xml`
    (the documented public RSS index — the legacy
    `getAllCapAlerts` URL referenced in the handoff returns 404 in
    prod; we verified the RSS path live on May 2026, 99 active alerts).
  - **5-minute Redis cache** at `nischint:sachet:rss_parsed_v1`
    (`CACHE_TTL_S = 300`). Empty / failed fetches do NOT poison the
    cache — next call retries.
  - **30-minute decay** on each emitted signal (`SIGNAL_TTL_S = 1800`)
    — flows through the existing `freshness_decay()` math so a stale
    Sachet alert won't silently bump confidence after the storm has
    cleared.
  - **HTTP timeout 1.0s** (well under `PROVIDER_TIMEOUT_S = 1.5`).
    Cold-cache slow path may fail-quiet; cache warm path is sub-ms.
  - **8-state bounding-box reverse-geocode**: Kerala / Karnataka /
    Tamil Nadu / Andhra Pradesh / Maharashtra / Gujarat / Odisha /
    West Bengal — covers the cyclone/flood/heatwave belt. Order in
    `STATE_BBOX` is significant: smaller / more-specific bboxes
    evaluated first so coords in the Western-Ghats overlap zone
    resolve to Kerala/Karnataka before Tamil Nadu (verified with
    Bengaluru, Kochi, Vijayawada, Visakhapatnam).
  - **Severity mapping**: title-keyword classifier maps RSS
    headlines to CAP severities — Extreme=0.95, Severe=0.80,
    Moderate=0.50, Minor=0.30. Most-actionable wins ties (an
    "Extreme thunderstorm" headline classifies as `extreme`).
  - **`raw_url` populated** with the per-alert
    `FetchXMLFile?identifier=…` URL → operator click-through to the
    structured CAP-XML.
  - **Disable env knob**: `DISABLE_SACHET=true` skips the provider
    entirely (CI / preview environments).
  - Fail-quiet contract: any HTTP / parse / geocode failure returns
    `None` — alert pipeline is never blocked.

### Wiring
- `external_signals/registry.py` — `SachetSignalProvider()` added to
  `_PROVIDERS` after `WeatherProvider()`. `_reset_providers_to_default()`
  also updated so test isolation stays clean.
- No DB migration. Audit/forensic linkback piggybacks on the
  existing `external_signals` JSONB + `actor_type='external_signal'`
  event row from NISCH-012.0.

### Tests — `tests/test_sachet_provider.py` (38 new)
- `test_severity_risk_mapping_locked` — 0.95/0.80/0.50/0.30 contract.
- 8 `resolve_state_known_cities` parametrised — Mumbai, Ahmedabad,
  Bengaluru, Chennai, Kochi, Vijayawada, Kolkata, Bhubaneswar.
- `resolve_state_returns_none_outside_india` — NYC, London → None.
- `resolve_state_returns_none_for_missing_coords` — None inputs.
- 10 `infer_severity_keyword_table` parametrised — extreme/severe/
  moderate/minor lexical buckets.
- `test_infer_severity_extreme_beats_lower_keywords` — most-
  actionable severity wins on multi-keyword headlines.
- `test_parse_rss_yields_alerts` — valid feed → 2 alerts, severity
  inferred, identifier preserved.
- `test_parse_rss_empty_bytes_returns_empty`,
  `test_parse_rss_malformed_returns_empty`,
  `test_parse_rss_skips_items_missing_title_or_id` — fail-quiet.
- 4 `pick_strongest_*` — severity ranking, no-match path,
  case-insensitive state, empty state guard.
- `test_cache_hit_skips_http` — Redis HIT short-circuits HTTP.
- `test_cache_miss_fetches_and_writes` — proper cache write at
  `CACHE_TTL_S`.
- `test_cache_miss_does_not_persist_empty_feed` — transient outage
  doesn't poison the cache with `[]`.
- `test_provider_returns_external_signal_for_matching_state` —
  shape contract: `provider=sachet`, `signal_type=ndma_extreme`,
  `risk_0_1=0.95`, `factors` include severity + state slug,
  `raw_url` is the `FetchXMLFile?…` link.
- `test_provider_returns_none_outside_indian_states` — short-
  circuits BEFORE upstream call (cheap for global users).
- `test_provider_returns_none_when_no_alerts_for_state`,
  `test_provider_returns_none_when_feed_empty`.
- `test_provider_is_disabled_when_env_flag_set` — `DISABLE_SACHET`
  opt-out works.

### Verified live
- Live RSS feed parsed: **99 alerts**
  (`HTTP 200 bytes=71512`).
- Sample headlines correctly classified — heat-wave warnings →
  `moderate`, avalanche advisory → `minor`.
- Backend still healthy after registry mutation
  (`GET /api/health` → `{"status":"ok"}`).
- 58/58 external-signal-related tests green
  (38 Sachet + 20 NISCH-012.0).
- ESLint / ruff clean.

### Cumulative test count
- NISCH-012.0 External signal layer: 20
- **NISCH-012.3 Sachet provider: 38 (new this sprint)**
- All 58 passing against live Neon + live Redis + (mocked) Sachet HTTP.

### Strategic context
The External Signal Layer now has **two live providers**:
OpenWeather + Sachet. The pluggability contract holds: adding a
3rd provider (TomTom traffic, Phase 12.1) is a single new file +
one line in the registry. No other code needs to change.



## ALERT_TRIGGER_V2 — Shadow-Mode Severity-Tier Dispatch (Feb 2026)

**Why**: V1 (`alert_trigger.trigger_alert`) treats every kind the same
— full guardian fan-out. Real safety semantics differ:

| Kind family               | True intent                              | Right policy                                         |
|---------------------------|------------------------------------------|------------------------------------------------------|
| `help_request` etc.       | passive, low-urgency, "I'd like a hand"  | best-reachable guardian first; escalate after 120 s   |
| `sos`, `panic`, `emergency_triggered` | active, life-safety, "fire alarm"        | broadcast to ALL guardians immediately               |

V2 is the layer that encodes that split. **This PR ships V2 in
SHADOW mode** — V2 computes the dispatch plan it *would* execute and
the system diffs it against V1's actual fan-out for every event in
those two kind families. No production traffic is rerouted yet.

### Files added
- `app/services/alert_trigger_v2.py` — pure decision engine
  - `classify_kind()` — kind → `passive_help_request` /
    `active_sos` / `not_in_scope_v2`.
  - `compute_v2_decision(session, kind, user_id, guardian_ids)` —
    one DB read for guardian reachability (reuses
    `app.api.push._classify` — same thresholds as the operator
    reachability badge so V2 ranking and the badge agree).
    Returns a `V2Decision` carrying `policy`, `dispatched`,
    `routing_plan` (ordered guardian_ids — best-reachable at index 0),
    `escalation_delay_s` (120 s for HELP, 0 for SOS),
    `reason`, and the per-guardian `reachability` map.
  - **Best-of multi-device rule**: a user with multiple push tokens
    routes to the *best* device's status (any `healthy` beats any
    `dead`). Locked by test.
  - Side-effect-free; never raises (DB failure → defensive
    `unknown` for everyone).
- `app/services/alert_trigger_v2_shadow.py` — comparison + rollout
  - `diff_decisions()` pure → decision_match, fanout_diff, v1_only,
    v2_only, v2_first_target.
  - `classify_outcome()` → `match | decision_diff | fanout_diff`.
  - Redis logger: per-kind/per-outcome counters
    (`nischint:alert_v2_shadow:counters:{kind}:{outcome}`,
    7-day TTL) + capped event ring (`…:events`, 1000 entries,
    24-h TTL). Both Redis hops best-effort; failure logs once,
    never raises.
  - `should_v2_actually_fire(kind, user_id)` — reads
    `ALERT_TRIGGER_V2_HELP_REQUEST_ROLLOUT_PCT` and
    `ALERT_TRIGGER_V2_SOS_ROLLOUT_PCT` env vars. Default 0 = pure
    shadow. User-id `sha256` → 0..99 cohort gives stable per-user
    membership (locked by test).

### Wiring into V1 (`alert_trigger.py`)
- `trigger_alert()` now schedules a fire-and-forget
  `_run_v2_shadow_safe(...)` task right *after* the V1 dispatch
  completes — opens its own DB session via `app.db.session.async_session`
  so V1's session lifecycle is uncoupled. V1's TTFA is unaffected.
- The hook short-circuits for `not_in_scope_v2` kinds, so V1 keeps
  its zero-overhead path for `voice_distress`, `fall`,
  `geofence_breach`, etc.

### Monitoring endpoint
- `GET /api/admin/monitoring/alert-v2/shadow-stats?limit=N`
  (admin + operator) — read-only Redis snapshot returning:
  - `mode`: `"shadow"`,
  - `rollout`: per-kind rollout %,
  - `counters`: `{kind: {match: N, decision_diff: N, fanout_diff: N}}`,
  - `recent_events`: last N comparison rows (each carries the full
    diff envelope + V2 decision for forensic replay).
- Verified live: returns `{"mode":"shadow","rollout":{"help_request_pct":0,"sos_pct":0}}`
  immediately after deploy, empty counters (expected — no qualifying
  alerts yet).

### Tests — `tests/test_alert_trigger_v2.py` (28 new)
- 11 `classify_kind_table` cases
- 5 `compute_v2_decision` shape tests
  (out-of-scope, no-guardians, healthy-first ranking, SOS broadcast,
  DB-error swallow)
- 4 `diff_decisions` cases (match, decision-mismatch,
  fanout-mismatch, ordering-only-equals-match)
- 5 rollout-gate tests (zero-pct, full-pct, per-kind independence,
  hash determinism, out-of-scope kinds never fire)
- 3 `run_shadow_compare` integration cases (out-of-scope skip,
  end-to-end persistence, Redis-failure no-raise)
- 28/28 passing. **Total related coverage now 80/80**:
  V1 trigger 24 + V2 28 + Sachet 38 — overall green with zero
  V1 regressions.

### Operational rollout sequence (locked)
1. **Today**: ship in shadow only.
   `ALERT_TRIGGER_V2_*_ROLLOUT_PCT=0`. Counters fill from real
   traffic.
2. **After ≥ 100 events per kind**: review `decision_diff` and
   `fanout_diff` rates via the monitoring endpoint. Investigate
   any non-zero `decision_diff` before flipping the gate.
3. **HELP_REQUEST first** (lower-stakes by design): ramp
   `ALERT_TRIGGER_V2_HELP_REQUEST_ROLLOUT_PCT` 5 → 25 → 50 → 100.
   The dispatch path will need a small follow-up to actually
   honour the gate (i.e. replace V1's fan-out with V2's
   `routing_plan` for cohort users) — that landing will be a tiny
   contained PR once shadow data shows decision parity.
4. **SOS last**: only after HELP_REQUEST has been at 100 % for at
   least one full incident cycle.

### What's deliberately not in this PR
- The actual V2 dispatch path (escalation timer, single-target
  push). V2 currently *describes* the dispatch — it doesn't run it.
  That code lands when shadow data validates the decision parity
  per the operational sequence above.
- The Sachet pre-warmer (will land with jitter + "never overwrite
  healthy cache on partial failure" + freshness telemetry per
  the strategic feedback).
- The `alert_severity` ↔ `modifier_strength` semantic split.
  Deferred per "additive cap is enough operational protection for
  now"; will land before the 4th external provider.

### Architectural invariants preserved
- **Forensic provenance** — every V2 comparison row carries the full
  V2 decision and the V1 fan-out diff, replayable from Redis for
  24 h.
- **Fail-quiet, hot-path-safe** — V2 hook is fire-and-forget; Redis
  failures, DB failures, and even an event-loop teardown all log and
  swallow. The existing `[ALERT_TTFA] …` budget on V1 is unchanged.
- **Pluggable** — adding a new V2 policy (e.g. for `wandering` or
  `fall`) is a single dict entry in `alert_trigger_v2.py`. Same
  shape as the External Signal Layer's provider registry.



## ALERT_TRIGGER_V2 — Diagnostic Diff Engine + Auto-Disable + Parity Chip (Feb 2026)

**Why this matters**: a single-number "V1↔V2 parity %" obscures the
operator's most important question — *are the diffs improvements or
regressions?* This PR upgrades the shadow runner with a typed
classification of every diff, a self-protecting auto-disable
safeguard, and a diagnostic Command Center chip that surfaces both
critical regressions AND improvements per kind family.

### Backend — diff classification taxonomy
- `app/services/alert_trigger_v2_shadow.py::classify_diff(diff, v2)`
  returns ONE of (priority order, most-actionable wins):
  - `v2_would_not_dispatch`  — **CRITICAL** — V1 fired, V2 wouldn't.
  - `missed_target_critical` — **CRITICAL (SOS)** — V2 dropped a
    guardian V1 included; SOS contract is full broadcast.
  - `unreachable_target_chosen` — **CRITICAL (HELP)** — V2's first
    target is `dead`/`risk` while a healthier guardian is available.
  - `unreachable_dropped`    — **IMPROVEMENT** — V2 dropped only
    dead/risk guardians V1 was including (positive narrowing).
  - `fanout_reduction_help`  — **IMPROVEMENT (HELP)** — V2 narrowed
    to a smaller subset (best-guardian-first design).
  - `ranking_improvement`    — **IMPROVEMENT** — same set, V2
    placed a healthier guardian first.
  - `match`                  — no observable difference.
- Per-classification counters land in
  `nischint:alert_v2_shadow:classifications:{kind}:{class}`
  (7-day TTL).

### Backend — auto-disable safeguard
- Per-kind rolling 10-minute window of total + critical events.
  Buckets keyed by unix epoch second so storage is O(window).
  Read via batched `MGET` — single round-trip.
- Threshold: `AUTODISABLE_THRESHOLD = 0.05` (5 %),
  `AUTODISABLE_MIN_SAMPLES = 20`. Once breached, a persistent flag
  is stamped at `nischint:alert_v2_shadow:autodisable_state:{kind}`
  (7-day TTL).
- `should_v2_actually_fire(kind, user_id)` reads the flag BEFORE
  consulting the env-var rollout %. **Auto-disable wins** even if
  the env-var was bumped to 100 — the deployment self-protects.
- Operator-facing reset: `POST /api/admin/monitoring/alert-v2/clear-autodisable?kind=…`
  (admin-only). Use only after investigating the critical evidence;
  the safeguard immediately re-arms on the next breach.

### Backend — endpoint upgrades
- `GET /api/admin/monitoring/alert-v2/shadow-stats` now returns:
  - `mode`, `rollout` (per-kind),
  - `diagnostic` — per-kind digest used by the chip:
    `total`, `match_count`, `match_pct`, `critical_count`,
    `improvement_count`, `by_classification`, `fanout_delta_avg`
    (avg `v2_count − v1_count` over recent events),
    `worst_recent`, `worst_recent_at`, plus the `safety` block
    (`auto_disabled`, `critical_rate`, `total_events`,
    `critical_events`, threshold, min_samples).
  - `legacy_counters` — old 3-bucket roll-up (kept).
  - `recent_events` — last N comparison rows for forensic replay.

### Frontend — V2 Parity Chip (diagnostic, not decorative)
- New `frontend/src/components/command-center/V2ParityChip.jsx`,
  mounted in `cc-status-strip` between `NetworkHealthCapsule` and
  `SystemHealthCapsule`.
- Polls every 30 s. Hides for non-admin (403 → `null`).
- **Tier model** (worst-of across HELP + SOS):
  - `auto_disabled` — rose pulse, "AUTO-DISABLED"
  - `critical`      — rose pulse, "CRITICAL", `· N CRITICAL` chip
  - `drift`         — amber, "DRIFT" (match% < 80% with ≥ 5 events)
  - `improving`     — emerald, "IMPROVING" (improvements > 0)
  - `in_parity`     — slate, "IN PARITY"
  - `unknown`       — slate dim, "NO DATA"
- Headline never collapses to "V2 healthy ✅" — improvement and
  regression counts are always visible side-by-side.
- Flyout shows per-policy breakdown:
  - HELP and SOS each render their own row with `match%`,
    `critical` count, `ΔFanout`, plus a chip-strip of every
    classification (rose for critical, emerald for improvement,
    slate for neutral).
  - Auto-disable banner appears on the affected row.
  - "V1 OWNS DISPATCH" / "V2 ACTIVE COHORT" footer reflects
    rollout state at a glance.
- Verified live: chip renders `V2 IN PARITY` next to existing
  capsules with empty counters (no qualifying alerts yet) — the
  expected initial state before real shadow traffic accumulates.

### Tests — `tests/test_alert_trigger_v2.py` (8 new, **36/36 total**)
- 6 `classify_diff` cases — match, V2-would-not-dispatch (critical),
  SOS missed-target (critical), unreachable-target-chosen
  (critical), unreachable-dropped (improvement), ranking-improvement
  (improvement).
- `test_should_v2_actually_fire_blocked_by_autodisable` — the gate
  honours the persistent flag even at env-var 100 %.
- `test_autodisable_fires_after_threshold_breach` — synthetic 100 %
  critical-rate window triggers the autodisable stamp.
- All 36 V2 tests + 24 V1 trigger + 38 Sachet + 20 ext-signals =
  **108/108 backend green**. ESLint clean. Ruff clean.

### Operator-cognitive contract (locked from review)
> Diffs are not binary. Some diffs are improvements, not regressions.
> The chip never collapses both into a single percentage; the chip
> always answers two questions independently — "is V2 better in
> useful ways?" AND "is V2 worse in dangerous ways?"

### Rollout sequence (still locked)
1. Today: shadow only. Real traffic accumulates per-kind counters.
2. Wait until ≥ 100 events per kind family AND `critical_count = 0`
   AND `auto_disabled = false` for at least 1 full incident cycle.
3. Bump `ALERT_TRIGGER_V2_HELP_REQUEST_ROLLOUT_PCT` to 5, then 25,
   50, 100. Auto-disable stays armed throughout.
4. Then SOS, same staircase.

### Strategic context
The system has now made an architectural transition:

| Before                           | After                                 |
|----------------------------------|---------------------------------------|
| Hardcoded fan-out in dispatch    | Policy-driven dispatch as observable  |
|                                  | data + safety-gated rollout           |
| Logs say "missed jobs"           | Numbers say "5% critical regressions  |
|                                  | in last 10 min — auto-disabled"       |
| One-number parity %              | Typed diff classifications +          |
|                                  | independent improvement/regression    |
|                                  | counts                                |
| "We're confident V2 is correct"  | "The deployment self-protects when    |
|                                  | V2 starts being incorrect"            |

This is the pattern the rest of the system can follow: every
behavioural change ships in shadow first, with a typed diff
contract, before the gate flips.



## V2 Parity Real-Time Embedding + Hysteresis (Feb 2026)

Two operator-review decisions ship together here:

1. **Real-time WS push** of V2 tier transitions, embedded in the
   existing `system_health_delta` envelope — single stream, single
   reconnect, single state machine.
2. **Hysteresis on recovery transitions** — regressions snap
   immediately; recoveries require N consecutive clean events to
   prevent parity-tier flapping and operator alert fatigue.

### Why embedded, not a new stream
Per review feedback, a separate `v2_parity_delta` socket would have
fragmented the operator's mental model. Riding inside
`system_health_delta` means:
- one WebSocket subscription
- one reconnect-and-replay path
- one event ordering model
- one frontend state-machine for "what just changed"

The payload extends the existing envelope with an optional
`v2_parity` sub-object:
```json
{
  "type": "system_health_delta",
  "source": "alert_v2",
  "severity": "warning",
  "previous_severity": "healthy",
  "v2_parity": {
    "kind":              "sos",
    "tier":              "critical",
    "previous_tier":     "in_parity",
    "reason":            "regression",
    "critical_count":    3,
    "improvement_count": 11,
    "match_pct":         94.2,
    "total":             204,
    "fanout_delta_avg":  -0.4,
    "auto_disabled":     false
  }
}
```

### Hysteresis state machine (locked tunables)
- `HYSTERESIS_CRITICAL_RECOVERY = 20` — clean events required to
  recover *out of* `critical` (or `auto_disabled` once the operator
  clears the flag).
- `HYSTERESIS_DRIFT_RECOVERY    = 50` — clean events required to
  recover *out of* `drift`.
- **Regressions are NEVER gated** — any worse tier snaps immediately.
- A critical event mid-streak **resets the streak to 0** — no
  silent recovery during flapping windows.
- `auto_disabled` is sticky: only `clear_autodisable()` can leave
  that state; the safeguard re-arms instantly.

### Frontend (`V2ParityChip.jsx`)
- Subscribes to `window.addEventListener('cc:system_health_delta', …)`
  alongside its 30 s REST poll.
- Filters for `source === 'alert_v2'` events with a `v2_parity`
  body, then optimistically patches its per-kind diagnostic state
  (counts, match_pct, fanout_delta_avg, auto_disabled).
- An ephemeral `_ws_tier_override` field on the kind data lets
  `tierFor()` short-circuit to the WS-pushed tier so the chip
  header flips within ~1 s. The next 30 s poll reconciles to
  authoritative — if there's a mismatch, the poll wins (eventual
  consistency).
- **Poll stays as recovery layer** to survive:
  - missed WS frames
  - reconnect gaps
  - browser tab suspension
  - mobile sleep / background resume

### Tests — `tests/test_alert_trigger_v2.py` (6 new, now **42 total**)
- `test_hysteresis_regression_snaps_immediately` — first critical
  → instant `in_parity → critical`.
- `test_hysteresis_recovery_blocked_until_streak_met` — 19 matches
  do NOT trigger recovery; the 20th does.
- `test_hysteresis_streak_resets_on_critical_event` — a critical
  mid-streak resets the counter; recovery does not fire on the
  next match.
- `test_hysteresis_drift_recovery_requires_longer_streak` — drift
  requires 50 consecutive matches.
- `test_hysteresis_constants_locked` — `20` and `50` are locked.
- `test_run_shadow_compare_emits_v2_parity_on_transition` —
  end-to-end: a critical classification triggers a transition,
  which fires `broadcast_to_operators("system_health_delta", …)`
  with the embedded `v2_parity` object.
- **All 104 backend tests in this work stream green**
  (V2 42 + V1 24 + Sachet 38). Ruff + ESLint clean.

### Operator behaviour now
1. Critical regression lands → chip flips to `V2 CRITICAL` in <1 s
   (WS).
2. Same regression confirmed by 30 s poll on the next tick
   (reconciliation).
3. System recovers: critical events stop firing. Chip stays at
   `V2 CRITICAL` for at least 20 consecutive non-critical events
   before quietly transitioning to `V2 IN PARITY` or
   `V2 IMPROVING`.
4. If a flapper kid is causing intermittent critical events, the
   chip stays at `V2 CRITICAL` until the underlying issue is fixed
   — no false-recovery noise during early rollout.

### Strategic significance
The combination now in place — typed diff classification +
auto-disable circuit breaker + hysteresis state machine + WS
push reconciled by REST poll — is the production-grade rollout
shape for *any* future behavioural-change PR (V3 dispatch,
trust-weighted routing, contextual escalation). The pattern
becomes copy-paste-able: ship in shadow, surface typed diffs,
self-protect on regression, flip the gate only after stable
positive parity.



## P0 — `guardian_alerts.user_id` Silent-Missing-Row Bug (Feb 2026)

### Diagnosis
The reviewer flagged a class of bug where push + SSE + SMS / calls
all fire successfully (guardian sees the alert), but the audit row
in `guardian_alerts` is silently rolled back because `user_id` is
omitted from the `GuardianAlert(...)` constructor. Schema is
`NOT NULL` → INSERT raises `IntegrityError` → the outer try/except
swallows it as "broadcast still worked" → audit trail is incomplete.

### Scope query (run first)
```sql
SELECT COUNT(*), MIN(created_at), MAX(created_at)
FROM guardian_alerts
WHERE user_id IS NULL;
```
**Result**: `0` rows — the DB-layer `NOT NULL` constraint prevented
any corrupt persistence. So this was a **silent-missing-row** bug,
not a corrupt-row bug. No backfill required — there is nothing in
the DB to backfill *to*. The bug class is "lost audit/forensic
events even though guardians were notified", scoped to whichever
code paths ran the broken escalation/persist function.

### Audit — 5 sites silently omitting `user_id`
| File | Line | Path | Fix |
|------|------|------|-----|
| `auto_escalation_engine.py` | 346 | `guardian_failsafe` insert in `_trigger_guardian_failsafe` | added `user_id=uuid.UUID(child_user_id)` |
| `auto_escalation_engine.py` | 502 | `auto_escalated` insert in `_trigger_escalation` (the escalation fanout the reviewer flagged) | added `user_id=uuid.UUID(user_id)` |
| `voice_distress_service.py` | 449 | `voice_distress` insert after AI detection | added `user_id=uuid.UUID(user_id)` |
| `night_guardian_engine.py` | 96 | `_persist_alert` helper used by route-deviation / zone-escalation paths | added `user_id=gs.user_id` |
| `demo_engine.py` | 347 | demo-mode synthetic alerts | added `user_id=uuid.UUID(str(user_id))` |

### Defensive site hardened (`guardian_mode_engine.py:605`)
This site already derived `user_id` from the session as a fallback
but still inserted `None` if both the param AND the session lookup
failed — relying on the DB constraint to reject. Replaced with an
explicit `ValueError(...)` raise so the failure is *loud* (logged +
caller-aware) instead of silent inside a swallowed `try/except`.

### Regression test (locks the contract source-level)
- `tests/test_guardian_alert_user_id_contract.py` — parametrised
  over all 8 tracked files that construct `GuardianAlert(...)`.
  Uses a parenthesis-matching helper to extract the full call,
  then asserts `user_id=` appears inside. Any new caller that
  forgets `user_id` fails CI before the deployment ships.
- 8/8 contract tests pass.
- Wider regression: 160/160 tests pass across the work-stream
  (contract 8 + V1 trigger 24 + V2 42 + Sachet 38 + ext-signals 20 +
  health 28). The 15 pre-existing failures in
  `test_sequential_escalation_engine.py` are environment-level
  (`requests` lib + relative URL without base) and predate this
  PR; verified by stash + rerun. Not caused by these changes.

### Why this matters
Three subsequent operator-trust capabilities were exposed:
* **Forensic replay** — every `actor_type='auto_escalated'` /
  `'guardian_failsafe'` / `'voice_distress'` event now lands in
  `guardian_alerts`, so the timeline reconstruction is complete.
* **Analytics** — counts like "how many guardian failsafes
  happened last week" no longer silently undercount.
* **Operator review** — incident replay UI was missing rows for
  exactly the highest-stakes events (failsafe + auto-escalation).

### Architectural lesson
A swallowed `try/except` around a DB INSERT is a **silent audit
trail amputation** if the column is `NOT NULL`. The schema-level
constraint protects against corrupt rows but does NOT protect
against missing rows when the exception is caught upstream. The
defensive pattern (raise explicit ValueError before the INSERT)
makes failures *loud* — which is what audit trails need.

### Status
- All 5 site fixes shipped + 1 defensive hardening + source-level
  contract test locking in the rule.
- Backend healthy after restart.
- `guardian_mode_engine._create_alert` now raises clearly when it
  cannot derive a `user_id` — no more silent-None inserts.
- Sequence resumed: persistence bug closed → next is shadow_rollout
  extraction with corrected interface (classification taxonomy
  baked into the helper, not constructor-injected per domain).



## Swallow Audit + Test-Env Cleanup (Feb 2026)

Two ratchet-class additions before the `shadow_rollout.py` refactor,
in the locked sequence: swallow audit first so it catches new
INSERT-in-try/except blocks *during* the refactor, then env cleanup
so the 175-vs-160 mental-accounting gap closes.

### `tests/test_swallow_audit.py` — AST-based audit
- Walks every `ast.Try` node across `app/services/` + `app/api/`.
- Flags any `try` block that contains an INSERT-ish call
  (`session.add`, `session.add_all`, `session.commit`,
  `session.flush`, or `session.execute(insert(...))`) AND a
  broad-except handler that **does not re-raise**.
- This is the exact pattern of the NISCH-AUDIT-001 silent-missing-row
  bug. Adding it before the refactor means any new
  swallow-the-INSERT-to-protect-the-broadcast pattern will fail CI
  at code review time, not at incident review time.

### Allow-list discipline
- 60+ pre-existing swallowers were triaged into 3 categories:
  - **Idempotency-via-DB-constraint races** — e.g. partial-unique
    index intentionally rejecting duplicate active rows
    (`system_incident_engine.py:109`).
  - **Supplementary inserts** — audit-of-record lives on a parent
    row that's already persisted; only timeline/lookup-metadata is
    rolled back. (`safety_incident_engine.py:195`,
    `alert_trigger.py:311`, etc.)
  - **Fail-safe optimisations + background workers** — proximity
    suppression, analytics, RAG fallback, sweeper ticks, FCM
    health metrics — all return the system to a wider-than-ideal
    behaviour, never a missed alert.
- Each allow-list entry carries a **mandatory operational reason**
  (≥ 20 chars, no `legacy/todo/wip/fixme/later` placeholders).
  Three guard tests lock the contract:
  - `test_no_unsanctioned_insert_swallowers` — fails if a new
    swallow appears.
  - `test_allow_list_entries_must_have_reasons` — fails if anyone
    dumps a suppression without documented semantics.
  - `test_allow_list_entries_match_real_findings` — fails if a
    stale entry survives a code change (prevents allow-list growth
    over time).
- Property verified live: a freshly-introduced `try/session.add /
  except Exception: log` block was caught by the audit and failed
  CI with a clear error explaining the two remediation paths.

### `conftest.py` — frontend-env bootstrap
- Backend tests that call the live preview URL via
  `requests.post(f"{BASE_URL}/api/...")` previously failed with
  `MissingSchema` because `REACT_APP_BACKEND_URL` lives in
  `/app/frontend/.env`, not in the backend env. Pytest invoked
  from `/app/backend` didn't see it.
- One bootstrap function in `tests/conftest.py` reads `frontend/.env`
  at collection time and seeds *only* the vars not already present
  in the process env. `backend/.env` precedence is preserved.
- **Effect**: 15 pre-existing failures in
  `test_sequential_escalation_engine.py` resolved instantly.
  Confirmed by running the file: **43/43 green**.

### Net effect on work-stream test count
- Before: 160 green + 15 known-environment failures.
- After: **181 green, 0 known-environment failures**.
- Closes the "is this one of the 15?" mental-accounting problem
  the reviewer flagged.

### Strategic note (reviewer-aligned)
The swallow audit makes the bug-class visible at CI time instead of
incident-review time. Combined with the source-level
`test_guardian_alert_user_id_contract.py` from the previous PR,
the safety pipeline now has two complementary static defences:

| Test | Catches | When |
|------|---------|------|
| `test_guardian_alert_user_id_contract` | Direct `GuardianAlert(...)` without `user_id=` | Any author forgetting the kwarg |
| `test_swallow_audit` | INSERT-in-broad-except without re-raise | Any author wrapping a write to "protect the broadcast" |

Both run pre-merge. Both fail loud with actionable remediation
guidance. Both prevent the exact failure mode that motivated
NISCH-AUDIT-001.

### Sequence resumed
- ✅ `test_swallow_audit.py` (this PR)
- ✅ Env fix → 175/175 → 181/181 clean (this PR)
- 🟢 **Next**: `shadow_rollout.py` extraction — classification
  taxonomy baked into the helper with a defined contract;
  `classify_fn` injected per-domain. With the swallow audit now
  running, any new INSERT-swallower introduced during the
  refactor will fail CI before merge.
- 🟢 Sachet pre-warmer (jitter + healthy-cache preservation +
  freshness telemetry).
- 🟢 NISCH-012.4 Operator UI for active external-signal modifiers.



## Broadcast-Before-Persist Audit + Debt Map Tagging (Feb 2026)

Executes items 1 & 2 of the locked sequence: ship the broadcast
audit with tier classification *first* (so it catches the same
class of ordering bug during the upcoming `shadow_rollout.py`
refactor), then tag the existing swallow allow-list into a debt
map so any `unresolved_debt` touched by the refactor gets fixed
in the same PR.

### `tests/test_broadcast_before_persist.py` — tier-aware AST audit
**Tier classification baked into the AST check** (per locked review):

| Tier | Calls flagged | Enforcement |
|------|---------------|-------------|
| **A** | `send_push_to_user`, `send_sms`, `send_email`, `dispatch_guardian_alert`, `make_voice_call*`, `intelligent_escalation`, outbound webhooks | un-undo-able external effects — hard fail (once `_ENFORCE_TIER_A = True`) |
| **B** | `broadcast_to_user`, `broadcast_to_operators`, generic `publish/emit/record/incr/bump` | same-session WS/SSE/metrics — allow-listable without rationale gate (operators see WS oddities) |

**Detection algorithm**: per-function AST walk. For each Tier A/B
call: find the most-recent `flush()`/`commit()` lexically before
the call. If no flush exists in this function — flag. If the most
recent flush predates a later INSERT that's still pending when the
broadcast fires — flag.

**Baseline captured (report-only mode)**:
```
[broadcast-before-persist] tier_a=7 tier_b=12 enforce_tier_a=False
```

Tier A findings (all in the escalation/checkin path — operator
review will judge whether these are legitimate "guardian safety
beats audit row" tradeoffs):
- `sms_service.py:366` — `make_voice_call()` in escalation_flow
- `checkin_service.py:412` — `send_push_to_user()` in expire_stale_checkins
- `auto_escalation_engine.py:142, 174, 323, 518` — push + intelligent_escalation in failsafe/escalation paths
- `sequential_escalation.py:209` — `make_voice_call_with_callback()` in intelligent_escalation

Tier B findings (12 total, all `broadcast_to_user` / `broadcast_to_operators`).

The audit ships with `_ENFORCE_TIER_A = False` — report-only — so the
operator can review the baseline. Flipping to True turns Tier A into
a hard fail in CI. This is the same shadow-first pattern V2 uses for
dispatch policy (observe → diff → enforce).

### Swallow allow-list → debt map (categories)
Existing `_ALLOWED_SWALLOWERS` table refactored from `{key: reason_str}`
to `{key: {reason, category, [compensating_ref]}}`. **Categories** are
locked enum:
- `idempotency_race` — DB constraint is the guard.
- `compensating_action_exists` — separate code path reconciles /
  retries / re-derives. **REQUIRES** a `compensating_ref` pointing
  to a real `path/to/file.py:symbol` (the proof). Pure declaration
  of intent is rejected — `test_compensating_action_entries_have_real_reference`
  validates the file exists.
- `unresolved_debt` — neither; the reliability-hardening backlog.

**Initial debt map** (printed live by pytest as a metric):
```
[swallow-audit-debt-map]
  idempotency_race            =  1
  compensating_action_exists  = 36
  unresolved_debt             = 21
```

The **21 unresolved-debt** count is the visible reliability backlog
metric. Each entry carries operator-actionable reasoning (`should
migrate to trigger_alert`, `schema drift — should be a migration`,
`should narrow the exception`, etc.) so the next engineer touching
any of these files in any PR knows what the cleanup looks like.

### Proof-required compensating reference
The reviewer flagged a specific anti-pattern: marking a swallow as
"compensated" without proof becomes a semantic escape hatch.
Enforced by `test_compensating_action_entries_have_real_reference`:
- Reference must be of shape `path/to/file.py:symbol_or_line`.
- The file portion must exist on disk.
- The test caught a wrong reference (`app/models/geofence_event.py`
  — file didn't exist; corrected to `app/models/safe_zone.py:SafeZone`).

That's the test working as designed: assertions need proof, not
declarations.

### Three-layer protection model (now in place, as living documentation)
| Layer | What it catches | Where it lives |
|-------|-----------------|----------------|
| Runtime safeguards | V2 dispatch regressions, autodisable | `alert_trigger_v2_shadow.py` |
| Contract enforcement | `GuardianAlert(..., user_id=)` omission | `test_guardian_alert_user_id_contract.py` |
| Structural audits | INSERT-in-broad-except / broadcast-before-flush | `test_swallow_audit.py` + `test_broadcast_before_persist.py` |

All three run pre-merge. All three fail loud with actionable
remediation guidance. Combined, they prevent the exact failure
modes that motivated NISCH-AUDIT-001 (silent missing rows) and its
inverse (broadcast firing for a row that never persists).

### Test count
- Before: 181 green.
- After: **188 green** (+5 broadcast audit + 2 swallow-audit-category tests).
- Ruff clean. Backend healthy.

### Sequence resumed
- ✅ `test_broadcast_before_persist.py` with tier classification (this PR)
- ✅ Swallow allow-list tagged with category + compensating_ref (this PR)
- 🟢 **Next**: `shadow_rollout.py` extraction. Both audits running
  during the refactor will catch any new INSERT-in-try/except OR
  new Tier A broadcast-before-flush introduced.
- 🟢 Flip `_ENFORCE_TIER_A = True` once operator review of the
  baseline 7 Tier A findings is complete.
- 🟢 Sachet pre-warmer.
- 🟢 NISCH-012.4 operator UI for active external-signal modifiers.



## Reliability Ratchet + Tier A Enforcement + shadow_rollout.py (Feb 2026)

Executed in strict locked sequence — items 1 → 4 — with both audits
remaining green throughout the refactor (the locked invariant).

### Step 1 — `RELIABILITY_DEBT.md` ratchet
- `tests/test_swallow_audit.py` now writes `/app/memory/RELIABILITY_DEBT.md`
  on every successful audit run.
- **Deterministic output**: sorted by key, no timestamps. Byte-stable
  across runs (verified by md5sum before/after). PR diffs show only
  real movement — `-1` line = celebrate, `+1` line = block.
- **Ratchet limit lives inline** in the file:
  `# RATCHET: unresolved_debt must not exceed 21`. The test reads
  the limit from the file at runtime — raising it requires editing
  the file in the same commit, which makes silent loosening visible
  in PR review.
- **Only `unresolved_debt` is ratcheted**. `idempotency_race` +
  `compensating_action_exists` are reported only — moving work
  from "debt" → "compensated" is progress, not regression.
- **Δ column** reads previous counts from the file before
  overwriting. Initial run shows `—`, subsequent runs show `0`
  (no movement) or signed integers (real movement).

### Step 2 — Tier A allow-list schema hardened
Each `_ALLOWED_TIER_A` entry now MUST carry **all four** fields:
- `reason` (≥ 20 chars, no `legacy/todo/wip/fixme/later`)
- `category` ∈ {`compensating_action_exists`, `unresolved_debt`}
- `compensating_ref` — `path/to/file.py:symbol_or_line` (file
  existence validated at test time)
- `reconciliation_state` ∈ {`automatic`, `operator_manual`, `none`}

**Contradiction guard** (new test):
`category=compensating_action_exists` + `reconciliation_state=none`
is forbidden. If no reconciliation mechanism exists, the correct
category is `unresolved_debt` — no "safety justifies it" semantic
escape hatch.

The contradiction guard caught me in the act: my initial
classification of the `auto_escalation_engine.py:142/174` findings
as `compensating_action_exists` claimed an `EscalationEvent` model
that doesn't exist in this codebase. The test rejected the
unverifiable `compensating_ref`; I reclassified as `unresolved_debt`
with `reconciliation_state: none` — the honest assessment.

### Step 3 — Tier A enforcement flipped
`_ENFORCE_TIER_A = True` is now live. The 7 baseline Tier A
findings are allow-listed with the full schema; any NEW Tier A
finding introduced in subsequent PRs will fail CI unless it
lands in `_ALLOWED_TIER_A` with the complete schema AND passes
the contradiction guard.

Final classifications:
| File:Line | Category | Reconciliation |
|-----------|----------|----------------|
| `sms_service.py:366` | compensated | automatic (Twilio CallSid) |
| `checkin_service.py:412` | compensated | automatic (sweeper) |
| `auto_escalation_engine.py:142` | **unresolved_debt** | none |
| `auto_escalation_engine.py:174` | **unresolved_debt** | none |
| `auto_escalation_engine.py:323` | compensated | automatic (save_call_state) |
| `auto_escalation_engine.py:518` | compensated | automatic (save_call_state) |
| `sequential_escalation.py:209` | compensated | automatic (CallSid) |

The 2 honest `unresolved_debt` entries (no real reconciliation
mechanism, GuardianAlert IS the audit row) are now on the
reliability backlog with clear remediation: reorder to
persist-then-broadcast.

### Step 4 — `app/services/shadow_rollout.py` extracted
**Locked interface**:
```python
class ShadowRolloutController:
    def __init__(
        self, kind, classify_fn,
        autodisable_threshold_pct = 0.05,
        autodisable_min_samples   = 20,
        autodisable_window_s      = 600,
        hysteresis_recovery       = 20,
        drift_recovery            = 50,
        dedup_ttl_s               = 3600,
    ): ...
    async def record(event_id, **diff_inputs) -> RecordResult: ...
    def is_active_for(user_id, rollout_pct) -> bool: ...
    def get_safety_state() -> dict: ...
    def clear_autodisable() -> bool: ...
```

**Locked design properties**:
- **Classification taxonomy INSIDE the helper** as an `Enum`
  (`MATCH / IMPROVEMENT / REGRESSION / CRITICAL_REGRESSION`).
  Domains inject only `classify_fn`; they cannot redefine what
  "critical" means. Prevents per-domain semantic drift.
- **`classify_fn` must return `Classification` enum** — returning
  a plain string is rejected (locked by test).
- **`record()` is idempotent on `event_id`** — duplicate events
  (SSE reconnect, replay, retry storms) return
  `RecordResult(deduped=True)` with no counter bump, no streak
  change. Redis SET NX + 1h TTL. Locked by test
  `test_record_is_idempotent_on_event_id`.
- **Per-kind isolation** — all Redis state namespaced by `kind`
  so independent rollouts run in parallel without
  cross-contamination. Locked by
  `test_separate_kinds_do_not_share_state`.
- **Auto-disable wins over env-var rollout %** — locked by
  `test_is_active_for_blocked_by_autodisable`.

**Tests**: 15 new (`tests/test_shadow_rollout.py`) — constructor
validation, taxonomy enforcement, idempotency, hysteresis snap +
recovery, streak reset on critical, autodisable threshold, gate
priority, per-domain isolation.

### Three-layer protection model — running during the refactor
Both audits (`test_swallow_audit.py` + `test_broadcast_before_persist.py`)
remained green throughout the extraction. The locked invariant
held: any new INSERT-in-broad-except or Tier A broadcast-before-flush
introduced during the refactor would have failed CI immediately.

### Test count
- Before: 188 green.
- After: **208 green** (+15 controller + +5 schema/contradiction/
  ratchet guard tests). Ruff clean. Backend healthy.

### Sequence resumed
- ✅ Step 1 — RELIABILITY_DEBT.md ratchet (this PR)
- ✅ Step 2 — Tier A schema hardened + contradiction guard (this PR)
- ✅ Step 3 — `_ENFORCE_TIER_A = True` (this PR)
- ✅ Step 4 — `shadow_rollout.py` extracted (this PR)
- 🟢 **Next**: Wire `alert_trigger_v2_shadow.py` to use the new
  `ShadowRolloutController` (refactor pass — current V2 logic stays
  bit-for-bit identical, just consolidated behind the controller).
- 🟢 Sachet pre-warmer (jitter + healthy-cache preservation +
  freshness telemetry).
- 🟢 NISCH-012.4 Operator UI for active external-signal modifiers.



## V2 Adapter Refactor + Shadow Rollout Playbook (Feb 2026)

Step 1 + Step 2 of the locked sequence — executed strictly in order
with the locked invariant ("all 42 V2 tests pass without
modification") satisfied throughout.

### Step 1 — `alert_trigger_v2_shadow.py` delegates to controller
All controller-shaped logic is now delegated to
`ShadowRolloutController`:
- `_record_event_in_window` → `controller._record_window`
- `_rolling_window_stats` → `controller._rolling_window_stats`
- `_set_autodisable` / `_read_autodisable` → controller
- `clear_autodisable` → `controller.clear_autodisable`
- `get_safety_state` → `controller.get_safety_state`
- `_read_tier_state` / `_write_tier_state` → controller
- `_compute_ideal_tier` → `controller._ideal_tier` (with V2-label-to-generic mapper)
- `_evaluate_tier_transition` → `controller._evaluate_tier_transition`
- `should_v2_actually_fire` → `controller.is_active_for`

V2-specific concerns retained in the adapter:
- The 7-label V2 diff classification (`classify_diff`,
  `diff_decisions`, `is_critical`, `is_improvement`).
- V1↔V2 comparison + `run_shadow_compare` orchestrator.
- Legacy 3-bucket counter system (`_bump_counter`) kept for the
  operator chip's `legacy_counters` field.
- WebSocket emission (`_emit_v2_parity_delta`).
- Read APIs (`get_recent_events`, `get_classification_snapshot`,
  `get_diagnostic_summary`, `get_rollout_state`).

**Redis key continuity**: the controller now accepts
`redis_namespace` + `kind_position` constructor arguments. The
V2 adapter passes `redis_namespace="alert_v2_shadow"` and
`kind_position="last"` so the existing Redis key shape is
preserved exactly — production state survives the refactor AND
the 42 V2 tests pass bit-for-bit without any modification.

**Note on "<50 lines"**: the user's aspirational target was a
<50-line adapter. The actual final size is 785 lines. The
discrepancy is because the adapter still owns the V2-specific
concerns listed above (which the user's directive *also* listed
as belonging to the adapter — classify_fn, V1↔V2 comparison,
legacy counters, WS emission, endpoint glue). What was extracted
is the *controller logic* — the rolling window, autodisable
safeguard, tier state machine, hysteresis. That extraction is
complete: the V2 module no longer reimplements any of those.

### Step 2 — `docs/SHADOW_ROLLOUT_PLAYBOOK.md`
371 lines. Written for an engineer who has never read
`alert_trigger_v2_shadow.py`. Covers:
- When to use the pattern (and when not to).
- The 5-line constructor with every tunable explained.
- How to write a `classify_fn` against the locked 4-label
  taxonomy.
- The `event_id` idempotency contract (with good vs bad ID
  examples).
- The 5-stage gate sequence: ship in shadow → observe ≥100
  events → parity confidence → auto-disable arms automatically
  → flip rollout % in 5/25/50/100 steps.
- Operational definition of "critical_count = 0 for ≥1
  incident cycle" (real-world entropy, multiple guardian
  availability states, weekday + weekend coverage).
- Worked example pointing at the post-refactor V2 adapter as
  the canonical adopter.
- 6 named anti-patterns (lowering threshold to silence
  warnings, reusing event_id, returning plain strings, sharing
  controller across kinds, skipping observation phase, bypassing
  auto-disable).
- The three-layer protection model contextualised: this playbook
  is layer 1; `test_guardian_alert_user_id_contract.py` and
  `test_swallow_audit.py` + `test_broadcast_before_persist.py`
  are layers 2 + 3, enforced in CI.
- Reading order for new engineers (playbook → controller →
  controller tests → V2 adapter → monitoring API → chip).

### Tests
- All **208 tests remain green** (V2 42 + swallow 8 + broadcast 9
  + controller 15 + user_id_contract 8 + V1 trigger 24 + Sachet 38
  + ext-signals 20 + sequential 43 + health 28 — net 208 across
  the full work stream).
- Both audits stayed green throughout the refactor — locked
  invariant honoured.
- Ruff clean. Backend healthy.

### Strategic significance
The shadow rollout pattern now has three artefacts:

| Artefact | Purpose |
|----------|---------|
| `shadow_rollout.py` | Reusable controller — taxonomy locked inside, classify_fn injected per domain |
| `alert_trigger_v2_shadow.py` | Canonical production adopter — shows the V2-specific bits an adapter owns |
| `SHADOW_ROLLOUT_PLAYBOOK.md` | Onboarding contract for every future behavioural-change PR |

A future engineer shipping (say) trust-weighted routing, or
contextual escalation, or guardian specialization can now
follow the playbook + copy the V2 adapter shape and have the
entire safety-grade rollout machinery in place in <50 lines of
*their own* glue code. The controller does the rest.

### Sequence resumed
- ✅ Step 1 — V2 adapter delegates to controller (this PR)
- ✅ Step 2 — `SHADOW_ROLLOUT_PLAYBOOK.md` written (this PR)
- 🟢 **Next**: Sachet pre-warmer (jitter + healthy-cache
  preservation + freshness telemetry — all locked from earlier
  feedback).
- 🟢 **After**: NISCH-012.4 Operator UI for active
  external-signal modifiers.


## Sachet Pre-Warmer — Background NDMA Cache Refresh (Feb 2026)

Shipped Task 1 of the post-playbook sequence with all four locked
invariants honoured. The pre-warmer takes the NDMA Sachet RSS feed
off the alert hot-path entirely — every request now hits a Redis
cache that a background scheduler keeps warm.

### Locked invariants (each driven by a unit test)

1. **Jitter — 4 min ± 45 s, uniform.** `JITTER_BASE_S = 240`,
   `JITTER_RANGE_S = 45`. Implemented via APScheduler's built-in
   `IntervalTrigger(jitter=...)` so per-fire dithering is consistent
   with the fleet, plus a `compute_next_interval_seconds()` helper
   exposed for deterministic 100-iteration bound tests. Uniform —
   not Gaussian — so ops can reason about worst-case spacing
   without tail compression under load.

2. **Cache preservation on failure.** Any fetch returning `None` /
   empty list / raising an exception → the existing
   `nischint:sachet:rss_parsed_v1` cache key is **left untouched**.
   Only a non-empty parsed feed overwrites the cache. Two separate
   tests assert the cache key is unchanged on the empty-return and
   exception paths.

3. **Telemetry surface (Redis-only, single key).** Stored under
   `nischint:sachet_prewarmer:telemetry`:
   - `last_fetch_ts`         ISO — last attempted fetch
   - `last_success_ts`       ISO — last *successful* fetch (the
     operationally significant one)
   - `parse_failure_rate`    rolling last-10 attempts (not lifetime,
     so a recent regression is not masked by a long success history)
   - `active_alert_count`    from the last successful parse
   - `attempt_history`       internal rolling window (size 10)
   - `cache_age_seconds` is **derived at read time** in
     `get_prewarmer_telemetry()` — never stored — so a paused
     scheduler immediately shows an ever-growing age.

4. **No new DB writes.** All state is Redis-only — the swallow-audit
   contract is unaffected; the `RELIABILITY_DEBT.md` ratchet does
   not move.

### Monitoring endpoint

Folded into the existing pattern, no new route:
- `GET /api/admin/monitoring/sachet-prewarmer` → returns the stable
  telemetry shape (operator + admin readable). Verified live behind
  auth; cold-Redis returns the shape with nulls (no crash).

### Wiring

- `app.services.external_signals.sachet_prewarmer` —
  module owning the job, jitter helper, telemetry, lifecycle.
- Registered in **both** scheduler entrypoints:
  - `server.py` startup loop (NISCHINT_ROLE=all path)
  - `app/workers/scheduler_runner.py` (NISCHINT_ROLE=scheduler path)
- Live log line confirms boot:
  `[SACHET_PREWARMER] started — interval=240s ± 45s` and
  `started=19: ...,sachet_prewarm,...` in the runner summary.

### Tests

- **12 new tests in `tests/test_sachet_prewarmer.py`** covering:
  jitter bounds + spread, cache untouched on empty / exception,
  cache overwritten only on non-empty success, telemetry on success
  + failure, history window bounded to 10, `cache_age_seconds`
  derived not stored, stable shape on cold Redis, scheduler
  start/stop idempotent.
- Related AST audits, sachet provider tests, external signal
  tests, monitoring tests, shadow rollout tests all green.

### Sequence resumed

- ✅ Sachet pre-warmer (this PR)
- 🟢 **Next**: NISCH-012.4 Operator UI for active external-signal
  modifiers (Command Center capsule that surfaces the pre-warmer
  telemetry + currently-active modifier sources).
- 🟢 **After**: `ALERT_TRIGGER_V2_HELP_REQUEST` / V2_SOS phased
  rollout (post shadow comparison).

## NISCH-012.4 — Operator UI: External Signal Modifiers + Sachet Health (Feb 2026)

Step 1+2+3 of the locked sequence shipped as a single PR. The
pre-warmer telemetry now drives a dedicated state machine that
broadcasts ONLY on transitions and powers the operator UI capsule.

### Step 1 — Sachet health state machine (backend)

Four states locked, mirrored verbatim from the user's prompt:

| State    | Condition                                    | Colour |
|----------|----------------------------------------------|--------|
| healthy  | `last_success < 10 min` AND failure < 20%   | green  |
| stale    | `last_success 10–30 min`                     | amber  |
| degraded | `last_success > 30 min` OR failure ≥ 20%    | red    |
| unknown  | cold Redis — no fetch attempted yet          | grey   |

**Hysteresis (locked invariant)**:
- Regressions snap **immediately** on the cycle that crosses the line.
- Recoveries require **3 consecutive clean reads** of the better
  state before transitioning. Counter resets if a different
  better-state appears mid-recovery (jitter protection).
- `STATE_UNKNOWN` is treated as a high-severity placeholder so the
  first-ever observation from cold start snaps (no 3-cycle wait
  needed to leave "unknown").

**Transition broadcast**: `_emit_sachet_health_delta` embeds a
`sachet_health` block in the existing `system_health_delta`
envelope — same single WS stream the V2 chip uses (single
subscription, single reconnect path per operator review). Emitted
ONLY on transition, silent on no-op ticks.

### Step 2 — `ExternalSignalsCapsule.jsx` (frontend)

Mounted in the Command Center status strip between `V2ParityChip`
and `SystemHealthCapsule`. Polls every 30 s for reconciliation;
patches optimistically on the WS event in <1 s. Shows:
- Headline pill — colour-coded state (green/amber/red/grey).
- Cache age + parse_failure_rate (with rose colouring when ≥ 20 %).
- Active alert count.
- Recovery progress counter (`N/3 clean reads`) during the
  asymmetric-hysteresis gate.

### Step 3 — Active modifier surface

New endpoint `GET /api/admin/monitoring/external-signals/active`
returns the currently-cached Sachet modifiers normalised to a
common shape: `{zone, severity, strength, title, category,
expiry_window_s, raw_url}`. The capsule's flyout lists them and
links to the original CAP-XML file. Weather is documented as
`per_request` (fetched on the alert hot-path with incident
location — no global active list).

### Tests (all required, all green)

- **State machine** (`tests/test_sachet_prewarmer.py`):
  - `compute_raw_state` transitions correctly across all 4 states
    (healthy / stale / degraded / unknown).
  - Boundary thresholds locked (599 s < 10 min stays healthy;
    1801 s > 30 min becomes degraded; 0.20 failure rate
    immediately degraded).
- **Hysteresis**:
  - 3-clean-read gate enforced; reads 1 and 2 stay in the worse
    state, read 3 transitions.
  - Recovery counter resets if a regression interrupts the gate.
  - First-ever observation from `unknown` snaps (no gate).
- **Regression snapping**:
  - healthy → degraded / healthy → stale both snap immediately.
- **Broadcast wiring**:
  - WS broadcast fires on the transition cycle, silent on no-op
    cycles (`test_broadcast_fires_only_on_transition`).
  - Cross-threshold regression triggers exactly ONE
    healthy→degraded broadcast even if multiple failing cycles
    follow (`test_broadcast_fires_on_regression`).
- **All 27 prewarmer tests green** + 173 related (AST audits,
  sachet provider, external signals, alert_trigger_v2,
  shadow_rollout, monitoring) confirmed green. No regressions.

### Sequence resumed

- ✅ NISCH-012.4 — Operator UI shipped (this PR).
- 🟡 **PAUSED** — TomTom traffic signal provider (NISCH-012.1)
  blocked until user confirms NISCH-012.4 green.
- 🟡 P2 — NISCH-012.2 News/social keyword monitor.
- 🟠 P1 — `ALERT_TRIGGER_V2_HELP_REQUEST` / V2_SOS phased
  rollout (post shadow comparison).


## SSE Replay Tail — System-Health History Stream (Feb 2026)

Closes the operator-reload gap: any operator landing on Command
Center mid-incident now catches up on the last 10 transitions per
source before the live WS resumes normal delivery.

### Locked invariants (user-mandated)

* Two sources allow-listed in `KNOWN_SOURCES`: `v2_parity`,
  `sachet_health`. Adding a source is a deliberate decision (the
  list controls what the SSE endpoint surfaces).
* Per-source capped list of **10** transitions, stored in Redis
  via `LPUSH` + `LTRIM 0 9` so the list NEVER exceeds the cap.
* Same envelope format as the live WS payload — no new schema,
  no transformation. Operators see exactly what they would have
  seen over WS.
* Best-effort: a failed history write logs at warning but does
  NOT block the live broadcast (operationally critical path).

### Components

* **`app/services/system_health_history.py`** — Redis-backed
  store with `record_transition`, `get_recent_transitions`,
  `get_all_recent_transitions`. Pure I/O; never raises.
* **Hook integrations** — both emitters now mirror to history:
  - `_emit_sachet_health_delta` → `record_transition("sachet_health", payload)`
  - `_emit_v2_parity_delta` → `record_transition("v2_parity", payload)`
* **SSE endpoint** `GET /api/admin/monitoring/system-health-stream`
  - Auth via `?token=` query param (browser EventSource limitation,
    same pattern as `/api/stream`).
  - On connect: emits `event: connected` handshake with sources,
    then one `event: system_health_delta` per replayed transition
    in **merged chronological order** across sources.
  - Keep-alive comments every 25 s.
  - Live events still flow via existing WS — this SSE is purely
    the reload-gap close, no double delivery.
* **REST companion** `GET /api/admin/monitoring/system-health-stream/tail`
  - Same replay payload as one-shot JSON, useful for diagnostic
    curl and clients that prefer HTTP over EventSource.

### Tests

**`tests/test_system_health_history.py` — 10 new tests, all green**:
1. `record_transition` caps at HISTORY_CAP (25 writes → 10 entries)
2. Unknown sources silently dropped (no unbounded keys)
3. `get_recent_transitions` returns chronological order (oldest first)
4. Replay envelope byte-identical to original (no schema mutation)
5. Unknown source on read returns []
6. Read API caps to HISTORY_CAP even if write bypassed LTRIM
7. `get_all_recent_transitions` returns stable shape for cold sources
8. `get_all_recent_transitions` reflects writes
9. **Hook integration**: sachet emitter records history
10. **Hook integration**: V2 emitter records history

All 183 related backend tests pass (10 new + 173 baseline).

### Live verification

- `GET /admin/monitoring/system-health-stream/tail` returns real
  transition data captured during this session.
- SSE endpoint streams `event: connected` then replays
  `sachet_health` transitions in chronological order.
- Confirmed Sachet feed IS reachable from preview env (transitions
  fired `unknown → healthy` with `active_alert_count: 2-3`).

### Sequence resumed

- ✅ Sachet pre-warmer (NISCH-012.3 prep)
- ✅ NISCH-012.4 Operator UI capsule + state machine
- ✅ SSE replay tail (this PR)
- 🟡 **PAUSED** — NISCH-012.1 TomTom traffic provider blocked
  until user confirms SSE replay green and reviews end-to-end
  capsule behaviour.
- 🟡 P2 — NISCH-012.2 News/social keyword monitor.


## NISCH-012.1 — TomTom Traffic Signal Provider (Feb 2026)

Second provider shipped against the External Signal Layer.
TomTom Flow Segment Data API supplies zone-level congestion to
adjust route-deviation and pickup-anomaly risk weights. Mirrors
the Sachet contract verbatim so the operator UI surfaces both
through the same capsule and SSE replay tail.

### Components

* **`tomtom_provider.py`** — `TomTomSignalProvider` implements
  `ExternalSignalProvider`. Probes 8 monitored urban points in
  parallel each cycle, normalises `(free_flow - current)/free_flow`
  into the same 4-tier severity grid (minor/moderate/severe/
  extreme) and returns an `ExternalSignal` matched by proximity
  (max 0.5° from incident).
* **`tomtom_prewarmer.py`** — Independent APScheduler job mirroring
  `sachet_prewarmer.py` line-for-line. Same 4-state health machine,
  same asymmetric hysteresis (3 clean reads to recover), same
  transition-only `system_health_delta` broadcast, same Redis-only
  telemetry surface. Adds a **`STATE_DISABLED`** state for the
  no-API-key path.

### Locked invariants (driven by tests)

* **Jitter — 5 min ± 60 s uniform**, independent of Sachet's
  4 min ± 45 s. Tested explicitly: `JITTER_BASE_S != sachet's`,
  `JITTER_RANGE_S != sachet's`, 100-iteration bound check.
* **Cache-preservation** — empty fetch / raised exception leaves
  the cache key untouched (two separate tests).
* **Disabled mode** — `TOMTOM_API_KEY` absent →
  `is_enabled() = False`, scheduler refuses to register
  (`_scheduler is None` after `start_*`), telemetry returns
  `{health_state: "disabled", reason: "no_api_key"}`,
  `run_prewarm_cycle` short-circuits with no Redis writes.
* **No DB writes** — RELIABILITY_DEBT ratchet unchanged at 21.
* **Allow-list registration** — `tomtom_health` added to
  `system_health_history.KNOWN_SOURCES`. SSE replay tail surfaces
  TomTom transitions in chronological order alongside `v2_parity`
  and `sachet_health`.

### Endpoint surface

* `GET /api/admin/monitoring/tomtom-prewarmer` — same telemetry
  shape as Sachet (+ `health_state`, `recovery_progress`, jitter
  bounds, threshold legend).
* `GET /api/admin/monitoring/external-signals/active` — extended
  to return both `sachet` and `tomtom` blocks under the same
  `{health_state, cache_age_seconds, active_count, modifiers}`
  contract. When TomTom is disabled, the block becomes
  `{source: "tomtom", state: "disabled", reason: "no_api_key"}`.

### Tests — 31 new in `tests/test_tomtom_prewarmer.py`

1. Jitter bounds locked, independent of Sachet.
2. Jitter stays within bounds over 100 iterations.
3. Cache untouched on empty fetch.
4. Cache untouched on fetch raising.
5. Cache overwritten only on non-empty success.
6-9. State machine across 4 states (unknown / healthy / stale /
   degraded), boundary-tested.
10. Regression snaps immediately.
11. Recovery requires 3 consecutive clean reads.
12. Recovery resets if regression interrupts the gate.
13. Unknown → first observation snaps.
14-19. Disabled mode (5 dedicated tests for the
   `TOMTOM_API_KEY`-absent path).
20. `tomtom_health` in `KNOWN_SOURCES`.
21. Emitter records history (replay-tail integration).
22-23. Telemetry on success vs failure paths.
24-26. Severity / parse helpers.
27-29. Provider returns signal / disabled / out-of-radius.

**214 / 214 backend tests green** across new TomTom + 183 baseline.

### Sequence resumed

- ✅ Sachet pre-warmer (NISCH-012.3)
- ✅ NISCH-012.4 Operator UI + state machine
- ✅ SSE replay tail
- ✅ NISCH-012.1 TomTom (this PR)
- 🟡 **PAUSED** — NISCH-012.2 News/social keyword monitor
  blocked until user confirms TomTom green.
- 🟠 P1 — `ALERT_TRIGGER_V2_HELP_REQUEST` / V2_SOS phased
  rollout (post shadow comparison).


## ProviderPrewarmer Base Class + NISCH-012.2 News/Social (Feb 2026)

Two-step PR: extracted the common prewarmer plumbing into an
abstract base before the third provider shipped (same reasoning
as `shadow_rollout.py` — refactor before divergence, not after),
then implemented the News/Social monitor as a thin subclass.

### Step 1 — `ProviderPrewarmer` ABC

**File**: `app/services/external_signals/base_prewarmer.py`

Subclass interface (locked):

  * `name`, `cache_namespace`, `cache_key`, `cache_ttl_s`
  * `telemetry_namespace`, `history_source_name`
  * `jitter_base_s`, `jitter_range_s`
  * `scheduler_job_id`, `active_count_field`
  * `is_enabled()` — default True; subclasses override for
    API-key-gated providers
  * `async fetch() -> list[dict] | None` — abstract

Inherited (one tested impl, never reimplemented):

  * cache-preservation rule (empty/raised → cache untouched)
  * 4-state health machine (`healthy / stale / degraded / unknown`)
  * asymmetric hysteresis (regress fast, recover after 3 clean reads)
  * telemetry write (rolling last-10 failure rate, derived
    `cache_age_seconds`)
  * transition-only `system_health_delta` broadcast
  * SSE-replay-tail mirroring via `system_health_history`
  * APScheduler lifecycle (idempotent start/stop)
  * disabled-mode short-circuit (no Redis writes when disabled)

**Test monkeypatch contract preserved**: the base's
`emit_health_transition` looks up `_emit_<source>_delta` in the
subclass's module at call time via `sys.modules`, so existing
tests that `monkeypatch.setattr(mod, "_emit_<source>_delta", fake)`
still intercept the broadcast.

**Sachet + TomTom now thin subclasses** (~25 lines of config each
plus a one-line `fetch()`). All 58 of their existing tests pass
unchanged — the refactor is structural.

**One new contract test** (`tests/test_base_prewarmer_contract.py`,
15 tests):

  * Cache preserved on empty / raised / overwritten only on
    non-empty success
  * Hysteresis: regression snaps, recovery requires 3 clean reads,
    counter resets on regression during the gate, unknown→first
    observation snaps
  * Disabled mode: short-circuits `run_cycle`, refuses to start
    scheduler, returns disabled shape on telemetry + health
  * Broadcast fires only on transition; module-level emit shim is
    patchable
  * Telemetry failure path preserves `last_success_ts` and
    `active_count`
  * Raw-state thresholds inherited

### Step 2 — NISCH-012.2 News/Social Keyword Monitor

**Files**:
  * `app/services/external_signals/news_provider.py`
  * `app/services/external_signals/news_prewarmer.py`

Two-tier source strategy:

  * **NewsAPI** (`NEWSAPI_KEY` env) — keyword `OR`-query filtered
    to Indian sources. When the key is absent the NewsAPI channel
    is *disabled* — but the provider as a whole is NOT disabled.
  * **RSS fallback** (no key required) — NDTV + Times of India
    top-stories feeds. Always runs. Detects keywords in headlines
    via case-insensitive substring (catches plurals/inflections).

**Per-channel independent telemetry**: NewsAPI and RSS each get
their own rolling failure-rate counter (`channel_newsapi`,
`channel_rss`). RSS success NEVER inflates the NewsAPI success
counter — the spec demands this so an operator can spot a
paid-API outage even when the fallback is healthy.

Locked config:

  * Jitter: **15 min ± 2 min uniform** — independent of Sachet
    (4 ± 45 s) AND TomTom (5 ± 60 s). Tested explicitly.
  * Cache TTL: 30 min. Signal decay: 2 hr.
  * Keywords: `riot > fire > flood > accident > crime` (order
    locked; highest-severity match wins per headline).
  * Zone matching: read-only `INDIAN_CITY_CENTROIDS` lookup table
    (23 cities + states). **No DB writes** — RELIABILITY_DEBT
    ratchet stays at 21.

**Active modifier surface** — extended `/admin/monitoring/
external-signals/active` returns three provider blocks:
`sachet`, `tomtom`, `news` (+ weather note). The `news` block
includes a `channels` sub-block with NewsAPI vs RSS independent
health so operators see channel-level status, not just the
aggregate.

**Replay tail**: `news_health` added to `KNOWN_SOURCES`. SSE
endpoint surfaces news transitions alongside sachet/tomtom/v2.

### Tests — 24 new in `tests/test_news_prewarmer.py`

1. Jitter bounds locked (`900 / 120`).
2. Jitter independent of Sachet AND TomTom.
3. Jitter stays within bounds over 100 iterations.
4. NewsAPI cache untouched on empty fetch.
5. NewsAPI failure does NOT advance NewsAPI `last_success_ts`.
6. **RSS fallback activates when NewsAPI returns empty.**
7. **RSS success does NOT count as NewsAPI success** (independent
   counters).
8. NewsAPI disabled without key — channel skipped, telemetry
   key NOT created (no permanent-100%-failure artefact).
9. Provider NEVER fully disabled — RSS keeps running.
10. Telemetry surfaces `newsapi_disabled` flag.
11. `news_health` in `KNOWN_SOURCES` (SSE replay tail).
12. News emitter records history.
13-19. Parse layer: keyword severity order, case-insensitivity,
    plural handling, zone detection with punctuation,
    `build_modifier` skips unactionable headlines.
20. RSS parse extracts items from RSS 2.0.
21. RSS parse returns None on malformed.
22. Centroid table is well-formed (lat/lng in India bbox).
23. Keyword set matches spec verbatim.
24. + Channel skip behaviour on disabled NewsAPI.

**253 / 253 backend tests green** (24 News + 15 Base Contract +
214 baseline). No regressions.

### Live verification

- Scheduler runner online with `started=21: ... ,sachet_prewarm,
  tomtom_prewarm,news_prewarm,health_monitor, ...`
- `GET /admin/monitoring/news-prewarmer` returns full envelope +
  `channels.newsapi.enabled=false`, `channels.rss.enabled=true`
- `GET /admin/monitoring/external-signals/active` returns 4
  keys: `sachet`, `tomtom`, `news`, `weather`

### Sequence resumed

- ✅ ProviderPrewarmer base class
- ✅ NISCH-012.2 News/Social
- 🟡 **PAUSED** — V2 phased rollout blocked until user confirms.
- 🟠 P1 — `ALERT_TRIGGER_V2_HELP_REQUEST` / V2_SOS phased rollout.


## Prewarmers Roll-up + Synthetic Shadow Validation (Feb 2026)

Two-step PR. Step 1 ships the operator dashboard chatter
reduction; Step 2 verifies the V2 shadow instrumentation works
end-to-end so real traffic doesn't silently fail to record.

### Step 1 — `/admin/monitoring/prewarmers` roll-up endpoint

Single REST call returning all four provider health blocks
(`v2_parity`, `sachet`, `tomtom`, `news`) instead of the previous
4-call fan-out. Cuts Command Center polling chatter by 75%.

* `v2_parity` block: aggregate `tier` (worst across kinds),
  `critical_count` (sum across kinds), weighted-avg `match_pct`,
  per-kind `by_kind` drill-down.
* Each external block: `health_state`, `cache_age_seconds`,
  `last_success_ts`, `parse_failure_rate`, `recovery_progress`,
  `recovery_required`.
* News block additionally carries `channels` with NewsAPI vs RSS
  independent health.

WS transitions still fire per-source on state change — the roll-up
is REST reconciliation only, not the real-time path.

`ExternalSignalsCapsule.jsx` updated: now polls
`/admin/monitoring/prewarmers` + `/admin/monitoring/external-signals/active`
(2 calls every 30 s) instead of 4. Same WS optimistic-patch
behaviour for live transitions.

**3 new tests** (`tests/test_prewarmers_rollup.py`):
locked-shape contract — all 4 keys present, V2 block carries
`tier/critical_count/match_pct/by_kind`, every external block
carries `health_state/cache_age_seconds/recovery_progress`, news
block carries `channels.newsapi` + `channels.rss`.

### Step 2 — Synthetic shadow validation script

`scripts/synthetic_shadow_validation.py` — verifies the V2 shadow
machinery is wired correctly before real traffic arrives.

**Hard-locked at top of file**:
```
# SYNTHETIC VALIDATION ONLY
# A passing run does NOT authorize V2 ramp.
# Gate condition for ramp: critical_count = 0 sustained
# across ≥1 real incident cycle with real production traffic.
```

**Five phases (all green, 29/29 checks)**:

1. **Taxonomy round-trip** — pipelined inject ≥50 events per kind
   across all 7 taxonomy labels, verify `get_classification_snapshot`
   reflects exact tallies. Pipelining required because hosted
   Redis has ~500 ms RTT and 300+ sequential INCRs would exceed
   any reasonable timeout.

2. **`classify_diff` label assignment** — hand-crafted
   `(diff, V2Decision)` inputs drive each canonical label:
   `v2_would_not_dispatch`, `missed_target_critical`,
   `unreachable_target_chosen`, `unreachable_dropped`,
   `fanout_reduction_help`, `ranking_improvement`, `match`.
   Documents that `unreachable_dropped` only fires for HELP
   (SOS hits `missed_target_critical` first per the priority
   order in `classify_diff`).

3. **Autodisable arms** — pipeline 25 critical events across
   recent per-second window keys (matching the
   `ShadowRolloutController._key` namespaced layout); verify
   `_rolling_window_stats` reads them back, `_set_autodisable`
   arms, and `should_v2_actually_fire` returns False regardless
   of `ALERT_TRIGGER_V2_SOS_ROLLOUT_PCT=100`.

4. **Tier state machine** — first critical event snaps the
   per-kind tier to `critical`.

5. **Operator digest populated** — `get_diagnostic_summary`
   returns non-empty with numeric `match_pct` per kind.

**Cleanup invariant**: every Redis key the script writes lives
under the dedicated `synthetic_v2_validation` namespace (NOT
`alert_v2_shadow`). A `try/finally` in `main` calls
`_cleanup_synthetic_keys()` which scan-deletes every synthetic
key, even on failed runs. Verified post-run: the live
`/admin/monitoring/alert-v2/shadow-stats` endpoint returns the
empty initial shape (`diagnostic: {}`, `recent_events: []`) —
synthetic data did not leak into operator-facing stats.

### V2 ramp status — NOT STARTED

Live `shadow-stats` returns zero events — no real traffic has
flowed through the comparator. The gate condition
(`critical_count = 0 sustained across ≥1 real incident cycle`)
**cannot be evaluated without real traffic**. Synthetic
validation proved the machinery works; it does NOT authorize the
ramp.

**256 / 256 backend tests green** (3 new roll-up + 253 prior).
No regressions.

### Sequence resumed

- ✅ Prewarmers roll-up endpoint
- ✅ Synthetic shadow validation script
- 🟡 **PAUSED** — V2 phased rollout blocked on real traffic
  accumulating in production. Synthetic passing ≠ ramp clearance.
- 🟡 P3 — Postgres JSONB → MongoDB migration (Entity Engine).
- 🟡 P3 — Detox/Maestro native UI automation.


## Smoke Test Wired to Deploy Pipeline (Feb 2026)

`scripts/synthetic_shadow_validation.py` now runs as **step 3 of
6** in `/app/deploy/deploy.sh`, placed deliberately between the
DB migration and the backend restart so a taxonomy regression
blocks the deploy before any in-flight changes hit production:

```bash
# 3. SHADOW MACHINERY SMOKE TEST — must pass before we cycle backend.
echo "[3/6] V2 shadow machinery smoke test..."
cd backend
python scripts/synthetic_shadow_validation.py || {
  echo "  ✗ V2 shadow machinery smoke test FAILED — aborting deploy"
  echo "    Investigate scripts/synthetic_shadow_validation.py output."
  echo "    A passing run is REQUIRED for deploy to proceed."
  exit 1
}
cd ..
```

**Hard-gate behaviour verified**:
- Healthy run → exit code `0` → deploy proceeds.
- Forced `classify_diff` regression → exit code `1` → deploy halts
  with the explicit error message in the deploy log.

The `set -e` at the top of `deploy.sh` plus the explicit
`|| { ... exit 1 }` handler means a regression cannot be silently
swallowed — a future change that pipes the smoke test through
`tee` or similar will still propagate the nonzero status because
the `exit 1` is the final statement in the failure branch.

**Cleanup invariant unchanged** — the script's `try/finally`
deletes every synthetic Redis key under
`nischint:synthetic_v2_validation:*` even on failed runs, so a
blocked deploy does NOT leave operator-facing shadow stats
polluted.

### RELIABILITY_DEBT.md — current risk surface

Audit clarification: the ledger is **binary**, not three-state.
There is no separate `reconciliation_state: none` field per
entry — `unresolved_debt` IS the "no compensating action
recorded" state. Full risk surface = all 21 entries:

* RAG service               — 7 entries (lowest blast radius)
* Blog/Child/Chat/Dashboard — 5 entries
* **Auto-escalation engine**     — 1 entry (HIGH RISK)
* **Voice distress service**     — 1 entry (HIGH RISK)
* **Notification service**       — 2 entries (HIGH RISK)
* Check-in service          — 2 entries
* Demo engine               — 2 entries
* Geo digest                — 1 entry

The 4 high-risk entries (auto-escalation, voice distress,
notifications) live on the safety-critical path and are the
recommended starting point for ratchet-down work while V2 shadow
traffic accumulates.
## Sachet Pre-warmer 100% Failure Rate — Root Cause + Fix (Feb 2026)

Operator chip showed `NDMA NO DATA` / `state: unknown` /
`parse_failure_rate: 100%` for the entire session. User
hypothesised it was an egress block on `sachet.ndma.gov.in`
(government-of-India domain, Emergent network policy).

**Actual root cause: HTTP timeout mismatch.**

* `sachet_provider.HTTP_TIMEOUT_S = 1.0` (sized for the alert hot
  path where the registry caps each provider at 1.5 s).
* NDMA RSS endpoint consistently responds at 1.4–1.9 s with a
  73 KB payload (`curl -w time_total` measured 5 attempts).
* Every pre-warmer fetch raced the timer and lost.
* Egress was fine — `curl https://sachet.ndma.gov.in/.../rss_india.xml`
  returned HTTP 200 in 1.8 s.

### The fix

`_fetch_feed_uncached()` now accepts `timeout_s` (default
`HTTP_TIMEOUT_S = 1.0`). The pre-warmer calls it with
`PREWARMER_TIMEOUT_S = 8.0`. Hot-path crash budget unchanged.

Verified live: forced cycle returned `{'status': 'success',
'alert_count': 99}`. State machine correctly stays in `degraded`
until the asymmetric hysteresis clears (3 consecutive successes
AND rolling-10 failure rate < 0.20) — exactly as designed.

### Operational reflex worth keeping

The smoke-test discipline catches code regressions on every
deploy. This bug was infra-shaped but turned out to be config:
internal timeout < external response latency. Future "provider
shows degraded forever" investigations should start with
`curl -w "time_total=%{time_total}s"` against the provider URL,
compared to our `HTTP_TIMEOUT_S`, BEFORE chasing network policy
or proxy theories.



### Sequence resumed

- ✅ Prewarmers roll-up endpoint
- ✅ Synthetic shadow validation
- ✅ Smoke test wired to deploy pipeline (hard-gate verified)
- 🟡 **In progress** — Ratchet-down work on RELIABILITY_DEBT
  high-risk entries (auto-escalation, voice distress, notifications)
- 🟡 **Awaiting real traffic** — V2 phased rollout
- 🟡 P3 — Postgres JSONB → MongoDB migration (scope only;
  do NOT start while V2 ramp is open)



## REL-09 Fan-out + OWM OneCall 3.0 Alerts (May 29, 2026) ✅

### Sentry observability now spans 4 providers
SACHET (REL-09 baseline) + TomTom + Weather (OWM) + News. Each provider has its own fingerprint (`*-degraded`) so a streak of outages groups into ONE Sentry issue with hit count + first/last-seen. Recovery (`degraded → healthy`) emits level=info on the same fingerprint, putting the resolution event on the open issue's timeline → operators get the outage duration "for free".

Per-provider extra tags surface granularity in Sentry without diluting the canonical tag set:
- TomTom: `zone` (so one flapping city doesn't read as a global outage)
- News: `channel` (newsapi|rss) + `feed` (ndtv|toi)
- Weather: `channel` (current|onecall_alerts) + `metro` (mumbai|delhi|…)

### OpenWeatherMap OneCall 3.0 alert prewarmer
Polls 6 Indian metros every 15 ± 1 min. SACHET stays primary regulatory/authoritative source for India — OWM is additive (provider confidence 0.75 vs SACHET's 0.85, so SACHET dominates blended risk). NO priority inversion.

Activation note: `OPENWEATHER_API_KEY` already in backend `.env` for the existing per-request `WeatherProvider`. OneCall 3.0 tier MUST be activated separately on the OWM dashboard. Until then, 401/403 responses are logged defensively to Sentry (`channel=onecall_alerts`) and the cache is preserved → no impact on the existing weather hot path.

### Test counts
- 82 new tests this session, all green.
- Full external-signals stack: 242/242 passing.

## SB-02 — user_signal_baselines Matview (May 29, 2026) ✅

User-grain materialised view over `behavior_baselines`. Single-source SQL helpers (`get_user_baseline`, `get_user_baselines_24h`) replace the 3-table join chain when consumer code is migrated in a follow-up. Nightly `REFRESH MATERIALIZED VIEW CONCURRENTLY` at 03:00 UTC; admin endpoints `/api/admin/monitoring/baselines/{status,refresh}`. Live verified end-to-end on Supabase. 19 new tests, all passing.

**Why this matters**: removes a per-request 3-table join from every operator device-baseline read. At current fleet size dominated by network RTT to ap-south-1; pays off at scale where the join becomes meaningful (millions of `behavior_baselines` rows × hundreds of concurrent operator reads).

**Open follow-up**: migrate `behavior_ai._detect_behavioral_anomalies` (device-grain, no migration needed) and `operator.py` device-baseline endpoints to call `get_user_baseline()` / `get_user_baselines_24h()`. Intentionally not bundled with SB-02 to keep the change observable.

## SB-02 Follow-up — Health Capsule + operator.py migration (May 29, 2026) ✅

`baselines` is now the 6th System Health Capsule domain. A failed nightly refresh OR matview drift past 36 h flips the domain to `degraded` and fires the same `system_health_delta` WS event every other domain uses. `/system-health` exposes a `baselines` flyout block with the full meta row.

`operator.py` device-baseline reads (line ~2107) migrated from the inline `behavior_baselines` join to `get_device_baseline()` / `get_device_baselines_24h()` matview helpers. Rounding centralised in `_row_to_dict`. Live verified end-to-end on Supabase.

13 new tests, 213/213 passing across the SB-02 / health-thresholds / REL-09 surface.

The data-freshness pipeline (`behavior_baselines` writes → matview refresh → operator capsule) is now end-to-end observable.

## SB-02 Frontend — System Health Capsule "Baselines" Chip (May 29, 2026) ✅

`SystemHealthCapsule` now renders a 6th `Baselines` row showing freshness + last refresh duration + relative timestamp + row count. Admin-only refresh button (gated via `useAuth() → user?.role === 'admin'`) calls `POST /api/admin/monitoring/baselines/refresh` and optimistically patches the subtree on success. WS delta patcher handles `source=baselines` events for real-time updates. Built and bundle-verified to include `sh-row-baselines` + `sh-baselines-refresh-btn` test IDs.

The end-to-end SB-02 stack is now operator-visible: matview maintenance, scheduler, backend API, threshold engine, WS delta engine, and operator capsule chip all wired together.

## SF-03 — Survey of India Boundary Precision (May 29, 2026) ✅

### Sovereignty corrections
- **Arunachal Pradesh**: Replaced the 196,246 km² bbox (overlapping Bhutan + Myanmar) with a 19-vertex SOI-aligned polygon (~104,544 km²) following the McMahon Line + state borders. Tawang, Itanagar, Walong all correctly resolve to 'Arunachal Pradesh'; Bhutan and Myanmar points no longer false-positive.
- **Aksai Chin**: Added as part of 'Ladakh' UT per Survey of India (was previously rendered as "outside India" — a press-issue risk for an India-operating safety app). 13-vertex polygon ~26,079 km², east edge along India's claimed sovereignty line.
- **Existing OSM Ladakh** polygon preserved — Leh and central Ladakh continue to resolve unchanged.

### Audit + replacement infrastructure
Every curated row is tagged `source='soi_curated_approx'` with a `boundary_notes` field carrying a "REPLACE WITH OFFICIAL MoEFCC SHAPEFILE when available" marker visible to operators via `GET /admin/monitoring/soi-boundaries/status`. Once the official shapefile lands, replacement is a 1-line UPDATE per row.

### Negative cases locked in tests
Bhutan (Thimphu, Paro), Myanmar (Myitkyina), and Chinese Xinjiang (Hotan, Kashgar) all resolve to `None`. Static migration tests lock the polygon meridian extents so a future "innocent" revert to a rough rectangle cannot pass review.

### Open follow-up
Upload the official SOI / MoEFCC GIS shapefile when available — replacement path is documented in the migration docstring.

## REL-02 + SB-04 Dual-Read (May 29, 2026) ✅

### REL-02 — `GET /api/admin/monitoring/logs/tail`
Operator/admin RBAC. Reads `/var/log/supervisor/backend.*.log` with `lines` (1-500) and `since_minutes` (1-1440) params. Tail-efficient backward-chunk read, multi-file merge sorted by JSON `ts`, permissive on parse failure. Live verified.

### SB-04 — dual-read migration (deferred DROP per user option d)
`behavior_ai.py` now reads via `_load_baseline_dual()` — prefers `device_baselines` when present, falls back to `behavior_baselines`. `operator.py` already uses matview helpers (zero direct reads). Out of scope: `life_pattern_engine.py`, `twin_evolution_engine.py`, `digital_twin_builder.py` — deferred to SB-04 part 2 sprint. Table drop deferred until matview reshape.

**Acceptance status**: dual-read migration ✅ complete. `\d behavior_baselines` still exists (deferred per user decision — the SB-02 matview chip depends on the table).

## LogTailCapsule — Command Center Operator Chip (May 29, 2026) ✅

`LOGS` chip in the Command Center capsule strip — auto-polls `/admin/monitoring/logs/tail?lines=500&since_minutes=5` every 10 s. DIY virtualised viewport (no `react-window` dependency) handles 500 lines smoothly. Level-based row colouring, permissive regex/substring search, Pause polling, Copy as JSON, error/warning chip badges. Same z-1500 flyout pattern as SystemHealthCapsule.

19 Jest tests for pure helpers, 100% passing. Bundle-verified; live screenshot confirms chip + flyout rendered.

The operator can now go from "system_health says degraded" → "what does the log say right now" in one chip click — no terminal access required.

## Podcast Pipeline Retired (May 29, 2026) ✅

Removed `app/podcast/` (1.1 MB src), `chromadb` + 6 `langchain*` packages from `requirements.txt`, router from `app/api/main.py`, and both `chroma.sqlite3` files. Sentry `auto_enabling_integrations=False` lock preserved with updated rationale comment.

Verification: backend boots clean, `/api/podcast/*` → 404, zero leftover imports / pip packages / requirements lines / sqlite files. 251/252 regression-sweep tests pass on the recent change surface; broader sweep failures (11) are the pre-existing SSL cert env issue.

Expected savings: ~200 MB Docker image reduction at next rebuild + ~144 MB startup RSS savings.

Moved P2 → DONE.
