// Fall Detection Service — Apple Watch-style 5-stage pipeline
//
// Stages: Free-fall → Impact → Orientation change → Post-impact → Immobility
// Confidence scoring: impact*0.30 + freefall*0.20 + orientation*0.20 + post_impact*0.10 + immobility*0.20
// Cooldown: 60s between detections

import { Accelerometer, Gyroscope } from 'expo-sensors';
import { Vibration, Platform } from 'react-native';
import * as Location from 'expo-location';

// ── Thresholds ──
const IMPACT_THRESHOLD_G = 2.7;
const FREEFALL_THRESHOLD_G = 0.5;
const ORIENTATION_THRESHOLD_DEG = 60;
const POST_IMPACT_THRESHOLD_G = 0.3;
const IMMOBILITY_THRESHOLD_G = 0.05;

const FREEFALL_WINDOW_MS = 500;
const POST_IMPACT_WINDOW_MS = 5000;
const IMMOBILITY_WINDOW_MS = 10000;
const RECOVERY_CANCEL_MS = 5000;
const COOLDOWN_MS = 60000;
const SENSOR_INTERVAL_MS = 50; // 20Hz

// SF-01 v2 Day 1 — Phase 2 false-positive guards.
//
// Two independent checks must pass *after* the accel impact spike,
// before we credit it as a real fall:
//
//   1. Gyro confirmation — angular velocity must exceed
//      GYRO_CONFIRM_THRESHOLD_RAD_S (= 120 °/s = 2.094 rad/s)
//      within GYRO_CONFIRM_WINDOW_MS (= 500 ms) of the spike.
//      Rationale: a real fall tumbles the body axis fast; sitting
//      down hard, dropping the phone on a desk, or running do NOT.
//
//   2. GPS-speed suppression — if the device is travelling faster
//      than GPS_SPEED_SUPPRESS_KMH (= 20 km/h) when the spike hits,
//      we ignore it entirely. Rationale: vehicle deceleration /
//      potholes generate accel + gyro spikes that look like falls.
const GYRO_CONFIRM_THRESHOLD_RAD_S = 2.094; // 120 °/s
const GYRO_CONFIRM_WINDOW_MS = 500;
const GPS_SPEED_SUPPRESS_KMH = 20;

// Confidence weights
const W_IMPACT = 0.30;
const W_FREEFALL = 0.20;
const W_ORIENTATION = 0.20;
const W_POST_IMPACT = 0.10;
const W_IMMOBILITY = 0.20;
const CONFIDENCE_THRESHOLD = 0.75;

// ── State ──
interface FallDetectionState {
  isMonitoring: boolean;
  lastFallTime: number;

  // Stage signals
  freefallDetected: boolean;
  freefallTime: number;
  impactDetected: boolean;
  impactTime: number;
  impactMagnitude: number;
  orientationChanged: boolean;
  orientationDelta: number;
  postImpactMotion: boolean;
  immobilityDetected: boolean;

  // Tracking
  baselineOrientation: { alpha: number; beta: number; gamma: number } | null;
  immobilityStart: number;
  postImpactSamples: number[];
  immobilitySamples: number[];

  // Timers
  immobilityTimer: ReturnType<typeof setTimeout> | null;
  recoveryTimer: ReturnType<typeof setTimeout> | null;

  // SF-01 v2 Day 1 — FP guard state
  lastGyroPeakTime: number;
  lastGyroPeakRadS: number;
  lastGpsSpeedKmh: number;
  lastGpsSpeedAt: number;
}

const state: FallDetectionState = {
  isMonitoring: false,
  lastFallTime: 0,
  freefallDetected: false,
  freefallTime: 0,
  impactDetected: false,
  impactTime: 0,
  impactMagnitude: 0,
  orientationChanged: false,
  orientationDelta: 0,
  postImpactMotion: false,
  immobilityDetected: false,
  baselineOrientation: null,
  immobilityStart: 0,
  postImpactSamples: [],
  immobilitySamples: [],
  immobilityTimer: null,
  recoveryTimer: null,
  lastGyroPeakTime: 0,
  lastGyroPeakRadS: 0,
  lastGpsSpeedKmh: 0,
  lastGpsSpeedAt: 0,
};

