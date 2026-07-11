/**
 * HC-03 — iOS HealthKit bridge.
 *
 * Mirrors the contract of `healthConnectService.ts` so the rest of the
 * app can stay platform-agnostic. The cross-platform router lives in
 * `services/healthSync.ts`.
 *
 * Native module: `@kingstinct/react-native-healthkit` (Expo config-plugin
 * compatible — the only HealthKit lib with a clean managed-workflow
 * config plugin as of Feb 2026).
 *
 * Feature flag: `EXPO_PUBLIC_ENABLE_HEALTHKIT` — defaults to `false`.
 * When the flag is OFF, or the platform isn't iOS, or the native
 * module isn't built into the binary, every public function returns
 * a graceful empty / `false` value so the wearable sync loop keeps
 * spinning without crashing.
 *
 * Why dynamic `require` rather than a top-level `import`?
 *   * The Expo preview JS bundle doesn't include `@kingstinct/react-native-healthkit`
 *     until the user runs `eas build` with the config plugin enabled.
 *   * A top-level import would crash the bundler on Android entirely.
 *   * Dynamic require gives a single, well-typed try/catch boundary
 *     that bridges "module not in bundle" → "feature off".
 */
import { Platform } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import type { HealthSignal } from './healthConnectService';

// Test seam — production code calls this only on iOS; tests inject
// custom platform / native handles to exercise each branch.
interface NativeHandle {
  requestAuthorization: (read: string[], write: string[]) => Promise<boolean>;
  queryQuantitySamples: (
    typeIdentifier: string,
    opts: { startDate: string; endDate: string },
  ) => Promise<Array<{ quantity: number; startDate: string; sourceName?: string }>>;
}

let _platformOverride: typeof Platform.OS | null = null;
let _nativeOverride: NativeHandle | null | 'force-missing' = null;

export function __setHealthKitOverrides(o: {
  platform?: typeof Platform.OS | null;
  native?: NativeHandle | null | 'force-missing';
} | null): void {
  _platformOverride = o?.platform ?? null;
  _nativeOverride = o?.native ?? null;
}

const HK_LAST_SYNC_KEY = 'hk_last_sync';
const ONE_HOUR_MS = 60 * 60 * 1000;

// HealthKit quantity type identifiers — pinned to the canonical names
// so a typo never silently swallows half a permission grant.
const HKQ_HEART_RATE = 'HKQuantityTypeIdentifierHeartRate';
const HKQ_SPO2       = 'HKQuantityTypeIdentifierOxygenSaturation';
const HKQ_STEP_COUNT = 'HKQuantityTypeIdentifierStepCount';

const READ_TYPES  = [HKQ_HEART_RATE, HKQ_SPO2, HKQ_STEP_COUNT];
const WRITE_TYPES: string[] = []; // read-only — we never write back to Health.


function _isFlagEnabled(): boolean {
  return process.env.EXPO_PUBLIC_ENABLE_HEALTHKIT === 'true';
}

function _isIOS(): boolean {
  return (_platformOverride ?? Platform.OS) === 'ios';
}

function _resolveNative(): NativeHandle | null {
  if (_nativeOverride === 'force-missing') return null;
  if (_nativeOverride) return _nativeOverride;
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const mod = require('@kingstinct/react-native-healthkit') as Partial<NativeHandle>;
    if (!mod || typeof mod.requestAuthorization !== 'function'
        || typeof mod.queryQuantitySamples !== 'function') {
      return null;
    }
    return mod as NativeHandle;
  } catch {
    // Module not in JS bundle (preview / Android / older binary).
    return null;
  }
}


export const isHealthKitAvailable = (): boolean => {
  if (!_isFlagEnabled() || !_isIOS()) return false;
  return _resolveNative() !== null;
};


export const requestHealthKitPermissions = async (): Promise<boolean> => {
  if (!isHealthKitAvailable()) return false;
  const native = _resolveNative();
  if (!native) return false;
  try {
    return await native.requestAuthorization(READ_TYPES, WRITE_TYPES);
  } catch {
    return false;
  }
};


function _mapSamples(
  type: HealthSignal['type'],
  unit: HealthSignal['unit'],
  rows: Array<{ quantity: number; startDate: string; sourceName?: string }>,
  valueAdapter?: (raw: number) => number,
): HealthSignal[] {
  return rows.map((r) => ({
    type,
    value:     valueAdapter ? valueAdapter(r.quantity) : r.quantity,
    unit,
    source:    r.sourceName ?? 'apple-health',
    timestamp: r.startDate,
  }));
}


export const fetchDeltaSignalsIOS = async (): Promise<HealthSignal[]> => {
  if (!isHealthKitAvailable()) return [];
  const native = _resolveNative();
  if (!native) return [];

  try {
    const lastSync = await AsyncStorage.getItem(HK_LAST_SYNC_KEY);
    const startDate = lastSync ?? new Date(Date.now() - ONE_HOUR_MS).toISOString();
    const endDate = new Date().toISOString();

    const [hrRows, spo2Rows, stepsRows] = await Promise.all([
      native.queryQuantitySamples(HKQ_HEART_RATE, { startDate, endDate }),
      native.queryQuantitySamples(HKQ_SPO2,       { startDate, endDate }),
      native.queryQuantitySamples(HKQ_STEP_COUNT, { startDate, endDate }),
    ]);

    await AsyncStorage.setItem(HK_LAST_SYNC_KEY, endDate);

    // HealthKit SpO₂ returns 0–1.0; normalize to 0–100 to match the
    // wire format the ingest endpoint expects.
    return [
      ..._mapSamples('heart_rate', 'bpm',   hrRows),
      ..._mapSamples('spo2',       '%',     spo2Rows, (v) => v <= 1 ? v * 100 : v),
      ..._mapSamples('steps',      'steps', stepsRows),
    ];
  } catch {
    return [];
  }
};


export const resetHealthKitLastSync = async (): Promise<void> => {
  await AsyncStorage.removeItem(HK_LAST_SYNC_KEY);
};
