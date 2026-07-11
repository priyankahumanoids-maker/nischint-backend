# Nischint — Production Rollout Runbook

> **Audience**: anyone with prod access (founder, on-call, SRE).
> **Purpose**: lock production signal in **<15 min** with **zero ambiguity**, then run a 24h soak before any feature flag escalation.
> **Source of truth**: this file + `/app/scripts/verify_prod.sh`.

---

## 🟢 Part 1 — Lock Production Signal (the only thing that matters today)

### Pre-flight (1 min)

You'll need:
- Production environment access (Emergent dashboard or your deploy console).
- A Slack workspace where you (or your on-call) can receive alerts.
- The Twilio Auth Token already set in production (already done — we validated this in preview).

### Step 1 — Create a Slack incoming webhook (3 min)

1. Open https://api.slack.com/apps → **Create New App** → **From scratch**.
2. Name: `Nischint Ops`, pick the workspace where you want alerts.
3. Left sidebar → **Incoming Webhooks** → toggle ON.
4. Click **Add New Webhook to Workspace** → pick a channel (e.g. `#nischint-ops`).
5. Copy the URL. It looks like `https://hooks.slack.com/services/T.../B.../...`.
6. Test it once from your terminal:
   ```bash
   curl -X POST -H 'Content-Type: application/json' \
     --data '{"text":"Nischint webhook test — ignore."}' \
     https://hooks.slack.com/services/T.../B.../...
   ```
   You should see the message in the channel within 1–2 seconds.

> **Don't have Slack?** Use Discord — same body works. Get a webhook from a Discord channel → ⚙️ → Integrations → Webhooks → Copy URL. Set it as `OPS_DISCORD_WEBHOOK_URL` instead.

### Step 2 — Add 4 env vars to **production** `.env` (3 min)

```bash
# Phase 1 V2 flag — voice-distress alerts via the unified front door.
ALERT_TRIGGER_V2_VOICE_DISTRESS=true

# Slack webhook for ops alerts (heartbeat, SLA transitions, twilio auth fails).
OPS_SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T.../B.../...
# OR (instead of Slack):
# OPS_DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/.../...

# Tag every ops alert as "prod" so you don't confuse preview ↔ prod messages.
ENV=prod
```

> **DO NOT touch** any of: `DATABASE_URL`, `MONGO_URL`, `REDIS_URL`, `TWILIO_*`, `JWT_SECRET`. Those stay exactly as they are.

### Step 3 — Redeploy production (1 min)

Push the env-var change through your usual deploy flow. The backend will restart with the new flags loaded.

### Step 4 — Run the verification script (3 min)

From any machine with `curl` + `python3`:

```bash
PROD_URL=https://nischint.care \
ADMIN_EMAIL=nischint4parents@gmail.com \
ADMIN_PASSWORD=secret123 \
bash /app/scripts/verify_prod.sh
```

Expected output (all rows ✅):
```
[1/7] Backend health         ✅
[2/7] Admin auth             ✅
[3/7] Twilio auth_ok         ✅
[4/7] SLA verdict             ✅ status=green
[5/7] Voice-distress flag     ✅ ALERT_TRIGGER_V2_VOICE_DISTRESS=true
[6/7] Slack webhook            ✅ test message dispatched
[7/7] Heartbeat job alive     ✅ last heartbeat <5min ago

✅ PRODUCTION LOCKED — 24h soak begins now.
```

If any row is ❌ → **DO NOT proceed**. Fix that one thing, re-run the script.

---

## 🟡 Part 2 — 24h Soak (non-negotiable)

### What to watch (3 things, nothing else)

1. **Heartbeat every 5 min** in Slack (or `[OPS_ALERT] level=info kind=heartbeat` in logs).
2. **Zero `sla_transition` alerts** (no green→amber/red events).
3. **TTFA values stable** — pull `/api/_dev/twilio/sla?since=3600` 2–3 times across the day; `sms_p95` and `voice_p95` shouldn't creep up.

### What to do if something fires

| Slack message | What it means | Action |
|---|---|---|
| `:bell: heartbeat` every 5 min | Healthy | None — that's the goal |
| **No heartbeat for >10 min** | Scheduler process died | `sudo supervisorctl restart nischint-scheduler` (or your prod equivalent) |
| `:warning: sla_transition green → amber` | One leg slow but recoverable | Wait 60s, watch for the recovery ping |
| `:rotating_light: sla_transition green → red` | Critical — SOS may not deliver | Read the `Last 10 TTFA events` block in the message. The `❌ twilio:*` rows tell you exactly which leg failed. Then: `curl /api/_dev/twilio/health` to check if it's auth or latency. |
| `:rotating_light: twilio_auth` | Credentials rotated/invalid | Re-check production `TWILIO_AUTH_TOKEN`. **STOP — don't flip Phase 2/3 until resolved.** |
| `:warning: twilio_give_up` | One specific delivery exhausted retries | Note which `kind=` (sms/voice). One-off failures are tolerable; pattern across 1h is not. |

### Quick mid-soak health pull

```bash
ADMIN_TOKEN=$(curl -s -X POST $PROD_URL/api/auth/login \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$ADMIN_EMAIL\",\"password\":\"$ADMIN_PASSWORD\"}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin).get('token') or json.load(sys.stdin).get('access_token'))")

# All-in-one snapshot
curl -s "$PROD_URL/api/_dev/twilio/sla?since=3600" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | python3 -m json.tool

# What dispatched in the last hour?
curl -s "$PROD_URL/api/_dev/ttfa/recent?n=20" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | python3 -m json.tool
```

---

## 🟢 Part 3 — Phase 2 & 3 Activation (only after a clean 24h soak)

### Phase 2 (T+24h, if soak was clean)

Add to production `.env`:
```bash
ALERT_TRIGGER_V2_HELP_REQUEST=true
```
Redeploy. Re-run `verify_prod.sh`. Soak another 24h.

### Phase 3 (T+48h, only if Phase 2 was clean)

```bash
ALERT_TRIGGER_V2_SOS=true
```
Redeploy. Re-run `verify_prod.sh`. **This one carries real-world blast radius — every SOS now flows through the unified pipeline.** Watch Slack for the next 6h closely.

---

## 🔴 Rollback (any phase, any time)

If you see sustained `sla_transition red` or `twilio_auth` failures, instantly disable the most recent flag:

```bash
# Whichever you flipped most recently — set it to false:
ALERT_TRIGGER_V2_VOICE_DISTRESS=false   # or HELP_REQUEST / SOS
```
Redeploy. The legacy code path immediately takes over. **No data loss** — both paths write to the same `guardian_alerts` table. The flag is the only switch.

> **Important**: the legacy paths are unchanged from before this session. Rollback is byte-identical to the system you were running 48h ago.

---

## 📞 If you can't fix it in 15 min

1. Roll back the most recent flag (above).
2. Note exact Slack message + timestamp.
3. Contact Emergent Support if the issue is environmental (credentials, deploy infra, domain config) — they have prod console access.
4. Otherwise: open the next session in this codebase, paste the Slack message, and the agent will pick up from this runbook.

---

## ✅ Done

When all 3 phases are flipped + a clean 24h after Phase 3 → **production rollout is complete**. We're ready to start Sprint 2 (NISCH-006 lifecycle + event timelines).

Until then: **don't ship features**. Earn the trust.
