/**
 * HC-01 Day 2 — Background wearable sync task.
 *
 * Registers a 10-minute BackgroundFetch task that pulls delta
 * Health Connect signals via `healthConnectService.fetchDeltaSignals`
 * and posts them to the backend.
 *
 * Deviations from the spec template:
 *   • Project uses `@/stores/authStore` (plural), not `@/store/authStore`.
 *   • Project's api client is a default export from `services/api`.
 *   • The backend route lives at POST /api/health-signals/wearable
 *     (api client already prefixes /api via its baseURL).
 */
import * as BackgroundFetch from 'expo-background-fetch';
import * as TaskManager from 'expo-task-manager';
import AsyncStorage from '@react-native-async-storage/async-storage';

import { fetchDeltaSignals } from '@/services/healthSync';
import { HC_KEYS } from '@/services/healthConnectStorage';
import api from '@/services/api';
import { useAuthStore } from '@/stores/authStore';

const TASK_NAME = 'WEARABLE_SYNC';

TaskManager.defineTask(TASK_NAME, async () => {
  try {
    const { token } = useAuthStore.getState();
    if (!token) {
      return BackgroundFetch.BackgroundFetchResult.NoData;
    }

    const signals = await fetchDeltaSignals();
    if (signals.length === 0) {
      return BackgroundFetch.BackgroundFetchResult.NoData;
    }

    await api.post('/health-signals/wearable', { signals });

    // Persist latest HR / SpO₂ for the VitalsStrip homescreen widget.
    // `.at(-1)` matches the spec: most-recent sample wins. We trust
    // the array order coming from healthConnectService (samples are
    // appended in time order within each record type).
    const hrSignal = signals.filter((s) => s.type === 'heart_rate').at(-1);
    const spo2Signal = signals.filter((s) => s.type === 'spo2').at(-1);
    if (hrSignal) {
      await AsyncStorage.setItem(HC_KEYS.lastHr, String(hrSignal.value));
    }
    if (spo2Signal) {
      await AsyncStorage.setItem(HC_KEYS.lastSpo2, String(spo2Signal.value));
    }
    await AsyncStorage.setItem(HC_KEYS.lastSync, new Date().toISOString());

    return BackgroundFetch.BackgroundFetchResult.NewData;
  } catch (err) {
    console.warn('[WEARABLE_SYNC] failed:', err);
    return BackgroundFetch.BackgroundFetchResult.Failed;
  }
});

export const registerWearableSync = (): Promise<void> =>
  BackgroundFetch.registerTaskAsync(TASK_NAME, {
    minimumInterval: 600, // 10 minutes
    stopOnTerminate: false,
    startOnBoot: true,
  });

export const unregisterWearableSync = (): Promise<void> =>
  BackgroundFetch.unregisterTaskAsync(TASK_NAME);

export const WEARABLE_SYNC_TASK = TASK_NAME;
