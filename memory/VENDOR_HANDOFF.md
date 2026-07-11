# Nischint — Vendor Handoff, Scope of Work & KRAs

**Document purpose**: everything a qualified software partner needs to take over ongoing development and maintenance. Hand this verbatim to vendor shortlists; combined with a signed NDA it is the complete RFP package for Nischint engineering.

**Document owner**: _TBD_
**Effective date**: _TBD_
**Handoff cut-off commit**: see `git log -1` on `main`

---

## 1. Product Summary

Nischint is a **real-time personal safety & decision-delivery system** covering:
- Guardian tracking (parent ↔ child / elderly caregiver)
- SOS + voice-distress escalation pipeline
- Journey intelligence (planned routes, live polyline, deviation detection)
- Operator Command Center (Risk Panel, SSE push, incident triage)
- Predictive risk foundation (disciplined SSE emitter, dedup, multi-instance safe)
- Adjacent SaaS modules: Blog / Podcast / SEO / Entity Engine / Revenue OS

It is **not** a simple tracking app — the category is "event-driven safety intelligence". Retain that framing when hiring.

---

## 2. System Snapshot (factual, live)

| Layer | Count | Evidence |
|---|---|---|
| **Backend** — FastAPI, Python 3.11 | 85 API modules · 113 services · 42 ORM models · **514 route handlers** · 209 test files · 71,234 LOC | `/app/backend/app/api`, `/services`, `/models`, `/tests` |
| **Frontend (web)** — React + CRA/Webpack + Tailwind + Shadcn | 76 pages · 103 components · 48,836 LOC | `/app/frontend/src/pages`, `/components` |
| **Mobile** — Expo SDK 55, React Native, TypeScript | 12 screens · 21 services · 9 Zustand stores · 14,118 LOC | `/app/mobile/app`, `/services`, `/stores` |
| **Data stores** | PostgreSQL (Supabase/asyncpg) + Redis (Upstash) + ChromaDB (RAG) | `/app/backend/requirements.txt` |
| **Async infra** | APScheduler (in-process jobs) + Redis Streams + SSE (EventSource) + FCM push | `scheduler_runner.py`, `event_broadcaster.py` |

### 2.1 Repo layout (high-level)

```
/app
├── backend/                   # FastAPI + Alembic + APScheduler
│   ├── app/
│   │   ├── api/               # 85 route modules — see §3.2
│   │   ├── services/          # 113 domain services (business logic)
│   │   ├── models/            # 42 SQLAlchemy ORM models
│   │   ├── workers/           # Scheduler runner (separate process)
│   │   └── core/              # Auth, config, login-backoff, utilities
│   ├── tests/                 # 209 test files, pytest + pytest-asyncio
│   └── requirements.txt
│
├── frontend/                  # React web app
│   └── src/
│       ├── pages/             # Route-level components (76)
│       ├── components/        # Shared UI (103)
│       ├── contexts/          # AuthContext + others
│       ├── api.js             # Axios + SSE client
│       └── __tests__/         # Jest regression suites
│
├── mobile/                    # React Native (Expo)
│   ├── app/                   # expo-router tree
│   ├── services/              # api, sse, push, siren, voice, audio, …
│   ├── components/            # GuardianLiveMap, JourneyPolyline, …
│   ├── stores/                # Zustand (auth, risk, live tracking, …)
│   └── hooks/                 # useGuardianSSE, usePolling, …
│
└── memory/                    # Product truth docs — read first
    ├── PRD.md                  (1500+ lines, master spec)
    ├── CHANGELOG.md            (dated, append-only)
    ├── ROADMAP.md              (P0/P1/P2 backlog)
    ├── SYSTEM_INVARIANTS.md    (non-negotiable architecture rules)
    ├── JOURNEY_INTELLIGENCE_INTEGRATION.md
    ├── WEARABLE_AUDIT.md
    └── test_credentials.md     (seeded accounts for QA)
```

---

