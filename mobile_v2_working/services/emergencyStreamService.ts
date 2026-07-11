// NISCH-008 — Mobile emergency stream recording service.
//
// Records 5 s audio chunks via `expo-audio`, captures 1 fps thumbnails
// via `expo-video-thumbnails`, and uploads them to the backend via
// pre-signed PUT URLs. Same wire contract in stub mode (local disk on
// the backend) and real-S3 mode.
//
// Lifecycle
// ─────────
// • `startSession({ incidentId, trigger })` — POST /sessions, then
//   begin the 5 s audio capture + 1 fps thumbnail loops.
// • Each audio chunk → POST /chunks/presign → PUT to upload_url →
//   POST /chunks/{id}/complete.
// • A network failure queues the chunk in an in-memory FIFO; the
//   service retries the queue on every successful subsequent upload.
// • `stopSession({ reason })` — POST /finalize and tears down loops.
// • Hard cap of 3 minutes — if neither the guardian acknowledges nor
//   the caller explicitly stops, the service auto-finalises.
//
// Strict TypeScript. No `any` in the public surface.

import { AudioModule, AudioRecorder, RecordingPresets } from 'expo-audio';
import * as FileSystem from 'expo-file-system';
import * as VideoThumbnails from 'expo-video-thumbnails';
import api from './api';

// ── Public types ────────────────────────────────────────────────────
export interface StartSessionOpts {
  incidentId: string;
  trigger?: string;
  riskScore?: number;
}

export type StopReason =
  | 'guardian_ack'
  | 'max_duration'
  | 'manual'
  | 'error';

export interface ChunkUploadResult {
  chunkId: string;
  sequence: number;
  mediaType: 'audio_chunk' | 'video_thumbnail';
  bytes: number;
  uploadedAt: number;
}

export interface PresignResponse {
  chunk_id: string;
  upload_url: string;
  s3_key: string;
  content_type: string;
  expires_at: number;
  expires_in: number;
  mock_s3: boolean;
}

interface QueuedChunk {
  localUri: string;
  mediaType: 'audio_chunk' | 'video_thumbnail';
  contentType: string;
  sequence: number;
  sizeBytes: number;
}

// ── Tuning constants ────────────────────────────────────────────────
export const AUDIO_CHUNK_MS = 5_000;
export const THUMBNAIL_INTERVAL_MS = 1_000;
export const MAX_SESSION_MS = 3 * 60 * 1_000;   // hard 3-min cap
export const RETRY_BACKOFF_MS = 2_000;
export const MAX_QUEUE_SIZE = 60;               // cap memory under outage

// Audio content type produced by `expo-audio` HIGH_QUALITY preset.
// (m4a / AAC inside an MP4 container on iOS + Android.)
const AUDIO_CONTENT_TYPE = 'audio/mp4';
const THUMBNAIL_CONTENT_TYPE = 'image/jpeg';

// ── Module-scoped state ─────────────────────────────────────────────
let _sessionId: string | null = null;
let _isCapturing = false;
let _audioSeq = 0;
let _thumbSeq = 0;
let _audioTimer: ReturnType<typeof setTimeout> | null = null;
let _thumbTimer: ReturnType<typeof setTimeout> | null = null;
let _maxDurationTimer: ReturnType<typeof setTimeout> | null = null;
let _recorder: AudioRecorder | null = null;
let _retryQueue: QueuedChunk[] = [];
let _retryTimer: ReturnType<typeof setTimeout> | null = null;
let _sessionVideoUri: string | null = null;
let _onChunkUploaded: ((r: ChunkUploadResult) => void) | null = null;

// Hooks for tests — swap the timers / network deps without going near
// real RN modules. Production runtime never touches these.
interface ServiceHooks {
  setTimeout?: typeof setTimeout;
  clearTimeout?: typeof clearTimeout;
  postJson?: (path: string, body: unknown) => Promise<unknown>;
  putBinary?: (url: string, blob: Uint8Array, contentType: string) => Promise<number>;
  recordAudioChunk?: () => Promise<{ uri: string; sizeBytes: number } | null>;
  captureThumbnail?: () => Promise<{ uri: string; sizeBytes: number } | null>;
}

let _hooks: ServiceHooks = {};

export function __setHooks(h: ServiceHooks): void { _hooks = h; }
export function __resetForTests(): void {
  _sessionId = null;
  _isCapturing = false;
  _audioSeq = 0;
  _thumbSeq = 0;
  _audioTimer = null;
  _thumbTimer = null;
  _maxDurationTimer = null;
  _recorder = null;
  _retryQueue = [];
  _retryTimer = null;
  _sessionVideoUri = null;
  _onChunkUploaded = null;
  _hooks = {};
}

const setT = (fn: () => void, ms: number) =>
  (_hooks.setTimeout ?? setTimeout)(fn, ms);
const clearT = (h: ReturnType<typeof setTimeout> | null) => {
  if (h !== null) (_hooks.clearTimeout ?? clearTimeout)(h);
};

