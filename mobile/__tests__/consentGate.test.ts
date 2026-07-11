/**
 * DPDP-04-MOB — Consent gate unit tests.
 *
 * What we lock down:
 *   1. `requireConsent` hits the API and caches on Accept.
 *   2. `requireConsent` returns false and stores a 24h timeout on Decline.
 *   3. A cached Grant short-circuits future calls (no modal shown, no API).
 *   4. A cached Decline expires after 24h and re-prompts.
 *   5. Queueing: two concurrent requests serialise.
 *
 * Pure logic test — no React rendering. We exercise the
 * `useConsentGateStore` programmatically and drive the resolver.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import Module from 'node:module';

const ORIGINAL = (Module as unknown as { _resolveFilename: Function })._resolveFilename;
const path = require('path');
const fs = require('fs');
const fixtures = path.join(__dirname, '_fixtures');
fs.mkdirSync(fixtures, { recursive: true });

// ── In-memory AsyncStorage ────────────────────────────────────────
const _kv: Record<string, string> = {};
fs.writeFileSync(path.join(fixtures, 'async-storage-mock.cjs'), `
const store = {
  getItem: async (k) => (k in global.__cgs_kv ? global.__cgs_kv[k] : null),
  setItem: async (k, v) => { global.__cgs_kv[k] = v; },
  removeItem: async (k) => { delete global.__cgs_kv[k]; },
};
Object.defineProperty(module.exports, '__esModule', { value: true });
module.exports.default = store;
`);
(global as any).__cgs_kv = _kv;

// ── Mock expo-constants ───────────────────────────────────────────
fs.writeFileSync(path.join(fixtures, 'expo-constants-mock.cjs'), `
Object.defineProperty(module.exports, '__esModule', { value: true });
module.exports.default = { expoConfig: { version: '1.0.0' } };
`);

// ── Mock API client: capture calls ────────────────────────────────
interface Recorded { method: 'post' | 'delete'; url: string; body?: unknown; }
const calls: Recorded[] = [];
fs.writeFileSync(path.join(fixtures, 'api-mock.cjs'), `
const calls = global.__cgs_calls;
const api = {
  post: async (url, body) => { calls.push({ method: 'post', url, body }); return { data: {} }; },
};
api['delete'] = async (url) => { calls.push({ method: 'delete', url }); return { data: {} }; };
Object.defineProperty(module.exports, '__esModule', { value: true });
module.exports.default = api;
`);
(global as any).__cgs_calls = calls;

// ── Resolver hijack for axios.ts -> api.ts mock ───────────────────
const MOD_MAP: Record<string, string> = {
  '@react-native-async-storage/async-storage': path.join(fixtures, 'async-storage-mock.cjs'),
  'expo-constants': path.join(fixtures, 'expo-constants-mock.cjs'),
};
(Module as unknown as { _resolveFilename: Function })._resolveFilename = function (req: string, parent: any) {
  if (req in MOD_MAP) return MOD_MAP[req];
  // Hijack ANY resolution of the api client to our mock. There's only
  // one `services/api.ts` in the project; matching its basename is safe.
  if (req === './api' || req === '../services/api' || req.endsWith('/services/api')) {
    return path.join(fixtures, 'api-mock.cjs');
  }
  return ORIGINAL.call(this, req, parent);
};

// Now require fresh modules under the hijack
delete require.cache[require.resolve('../stores/consentGateStore')];
delete require.cache[require.resolve('../services/consentService')];

const storeMod = require('../stores/consentGateStore') as typeof import('../stores/consentGateStore');
const svc = require('../services/consentService') as typeof import('../services/consentService');

const flush = () => new Promise<void>((r) => setImmediate(r));

test('accept path: shows modal, calls API, caches grant', async () => {
  await svc.__resetAllConsentCache();
  calls.length = 0;

  const p = svc.requireConsent('location_tracking');
  await flush();
  // Modal should be pending
  assert.equal(storeMod.useConsentGateStore.getState().pending?.category, 'location_tracking');

  storeMod.useConsentGateStore.getState().resolveCurrent(true);
  const granted = await p;
  await flush();

  assert.equal(granted, true);
  // Cache populated
  const cached = _kv['dpdp_consent_location_tracking'];
  assert.ok(cached);
  assert.equal(JSON.parse(cached).granted, true);
  // API called
  await flush();
  assert.ok(calls.some((c) => c.method === 'post' && c.url === '/privacy/consents/me'));
});

test('decline path: caches refusal, calls DELETE', async () => {
  await svc.__resetAllConsentCache();
  calls.length = 0;

  const p = svc.requireConsent('audio_recording');
  await flush();
  storeMod.useConsentGateStore.getState().resolveCurrent(false);
  const granted = await p;
  await flush();

  assert.equal(granted, false);
  const cached = JSON.parse(_kv['dpdp_consent_audio_recording']);
  assert.equal(cached.granted, false);
  assert.ok(typeof cached.decided_at === 'number');
});

test('cached grant short-circuits — no modal, no extra API call', async () => {
  await svc.__resetAllConsentCache();
  // Seed the cache as if we'd granted earlier.
  _kv['dpdp_consent_health_vitals'] = JSON.stringify({
    granted: true,
    decided_at: Date.now(),
    version: '1.0',
  });
  calls.length = 0;

  const granted = await svc.requireConsent('health_vitals');

  assert.equal(granted, true);
  assert.equal(storeMod.useConsentGateStore.getState().pending, null);
  assert.equal(calls.length, 0);
});

test('cached decline expires after 24h and re-prompts', async () => {
  await svc.__resetAllConsentCache();
  // Seed a 25-hour-old decline.
  _kv['dpdp_consent_push_notifications'] = JSON.stringify({
    granted: false,
    decided_at: Date.now() - 25 * 60 * 60 * 1000,
    version: '1.0',
  });
  calls.length = 0;

  const p = svc.requireConsent('push_notifications');
  await flush();
  // The expired decline should trigger a modal again.
  assert.equal(
    storeMod.useConsentGateStore.getState().pending?.category,
    'push_notifications',
  );
  storeMod.useConsentGateStore.getState().resolveCurrent(true);
  await p;
});

test('queueing: second request waits for first to resolve', async () => {
  await svc.__resetAllConsentCache();
  calls.length = 0;

  const p1 = svc.requireConsent('location_tracking');
  const p2 = svc.requireConsent('audio_recording');
  await flush();

  // Only the first should be pending; second queued.
  const st = storeMod.useConsentGateStore.getState();
  assert.equal(st.pending?.category, 'location_tracking');
  assert.equal(st.queue.length, 1);
  assert.equal(st.queue[0].category, 'audio_recording');

  storeMod.useConsentGateStore.getState().resolveCurrent(true);
  await p1;
  await flush();

  // Now the queued one should be the active prompt.
  assert.equal(storeMod.useConsentGateStore.getState().pending?.category, 'audio_recording');
  storeMod.useConsentGateStore.getState().resolveCurrent(false);
  const r2 = await p2;
  assert.equal(r2, false);
});
