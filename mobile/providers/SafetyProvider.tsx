// SafetyProvider — Global safety layer that survives screen transitions
// Manages: shake detection (always-on), fall detection (5-stage pipeline), voice monitoring, emergency state recovery
import { useEffect, useRef, useState, useCallback } from 'react';
import { Vibration, Alert } from 'react-native';
import { useEmergencyStore } from '../stores/emergencyStore';
import { useAuthStore } from '../stores/authStore';
import {
  startShakeDetection,
  triggerSilentSOS,
  restoreEmergencyState,
} from '../services/deviceSafety';
import {
  startFallDetection,
  stopFallDetection,
  type FallSignals,
} from '../services/fallDetection';
import { stopAudioMonitoring } from '../services/audioMonitorService';
import { registerPushToken, setupPushListeners } from '../services/pushService';
import api from '../services/api';

// ── Safe-call helper: never let a native call crash the app on startup ──
async function safe<T>(label: string, fn: () => Promise<T> | T): Promise<T | null> {
  try {
    return await fn();
  } catch (e) {
    console.warn(`[SAFETY] ${label} failed (continuing without it):`, (e as any)?.message || e);
    return null;
  }
}

const AUTO_SOS_COUNTDOWN_S = 10;

export function SafetyProvider({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.token);
  const user = useAuthStore((s) => s.user);
  const isActive = useEmergencyStore((s) => s.isActive);
  const restore = useEmergencyStore((s) => s.restore);
  const activate = useEmergencyStore((s) => s.activate);
  const setTriggering = useEmergencyStore((s) => s.setTriggering);
  const isActiveRef = useRef(isActive);

  // Capability-based gating: explicit map (NOT a role set) so new backend roles
  // default to false and must be explicitly whitelisted. Prevents role-explosion
  // bugs where a new role accidentally inherits emitter capability.
  // Keep in sync with backend `CAN_TRIGGER_SOS` in app/api/emergency.py.
  const CAN_TRIGGER_SOS: Record<string, boolean> = {
    child:    true,
    kid:      true,
    woman:    true,
    elderly:  true,
    senior:   true,
    guardian: false,
    parent:   false,
    operator: false,
    admin:    false,
  };
  const role = (user?.role || '').toLowerCase();
  const sensorsEnabled = CAN_TRIGGER_SOS[role] === true;
  const [fallPending, setFallPending] = useState<{
    eventId: string;
    countdown: number;
    confidence: number;
  } | null>(null);
  const countdownRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    isActiveRef.current = isActive;
  }, [isActive]);

  // Fall confirmation handler
  const handleFallDetected = useCallback(async (confidence: number, signals: FallSignals) => {
    if (isActiveRef.current) return; // Already in emergency

    try {
      // Report fall to backend
      const res = await api.post('/sensors/fall', {
        lat: 0, lng: 0, // Will be updated with actual location
        ...signals,
      });

      if (res.data?.event_id) {
        setFallPending({
          eventId: res.data.event_id,
          countdown: AUTO_SOS_COUNTDOWN_S,
          confidence,
        });

        // Start countdown
        countdownRef.current = setInterval(() => {
          setFallPending(prev => {
            if (!prev) return null;
            const next = prev.countdown - 1;
            if (next <= 0) {
              // Auto-SOS
              triggerAutoSOS(prev.eventId);
              clearInterval(countdownRef.current!);
              return null;
            }
            return { ...prev, countdown: next };
          });
        }, 1000);
      }
    } catch (err) {
      console.error('Fall report error:', err);
    }
  }, []);

  const triggerAutoSOS = async (eventId: string) => {
    try {
      await api.post(`/sensors/fall/${eventId}/auto-sos`);
      const result = await triggerSilentSOS('1234', 'fall_detection');
      if (result.success && result.eventId) {
        await activate(result.eventId, 'fall_detection');
      }
    } catch (err) {
      console.error('Auto-SOS error:', err);
    }
  };

  const handleUserSafe = async () => {
    if (fallPending) {
      if (countdownRef.current) clearInterval(countdownRef.current);
      try {
        await api.post(`/sensors/fall/${fallPending.eventId}/resolve`, {
          resolved_by: 'user_confirmed_safe',
        });
      } catch {}
      setFallPending(null);
    }
  };

  const handleUserNeedsHelp = async () => {
    if (fallPending) {
      if (countdownRef.current) clearInterval(countdownRef.current);
      try {
        await api.post(`/sensors/fall/${fallPending.eventId}/resolve`, {
          resolved_by: 'user_called_help',
        });
      } catch {}
      const result = await triggerSilentSOS('1234', 'fall_detection');
      if (result.success && result.eventId) {
        await activate(result.eventId, 'fall_detection');
      }
      setFallPending(null);
    }
  };

  useEffect(() => {
    if (!token) return;

    let shakeCleanup: (() => void) | null = null;
    let fallCleanup: (() => void) | null = null;
    let pushCleanup: (() => void) | null = null;

    // Defer all native-sensor init so the app can render first.
    // If ANY call throws (permission denied / native module missing), we
    // log and continue — startup must NEVER crash because a sensor failed.
    const bootTimer = setTimeout(async () => {
      // 1. Restore persisted emergency state (reads AsyncStorage — safe)
      await safe('restore emergency state', async () => {
        const restored = await restore();
        if (restored) {
          await restoreEmergencyState();
        }
      });

      // 1b. Register push token for FCM notifications (works when app is killed)
      await safe('push registration', () => registerPushToken());
      const pushSub = await safe('push listeners', () =>
        setupPushListeners((data) => {
          console.log('[PUSH_DATA]', JSON.stringify(data).substring(0, 200));
        })
      );
      if (pushSub) pushCleanup = pushSub;

      // 2. Start global shake detection — IMMEDIATE SOS on shake
      //    Only for PROTECTED users (child/woman/elderly). Guardians never
      //    emit SOS from their own device sensors.
      if (sensorsEnabled) {
        const shakeSub = await safe('shake detection', () =>
          startShakeDetection(async () => {
            if (isActiveRef.current) return;
            if (useEmergencyStore.getState().isTriggering) return;

            try { Vibration.vibrate([0, 100, 50, 100]); } catch {}
            setTriggering(true);

            const result = await triggerSilentSOS('1234', 'shake');
            if (result.success && result.eventId) {
              await activate(result.eventId, 'shake');
            } else if (result.error === 'offline_queued') {
              await activate('pending', 'shake');
            }
            setTriggering(false);
          })
        );
        if (shakeSub) shakeCleanup = shakeSub;

        // 3. Start fall detection (5-stage Apple Watch-style pipeline)
        const fallSub = await safe('fall detection', () =>
          startFallDetection(handleFallDetected)
        );
        if (fallSub) fallCleanup = fallSub;

        // 4. NISCH-012 — continuous motion telemetry. Runs
        //    independently of fall detection (different sample
        //    rate, different feature window, different upload
        //    cadence). ADDITIVE — does not touch the fall pipeline.
        try {
          const { startMotionTelemetry } = await import('../services/motionTelemetryService');
          await startMotionTelemetry();
        } catch (err) {
          console.warn('[SAFETY] motion telemetry start failed:', err);
        }
      } else {
        console.log(`[SAFETY] Role="${role}" — sensors (shake + fall) disabled. This device only RECEIVES alerts.`);
      }

      // 4. Voice distress monitoring is INTENTIONALLY NOT auto-started on boot.
      //    It requires microphone permission + active audio recording which can
      //    crash the app on unsupported/permissionless devices.
      //    It is started only when the user explicitly begins a journey
      //    (see app/(tabs)/journey.tsx and hooks/useJourneyLifecycle.native.ts).
      console.log('[VOICE] Mic monitoring NOT started on boot — will start on Journey Begin');
    }, 800);

    return () => {
      clearTimeout(bootTimer);
      try { shakeCleanup?.(); } catch {}
      try { fallCleanup?.(); } catch {}
      try { pushCleanup?.(); } catch {}
      try { stopAudioMonitoring(); } catch {}
      try {
        // NISCH-012 — stop motion telemetry on provider unmount.
        // Dynamic import to keep the static graph clean.
        import('../services/motionTelemetryService').then(
          ({ stopMotionTelemetry }) => stopMotionTelemetry(),
        ).catch(() => {/* non-fatal */});
      } catch {}
      if (countdownRef.current) clearInterval(countdownRef.current);
    };
  }, [token, handleFallDetected, sensorsEnabled, role]);

  // Fall confirmation dialog overlay — only for protected users.
  useEffect(() => {
    if (!sensorsEnabled) return;
    if (fallPending) {
      Alert.alert(
        'Possible Fall Detected',
        `Are you okay? (${fallPending.countdown}s)\nConfidence: ${(fallPending.confidence * 100).toFixed(0)}%\n\nHelp will be sent automatically if no response.`,
        [
          { text: "I'm OK", style: 'cancel', onPress: handleUserSafe },
          { text: 'Send Help', style: 'destructive', onPress: handleUserNeedsHelp },
        ],
        { cancelable: false }
      );
    }
  }, [fallPending?.countdown, sensorsEnabled]);

  return <>{children}</>;
}
