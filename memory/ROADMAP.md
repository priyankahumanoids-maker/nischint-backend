# NISCHINT Roadmap

## 🎯 Next Session Priorities (locked 2026-02, updated late-session)

### P0 — DPDP compliance surfaces (status)
- [x] **`GET /api/privacy/me`** right-of-access export (JSON + PDF) — landed 2026-05-24.
- [x] **Settings → Privacy → "Download my data"** button — landed 2026-05-24 at `/m/privacy`, reachable via Profile → "Privacy & My Data". PDF + JSON downloads work end-to-end.
- [ ] **Mobile (Expo) Privacy screen** — mirror the web `/m/privacy` UI in React-Native. Re-use the same backend.
- [ ] **NISCH-009 self-serve erasure** — currently routes users to `privacy@nischint.care`. Build admin-side workflow + soft-delete in `users` / cascade to `seniors`.
- [ ] **Hindi-localised PDF variant** for the export (optional).

### P0 — HC-01 Health Connect wearables (status)
- [x] **Day 1** — `react-native-health-connect@3.5.3` + Android manifest/permissions + iOS HealthKit entitlements. (2026-05-24)
- [x] **Day 2** — `healthConnectService`, `wearableSyncTask`, `POST /api/health-signals/wearable` with range + ISO validation. (2026-05-24)
- [x] **Day 3** — `evaluate_risk` brain hook wired (FALL_DETECTED → fall=1.0; HR_HIGH/SPO2_LOW → voice channel), `WearableConnectCard`, `VitalsStrip`, startup BackgroundFetch registration, stub `/health-history` route. (2026-05-24)
- [x] **Day 4** — `DependentVitalsCard` on the guardian dashboard, `GET /api/health-signals/dependent/{id}/latest` guarded by `_resolve_guardian_ids`, 7-test backend pytest E2E, 7-test mobile fallback `node --test`. (2026-05-24)
- [ ] **HC-02** — Real `/health-history` charts (7-day HR + SpO₂ trends + anomaly flag).
- [ ] **HC-03** — iOS HealthKit native bridge (`react-native-health-connect` is Android-only).

### P0 — SF-02 PostGIS hazard matching (status)
- [x] **Closed 2026-05-24** — Production verification passed: p99 = 0.057 ms (gate 50 ms), composite = 0.793 on himalaya scenario via PostGIS Uttarakhand polygon.
- [ ] **SF-03** — Precise Survey of India (SOI) boundary for Arunachal Pradesh (replaces the 196 k km² bbox approximation).

### P0 — SB-01 Safety Brain Hermes learning loop (status)
- [x] **Day 1 (2026-05-25)** — Path A + D data-capture layer landed.
  - `GET /api/admin/sb01/status` + `GET /api/admin/sb01/user-baseline/{uid}` (operator-gated)
  - `POST /api/safety-events/{id}/feedback` (auth-gated to event-owner / guardian / operator)
  - `safety_event_feedback` table + 3 indexes (incl. UNIQUE on (event, source))
  - 12-test pytest pure-HTTP suite, all passing
- [x] **Day 2 (2026-05-25)** — Hermes weight attenuator wired into `compute_risk_score` + `evaluate_risk`. **Himalaya invariant preserved** (composite ≥ 0.793 on new-user path). 43/43 regression tests green (12 SF-01 FP + 12 SB-01 hermes + 12 SB-01 attenuator + 7 HC-01).
- [x] **Day 3 (2026-05-25)** — Operator Confidence Engine UI + guardian feedback bottom sheet + `GET /api/admin/sb01/attenuation-summary` + AIL-01 architecture doc. SB-01 sprint **CLOSED**.
- [ ] **SB-04 hygiene (carry-over)** — Audit the 7 `behavior_baselines` SELECT/INSERT/UPDATE call-sites in `behavior_ai.py` + `operator.py`. Either migrate them to `device_baselines` or confirm unreachable, THEN drop the orphan table. Day 1 report incorrectly flagged it as dead code; it's not.
- [ ] **SB-02** — Materialised `user_signal_baselines` view for 30-day rolling FP rates so the per-request DB hit doesn't scale linearly with feedback growth.

### P0 — Validate the async migration before declaring 520 fixed
- [ ] **Redeploy preview → production** so the async RAG migration
  reaches `nischint.care`. The 520 fix is code-side complete but
  not active in production until redeploy.
- [ ] **Load-test `/api/rag/generate`** with `wrk` / `autocannon` /
  `k6` at three rungs: 10, 25, 50 concurrent. Acceptance criteria:
    - WebSocket heartbeat stable on `/ws/command-center`
    - SSE keepalive ping interval unchanged on `/api/stream/*`,
      `/api/journey-sync/*`, `/api/monitoring/system-health-stream`
    - p95 of unrelated endpoints (`/api/dashboard/*`, `/api/operator/*`)
      stable
    - No `dlq_replay_raised` / `dlq_cycle_error` spike in scheduler logs
    - `RAG_GENERATION_SEMAPHORE` saturation visible via a future
      operator chip (next-sprint task — flag this if it surfaces)
