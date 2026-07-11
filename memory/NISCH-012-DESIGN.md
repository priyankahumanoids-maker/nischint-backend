# NISCH-012 — External Data Integration Layer

> Design doc generated Feb 2026, ahead of implementation. Read this
> before greenlighting Phase 12.0 so we agree on the abstractions
> before the first line lands.

---

## TL;DR

We ship in 5 phases. Phase 12.0 is a 3-day pilot that wires the
**already-implemented** weather signal into the alert pipeline (it
currently feeds the dashboard but NOT the trigger pipeline — that's
the architectural gap). Phases 12.1-12.4 then plug into the same
abstraction one provider at a time.

Critical decisions locked in this doc:
1. Provider abstraction: `ExternalSignalProvider` interface
2. Modifier math: **additive, capped at +0.20** (multiplicative
   compounds badly when 3 signals fire)
3. Persistence: `external_signal_modifiers` JSONB column on
   `safety_incidents` for forensic explainability
4. Traffic: **TomTom** (not Google Maps) — better Indian free tier
5. NDRF: **Sachet CAP-XML** with ETag polling (NOT the noisy RSS)
6. News: NewsAPI (English) + Twitter v2 (Hindi/regional) deferred
   to 12.2 with operator-review queue (no auto-escalation)

---

## What's already in the codebase (Phase 0 — done)

| Capability                        | File                                         | State                    |
|-----------------------------------|----------------------------------------------|--------------------------|
| OpenWeather client + cache        | `services/weather_service.py`                | LIVE (10-min Redis cache)|
| Environment risk engine (5-factor)| `services/environment_risk_engine.py`        | LIVE (30-min cache)      |
| `OPENWEATHER_API_KEY`             | `backend/.env`                               | SET                      |
| `httpx` + grid-cache pattern      | weather_service.py                           | LIVE (reusable)          |
| Risk engines consuming env risk   | `dynamic_risk_engine`, `guardian_ai_refinement`, `command_center_unified`, `operator`, `ai_services`, `incident_replay_engine` | LIVE |
| **Forensic event log infrastructure** | `safety_incident_events`                | LIVE (NISCH-006)         |

**The architectural gap**: weather risk feeds the **dashboard** path
but the **trigger pipeline** (`incident_classifier`,
`safety_incident_engine`, `voice_distress_service`, `alert_trigger.py`)
does NOT consume it. A distress call during a flood gets no
confidence bump today. Phase 12.0 fixes this.

---

## Provider abstraction — the contract

```python
# /app/backend/app/services/external_signals/base.py
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

class ExternalSignal(BaseModel):
    provider: str          # "weather" | "traffic" | "sachet" | "news"
    risk_0_1: float        # 0..1 normalized severity contribution
    factors: list[str]     # human-readable reasons ("flood_warning", "heavy_rain")
    confidence: float      # 0..1 — how much do we trust this provider's data right now?
    fetched_at: datetime
    expires_at: Optional[datetime]   # when the underlying source expires
    raw_url: Optional[str]           # for forensic linkback (e.g. CAP alert URL)

class ExternalSignalProvider(ABC):
    name: str
    cache_ttl_s: int

    @abstractmethod
    async def fetch(self, lat: float, lng: float,
                    when: Optional[datetime] = None) -> Optional[ExternalSignal]:
        """Return the current signal at the given location, or None if
        the provider is unreachable / has no data. NEVER raise — fail
        quiet so the alert path is never blocked on external infra."""
```

Each provider sits in its own module:
- `services/external_signals/weather.py` — wraps existing
  `weather_service.py` (no new HTTP client; just an adapter)
- `services/external_signals/traffic.py` — TomTom (Phase 12.1)
- `services/external_signals/sachet.py` — Sachet CAP polling (Phase 12.3)
- `services/external_signals/news.py` — NewsAPI + Twitter (Phase 12.2)

A `services/external_signals/registry.py` exposes:
```python
async def fetch_all_signals(lat, lng, when=None) -> list[ExternalSignal]:
    """Parallel-fetch every enabled provider with asyncio.gather +
    timeout. Disabled providers (no API key in env) are silently
    skipped. Failures of any single provider don't fail the batch."""
```

**Why this contract:**
- Pure pluggability — adding a 5th provider is a new file + 1 line
  in the registry.
- `fail-quiet` rule is enforced at the type system: every method
  returns `Optional` and never raises. No try/except smell scattered
  across consumers.
