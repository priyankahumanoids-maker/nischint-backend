/**
 * HC-03 — iOS HealthKit bridge + cross-platform router tests.
 *
 * Locks:
 *   1. Feature flag OFF → `isHealthKitAvailable()` returns false on iOS
 *      and `fetchDeltaSignalsIOS()` returns [].
 *   2. Feature flag ON + iOS + native module present →
 *      `isHealthKitAvailable()` returns true.
 *   3. Native module missing (`force-missing`) → graceful no-op.
 *   4. `fetchDeltaSignalsIOS` normalizes HealthKit SpO₂ (0–1.0) into
 *      the 0–100 wire format and maps heart_rate + steps through.
 *   5. Router picks the right per-OS bridge.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import Module from 'node:module';

const ORIGINAL = (Module as unknown as { _resolveFilename: Function })._resolveFilename;
const path = require('path');
const fs = require('fs');
const fixturesDir = path.join(__dirname, '_fixtures');
fs.mkdirSync(fixturesDir, { recursive: true });

fs.writeFileSync(path.join(fixturesDir, 'asyncstorage-hk-mock.cjs'), `
const _store = new Map();
const impl = {
  getItem: async (k) => _store.get(k) ?? null,
  setItem: async (k, v) => { _store.set(k, v); },
  removeItem: async (k) => { _store.delete(k); },
  __dump: () => Object.fromEntries(_store),
};
module.exports = impl;
module.exports.default = impl;
module.exports.__esModule = true;`);
fs.writeFileSync(path.join(fixturesDir, 'rn-hk-mock.cjs'),
                 `module.exports = { Platform: { OS: 'ios' } };`);
fs.writeFileSync(path.join(fixturesDir, 'health-connect-hk-mock.cjs'), `
let _granted = true;
let _signals = [];
module.exports = {
  requestHealthPermissions: async () => _granted,
  fetchDeltaSignals: async () => _signals,
  resetLastSync: async () => undefined,
  __setMock: (g, s) => { _granted = g; _signals = s; },
};`);
// Use a known-missing module path so dynamic require fails cleanly
// for the negative-path test.

(Module as unknown as { _resolveFilename: Function })._resolveFilename = function (
  request: string, parent: NodeJS.Module, ...rest: unknown[]
) {
  const map: Record<string, string> = {
    'react-native':                       './_fixtures/rn-hk-mock.cjs',
    '@react-native-async-storage/async-storage': './_fixtures/asyncstorage-hk-mock.cjs',
    // The router pulls in the Android service. Stub it.
    './healthConnectService':             './_fixtures/health-connect-hk-mock.cjs',
    '@/services/healthConnectService':    './_fixtures/health-connect-hk-mock.cjs',
  };
  if (map[request]) return require.resolve(map[request]);
  return ORIGINAL.call(this, request, parent, ...rest);
};

const hk = require('../services/healthKitService') as typeof import('../services/healthKitService');
const router = require('../services/healthSync') as typeof import('../services/healthSync');

// ── 1. Flag OFF → no-op even on iOS ─────────────────────────────────
test('feature flag OFF → isHealthKitAvailable() == false and fetch returns []', async () => {
  delete process.env.EXPO_PUBLIC_ENABLE_HEALTHKIT;
  hk.__setHealthKitOverrides({ platform: 'ios', native: null });
  assert.equal(hk.isHealthKitAvailable(), false);
  const out = await hk.fetchDeltaSignalsIOS();
  assert.deepEqual(out, []);
});

// ── 2. Flag ON + iOS + native present → available ───────────────────
test('flag ON + iOS + native module present → available', async () => {
  process.env.EXPO_PUBLIC_ENABLE_HEALTHKIT = 'true';
  hk.__setHealthKitOverrides({
    platform: 'ios',
    native: {
      requestAuthorization: async () => true,
      queryQuantitySamples: async () => [],
    },
  });
  assert.equal(hk.isHealthKitAvailable(), true);
  assert.equal(await hk.requestHealthKitPermissions(), true);
});

// ── 3. Flag ON but native missing → graceful no-op ──────────────────
test('flag ON + iOS + native MISSING → graceful no-op', async () => {
  process.env.EXPO_PUBLIC_ENABLE_HEALTHKIT = 'true';
  hk.__setHealthKitOverrides({ platform: 'ios', native: 'force-missing' });
  assert.equal(hk.isHealthKitAvailable(), false);
  assert.equal(await hk.requestHealthKitPermissions(), false);
  const out = await hk.fetchDeltaSignalsIOS();
  assert.deepEqual(out, []);
});

// ── 4. Sample shape: SpO₂ normalized + types mapped correctly ───────
test('fetchDeltaSignalsIOS normalizes SpO₂ 0-1.0 → 0-100 and maps types', async () => {
  process.env.EXPO_PUBLIC_ENABLE_HEALTHKIT = 'true';
  hk.__setHealthKitOverrides({
    platform: 'ios',
    native: {
      requestAuthorization: async () => true,
      queryQuantitySamples: async (typeId: string) => {
        if (typeId === 'HKQuantityTypeIdentifierHeartRate') {
          return [{ quantity: 75, startDate: '2026-05-25T10:00:00Z',
                    sourceName: 'Apple Watch' }];
        }
        if (typeId === 'HKQuantityTypeIdentifierOxygenSaturation') {
          // HealthKit returns SpO₂ as 0–1.0 fraction.
          return [{ quantity: 0.97, startDate: '2026-05-25T10:00:00Z' }];
        }
        if (typeId === 'HKQuantityTypeIdentifierStepCount') {
          return [{ quantity: 1234, startDate: '2026-05-25T10:00:00Z' }];
        }
        return [];
      },
    },
  });
  const out = await hk.fetchDeltaSignalsIOS();
  assert.equal(out.length, 3);
  const hr   = out.find((s) => s.type === 'heart_rate');
  const spo2 = out.find((s) => s.type === 'spo2');
  const steps = out.find((s) => s.type === 'steps');
  assert.ok(hr && hr.value === 75 && hr.source === 'Apple Watch');
  // Critical contract: 0.97 normalises to 97, not stays at 0.97.
  assert.ok(spo2 && spo2.value === 97);
  assert.ok(steps && steps.value === 1234);
});

// ── 5. Router picks the right per-OS bridge ──────────────────────────
test('healthSync router routes iOS → HealthKit, Android → HealthConnect, web → empty', async () => {
  process.env.EXPO_PUBLIC_ENABLE_HEALTHKIT = 'true';
  hk.__setHealthKitOverrides({
    platform: 'ios',
    native: {
      requestAuthorization: async () => true,
      queryQuantitySamples: async () => [{ quantity: 80,
                                           startDate: '2026-05-25T10:00:00Z' }],
    },
  });

  router.__setHealthSyncPlatform('ios');
  let signals = await router.fetchDeltaSignals();
  // HR + SpO₂ + steps queries all return the same 80 value in our
  // fixture above, so we expect 3 samples.
  assert.equal(signals.length, 3);
  assert.equal(await router.requestHealthPermissions(), true);

  // Stub Android service via the fixture (already wired through the
  // resolver hook above). Note: the mock module is the *same* module
  // identity used by the router import, so we can dial it via require.
  const hcMock = require('./_fixtures/health-connect-hk-mock.cjs') as {
    __setMock: (g: boolean, s: object[]) => void;
  };
  hcMock.__setMock(true, [{ type: 'heart_rate', value: 60, unit: 'bpm',
                            source: 'mock', timestamp: '2026-05-25T11:00:00Z' }]);
  router.__setHealthSyncPlatform('android');
  signals = await router.fetchDeltaSignals();
  assert.equal(signals.length, 1);
  assert.equal(signals[0].value, 60);
  assert.equal(await router.requestHealthPermissions(), true);

  router.__setHealthSyncPlatform('web');
  assert.deepEqual(await router.fetchDeltaSignals(), []);
  assert.equal(await router.requestHealthPermissions(), false);
});
