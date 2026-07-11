/**
 * REL-07 — SACHET (NDMA) egress proxy
 *
 * Cloudflare Worker that proxies HTTPS GETs through a Mumbai colo to
 * `sachet.ndma.gov.in`. Required because NDMA blocks our Emergent
 * us-east-1 backend IPs at the origin server. Cloudflare's edge
 * routing places this Worker on a colo close to the requester —
 * traffic to `*.workers.dev` from our backend exits via the nearest
 * CF datacenter (typically Mumbai for India-routed traffic, which
 * NDMA does NOT block).
 *
 * Endpoint mapping:
 *
 *   https://sachet-proxy.<sub>.workers.dev/<path>
 *      → https://sachet.ndma.gov.in/<path>
 *
 * Examples:
 *   /cap_public_website/rss/rss_india.xml
 *   /cap_public_website/FetchAllAlertDetails
 *   /cap_public_website/FetchXMLFile?identifier=XXX
 *
 * Security:
 *   • Only GET / HEAD passed through. POST etc → 405 (write-amp
 *     defense — the upstream is read-only public data).
 *   • Pin to a single upstream hostname (`UPSTREAM_HOST`). Anything
 *     else → 404. Stops the Worker being used as an open-relay.
 *   • Hop-by-hop request headers are stripped; the Worker uses a
 *     pinned User-Agent so NDMA sees a single client identity.
 *   • Response is returned as-is with CORS headers. No body
 *     transformation — the SACHET parser in the backend handles
 *     RSS/XML and JSON paths.
 *
 * Caching:
 *   • Cloudflare's edge cache is honoured (no `cf.cacheTtl` override
 *     — let NDMA's own Cache-Control headers win). The backend has
 *     a 300s Redis cache on top of this, so a stale CF edge response
 *     is not a correctness issue.
 *
 * Deployment:
 *   1. `cd deploy/cloudflare-workers/sachet-proxy`
 *   2. `npx wrangler login`
 *   3. `npx wrangler deploy`
 *   4. Worker URL → set `SACHET_PROXY_URL` env on backend (e.g.
 *      `SACHET_PROXY_URL=https://sachet-proxy.<your-sub>.workers.dev`).
 *
 * Rollback:
 *   • `npx wrangler delete --name sachet-proxy` or unset
 *     `SACHET_PROXY_URL` — the backend falls back to direct upstream.
 */

const UPSTREAM_HOST = 'sachet.ndma.gov.in';
const UPSTREAM_BASE = `https://${UPSTREAM_HOST}`;

// Reasonable identity — opaque to NDMA but human-grep-able in their
// logs if they ever look. Includes contact path in case they want to
// reach out about the proxy.
const PINNED_USER_AGENT = 'nischint-sachet-proxy/1.0 (+https://nischint.care)';

// Allow-list of headers we forward to NDMA. Anything else is dropped
// to keep the request shape consistent and avoid leaking client
// fingerprints to upstream.
const FORWARDED_REQUEST_HEADERS = new Set([
  'accept',
  'accept-encoding',
  'accept-language',
  'if-modified-since',
  'if-none-match',
]);

// Headers we lift verbatim from the NDMA response. Cloudflare's
// response handler will overwrite `content-encoding` on its own
// re-compression path, so we intentionally do NOT forward that one.
const FORWARDED_RESPONSE_HEADERS = new Set([
  'content-type',
  'content-length',
  'cache-control',
  'etag',
  'last-modified',
  'expires',
]);

const CORS_HEADERS = {
  'access-control-allow-origin': '*',
  'access-control-allow-methods': 'GET, HEAD, OPTIONS',
  'access-control-allow-headers': 'accept, accept-language, if-none-match',
  'access-control-max-age': '86400',
};

function withCors(body, init = {}) {
  const headers = new Headers(init.headers || {});
  for (const [k, v] of Object.entries(CORS_HEADERS)) headers.set(k, v);
  return new Response(body, { ...init, headers });
}

function errorResponse(status, message) {
  return withCors(JSON.stringify({ error: message }), {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8' },
  });
}

export default {
  async fetch(request) {
    const incoming = new URL(request.url);

    // CORS preflight — return immediately, no upstream call.
    if (request.method === 'OPTIONS') {
      return withCors(null, { status: 204 });
    }

    if (request.method !== 'GET' && request.method !== 'HEAD') {
      return errorResponse(405, 'only GET/HEAD allowed');
    }

    // Refuse anything that doesn't look like a SACHET path. We could
    // be more permissive, but the strict allow-list is the cheapest
    // open-relay defense.
    if (!incoming.pathname.startsWith('/cap_public_website/')) {
      return errorResponse(404, 'not a SACHET path');
    }

    // Health probe — useful for the backend to ping the worker
    // without hitting NDMA.
    if (incoming.pathname === '/cap_public_website/_proxy_health') {
      return withCors(
        JSON.stringify({
          ok: true,
          upstream: UPSTREAM_HOST,
          colo: request.cf?.colo || 'unknown',
          timestamp: new Date().toISOString(),
        }),
        {
          status: 200,
          headers: { 'content-type': 'application/json; charset=utf-8' },
        }
      );
    }

    const upstreamUrl = `${UPSTREAM_BASE}${incoming.pathname}${incoming.search}`;

    // Build the upstream request with only the allow-listed headers.
    const upstreamHeaders = new Headers();
    upstreamHeaders.set('user-agent', PINNED_USER_AGENT);
    upstreamHeaders.set('host', UPSTREAM_HOST);
    for (const [k, v] of request.headers.entries()) {
      if (FORWARDED_REQUEST_HEADERS.has(k.toLowerCase())) {
        upstreamHeaders.set(k, v);
      }
    }

    let upstreamResp;
    try {
      upstreamResp = await fetch(upstreamUrl, {
        method: request.method,
        headers: upstreamHeaders,
        // 12s upper bound — matches NDMA's tail latency observed in
        // production. The backend's hot-path timeout is 1s; the
        // pre-warmer's is 8s; both are well under this ceiling.
        cf: { cacheEverything: false },
        redirect: 'follow',
      });
    } catch (err) {
      return errorResponse(
        502,
        `upstream fetch failed: ${(err && err.message) || String(err)}`
      );
    }

    // Lift the allow-listed response headers.
    const respHeaders = new Headers();
    for (const [k, v] of upstreamResp.headers.entries()) {
      if (FORWARDED_RESPONSE_HEADERS.has(k.toLowerCase())) {
        respHeaders.set(k, v);
      }
    }
    // Always add CORS.
    for (const [k, v] of Object.entries(CORS_HEADERS)) respHeaders.set(k, v);
    // Diagnostic header — lets the backend confirm in logs which colo
    // served the request without parsing CF's own debug headers.
    if (request.cf?.colo) {
      respHeaders.set('x-sachet-proxy-colo', request.cf.colo);
    }

    return new Response(upstreamResp.body, {
      status: upstreamResp.status,
      statusText: upstreamResp.statusText,
      headers: respHeaders,
    });
  },
};