// ── Network primitives ──────────────────────────────────────────────
async function postJson<T>(path: string, body: unknown): Promise<T> {
  if (_hooks.postJson) {
    return (await _hooks.postJson(path, body)) as T;
  }
  const res = await api.post(path, body);
  return res.data as T;
}

async function putBinary(
  url: string,
  bytes: Uint8Array,
  contentType: string,
): Promise<number> {
  if (_hooks.putBinary) return _hooks.putBinary(url, bytes, contentType);
  // Use fetch directly so we bypass the axios JSON-content-type default
  // and don't ship the Authorization header to S3 / the mock endpoint.
  const res = await fetch(url, {
    method: 'PUT',
    headers: { 'Content-Type': contentType },
    body: bytes as unknown as BodyInit,
  });
  if (!res.ok) throw new Error(`upload PUT failed status=${res.status}`);
  return bytes.byteLength;
}

// ── Capture primitives ──────────────────────────────────────────────
async function recordAudioChunk(): Promise<{ uri: string; sizeBytes: number } | null> {
  if (_hooks.recordAudioChunk) return _hooks.recordAudioChunk();
  const rec = _recorder;
  if (!rec) return null;
  try {
    await rec.stop();
    const uri = rec.uri;
    if (!uri) return null;
    const info = await FileSystem.getInfoAsync(uri);
    const sizeBytes = (info.exists && info.size != null) ? info.size : 0;
    // Re-arm for the next 5 s window.
    await rec.prepareToRecordAsync(RecordingPresets.HIGH_QUALITY);
    rec.record();
    return { uri, sizeBytes };
  } catch {
    return null;
  }
}

async function captureThumbnail(): Promise<{ uri: string; sizeBytes: number } | null> {
  if (_hooks.captureThumbnail) return _hooks.captureThumbnail();
  if (!_sessionVideoUri) return null;
  try {
    const elapsed = (Date.now() - _sessionStartedAt) / 1000;
    const t = Math.max(0, Math.floor(elapsed));
    const { uri } = await VideoThumbnails.getThumbnailAsync(_sessionVideoUri, {
      time: t * 1000,
      quality: 0.4,
    });
    const info = await FileSystem.getInfoAsync(uri);
    const sizeBytes = (info.exists && info.size != null) ? info.size : 0;
    return { uri, sizeBytes };
  } catch {
    return null;
  }
}

async function loadLocalBytes(uri: string): Promise<Uint8Array> {
  if (uri.startsWith('mock://')) return new Uint8Array([1, 2, 3]); // tests
  const b64 = await FileSystem.readAsStringAsync(uri, {
    encoding: 'base64',
  });
  // Decode base64 → bytes without depending on `Buffer` (RN ships
  // `globalThis.atob` via expo).
  const binary = (globalThis as { atob?: (s: string) => string }).atob?.(b64);
  if (!binary) return new Uint8Array();
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) out[i] = binary.charCodeAt(i);
  return out;
}

// ── Upload pipeline ─────────────────────────────────────────────────
let _sessionStartedAt = 0;

async function uploadChunk(q: QueuedChunk): Promise<ChunkUploadResult> {
  if (!_sessionId) throw new Error('no active session');
  const presign = await postJson<PresignResponse>(
    `/emergency-stream/sessions/${_sessionId}/chunks/presign`,
    {
      sequence:     q.sequence,
      media_type:   q.mediaType,
      content_type: q.contentType,
      size_bytes:   q.sizeBytes,
    },
  );

  const bytes = await loadLocalBytes(q.localUri);
  const uploadedBytes = await putBinary(
    presign.upload_url,
    bytes,
    q.contentType,
  );

  // The stub-mode `/_mock_s3` PUT already marks the chunk uploaded
  // server-side. Real-S3 mode needs this explicit completion ping.
  if (!presign.mock_s3) {
    await postJson(
      `/emergency-stream/sessions/${_sessionId}/chunks/${presign.chunk_id}/complete`,
      { size_bytes: uploadedBytes },
    );
  }

  const result: ChunkUploadResult = {
    chunkId:    presign.chunk_id,
    sequence:   q.sequence,
    mediaType:  q.mediaType,
    bytes:      uploadedBytes,
    uploadedAt: Date.now(),
  };
  _onChunkUploaded?.(result);
  return result;
}

async function flushRetryQueue(): Promise<void> {
  if (_retryQueue.length === 0) return;
  // FIFO — preserve capture order so playback reconstructs the timeline.
  while (_retryQueue.length > 0) {
    const head = _retryQueue[0];
    try {
      await uploadChunk(head);
      _retryQueue.shift();
    } catch {
      // Still failing — leave the queue intact and bail. The next
      // successful upload will retry, or `stopSession` will trigger
      // a final flush attempt.
      return;
    }
  }
}

async function attemptUpload(q: QueuedChunk): Promise<void> {
  try {
    await uploadChunk(q);
    // Opportunistically retry anything we queued earlier.
    if (_retryQueue.length > 0) await flushRetryQueue();
  } catch {
    if (_retryQueue.length < MAX_QUEUE_SIZE) _retryQueue.push(q);
    if (_retryTimer === null) {
      _retryTimer = setT(() => { _retryTimer = null; void flushRetryQueue(); },
                         RETRY_BACKOFF_MS);
    }
  }
}