let accelSubscription: any = null;
let gyroSubscription: any = null;
let onFallDetectedCallback: ((confidence: number, signals: FallSignals) => void) | null = null;

export interface FallSignals {
  impact_score: number;
  freefall_score: number;
  orientation_score: number;
  post_impact_score: number;
  immobility_score: number;
}

function resetState() {
  state.freefallDetected = false;
  state.freefallTime = 0;
  state.impactDetected = false;
  state.impactTime = 0;
  state.impactMagnitude = 0;
  state.orientationChanged = false;
  state.orientationDelta = 0;
  state.postImpactMotion = false;
  state.immobilityDetected = false;
  state.baselineOrientation = null;
  state.postImpactSamples = [];
  state.immobilitySamples = [];
  if (state.immobilityTimer) clearTimeout(state.immobilityTimer);
  if (state.recoveryTimer) clearTimeout(state.recoveryTimer);
  state.immobilityTimer = null;
  state.recoveryTimer = null;
}

function computeConfidence(): number {
  const impact = state.impactDetected ? Math.min(1.0, state.impactMagnitude / 4.0) : 0;
  const freefall = state.freefallDetected ? 1.0 : 0;
  const orientation = state.orientationChanged ? Math.min(1.0, state.orientationDelta / 90) : 0;

  // Post-impact: small instability movements
  const postImpactAvg = state.postImpactSamples.length > 0
    ? state.postImpactSamples.reduce((a, b) => a + b, 0) / state.postImpactSamples.length
    : 0;
  const postImpact = postImpactAvg > 0.05 && postImpactAvg < POST_IMPACT_THRESHOLD_G ? 1.0 : postImpactAvg > 0 ? 0.3 : 0;

  const immobility = state.immobilityDetected ? 1.0 : 0;

  return (
    W_IMPACT * impact +
    W_FREEFALL * freefall +
    W_ORIENTATION * orientation +
    W_POST_IMPACT * postImpact +
    W_IMMOBILITY * immobility
  );
}

function getSignals(): FallSignals {
  const impact = state.impactDetected ? Math.min(1.0, state.impactMagnitude / 4.0) : 0;
  const freefall = state.freefallDetected ? 1.0 : 0;
  const orientation = state.orientationChanged ? Math.min(1.0, state.orientationDelta / 90) : 0;
  const postImpactAvg = state.postImpactSamples.length > 0
    ? state.postImpactSamples.reduce((a, b) => a + b, 0) / state.postImpactSamples.length
    : 0;
  const postImpact = postImpactAvg > 0.05 && postImpactAvg < POST_IMPACT_THRESHOLD_G ? 1.0 : postImpactAvg > 0 ? 0.3 : 0;
  const immobility = state.immobilityDetected ? 1.0 : 0;

  return { impact_score: impact, freefall_score: freefall, orientation_score: orientation, post_impact_score: postImpact, immobility_score: immobility };
}

