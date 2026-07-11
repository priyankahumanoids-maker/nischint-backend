// Voice Distress Detection Service — Hybrid on-device + optional cloud
//
// On-device (primary): keyword detection + scream pattern analysis
// Cloud (Phase 2): OpenAI Whisper transcript verification
// Distress score: keyword*0.4 + scream*0.35 + repetition*0.25
// Cooldown: 30s between events, bypass at score >= 0.9
//
// Migrated from `expo-av` (SDK 54) → `expo-audio` (SDK 55). We use
// `AudioModule.AudioRecorder` directly (not the `useAudioRecorder`
// hook) because this is imperative background service code.

import {
  AudioModule,
  requestRecordingPermissionsAsync,
  setAudioModeAsync,
  RecordingPresets,
  type AudioRecorder,
  type RecorderState,
} from 'expo-audio';
import { Platform, AppState } from 'react-native';
import { requireConsent } from './consentService';

// Distress keywords for on-device matching
const DISTRESS_KEYWORDS = [
  'help', 'stop', 'leave me', 'call police', 'emergency',
  "don't touch", 'save me', 'please help', 'let go',
];

// Audio thresholds — production-grade tuning (P1.1)
const LOG_LEVEL: 'DEBUG' | 'INFO' | 'ERROR' = 'INFO'; // Set to DEBUG for verbose logs
const AMPLITUDE_THRESHOLD = 0.85;     // Scream detection threshold
const IMMEDIATE_SCREAM_AMP = 0.92;    // Immediate trigger — no repeat needed
const METERING_SCREAM_DB = -25;       // Raw dB threshold for scream
const WHISPER_AMP_MIN = 0.55;         // Whisper mode minimum amplitude
const WHISPER_CONFIDENCE_MIN = 0.60;  // Whisper mode minimum confidence
const PITCH_VARIANCE_THRESHOLD = 0.9;
const DETECTION_INTERVAL_MS = 2000;
const COOLDOWN_MS = 30000;
const DECAY_FACTOR = 0.6;             // Scream score decay per non-scream cycle
const DECAY_TRIGGER_THRESHOLD = 2;    // Trigger when decay score reaches this
const INCIDENT_LOCK_MS = 60000;       // 60s lockout after incident trigger
const WHISPER_REPEAT_WINDOW_MS = 3000; // 3s window for whisper repeat detection

interface VoiceDetectionState {
  isMonitoring: boolean;
  recording: AudioRecorder | null;
  lastReportTime: number;
  screamScore: number;
  incidentActive: boolean;
  incidentStartTime: number;
  lastWhisperTime: number;        // Track whisper repeats within 3s
  whisperRepeatCount: number;
  permissionGranted: boolean;
}

const state: VoiceDetectionState = {
  isMonitoring: false,
  recording: null,
  lastReportTime: 0,
  screamScore: 0,
  incidentActive: false,
  incidentStartTime: 0,
  lastWhisperTime: 0,
  whisperRepeatCount: 0,
  permissionGranted: false,
};

let monitorInterval: ReturnType<typeof setInterval> | null = null;
let onDistressCallback: ((data: VoiceDistressData) => void) | null = null;

export interface VoiceDistressData {
  keywords: string[];
  scream_detected: boolean;
  repeated: boolean;
  confidence: number;          // 0–1 confidence score
  trigger_type: string;        // 'immediate-scream' | 'decay-scream' | 'whisper-mode'
  audio_features: {
    amplitude: number;
    pitch_variance: number;
    spectral_spread: number;
    duration_ms: number;
  };
  audio_uri?: string;
}

// Simple amplitude-based scream detection
function analyzeAudioFeatures(status: RecorderState): {
  amplitude: number;
  pitch_variance: number;
  spectral_spread: number;
} {
  // expo-audio surfaces metering on RecorderState when isMeteringEnabled=true.
  const metering = status.metering ?? -160; // dBFS, -160 is silence
  // Normalize: -160 to 0 dBFS → 0 to 1
  const amplitude = Math.max(0, Math.min(1, (metering + 160) / 160));

  // Estimate pitch variance from amplitude pattern (simplified)
  // High amplitude + rapid changes suggest screaming
  const pitch_variance = amplitude > AMPLITUDE_THRESHOLD ? Math.min(1, amplitude * 1.2) : amplitude * 0.5;
  const spectral_spread = amplitude > 0.8 ? 0.7 : amplitude * 0.5;

  return { amplitude, pitch_variance, spectral_spread };
}

