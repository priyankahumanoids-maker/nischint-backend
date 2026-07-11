/**
 * HC-03 — Cross-platform health-data router.
 *
 * Single entry point the rest of the app uses. Routes Android calls
 * to `react-native-health-connect` and iOS calls to the HealthKit
 * bridge in `healthKitService.ts`. Returns gracefully empty on every
 * other platform (web preview, unbuilt JS bundle, denied permissions).
 *
 * Public surface mirrors `healthConnectService.ts` so the wearable
 * background task doesn't care which OS it's running on.
 */
import { Platform } from 'react-native';
import {
  fetchDeltaSignals as fetchDeltaSignalsAndroid,
  requestHealthPermissions as requestHealthPermissionsAndroid,
  resetLastSync as resetLastSyncAndroid,
  type HealthSignal,
} from './healthConnectService';
import {
  fetchDeltaSignalsIOS,
  isHealthKitAvailable,
  requestHealthKitPermissions,
  resetHealthKitLastSync,
} from './healthKitService';

export type { HealthSignal } from './healthConnectService';

// Test seam — swap the platform we report to the router. Production
// runtime never reads this; tests set it before invoking.
let _platformOverride: typeof Platform.OS | null = null;
export function __setHealthSyncPlatform(p: typeof Platform.OS | null): void {
  _platformOverride = p;
}
function _os(): typeof Platform.OS { return _platformOverride ?? Platform.OS; }


export async function requestHealthPermissions(): Promise<boolean> {
  if (_os() === 'android') return requestHealthPermissionsAndroid();
  if (_os() === 'ios')     return requestHealthKitPermissions();
  return false;
}


export async function fetchDeltaSignals(): Promise<HealthSignal[]> {
  if (_os() === 'android') return fetchDeltaSignalsAndroid();
  if (_os() === 'ios')     return fetchDeltaSignalsIOS();
  return [];
}


export async function resetLastSync(): Promise<void> {
  if (_os() === 'android') return resetLastSyncAndroid();
  if (_os() === 'ios')     return resetHealthKitLastSync();
}


export function isHealthSyncAvailable(): boolean {
  if (_os() === 'android') return true;
  if (_os() === 'ios')     return isHealthKitAvailable();
  return false;
}
