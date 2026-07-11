// Audio Service — lightweight amplitude-spike distress trigger.
//
// NOT continuous streaming. We sample short 2s windows every 10s and
// look at peak metering to detect scream/distress. When a spike is
// detected AND score exceeds threshold, we publish a `voice_distress`
// event to the backend via journeyService.
//
// Migrated from `expo-av` (SDK 54) → `expo-audio` (SDK 55). Recording
// status is now polled via `recorder.getStatus()` every 200ms rather
// than a `setOnRecordingStatusUpdate` callback.

import {
  AudioModule,
  requestRecordingPermissionsAsync,
  setAudioModeAsync,
  RecordingPresets,
  type AudioRecorder,
} from 'expo-audio';
import { sendEvent, sendSOS } from './journeyService';
import { useJourneyEngineStore } from '../stores/journeyEngineStore';

const SAMPLE_WINDOW_MS = 2_000;
const SAMPLE_INTERVAL_MS = 10_000;
// Metering is in dBFS — 0 is max, -160 is silent. Scream is usually > -10 dBFS peak.
const SPIKE_DBFS_THRESHOLD = -12;
// Score threshold at which we escalate to SOS (critical)
const SOS_SCORE_THRESHOLD = 0.9;
// Normal distress event threshold
const ALERT_SCORE_THRESHOLD = 0.5;
// Metering poll interval while recording (expo-audio doesn't emit metering
// via the recording status event; we poll `getStatus()` instead).
const METERING_POLL_MS = 200;

let _recorder: AudioRecorder | null = null;
let _sampleTimer: ReturnType<typeof setTimeout> | null = null;
let _active = false;
let _sessionId = 'default';
let _lastDistressAt = 0;
const DISTRESS_COOLDOWN_MS = 20_000;

export function setAudioSessionId(sid: string): void {
  _sessionId = sid;
}

export async function ensureMicPermission(): Promise<boolean> {
  try {
    const resp = await requestRecordingPermissionsAsync();
    if (resp.status !== 'granted') {
      console.warn('[AUDIO_SVC] mic permission denied');
      return false;
    }
    try {
      await setAudioModeAsync({
        allowsRecording: true,
        playsInSilentMode: true,
        shouldPlayInBackground: false,
        interruptionMode: 'duckOthers',
      });
    } catch (e) {
      console.warn('[AUDIO_SVC] setAudioModeAsync failed (continuing):', (e as any)?.message || e);
    }
    return true;
  } catch (e) {
    console.warn('[AUDIO_SVC] permission error', e);
    return false;
  }
}

export async function startAudioMonitoring(sessionId: string): Promise<boolean> {
  _sessionId = sessionId;
  if (_active) return true;
  const ok = await ensureMicPermission();
  if (!ok) return false;
  _active = true;
  console.log('[AUDIO_SVC] monitoring started');
  scheduleNextSample(500);
  return true;
}

export async function stopAudioMonitoring(): Promise<void> {
  _active = false;
  if (_sampleTimer) {
    clearTimeout(_sampleTimer);
    _sampleTimer = null;
  }
  await cleanupRecorder();
  console.log('[AUDIO_SVC] monitoring stopped');
}

function scheduleNextSample(delayMs: number): void {
  if (!_active) return;
  if (_sampleTimer) clearTimeout(_sampleTimer);
  _sampleTimer = setTimeout(() => {
    void takeSample();
  }, delayMs);
}

async function cleanupRecorder(): Promise<void> {
  if (_recorder) {
    const r = _recorder;
    _recorder = null;
    try {
      if (r.isRecording) {
        await r.stop();
      }
    } catch {
      // Stop may fail if not started — safe to ignore.
    }
  }
}

async function takeSample(): Promise<void> {
  if (!_active) return;
  let peakDbfs: number | null = null;
  let pollTimer: ReturnType<typeof setInterval> | null = null;
  try {
    await cleanupRecorder();

    // Create + prepare the recorder WITH metering enabled.
    const recorder = new AudioModule.AudioRecorder({
      ...RecordingPresets.LOW_QUALITY,
      isMeteringEnabled: true,
    });
    await recorder.prepareToRecordAsync({
      ...RecordingPresets.LOW_QUALITY,
      isMeteringEnabled: true,
    });
    _recorder = recorder;
    recorder.record();

    // Poll `getStatus()` for metering — expo-audio doesn't surface
    // metering through the recordingStatusUpdate event.
    pollTimer = setInterval(() => {
      try {
        const s = recorder.getStatus();
        if (s.isRecording && typeof s.metering === 'number') {
          const m = s.metering;
          if (peakDbfs == null || m > peakDbfs) peakDbfs = m;
        }
      } catch { /* ignore transient status errors */ }
    }, METERING_POLL_MS);

    // Record for a short window
    await new Promise((r) => setTimeout(r, SAMPLE_WINDOW_MS));

    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    await cleanupRecorder();
  } catch (e: any) {
    console.warn('[AUDIO_SVC] sample failed', e?.message);
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    await cleanupRecorder();
    scheduleNextSample(Math.min(SAMPLE_INTERVAL_MS * 2, 30_000));
    return;
  }

  // Evaluate
  if (peakDbfs != null && peakDbfs > SPIKE_DBFS_THRESHOLD) {
    const score = amplitudeToScore(peakDbfs);
    await onDistressDetected(score, peakDbfs);
  }

  scheduleNextSample(SAMPLE_INTERVAL_MS);
}

function amplitudeToScore(peakDbfs: number): number {
  // Map dBFS [-12 .. 0] → [0.4 .. 1.0]
  const clamped = Math.max(-30, Math.min(0, peakDbfs));
  const normalized = (clamped + 12) / 12; // -12 → 0, 0 → 1
  return Math.max(0, Math.min(1, 0.4 + 0.6 * normalized));
}

async function onDistressDetected(score: number, peakDbfs: number): Promise<void> {
  const now = Date.now();
  if (now - _lastDistressAt < DISTRESS_COOLDOWN_MS) {
    console.log('[AUDIO_SVC] distress suppressed (cooldown)');
    return;
  }
  _lastDistressAt = now;

  console.warn(`[AUDIO_SVC] DISTRESS score=${score.toFixed(2)} peak=${peakDbfs}dBFS`);

  if (score >= SOS_SCORE_THRESHOLD) {
    const loc = useJourneyEngineStore.getState().lastLocation;
    await sendSOS({
      sessionId: _sessionId,
      riskLevel: 'critical',
      riskScore: Math.round(score * 100),
      location: loc ? { lat: loc.lat, lng: loc.lng } : null,
      meta: { trigger: 'voice_distress', peak_dbfs: peakDbfs },
    });
    return;
  }

  if (score >= ALERT_SCORE_THRESHOLD) {
    await sendEvent('voice_distress', {
      sessionId: _sessionId,
      score,
      peak_dbfs: peakDbfs,
      timestamp: now,
    });
  }
}