function processAccelerometer(data: { x: number; y: number; z: number }) {
  const now = Date.now();
  const magnitude = Math.sqrt(data.x ** 2 + data.y ** 2 + data.z ** 2);

  // Cooldown check
  if (now - state.lastFallTime < COOLDOWN_MS) return;

  // Stage 1: Free-fall detection (brief weightlessness before impact)
  if (!state.freefallDetected && !state.impactDetected && magnitude < FREEFALL_THRESHOLD_G) {
    state.freefallDetected = true;
    state.freefallTime = now;
  }

  // Stage 2: Impact detection
  if (!state.impactDetected && magnitude > IMPACT_THRESHOLD_G) {
    // SF-01 v2 Day 1 — GPS speed suppression. If the device is in
    // a moving vehicle when an accel spike hits, this is almost
    // never a real fall (pothole / deceleration / hard brake).
    // We don't even start the 5-stage pipeline.
    if (
      state.lastGpsSpeedKmh >= GPS_SPEED_SUPPRESS_KMH
      && (now - state.lastGpsSpeedAt) < 10000  // GPS fix < 10s old
    ) {
      // Stay silent; do not flip impactDetected. Logged once per
      // spike via the dev-mode log so QA can confirm in the jog
      // / car-ride tests.
      if (__DEV__) {
        console.log(
          '[FALL] suppressed by GPS speed guard',
          { speed_kmh: state.lastGpsSpeedKmh, mag_g: magnitude.toFixed(2) },
        );
      }
      return;
    }

    // If freefall was detected, check it was recent
    if (state.freefallDetected && (now - state.freefallTime) > FREEFALL_WINDOW_MS) {
      state.freefallDetected = false; // Too old, not a real freefall
    }

    state.impactDetected = true;
    state.impactTime = now;
    state.impactMagnitude = magnitude;

    // Record baseline orientation for change detection
    state.baselineOrientation = null; // Will be set by gyro

    // Start post-impact tracking
    state.postImpactSamples = [];
    state.immobilitySamples = [];
    return;
  }

  // Stage 4 & 5: After impact — track post-impact motion + immobility
  if (state.impactDetected) {
    const elapsed = now - state.impactTime;

    // Post-impact motion (2-5s after impact)
    if (elapsed > 1000 && elapsed < POST_IMPACT_WINDOW_MS) {
      state.postImpactSamples.push(magnitude);
      const avgMotion = state.postImpactSamples.reduce((a, b) => a + b, 0) / state.postImpactSamples.length;
      if (avgMotion > 0.05 && avgMotion < POST_IMPACT_THRESHOLD_G) {
        state.postImpactMotion = true;
      }
    }

    // Immobility detection (5-15s after impact)
    if (elapsed > POST_IMPACT_WINDOW_MS) {
      state.immobilitySamples.push(magnitude);
      const recent = state.immobilitySamples.slice(-20);
      const avgRecent = recent.reduce((a, b) => a + b, 0) / recent.length;

      if (avgRecent < IMMOBILITY_THRESHOLD_G + 1.0) { // Near 1g (gravity) with low variation
        const variance = recent.reduce((sum, v) => sum + (v - avgRecent) ** 2, 0) / recent.length;
        if (variance < 0.01) { // Very low motion variation
          state.immobilityDetected = true;
        }
      }

      // Check if enough time passed for immobility conclusion
      if (elapsed > IMMOBILITY_WINDOW_MS && state.immobilityDetected) {
        checkAndTriggerFall();
      }

      // Movement recovery: if significant motion after impact, cancel
      if (elapsed < RECOVERY_CANCEL_MS && magnitude > 1.5) {
        resetState();
        return;
      }
    }

    // Timeout: if 15s after impact and no trigger, reset
    if (elapsed > 15000) {
      resetState();
    }
  }
}

function processGyroscope(data: { x: number; y: number; z: number }) {
  // SF-01 v2 Day 1 — record gyro angular-velocity peak regardless of
  // impact state. The gyro-confirm guard reads the most recent peak
  // and asks: did the body axis tumble fast enough, recently enough,
  // for this accel spike to be a fall?
  const rotMagnitude = Math.sqrt(data.x ** 2 + data.y ** 2 + data.z ** 2);
  if (rotMagnitude > state.lastGyroPeakRadS) {
    // Latch the peak. Decays naturally — once GYRO_CONFIRM_WINDOW_MS
    // passes after impact, the guard rejects regardless of latch.
    state.lastGyroPeakRadS = rotMagnitude;
    state.lastGyroPeakTime = Date.now();
  }
  // Slow decay so a long-stale peak doesn't trick the confirm guard.
  if (Date.now() - state.lastGyroPeakTime > GYRO_CONFIRM_WINDOW_MS) {
    state.lastGyroPeakRadS = rotMagnitude;
    state.lastGyroPeakTime = Date.now();
  }

  if (!state.impactDetected) return;

  // Stage 3: Orientation change after impact
  const rotDeg = rotMagnitude * (180 / Math.PI);

  if (rotDeg > ORIENTATION_THRESHOLD_DEG) {
    state.orientationChanged = true;
    state.orientationDelta = Math.max(state.orientationDelta, rotDeg);
  }
}