## 3. Architecture

### 3.1 Process topology

```
          ┌────────────────────┐
  [RN]    │ Expo SDK 55 App    │──push──▶ FCM ──▶ Android/iOS
  [WEB]   │ React CRA (nginx)  │                       │
          └──────────┬─────────┘                       │
                     │ HTTPS + SSE                     │
                     ▼                                 │
          ┌──────────────────────┐    ┌────────────────┴────┐
          │  FastAPI   (port 8001)│    │  APScheduler runner │
          │  supervisor-managed   │    │  separate process   │
          │  514 handlers         │    │  watchdog/escalation│
          └──────────┬────────────┘    └────────────────────┘
                     │
             ┌───────┼───────────────┐
             ▼       ▼               ▼
       ┌─────────┐ ┌───────┐  ┌─────────────┐
       │Postgres │ │ Redis │  │ Chroma (RAG)│
       │(async)  │ │Upstash│  └─────────────┘
       └─────────┘ └───────┘
```

**Two always-on processes** managed by `supervisord`: `backend` (FastAPI API) and `nischint-scheduler` (APScheduler tick loop). Isolation is deliberate — see `SYSTEM_INVARIANTS.md`. Never consolidate them.

### 3.2 API surface (85 routers — auto-generated from disk)

Auth & users · seniors · devices · telemetry · incidents · dashboard · stream · push · alert_ack · risk_panel · journey · operator · my · safety · night_guardian · safe_route · guardian · guardian_ai · guardian_ai_v2 · guardian_dashboard · guardian_incidents · guardian_link · guardian_live · guardian_network · predictive_alert · safety_score · emergency · route_monitor · sensors · zones · geofence · google_auth · admin · ai_brain · ai_learning · ai_services · blog · caregiver · chatbot · checkin · child · command_center_unified · demo · enquiry · entity_engine · fake_call · fake_notification · funnel_tracking · geo_analytics · geo_scaling · journey_delivery · journey_rollout · journey_store · journey_sync · location_sharing · monitoring · notification_settings · pickup · pilot · pr_intelligence · rag · realtime_events · replay · reroute · revenue_os · safety_brain · safety_brain_v2 · safety_events · seo_engine · sos · status · twilio_webhook · voice_trigger · wearable · ws_command_center · _dev

### 3.3 Real-time delivery contract

- Server → client: **SSE** on `/api/stream` (web) and `/api/journey/sos/{id}/stream` (mobile SOS).
- Broadcaster: `app/services/event_broadcaster.py` — channels keyed by `user:{id}` and `role:operator`.
- Event envelope: `{ id, type, channel, data, timestamp }`.
- Replay buffer: 60s, in-memory per process.
- **Risk updates**: go through `app/services/risk_emitter.py` — disciplined emitter with Redis-backed state + atomic INCR versioning + `emit_key` idempotency. See `CHANGELOG.md` 2026-05-04 entries.

### 3.4 Non-negotiable architectural rules

Read `/app/memory/SYSTEM_INVARIANTS.md` in full. Summary:
1. **Separation of API and Scheduler processes.** Never fold scheduler logic into request handlers.
2. **APScheduler jobs must keep `coalesce=True, misfire_grace_time=30`.** `_tick` interval ≥ 10s. Lowering either causes scheduler starvation.
3. **`GuardianAlert.session_id` is nullable; `user_id` is NOT NULL.** Always pass `user_id` when creating alerts.
4. **Journey points are append-only — never a state source.** Reads come from `guardian_sessions.current_location`.
5. **Stale packets (server-clock compare)** must be dropped silently. No side effects.
6. **All backend routes prefixed with `/api`.** The ingress redirects on that prefix.
7. **All URLs/ports/tokens come from `.env`** — never hard-code defaults.
8. **MongoDB `_id` must be excluded** from responses (legacy doc fields).

### 3.5 Third-party integrations

