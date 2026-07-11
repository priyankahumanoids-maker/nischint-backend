// Journey Polyline — tri-color historical GPS trail for guardians.
//
// Consumes `GET /api/guardian/{session_id}/polyline` and renders the
// returned points as segmented polylines:
//
//   SOLID BLUE    normal edges (good signal, gap < 15s)
//   DASHED AMBER  degraded edges (15s ≤ gap < 60s OR quality='degraded')
//   DASHED GREY   offline edges (gap ≥ 60s — we "missed" points here)
//
// Polls the endpoint every `pollIntervalMs` (default 15s) to keep the
// live view fresh. On unmount the poll is cleared.
//
// Designed to be dropped INSIDE a `<MapView>` — it renders zero or
// more `<Polyline>` children. It does not render any map chrome.
import { memo, useEffect, useMemo, useRef, useState } from 'react';
import { guardianService } from '@/services/endpoints';
import { colors } from '@/theme';

// react-native-maps is optional — `require` so the module tree loads
// even on platforms where it isn't installed.
let PolylineComp: any = null;
try {
  const Maps = require('react-native-maps');
  PolylineComp = Maps.Polyline;
} catch {}

// ── Tunables ────────────────────────────────────────────────────────
// These are deliberately conservative. Tuning them higher hides
// network jitter at the cost of masking real degradation.
export const GAP_DEGRADED_S = 15;  // ≥ this → degraded
export const GAP_OFFLINE_S  = 60;  // ≥ this → offline

export type PolylinePoint = {
  seq: number;
  lat: number;
  lng: number;
  ts: string | null;
  quality: string | null;
  gap_s: number | null;
};

export type PolylineEnvelope = {
  session_id: string;
  user_id: string;
  status: string;
  is_offline: boolean;
  is_stale: boolean;
  stale_seconds: number | null;
  last_seen_online_at: string | null;
  total_points: number;
  offline_gaps: number;
  max_gap_seconds: number;
  points: PolylinePoint[];
  last_point: PolylinePoint | null;
  returned: number;
  limit: number;
  truncated: boolean;
};

export type SegmentKind = 'good' | 'degraded' | 'offline';

export type Segment = {
  kind: SegmentKind;
  coords: Array<{ latitude: number; longitude: number }>;
};

// Pure — so it's testable without a device.
export function classifyEdge(prev: PolylinePoint, next: PolylinePoint): SegmentKind {
  const gap = next.gap_s ?? 0;
  if (gap >= GAP_OFFLINE_S) return 'offline';
  if (gap >= GAP_DEGRADED_S) return 'degraded';
  if (prev.quality === 'degraded' || next.quality === 'degraded') return 'degraded';
  return 'good';
}

// Pure — groups consecutive same-kind edges into polyline segments.
// Each segment's `coords` includes the shared boundary vertex so
// adjacent segments visually touch without gaps.
export function segmentize(points: PolylinePoint[]): Segment[] {
  if (!points || points.length < 2) return [];
  const segs: Segment[] = [];
  let cur: Segment = {
    kind: classifyEdge(points[0], points[1]),
    coords: [
      { latitude: points[0].lat, longitude: points[0].lng },
      { latitude: points[1].lat, longitude: points[1].lng },
    ],
  };
  for (let i = 2; i < points.length; i++) {
    const kind = classifyEdge(points[i - 1], points[i]);
    const coord = { latitude: points[i].lat, longitude: points[i].lng };
    if (kind === cur.kind) {
      cur.coords.push(coord);
    } else {
      segs.push(cur);
      cur = {
        kind,
        coords: [
          { latitude: points[i - 1].lat, longitude: points[i - 1].lng },
          coord,
        ],
      };
    }
  }
  segs.push(cur);
  return segs;
}

// ── Style lookup ────────────────────────────────────────────────────
const STYLES: Record<SegmentKind, {
  strokeColor: string;
  strokeWidth: number;
  lineDashPattern?: number[];
}> = {
  good: {
    strokeColor: colors.primary,       // solid blue
    strokeWidth: 4,
  },
  degraded: {
    strokeColor: colors.warning,       // amber
    strokeWidth: 3,
    lineDashPattern: [10, 8],
  },
  offline: {
    strokeColor: colors.textMuted,     // grey
    strokeWidth: 2,
    lineDashPattern: [4, 6],
  },
};

interface Props {
  sessionId: string;
  pollIntervalMs?: number;
  limit?: number;
  onLoad?: (envelope: PolylineEnvelope) => void;
  onError?: (err: unknown) => void;
}

function JourneyPolylineInner(props: Props) {
  const { sessionId, pollIntervalMs = 15000, limit = 1000, onLoad, onError } = props;
  const [envelope, setEnvelope] = useState<PolylineEnvelope | null>(null);
  const abortRef = useRef<{ cancelled: boolean }>({ cancelled: false });

  useEffect(() => {
    abortRef.current = { cancelled: false };
    const localAbort = abortRef.current;

    const load = async () => {
      try {
        const res = await guardianService.getPolyline(sessionId, limit);
        if (localAbort.cancelled) return;
        const data = res.data as PolylineEnvelope;
        setEnvelope(data);
        if (onLoad) onLoad(data);
      } catch (e) {
        if (!localAbort.cancelled && onError) onError(e);
      }
    };

    load();
    const iv = pollIntervalMs > 0 ? setInterval(load, pollIntervalMs) : null;
    return () => {
      localAbort.cancelled = true;
      if (iv) clearInterval(iv);
    };
  }, [sessionId, pollIntervalMs, limit, onLoad, onError]);

  const segments = useMemo(() => segmentize(envelope?.points || []), [envelope]);

  if (!PolylineComp || segments.length === 0) return null;

  return (
    <>
      {segments.map((seg, idx) => {
        const style = STYLES[seg.kind];
        return (
          <PolylineComp
            key={`${seg.kind}-${idx}`}
            coordinates={seg.coords}
            strokeColor={style.strokeColor}
            strokeWidth={style.strokeWidth}
            lineDashPattern={style.lineDashPattern}
            // Offline segments draw underneath so a following good
            // segment visually "wins" at overlap points.
            zIndex={seg.kind === 'good' ? 3 : seg.kind === 'degraded' ? 2 : 1}
            testID={`journey-polyline-${seg.kind}`}
          />
        );
      })}
    </>
  );
}

export const JourneyPolyline = memo(JourneyPolylineInner);
export default JourneyPolyline;
