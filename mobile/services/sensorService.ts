// Fall Detection Sensor Service — orchestrates fallDetection.ts + location + API + countdown
//
// Wraps the existing 5-stage fall detection pipeline and wires:
//  1. Location fetch on detection
//  2. POST /api/sensors/fall report
//  3. 10-second "are you OK?" countdown
//  4. Auto-SOS on timeout via POST /api/sensors/fall/{id}/auto-sos

import { startFallDetection, stopFallDetection, isFallDetectionActive, FallSignals } from './fallDetection';
import * as Location from 'expo-location';
import api from './api';

// ── Shared Alert Types ──

export type AlertType = 'fall' | 'voice' | 'wandering';

export interface SafetyAlert {
  id: string;
  type: AlertType;
  message: string;
  timestamp: number;
  countdownSeconds: number;
  secondsRemaining: number;
  eventId?: string;
  location?: { lat: number; lng: number };
  data?: Record<string, unknown>;
  /** Extra buttons beyond "I'm OK" */
  actions?: { label: string; key: string }[];
}

// ── Internal State ──

let _onAlert: ((alert: SafetyAlert) => void) | null = null;
let _onCountdown: ((alertId: string, remaining: number) => void) | null = null;
let _onAutoSOS: ((alertId: string) => void) | null = null;
let _countdownTimer: ReturnType<typeof setInterval> | null = null;
let _activeAlert: SafetyAlert | null = null;

// ── Helpers ──

async function getLocation(): Promise<{ lat: number; lng: number } | null> {
  try {
    const { status } = await Location.requestForegroundPermissionsAsync();
    if (status !== 'granted') return null;
    const loc = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High });
    return { lat: loc.coords.latitude, lng: loc.coords.longitude };
  } catch {
    return null;
  }
}

function clearCountdown() {
  if (_countdownTimer) {
    clearInterval(_countdownTimer);
    _countdownTimer = null;
  }
}

async function triggerAutoSOS(alert: SafetyAlert) {
  clearCountdown();
  try {
    if (alert.eventId) {
      await api.post(`/sensors/fall/${alert.eventId}/auto-sos`);
    } else {
      await api.post('/sos/trigger', {
        trigger_type: 'auto',
        lat: alert.location?.lat ?? 0,
        lng: alert.location?.lng ?? 0,
      });
    }
  } catch (e) {
    console.error('[FallService] Auto-SOS failed:', e);
  }
  _onAutoSOS?.(alert.id);
  _activeAlert = null;
}

function startCountdown(alert: SafetyAlert) {
  clearCountdown();
  let remaining = alert.countdownSeconds;

  _countdownTimer = setInterval(() => {
    remaining -= 1;
    _onCountdown?.(alert.id, remaining);

    if (remaining <= 0) {
      clearCountdown();
      triggerAutoSOS(alert);
    }
  }, 1000);
}

// ── Public API ──

export interface SensorCallbacks {
  onAlert: (alert: SafetyAlert) => void;
  onCountdown: (alertId: string, remaining: number) => void;
  onAutoSOS: (alertId: string) => void;
}

/**
 * Start fall detection monitoring.
 * Subscribes to accelerometer + gyroscope.
 * On detection: fetches location → reports to backend → shows alert with countdown.
 */
export function startSensorMonitoring(callbacks: SensorCallbacks): () => void {
  _onAlert = callbacks.onAlert;
  _onCountdown = callbacks.onCountdown;
  _onAutoSOS = callbacks.onAutoSOS;

  const cleanup = startFallDetection(async (confidence: number, signals: FallSignals) => {
    const location = await getLocation();

    // SF-01 v2 Day 2 — emit live motion signal alongside the existing
    // /sensors/fall report. /signals/motion is the lightweight
    // composite-recalc surface; the existing fall endpoint is the
    // canonical audit row. Both run — additive contract.
    try {
      await api.post('/signals/motion', {
        fall: confidence,
        voice_distress: 0,
        lat: location?.lat ?? 0,
        lng: location?.lng ?? 0,
      });
    } catch (e) {
      // Non-fatal — the 5-min ledger still captures motion windows
      // and the canonical /sensors/fall call below records the event.
      console.warn('[FallService] /signals/motion emit failed:', (e as any)?.message || e);
    }

    let eventId: string | undefined;
    try {
      const res = await api.post('/sensors/fall', {
        lat: location?.lat ?? 0,
        lng: location?.lng ?? 0,
        impact_score: signals.impact_score,
        freefall_score: signals.freefall_score,
        orientation_score: signals.orientation_score,
        post_impact_score: signals.post_impact_score,
        immobility_score: signals.immobility_score,
      });
      eventId = res.data?.event_id;
    } catch (e) {
      console.error('[FallService] Report failed:', e);
    }

    const alert: SafetyAlert = {
      id: `fall-${Date.now()}`,
      type: 'fall',
      message: 'Fall detected — are you OK?',
      timestamp: Date.now(),
      countdownSeconds: 10,
      secondsRemaining: 10,
      eventId,
      location: location ?? undefined,
      data: { confidence, ...signals },
    };

    _activeAlert = alert;
    _onAlert?.(alert);
    startCountdown(alert);
  });

  return () => {
    cleanup();
    stopSensorMonitoring();
  };
}

/**
 * User tapped "I'm OK" — resolve the fall event and clear countdown.
 */
export async function dismissFallAlert(alertId: string): Promise<void> {
  clearCountdown();
  const alert = _activeAlert;
  if (alert?.eventId) {
    try {
      await api.post(`/sensors/fall/${alert.eventId}/resolve`, {
        resolved_by: 'user_confirmed_safe',
      });
    } catch {}
  }
  _activeAlert = null;
}

export function stopSensorMonitoring(): void {
  clearCountdown();
  stopFallDetection();
  _onAlert = null;
  _onCountdown = null;
  _onAutoSOS = null;
  _activeAlert = null;
}

export { isFallDetectionActive };