// ── Capture loops ───────────────────────────────────────────────────
function scheduleAudioLoop(): void {
  if (!_isCapturing) return;
  _audioTimer = setT(async () => {
    if (!_isCapturing) return;
    const chunk = await recordAudioChunk();
    if (chunk) {
      _audioSeq += 1;
      void attemptUpload({
        localUri:    chunk.uri,
        mediaType:   'audio_chunk',
        contentType: AUDIO_CONTENT_TYPE,
        sequence:    _audioSeq,
        sizeBytes:   chunk.sizeBytes,
      });
    }
    scheduleAudioLoop();
  }, AUDIO_CHUNK_MS);
}

function scheduleThumbnailLoop(): void {
  if (!_isCapturing) return;
  _thumbTimer = setT(async () => {
    if (!_isCapturing) return;
    const t = await captureThumbnail();
    if (t) {
      _thumbSeq += 1;
      void attemptUpload({
        localUri:    t.uri,
        mediaType:   'video_thumbnail',
        contentType: THUMBNAIL_CONTENT_TYPE,
        sequence:    _thumbSeq,
        sizeBytes:   t.sizeBytes,
      });
    }
    scheduleThumbnailLoop();
  }, THUMBNAIL_INTERVAL_MS);
}

// ── Public API ──────────────────────────────────────────────────────
export interface StartResult {
  sessionId: string;
  state: string;
  startedAt: string | null;
}

export async function startSession(
  opts: StartSessionOpts,
  onChunk?: (r: ChunkUploadResult) => void,
): Promise<StartResult> {
  if (_isCapturing) throw new Error('session already running');
  _onChunkUploaded = onChunk ?? null;

  const res = await postJson<{ session_id: string; state: string; started_at: string | null }>(
    '/emergency-stream/sessions',
    {
      incident_id: opts.incidentId,
      trigger:     opts.trigger ?? 'safety_brain_alert',
      risk_score:  opts.riskScore,
    },
  );
  _sessionId = res.session_id;
  _isCapturing = true;
  _sessionStartedAt = Date.now();
  _audioSeq = 0;
  _thumbSeq = 0;
  _retryQueue = [];

  // Prepare the audio recorder ONLY when running in a real RN runtime.
  // Tests skip this — they provide `recordAudioChunk` via hooks.
  if (!_hooks.recordAudioChunk) {
    try {
      await AudioModule.requestRecordingPermissionsAsync();
      const r = new AudioModule.AudioRecorder(RecordingPresets.HIGH_QUALITY);
      await r.prepareToRecordAsync(RecordingPresets.HIGH_QUALITY);
      r.record();
      _recorder = r;
    } catch {
      _recorder = null;
    }
  }

  scheduleAudioLoop();
  scheduleThumbnailLoop();

  // Hard 3-min auto-finalize so we never leave a session running.
  _maxDurationTimer = setT(() => {
    void stopSession({ reason: 'max_duration' });
  }, MAX_SESSION_MS);

  return {
    sessionId: res.session_id,
    state:     res.state,
    startedAt: res.started_at,
  };
}

export interface StopResult {
  sessionId: string;
  state: string;
  endedAt: string | null;
  durationSeconds: number | null;
  reason: StopReason;
  pendingQueueSize: number;
}

export async function stopSession(
  opts: { reason: StopReason } = { reason: 'manual' },
): Promise<StopResult> {
  if (!_sessionId) {
    return {
      sessionId: '', state: 'ended', endedAt: null, durationSeconds: null,
      reason: opts.reason, pendingQueueSize: 0,
    };
  }
  _isCapturing = false;
  clearT(_audioTimer);
  clearT(_thumbTimer);
  clearT(_maxDurationTimer);
  clearT(_retryTimer);
  _audioTimer = null;
  _thumbTimer = null;
  _maxDurationTimer = null;
  _retryTimer = null;

  // Final best-effort flush — give queued chunks one last shot.
  await flushRetryQueue();

  if (_recorder && !_hooks.recordAudioChunk) {
    try {
      await _recorder.stop();
    } catch { /* ignore */ }
    _recorder = null;
  }

  const fin = await postJson<{ session_id: string; state: string; ended_at: string | null; duration_seconds: number | null }>(
    `/emergency-stream/sessions/${_sessionId}/finalize`,
    {},
  ).catch(() => ({
    session_id: _sessionId ?? '', state: 'ended',
    ended_at: null, duration_seconds: null,
  }));

  const result: StopResult = {
    sessionId:       fin.session_id,
    state:           fin.state,
    endedAt:         fin.ended_at,
    durationSeconds: fin.duration_seconds,
    reason:          opts.reason,
    pendingQueueSize: _retryQueue.length,
  };
  _sessionId = null;
  return result;
}

export function isActive(): boolean { return _isCapturing; }
export function getQueueSize(): number { return _retryQueue.length; }
export function getCurrentSessionId(): string | null { return _sessionId; }
