// Push Notification Service — register FCM token + handle incoming pushes
import * as Notifications from 'expo-notifications';
import * as Device from 'expo-device';
import { Platform, Alert } from 'react-native';
import api from './api';
import { playSirenLoop, stopSirenLoop } from './sirenPlayer';
import { requireConsent } from './consentService';

// Configure notification behavior (foreground display)
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: true,
    shouldShowBanner: true,
    shouldShowList: true,
    priority: Notifications.AndroidNotificationPriority.MAX,
  }),
});

let _registered = false;

/**
 * Register for push notifications:
 * 1. Request permission
 * 2. Get native FCM device token
 * 3. Send to backend for storage
 */
export async function registerPushToken(): Promise<string | null> {
  if (_registered) return null;

  try {
    // Must be a physical device
    if (!Device.isDevice) {
      console.log('[PUSH] Skipping — not a physical device');
      return null;
    }

    // Request permission — wrap in try/catch so a denial/native error never crashes app
    let finalStatus: string;
    try {
      const existing = await Notifications.getPermissionsAsync();
      finalStatus = existing.status;
      if (finalStatus !== 'granted') {
        // DPDP-04-MOB — pre-permission consent half-modal before OS prompt.
        // If declined, skip the OS prompt entirely so we don't burn the
        // "you only get to ask once" iOS budget.
        const consent = await requireConsent('push_notifications');
        if (!consent) {
          console.warn('[PUSH] DPDP consent declined — skipping native prompt');
          return null;
        }
        const req = await Notifications.requestPermissionsAsync();
        finalStatus = req.status;
      }
    } catch (e) {
      console.warn('[PUSH] Permission request error (continuing without push):', (e as any)?.message || e);
      return null;
    }

    if (finalStatus !== 'granted') {
      console.warn('[PUSH] Permission denied');
      return null;
    }

    // Android: set up notification channels.
    //
    // We register two channels:
    //   1. `safety-alerts` — default HIGH-importance channel for routine
    //      safety pushes (geofence breach hints, low battery, journey
    //      ended, etc).
    //   2. `critical_safety` — MAX-importance, DND-bypass, custom siren
    //      loop sound, aggressive vibration. Mirrors the backend
    //      `louder_push` contract in `app/services/push_service.py`.
    //      Without this channel, FCM silently routes to default and the
    //      "interruption" guarantee is lost.
    if (Platform.OS === 'android') {
      try {
        await Notifications.setNotificationChannelAsync('safety-alerts', {
          name: 'Safety Alerts',
          importance: Notifications.AndroidImportance.MAX,
          vibrationPattern: [0, 500, 300, 500, 300, 500],
          sound: 'default',
          enableVibrate: true,
          lockscreenVisibility: Notifications.AndroidNotificationVisibility.PUBLIC,
        });
      } catch (e) {
        console.warn('[PUSH] Channel setup failed:', (e as any)?.message || e);
      }
      try {
        await Notifications.setNotificationChannelAsync('critical_safety', {
          name: 'Critical Safety Alerts',
          description:
            'Life-safety alerts that bypass Do Not Disturb. Includes Emergency SOS escalations and louder-push re-broadcasts.',
          importance: Notifications.AndroidImportance.MAX,
          // Long, repeating siren-style pulse — the channel pattern
          // wins over the FCM payload `vibrate_timings` on Android 8+.
          vibrationPattern: [0, 800, 200, 800, 200, 800, 200, 800],
          sound: 'siren_loop',
          enableVibrate: true,
          enableLights: true,
          lightColor: '#FF1744',
          lockscreenVisibility: Notifications.AndroidNotificationVisibility.PUBLIC,
          // DND bypass — only honored if the user has granted
          // Notification Policy Access. Setting it here marks the
          // channel as eligible; the actual bypass kicks in once
          // permission is granted.
          bypassDnd: true,
          showBadge: true,
        });
      } catch (e) {
        console.warn('[PUSH] critical_safety channel setup failed:', (e as any)?.message || e);
      }
    }

    // Get native device push token (FCM on Android, APNs on iOS)
    const tokenData = await Notifications.getDevicePushTokenAsync();
    const token = tokenData.data;
    console.log('[PUSH] Device token:', token.substring(0, 20) + '...');

    // Register with backend
    try {
      await api.post('/push/token', { token });
      console.log('[PUSH] Token registered with backend');
    } catch (e: any) {
      console.warn('[PUSH] Backend registration failed (will retry later):', e?.message || e);
    }
    _registered = true;
    return token;
  } catch (e: any) {
    console.error('[PUSH] Registration failed (non-fatal):', e?.message || e);
    return null;
  }
}

/**
 * Listen for incoming notifications (foreground + background tap).
 *
 * Special handling for `data.louder_push === "true"`:
 *   - In foreground, Android suppresses the heads-up presentation, so we
 *     manually play the siren loop via `expo-audio` AND re-present the
 *     notification on the `critical_safety` channel (so it appears on
 *     the lock screen / shade with full siren behavior).
 *   - In background/killed state, FCM already routes through the
 *     `critical_safety` channel — we don't double-fire.
 */
export function setupPushListeners(onNotification?: (data: any) => void) {
  const isLouder = (data: any): boolean =>
    data?.louder_push === 'true' || data?.louder_push === true;

  // Foreground notification received
  const foregroundSub = Notifications.addNotificationReceivedListener(async (notification) => {
    const content = notification.request.content;
    const data = content.data || {};
    console.log('[PUSH_RECEIVED]', content.title, JSON.stringify(data).substring(0, 200));

    if (isLouder(data)) {
      // Foreground siren fallback — Android won't heads-up while app is
      // foregrounded, so we explicitly play the siren and present a
      // local notification on the critical channel.
      try { await playSirenLoop(30000); } catch {}
      if (Platform.OS === 'android') {
        try {
          await Notifications.scheduleNotificationAsync({
            content: {
              title: content.title || 'EMERGENCY',
              body: content.body || 'Tap to respond',
              data,
              sound: 'siren_loop',
              priority: Notifications.AndroidNotificationPriority.MAX,
              vibrate: [0, 800, 200, 800, 200, 800],
              sticky: true,
            } as any,
            trigger: { channelId: 'critical_safety' } as any,
          });
        } catch (e) {
          console.warn('[PUSH] foreground critical re-present failed:', (e as any)?.message || e);
        }
      }
    }
    if (onNotification) onNotification(data);
  });

  // User tapped notification (from background/killed state)
  const responseSub = Notifications.addNotificationResponseReceivedListener((response) => {
    const data = response.notification.request.content.data || {};
    console.log('[PUSH_TAPPED]', response.notification.request.content.title, JSON.stringify(data).substring(0, 100));
    // User engaged → kill the siren.
    stopSirenLoop().catch(() => {});
    if (onNotification) onNotification(data);
  });

  return () => {
    foregroundSub.remove();
    responseSub.remove();
    stopSirenLoop().catch(() => {});
  };
}

/**
 * Stop the foreground siren loop. Call this when the user ACKs the
 * alert from anywhere in the app (e.g., swipe-to-ACK on Risk Panel).
 */
export async function silenceCriticalAlert(): Promise<void> {
  try { await stopSirenLoop(); } catch {}
  try { await Notifications.dismissAllNotificationsAsync(); } catch {}
}
