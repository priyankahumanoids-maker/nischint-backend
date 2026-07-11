/**
 * Funnel Tracker — Lightweight conversion tracking for SEO pages.
 * Tracks: page_view → cta_click → modal_open → lead_submit → whatsapp_redirect
 * Dual: sends to backend API + PostHog (if configured)
 */
import posthog from 'posthog-js';

// Same-origin relative paths — works on any domain without CORS / stale-bundle issues.
const API_BASE = '';
const SESSION_KEY = 'nischint_funnel_sid';

// PostHog is initialised inline in `public/index.html` (source of
// truth — uses the production project key). Lighthouse audit on
// 2026-05-30 caught us double-initialising here with a STALE `.env`
// key that triggered cascading 401/404s on every page load.
// We no longer re-init; just call `posthog.capture()` if the global
// SDK is loaded. Init-elsewhere is the explicit contract.
const PH_READY = () => {
  try {
    return typeof window !== 'undefined' && window.posthog && typeof window.posthog.capture === 'function';
  } catch (_) {
    return false;
  }
};

function getSessionId() {
  let sid = localStorage.getItem(SESSION_KEY);
  if (!sid) {
    sid = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    localStorage.setItem(SESSION_KEY, sid);
  }
  return sid;
}

const queue = [];
let flushTimer = null;

function phCapture(event, page) {
  if (PH_READY()) {
    try { posthog.capture(event, { page, session_id: getSessionId() }); } catch (_) {}
  }
}

function enqueue(event, page) {
  queue.push({ event, page: page || null, session_id: getSessionId(), timestamp: Date.now() });
  phCapture(event, page);
  if (flushTimer) clearTimeout(flushTimer);
  flushTimer = setTimeout(flush, 300);
}

async function flush() {
  if (queue.length === 0) return;
  const batch = queue.splice(0);
  try {
    const ctrl = new AbortController();
    setTimeout(() => ctrl.abort(), 3000);
    await fetch(`${API_BASE}/api/track/batch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ events: batch }),
      signal: ctrl.signal,
      keepalive: true,
    });
  } catch (_) {}
}

function fireNow(event, page) {
  phCapture(event, page);
  const payload = { event, page: page || null, session_id: getSessionId(), timestamp: Date.now() };
  try {
    navigator.sendBeacon?.(
      `${API_BASE}/api/track`,
      new Blob([JSON.stringify(payload)], { type: 'application/json' })
    ) || fetch(`${API_BASE}/api/track`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      keepalive: true,
    });
  } catch (_) {}
}

export const funnel = {
  pageView: (page) => enqueue('page_view', page),
  ctaClick: (page) => enqueue('cta_click', page),
  modalOpen: (page) => enqueue('modal_open', page),
  leadSubmit: (page, phone) => {
    fireNow('lead_submit', page);
    if (PH_READY() && phone) {
      try { posthog.identify(phone); } catch (_) {}
    }
  },
  whatsappRedirect: (page) => fireNow('whatsapp_redirect', page),
  flush,
};

// ── GEO SEO Tracking ──
// Fires to /api/events (geo_analytics backend) with city/variant/type/channel
const _geoFired = new Set();

function fireGeoEvent(event, { city, variant, type, url } = {}) {
  const key = `${event}:${city}:${variant}:${type}`;
  if (_geoFired.has(key)) return; // once per session
  _geoFired.add(key);
  const payload = {
    event,
    city: city || null,
    variant: variant || 'default',
    type: type || null,
    channel: 'seo_geo',
    url: url || window.location.pathname,
    session_id: getSessionId(),
  };
  phCapture(event, city);
  try {
    navigator.sendBeacon?.(
      `${API_BASE}/api/geo-events`,
      new Blob([JSON.stringify(payload)], { type: 'application/json' })
    ) || fetch(`${API_BASE}/api/geo-events`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      keepalive: true,
    });
  } catch (_) {}
}

export const geo = {
  pageView: (opts) => fireGeoEvent('geo_page_view', opts),
  ctaClick: (opts) => fireGeoEvent('geo_cta_click', opts),
};
