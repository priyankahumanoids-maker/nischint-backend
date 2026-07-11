// NISCH-012 — Continuous Motion Telemetry Bridge.
//
// Subsamples accelerometer + gyroscope at 5 Hz, aggregates into
// 60-second feature windows, and batch-uploads every 5 minutes
// to `POST /api/sensors/motion/features`.
//
// LOCKED ADDITIVE CONTRACT (per the locked product brief):
//   * Runs independently of `fallDetection.ts`. Both services
//     can subscribe to expo-sensors at different rates without
//     interference — expo-sensors deduplicates listeners.
//   * Fall detection continues to drive its own 20 Hz pipeline
//     and binary triggers. This service NEVER reads from or
//     mutates the fall pipeline.
//   * Battery profile: 5 Hz subsample (vs fall pipeline's 20 Hz)
//     + 60 s in-memory aggregation + 5 min batched HTTP. ~2 KB
//     per upload. Negligible incremental cost.
//
// FAIL-SAFE:
//   * Upload failures queue locally (in-memory) and retry on the
//     next 5-min cycle. Bounded queue (max 12 windows = 1 hour)
//     to cap memory if the network is down for an extended
//     period. Older windows drop oldest-first.
//   * Sensor permission denied → service starts no-op. The
//     existing fall pipeline retains its own permission flow.
//   * Idempotency via `device_id|window_started_at` — the
//     backend collapses duplicate uploads silently.

import { Accelerometer, Gyroscope } from 'expo-sensors';
import * as Application from 'expo-application';
import { Platform } from 'react-native';
import api from './api';

// ── Locked constants ────────────────────────────────────────────

// Subsample rate. 5 Hz = 200 ms between samples. Distinct from
// the fall pipeline's 50 ms / 20 Hz cadence to keep both
// pipelines independent.
const SAMPLE_RATE_HZ = 5;
const SAMPLE_INTERVAL_MS = 1000 / SAMPLE_RATE_HZ;

// Feature window. 60 s = ~300 samples at 5 Hz.
const WINDOW_DURATION_S = 60;
const WINDOW_DURATION_MS = WINDOW_DURATION_S * 1000;

// Batch upload cadence — 5 min = 5 windows per batch under
// healthy conditions.
const BATCH_UPLOAD_INTERVAL_MS = 5 * 60 * 1000;

// Local retry queue cap — 1 h of windows. Older windows drop.
const MAX_QUEUED_WINDOWS = 12;

// Activity classifier thresholds. Rule-based; locked at
// startup. A future PR can swap in a TFLite classifier behind
// the same interface.
const STATIONARY_STDDEV_THRESHOLD = 0.05;
const WALKING_STDDEV_THRESHOLD    = 0.30;
const RUNNING_STDDEV_THRESHOLD    = 1.20;
// Sustained high mean + low stddev → likely in a vehicle
// (constant acceleration baseline shifted from 1 g by motion).
const VEHICLE_MEAN_LOW  = 0.85;
const VEHICLE_MEAN_HIGH = 1.15;
const VEHICLE_STDDEV_MAX = 0.18;
// Anomalous = neither walking/running/stationary/vehicle but
// stddev exceeds running threshold (e.g. a fall-like spike that
// wasn't classified by the fall pipeline).
const ANOMALOUS_PEAK_G = 3.0;

// ── Types ───────────────────────────────────────────────────────

type ActivityClass =
  | 'stationary' | 'walking' | 'running' | 'vehicle' | 'anomalous';

interface WindowFeatures {
  window_started_at: string;
  window_duration_s: number;
  accel_mean_g:   number;
  accel_stddev_g: number;
  accel_peak_g:   number;
  gyro_variance:  number;
  activity_class: ActivityClass;
  sample_count:   number;
  sample_rate_hz: number;
  device_context?: Record<string, unknown>;
}

// ── Internal state ──────────────────────────────────────────────

// Latest accelerometer + gyroscope samples — paired by timestamp
// rather than re-subscribed at high frequency.
let _windowStartMs = 0;
let _accelMagSamples: number[] = [];
let _gyroMagSamples:  number[] = [];
let _latestAccel = { x: 0, y: 0, z: 0 };
let _latestGyro  = { x: 0, y: 0, z: 0 };

