# Disaster-Recovery Runbook

> Last drill: **2026-05-30 (preview pod, app-pool variant)**.
> Maintained by: platform on-call.
> Audit cadence: every 90 days *and* after any infra change to DB or Redis.

This runbook is the playbook for two of the most common production
failure modes: PostgreSQL connection-pool exhaustion (a slow internal
failure) and Redis unreachability (a sudden external failure).

It captures **what we tested, what worked, what broke, and the exact
remediation steps**. Every recommendation here is backed by evidence
from the 2026-05-30 drill, not theory.

---

## Architecture you must know before triage

The backend runs **two Python processes** under supervisor — they share
the same .env but have **separate SQLAlchemy connection pools**:

| supervisor unit | role | pool | starts schedulers? |
|---|---|---|---|
| `backend` | uvicorn API server | own pool (size=20, max_overflow=10) | **no** — `role=api` skips |
| `nischint-scheduler` | APScheduler runner (`app.workers.scheduler_runner`) | own pool (size=20, max_overflow=10) | **yes** — owns `db_pool_monitor`, `health_monitor`, etc. |

**Why this matters:** the DB-pool-monitor only watches the *scheduler
process's* pool. A user-traffic spike that drains the *uvicorn
process's* pool will NOT trigger `system_incident(database_pool)`. The
2026-05-30 drill confirmed this gap (see below).

---

## Scenario 1 — PostgreSQL connection-pool exhaustion

### Symptoms

| Surface | Behaviour observed during drill |
|---|---|
| `/api/health` | **HTTP 200** throughout (correct — shallow liveness probe) |
| `/api/public/status` | Initially served from Redis cache (30 s TTL). After cache expiry, response time climbed to **48–60 s**. 9 of 35 concurrent requests timed out at 60 s. |
| `/api/admin/monitoring/dashboard-summary` | Failed to respond within 5 s during storm (own DB session queued behind storm) |
| `/api/auth/login` (post-storm) | Recovered in < 10 s once storm cleared |
| Application logs | No errors. `pool_timeout` reached for surplus requests, returning 504/500 to clients. |
| `system_incident(database_pool)` | **NOT fired** — see "Known gap" below. |
| Browser preview / SPA | Responses delayed; static assets unaffected (cached at CDN). |

### Drill evidence (2026-05-30)

```
Storm: 35 concurrent /api/public/status requests, cache flushed first.
Result: 26 × HTTP 200 (48–60 s each), 9 × timeout (-1).
Pool baseline before: 0/30 in use.
Pool during admin probe attempts: unable to acquire — admin endpoint
also waited on the same pool, so monitoring itself was blind.
Recovery: < 10 s after storm cleared. Final pool: 0/30, util 0%.
```

### Triage — first 60 seconds

1. Confirm symptom is pool exhaustion (not a Postgres outage):
   ```sh
   curl -s "https://nischint.care/api/health"   # liveness — must be 200
   curl -s "https://nischint.care/api/public/status" | jq .components
   ```
2. Pull live pool stats (operator JWT required):
   ```sh
   TOKEN=$(curl -s -X POST "https://nischint.care/api/auth/login" \
     -H "Content-Type: application/json" \
     -d '{"email":"operator@nischint.com","password":"...REDACTED..."}' \
     | jq -r .access_token)

   curl -s -H "Authorization: Bearer $TOKEN" \
     "https://nischint.care/api/admin/monitoring/dashboard-summary" \
     | jq .db.pool
   ```
   Look for: `pg_pool_checked_out` near `pg_pool_total_capacity`,
   `pg_pool_wait_count > 0`, `pg_pool_utilization_pct ≥ 85`.

3. Identify the offending source. Three usual suspects, ranked by
   frequency in past incidents:
   - **Slow scheduler job holding a session.** Check
     `/api/admin/monitoring/scheduler/runtime-info` for any job stuck
     >60 s. Likely owners: `risk_prediction_reconciler`,
     `behavioral_baseline_prewarm`, `fleet_weather`.
   - **Runaway analytical query.** Check
     `pg_stat_activity` from Supabase dashboard
     (filter `state = active` and `query_start < now() - interval '10s'`).
   - **Sudden user traffic spike** without a corresponding cache hit
     ratio. Less likely after the Lighthouse / Redis caching work.

### Remediation by root cause

| Root cause | Action |
|---|---|
| Scheduler stuck on a slow query | `sudo supervisorctl restart nischint-scheduler` in the preview pod (no equivalent in prod — Emergent platform restart needed). This releases all sessions held by the scheduler. |
| Runaway query | In Supabase dashboard: `SELECT pg_cancel_backend(pid)` for the offending pid. If the query is recurring, file a ticket against the issuer (often a backfill or migration). |
| Pure traffic spike | Already mitigated by `/api/public/status` 30 s cache + Cloudflare CDN. If sustained, the only escape is horizontal scale of the API process (currently `--workers 1` — bottleneck open with Emergent Support). |

