// Risk Overlay Map — Unified Google Maps (react-native-maps)
// Displays per-child color-coded risk markers + optional circles.
// Data source: useRiskStore + useLiveTrackingStore (+ hard-sync with active
// emergency alerts from useAlertStore). Also kick-started with an initial
// /guardian/live/risk fetch so cold-start shows data before SSE/polling warms up.

import React, { useEffect, useState, useRef, useCallback, useMemo } from 'react';
import { View, Text, StyleSheet, ActivityIndicator, TouchableOpacity } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { guardianDashboardService } from '@/services/endpoints';
import { useRiskStore, type RiskEntry } from '@/stores/riskStore';
import { useAlertStore } from '@/stores/alertStore';
import { useLiveTrackingStore } from '@/stores/liveTrackingStore';

// Lazy-load react-native-maps so a missing native module never crashes bundle
// evaluation (Expo Go / web). If unavailable, render the text fallback card.
let MapView: any = null;
let MarkerComp: any = null;
let CircleComp: any = null;
let PROVIDER_GOOGLE: any = undefined;
let mapsAvailable = false;
try {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const Maps = require('react-native-maps');
  MapView = Maps.default;
  MarkerComp = Maps.Marker;
  CircleComp = Maps.Circle;
  PROVIDER_GOOGLE = Maps.PROVIDER_GOOGLE;
  mapsAvailable = !!MapView;
} catch (e) {
  console.warn('[RISK_MAP] react-native-maps not available — rendering fallback:', (e as any)?.message || e);
  mapsAvailable = false;
}

const RISK_COLORS: Record<string, string> = {
  CRITICAL: '#FF3B30',
  RED: '#FF3B30',
  YELLOW: '#FFCC00',
  GREEN: '#34C759',
  SAFE: '#34C759',
  LOW: '#34C759',
  MEDIUM: '#FFCC00',
  HIGH: '#FF3B30',
};

function riskColorFor(level: string): string {
  return RISK_COLORS[level] || '#34C759';
}

