/**
 * HC-01 Day 3 — Health Connect AsyncStorage keys & helpers.
 *
 * Single source of truth for the storage keys used across the Health
 * Connect surfaces (background sync, vitals strip, onboarding card).
 */
import AsyncStorage from '@react-native-async-storage/async-storage';

export const HC_KEYS = {
  permissionsGranted: 'hc_permissions_granted',
  permissionsDeniedUntil: 'hc_permissions_denied_until',
  lastSync: 'hc_last_sync',
  lastHr: 'hc_last_hr',
  lastSpo2: 'hc_last_spo2',
} as const;

export const HC_DENY_REPROMPT_DAYS = 7;

export const isHealthConnectGranted = async (): Promise<boolean> => {
  const v = await AsyncStorage.getItem(HC_KEYS.permissionsGranted);
  return v === 'true';
};

export const isHealthConnectDenyActive = async (): Promise<boolean> => {
  const v = await AsyncStorage.getItem(HC_KEYS.permissionsDeniedUntil);
  if (!v) return false;
  const expiresAt = Number.parseInt(v, 10);
  if (!Number.isFinite(expiresAt)) return false;
  if (Date.now() >= expiresAt) {
    // Expired — clear so the card can re-appear.
    await AsyncStorage.removeItem(HC_KEYS.permissionsDeniedUntil);
    return false;
  }
  return true;
};

export const markHealthConnectGranted = async (): Promise<void> => {
  await AsyncStorage.setItem(HC_KEYS.permissionsGranted, 'true');
  await AsyncStorage.removeItem(HC_KEYS.permissionsDeniedUntil);
};

export const markHealthConnectDenied = async (): Promise<void> => {
  const expiresAt = Date.now() + HC_DENY_REPROMPT_DAYS * 24 * 60 * 60 * 1000;
  await AsyncStorage.setItem(HC_KEYS.permissionsDeniedUntil, String(expiresAt));
};