function checkAndTriggerFall() {
  if (!state.impactDetected) return;

  // SF-01 v2 Day 1 — gyro confirmation guard. The accel spike alone
  // is not enough; a real fall must also tumble the body axis fast
  // (≥ 120 °/s ≡ 2.094 rad/s) within 500 ms of the spike.
  const gyroAgeMs = state.lastGyroPeakTime > 0
    ? Math.abs(state.lastGyroPeakTime - state.impactTime)
    : Number.POSITIVE_INFINITY;
  const gyroConfirmed =
    state.lastGyroPeakRadS >= GYRO_CONFIRM_THRESHOLD_RAD_S
    && gyroAgeMs <= GYRO_CONFIRM_WINDOW_MS;
  if (!gyroConfirmed) {
    if (__DEV__) {
      console.log(
        '[FALL] suppressed by gyro-confirm guard',
        {
          gyro_peak_rad_s: state.lastGyroPeakRadS.toFixed(2),
          gyro_age_ms: gyroAgeMs,
        },
      );
    }
    resetState();
    return;
  }

  const confidence = computeConfidence();
  const signals = getSignals();

  if (confidence >= CONFIDENCE_THRESHOLD) {
    state.lastFallTime = Date.now();

    // Vibration pattern to alert user
    Vibration.vibrate([0, 200, 100, 200, 100, 200]);

    if (onFallDetectedCallback) {
      onFallDetectedCallback(confidence, signals);
    }

    resetState();
  } else {
    // Below threshold — false positive, reset
    resetState();
  }
}

// ── Public API ──

export function startFallDetection(
  onFallDetected: (confidence: number, signals: FallSignals) => void
): () => void {
  if (state.isMonitoring) return () => {};

  state.isMonitoring = true;
  onFallDetectedCallback = onFallDetected;
  resetState();

  try {
    Accelerometer.setUpdateInterval(SENSOR_INTERVAL_MS);
    Gyroscope.setUpdateInterval(SENSOR_INTERVAL_MS);

    accelSubscription = Accelerometer.addListener(processAccelerometer);
    gyroSubscription = Gyroscope.addListener(processGyroscope);
  } catch (e) {
    // Sensors not available (emulator, hardware missing, permission issue)
    console.warn('[FALL] Sensor init failed (fall detection disabled):', (e as any)?.message || e);
    state.isMonitoring = false;
    onFallDetectedCallback = null;
    return () => {};
  }

  return () => stopFallDetection();
}

export function stopFallDetection() {
  state.isMonitoring = false;
  onFallDetectedCallback = null;
  resetState();

  try {
    if (accelSubscription) {
      accelSubscription.remove();
      accelSubscription = null;
    }
    if (gyroSubscription) {
      gyroSubscription.remove();
      gyroSubscription = null;
    }
  } catch (e) {
    console.warn('[FALL] Error stopping sensors:', (e as any)?.message || e);
  }
}

export function isFallDetectionActive(): boolean {
  return state.isMonitoring;
}

// SF-01 v2 Day 1 — GPS speed feed for the vehicle-suppression guard.
// Called from `motionTelemetryService` on each GPS tick. Cheap setter;
// `processAccelerometer` reads the latched value with a 10 s freshness
// window so a stale GPS fix can't keep the guard armed forever.
//
// km/h is the contract because GuardianSession + LiveSafetyMap also
// surface km/h — same unit everywhere prevents conversion bugs.
export function updateGpsSpeed(speed_kmh: number) {
  if (!Number.isFinite(speed_kmh) || speed_kmh < 0) return;
  state.lastGpsSpeedKmh = speed_kmh;
  state.lastGpsSpeedAt = Date.now();
}

// ── Manual Fall Report (for testing) ──
export function simulateFall(): FallSignals {
  return {
    impact_score: 0.92,
    freefall_score: 0.75,
    orientation_score: 0.85,
    post_impact_score: 0.6,
    immobility_score: 0.88,
  };
}
