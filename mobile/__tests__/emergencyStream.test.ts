/**
 * NISCH-008 — Mobile emergency stream service tests.
 *
 * Locks the contract of `services/emergencyStreamService.ts`:
 *   1. Start/stop lifecycle posts to the correct endpoints, transitions
 *      state, and a stop without a prior start is a no-op.
 *   2. A successful chunk upload calls presign + PUT + (in stub mode) NO
 *      explicit /complete ping — the stub `/_mock_s3` PUT does it.
 *   3. Network failure on PUT queues the chunk locally; a subsequent
 *      successful upload flushes the queue (FIFO).
 *   4. The hard 3-minute cap auto-finalises even if the caller never
 *      stops.
 *   5. Guardian-ack stop fires the finalize endpoint with `reason`
 *      surfaced in the StopResult.
 *
 * Runner: pure Node `node --test --import tsx`. Same pattern as
 * `wearable.fallback.test.ts` — module-resolution hooks mock all the
 * RN/expo modules so we can exercise the service without booting RN.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import Module from 'node:module';

// ── Module-resolution hook for RN/expo modules ────────────────────
const ORIGINAL_RESOLVE = (Module as unknown as { _resolveFilename: Function })._resolveFilename;
const path = require('path');
const fs = require('fs');
const fixturesDir = path.join(__dirname, '_fixtures');
fs.mkdirSync(fixturesDir, { recursive: true });

fs.writeFileSync(path.join(fixturesDir, 'expo-audio-mock.cjs'),
  `module.exports = {
  AudioModule: {
    requestRecordingPermissionsAsync: async () => ({ granted: true }),
    AudioRecorder: function () {
      this.uri = 'mock://audio.m4a';
      this.prepareToRecordAsync = async () => undefined;
      this.record = () => undefined;
      this.stop = async () => undefined;
      this.getStatus = () => ({ isRecording: false, metering: -30 });
    },
  },
  RecordingPresets: { HIGH_QUALITY: {} },
};`);
fs.writeFileSync(path.join(fixturesDir, 'expo-video-thumbnails-mock.cjs'),
  `module.exports = { getThumbnailAsync: async () => ({ uri: 'mock://thumb.jpg' }) };`);
fs.writeFileSync(path.join(fixturesDir, 'expo-file-system-mock.cjs'),
  `module.exports = {
  getInfoAsync: async () => ({ exists: true, size: 1024 }),
  readAsStringAsync: async () => 'AQID',
};`);
fs.writeFileSync(path.join(fixturesDir, 'expo-secure-store-mock.cjs'),
  `module.exports = { getItemAsync: async () => null, setItemAsync: async () => undefined, deleteItemAsync: async () => undefined };`);
fs.writeFileSync(path.join(fixturesDir, 'expo-router-mock.cjs'),
  `module.exports = { router: { replace: () => undefined } };`);
fs.writeFileSync(path.join(fixturesDir, 'react-native-mock.cjs'),
  `module.exports = { Platform: { OS: 'ios' } };`);
fs.writeFileSync(path.join(fixturesDir, 'api-mock.cjs'),
  `// Default no-op axios-like client. Tests inject behaviour via __setHooks.
module.exports = { default: { post: async () => ({ data: {} }) } };`);

(Module as unknown as { _resolveFilename: Function })._resolveFilename = function (
  request: string,
  parent: NodeJS.Module,
  ...rest: unknown[]
) {
  const map: Record<string, string> = {
    'expo-audio':              './_fixtures/expo-audio-mock.cjs',
    'expo-video-thumbnails':   './_fixtures/expo-video-thumbnails-mock.cjs',
    'expo-file-system':        './_fixtures/expo-file-system-mock.cjs',
    'expo-secure-store':       './_fixtures/expo-secure-store-mock.cjs',
    'expo-router':             './_fixtures/expo-router-mock.cjs',
    'react-native':            './_fixtures/react-native-mock.cjs',
  };
  const mapped = map[request];
  if (mapped) return require.resolve(mapped);
  if (request === './api' || request.endsWith('/services/api')) {
    return require.resolve('./_fixtures/api-mock.cjs');
  }
  return ORIGINAL_RESOLVE.call(this, request, parent, ...rest);
};

// Service must be imported AFTER the resolver hook is in place.
const svc =
  require('../services/emergencyStreamService') as typeof import('../services/emergencyStreamService');

// ── Tiny manual fake clock so we can fast-forward setTimeout. ───────
type Pending = { id: number; due: number; fn: () => void };
let _clock = 0;
let _next = 1;
let _pending: Pending[] = [];
const fakeSetTimeout = ((fn: () => void, ms: number) => {
  const p = { id: _next, due: _clock + ms, fn };
  _next += 1;
  _pending.push(p);
  return p as unknown as ReturnType<typeof setTimeout>;
}) as typeof setTimeout;
const fakeClearTimeout = ((h: unknown) => {
  if (h && typeof h === 'object' && 'id' in h) {
    _pending = _pending.filter((p) => p.id !== (h as Pending).id);
  }
}) as typeof clearTimeout;
async function advance(ms: number): Promise<void> {
  _clock += ms;
  const due = _pending.filter((p) => p.due <= _clock);
  _pending = _pending.filter((p) => p.due > _clock);
  for (const p of due) {
    p.fn();
    // Let microtasks (async upload pipeline) settle.
    await new Promise((r) => setImmediate(r));
  }
}
function resetClock(): void {
  _clock = 0;
  _next = 1;
  _pending = [];
}

// ── Test helpers ────────────────────────────────────────────────────
type Call = { path: string; body: unknown };
function makeHooks({
  failPut = false, audioFails = false,
}: { failPut?: boolean; audioFails?: boolean } = {}) {
  const calls: Call[] = [];
  const puts: { url: string; bytes: number; contentType: string }[] = [];
  let chunkSeq = 0;
  const postJson = async (p: string, body: unknown) => {
    calls.push({ path: p, body });
    if (p === '/emergency-stream/sessions') {
      return { session_id: 'sess-1', state: 'connecting', started_at: null };
    }
    if (p.endsWith('/finalize')) {
      return { session_id: 'sess-1', state: 'ended',
               ended_at: '2026-05-25T12:00:00Z', duration_seconds: 30 };
    }
    if (p.endsWith('/chunks/presign')) {
      chunkSeq += 1;
      return {
        chunk_id:     `chunk-${chunkSeq}`,
        upload_url:   `https://stub.local/_mock_s3?key=k${chunkSeq}`,
        s3_key:       `k${chunkSeq}`,
        content_type: (body as { content_type: string }).content_type,
        expires_at:   Math.floor(Date.now() / 1000) + 600,
        expires_in:   600,
        mock_s3:      true,
      };
    }
    return { ok: true };
  };
  const putBinary = async (url: string, bytes: Uint8Array, ct: string) => {
    if (failPut) throw new Error('network down');
    puts.push({ url, bytes: bytes.byteLength, contentType: ct });
    return bytes.byteLength;
  };
  const recordAudioChunk = async () =>
    audioFails ? null : { uri: 'mock://audio.m4a', sizeBytes: 4096 };
  const captureThumbnail = async () => ({ uri: 'mock://thumb.jpg', sizeBytes: 1024 });
  svc.__setHooks({
    setTimeout: fakeSetTimeout, clearTimeout: fakeClearTimeout,
    postJson, putBinary, recordAudioChunk, captureThumbnail,
  });
  return { calls, puts };
}

function reset() {
  svc.__resetForTests();
  resetClock();
}

// ── 1. Lifecycle ────────────────────────────────────────────────────
test('startSession → stopSession lifecycle hits the right endpoints', async () => {
  reset();
  const { calls } = makeHooks();

  const start = await svc.startSession({ incidentId: 'inc-1', trigger: 'safety_brain:alert' });
  assert.equal(start.sessionId, 'sess-1');
  assert.equal(start.state, 'connecting');
  assert.equal(svc.isActive(), true);
  assert.equal(svc.getCurrentSessionId(), 'sess-1');

  const stop = await svc.stopSession({ reason: 'manual' });
  assert.equal(stop.state, 'ended');
  assert.equal(stop.reason, 'manual');
  assert.equal(svc.isActive(), false);
  assert.equal(svc.getCurrentSessionId(), null);

  const paths = calls.map((c) => c.path);
  assert.deepEqual(paths, [
    '/emergency-stream/sessions',
    '/emergency-stream/sessions/sess-1/finalize',
  ]);
});

test('stopSession is a no-op when no session is active', async () => {
  reset();
  makeHooks();
  const stop = await svc.stopSession({ reason: 'manual' });
  assert.equal(stop.sessionId, '');
  assert.equal(stop.state, 'ended');
  assert.equal(svc.isActive(), false);
});

// ── 2. Chunk upload ────────────────────────────────────────────────
test('5s tick uploads one audio chunk (presign + PUT, stub-mode skips /complete)', async () => {
  reset();
  const { calls, puts } = makeHooks();
  await svc.startSession({ incidentId: 'inc-1' });

  // Fast-forward past one audio tick (5 s).
  await advance(5_000);
  // Settle any pending uploads.
  await new Promise((r) => setImmediate(r));
  await new Promise((r) => setImmediate(r));

  assert.equal(puts.length >= 1, true, 'PUT to upload_url should fire');
  const presigns = calls.filter((c) => c.path.endsWith('/chunks/presign'));
  assert.equal(presigns.length >= 1, true);
  const completes = calls.filter((c) => c.path.includes('/complete'));
  assert.equal(completes.length, 0, 'stub-mode skips explicit /complete');

  await svc.stopSession({ reason: 'manual' });
});

// ── 3. Network failure → queue → flush on next success ─────────────
test('PUT failure queues the chunk; subsequent success flushes the queue', async () => {
  reset();
  let allowPut = false;
  const calls: Call[] = [];
  const puts: { url: string }[] = [];
  let chunkSeq = 0;
  svc.__setHooks({
    setTimeout: fakeSetTimeout, clearTimeout: fakeClearTimeout,
    postJson: async (p: string, body: unknown) => {
      calls.push({ path: p, body });
      if (p === '/emergency-stream/sessions')
        return { session_id: 's1', state: 'connecting', started_at: null };
      if (p.endsWith('/finalize'))
        return { session_id: 's1', state: 'ended', ended_at: null, duration_seconds: 0 };
      if (p.endsWith('/chunks/presign')) {
        chunkSeq += 1;
        return {
          chunk_id: `c${chunkSeq}`, upload_url: `https://stub.local/k${chunkSeq}`,
          s3_key: `k${chunkSeq}`, content_type: 'audio/mp4',
          expires_at: 0, expires_in: 600, mock_s3: true,
        };
      }
      return { ok: true };
    },
    putBinary: async (url: string, bytes: Uint8Array) => {
      if (!allowPut) throw new Error('network down');
      puts.push({ url });
      return bytes.byteLength;
    },
    recordAudioChunk: async () => ({ uri: 'mock://audio.m4a', sizeBytes: 4096 }),
    captureThumbnail: async () => ({ uri: 'mock://thumb.jpg', sizeBytes: 1024 }),
  });

  await svc.startSession({ incidentId: 'inc-1' });

  // Two ticks while uploads fail — chunks land in the retry queue.
  await advance(5_000);
  await new Promise((r) => setImmediate(r));
  await new Promise((r) => setImmediate(r));
  await advance(5_000);
  await new Promise((r) => setImmediate(r));
  await new Promise((r) => setImmediate(r));

  assert.equal(svc.getQueueSize() >= 2, true,
               `expected ≥2 queued, got ${svc.getQueueSize()}`);
  assert.equal(puts.length, 0);

  // Re-enable PUT and let the retry timer fire.
  allowPut = true;
  await advance(svc.RETRY_BACKOFF_MS + 100);
  await new Promise((r) => setImmediate(r));
  await new Promise((r) => setImmediate(r));
  // Also drive another audio tick so the success-path retries the queue.
  await advance(5_000);
  await new Promise((r) => setImmediate(r));
  await new Promise((r) => setImmediate(r));

  assert.equal(svc.getQueueSize(), 0, 'queue must be drained after success');
  assert.equal(puts.length >= 2, true, 'queued PUTs must replay');

  await svc.stopSession({ reason: 'manual' });
});

// ── 4. Hard 3-min cap auto-finalises ───────────────────────────────
test('max-duration cap auto-finalises the session at 3 min', async () => {
  reset();
  const { calls } = makeHooks();
  await svc.startSession({ incidentId: 'inc-1' });
  assert.equal(svc.isActive(), true);

  // Jump past the 3-min cap.
  await advance(svc.MAX_SESSION_MS + 100);
  // Allow async stopSession() chain to flush.
  for (let i = 0; i < 10; i += 1) await new Promise((r) => setImmediate(r));

  assert.equal(svc.isActive(), false, 'session must end after 3 min');
  assert.equal(svc.getCurrentSessionId(), null);
  const finalize = calls.filter((c) => c.path.endsWith('/finalize'));
  assert.equal(finalize.length, 1, 'finalize must be called exactly once');
});

// ── 5. Guardian-ack stop surfaces the reason ───────────────────────
test('guardian-ack stopSession finalises and surfaces reason=guardian_ack', async () => {
  reset();
  const { calls } = makeHooks();
  await svc.startSession({ incidentId: 'inc-1' });
  const stop = await svc.stopSession({ reason: 'guardian_ack' });
  assert.equal(stop.reason, 'guardian_ack');
  assert.equal(stop.state, 'ended');
  assert.equal(svc.isActive(), false);
  const finalize = calls.filter((c) => c.path.endsWith('/finalize'));
  assert.equal(finalize.length, 1);
});