- Forensic linkback (`raw_url`) means operators can click through
  to the original CAP alert / TomTom incident page from the timeline.

---

## Modifier math — additive, capped, audited

```python
# /app/backend/app/services/external_signals/modifier.py

CONFIDENCE_BUMP_PER_HIGH_SIGNAL = 0.05
CONFIDENCE_BUMP_CAP             = 0.20    # max +0.20 even if 8 signals fire
HIGH_SIGNAL_THRESHOLD           = 0.6     # only signals with risk >= 0.6 contribute

def apply_external_modifiers(
    base_confidence: float,
    signals: list[ExternalSignal],
) -> tuple[float, list[dict]]:
    """Returns (modified_confidence, audit_trail).

    `audit_trail` is what gets persisted into safety_incidents.extra
    so the timeline can show 'confidence was 0.78 → 0.93 because:
    weather=heavy_rain (+0.05), sachet=cyclone_warning (+0.10)'."""
    audit = []
    bump = 0.0
    for sig in sorted(signals, key=lambda s: -s.risk_0_1):
        if sig.risk_0_1 < HIGH_SIGNAL_THRESHOLD:
            continue
        if bump >= CONFIDENCE_BUMP_CAP:
            audit.append({"provider": sig.provider, "factors": sig.factors,
                          "applied": False, "reason": "cap_reached"})
            continue
        contribution = min(
            CONFIDENCE_BUMP_PER_HIGH_SIGNAL * sig.risk_0_1,
            CONFIDENCE_BUMP_CAP - bump,
        )
        bump += contribution
        audit.append({"provider": sig.provider, "factors": sig.factors,
                      "applied": True, "delta": round(contribution, 3),
                      "raw_url": sig.raw_url})
    return min(0.99, base_confidence + bump), audit
```

**Why additive, not multiplicative:**
- Multiplicative compounds badly when 3 signals fire at once
  (1.0 × 1.5 × 1.5 × 1.5 = 3.4 — runaway).
- Additive with a hard cap is bounded and explainable:
  "your alert got bumped because of weather + traffic + Sachet,
  total +0.20, capped."

**Why threshold = 0.6:**
- Below 0.6, signals are noise (mild traffic, light rain).
- Above 0.6, signals are operational (flood, accident, cyclone).
- The threshold is per-signal — even one strong signal is enough
  to bump; 6 weak signals get ignored.

---

## Schema changes (Phase 12.0)

One Alembic migration:
```python
# em1a2b3c4dz01_add_external_signals_to_incidents.py
op.add_column("safety_incidents",
    sa.Column("external_signals", JSONB, nullable=True))
op.add_column("safety_incidents",
    sa.Column("confidence_pre_external", sa.Float, nullable=True))
```

`external_signals` shape:
```json
{
  "fetched_at": "2026-05-09T13:42:11Z",
  "modifier_applied": 0.15,
  "modifier_capped":  false,
  "audit": [
    {"provider": "weather", "factors": ["heavy_rain","flood_risk"],
     "applied": true, "delta": 0.05, "raw_url": null},
    {"provider": "sachet", "factors": ["cyclone_warning_extreme"],
     "applied": true, "delta": 0.10,
     "raw_url": "https://sachet.ndma.gov.in/cap_public_website/FetchXMLFile?identifier=…"}
  ]
}
```

`confidence_pre_external` is the original ML/heuristic confidence
before external bumps — gives operators an "AI said X, weather/Sachet
bumped to Y" view in the timeline.

A forensic `safety_incident_events` row also fires on every modifier
application with `actor_type='external_signal'` so the timeline
shows the bump alongside guardian acks and community feedback.

---

## Phase plan — concrete steps

### Phase 12.0 — Plumbing + weather pilot (3 days)

**Day 1**: Build the abstraction.
- `services/external_signals/{base,registry,modifier}.py`
- `services/external_signals/weather.py` (adapter over the existing
  `weather_service.py` — zero new HTTP code)
- Migration `em1a2b3c4dz01` — `external_signals` JSONB +
  `confidence_pre_external`

**Day 2**: Wire into the alert pipeline.
- `incident_classifier.py` calls `registry.fetch_all_signals()` and
  `apply_external_modifiers()` after the base ML/heuristic classification
- `safety_incident_engine.create_incident()` persists the audit
  trail into `external_signals` JSONB + writes a
  `safety_incident_events` row with `actor_type='external_signal'`
