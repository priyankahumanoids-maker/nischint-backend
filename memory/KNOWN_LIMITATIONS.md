# Known Limitations

Living register of accepted production limitations that are NOT bugs and
should NOT be auto-paged. Each entry documents the limitation, its
blast radius, the workaround in place, and the proposed long-term fix.

---

## KL-001 — NDMA SACHET feed: Indian-IP allow-list — ✅ CLOSED (REL-07)

**Status**: Code-complete. Closes once the Cloudflare Worker is deployed
**and** `SACHET_PROXY_URL` is set on the production backend pod.

**Fix shipped**: REL-07 — `deploy/cloudflare-workers/sachet-proxy/`.
A Cloudflare Worker proxies HTTPS requests to `sachet.ndma.gov.in`
through a CF Indian colo (typically `BOM` Mumbai) which is **not**
blocked by NDMA's country-of-origin allow-list. `sachet_provider.py`
reads `SACHET_PROXY_URL` per-request via `effective_url()` — when
set, all NDMA calls route through the Worker; when unset the code
falls back to direct upstream (pre-REL-07 behaviour, unchanged).

**Deploy steps**:
1. `cd deploy/cloudflare-workers/sachet-proxy && npx wrangler deploy`
2. Copy the printed `https://sachet-proxy.<your-sub>.workers.dev`
3. Set `SACHET_PROXY_URL=<that URL>` on the backend pod
4. No code redeploy needed — the env var is read at request time.

**Verification**:
- `curl <SACHET_PROXY_URL>/cap_public_website/_proxy_health` →
  `{"ok": true, "upstream": "sachet.ndma.gov.in", "colo": "BOM", ...}`.
- Operator dashboard SACHET tile flips from `degraded` → `healthy`
  on the next prewarmer tick.

**Rollback**: Unset `SACHET_PROXY_URL` on the pod (no redeploy),
or `npx wrangler delete --name sachet-proxy`. The provider drops
back to direct upstream — same behaviour as before this fix.

---

## KL-001 — NDMA SACHET feed: Indian-IP allow-list (historical) 🗄️

(Kept for context — the original limitation that REL-07 closes.)

**Component**: `app/services/external_signals/sachet_provider.py`,
`app/services/external_signals/sachet_prewarmer.py`

**Symptom**: ~100 % failure rate on `https://sachet.ndma.gov.in/cap_public_website/rss/rss_india.xml`
from the Emergent production backend (us-east-1 egress). Same URL
returns HTTP 200 from machines with an Indian-origin IP.

**Root cause**: NDMA enforces a country-of-origin allow-list at the
origin server. The Emergent IaaS egress range is not whitelisted, and
NDMA does not publish a self-serve allow-listing process.

**Blast radius**: **None — functional**. SF-02 PostGIS env hazard
scoring is the primary signal and runs independently. NDMA is *additive
only* — when reachable it contributes a 0.30 – 0.95 severity bump via
`apply_external_modifiers`; when blocked, the registry's
cache-preservation invariant + hysteresis settles the prewarmer into
`degraded` and emits no false alerts.

**Operational impact**: The operator dashboard's SACHET tile shows
`degraded` on production. This is **expected** and **should not page**
on-call. The state mirrors to
`system_health_history.KNOWN_SOURCES["sachet_health"]` and is replayed
on SSE reconnect.

**Workaround (current)**: None — fail-quiet by design. PostGIS env
hazard scoring covers the gap.

**Long-term remediation (ranked)**:
1. **Mumbai-region egress proxy** — lightweight HTTPS pass-through on
   the Supabase Mumbai instance. Lowest latency, no extra vendor.
2. **Cloudflare Worker** routed via a Mumbai colo, fronting the RSS
   URL. Single-file deploy, but adds CF Workers to the bill of
   materials.
3. **NDMA allow-list petition** — official ask via the NDMA
   data-partnerships desk. Highest leverage, slowest timeline.

**On-call playbook**:
- If SACHET is `degraded` on production → **do nothing**. Verify state
  history in `/api/admin/sachet-prewarmer` shows continuous failures
  rather than intermittent ones (intermittent = network blip, not
  IP-block).
- If SACHET is `degraded` in preview / from a Mumbai machine → real
  outage, escalate.

**Last verified**: Feb 2026.

---