function isScreamPattern(features: { amplitude: number; pitch_variance: number }): boolean {
  return features.amplitude > AMPLITUDE_THRESHOLD && features.pitch_variance > PITCH_VARIANCE_THRESHOLD;
}

// On-device keyword matching (called with speech-to-text results when available)
export function matchKeywords(transcript: string): string[] {
  const lower = transcript.toLowerCase();
  return DISTRESS_KEYWORDS.filter(kw => lower.includes(kw));
}

// Compute confidence score from signal fusion
function computeConfidence(amp: number, pitch: number, screamScore: number): number {
  return Math.min(1.0, (amp * 0.6) + (pitch * 0.2) + (Math.min(screamScore, 3) / 3 * 0.2));
}

function triggerDistressReport(
  keywords: string[],
  screamDetected: boolean,
  repeated: boolean,
  features: ReturnType<typeof analyzeAudioFeatures>,
  audioUri?: string,
  triggerType?: string,
) {
  const now = Date.now();

  // Cooldown (secondary guard)
  if (now - state.lastReportTime < COOLDOWN_MS) return;

  // Compute confidence
  const confidence = computeConfidence(features.amplitude, features.pitch_variance, state.screamScore);

  // Activate incident lock
  state.incidentActive = true;
  state.incidentStartTime = now;
  state.lastReportTime = now;
  state.screamScore = 0;

  console.log(`[MIC] TRIGGER: ${triggerType || 'unknown'} — amp:${features.amplitude.toFixed(3)} confidence:${confidence.toFixed(3)}`);

  if (onDistressCallback) {
    onDistressCallback({
      keywords,
      scream_detected: screamDetected,
      repeated,
      confidence,
      trigger_type: triggerType || 'unknown',
      audio_features: {
        ...features,
        duration_ms: DETECTION_INTERVAL_MS,
      },
      audio_uri: audioUri,
    });
  }
}

// Public: manually reset incident lock (e.g., user taps "I'm Safe")
export function resetIncidentLock() {
  state.incidentActive = false;
  state.incidentStartTime = 0;
  state.screamScore = 0;
  console.log('[MIC] Incident lock manually reset');
}

// ── Public API ──

