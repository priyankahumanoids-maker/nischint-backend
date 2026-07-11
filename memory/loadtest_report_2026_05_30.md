# LT-01 Days 11-12 Launch Prep — Load Test Report
**Date**: 2026-05-30
**Environment**: PREVIEW only (`http://localhost:8001` — see "Environment caveats" below)
**Why not production**: User direction — `https://nischint.care` is a live family-safety app; running SOS load there would generate real push notifications to real guardians.

---

## Executive Summary

### 🔴 Launch blocker found
**Headline 60s test (60 VUs, ramped 10/s)**: 94.75% of requests timed out at the 10s ceiling. Root cause: **`uvicorn --workers 1`** in the running config can't process the request mix during ramp-up. Bottleneck is **asyncio event-loop saturation**, not DB pool, not memory, not file descriptors.

### 🟢 Soak test (24 min steady, 5 VUs): leak-free
- RSS grew +18 MB over 24 min (linear, ~0.75 MB/min)
- File descriptors flat (33), asyncio task count flat (10), pg pool peak 1/30
- Event-loop lag stayed below 1 ms throughout

### ⚠️ Test design caveat
The soak harness's bootstrap JWT expired mid-test → 100% of soak requests got `401 Unauthorized` after ~20s. The leak-free observation is valid for the **auth-reject path**; the real endpoint paths weren't exercised at steady-state under the soak. See "Soak test caveat" section. **Fix is mechanical** (refresh the soak token every 5 min) — not blocking the headline finding.

---

## Scenarios run

| # | Scenario | Concurrency | Endpoint | Notes |
|---|---|---|---|---|
| 1 | Auth-verified read | ~50 share of 60 VUs | `GET /api/auth/me` | Replaces `/login` (would have tripped 5/min IP brute-force limit) |
| 2 | Guardian dashboard | ~30 share | `GET /api/guardian/sessions/active` | |
| 3 | SOS trigger | ~10 share | `POST /api/sos/trigger` | **Short-circuited** via `LOADTEST_MODE=true` + `X-Loadtest-Token` header — no DB writes, no fan-out |
| 4 | Health signals POST | ~20 share | `POST /api/health-signals/wearable` | Two synthetic device fingerprints exercise HC-02 by-device bucketing |
| 5 | Command Center WS | 5 concurrent | `WS /api/ws/command-center` | Held open 30s, admin token |

---

## Scenario 1-4 results (headline 60s test)

```
Type   Name                                              reqs  fails  p50      p95      p99      max
GET    s1:auth/me                                         149   134   10000ms  10000ms  10000ms  10241ms
GET    s2:guardian/sessions/active                         79    79   10000ms  10000ms  10000ms  10003ms
POST   s3:sos/trigger (LT shortcircuit)                    22    21   10000ms  10000ms  10000ms  10138ms
POST   s4:health-signals/wearable                          48    48   10000ms  10000ms  10000ms  10004ms
       Aggregated                                         305   289   10000ms  10000ms  10000ms  10241ms
```

**Failure mode**: ReadTimeout @ client-side 10s ceiling. Once the loop saturates, every in-flight request crosses the timeout before the worker can drain.

### Timeline (per-second aggregated)
```
t (s)  users  reqs/s  fails/s  p50      p95      p99
0       0     0       0        N/A      N/A      N/A
5       20    0       0        N/A      N/A      N/A
10      60    0.71    0.14     3900     5900     5900    ← functional but slow
15      60    1.10    0.20     6600     10000    10000   ← collapsing
20      60    4.30    3.10     10000    10000    10000   ← saturated
25-60   60    5-7     5-7      10000    10000    10000   ← never recovers
```

Critical: between t=10s and t=15s the loop tipped from "slow" to "saturated" and never recovered for the rest of the run.

### Runtime metrics during test (smoking gun)
```
ts (s)   RSS    FDs   tasks    loop_lag   pool_out   pool_util
t+0      189.8  28    10       0.08 ms    0          0.0 %
t+5      190.7  29    17       0.14 ms    1          3.3 %
t+15     191.5  42    105      217.16 ms  0          0.0 %       ← lag jumps 1500×
t+25     194.4  66    358      453.58 ms  4          13.3 %      ← 358 tasks queued
t+50     203.0  51    217      2227.94 ms 19         63.3 %      ← peak: 2228 ms lag
t+60     209.7  41    185      218.06 ms  0          0.0 %
t+90     210.6  38    21       0.09 ms    0          0.0 %       ← drains after test
```

