// NISCH-007 Part B — Guardian Incident Feed screen.
//
// Slots into the (tabs) router as the "Incidents" tab.
//
// Behavior:
//   * Map / Feed segmented toggle at top
//   * Zone filter chips below the toggle
//   * Both views share the same `incidents` state — flipping the toggle
//     never re-fetches
//   * SSE patches existing rows in place; new incidents prepend with a
//     200 ms teal flash; resolved incidents fade out of the active view
//   * SSE stale → 30 s polling fallback (canceled the moment SSE recovers)
//
// Data shape: the /nearby endpoint returns `marker_lat`/`marker_lng`
// already rounded to 3 decimal places (~111m) by the backend — that's
// our privacy contract: directionally accurate but never exposes the
// child's precise GPS. When the child has no fix, those fields come
// back `null` and `IncidentMapView` falls back to a per-id bearing
// ray-cast so the marker still has a stable position on the map.
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { View, StyleSheet, TouchableOpacity, Text, ActivityIndicator } from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';

import { colors } from '@/theme';
import api from '@/services/api';
import { useGuardianSSE, isGuardianSSEAlive } from '@/hooks/useGuardianSSE';
import { useGPSLocation } from '@/hooks/useGPSLocation';

import { ZoneFilterBar, ZoneKey } from '@/components/incidents/ZoneFilterBar';
import { IncidentFeedList }       from '@/components/incidents/IncidentFeedList';
import { IncidentMapView, SavedZone } from '@/components/incidents/IncidentMapView';
import { IncidentMarkerSheet }    from '@/components/incidents/IncidentMarkerSheet';
import type { FeedIncident }      from '@/components/incidents/IncidentFeedRow';

const POLL_FALLBACK_MS = 30_000;
const FLASH_DURATION_MS = 200;

type ViewMode = 'map' | 'feed';