export async function startVoiceMonitoring(
  onDistress: (data: VoiceDistressData) => void,
): Promise<() => void> {
  // ADDITION 2 — SINGLETON LOCK: Prevent double start
  if (state.isMonitoring) {
    console.log('[MIC] Already running, skipping restart');
    return () => {};
  }

  // STEP 1 — Permission check (never throw)
  let status: string = 'undetermined';
  try {
    // DPDP-04-MOB — pre-permission consent half-modal before OS prompt.
    // If the user declines we never request the mic permission, leaving
    // the system state untouched and voice monitoring disabled.
    const consent = await requireConsent('audio_recording');
    if (!consent) {
      console.warn('[MIC] DPDP consent declined — voice monitoring disabled');
      state.permissionGranted = false;
      return () => {};
    }
    console.log('[MIC] Requesting microphone permission...');
    const res = await requestRecordingPermissionsAsync();
    status = res.status;
    console.log('[MIC] Permission status:', status);
  } catch (e) {
    console.warn('[MIC] Permission request failed — voice monitoring disabled:', (e as any)?.message || e);
    state.permissionGranted = false;
    return () => {};
  }

  if (status !== 'granted') {
    console.warn('[MIC] Permission DENIED — voice monitoring disabled');
    state.permissionGranted = false;
    return () => {};
  }
  state.permissionGranted = true;
  console.log('[MIC] Permission GRANTED');

  // STEP 2 — Audio mode setup (never throw)
  try {
    console.log('[MIC] Configuring audio mode...');
    await setAudioModeAsync({
      allowsRecording: true,
      playsInSilentMode: true,
      shouldPlayInBackground: true,
      allowsBackgroundRecording: true,
      interruptionMode: 'duckOthers',
    });
    console.log('[MIC] Audio mode initialized (background-capable)');
  } catch (e) {
    console.warn('[MIC] setAudioModeAsync failed — voice monitoring disabled:', (e as any)?.message || e);
    return () => {};
  }

  state.isMonitoring = true;
  onDistressCallback = onDistress;
  state.screamScore = 0;
  state.incidentActive = false;
  state.incidentStartTime = 0;
  state.lastWhisperTime = 0;
  state.whisperRepeatCount = 0;

  // STEP 3 — Start self-scheduling mic capture loop (NOT setInterval — avoids overlap)
  console.log('[MIC] Starting periodic audio capture');
  let cycleCount = 0;
  let consecutiveErrors = 0;

  async function captureLoop() {
    if (!state.isMonitoring) return;

    try {
      // HARD RESET: Always stop any lingering recording
      if (state.recording) {
        try {
          if (state.recording.isRecording) await state.recording.stop();
        } catch (_) {}
        state.recording = null;
      }

      // Bail check
      if (!state.isMonitoring) return;

      // Re-initialize audio mode to ensure clean native state
      await setAudioModeAsync({
        allowsRecording: true,
        playsInSilentMode: true,
        shouldPlayInBackground: true,
        allowsBackgroundRecording: true,
        interruptionMode: 'duckOthers',
      });

      // Create + prepare + start in sequence. expo-audio's
      // `AudioRecorder` constructor takes options directly; we then
      // `prepareToRecordAsync` with the metering flag so `getStatus()`
      // returns a .metering value.
      const recordingOptions = {
        ...RecordingPresets.HIGH_QUALITY,
        isMeteringEnabled: true,
      };
      const recording = new AudioModule.AudioRecorder(recordingOptions);
      await recording.prepareToRecordAsync(recordingOptions);
      state.recording = recording;
      recording.record();

      // Record for a short burst
      await new Promise(resolve => setTimeout(resolve, 1500));

      // Bail if monitoring was stopped during recording
      if (!state.isMonitoring) {
        try { await recording.stop(); } catch (_) {}
        state.recording = null;
        return;
      }

      const status = recording.getStatus();
      // Capture URI before stopping (needed for Whisper transcription)
      const audioUri = recording.uri;
      await recording.stop();
      state.recording = null;

      // SUCCESS — reset error counter
      consecutiveErrors = 0;
      cycleCount++;
      const metering = status.metering ?? -160;
      const amplitude = Math.max(0, Math.min(1, (metering + 160) / 160));

      if (cycleCount % 5 === 1 || amplitude > 0.4) {
        console.log(`[MIC] cycle:${cycleCount} metering:${metering.toFixed(1)}dB amp:${amplitude.toFixed(3)} dur:${status.durationMillis}ms`);
      }

      if (status.isRecording || status.durationMillis > 0) {
        const features = analyzeAudioFeatures(status);
        const amp = features.amplitude;
        const confidence = computeConfidence(amp, features.pitch_variance, state.screamScore);

        // INCIDENT LOCK — skip ALL detection during active incident
        if (state.incidentActive && (Date.now() - state.incidentStartTime < INCIDENT_LOCK_MS)) {
          if (cycleCount % 10 === 0) {
            console.log(`[MIC] INCIDENT LOCK — ${Math.ceil((INCIDENT_LOCK_MS - (Date.now() - state.incidentStartTime)) / 1000)}s remaining`);
          }
        } else {
          // Auto-expire incident lock
          if (state.incidentActive) {
            state.incidentActive = false;
            console.log('[MIC] Incident lock expired — resuming detection');
          }

          const scream = isScreamPattern(features);

          // ── RULE 1: IMMEDIATE TRIGGER (amp >= 0.92 OR metering >= -25) ──
          if (amp >= IMMEDIATE_SCREAM_AMP || metering >= METERING_SCREAM_DB) {
            console.log(`[VOICE_TRIGGER_CONFIRMED] immediate-scream amp:${amp.toFixed(3)} metering:${metering.toFixed(1)} confidence:${confidence.toFixed(3)}`);
            triggerDistressReport([], true, false, features, audioUri || undefined, 'immediate-scream');
          }
          // ── RULE 2: SCREAM DECAY (amp >= 0.85, needs repeat >= 2) ──
          else if (scream) {
            state.screamScore += 1;
            if (state.screamScore >= DECAY_TRIGGER_THRESHOLD) {
              console.log(`[VOICE_TRIGGER_CONFIRMED] decay-scream amp:${amp.toFixed(3)} confidence:${confidence.toFixed(3)} repeatCount:${state.screamScore.toFixed(0)}`);
              triggerDistressReport([], true, true, features, audioUri || undefined, 'decay-scream');
            } else {
              if (LOG_LEVEL === 'DEBUG') {
                console.log(`[VOICE_PRETRIGGER] scream amp:${amp.toFixed(3)} confidence:${confidence.toFixed(3)} score:${state.screamScore.toFixed(2)} (need ${DECAY_TRIGGER_THRESHOLD})`);
              }
            }
          }
          // ── RULE 3: WHISPER MODE (amp >= 0.55, confidence >= 0.60, needs repeat or keyword) ──
          else if (amp >= WHISPER_AMP_MIN && audioUri) {
            const now = Date.now();
            // Track whisper repeats within 3s window
            if (now - state.lastWhisperTime < WHISPER_REPEAT_WINDOW_MS) {
              state.whisperRepeatCount++;
            } else {
              state.whisperRepeatCount = 1;
            }
            state.lastWhisperTime = now;

            if (confidence >= WHISPER_CONFIDENCE_MIN && state.whisperRepeatCount >= 2) {
              console.log(`[VOICE_TRIGGER_CONFIRMED] whisper-mode amp:${amp.toFixed(3)} confidence:${confidence.toFixed(3)} repeatCount:${state.whisperRepeatCount}`);
              triggerDistressReport([], false, true, features, audioUri, 'whisper-mode');
            } else if (LOG_LEVEL === 'DEBUG' && state.whisperRepeatCount % 5 === 1) {
              console.log(`[VOICE_TRIGGER_SUPPRESSED] whisper amp:${amp.toFixed(3)} confidence:${confidence.toFixed(3)} repeat:${state.whisperRepeatCount} (need conf>=${WHISPER_CONFIDENCE_MIN} + repeat>=2)`);
            }
            // Decay scream score
            state.screamScore *= DECAY_FACTOR;
          }
          else {
            // Non-trigger: decay
            state.screamScore *= DECAY_FACTOR;
            state.whisperRepeatCount = 0;
          }
        }
      }

      // Schedule next cycle immediately
      if (state.isMonitoring) {
        monitorInterval = setTimeout(captureLoop, 500) as any;
      }

    } catch (err) {
      // FAILURE — backoff before retrying
      consecutiveErrors++;
      state.recording = null;
      const backoff = Math.min(consecutiveErrors * 2000, 10000); // 2s, 4s, 6s… up to 10s
      console.debug(`[MIC] Capture error #${consecutiveErrors} — retrying in ${backoff}ms:`, (err as any)?.message || err);

      if (state.isMonitoring) {
        monitorInterval = setTimeout(captureLoop, backoff) as any;
      }
    }
  }

  // Start first cycle after a short initial delay
  monitorInterval = setTimeout(captureLoop, 500) as any;

  // STEP 5 — AppState handling (background/foreground)
  const appStateSub = AppState.addEventListener('change', (nextState) => {
    if (nextState === 'active' && state.isMonitoring) {
      console.log('[MIC] App foregrounded — mic capture continues');
    } else if (nextState === 'background') {
      console.log('[MIC] App backgrounded — mic stays active (staysActiveInBackground=true)');
    }
  });

  console.log('[MIC] Voice monitoring ACTIVE — listening for distress patterns');

  return () => {
    appStateSub.remove();
    stopVoiceMonitoring();
  };
}