- [ ] If 520 persists after redeploy with green load-test, escalate
  to **Emergent Support** for CF SSL-mode / DNS / edge-timeout
  config review (origin issue, not code issue).

### P0 — Next-sprint hardening for RAG generation
- [ ] **Request-correlation IDs** — propagate `request_id` /
  `generation_id` / `trace_id` through the generation pipeline.
  Log latency, token count, timeout source, model, retries with
  every event.
- [ ] **Latency histograms** — per-endpoint p50/p95/p99 emitted to
  the same telemetry surface as the `ProviderPrewarmer` budget
  exporter. Operator chip surfaces the histogram alongside the
  existing prewarmer chips.
- [ ] **Queue-backed generation fallback** — on `asyncio.TimeoutError`
  the FastAPI endpoint currently returns 503-deferred. Upgrade to:
  LPUSH the request payload to a new `dlq:rag_generation_retry`
  bounded queue; reconciler re-runs against the next available
  semaphore slot. Aligns with the DLQ architecture's
  "compensating action exists" rule.
- [ ] **Operator chip for semaphore saturation** — surface
  `RAG_GENERATION_SEMAPHORE` in-flight count + wait-queue depth in
  the Command Center capsule strip. Amber at 80 % saturation, red
  at 100 %. Same pattern as prewarmer budget warnings.

### P0 — Final reliability ratchet (1 → 0)
- [ ] **Delete `app/api/child.py:211`** when V2 ramp completes at
  100 %. This is the last debt entry; the file's legacy
  help-request block dies with the V2 ramp.