| Service | Where wired | Owner-provided secret |
|---|---|---|
| **Firebase (FCM)** — push | `services/push_service.py`, `api/push.py` | Project JSON + service-account |
| **Twilio** — SMS + automated voice escalation | `services/sms_service.py`, `services/alert_ack_engine.py`, `api/twilio_webhook.py` | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM` |
| **OpenAI / Anthropic / Gemini** — LLM text, Whisper STT, image-gen | via Emergent LLM key + `emergentintegrations` lib | `EMERGENT_LLM_KEY` |
| **Stripe** — payments (if enabled) | Revenue OS module | Stripe test keys in env |
| **Resend / SendGrid** — transactional email | `services/email_service.py` | `RESEND_API_KEY` |
| **Supabase** — primary Postgres | `DATABASE_URL` (asyncpg DSN) | managed |
| **Upstash Redis** — cache + streams | `REDIS_URL` | managed |
| **Google OAuth** — social login | `api/google_auth.py` | OAuth client creds |
| **ChromaDB** — RAG vector store | `services/rag_generation.py` | embedded |

---

## 4. Deployment & Operations

### 4.1 Runtime
- Kubernetes-hosted preview + prod environments (Emergent platform).
- `supervisord` manages processes: `backend` + `frontend` + `nischint-scheduler`.
- **Hot reload on**: editing Python auto-reloads backend; yarn watches frontend.
- Manual restart only needed after `.env` changes or new dependency installs: `sudo supervisorctl restart backend`.

### 4.2 Environment variables (canonical, partial list)
Kept in `.env` files — never committed, never defaulted in code:
- `DATABASE_URL`, `REDIS_URL`, `DB_NAME`
- `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `JWT_EXPIRATION_MINUTES`
- `EMERGENT_LLM_KEY`
- `FIREBASE_PROJECT_ID`, `FIREBASE_PRIVATE_KEY`, `FIREBASE_CLIENT_EMAIL`
- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM`
- `REACT_APP_BACKEND_URL` (frontend)
- `EXPO_PUBLIC_API_URL` (mobile)
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
- `RESEND_API_KEY`

### 4.3 Deployment workflow
1. PR → review → merge to `main`.
2. Emergent's **Save to Github** + platform deploy handles infra.
3. Alembic migrations run before app boot.
4. Smoke test: `curl /api/health` + SSE subscribe + one E2E SOS trigger.

---

## 5. Scope of Work (vendor deliverables)

Organized in **three tiers**. Vendor must propose against each.

### 5.1 Tier A — Maintenance (always-on, recurring)

| # | Deliverable | Accept criteria |
|---|---|---|
| A1 | **Uptime & incident response** | Prod uptime ≥ 99.5% monthly. P1 outage triage starts within 30 min (business hours) / 2 hr (off-hours). |
| A2 | **Dependency & security patching** | Python/Node/Expo patches applied within 14 days of CVE disclosure. Monthly `yarn audit` + `pip-audit` report. |
| A3 | **Bug triage & fix** | All P0 bugs closed < 48 hr, P1 < 1 week, P2 < 1 sprint. |
| A4 | **Test suite health** | Keep 209 backend + web + mobile suites green. No skipped tests without an open ticket. |
| A5 | **Observability upkeep** | `[RISK_EMIT]` / `[RISK_LIVE]` / `[SSE_DELIVERY]` logs remain readable. Log-based anomaly alerts to on-call. |
| A6 | **Backup & DR** | Postgres nightly snapshots retained 30 days. Quarterly restore drill. |
| A7 | **Credentials rotation** | JWT secret + Firebase + Twilio + Resend rotated at least annually. |

### 5.2 Tier B — Feature development (pipeline)

From the live `memory/ROADMAP.md` + `CHANGELOG.md` backlog. Updated as of handoff:

| Priority | Feature | Reference |
|---|---|---|
| 🔴 P0 | Twilio voice-escalation E2E (needs valid Auth Token, code is done) | `services/alert_ack_engine.py` |
| 🟢 P1 | **Predictive Risk v1** — rule-based, shadow-mode first | New `services/risk_predictor.py` |
| 🟢 P1 | Kill `/live/risk` polling after SSE validation | `useGuardianLocationPolling.ts`, `FamilyDashboard.jsx` |
| 🟡 P1 | Watchdog → emitter wiring (time-decay risk pulses) | `alert_ack_engine._tick` |
| 🟡 P1 | Android `critical_safety` channel siren loop field validation on EAS build | `mobile/services/pushService.ts` |
| 🟡 P1 | Shareable journey-replay link (public, signed-token) | New page `/journey/:sid/replay` |
| 🟢 P2 | Phase 2 AI Workload Isolation (Redis Streams `XREADGROUP` for LiteLLM) | New service |
| 🟢 P2 | Migrate Entity Engine + GEO history to MongoDB | Research needed |
| 🟢 P2 | Predictive heatmap UX integration | Operator dashboard |
| 🟢 P2 | Offline-first mobile journey (queue + replay) | `mobile/services/offlineQueue.ts` |

### 5.3 Tier C — Strategic (vendor proposes)

Vendor must propose one *system-level* improvement per quarter (not feature work). Examples:
- Horizontal scale runbook (we're single-process on several services today).
- Multi-region Postgres replica strategy.
- ML model lifecycle (when Predictive v2 outgrows rules).
- Mobile native-module split (when Expo Go hits a hard limit).

---

## 6. KRAs / KPIs (how the contract is measured)

Group by **system health**, **delivery**, and **customer-impact**. All measured monthly.

### 6.1 System-health KRAs (non-negotiable)

| KRA | Target | Evidence source |
|---|---|---|
| API uptime | ≥ 99.5% / month | uptime monitor (Grafana / Better Uptime) |
| SSE delivery success rate | ≥ 99.9% | `[SSE_DELIVERY] OK` vs. `QUEUED` ratio |
| Risk emitter p95 latency (trigger → broadcast) | < 500 ms | log sampling |
| Postgres query p99 | < 300 ms | Supabase metrics |
| Redis availability | ≥ 99.9% | Upstash dashboard |
| FCM push delivery success | ≥ 97% | FCM console + `push_service` logs |
| Backend error rate | < 0.5% of requests | Nginx 5xx counter |
| Alembic migration failure | 0 | deploy logs |

### 6.2 Delivery KRAs

| KRA | Target |
|---|---|
| P0 bug MTTR | ≤ 48 hr |
| P1 bug MTTR | ≤ 1 week |
| Sprint velocity (agreed at kickoff) | ≥ 85% of committed |
| Test coverage (backend) | No regression vs. handoff baseline |
| PR review turnaround | ≤ 1 business day |
| Runbook/docs freshness | `CHANGELOG.md` updated same-day as ship |

### 6.3 Customer-impact KRAs

| KRA | Target |
|---|---|
| SOS trigger → guardian push received | < 5 seconds p95 |
| Guardian ack-to-siren-silenced | < 1 second p95 |
| App cold-start → map first-render | < 3 seconds on 4G |
| False-positive voice-distress rate | < 1 per 1000 journey-hours |
| **Predictive v1 shadow accuracy** (once built) | ≥ 60% precision on 1000 labeled events before go-live |

### 6.4 Security KRAs

| KRA | Target |
|---|---|
| CVE patch latency | < 14 days |
| Auth bypass incidents | 0 |
| PII leak incidents | 0 |
| Secret rotation cadence | ≤ 12 months |
| Failed-login rate-limit bypasses | 0 |

---

## 7. Access Matrix (what vendor needs)

| Access | Purpose | Owner-side action |
|---|---|---|
| GitHub read+write on Nischint org | Code changes, PR reviews | Invite `@vendor-lead` + `@vendor-engineers` |
| Emergent platform seat | Preview/prod deploys | Add as collaborator |
| Supabase project — developer role | DB inspection, migrations | Invite |
| Upstash Redis — developer role | Cache/stream ops | Invite |
| Firebase console — developer role | FCM config | Add email |
| Twilio console — developer role | SMS/voice, number config | Add user |
| Sentry / log aggregator | Error triage | Add seat |
| `test_credentials.md` | QA accounts | Already in repo (`/app/memory/`) |
| **Not shared**: primary domain registrar, Apple/Google store publisher keys, Stripe live keys | Retained by client | — |

---

## 8. Intellectual Property & Compliance

- All code vendor produces is **work-for-hire** assigned to Nischint.
- Vendor may not reuse Nischint-specific domain code in other products.
- Vendor must NOT store Nischint user PII on vendor-controlled systems except for time-boxed debugging with client approval.
- DPDP (India) applies: voice audio, location trails, contact graphs are sensitive personal data.
- Quarterly DPIA (data-protection impact assessment) signed jointly.

---

## 9. Communication & Governance

| Ritual | Cadence | Attendees |
|---|---|---|
| Sprint planning | Every 2 weeks | Vendor lead + client owner |
| Stand-up | Daily, async (Slack/Discord) | Vendor engineers + client owner |
| Demo & review | End of sprint | All |
| System health review | Monthly | Vendor lead + client CTO |
| Quarterly strategic review | Q1/Q2/Q3/Q4 | Leadership both sides |
| Incident post-mortem | Within 5 business days of a P0 | Vendor + client |

Single source of truth for tasks: GitHub Projects (or Linear, client's choice).
Single source of truth for product: `/app/memory/PRD.md` (+ `ROADMAP.md`, `CHANGELOG.md`).

---

## 10. Onboarding Plan (vendor's first 30 days)

### Week 1 — Read-only immersion
- Read `memory/PRD.md`, `SYSTEM_INVARIANTS.md`, `CHANGELOG.md` (last 90 days), `ROADMAP.md`.
- Clone repo, get local stack running (postgres + redis docker compose + yarn + pytest).
- Walk through the four critical flows live:
  1. Guardian signup → child link → journey start → live map → journey end
  2. SOS trigger (`/api/child/help-request`) → SSE event → guardian push → auto-escalation
  3. Voice-distress detection → backend event → guardian alert
  4. Operator Risk Panel → swipe-to-ACK → DB alert update

### Week 2 — Shadow
- Pair with outgoing agent/team on any active P0/P1.
- Take over one P1 bug end-to-end under review.
- Run the full test suite: `pytest tests/ -q` (backend), `yarn test` (web), `tsc --noEmit` (mobile).

### Week 3 — Ownership
- Own one Tier-B feature (e.g., kill `/live/risk` polling or ship Predictive v1 shadow mode).
- Publish first monthly health report against the KRAs in §6.

### Week 4 — Sign-off
- Joint review: is the vendor productive? KRAs realistic? Any gaps in access/docs?
- Either formalize the engagement or terminate cleanly.

---

## 11. Known Technical Debt (disclosed upfront)

Be honest with vendors — this protects both sides. Current disclosed debt:

- Alembic migrations directory is empty (schema is provisioned directly). Migration discipline needs to be introduced vendor-side.
- 2 frontend tests exist (auth interceptor + protected route). Jest coverage is low.
- 1 unit test for mobile polyline. Mobile lacks a proper Jest/Detox setup.
- Several services (e.g. Entity Engine, GEO history) still use MongoDB-style docs inside Postgres JSONB — migration planned.
- Some older route modules (`guardian_ai` vs `guardian_ai_v2`, `safety_brain` vs `safety_brain_v2`) are parallel generations; a dedup pass is due.
- Twilio voice escalation is code-complete but credentials-blocked at handoff.

---

## 12. Minimum Vendor Qualification Bar

Don't shortlist vendors that don't meet **all five**:

1. **Production FastAPI + async SQLAlchemy** experience (5+ apps shipped).
2. **SSE / WebSocket real-time systems at ≥ 10K concurrent connections** — they must describe back-pressure + reconnection strategies in the bid.
3. **React Native + Expo** delivery for a production app (not just Expo Go demos).
4. **APScheduler / Celery / similar** background-job experience; understands why we split API from scheduler.
5. **Incident-response track record**: they publish their on-call SLA tiers and have previously run P0 post-mortems.

Ask for two client references and one **public post-mortem** in the bid.

---

## 13. Pricing Structure (recommended)

Two models — let vendors pick; you can negotiate.

**Model A — Fixed monthly retainer + T&M overflow**
- Tier A (maintenance): fixed monthly ₹X (covers up to N engineering hours).
- Tier B (features): billed T&M at ₹Y/hour against approved sprints.
- Tier C (strategic): quarterly fixed ₹Z per proposal.

**Model B — Full managed service**
- Single monthly fee covering all three tiers.
- KRA-linked penalty clause: X% refund per missed Tier-A KRA per month.

Client gets to audit vendor time logs quarterly.

---

## 14. Exit Clause (critical — do not skip)

- 60-day notice either way.
- Within the notice period vendor must:
  - Hand over **current runbook + infra topology diagram + access matrix**.
  - Complete a joint 5-day rehearsed handover to next team.
  - Leave `memory/CHANGELOG.md` updated through their last commit.
  - Return/disable all access.
- Client keeps all code + documentation + test credentials.
- Vendor may not solicit Nischint customers for 18 months post-engagement.

---

## 15. First 10 Things to Ask Shortlisted Vendors

Hand this as an RFP response template:

1. Walk us through how you'd take over a system with 514 FastAPI handlers + an in-process APScheduler in 30 days. What's your first week?
2. Show us one SSE-heavy system you've scaled past 10K concurrent connections. What broke first?
3. How do you run incident post-mortems? Share one redacted real example.
4. How would you implement our shadow-mode predictive risk v1? Rule set + accuracy gate?
5. Our `SYSTEM_INVARIANTS.md` is non-negotiable. Read it and tell us which rule you'd most want to challenge, and why.
6. How do you handle credential rotation for Twilio/Firebase/JWT without downtime?
7. What's your process for introducing Alembic migration discipline to a project that currently has none?
8. Our risk emitter uses Redis atomic INCR for versioning. Walk us through the failure modes and how you'd monitor them.
9. What tooling do you recommend for mobile crash reporting and performance monitoring (we currently have none on RN)?
10. Draft a 1-page SLA that includes your KRA measurement method and penalty for missed targets.

---

## 16. Appendix — Quick-reference files for vendor review

| File | Why it matters |
|---|---|
| `/app/memory/PRD.md` | Product spec, updated continuously. Read first. |
| `/app/memory/SYSTEM_INVARIANTS.md` | Non-negotiable architecture rules. |
| `/app/memory/CHANGELOG.md` | Dated history of every recent change. Includes all 2026-05-* entries from the current session. |
| `/app/memory/ROADMAP.md` | P0/P1/P2 backlog. |
| `/app/memory/JOURNEY_INTELLIGENCE_INTEGRATION.md` | How journey polyline + risk layer hook together. |
| `/app/memory/WEARABLE_AUDIT.md` | Wearable device integration audit. |
| `/app/memory/test_credentials.md` | QA accounts (rotate during/after handover). |
| `/app/backend/app/services/risk_emitter.py` | Reference example of the emit-discipline pattern — vendor will be expected to extend this pattern for predictive. |
| `/app/backend/app/services/event_broadcaster.py` | The SSE broadcaster. Do not replace; extend. |
| `/app/backend/app/workers/scheduler_runner.py` | The scheduler-process entrypoint. Must stay separate from API. |

---

_This document is the authoritative handoff package. Any commitment to a vendor that deviates from §5 / §6 / §14 must be escalated to the owner before signature._