### Recovery verification (must pass before declaring "all clear")

```sh
# Pool returns to healthy
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://nischint.care/api/admin/monitoring/dashboard-summary" \
  | jq '.db.pool | {checked_out: .pg_pool_checked_out, util: .pg_pool_utilization_pct, available}'
# Expect checked_out < 5, util < 30%, available true

# Login round-trip
time curl -s -X POST "https://nischint.care/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"operator@nischint.com","password":"...REDACTED..."}'
# Expect time < 5 s

# Public status returns within 1 s (cache hit)
time curl -s "https://nischint.care/api/public/status" -o /dev/null
# Expect time < 1 s
```

### Known gap discovered by the 2026-05-30 drill

🚨 **`db_pool_monitor` does NOT see uvicorn-process pool pressure.**

The monitor runs inside `nischint-scheduler` and reads
`get_pool_stats()` from *its own* SQLAlchemy engine. The uvicorn
process has a separate engine with a separate pool. The drill saturated
uvicorn's pool to 100% for 60 s — the scheduler's pool stayed at 0%
the whole time — no incident fired.

**Recommended fix (TODO):**
- Have uvicorn push its `pool_stats()` into Redis on a 5 s tick.
- Have `db_pool_monitor` aggregate readings from both processes (or
  the worst-case of the two) before evaluating thresholds.
- Until that lands, treat the existing monitor as covering only the
  background-worker path, not the user-traffic path. The user-traffic
  path is observable only via `/api/admin/monitoring/dashboard-summary`,
  which itself becomes unavailable during the very condition it would
  diagnose. Sentry alarms on 504/p99 latency are the de-facto early
  warning.

---

## Scenario 2 — Redis unreachability

### Symptoms (matrix from 2026-05-30 drill)

| Surface | Behaviour with Redis pointed at `invalid-host` |
|---|---|
| Backend startup | **Graceful** — `Redis connection failed: ... — running without cache` logged once at INFO/WARNING level. App starts normally. |
| `/api/health` | **HTTP 200** (does not touch Redis) |
| `/api/public/status` | **HTTP 200**, response time grew from `~0.4 s cached → 5.9 s uncached`. Components all "operational" because the public status logic never asserted on Redis. |
| WebSocket fanout | `Redis unavailable — using in-memory broadcast only` — automatic fallback worked. Multi-process fan-out is lost but single-process WS still functional. |
| **`/api/auth/login` (and every rate-limited endpoint)** | 🚨 **HTTP 500 — uncaught `redis.exceptions.ConnectionError`** |
| Funnel analytics, heatmap caches, user-presence pings | Fail silently (return None / skip) — by design. |
| Scheduler-driven WS broadcasts (Stream consumer) | Stop publishing; resume on Redis reconnect. |

### Root cause of the auth 500

```
File "/root/.venv/lib/python3.11/site-packages/slowapi/extension.py", line 509
    if not self.limiter.hit(lim.limit, *args, cost=cost):
File "/root/.venv/lib/python3.11/site-packages/limits/storage/redis.py", line 224
    return int(self.lua_incr_expire([key], [expiry, amount]))
redis.exceptions.ConnectionError: Error -2 connecting to invalid-host-dr-drill.local:6379
```

`slowapi` is configured to use Redis as its hit-counter storage. The
`limits` library raises ConnectionError unmodified; nothing catches it
in our `auth.py` decorator, so it surfaces as 500. **Every rate-limited
endpoint inherits this behaviour** — auth, password reset, SOS trigger,
sensitive admin actions.

### Triage — first 60 seconds

1. Confirm Redis is the actual culprit:
   ```sh
   curl -s "https://nischint.care/api/health"     # 200
   curl -s "https://nischint.care/api/public/status" | jq .overall  # operational
   curl -s -X POST "https://nischint.care/api/auth/login" -d '{}'
   # If health is 200 but login is 500 → Redis side
   ```

2. Inspect the live REDIS_URL target. Upstash (current provider):
   - Dashboard: <https://console.upstash.com/>
   - Project: `beloved-cub-70104` (eu-west-1)
   - SLA: 99.99%; status page <https://status.upstash.com/>
   - Common failure modes: regional incident, quota exceeded
     (free-tier 10K commands/day), TLS cert renewal.

### Remediation

| Failure mode | Action |
|---|---|
| Upstash regional incident | Wait it out — Redis cache is *not* critical-path for safety operations. Auth + rate-limited endpoints will 500 during the window. Post a `degraded` status update via `/status` page (until [TODO] is fixed, manually). |
| Quota exceeded | Upgrade plan or rotate to the standby Redis (TODO — provision a second). |
| Misconfigured `REDIS_URL` in `.env` | Restore from the previous deploy / known good. Reload via `sudo supervisorctl restart backend` (preview) or trigger redeploy (prod). |

### Recovery verification