// Pending windows awaiting upload. FIFO; bounded.
const _queue: WindowFeatures[] = [];

let _accelSub: { remove: () => void } | null = null;
let _gyroSub:  { remove: () => void } | null = null;
let _aggregateTimer: ReturnType<typeof setInterval> | null = null;
let _uploadTimer:    ReturnType<typeof setInterval> | null = null;
let _liveHeartbeatTimer: ReturnType<typeof setInterval> | null = null;
let _running = false;

// SF-01 v2 Day 2 — Live heartbeat to /api/signals/motion.
// 30s cadence per spec. Bandwidth guard: skip when the latest
// window's signals are all at baseline (nothing happening).
const LIVE_HEARTBEAT_INTERVAL_MS = 30 * 1000;
// Baseline filter — accel stddev below this AND no recent peak means
// the device is sitting on a table. No reason to wake the safety
// brain composite recalc.
const LIVE_HEARTBEAT_SKIP_STDDEV = 0.04;
const LIVE_HEARTBEAT_SKIP_PEAK_G = 1.30;
// Cached last-known location — populated by `setLatestLocation`,
// called from the existing locationService update path so we don't
// take a new GPS fix per heartbeat.
let _lastKnownLat: number | null = null;
let _lastKnownLng: number | null = null;
let _lastKnownLocationAt = 0;

// ── Helpers ─────────────────────────────────────────────────────

function _mag(v: { x: number; y: number; z: number }): number {
  return Math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z);
}

function _mean(xs: number[]): number {
  if (xs.length === 0) return 0;
  let s = 0;
  for (let i = 0; i < xs.length; i++) s += xs[i];
  return s / xs.length;
}

function _stddev(xs: number[], mean?: number): number {
  if (xs.length < 2) return 0;
  const m = mean ?? _mean(xs);
  let s = 0;
  for (let i = 0; i < xs.length; i++) {
    const d = xs[i] - m;
    s += d * d;
  }
  return Math.sqrt(s / xs.length);
}

function _peak(xs: number[]): number {
  let p = 0;
  for (let i = 0; i < xs.length; i++) {
    if (xs[i] > p) p = xs[i];
  }
  return p;
}

function _classify(
  mean: number, stddev: number, peak: number,
): ActivityClass {
  // Precedence locked: critical/spike > running > walking >
  // vehicle > stationary. Mirrors the trust-tile "worst wins"
  // semantic so the activity_class column ranks correctly.
  if (peak >= ANOMALOUS_PEAK_G && stddev >= RUNNING_STDDEV_THRESHOLD) {
    return 'anomalous';
  }
  if (stddev >= RUNNING_STDDEV_THRESHOLD) return 'running';
  if (stddev >= WALKING_STDDEV_THRESHOLD) return 'walking';
  if (mean >= VEHICLE_MEAN_LOW && mean <= VEHICLE_MEAN_HIGH
      && stddev <= VEHICLE_STDDEV_MAX
      && stddev > STATIONARY_STDDEV_THRESHOLD) {
    return 'vehicle';
  }
  if (stddev <= STATIONARY_STDDEV_THRESHOLD) return 'stationary';
  return 'walking';
}

function _enqueue(window: WindowFeatures): void {
  _queue.push(window);
  // Drop oldest if over cap — preserves freshest signal.
  while (_queue.length > MAX_QUEUED_WINDOWS) _queue.shift();
}

function _resetWindow(): void {
  _windowStartMs = Date.now();
  _accelMagSamples = [];
  _gyroMagSamples = [];
}