export function RiskOverlayMap() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [mapReady, setMapReady] = useState(false);
  const [selectedChild, setSelectedChild] = useState<RiskEntry | null>(null);
  const mapRef = useRef<any>(null);
  const prevCriticalRef = useRef<string | null>(null);

  const riskEntries = useRiskStore((s) => s.entries);
  const liveChildren = useLiveTrackingStore((s) => s.children);
  const storeAlerts = useAlertStore((s) => s.alerts);

  // Initial cold-start fetch; SSE or polling hook takes over afterwards.
  const fetchRisk = useCallback(async () => {
    try {
      const res = await guardianDashboardService.getLiveRisk();
      const data: RiskEntry[] = res.data || [];
      const store = useRiskStore.getState();
      for (const entry of data) {
        store.updateRisk(entry);
      }
      setError(null);
    } catch (e: any) {
      console.warn('[RISK_MAP] Initial fetch failed:', e?.message);
      setError('Could not load risk data');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchRisk(); }, [fetchRisk]);

  // Merge SSE risk entries with live tracking positions + active alert hard-sync
  const mergedData: RiskEntry[] = useMemo(() => {
    return Object.values(riskEntries).map((entry) => {
      const live = liveChildren[entry.child_id];
      const merged: RiskEntry = { ...entry, factors: entry.factors || [] };
      if (live && live.lat && live.lng) {
        merged.lat = live.lat;
        merged.lng = live.lng;
      }
      const hasEmergencyAlert = storeAlerts.some(
        (a: any) =>
          (a.child_id === entry.child_id) &&
          (a.alert_type === 'emergency_triggered' ||
            a.alert_type === 'auto_escalated' ||
            a.alert_type === 'voice_distress')
      );
      if (hasEmergencyAlert) {
        merged.risk = 'CRITICAL';
        merged.score = Math.max(merged.score, 9);
        if (!merged.factors.includes('Active emergency alert')) {
          merged.factors = [...merged.factors, 'Active emergency alert'];
        }
      }
      return merged;
    });
  }, [riskEntries, liveChildren, storeAlerts]);

  // Auto-focus on the highest-score CRITICAL child (debounced)
  useEffect(() => {
    if (!mapReady || !mapRef.current) return;
    const criticals = mergedData.filter((r) => r.risk === 'CRITICAL');
    if (criticals.length === 0) {
      prevCriticalRef.current = null;
      return;
    }
    const top = [...criticals].sort((a, b) => b.score - a.score)[0];
    if (top.child_id !== prevCriticalRef.current) {
      prevCriticalRef.current = top.child_id;
      if (typeof mapRef.current.animateToRegion === 'function') {
        mapRef.current.animateToRegion({
          latitude: top.lat,
          longitude: top.lng,
          latitudeDelta: 0.01,
          longitudeDelta: 0.01,
        }, 800);
      }
    }
  }, [mergedData, mapReady]);

  const initialRegion = useMemo(() => {
    const first = mergedData[0];
    if (first && first.lat && first.lng) {
      return {
        latitude: first.lat,
        longitude: first.lng,
        latitudeDelta: 0.02,
        longitudeDelta: 0.02,
      };
    }
    // Default: Bangalore (fallback only; overridden once data arrives)
    return { latitude: 12.97, longitude: 77.59, latitudeDelta: 0.1, longitudeDelta: 0.1 };
  }, [mergedData.length > 0]);

  if (loading && Object.keys(riskEntries).length === 0) {
    return (
      <View style={styles.center} testID="risk-map-loading">
        <ActivityIndicator size="large" color="#0EA5E9" />
        <Text style={styles.loadingText}>Loading risk map...</Text>
      </View>
    );
  }

  if (!mapsAvailable || !MapView) {
    return (
      <View style={styles.center} testID="risk-map-fallback">
        <Ionicons name="map-outline" size={40} color="#64748B" />
        <Text style={styles.loadingText}>Risk Overlay</Text>
        <Text style={{ color: '#64748B', fontSize: 12, marginTop: 4, paddingHorizontal: 24, textAlign: 'center' }}>
          {mergedData.length === 0
            ? 'No active journeys — children without live sessions won\'t show here.'
            : `${mergedData.length} child${mergedData.length > 1 ? 'ren' : ''} being tracked.`}
        </Text>
        {mergedData.slice(0, 5).map((entry) => (
          <View key={entry.child_id} style={{ flexDirection: 'row', alignItems: 'center', gap: 10, marginTop: 10, paddingHorizontal: 16 }}>
            <View style={{ width: 10, height: 10, borderRadius: 5, backgroundColor: riskColorFor(entry.risk) }} />
            <Text style={{ color: '#F1F5F9', fontSize: 13, fontWeight: '600' }}>{entry.child_name}</Text>
            <Text style={{ color: '#94A3B8', fontSize: 11 }}>
              {entry.risk} · {entry.score}/10
            </Text>
          </View>
        ))}
      </View>
    );
  }

  return (
    <View style={styles.container} testID="risk-overlay-map">
      <MapView
        ref={mapRef}
        provider={PROVIDER_GOOGLE}
        style={styles.map}
        initialRegion={initialRegion}
        showsCompass
        showsMyLocationButton={false}
        onMapReady={() => setMapReady(true)}
        testID="risk-overlay-map-view"
      >
        {mergedData.map((entry) => {
          if (!entry.lat || !entry.lng) return null;
          const clr = riskColorFor(entry.risk);
          const isCritical = entry.risk === 'CRITICAL';
          return (
            <React.Fragment key={entry.child_id}>
              {/* Emphasis circle for HIGH/CRITICAL */}
              {(entry.risk === 'CRITICAL' || entry.risk === 'RED') && CircleComp && (
                <CircleComp
                  center={{ latitude: entry.lat, longitude: entry.lng }}
                  radius={isCritical ? 180 : 120}
                  strokeColor={clr}
                  strokeWidth={2}
                  fillColor={clr + '33'}
                />
              )}
              <MarkerComp
                coordinate={{ latitude: entry.lat, longitude: entry.lng }}
                title={entry.child_name}
                description={`${entry.risk} · ${entry.score}/10 · ${entry.speed_kmh?.toFixed?.(1) ?? 0} km/h`}
                onPress={() => setSelectedChild(entry)}
                testID={`risk-marker-${entry.child_id}`}
              >
                <View style={[markerStyles.outer, { borderColor: clr }]}>
                  <View style={[markerStyles.inner, { backgroundColor: clr }]}>
                    <Ionicons name="person" size={14} color="#FFF" />
                  </View>
                </View>
              </MarkerComp>
            </React.Fragment>
          );
        })}
      </MapView>

      {/* Legend */}
      <View style={styles.legend}>
        {([
          { level: 'GREEN', label: 'Safe' },
          { level: 'YELLOW', label: 'Caution' },
          { level: 'RED', label: 'High Risk' },
          { level: 'CRITICAL', label: 'Critical' },
        ] as const).map(({ level, label }) => (
          <View key={level} style={styles.legendItem}>
            <View style={[styles.legendDot, { backgroundColor: riskColorFor(level) }]} />
            <Text style={styles.legendText}>{label}</Text>
          </View>
        ))}
      </View>

      {mergedData.length === 0 && !error && (
        <View style={styles.emptyOverlay} testID="risk-map-empty">
          <Ionicons name="map-outline" size={32} color="#6B7280" />
          <Text style={styles.emptyText}>No active journeys to display</Text>
          <Text style={styles.emptySubtext}>Risk zones appear when a child starts a journey</Text>
        </View>
      )}

      {error && (
        <View style={styles.errorOverlay}>
          <Text style={styles.errorText}>{error}</Text>
          <TouchableOpacity onPress={fetchRisk} style={styles.retryBtn} testID="risk-map-retry">
            <Text style={styles.retryText}>Retry</Text>
          </TouchableOpacity>
        </View>
      )}

      {selectedChild && (
        <View style={styles.infoCard} testID="risk-map-info-card">
          <TouchableOpacity
            style={styles.infoClose}
            onPress={() => setSelectedChild(null)}
            testID="risk-map-info-close"
          >
            <Ionicons name="close" size={18} color="#9CA3AF" />
          </TouchableOpacity>
          <View style={styles.infoHeader}>
            <View style={[styles.riskBadge, { backgroundColor: riskColorFor(selectedChild.risk) }]}>
              <Text style={styles.riskBadgeText}>{selectedChild.risk}</Text>
            </View>
            <Text style={styles.infoName}>{selectedChild.child_name}</Text>
          </View>
          <Text style={styles.infoScore}>
            Risk Score: {selectedChild.score}/10 | Speed: {selectedChild.speed_kmh ?? 0} km/h
          </Text>
          {selectedChild.factors && selectedChild.factors.length > 0 && (
            <Text style={styles.infoFactors}>
              {selectedChild.factors.join(' | ')}
            </Text>
          )}
          <Text style={styles.infoTime}>
            Last update: {new Date(selectedChild.last_updated).toLocaleTimeString()}
          </Text>
        </View>
      )}
    </View>
  );
}

