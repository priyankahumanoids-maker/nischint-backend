/**
 * HC-01 Day 2 — Health Connect (Android) data-access service.
 *
 * Reads HeartRate, OxygenSaturation, and Steps from the on-device
 * Health Connect provider since the last successful sync. Persists
 * `hc_last_sync` via AsyncStorage so cold restarts / app-kills don't
 * re-pull data we've already shipped.
 *
 * Notes vs. the spec template:
 *   • Project does not use MMKV — we use AsyncStorage (same one the
 *     existing alertStore / authStore use). API surface is preserved.
 *   • react-native-health-connect@3.5.3 returns
 *     `OxygenSaturationRecord.percentage: number` (0–100), NOT a
 *     `{ value }` wrapper. We pass the value through unchanged.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';
import {
  initialize,
  requestPermission,
  readRecords,
  type HeartRateRecord,
  type OxygenSaturationRecord,
  type StepsRecord,
} from 'react-native-health-connect';
import { requireConsent } from './consentService';

export interface HealthSignal {
  type: 'heart_rate' | 'spo2' | 'steps' | 'fall';
  value: number;
  unit: string;
  source: string;
  timestamp: string;
}

const LAST_SYNC_KEY = 'hc_last_sync';
const ONE_HOUR_MS = 60 * 60 * 1000;

export const requestHealthPermissions = async (): Promise<boolean> => {
  try {
    // DPDP-04-MOB — pre-permission consent half-modal before OS prompt.
    // Health Connect on Android forwards the user to the system Permission
    // Controller; if the user declines our gate, we skip that handoff
    // entirely.
    const consent = await requireConsent('health_vitals');
    if (!consent) {
      console.warn('[HC] DPDP consent declined — skipping native prompt');
      return false;
    }
    await initialize();
    const granted = await requestPermission([
      { accessType: 'read', recordType: 'HeartRate' },
      { accessType: 'read', recordType: 'OxygenSaturation' },
      { accessType: 'read', recordType: 'Steps' },
    ]);
    return granted.length > 0;
  } catch {
    return false;
  }
};

export const fetchDeltaSignals = async (): Promise<HealthSignal[]> => {
  try {
    await initialize();

    const lastSync = await AsyncStorage.getItem(LAST_SYNC_KEY);
    const startTime = lastSync ?? new Date(Date.now() - ONE_HOUR_MS).toISOString();
    const endTime = new Date().toISOString();
    const filter = {
      timeRangeFilter: { operator: 'between' as const, startTime, endTime },
    };

    const [hr, spo2, steps] = await Promise.all([
      readRecords('HeartRate', filter),
      readRecords('OxygenSaturation', filter),
      readRecords('Steps', filter),
    ]);

    await AsyncStorage.setItem(LAST_SYNC_KEY, endTime);

    const hrSignals: HealthSignal[] = (hr.records as HeartRateRecord[]).flatMap((r) =>
      r.samples.map((s) => ({
        type: 'heart_rate' as const,
        value: s.beatsPerMinute,
        unit: 'bpm',
        source: r.metadata?.dataOrigin ?? 'unknown',
        timestamp: s.time,
      })),
    );

    const spo2Signals: HealthSignal[] = (spo2.records as OxygenSaturationRecord[]).map((r) => ({
      type: 'spo2' as const,
      value: r.percentage,
      unit: '%',
      source: r.metadata?.dataOrigin ?? 'unknown',
      timestamp: r.time,
    }));

    const stepsSignals: HealthSignal[] = (steps.records as StepsRecord[]).map((r) => ({
      type: 'steps' as const,
      value: r.count,
      unit: 'steps',
      source: r.metadata?.dataOrigin ?? 'unknown',
      timestamp: r.startTime,
    }));

    return [...hrSignals, ...spo2Signals, ...stepsSignals];
  } catch {
    return [];
  }
};

export const resetLastSync = async (): Promise<void> => {
  await AsyncStorage.removeItem(LAST_SYNC_KEY);
};