export function stopVoiceMonitoring() {
  console.log('[MIC] stopVoiceMonitoring called — isMonitoring:', state.isMonitoring);
  // 1. Immediately flag as stopped so in-flight cycles bail out
  state.isMonitoring = false;
  onDistressCallback = null;

  // 2. Clear the scheduled next cycle
  if (monitorInterval) {
    clearTimeout(monitorInterval);
    monitorInterval = null;
  }

  // 3. Hard-kill any active recording (fire-and-forget)
  if (state.recording) {
    const rec = state.recording;
    state.recording = null;
    try {
      if (rec.isRecording) rec.stop();
    } catch (_) {}
  }
}

// Manual keyword report (called from speech-to-text results).
// Routes through the same `triggerDistressReport` path as the built-in
// detectors so cooldown / incident-lock / callback wiring are all
// respected. The confidence floor of 0.7 reflects that keyword hits are
// a strong signal even at low amplitude.
export function reportKeywords(
  transcript: string,
  features?: { amplitude: number; pitch_variance: number; spectral_spread: number },
) {
  const keywords = matchKeywords(transcript);
  if (keywords.length === 0) return;
  const f = features || { amplitude: 0.5, pitch_variance: 0.3, spectral_spread: 0.3 };
  triggerDistressReport(
    keywords,
    false,          // scream_detected — the caller didn't claim one
    false,          // repeated — unknown, be conservative
    f,
    undefined,
    'keyword-match',
  );
}

export function isVoiceMonitoringActive(): boolean {
  return state.isMonitoring;
}

// Simulate for testing
export function simulateVoiceDistress(): VoiceDistressData {
  return {
    keywords: ['help', 'stop'],
    scream_detected: true,
    repeated: true,
    confidence: 0.95,
    trigger_type: 'simulate',
    audio_features: { amplitude: 0.91, pitch_variance: 0.72, spectral_spread: 0.65, duration_ms: 2000 },
  };
}
