# SACHET Proxy — Cloudflare Worker (REL-07)

Closes [KL-001](../../../memory/KNOWN_LIMITATIONS.md#kl-001--ndma-sachet-feed-indian-ip-allow-list)
by routing the NDMA SACHET RSS/JSON requests through a Cloudflare
Worker that egresses from an Indian colo (which NDMA does *not*
block).

## What it does

```
backend  ──HTTPS──▶  Cloudflare Worker (auto-colo)  ──HTTPS──▶  sachet.ndma.gov.in
```

The Worker is a **strict pass-through** for `GET` / `HEAD` requests
under the `/cap_public_website/` path namespace only. Everything else
returns `404` / `405`. Open-relay defense.

## Deploy

```bash
cd deploy/cloudflare-workers/sachet-proxy
npm install              # installs wrangler locally
npx wrangler login       # one-time per machine — auths via CF account
npx wrangler deploy
```

After `wrangler deploy` succeeds you'll see something like:

```
Uploaded sachet-proxy (1.2 sec)
Published sachet-proxy (0.6 sec)
   https://sachet-proxy.<your-sub>.workers.dev
```

Copy that URL — that's your **`SACHET_PROXY_URL`**.

## Wire to the backend

Set the env on the Emergent backend pod (Profile → Env or platform
console):

```
SACHET_PROXY_URL=https://sachet-proxy.<your-sub>.workers.dev
```

Restart the backend; `sachet_provider.py` reads the var on every
request and rewrites the upstream host transparently. **No code
deploy is required** — the var is read at request time.

## Verify

```bash
curl -s https://sachet-proxy.<your-sub>.workers.dev/cap_public_website/_proxy_health | jq .
# {
#   "ok": true,
#   "upstream": "sachet.ndma.gov.in",
#   "colo": "BOM",
#   "timestamp": "2026-02-..."
# }
```

`"colo": "BOM"` confirms the request egressed from Mumbai. (Other
Indian colos — `MAA` Chennai, `HYD` Hyderabad, `DEL` Delhi — are
also unblocked by NDMA.)

End-to-end smoke:

```bash
curl -sI https://sachet-proxy.<your-sub>.workers.dev/cap_public_website/rss/rss_india.xml | head
# HTTP/2 200
# content-type: application/rss+xml
# x-sachet-proxy-colo: BOM
# ...
```

## Rollback

Either of:

- Unset `SACHET_PROXY_URL` on the backend — code falls back to
  `https://sachet.ndma.gov.in` directly (same behaviour as before
  REL-07).
- `npx wrangler delete --name sachet-proxy` to fully tear down.

## Headers

| Direction | What we forward                                                |
|-----------|----------------------------------------------------------------|
| Request   | `accept`, `accept-encoding`, `accept-language`, `if-modified-since`, `if-none-match` |
| Request   | Pinned `user-agent: nischint-sachet-proxy/1.0 (+https://nischint.care)` |
| Response  | `content-type`, `content-length`, `cache-control`, `etag`, `last-modified`, `expires` |
| Response  | CORS headers (`*` origin), plus `x-sachet-proxy-colo` diagnostic |

All other request headers are dropped before hitting NDMA — keeps
the request shape consistent across our worldwide eyeball traffic.

## Limits & cost

- CF Workers free tier: 100k requests/day, 10 ms CPU/request.
- Our backend hits NDMA at ~1 request / 5 minutes (Redis-cached on
  the backend side) ≈ 288 requests/day. Well within free tier.
- If usage spikes, the paid plan starts at $5/month for 10M requests
  — still trivial.