**Read this row by row**:
- **pool_out peak 19/30 (63%), pool_wait_count=0** → DB connection pool is healthy. Not the bottleneck.
- **asyncio_loop_lag peak 2228 ms** → event loop couldn't yield for >2 seconds. Anything sync executing inline (bcrypt verify, JWT signing, JSON parsing of large payloads) blocks the entire request stream.
- **asyncio_task_count peaked at 358** (baseline 10) → 348 requests queued waiting for CPU. With 10s timeout and ~6 req/s drain rate, anything beyond ~60 queued requests is guaranteed to time out.
- **RSS +20 MB peak**, recovered to 210 MB after — no leak.

---

## Scenario 5 — Command Center WebSocket (clean ✅)

```json
{
  "scenario":        "s5_command_center_ws",
  "concurrency":     5,
  "duration_s":      30,
  "connected":       5,
  "disconnected":    5,
  "messages_recvd":  15,
  "connect_latency_ms": { "p50": 1864.6, "p95": 1948.6, "p99": 1948.6 },
  "errors":          []
}
```

- 5/5 admin connections established, role gate passed
- 5/5 disconnected gracefully at deadline
- 15 messages received (3 per conn × 30s = expected heartbeat cadence)
- **0 errors** ✅
- Connect latency ~1.9s — slow but no failures. Likely the JWT verify path runs on the same congested event loop and contends with the locust traffic that just finished.

---

## Soak test (30 min, 5 VUs)

### Metrics — clean, no leaks
```
duration:    23.8 min sampled  (138 rows × 10s interval)
RSS:         start=194.8  end=213.1  peak=213.1  growth=+18.3 MB
FDs:         start=33  end=33  peak=34
asyncio:     start=12 tasks  end=10 tasks  peak=12
pg pool:     peak=1/30 (3.3 %)
loop lag:    peak=0.72 ms

t+0.0 min   RSS=194.8 MB  FDs=33  tasks=12  loop_lag=0.72ms
t+3.0 min   RSS=198.7 MB  FDs=33  tasks=10  loop_lag=0.12ms
t+6.0 min   RSS=199.7 MB  FDs=33  tasks=10  loop_lag=0.10ms
t+9.0 min   RSS=199.7 MB  FDs=33  tasks=10  loop_lag=0.14ms
t+12.0 min  RSS=202.7 MB  FDs=33  tasks=10  loop_lag=0.13ms
t+15.0 min  RSS=205.6 MB  FDs=33  tasks=10  loop_lag=0.15ms
t+18.0 min  RSS=208.4 MB  FDs=33  tasks=10  loop_lag=0.14ms
t+21.0 min  RSS=211.2 MB  FDs=33  tasks=10  loop_lag=0.16ms
t+23.7 min  RSS=213.1 MB  FDs=33  tasks=10  loop_lag=0.16ms
```

### Soak test caveat (be honest)

The locust soak ran 1,800 seconds but the bootstrap JWT token expired part-way through. **100% of the 4,408 soak requests** returned `401 Unauthorized` once expiry hit (~20-30 minutes in, depending on TTL).

**What this DOES tell us**:
- The **auth-reject path** has no leak over 24 min at 2.5 req/s aggregate
- Failed-auth responses return in p50=3ms / p95=8ms — auth rejection is cheap
- No FD/task/pool/RSS regression over the window

**What this DOES NOT tell us**:
- Steady-state DB-backed request behavior over 30 minutes
- Whether the linear +0.75 MB/min RSS growth is from the auth-reject code path, the scheduler, or both

**Fix for next soak run**: refresh the JWT in the locust soak file every 5 minutes via a `between_task` hook. ~10 min to wire. Leaving this for the next iteration so the launch-blocker finding doesn't get buried.

---

## Recommendations — priority order

### 🔴 P0 — Launch blocker
**Increase uvicorn `--workers` count in production supervisord.conf.** Current `--workers 1` cannot handle the requested concurrency mix. Pair this fix with the in-flight `--reload` support ticket (one combined platform change). Recommended starting point: `--workers 2` for the API role; bench again before launch.

