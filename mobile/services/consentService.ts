// DPDP-04-MOB — Client-side consent gate.
//
// `requireConsent(category)` is the single API every native-permission
// call site uses. It:
//   1. Short-circuits with cached state (granted → true; revoked → false).
//   2. Otherwise shows a half-modal explaining purpose + DPDP §6.3
//      compliance, and awaits the user's choice.
//   3. On accept → POST /api/privacy/consents/me, persist cache, return
//      true. The native OS prompt is then fired by the caller.
//   4. On decline → DELETE /api/privacy/consents/me/{category}
//      (idempotent), persist cache, return false. Caller skips the OS
//      prompt and runs in degraded mode.
//
// Cache invalidation: the consent record server-side may be revoked
// from the Privacy screen. We expose `refreshConsentCache()` for the
// settings screen to bust the cache when that happens.

import AsyncStorage from '@react-native-async-storage/async-storage';
import Constants from 'expo-constants';
import api from './api';
import {
  useConsentGateStore,
  type ConsentCategory,
} from '../stores/consentGateStore';

// Re-export so callers can import the type from a single module.
export type { ConsentCategory };

const CACHE_KEY_PREFIX = 'dpdp_consent_';
const DECISION_TTL_MS = 24 * 60 * 60 * 1000; // re-prompt 24h after decline

const CURRENT_CONSENT_TEXT_VERSION = '1.0';

interface CachedDecision {
  granted: boolean;
  decided_at: number;
  version: string;
}

function appVersion(): string {
  // expo-constants surface name has shifted across SDKs — try both,
  // fall back to '?'.
  // @ts-expect-error — manifest2 lives only on newer SDKs.
  const v = Constants?.expoConfig?.version ?? Constants?.manifest?.version ?? '?';
  return String(v);
}

async function readCache(category: ConsentCategory): Promise<CachedDecision | null> {
  try {
    const raw = await AsyncStorage.getItem(`${CACHE_KEY_PREFIX}${category}`);
    if (!raw) return null;
    const parsed: CachedDecision = JSON.parse(raw);
    if (parsed.version !== CURRENT_CONSENT_TEXT_VERSION) return null;
    return parsed;
  } catch {
    return null;
  }
}

async function writeCache(
  category: ConsentCategory,
  granted: boolean,
): Promise<void> {
  try {
    const payload: CachedDecision = {
      granted,
      decided_at: Date.now(),
      version: CURRENT_CONSENT_TEXT_VERSION,
    };
    await AsyncStorage.setItem(
      `${CACHE_KEY_PREFIX}${category}`,
      JSON.stringify(payload),
    );
  } catch {
    /* AsyncStorage flake → next launch will re-prompt; safe. */
  }
}

/** Record the user's decision with the backend. Failure is non-fatal — the
 * user's choice is honored locally regardless. */
async function reportDecision(
  category: ConsentCategory,
  granted: boolean,
): Promise<void> {
  try {
    if (granted) {
      await api.post('/privacy/consents/me', {
        category,
        consent_text_version: CURRENT_CONSENT_TEXT_VERSION,
        app_version: appVersion(),
      });
    } else {
      // Revoke — idempotent server-side. 404 (no prior record) is fine,
      // it just means the user is declining without ever granting.
      try {
        await api.delete(`/privacy/consents/me/${category}`);
      } catch (e: any) {
        if (e?.response?.status !== 404) throw e;
      }
    }
  } catch (e: any) {
    console.warn(
      `[CONSENT] backend report failed for ${category} (continuing):`,
      e?.message || e,
    );
  }
}

/**
 * Show the pre-permission consent half-modal for `category` and resolve
 * with the user's choice. If the user previously decided, the cached
 * answer is returned immediately (no modal).
 */
export async function requireConsent(category: ConsentCategory): Promise<boolean> {
  const cached = await readCache(category);
  if (cached) {
    // Granted decisions are sticky; declined decisions auto-expire so
    // the user gets re-asked after 24h instead of being locked out
    // forever from a feature they may have toggled off accidentally.
    if (cached.granted) return true;
    const age = Date.now() - cached.decided_at;
    if (age < DECISION_TTL_MS) return false;
  }

  const granted = await new Promise<boolean>((resolve) => {
    useConsentGateStore.getState().enqueue({ category, resolve });
  });

  await writeCache(category, granted);
  // Fire-and-forget the backend report; do not block the caller. The
  // OS permission prompt should appear with minimal latency after the
  // user taps Accept.
  void reportDecision(category, granted);
  return granted;
}

/** Bust the local cache for a single category. Used by the Privacy
 * screen when the user revokes consent there — next time the feature
 * is invoked we must re-show the gate. */
export async function clearConsentCache(category: ConsentCategory): Promise<void> {
  try {
    await AsyncStorage.removeItem(`${CACHE_KEY_PREFIX}${category}`);
  } catch {
    /* non-fatal */
  }
}

/** Settings-screen toggle: directly record the user's decision without
 * showing the pre-permission half-modal (the user is already on the
 * privacy screen, the context is explicit).
 *
 *   • granted=true  → POST + cache "granted" so feature invocations
 *                     stop nagging.
 *   • granted=false → DELETE + bust the local cache so the next
 *                     feature invocation re-prompts via the half-modal
 *                     (and re-grants if the user changes their mind).
 *
 * Returns true if the backend acknowledged, false on network error.
 * Local cache is updated in either case so the UI stays consistent.
 */
export async function setConsentDecision(
  category: ConsentCategory,
  granted: boolean,
): Promise<boolean> {
  // Update local cache first so the UI reflects the toggle immediately.
  if (granted) {
    await writeCache(category, true);
  } else {
    await clearConsentCache(category);
  }
  try {
    await reportDecision(category, granted);
    return true;
  } catch {
    return false;
  }
}

/** Test seam — clears all categories. */
export async function __resetAllConsentCache(): Promise<void> {
  const categories: ConsentCategory[] = [
    'location_tracking',
    'audio_recording',
    'health_vitals',
    'push_notifications',
    'biometric_sensors',
  ];
  await Promise.all(categories.map(clearConsentCache));
}