```sh
# Application logs show a fresh "Redis connected" line
ssh prod-pod tail -50 /var/log/supervisor/backend.err.log | grep "Redis connected"

# Login round-trip succeeds
curl -s -X POST "https://nischint.care/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"operator@nischint.com","password":"...REDACTED..."}' \
  | jq 'keys'   # expect ["access_token", ...]
```

### Known gap discovered by the 2026-05-30 drill

🚨 **slowapi has no memory-storage fallback.**

When Redis is unreachable, every rate-limited endpoint returns 500
immediately on the rate-check step — *before* the actual handler ever
runs. This is worse than it sounds: it means a 5-minute Upstash blip
takes down auth, password reset, and SOS trigger entirely.

**Recommended fix (TODO):**
- Wrap `limiter.hit()` in a try/except that, on `redis.ConnectionError`,
  falls through to an in-memory `MovingWindowRateLimiter` per-process
  rather than returning 500.
- Document the fallback in the `auth.py` decorator so on-call knows
  per-process limits are weaker (different process gets a fresh budget)
  but available.
- A 30-line `slowapi`-compatible storage wrapper would close the gap
  and could ship in a single afternoon.

---

## How to run this drill again

The drill harness lives at `/tmp/dr_drill_db.py` (regenerated as needed).
Always run against the preview pod, never production.

### Phase 1 — DB pool exhaustion (safe variant, app-level)

```sh
# 1. Capture baseline
curl -s "https://gps-mic-restart.preview.emergentagent.com/api/public/status" \
  | jq '.overall, .components'

# 2. Flush the status-page Redis cache so requests actually hit DB
python3 -c "
import sys; sys.path.insert(0, '/app/backend')
from app.services import redis_service
print('flushed:', redis_service.delete_key('public_status', 'v1'))"

# 3. Fire the burst
python3 /tmp/dr_drill_db.py burst

# 4. While the burst runs, sample pool stats with a separate token
TOKEN=$(curl -s -X POST ".../api/auth/login" ... | jq -r .access_token)
curl -s -H "Authorization: Bearer $TOKEN" ".../api/admin/monitoring/dashboard-summary" | jq .db.pool

# 5. Confirm recovery: status response < 10 s, login 200, pool util < 30 %
```

### Phase 2 — Redis failure (safe — local .env only)

```sh
# 1. Backup
cp /app/backend/.env /tmp/backend_env_backup.txt

# 2. Inject invalid host
sed -i 's|^REDIS_URL=.*|REDIS_URL=redis://invalid-host-dr-drill.local:6379/0|' /app/backend/.env

# 3. Restart, wait 10 s for cold start
sudo supervisorctl restart backend
sleep 10

# 4. Verify expected behaviour:
#    - /api/health → 200
#    - /api/public/status → 200 (slower, ~6 s uncached)
#    - /api/auth/login → 500 (known gap until slowapi fallback shipped)

# 5. Restore
cp /tmp/backend_env_backup.txt /app/backend/.env
sudo supervisorctl restart backend
sleep 10

# 6. Verify recovery: /api/auth/login → 200
```

---

## Open follow-ups from the 2026-05-30 drill

| # | Severity | Area | Action | Status |
|---|---|---|---|---|
| 1 | 🔴 P0 | Auth / rate-limit | Add in-memory fallback to `slowapi` rate-limiter so Redis outage doesn't 500 auth. | ✅ **Shipped 2026-05-30** — `app/core/rate_limiter.py` passes `in_memory_fallback_enabled=True`. Verified: login returns 200 with invalid REDIS_URL; rate-limit budgets still enforced in fallback mode (9× 401 → 429). 4 regression tests in `test_rate_limiter_fallback.py`. |
| 2 | 🟡 P1 | Monitoring | Aggregate uvicorn-process pool stats into `db_pool_monitor` so user-traffic-driven pool exhaustion fires `system_incident`. | ✅ **Shipped 2026-05-30** — `app/services/pool_stats_publisher.py` runs a 5 s asyncio ticker inside uvicorn that writes pool stats to Redis key `pool_stats:uvicorn` (TTL 15 s). `db_pool_monitor._tick()` now reads both local and Redis-published snapshots and feeds the worst-of into the threshold engine. Verified: a published `93.33 %` snapshot increments the high-readings counter and fires `system_health_delta database_pool healthy→degraded`. 8 regression tests in `test_db_pool_monitor_aggregation.py`. |
| 3 | 🟡 P1 | Observability | Document Sentry alert rule: "P99 `/api/public/status` latency > 10 s for 2 min" — until #2 ships, this is our only signal for uvicorn-pool exhaustion. | ⏳ Now redundant with #2 above, but still worth keeping as a belt-and-braces alert. |
| 4 | 🟢 P2 | Capacity | Resolve the `--workers 1` Emergent Support ticket; with 2 workers we get 60 sessions of pool headroom. | ⏳ Waiting on Emergent Support |
| 5 | 🟢 P2 | Redundancy | Provision a standby Redis (Upstash or self-hosted) so item #1 isn't the only safety net. | 📋 Backlog |