function _flushWindow(): WindowFeatures | null {
  // Need at least ~half a window of samples to emit. Avoids
  // garbage windows on startup or after a permission flicker.
  const expected = Math.floor(WINDOW_DURATION_S * SAMPLE_RATE_HZ * 0.5);
  if (_accelMagSamples.length < expected) {
    _resetWindow();
    return null;
  }
  const accelMean = _mean(_accelMagSamples);
  const accelStddev = _stddev(_accelMagSamples, accelMean);
  const accelPeak = _peak(_accelMagSamples);
  // Gyro variance — variance, not stddev. The trust evaluator
  // and operator UI treat it as a rotation-energy proxy.
  const gyroMean = _mean(_gyroMagSamples);
  const gyroVar = _stddev(_gyroMagSamples, gyroMean) ** 2;

  const w: WindowFeatures = {
    window_started_at: new Date(_windowStartMs).toISOString(),
    window_duration_s: WINDOW_DURATION_S,
    accel_mean_g:   Number(accelMean.toFixed(4)),
    accel_stddev_g: Number(accelStddev.toFixed(4)),
    accel_peak_g:   Number(accelPeak.toFixed(4)),
    gyro_variance:  Number(gyroVar.toFixed(6)),
    activity_class: _classify(accelMean, accelStddev, accelPeak),
    sample_count:   _accelMagSamples.length,
    sample_rate_hz: SAMPLE_RATE_HZ,
    device_context: {
      platform: Platform.OS,
      // Phase-1: minimal context. A future PR can add charging
      // state, screen lock, network class without changing the
      // ingest contract.
    },
  };
  _resetWindow();
  return w;
}

async function _uploadBatch(): Promise<void> {
  if (_queue.length === 0) return;
  // Drain into a local copy so a parallel sensor tick can't
  // mutate the in-flight batch mid-upload.
  const batch = _queue.slice(0);
  let deviceId: string;
  try {
    // expo-application gives a stable per-install identifier on
    // both iOS and Android. Falls back to "unknown" so the upload
    // still goes through (backend tolerates non-UUID device_id).
    deviceId =
      (Application.getAndroidId?.() as string | null)
      || (await Application.getIosIdForVendorAsync?.())
      || 'unknown';
  } catch {
    deviceId = 'unknown';
  }
  try {
    const res = await api.post('/sensors/motion/features', {
      device_id: deviceId,
      windows: batch,
    });
    // Drop only the windows the backend acknowledged as
    // `inserted` or `duplicate`. `failed` windows stay in the
    // queue for the next cycle.
    const results: Array<{ window_started_at: string; status: string }>
      = (res?.data?.results ?? []) as Array<{ window_started_at: string; status: string }>;
    const ackedKeys = new Set<string>();
    for (const r of results) {
      if (r.status === 'inserted' || r.status === 'duplicate') {
        ackedKeys.add(r.window_started_at);
      }
    }
    // Re-keep only failed windows (or windows not echoed).
    for (let i = _queue.length - 1; i >= 0; i--) {
      if (ackedKeys.has(_queue[i].window_started_at)) {
        _queue.splice(i, 1);
      }
    }
  } catch {
    // Network failure → leave the batch in the queue for the
    // next 5-min cycle. Bounded queue caps memory at 1 h.
    // Silent — observability is on the backend ingestion log.
  }
}

// SF-01 v2 Day 2 — live heartbeat emitter. Pushes a /signals/motion
// snapshot every 30s using a derived `fall` proxy (accel peak / 4G,
// clipped) so the backend Safety Brain has a continuous signal stream
// even between fall events. `voice_distress` stays 0 here — the
// audioMonitorService owns that channel and emits its own signal
// when voiceDistression triggers.
async function _emitLiveHeartbeat(): Promise<void> {
  if (_accelMagSamples.length < 5) return;  // not enough samples yet
  const accelMean = _mean(_accelMagSamples);
  const accelStddev = _stddev(_accelMagSamples, accelMean);
  const accelPeak = _peak(_accelMagSamples);

  // Bandwidth guard — skip baseline frames. ALWAYS emit when an
  // anomaly-class peak is happening (lets the backend correlate
  // partial fall-pipeline signals against motion telemetry).
  const looksBaseline =
    accelStddev <= LIVE_HEARTBEAT_SKIP_STDDEV
    && accelPeak <= LIVE_HEARTBEAT_SKIP_PEAK_G;
  if (looksBaseline) return;

  // Derive a fall-proxy score in [0,1]. Not a fall detection — just
  // a continuous motion intensity signal the safety brain can fuse.
  const fallProxy = Math.max(0, Math.min(1, (accelPeak - 1.0) / 3.0));

  // Use cached GPS — never block the 30s tick on a fresh fix.
  // Backend tolerates a stale or absent fix (lat=0,lng=0 is fine for
  // live composite recalc; only the alert pipeline cares about it).
  const stale = (Date.now() - _lastKnownLocationAt) > 5 * 60 * 1000;
  const lat = (!stale && _lastKnownLat !== null) ? _lastKnownLat : 0;
  const lng = (!stale && _lastKnownLng !== null) ? _lastKnownLng : 0;

  try {
    await api.post('/signals/motion', {
      fall:           Number(fallProxy.toFixed(3)),
      voice_distress: 0,
      lat,
      lng,
    });
  } catch {
    // Non-fatal. The 5-min ledger and the on-event /sensors/fall
    // path still capture the canonical record.
  }
}

