// useGuardianLocationPolling — polls /guardian/live/risk every N seconds
// and hydrates risk + live-tracking stores so the map stays warm even
// when SSE is unavailable.
//
// CRITICAL: Polling now coordinates with SSE health. When the singleton
// guardian SSE reports alive AND not stale, polling skips its tick —
// avoiding double-fetch and battery/network waste. The moment SSE goes
// stale or disconnects, polling resumes automatically.
//
// Logs the audit asked for:
//   [POLLING_FALLBACK_ENABLED]  — first tick after SSE went stale
//   [POLLING_FALLBACK_DISABLED] — first tick where SSE recovered
//   [POLLING_DISABLED]          — single skipped tick (debug)
import { useEffect, useRef } from 'react';
import { guardianDashboardService } from '@/services/endpoints';
import { useRiskStore } from '@/stores/riskStore';
import { useLiveTrackingStore } from '@/stores/liveTrackingStore';
import { isGuardianSSEAlive } from '@/hooks/useGuardianSSE';

const DEFAULT_INTERVAL_MS = 5000;

export function useGuardianLocationPolling(
  enabled: boolean = true,
  intervalMs: number = DEFAULT_INTERVAL_MS
) {
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const inFlightRef = useRef<boolean>(false);
  // Tracks the last "polling state" we logged so we don't spam every
  // tick — only log on transitions.
  const wasFallbackActiveRef = useRef<boolean | null>(null);

  useEffect(() => {
    if (!enabled) return;
    // Singleton guard inside the effect — a stale interval from a
    // previous fast re-mount would otherwise stack a second tick.
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }

    let cancelled = false;

    const poll = async () => {
      if (inFlightRef.current) return;

      // Coordination gate: skip the tick when SSE is alive + fresh.
      const sseAlive = isGuardianSSEAlive();
      if (sseAlive) {
        if (wasFallbackActiveRef.current !== false) {
          console.log('[POLLING_FALLBACK_DISABLED] guardian — SSE healthy');
          wasFallbackActiveRef.current = false;
        }
        return;
      }
      if (wasFallbackActiveRef.current !== true) {
        console.log('[POLLING_FALLBACK_ENABLED] guardian — SSE stale/down');
        wasFallbackActiveRef.current = true;
      }

      inFlightRef.current = true;
      try {
        const res = await guardianDashboardService.getLiveRisk();
        if (cancelled) return;
        const rows: any[] = Array.isArray(res.data) ? res.data : [];
        const riskStore = useRiskStore.getState();
        const liveStore = useLiveTrackingStore.getState();

        for (const row of rows) {
          const childId = String(row.child_id);
          const lat = Number(row.lat);
          const lng = Number(row.lng);
          if (!childId || Number.isNaN(lat) || Number.isNaN(lng)) continue;

          riskStore.updateRisk({
            child_id: childId,
            child_name: row.child_name || 'Child',
            lat,
            lng,
            risk: row.risk || 'GREEN',
            score: Number(row.score) || 0,
            factors: Array.isArray(row.factors) ? row.factors : [],
            speed_kmh: Number(row.speed_kmh) || 0,
            last_updated: row.last_updated || new Date().toISOString(),
          });

          liveStore.updateChild(childId, {
            child_id: childId,
            child_name: row.child_name || 'Child',
            child_role: row.child_role || 'child',
            lat,
            lng,
            speed: (Number(row.speed_kmh) || 0) / 3.6,
            zone: row.zone || '',
            risk: row.risk || 'SAFE',
            ts: row.last_updated || new Date().toISOString(),
          });
        }
      } catch (e: any) {
        if (__DEV__) console.warn('[LOC_POLL] failed:', e?.message);
      } finally {
        inFlightRef.current = false;
      }
    };

    // Kick off immediately, then on interval.
    poll();
    timerRef.current = setInterval(poll, intervalMs);

    return () => {
      cancelled = true;
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [enabled, intervalMs]);
}