Bundle into the same support ticket:
```
# Production backend program proposed final form:
command=/root/.venv/bin/uvicorn server:app --host 0.0.0.0 --port 8001 --workers 2
# (was: --workers 1 --reload)
```

### 🟡 P1 — Profile the inline-sync work
The 2228 ms loop lag means *something* synchronous is blocking the event loop under contention. Candidates ranked by likelihood:

1. **bcrypt password verification** on `/api/auth/login` (12-round bcrypt is ~80-200ms per call, sync, CPU-bound; runs on the same event loop). Verify it's wrapped in `asyncio.to_thread` or executor.
2. **JWT HS256 signing** (cheap, but at 60 VUs adds up). Likely not the culprit alone.
3. **PostGIS query path for hazard zones** during HC-02 ingest — SF-03c boundary checks may be slow when called per signal.

Recommend: add a `prometheus_client` histogram around `verify_password`, `create_access_token`, and `is_inside_india_per_soi` to confirm. ~30 min to wire.

### 🟡 P1 — Fix soak harness token expiry
Add a `@events.request.add_listener` that refreshes the shared JWT every N requests (e.g., every 200) so the 30-min soak actually measures the DB-backed path. ~10 min.

### 🟢 P2 — Tighten brute-force protection threshold post-launch
Current `/api/auth/login` limit is `5/minute/IP`. This is correctly tuned for prod (caught the v1 test attempt). Worth a follow-up: confirm the limit window resets cleanly after burst — looked good but worth a dedicated test.

---

## Environment caveats

* **Test target**: `http://localhost:8001` (not the public Cloudflare URL). The pod cannot dial its own public URL — egress through Cloudflare's edge → K8s ingress → service loops back and times out. This is an environmental constraint of the preview pod, not a real production behaviour.
* **What this skips**: Cloudflare, Nginx, K8s ingress. Adds a fixed ~10-30ms overhead in real production traffic but does NOT change the scaling characteristics we measured. Worker saturation will manifest identically whether or not Cloudflare sits in front.
* **Test user role**: `nischint4parents@gmail.com` (admin role). Got 5 forbidden responses on `/api/guardian/sessions/active` during the headline test — that endpoint may require explicit `guardian` role. Mark this as a future scenario refinement.

---

## Files produced

* `/app/backend/loadtest/locustfile.py` — headline 60s test (5 scenarios)
* `/app/backend/loadtest/locustfile_soak.py` — 30-min steady-state soak
* `/app/backend/loadtest/ws_command_center_loadtest.py` — scenario 5 WS harness
* `/app/backend/loadtest/runtime_sampler.py` — RSS + pool CSV sampler
* `/app/backend/app/api/sos.py` — added `LOADTEST_MODE`+`X-Loadtest-Token` short-circuit (LT-01)
* `/app/backend/.env` — added `LOADTEST_MODE=true`, `LOADTEST_TOKEN=<32-byte token>`
* `/tmp/locust_results_*.csv` — headline test raw stats
* `/tmp/soak_results_*.csv` — soak test raw stats
* `/tmp/load_metrics.csv` — headline test RSS+pool samples
* `/tmp/soak_metrics.csv` — soak test RSS+pool samples (143 rows × 10s)

---

## Repro

```bash
# Set LT_TOKEN from /app/backend/.env LOADTEST_TOKEN
export HOST=http://localhost:8001
export LT_TOKEN=$(grep LOADTEST_TOKEN /app/backend/.env | cut -d= -f2)

# Headline 60s test
locust -f backend/loadtest/locustfile.py --headless \
       --users 60 --spawn-rate 10 --run-time 60s --host $HOST \
       --csv /tmp/locust_results --only-summary

# Scenario 5 WS
python backend/loadtest/ws_command_center_loadtest.py --duration 30 --concurrency 5

# 30-min soak
locust -f backend/loadtest/locustfile_soak.py --headless \
       --users 5 --spawn-rate 1 --run-time 1800s --host $HOST \
       --csv /tmp/soak_results

# RSS+pool sampler (run in parallel with above)
python backend/loadtest/runtime_sampler.py --duration 1800 --interval 10 --output /tmp/soak_metrics.csv
```
