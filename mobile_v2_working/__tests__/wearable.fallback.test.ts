/**
 * HC-01 Day 4 — Fallback / graceful-denial behaviour test.
 *
 * Verifies — without booting a React Native runtime — that:
 *   1. `isHealthConnectGranted()` returns false when the flag is absent.
 *   2. `WearableConnectCard` is hidden when the 7-day deny window is
 *      still active, and re-appears after it expires.
 *   3. `VitalsStrip` is hidden when permissions are not granted.
 *   4. The Health Connect initialize() call throwing (simulating
 *      Android < 9 with no Health Connect provider) does not crash
 *      `requestHealthPermissions` — it returns false cleanly.
 *
 * Runner: pure Node + `node --test --import tsx`. We mock the
 * `@react-native-async-storage/async-storage` module via Node's
 * module-resolution hook BEFORE importing the storage helpers.
 *
 * Run with:
 *   cd /app/mobile && yarn test:hc01
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import Module from 'node:module';

// ── 1. In-memory AsyncStorage mock ────────────────────────────────
const mem = new Map<string, string>();
const fakeAsyncStorage = {
  getItem: async (k: string) => (mem.has(k) ? mem.get(k)! : null),
  setItem: async (k: string, v: string) => {
    mem.set(k, v);
  },
  removeItem: async (k: string) => {
    mem.delete(k);
  },
  clear: async () => {
    mem.clear();
  },
};

// ── 2. Module resolution hook: replace AsyncStorage + react-native ─
// Node's `Module._resolveFilename` is intercepted so the storage
// helper sees our fake AsyncStorage when it `import`s it.
const ORIGINAL_RESOLVE = (Module as any)._resolveFilename;
(Module as any)._resolveFilename = function (
  request: string,
  parent: NodeJS.Module,
  ...rest: unknown[]
) {
  if (request === '@react-native-async-storage/async-storage') {
    return require.resolve('./_fixtures/async-storage-mock.cjs');
  }
  if (request === 'react-native-health-connect') {
    return require.resolve('./_fixtures/health-connect-mock.cjs');
  }
  return ORIGINAL_RESOLVE.call(this, request, parent, ...rest);
};

// Provide a CJS file that re-exports the in-memory mock as default.
// This lives in `_fixtures/` so it's never picked up by EAS Build.
const path = require('path');
const fs = require('fs');
const fixturesDir = path.join(__dirname, '_fixtures');
fs.mkdirSync(fixturesDir, { recursive: true });

fs.writeFileSync(
  path.join(fixturesDir, 'async-storage-mock.cjs'),
  `// Lazy: re-reads globalThis each call so the storage helpers see
// the in-memory map set up by the test file at runtime.
const proxy = {
  getItem: (k) => globalThis.__hc01_asyncStorage__.getItem(k),
  setItem: (k, v) => globalThis.__hc01_asyncStorage__.setItem(k, v),
  removeItem: (k) => globalThis.__hc01_asyncStorage__.removeItem(k),
  clear: () => globalThis.__hc01_asyncStorage__.clear(),
};
module.exports = proxy;
module.exports.default = proxy;
`,
);

// `initialize()` throws in scenario #4 (simulate Android <9).
fs.writeFileSync(
  path.join(fixturesDir, 'health-connect-mock.cjs'),
  `module.exports = {
  initialize: async () => { if (globalThis.__hc01_initShouldThrow__) throw new Error('Health Connect not installed'); return true; },
  requestPermission: async () => (globalThis.__hc01_initShouldThrow__ ? [] : [{ accessType: 'read', recordType: 'HeartRate' }]),
  readRecords: async () => ({ records: [] }),
};`,
);

(globalThis as any).__hc01_asyncStorage__ = fakeAsyncStorage;
(globalThis as any).__hc01_initShouldThrow__ = false;

// Now safe to import the storage helpers + service under test.
const {
  isHealthConnectGranted,
  isHealthConnectDenyActive,
  markHealthConnectGranted,
  markHealthConnectDenied,
  HC_DENY_REPROMPT_DAYS,
  HC_KEYS,
} = require('../services/healthConnectStorage') as typeof import('../services/healthConnectStorage');

const { requestHealthPermissions } = require('../services/healthConnectService') as typeof import('../services/healthConnectService');


test('1. Permissions absent → isHealthConnectGranted is false', async () => {
  mem.clear();
  assert.equal(await isHealthConnectGranted(), false);
});

test('2. After grant → isHealthConnectGranted is true and deny window cleared', async () => {
  mem.clear();
  mem.set(HC_KEYS.permissionsDeniedUntil, String(Date.now() + 1_000_000));
  await markHealthConnectGranted();
  assert.equal(await isHealthConnectGranted(), true);
  assert.equal(await isHealthConnectDenyActive(), false);
});

test('3. After deny → 7-day cool-off is active', async () => {
  mem.clear();
  await markHealthConnectDenied();
  assert.equal(await isHealthConnectDenyActive(), true);
  // Stored value should be ~7 days into the future.
  const raw = mem.get(HC_KEYS.permissionsDeniedUntil)!;
  const stored = Number.parseInt(raw, 10);
  const expected = Date.now() + HC_DENY_REPROMPT_DAYS * 86_400_000;
  // Allow 5s skew for test execution time.
  assert.ok(Math.abs(stored - expected) < 5_000, `deny-until skew ${stored - expected}ms`);
});

test('4. Expired deny window → isHealthConnectDenyActive returns false AND clears stale key', async () => {
  mem.clear();
  mem.set(HC_KEYS.permissionsDeniedUntil, String(Date.now() - 1));
  assert.equal(await isHealthConnectDenyActive(), false);
  assert.equal(mem.has(HC_KEYS.permissionsDeniedUntil), false, 'stale deny key should be cleared');
});

test('5. VitalsStrip predicate — hidden when not granted', async () => {
  mem.clear();
  // The strip renders only when isHealthConnectGranted() === true.
  assert.equal(await isHealthConnectGranted(), false);
});

test('6. WearableConnectCard predicate — hidden during deny window, visible after', async () => {
  mem.clear();
  await markHealthConnectDenied();
  // visible ⇔ !granted && !denyActive
  const grantedNow = await isHealthConnectGranted();
  const denyNow = await isHealthConnectDenyActive();
  assert.equal(!grantedNow && !denyNow, false, 'card must be hidden during deny window');

  // Fast-forward: simulate cool-off expired by stomping the key.
  mem.set(HC_KEYS.permissionsDeniedUntil, String(Date.now() - 1));
  const denyLater = await isHealthConnectDenyActive();
  const grantedLater = await isHealthConnectGranted();
  assert.equal(!grantedLater && !denyLater, true, 'card must reappear after cool-off');
});

test('7. initialize() throwing (Android < 9 simulation) → requestHealthPermissions returns false, no crash', async () => {
  mem.clear();
  (globalThis as any).__hc01_initShouldThrow__ = true;
  try {
    const ok = await requestHealthPermissions();
    assert.equal(ok, false, 'must swallow init errors and return false');
  } finally {
    (globalThis as any).__hc01_initShouldThrow__ = false;
  }
});