export default function GuardianIncidentFeed() {
  const router = useRouter();
  const gps = useGPSLocation({ watchPosition: true });

  const [mode, setMode]               = useState<ViewMode>('feed');
  const [zone, setZone]               = useState<ZoneKey>('all');
  const [incidents, setIncidents]     = useState<FeedIncident[]>([]);
  const [refreshing, setRefreshing]   = useState(false);
  const [loading, setLoading]         = useState(true);
  const [activeId, setActiveId]       = useState<string | null>(null);
  const [savedZones, setSavedZones]   = useState<SavedZone[]>([]);
  // NISCH-008 — incident_id → live stream_id mapping. Populated by
  // the guardian SSE channel (`stream_available` events). Cleared
  // when the stream ends. Used by the marker sheet to show the
  // "🔴 LIVE — tap to listen" affordance.
  const [liveStreams, setLiveStreams] = useState<Record<string, string>>({});

  const pollTimerRef   = useRef<ReturnType<typeof setInterval> | null>(null);
  const flashTimersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  // ── 1. Fetch loop ────────────────────────────────────────────────
  const fetchIncidents = useCallback(async (silent = false) => {
    if (!gps.latitude || !gps.longitude) return;
    if (!silent) setLoading(true);
    try {
      const params: Record<string, string | number> = {
        lat:    gps.latitude,
        lng:    gps.longitude,
        radius: 500,
        status: 'active',
        limit:  20,
      };
      if (zone !== 'all') params.zone = zone;
      const res = await api.get('/incidents/nearby', { params });
      const list: FeedIncident[] = (res.data?.incidents || []).map((i: any) => ({
        id:                       i.id,
        state:                    i.state,
        state_label:              i.state_label,
        severity:                 i.severity,
        distance_metres:          i.distance_metres,
        zone_match:               i.zone_match,
        elapsed_since_created:    i.elapsed_since_created,
        sla_degraded_at_dispatch: !!i.sla_degraded_at_dispatch,
        // Privacy-rounded marker coords (3dp ~111m). May be null when
        // the child has no location fix — IncidentMapView handles the
        // bearing fallback in that case.
        marker_lat: i.marker_lat == null ? null : Number(i.marker_lat),
        marker_lng: i.marker_lng == null ? null : Number(i.marker_lng),
      }));
      setIncidents(list);
    } catch (e: any) {
      if (__DEV__) console.warn('[INCIDENT_FEED] fetch failed:', e?.message);
    } finally {
      if (!silent) setLoading(false);
      setRefreshing(false);
    }
  }, [gps.latitude, gps.longitude, zone]);

  // ── 2. Initial fetch + zone-change refetch ───────────────────────
  useEffect(() => {
    fetchIncidents();
  }, [fetchIncidents]);

  // ── 3. Saved zones (best-effort, silent on failure) ─────────────
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await api.get('/zones');
        const list: SavedZone[] = (res.data?.zones || res.data || [])
          .filter((z: any) => z.active !== false)
          .map((z: any) => ({
            id:         String(z.id),
            lat:        Number(z.lat),
            lng:        Number(z.lng),
            radius_m:   Number(z.radius_m || 100),
            zone_type:  String(z.zone_type || 'custom'),
          }))
          .filter((z: SavedZone) => Number.isFinite(z.lat) && Number.isFinite(z.lng));
        if (!cancelled) setSavedZones(list);
      } catch {
        // Silent — zones are decorative
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // ── 4. SSE patch loop ────────────────────────────────────────────
  useGuardianSSE(useCallback((eventType: string, payload: any) => {
    // NISCH-008 — guardian-side stream lifecycle. We track which
    // incident has a live stream so the marker sheet can render
    // a "🔴 LIVE — tap to listen" affordance.
    if (eventType === 'stream_available' && payload?.stream_id && payload?.incident_id) {
      setLiveStreams((prev) => ({
        ...prev,
        [payload.incident_id]: payload.stream_id,
      }));
      return;
    }
    if (eventType === 'stream_state' && payload?.stream_id) {
      const s = payload.state;
      if (s === 'ended' || s === 'declined') {
        setLiveStreams((prev) => {
          const next: Record<string, string> = {};
          for (const [iid, sid] of Object.entries(prev)) {
            if (sid !== payload.stream_id) next[iid] = sid;
          }
          return next;
        });
      }
      return;
    }

    // We listen to BOTH `incident_state_change` (Day 3 forensic stream)
    // and `incident_created` / `incident_updated` (existing pipeline
    // events) so the feed reflects truth from any path.
    const interesting =
      eventType === 'incident_state_change' ||
      eventType === 'incident_created' ||
      eventType === 'incident_updated';
    if (!interesting) return;

    const inc = payload?.incident || payload;
    const id = inc?.id || inc?.incident_id;
    if (!id) return;

    const newState: string | undefined = inc?.state || inc?.to_state;
    setIncidents((curr) => {
      const idx = curr.findIndex((c) => c.id === id);

      // Resolved → drop from `active` view (the only view we render).
      if (newState === 'resolved' || newState === 'archived') {
        return idx >= 0 ? curr.filter((c) => c.id !== id) : curr;
      }

      if (idx >= 0) {
        // In-place patch — preserve _flash, distance, zone_match.
        const next = [...curr];
        next[idx] = {
          ...next[idx],
          state:        newState || next[idx].state,
          state_label:  inc?.state_label || next[idx].state_label,
          severity:     inc?.severity    || next[idx].severity,
        };
        return next;
      }

      // New row → prepend with flash; trigger a refetch shortly to
      // hydrate distance + zone fields the SSE payload lacks.
      const placeholder: FeedIncident = {
        id,
        state:                    newState || 'detected',
        state_label:              inc?.state_label || 'New incident',
        severity:                 inc?.severity || 'medium',
        distance_metres:          inc?.distance_metres ?? 0,
        zone_match:               inc?.zone_match ?? null,
        elapsed_since_created:    inc?.elapsed_since_created || 'just now',
        sla_degraded_at_dispatch: !!inc?.sla_degraded_at_dispatch,
        // SSE payload doesn't carry rounded markers. Bearing fallback
        // takes over in the map view until the refetch hydrates.
        marker_lat:               null,
        marker_lng:               null,
        _flash: true,
      };
      // Schedule flash clear.
      const t = setTimeout(() => {
        flashTimersRef.current.delete(id);
        setIncidents((cs) => cs.map((c) =>
          c.id === id ? { ...c, _flash: false } : c
        ));
      }, FLASH_DURATION_MS);
      flashTimersRef.current.set(id, t);
      // Hydrate full fields from the API.
      fetchIncidents(true);
      return [placeholder, ...curr];
    });
  }, [fetchIncidents]));

  // ── 5. Polling fallback when SSE is stale/down ───────────────────
  useEffect(() => {
    const tick = () => {
      if (!isGuardianSSEAlive()) {
        fetchIncidents(true);
      }
    };
    pollTimerRef.current = setInterval(tick, POLL_FALLBACK_MS);
    return () => {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    };
  }, [fetchIncidents]);

  // ── 6. Cleanup flash timers on unmount ───────────────────────────
  useEffect(() => () => {
    flashTimersRef.current.forEach((t) => clearTimeout(t));
    flashTimersRef.current.clear();
  }, []);

  // ── 7. Map data — pass incidents straight through. The map view
  //       picks privacy-rounded `marker_lat`/`marker_lng` from the
  //       API and falls back to a stable per-id bearing when null.
  const centre = useMemo(
    () => ({ lat: gps.latitude || 19.0760, lng: gps.longitude || 72.8777 }),
    [gps.latitude, gps.longitude]
  );

  // ── 8. Handlers ──────────────────────────────────────────────────
  const handleRowPress = useCallback((id: string) => {
    router.push({ pathname: '/incident-timeline', params: { id } } as any);
  }, [router]);

  const onPullToRefresh = useCallback(() => {
    setRefreshing(true);
    fetchIncidents(true);
  }, [fetchIncidents]);

  const activeIncident = activeId
    ? incidents.find((i) => i.id === activeId) || null
    : null;

  // ── 9. Render ────────────────────────────────────────────────────
  return (
    <SafeAreaView style={styles.root} edges={['top']}>
      <View style={styles.header}>
        <Text style={styles.title}>Nearby Incidents</Text>
        <View style={styles.toggle}>
          <ToggleBtn
            active={mode === 'feed'}
            label="Feed"
            onPress={() => setMode('feed')}
            testID="toggle-feed"
          />
          <ToggleBtn
            active={mode === 'map'}
            label="Map"
            onPress={() => setMode('map')}
            testID="toggle-map"
          />
        </View>
      </View>

      <ZoneFilterBar active={zone} onChange={setZone} />

      {loading && incidents.length === 0 ? (
        <View style={styles.loading}>
          <ActivityIndicator color={colors.primary} />
        </View>
      ) : mode === 'feed' ? (
        <IncidentFeedList
          incidents={incidents}
          refreshing={refreshing}
          onRefresh={onPullToRefresh}
          onRowPress={handleRowPress}
        />
      ) : (
        <IncidentMapView
          centre={centre}
          incidents={incidents}
          savedZones={savedZones}
          onMarkerPress={setActiveId}
          onRecentre={() => {}}
        />
      )}

      <IncidentMarkerSheet
        incident={activeIncident}
        liveStreamId={activeId ? liveStreams[activeId] || null : null}
        onClose={() => setActiveId(null)}
        onViewTimeline={(id) => {
          setActiveId(null);
          handleRowPress(id);
        }}
      />
    </SafeAreaView>
  );
}

function ToggleBtn({
  active, label, onPress, testID,
}: { active: boolean; label: string; onPress: () => void; testID: string }) {
  return (
    <TouchableOpacity
      testID={testID}
      onPress={onPress}
      activeOpacity={0.85}
      style={[styles.toggleBtn, active && styles.toggleBtnActive]}
    >
      <Text style={[styles.toggleText, active && styles.toggleTextActive]}>
        {label}
      </Text>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: colors.bg,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingTop: 12,
    paddingBottom: 8,
  },
  title: {
    fontSize: 22,
    fontWeight: '700',
    color: colors.textPrimary,
  },
  toggle: {
    flexDirection: 'row',
    backgroundColor: colors.bgCard,
    borderRadius: 10,
    padding: 3,
  },
  toggleBtn: {
    paddingHorizontal: 14,
    paddingVertical: 6,
    borderRadius: 8,
  },
  toggleBtnActive: {
    backgroundColor: colors.primary,
  },
  toggleText: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.textSecondary,
  },
  toggleTextActive: {
    color: colors.white,
  },
  loading: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
});
