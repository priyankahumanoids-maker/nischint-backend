// Journey Service — orchestrator between mobile sensors and backend Journey Engine v5.
//
// Responsibilities:
//   • POST /api/journey/sync for batched events (locations, state transitions)
//   • POST /api/journey/sos for immediate SOS (bypasses queue)
//   • POST /api/journey/risk/score for periodic risk evaluations
//   • Flush the offline queue when network returns online
//   • Keep journeyEngineStore counters + connection status updated
//
// Does NOT modify backend contracts. Uses existing endpoints only.
import NetInfo from '@react-native-community/netinfo';
import api from './api';
import { enqueue, peek, markSuccess, markFailure, size as queueSize, computeBackoffMs } from './offlineQueue';
import { useJourneyEngineStore } from '../stores/journeyEngineStore';

const BATCH_SIZE = 10;

let _online = true;
let _flushing = false;
let _flushScheduled: ReturnType<typeof setTimeout> | null = null;

// ── Network monitor ────────────────────────────────────────────────
let _unsubNet: (() => void) | null = null;

export function initJourneyService(): void {
  if (_unsubNet) return;
  _unsubNet = NetInfo.addEventListener((state) => {
    const wasOnline = _online;
    _online = !!state.isConnected && state.isInternetReachable !== false;
    useJourneyEngineStore.getState().setConnection(_online ? 'online' : 'offline');
    if (_online && !wasOnline) {
      console.log('[JOURNEY_SVC] network back → flushing queue');
      scheduleFlush(500);
    }
  });
  // Seed initial state
  NetInfo.fetch().then((s) => {
    _online = !!s.isConnected && s.isInternetReachable !== false;
    useJourneyEngineStore.getState().setConnection(_online ? 'online' : 'offline');
  });
  // Kick off first flush shortly after init
  scheduleFlush(2000);
}

export function shutdownJourneyService(): void {
  if (_unsubNet) _unsubNet();
  _unsubNet = null;
  if (_flushScheduled) clearTimeout(_flushScheduled);
  _flushScheduled = null;
}

// ── Public API ─────────────────────────────────────────────────────

/**
 * Queue a non-critical event. Flushed to `/api/journey/sync` in batches.
 * Works offline — persisted to AsyncStorage.
 */
export async function sendEvent(type: string, payload: Record<string, any>): Promise<void> {
  await enqueue(type, payload);
  await refreshQueueSize();
  if (_online) scheduleFlush(300);
}

/**
 * Immediate SOS — bypasses queue, POSTs directly to /api/journey/sos.
 * Backup copy is still enqueued in case the direct POST fails.
 */
export async function sendSOS(params: {
  sessionId: string;
  riskScore?: number;
  riskLevel?: 'high' | 'critical';
  location?: { lat: number; lng: number } | null;
  network?: 'online' | 'offline';
  battery?: number | null;
  meta?: Record<string, any>;
}): Promise<{ sos_id?: string; status?: string; error?: string }> {
  const body = {
    ts: Date.now(),
    sessionId: params.sessionId,
    riskScore: params.riskScore ?? 90,
    riskLevel: params.riskLevel ?? 'high',
    location: params.location ?? null,
    network: params.network ?? (_online ? 'online' : 'offline'),
    battery: params.battery ?? null,
    meta: params.meta ?? {},
  };

  // Always enqueue a backup (will be pruned after direct success)
  await enqueue('sos_backup', body);

  if (!_online) {
    console.warn('[JOURNEY_SVC] SOS queued — offline');
    return { status: 'queued_offline' };
  }

  try {
    const resp = await api.post('/journey/sos', body);
    console.warn('[JOURNEY_SVC] SOS delivered', resp.data?.sos_id);
    return resp.data;
  } catch (e: any) {
    console.error('[JOURNEY_SVC] SOS direct failed, kept in queue', e?.message);
    scheduleFlush(1000);
    return { error: e?.message || 'network_error' };
  }
}

/**
 * Request a risk decision from the AI Brain.
 * Returns the FULL decision (action, executed, cooldown) so the caller
 * can drive Signal → Brain → Action → Human UX correctly.
 *
 * Falls back to legacy `/journey/risk/score` on brain failure (score-only).
 */