- `incidents_feed` and `safety_incidents` timeline endpoint surface
  `confidence_pre_external` + `external_signals.audit` on the response

**Day 3**: Tests + deploy.
- `tests/test_external_signal_modifier.py` — modifier math (cap,
  threshold, weak-signal exclusion, audit shape)
- `tests/test_external_signals_registry.py` — registry skips
  disabled providers, swallows individual failures, parallel fetch
- `tests/test_incident_classifier_with_signals.py` — end-to-end:
  voice-distress event in a known weather grid → confidence bumped
  appropriately + audit persisted
- Mobile: timeline screen renders the audit trail (one new
  `<ExternalSignalsBlock />` component below the existing event list)

**Validation gate**: Same TestFlight build as today serves Phase 12.0
without rebuild. Pure backend + an additive timeline UI block.

### Phase 12.1 — Traffic via TomTom (4 days)

**Why TomTom over Google Maps**: TomTom Free tier = 2,500 req/day,
generous for our scale. Google = $7/1000 reqs, 10× more expensive
at scale, and our use case (Indian routing) is TomTom's strong
suit.

**Day 1**: TomTom Traffic Incident Details API client
- New env var: `TOMTOM_API_KEY`
- `services/external_signals/traffic.py` provider returning
  `risk_0_1` based on (a) congestion level near the user, (b)
  active incidents (accidents, road closures) within 1 km.
- 5-min Redis cache per ~500m grid (their incidents API is rate-
  limited; aggressive caching is mandatory).

**Day 2-3**: Risk-modifier policy.
- Heavy congestion (level ≥ 4) + late hour (22:00-04:00 local) +
  voice/SOS distress = treat as `risk_0_1 = 0.8` (operational signal:
  child stuck in stalled traffic with active distress is a real
  safety event, not just "they're in a jam").
- Active accident incident within 1 km of an SOS = `risk_0_1 = 0.9`.

**Day 4**: Tests + deploy.
- `tests/test_external_signals_traffic.py` — 6+ cases: congestion
  thresholds, accident proximity, cache TTL, time-of-day gating,
  fail-quiet on 401/429.

### Phase 12.2 — News + social keyword monitor (5 days)

**Why this is the riskiest phase and runs LAST among the auto-active
providers:**
- Signal-to-noise ratio of news is 10:1 worse than weather/traffic/
  Sachet. A keyword hit is NOT a confirmed incident.
- Auto-bumping confidence on news is a compliance liability
  (false positive cascade, harassment risk if we trigger SOS-style
  workflows on a misclassified tweet).

**Policy: news signals NEVER auto-bump confidence.** They only
populate an **operator review queue** that surfaces in the existing
operator console (NISCH-009 anomaly review pattern). Operator
manually escalates if needed.

- Day 1-2: NewsAPI client (`NEWS_API_KEY`) — pull headlines mentioning
  "[city/district name] AND (accident|crime|disaster|protest|outbreak)"
  every 15 min, geocode the headline, populate review queue.
- Day 3: Twitter v2 client (`TWITTER_BEARER_TOKEN`) — same shape,
  hashtag + keyword filter, English + Hindi.
- Day 4: Operator review queue UI — list of unprocessed news/social
  hits with "Trigger area-wide elevated-risk window" button.
- Day 5: Tests.

### Phase 12.3 — Sachet CAP-XML (3 days)

**Verified path** (per Sachet integration guide PDF):
- Polling endpoint #1 (alert list): RSS at
  `https://sachet.ndma.gov.in/cap_public_website/rss/rss_india.xml`
  — gives us alert identifiers. Poll every 60s with ETag.
- Polling endpoint #2 (per-alert structured CAP-XML):
  `https://sachet.ndma.gov.in/cap_public_website/FetchXMLFile?identifier={id}`
  — one fetch per new identifier seen in the RSS. Cache forever
  (CAP alerts are immutable; new revisions get new identifiers).
- No auth, no registration, no rate limit documented (but ETag
  support implies they expect compliant clients).

**Day 1**: Build the poller as an APScheduler tick (60s cadence)
in `safety_incident_scheduler.py`.
- New table: `sachet_alerts (identifier PK, event_code, severity,
  urgency, certainty, area_geojson, effective, expires, raw_xml,
  fetched_at)`.
- ETag stored in Redis (`nischint:sachet:rss:etag`).
- Poll RSS → for each unseen identifier, fetch CAP-XML, parse,
  insert. Skip already-seen.

