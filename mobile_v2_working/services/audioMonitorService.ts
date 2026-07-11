// Voice Distress Audio Monitor — orchestrates voiceDistression.ts + location + API + countdown
//
// Wraps the existing voice distress detection pipeline and wires:
//  1. Location fetch on detection
//  2. POST /api/sensors/voice-distress report
//  3. 10-second "are you OK?" countdown
//  4. Auto-SOS on timeout
//  Pauses when Fake Call mode is active.

import { startVoiceMonitoring, stopVoiceMonitoring, isVoiceMonitoringActive, VoiceDistressData } from './voiceDistression';
import * as Location from 'expo-location';
import * as FileSystem from 'expo-file-system';
import api from './api';
import type { SafetyAlert, SensorCallbacks } from './sensorService';

// ── Internal State ──

let _onAlert: SensorCallbacks['onAlert'] | null = null;
let _onCountdown: SensorCallbacks['onCountdown'] | null = null;
let _onAutoSOS: SensorCallbacks['onAutoSOS'] | null = null;
let _countdownTimer: ReturnType<typeof setInterval> | null = null;
let _activeAlert: SafetyAlert | null = null;
let _cleanupFn: (() => void) | null = null;
let _fakeCallActive = false;
let _lastVoiceTriggerTime = 0;
const VOICE_TRIGGER_COOLDOWN_MS = 20000; // 20s between voice distress reports
const RAPID_FIRE_GUARD_MS = 5000;        // 5s guard against duplicate whisper triggers

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
  // SOS is triggered server-side by voice_distress_service (CRITICAL risk).
  // This countdown is UI-only feedback. Just resolve the event and notify UI.
  try {
    if (alert.eventId) {
      await api.post(`/sensors/voice-distress/${alert.eventId}/resolve`, {
        resolved_by: 'auto_sos_countdown_expired',
      });
    }
    console.log('[VoiceService] Auto-SOS countdown expired — backend handles SOS internally');
  } catch (e) {
    console.error('[VoiceService] Resolve after countdown failed:', e);
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

/**
 * Start audio monitoring for voice distress.
 * On distress detection: fetches location → reports → shows alert with countdown.
 */
export async function startAudioMonitoring(callbacks: SensorCallbacks): Promise<() => void> {
  _onAlert = callbacks.onAlert;
  _onCountdown = callbacks.onCountdown;
  _onAutoSOS = callbacks.onAutoSOS;

  console.log('[VOICE] Starting audio monitoring orchestrator...');

  const cleanup = await startVoiceMonitoring(async (distressData: VoiceDistressData) => {
    if (_fakeCallActive) {
      console.log('[VOICE] Fake call active — skipping distress report');
      return;
    }

    // 20s cooldown — prevent rapid-fire triggers from consecutive scream cycles
    const now = Date.now();
    if (now - _lastVoiceTriggerTime < VOICE_TRIGGER_COOLDOWN_MS) {
      console.log(`[VOICE_DUPLICATE_SUPPRESSED] Cooldown ${Math.ceil((VOICE_TRIGGER_COOLDOWN_MS - (now - _lastVoiceTriggerTime)) / 1000)}s remaining`);
      return;
    }
    // 5s rapid-fire guard — catches duplicate whisper triggers before incident lock kicks in
    if (_lastVoiceTriggerTime && now - _lastVoiceTriggerTime < RAPID_FIRE_GUARD_MS) {
      console.log('[VOICE_DUPLICATE_SUPPRESSED] Rapid-fire guard (5s)');
      return;
    }
    _lastVoiceTriggerTime = now;

    console.log('[VOICE] Distress detected — fetching location and reporting...');
    const location = await getLocation();

    // Read audio file as base64 for Whisper transcription
    let audioBase64: string | undefined;
    if (distressData.audio_uri) {
      try {
        const raw = await FileSystem.readAsStringAsync(distressData.audio_uri, {
          encoding: 'base64',
        });
        // Empty audio guard — skip garbage payloads
        if (raw && raw.length >= 1000) {
          audioBase64 = raw;
          console.log(`[VOICE] Audio encoded: ${(audioBase64.length / 1024).toFixed(1)}KB base64`);
        } else {
          console.log('[VOICE] Empty audio — skipping');
        }
      } catch (e) {
        console.warn('[VOICE] Failed to read audio file:', e);
      }
    }

    let eventId: string | undefined;
    try {
      const res = await api.post('/sensors/voice-distress', {
        lat: location?.lat ?? 0,
        lng: location?.lng ?? 0,
        keywords: distressData.keywords,
        scream_detected: distressData.scream_detected,
        repeated: distressData.repeated,
        audio_features: distressData.audio_features,
        audio_base64: audioBase64 || null,
        confidence: distressData.confidence,
        trigger_type: distressData.trigger_type,
      });
      eventId = res.data?.event_id;
      if (res.data?.whisper_transcript) {
        console.log(`[VOICE] Whisper: "${res.data.whisper_transcript}"`);
      }
      if (res.data?.risk_level) {
        console.log(`[VOICE] Risk: ${res.data.risk_level} Score: ${res.data.distress_score} Confidence: ${distressData.confidence.toFixed(3)}`);
      }
    } catch (e) {
      console.error('[VoiceService] Report failed:', e);
    }

    const alert: SafetyAlert = {
      id: `voice-${Date.now()}`,
      type: 'voice',
      message: 'Distress sound detected — are you OK?',
      timestamp: Date.now(),
      countdownSeconds: 10,
      secondsRemaining: 10,
      eventId,
      location: location ?? undefined,
      data: distressData as unknown as Record<string, unknown>,
    };

    _activeAlert = alert;
    _onAlert?.(alert);
    startCountdown(alert);
  });

  _cleanupFn = cleanup;
  return () => stopAudioMonitoring();
}

/**
 * User tapped "I'm OK" — resolve voice distress event.
 */
export async function dismissVoiceAlert(alertId: string): Promise<void> {
  clearCountdown();
  const alert = _activeAlert;
  if (alert?.eventId) {
    try {
      await api.post(`/sensors/voice-distress/${alert.eventId}/resolve`, {
        resolved_by: 'user_safe',
      });
    } catch {}
  }
  _activeAlert = null;
}

export function setFakeCallActive(active: boolean): void {
  _fakeCallActive = active;
}

export function stopAudioMonitoring(): void {
  clearCountdown();
  stopVoiceMonitoring();
  if (_cleanupFn) _cleanupFn();
  _cleanupFn = null;
  _onAlert = null;
  _onCountdown = null;
  _onAutoSOS = null;
  _activeAlert = null;
}

export { isVoiceMonitoringActive };