export async function requestRiskScore(params: {
  sessionId: string;
  userType?: 'child' | 'woman' | 'adult' | 'elderly';
  idleSec?: number;
  anomalyCount?: number;
  speedDropCount?: number;
  battery?: number | null;
  network?: 'online' | 'offline';
  sosActive?: boolean;
  location?: { lat: number; lng: number } | null;
  hour?: number;
}): Promise<{
  risk_score?: number;
  effective_score?: number;
  final_score?: number;
  level?: string;
  risk_level?: string;
  recommended_action?: string;
  executed?: boolean;
  cooldown_applied?: boolean;
  sos_id?: string | null;
  triggers_fired?: string[];
  factors?: string[];
} | null> {
  if (!_online) return null;
  try {
    // Prefer AI Brain endpoint — unified multi-signal decision with autonomous execution
    const brainResp = await api.post('/ai-brain/decide', {
      user_id: params.sessionId,
      user_type: params.userType || 'adult',
      signals: {
        gps: params.location ? { lat: params.location.lat, lng: params.location.lng } : undefined,
        device: {
          battery: params.battery ?? undefined,
          network: params.network !== 'offline',
        },
        time: { hour: params.hour ?? new Date().getHours() },
        motion: { activity: params.sosActive ? 'still' : 'walk' },
      },
      skip_behavior: true, // fast path — behavior layer runs on scheduler
      auto_execute: true,  // let the brain autonomously act
    });
    const d = brainResp.data || {};
    const levelMap: Record<string, 'safe' | 'caution' | 'high' | 'critical'> = {
      GREEN: 'safe', YELLOW: 'caution', RED: 'high', CRITICAL: 'critical',
    };
    const level = levelMap[d.risk_level] || 'safe';
    const score = d.risk_score ?? 0;
    useJourneyEngineStore.getState().setRisk(score, level);
    return {
      risk_score: score,
      effective_score: d.final_score,
      final_score: d.final_score,
      level,
      risk_level: d.risk_level,
      recommended_action: d.recommended_action,
      executed: !!d.executed,
      cooldown_applied: !!d.cooldown_applied,
      sos_id: d.execution_detail?.sos_id ?? d.sos_id ?? null,
      triggers_fired: d.triggers_fired,
      factors: d.triggers_fired,
    };
  } catch (e: any) {
    // Fall back to legacy journey risk endpoint on any brain failure
    console.warn('[JOURNEY_SVC] ai-brain failed, falling back to /journey/risk/score', e?.message);
  }
  try {
    const resp = await api.post('/journey/risk/score', {
      session_id: params.sessionId,
      idle_sec: params.idleSec ?? 0,
      anomaly_count: params.anomalyCount ?? 0,
      speed_drop_count: params.speedDropCount ?? 0,
      battery: params.battery ?? null,
      network: params.network ?? 'online',
      sos_active: params.sosActive ?? false,
      location: params.location ?? null,
      hour: params.hour ?? new Date().getHours(),
    });
    const d = resp.data || {};
    const level = (d.level || 'safe') as 'safe' | 'caution' | 'high' | 'critical';
    const score = d.effective_score ?? d.risk_score ?? 0;
    useJourneyEngineStore.getState().setRisk(score, level);
    return d;
  } catch (e: any) {
    console.warn('[JOURNEY_SVC] risk score failed', e?.message);
    return null;
  }
}

// ── Internal flush ─────────────────────────────────────────────────

function scheduleFlush(delayMs: number): void {
  if (_flushScheduled) return;
  _flushScheduled = setTimeout(() => {
    _flushScheduled = null;
    void flushQueue();
  }, delayMs);
}

async function flushQueue(): Promise<void> {
  if (_flushing || !_online) return;
  _flushing = true;
  try {
    const batch = await peek(BATCH_SIZE);
    if (!batch.length) {
      _flushing = false;
      await refreshQueueSize();
      return;
    }

    // Normalize batch items for /api/journey/sync contract
    const events = batch.map((item) => ({
      id: item.id,
      type: item.type,
      ts: item.created_at,
      ...item.payload,
    }));

    try {
      const resp = await api.post('/journey/sync', { events });
      const successIds = batch.map((b) => b.id);
      await markSuccess(successIds);
      useJourneyEngineStore.getState().markSync();
      if (resp.data?.sos_count > 0) {
        console.warn('[JOURNEY_SVC] synced (incl SOS)', resp.data);
      } else {
        console.log('[JOURNEY_SVC] synced', events.length, 'events');
      }
    } catch (e: any) {
      console.warn('[JOURNEY_SVC] flush batch failed', e?.message);
      const ids = batch.map((b) => b.id);
      await markFailure(ids);
      // Schedule retry with backoff based on highest retry count in batch
      const maxRetry = Math.max(...batch.map((b) => b.retry_count + 1));
      scheduleFlush(computeBackoffMs(maxRetry));
    }

    // If more items pending, schedule another flush
    const remaining = await queueSize();
    if (remaining > 0 && _online) scheduleFlush(500);
    await refreshQueueSize();
  } finally {
    _flushing = false;
  }
}

async function refreshQueueSize(): Promise<void> {
  const n = await queueSize();
  useJourneyEngineStore.getState().setQueueSize(n);
}

export function isOnline(): boolean {
  return _online;
}