### P1 — Phase 2 Sensor AI (after NISCH-012 stabilizes in production)
- [ ] On-device audio classification (distress / scream / glass-break) — runs in the same edge processor as the accel/gyro pipeline, batched feature uploads.
- [ ] Behavioral learning loops on top of `activity_class` distributions — anomalous-class run-length, vehicle/walking transition cadence, etc.
- [ ] Camera-assisted verification (Phase 3 in the user's 6-layer plan) — defer until edge-AI inference budget is measured.

### NISCH-012 — DONE ✅ (May 13, 2026)
Continuous Motion Telemetry Bridge live. Phase 1 of the 6-layer
ambient-intelligence sensor architecture verified end-to-end
(iteration 197: 45/45 tests passing). See CHANGELOG for full
architecture mapping.

### P1 — NISCH-010 / NISCH-011 ML Layer (implementation)

**NISCH-010 status: DONE ✅ (May 13, 2026 — see CHANGELOG)**
**NISCH-011 status: DONE ✅ (May 13, 2026 — see CHANGELOG)**
**NISCH-011.1 Twin Trust Tile: DONE ✅ (May 13, 2026 — backend complete; frontend tile pending)**
**NISCH-011.2 Trust Badge + Real-Time Propagation: DONE ✅ (May 13, 2026 — `GET /api/behavioral/trust/badge` + `trust_level_changed` WS event + 4-field payload incl. `severity_delta`)**
**Frontend Twin Trust Tile: DONE ✅ (May 13, 2026 — mounted in Command Center header beside DLQCapsule; polls every 10s; animated transitions via client-side severity_delta)**

- Behavioural twin tables (`behavioral_baselines` + `behavioral_anomalies`) live
- 5-class locked taxonomy (`baseline | drift | irregular |
  elevated_behavioral_risk | critical_behavioral_shift`)
- 4-tier temporal memory: 5/30-min Redis, 6/24-h Postgres
- Fusion engine: `fused_risk = anomaly × zone × temporal × sensor
  × divergence_weight`; divergence DAMPENS only
- Strict dispatch-influence gate: only `critical_behavioral_shift`
  AND `zone_risk ≥ 0.6` influences dispatch
- DLQ append-only `dlq:ml_predictions` (10k cap) as compensating action
- Prewarmer (1h cadence, 2 s budget) wired in both supervisor modes
- 35 dedicated tests + 352-test full regression all green
- Ratchet held: `unresolved_debt=1`, `compensating_action_exists=40`

**Next up — operationalisation:**
- Phase 1 forecasters (EWMA + Bayesian + Prophet stub) live
- `risk_predictions` ledger active with `prediction_class`,
  `prediction_context_snapshot`, `prediction_pipeline_version`,
  `outcome_resolution_version` columns
- Prewarmer (1h) + reconciler (15-min) wired into both supervisor
  modes
- API endpoints registered (`/api/risk/predict`, `.../forecast`,
  `.../accuracy`, `.../route` 501 stub)
- Alert pipeline integrated with non-blocking guarantee
- 30 dedicated unit tests + 317-test regression green
- Backend testing agent (iteration 194) verified

**Next up — NISCH-011 Behavioral Baseline + Digital Twin (P1):**

**Locked design constraints (see `/app/docs/NISCH_010_011_ML_SCOPING.md`):**

- **Both detectors are `ProviderPrewarmer` subclasses.** LSTM risk
  scoring and Z-score anomaly both fit the "compute on schedule,
  cache result, surface as modifier with health state" shape that
  the base class already encodes. Inheriting gives them hysteresis,
  latency exporter, `budget_warning` amber/red, and the operator
  chip for free. The only thing the subclass implements is `fetch()`
  — runs a model instead of an HTTP call.

- **`dlq:ml_predictions` is a prediction *ledger*, not a retry
  queue.** Stores `(inputs, would-have-predicted output, timestamp)`
  on every inference attempt — successes AND failures. The shape
  diverges from the audit-row DLQs because a silent prediction drop
  during an incident is unrecoverable from a post-mortem
  perspective. Operators need to be able to ask "what would the
  model have said at 14:32:05" even when the inference didn't
  influence dispatch. No 3-strike poison semantics — append-only
  ring-buffer bounded at 10 000 entries (~24 h of predictions
  at expected throughput).

- [ ] **Implementation order:** ledger → behavioural Z-score → LSTM.
- [ ] **NISCH-010 — Predictive risk surface** (LSTM + Prophet). Scoping deliverables:
    - Data inventory: what time-series features exist today in PostgreSQL (GEO history JSONB, behavior_anomalies, safety_incidents) and the minimum window needed for LSTM to converge
    - Decision: train offline (S3 + batch) vs online (sliding window in Redis Streams)
    - SLA: prediction latency target (must be < hot-path budget, so ≤ 200 ms)
    - Shadow-rollout design — same `alert_trigger_v2_shadow` pattern (log what it WOULD have predicted for 1-2 incident cycles before any hot-path wiring)
- [ ] **NISCH-011 — Z-score anomaly detector** (per-user behavioural drift). Scoping deliverables:
    - Rolling window size and storage (Redis sorted set vs Postgres time-bucket)
    - Z-threshold tuning approach — start at |z| ≥ 2.5, treat as evidence not as a fire signal
    - Integration point: feeds into the External Signal Layer as a 5th provider OR as a separate `BehavioralSignalProvider`

### P1 — V2 ramp (still blocked)
- [ ] Watch for **real production-incident traffic** on `nischint.care`. Once an incident clears the `critical_count = 0` gate for ≥ 1 cycle, authorise the 5 % V2 ramp (`ALERT_TRIGGER_V2_HELP_REQUEST` / `V2_SOS` flags). No synthetic shortcuts.

---


## P0 (Critical)
- [x] Guardian Incident Management Frontend (Metrics + Timeline + Acknowledge)
- [x] Command Center Performance (batch endpoint + Redis cache + skeleton)
- [x] Fix behavior_anomalies insert bug
- [x] Live System Monitoring on Status Page
- [x] Twilio SMS Integration
- [x] NISCHINT Signature Voice Notification System
- [x] AI Learning Loop (Feature Store + XGBoost Model + Prediction API + Feedback + Safety Brain integration)
- [x] Step-1 Core Safety UX — Child Home (80% Big Red "HOLD FOR SOS" button, 1s trigger, 3s cancel)
- [ ] Redeploy to production (CORS fix pending)
- [ ] Multi-subdomain SSL provisioning (Emergent Support)

## P1 (Important)
- [ ] Test Mobile App on real device (Expo Go)
- [ ] Build Production APK/IPA (EAS Build)
- [ ] Analytics Integration (GA4 / PostHog)
- [ ] Command Center further optimization (reduce 10s load time)
- [ ] Advisory-to-SOS escalation notification (2nd Sustained Risk Gate fire → "confirmed" signal)
- [ ] Gate bypass for elderly + fall detection (instant SOS)
- [ ] Dashboard Timeline badges ("⏸ Held (gate)" vs "⚡ Sustained → fired")
- [ ] Offline Mesh Mode (BLE/Bridgefy peer-to-peer alerts)
- [ ] Migrate `expo-av` → `expo-audio` (SDK 55 deprecation)

## P2 (Nice to Have)
- [ ] SEO & Open Graph Tags
- [ ] Connect System Status to real CloudWatch/Prometheus
- [ ] E2E Playwright test suite
- [ ] Native App Store submission
- [ ] Multi-tenancy for institutional clients
- [ ] AI Learning Loop (train on historical data)
- [ ] Unified MessagingService (push + email)
