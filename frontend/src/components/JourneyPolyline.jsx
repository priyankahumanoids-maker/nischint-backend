// JourneyPolyline (web / react-leaflet) — tri-color historical GPS
// trail for guardian live-map pages. Mirrors the React Native component
// at `mobile/components/JourneyPolyline.tsx`. The pure segmentation
// logic is intentionally identical so a guardian sees the same trail
// shape on phone and desktop.
//
//   SOLID BLUE    good edges (gap < 15s)
//   DASHED AMBER  degraded edges (gap 15–60s OR quality == 'degraded')
//   DASHED GREY   offline edges (gap >= 60s)
import React, { memo, useEffect, useMemo, useRef, useState } from 'react';
import { Polyline } from 'react-leaflet';
import api from '../api';

// Keep in sync with `mobile/components/JourneyPolyline.tsx`.
export const GAP_DEGRADED_S = 15;
export const GAP_OFFLINE_S = 60;

export function classifyEdge(prev, next) {
  const gap = next.gap_s ?? 0;
  if (gap >= GAP_OFFLINE_S) return 'offline';
  if (gap >= GAP_DEGRADED_S) return 'degraded';
  if (prev.quality === 'degraded' || next.quality === 'degraded') return 'degraded';
  return 'good';
}

export function segmentize(points) {
  if (!points || points.length < 2) return [];
  const segs = [];
  let cur = {
    kind: classifyEdge(points[0], points[1]),
    coords: [
      [points[0].lat, points[0].lng],
      [points[1].lat, points[1].lng],
    ],
  };
  for (let i = 2; i < points.length; i++) {
    const kind = classifyEdge(points[i - 1], points[i]);
    const coord = [points[i].lat, points[i].lng];
    if (kind === cur.kind) {
      cur.coords.push(coord);
    } else {
      segs.push(cur);
      cur = {
        kind,
        coords: [
          [points[i - 1].lat, points[i - 1].lng],
          coord,
        ],
      };
    }
  }
  segs.push(cur);
  return segs;
}

// Leaflet uses a `dashArray` SVG string ("10,8" = 10px dash, 8px gap).
const STYLES = {
  good:     { color: '#06b6d4', weight: 4, opacity: 0.95 },
  degraded: { color: '#f59e0b', weight: 3, opacity: 0.9, dashArray: '10,8' },
  offline:  { color: '#64748b', weight: 2, opacity: 0.75, dashArray: '4,6' },
};

/**
 * Drop inside a `<MapContainer>`. Polls the polyline endpoint every
 * `pollIntervalMs` (default 15s).
 */
function JourneyPolylineWebInner({
  sessionId,
  pollIntervalMs = 15000,
  limit = 1000,
  onLoad,
  onError,
}) {
  const [envelope, setEnvelope] = useState(null);
  const abortRef = useRef({ cancelled: false });

  useEffect(() => {
    if (!sessionId) return undefined;
    abortRef.current = { cancelled: false };
    const localAbort = abortRef.current;

    const load = async () => {
      try {
        const res = await api.get(`/guardian/${sessionId}/polyline?limit=${limit}`);
        if (localAbort.cancelled) return;
        setEnvelope(res.data);
        if (onLoad) onLoad(res.data);
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

  if (!sessionId || segments.length === 0) return null;

  return (
    <>
      {segments.map((seg, idx) => (
        <Polyline
          key={`${seg.kind}-${idx}`}
          positions={seg.coords}
          pathOptions={STYLES[seg.kind]}
          data-testid={`journey-polyline-${seg.kind}`}
        />
      ))}
    </>
  );
}

const JourneyPolyline = memo(JourneyPolylineWebInner);
export default JourneyPolyline;