**Day 2**: Build the provider that queries the table.
- `services/external_signals/sachet.py`: given (lat, lng, when),
  query `sachet_alerts` for rows whose `area_geojson` contains the
  point AND `effective <= when <= expires`. Return strongest match.
- CAP severity → `risk_0_1` mapping:
  - `Extreme` (cyclone, flood imminent) → 0.95
  - `Severe`  → 0.80
  - `Moderate` → 0.50
  - `Minor` / `Unknown` → 0.30

**Day 3**: Tests + deploy.
- 5+ test cases: poller respects ETag (304 path), inserts new rows
  on 200, parses CAP polygon correctly, provider returns highest
  severity when multiple alerts cover a point, expired alerts are
  filtered out.

### Phase 12.4 — Operator UI surface (2 days)

- Operator console: "External signal influences" panel showing
  active signals across the fleet, top 5 alerts by impact (incidents
  bumped because of this signal).
- Per-incident timeline: `<ExternalSignalsBlock />` component
  rendering the audit trail with provider chips + factor tags +
  forensic linkback URLs.
- One "system audit" view: total modifier applications by provider
  in the last 24h — answers operator question "is the weather
  signal actually firing in production?"

---

## Cost & dependency table

| Provider     | Free tier              | Auth needed?     | Rate limit                | Setup blocker?              |
|--------------|------------------------|------------------|---------------------------|------------------------------|
| OpenWeather  | 60 req/min             | API key (have it)| Already cached aggressively| None (live)                 |
| TomTom       | 2,500 req/day          | API key (need it)| Per-key throttle          | User signs up at developer.tomtom.com (5 min) |
| Sachet CAP   | Unlimited (uses ETag)  | None             | Undocumented (be polite)  | None                        |
| NewsAPI      | 100 req/day free       | API key          | 100/day on free           | User signs up + considers $50/mo Developer tier |
| Twitter v2   | 1,500 tweets/15min basic | Bearer token   | Tier-based                | Twitter dev account approval ~3-5 days |

---

## Open questions for the user before Phase 12.0 kicks off

1. **Mobile app version gating** — the new `external_signals.audit`
   block on the timeline response: do we render it (a) on every
   incident (might confuse users who don't care), (b) only when the
   modifier was actually applied (`audit.length > 0`), or (c)
   guarded by a feature flag for staged rollout?

2. **Confidence bump visible to guardians?** When a confidence bump
   fires, should the guardian SSE include the bump+factors in the
   payload (so the row in the feed shows "weather elevated"), or
   should it stay operator-only?

3. **TomTom signup** — the API key is the only blocker for Phase 12.1.
   Want me to ship 12.0+12.3 (which need no new API keys) FIRST and
   defer TomTom until you've signed up?

4. **News/social** — given the SNR concern, do we ship 12.2 at all,
   or treat it as 13.x and skip from this sprint?

---

## Recommended sequencing

```
12.0 (3d) ───→ 12.3 Sachet (3d) ───→ 12.1 TomTom (4d) ───→ 12.4 UI (2d)
                                                                         ↓
                                                              [MAYBE] 12.2 News
```

12.0 + 12.3 + 12.1 + 12.4 = **12 working days, ~2.5 calendar weeks**
matching the card's 2-3 week estimate. Skipping 12.2 (operator-
review-only) keeps it in the 2-3w window. Adding 12.2 pushes to
~3.5 weeks.

---

## Files to be touched (preview list)

**New backend:**
- `migrations/versions/em1a2b3c4dz01_add_external_signals_to_incidents.py`
- `app/services/external_signals/{base,registry,modifier,weather,traffic,sachet,news}.py`
- `app/services/sachet_poller.py`
- `app/api/external_signals.py` (operator audit endpoint)
- `tests/test_external_signal_*.py`

**Modified backend:**
- `app/services/incident_classifier.py` — call registry + modifier
- `app/services/safety_incident_engine.py` — persist audit
- `app/api/safety_incidents.py` — surface audit on timeline
- `app/api/incidents_feed.py` — optional: surface modifier flag
- `app/services/safety_incident_scheduler.py` — register Sachet poller

**Modified mobile:**
- `app/incident-timeline.tsx` — render `<ExternalSignalsBlock />`
- `components/incidents/ExternalSignalsBlock.tsx` (new)

No native module changes — Phase 12.0–12.3 ship via JS-only update
on top of the existing TestFlight build.
