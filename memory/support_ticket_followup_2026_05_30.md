# Follow-up — Production `backend` supervisord `--workers 2` ticket

**For user to send via the Emergent platform support channel.**

> Before sending, replace `<ORIGINAL_TICKET_ID>` and `<N>` below with
> the real ticket ID and the actual number of days since you filed
> the original ticket. The original ticket draft is at
> `/app/memory/support_ticket_reload_flag.md`.

---

## Subject

Follow-up: Production `backend` supervisord — `--workers 2` change (ref ticket #`<ORIGINAL_TICKET_ID>`)

## Body

Hi Emergent team,

Quick nudge on the ticket I filed `<N>` days ago asking for two changes
to the production `backend` program in
`/etc/supervisor/conf.d/supervisord.conf`:

1. Drop the `--reload` flag (still causing intermittent 520s every
   time `WatchFiles` triggers a worker restart on a routine file
   write).
2. Bump `--workers 1` → `--workers 2` (a re-confirmed load test today
   still shows ~95 % timeouts at 60 concurrent users with the current
   single-worker config).

Since I filed the ticket, we've shipped a number of reliability fixes
on our side that **partially** compensate but don't replace the
supervisord change:

- bcrypt offloaded to a thread pool (`asyncio.to_thread`) — frees the
  event loop on auth, but the single-worker bottleneck still caps
  throughput.
- `slowapi` rate-limiter now has a memory fallback so auth doesn't 500
  during Redis blips.
- `db_pool_monitor` now aggregates uvicorn-process pool stats so we
  can actually *see* the saturation we're caught in.
- Disaster-recovery drill on 2026-05-30 confirmed the API survives
  Redis outages and the public `/status` page is rock-solid — but
  the underlying worker-count gap is the one thing we genuinely
  cannot fix from our side.

Could you confirm:

1. Whether the change is queued / blocked on anything from us, or
2. If it's been deprioritized, what the expected window looks like.

We have App Store submission pegged to this fix — if there's an
estimated landing date even a few weeks out, that lets us plan
downstream comms. If it's faster to fix via a different channel
(e.g. a customer-overridable supervisor include file), I'm happy to
switch approach.

Full original detail is in the original ticket; happy to re-share the
load-test artefacts (`/app/memory/loadtest_report_2026_05_30.md`) if
useful.

Thanks for the help.

— Meta

---

## Filesystem evidence at follow-up time

For your own records, current state of the config the ticket asks to
edit (verified 2026-05-30):

```
$ grep -A 3 "program:backend\]" /etc/supervisor/conf.d/supervisord.conf
[program:backend]
command=/root/.venv/bin/uvicorn server:app --host 0.0.0.0 --port 8001 --workers 1 --reload
directory=/app/backend
autostart=true
```

```
$ stat /etc/supervisor/conf.d/supervisord.conf | grep Modify
Modify: 2026-05-30 14:14:16.749547111 +0000
```

Both problem flags (`--workers 1` AND `--reload`) still present;
no platform-side edit observed in the window since the original
ticket was filed.