// ── Public API ──────────────────────────────────────────────────

export async function startMotionTelemetry(): Promise<boolean> {
  if (_running) return true;
  try {
    const accelOk = await Accelerometer.isAvailableAsync();
    const gyroOk  = await Gyroscope.isAvailableAsync();
    if (!accelOk || !gyroOk) return false;

    Accelerometer.setUpdateInterval(SAMPLE_INTERVAL_MS);
    Gyroscope.setUpdateInterval(SAMPLE_INTERVAL_MS);

    _resetWindow();

    _accelSub = Accelerometer.addListener((data) => {
      _latestAccel = data;
      _accelMagSamples.push(_mag(data));
    });
    _gyroSub = Gyroscope.addListener((data) => {
      _latestGyro = data;
      _gyroMagSamples.push(_mag(data));
    });

    // Window aggregator — flushes one 60-s window per tick.
    _aggregateTimer = setInterval(() => {
      const w = _flushWindow();
      if (w) _enqueue(w);
    }, WINDOW_DURATION_MS);

    // Batch uploader — every 5 min.
    _uploadTimer = setInterval(() => {
      void _uploadBatch();
    }, BATCH_UPLOAD_INTERVAL_MS);

    // SF-01 v2 Day 2 — 30s live motion heartbeat to /signals/motion.
    // This is the lightweight composite-recalc surface; the 5-min
    // batch above is the audit ledger. Both run independently.
    // Heartbeat fires only when SOMETHING above the baseline is
    // happening — saves bandwidth in steady-state (the modal case).
    _liveHeartbeatTimer = setInterval(() => {
      void _emitLiveHeartbeat();
    }, LIVE_HEARTBEAT_INTERVAL_MS);

    _running = true;
    return true;
  } catch {
    _running = false;
    return false;
  }
}

export function stopMotionTelemetry(): void {
  if (!_running) return;
  try {
    if (_accelSub) _accelSub.remove();
    if (_gyroSub)  _gyroSub.remove();
  } catch {
    // Sensor unsubscribe errors are non-fatal.
  }
  _accelSub = null;
  _gyroSub  = null;
  if (_aggregateTimer) clearInterval(_aggregateTimer);
  if (_uploadTimer)    clearInterval(_uploadTimer);
  if (_liveHeartbeatTimer) clearInterval(_liveHeartbeatTimer);
  _aggregateTimer = null;
  _uploadTimer    = null;
  _liveHeartbeatTimer = null;
  _running = false;
}

export function isMotionTelemetryActive(): boolean {
  return _running;
}

// SF-01 v2 Day 2 — accept GPS updates from the locationService so the
// 30s heartbeat doesn't have to take its own GPS fix. Called from
// `locationService.onLocationUpdate` on every fix.
export function setLatestLocation(lat: number, lng: number): void {
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
  _lastKnownLat = lat;
  _lastKnownLng = lng;
  _lastKnownLocationAt = Date.now();
}

/** Test hook — drains the queue immediately, used in unit tests. */
export async function _testFlushAndUpload(): Promise<void> {
  const w = _flushWindow();
  if (w) _enqueue(w);
  await _uploadBatch();
}

/** Test hook — exposes the queue for inspection. */
export function _testGetQueue(): WindowFeatures[] {
  return _queue.slice();
}

/** Pure-function classifier export for unit tests. */
export const _classifyForTest = _classify;

export const _MOTION_TELEMETRY_CONSTANTS = {
  SAMPLE_RATE_HZ,
  WINDOW_DURATION_S,
  BATCH_UPLOAD_INTERVAL_MS,
  MAX_QUEUED_WINDOWS,
} as const;