const markerStyles = StyleSheet.create({
  outer: {
    width: 32, height: 32, borderRadius: 16, borderWidth: 2,
    backgroundColor: '#FFFFFF', justifyContent: 'center', alignItems: 'center',
  },
  inner: {
    width: 24, height: 24, borderRadius: 12,
    justifyContent: 'center', alignItems: 'center',
  },
});

const styles = StyleSheet.create({
  container: { flex: 1, position: 'relative' },
  map: { flex: 1 },
  center: { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#0F172A' },
  loadingText: { color: '#94A3B8', marginTop: 12, fontSize: 14 },
  legend: {
    position: 'absolute', top: 12, right: 12,
    backgroundColor: '#1E293BEE', borderRadius: 10, padding: 10, gap: 6,
  },
  legendItem: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  legendDot: { width: 10, height: 10, borderRadius: 5 },
  legendText: { color: '#E2E8F0', fontSize: 11 },
  emptyOverlay: {
    position: 'absolute', top: 0, left: 0, right: 0, bottom: 0,
    justifyContent: 'center', alignItems: 'center', backgroundColor: '#0F172ACC',
  },
  emptyText: { color: '#94A3B8', fontSize: 16, marginTop: 12, fontWeight: '600' },
  emptySubtext: { color: '#64748B', fontSize: 12, marginTop: 4 },
  errorOverlay: {
    position: 'absolute', bottom: 80, left: 20, right: 20,
    backgroundColor: '#7F1D1DEE', borderRadius: 10, padding: 14, alignItems: 'center',
  },
  errorText: { color: '#FCA5A5', fontSize: 13 },
  retryBtn: { marginTop: 8, paddingHorizontal: 16, paddingVertical: 6, backgroundColor: '#DC2626', borderRadius: 8 },
  retryText: { color: '#FFF', fontWeight: '600', fontSize: 13 },
  infoCard: {
    position: 'absolute', bottom: 20, left: 16, right: 16,
    backgroundColor: '#1E293BF5', borderRadius: 14, padding: 16,
    borderWidth: 1, borderColor: '#334155',
  },
  infoClose: { position: 'absolute', top: 10, right: 10 },
  infoHeader: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  riskBadge: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6 },
  riskBadgeText: { color: '#FFF', fontSize: 11, fontWeight: '800' },
  infoName: { color: '#F1F5F9', fontSize: 17, fontWeight: '700' },
  infoScore: { color: '#94A3B8', fontSize: 12, marginTop: 6 },
  infoFactors: { color: '#FBBF24', fontSize: 12, marginTop: 4 },
  infoTime: { color: '#64748B', fontSize: 11, marginTop: 6 },
});
