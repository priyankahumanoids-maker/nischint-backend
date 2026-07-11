// GuardianLiveMap — Real-time child tracking map for guardian dashboard
// Fixes: debounced animation, dedup trail, memoized children, user pan detection
import { useState, useEffect, useRef, memo, useMemo, useCallback } from 'react';
import { View, Text, StyleSheet, Dimensions } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { colors, spacing, fontSize, radius } from '@/theme';
import type { ChildLocation } from '@/stores/liveTrackingStore';
import { isChildStale } from '@/stores/liveTrackingStore';
import { JourneyPolyline } from './JourneyPolyline';

var MapView: any = null;
var MarkerComp: any = null;
var PolylineComp: any = null;
var PROVIDER_GOOGLE: any = undefined;
try {
  var Maps = require('react-native-maps');
  MapView = Maps.default;
  MarkerComp = Maps.Marker;
  PolylineComp = Maps.Polyline;
  PROVIDER_GOOGLE = Maps.PROVIDER_GOOGLE;
} catch (e) {
  console.warn('[LIVE_MAP] react-native-maps not available');
}

var RISK_COLORS: Record<string, string> = {
  SAFE: colors.safe,
  LOW: colors.safe,
  MEDIUM: colors.warning,
  HIGH: colors.high,
  CRITICAL: colors.critical,
};

// Role-aware display name — shows identity, not raw DB full_name
var ROLE_ICONS: Record<string, string> = {
  child: 'happy-outline',
  woman: 'shield-half-outline',
  senior: 'accessibility-outline',
};

function getRoleLabel(role: string): string {
  if (role === 'woman' || role === 'women') return 'Women Safety';
  if (role === 'child' || role === 'kid') return 'Kids Safety';
  if (role === 'senior') return 'Senior Care';
  return '';
}

function deriveStatus(speed: number, risk: string, stale: boolean) {
  if (stale) {
    return { label: 'STALE', color: colors.textMuted, icon: 'time-outline' };
  }
  if (risk === 'CRITICAL' || risk === 'HIGH') {
    return { label: 'ALERT', color: colors.critical, icon: 'warning' };
  }
  if (risk === 'MEDIUM') {
    return { label: 'CAUTION', color: colors.warning, icon: 'alert-circle' };
  }
  if (speed > 1.5) {
    return { label: 'MOVING', color: colors.primary, icon: 'walk' };
  }
  if (speed > 0.3) {
    return { label: 'SLOW', color: colors.primaryLight, icon: 'footsteps' };
  }
  return { label: 'IDLE', color: colors.textMuted, icon: 'pause-circle' };
}

function formatSpeed(mps: number) {
  if (mps < 0.3) return 'Stationary';
  var kmh = mps * 3.6;
  if (kmh < 1) return mps.toFixed(1) + ' m/s';
  return kmh.toFixed(1) + ' km/h';
}

function timeAgoShort(iso: string) {
  var sec = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (sec < 5) return 'just now';
  if (sec < 60) return sec + 's ago';
  var min = Math.floor(sec / 60);
  if (min < 60) return min + 'm ago';
  return Math.floor(min / 60) + 'h ago';
}

// Memoized trail polyline — only re-renders when trail array changes
var TrailLine = memo(function TrailLine(props: { coords: Array<{ latitude: number; longitude: number }> }) {
  if (!PolylineComp || props.coords.length < 2) return null;
  return (
    <PolylineComp
      coordinates={props.coords}
      strokeColor={colors.primary}
      strokeWidth={3}
      testID="trail-polyline"
    />
  );
});

// Memoized marker — only re-renders when position actually changes
var ChildMarker = memo(function ChildMarker(props: {
  lat: number;
  lng: number;
  name: string;
  statusLabel: string;
  statusColor: string;
  zone: string;
}) {
  if (!MarkerComp) return null;
  return (
    <MarkerComp
      coordinate={{ latitude: props.lat, longitude: props.lng }}
      title={props.name}
      description={props.statusLabel + ' - ' + props.zone}
      testID="child-marker"
    >
      <View style={[ms.outer, { borderColor: props.statusColor }]}>
        <View style={[ms.inner, { backgroundColor: props.statusColor }]}>
          <Ionicons name="person" size={14} color={colors.white} />
        </View>
      </View>
    </MarkerComp>
  );
});

var ms = StyleSheet.create({
  outer: {
    width: 32, height: 32, borderRadius: 16, borderWidth: 2,
    backgroundColor: colors.bgCard, justifyContent: 'center', alignItems: 'center',
  },
  inner: {
    width: 24, height: 24, borderRadius: 12,
    justifyContent: 'center', alignItems: 'center',
  },
});

interface Props {
  data: ChildLocation;
  height?: number;
  /**
   * If provided, the map renders the session's authoritative tri-color
   * historical polyline (fetched from `/api/guardian/{sid}/polyline`)
   * instead of the in-memory SSE trail. Falls back to the SSE trail
   * when omitted.
   */
  sessionId?: string | null;
}

function GuardianLiveMapInner(props: Props) {
  var data = props.data;
  var height = props.height || 280;
  var sessionId = props.sessionId || null;
  var mapRef = useRef<any>(null);
  var [mapReady, setMapReady] = useState(false);
  var [mapError, setMapError] = useState(false);
  var [tick, setTick] = useState(0);

  // Fix 5: Auto-follow vs user pan
  var isUserInteracting = useRef(false);
  var panTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Fix 1: Debounced animation (~500ms after last update)
  var animTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  var lastAnimated = useRef({ lat: 0, lng: 0 });

  // Tick for time-ago refresh
  useEffect(function() {
    var iv = setInterval(function() { setTick(function(n) { return n + 1; }); }, 5000);
    return function() { clearInterval(iv); };
  }, []);

  // Debounced auto-follow
  useEffect(function() {
    if (!mapReady || !mapRef.current || !data.lat || !data.lng) return;
    if (isUserInteracting.current) return; // Fix 5: don't fight user pan

    // Skip if position hasn't meaningfully changed (~1m threshold)
    var dLat = Math.abs(data.lat - lastAnimated.current.lat);
    var dLng = Math.abs(data.lng - lastAnimated.current.lng);
    if (dLat < 0.00001 && dLng < 0.00001) return;

    if (animTimer.current) clearTimeout(animTimer.current);
    animTimer.current = setTimeout(function() {
      if (mapRef.current && typeof mapRef.current.animateToRegion === 'function' && !isUserInteracting.current) {
        mapRef.current.animateToRegion({
          latitude: data.lat,
          longitude: data.lng,
          latitudeDelta: 0.004,
          longitudeDelta: 0.004,
        }, 600);
        lastAnimated.current = { lat: data.lat, lng: data.lng };
      }
    }, 300);

    return function() {
      if (animTimer.current) clearTimeout(animTimer.current);
    };
  }, [data.lat, data.lng, mapReady]);

  // Fix 5: Pan handlers
  var onPanStart = useCallback(function() {
    isUserInteracting.current = true;
    if (panTimer.current) clearTimeout(panTimer.current);
  }, []);

  var onPanEnd = useCallback(function() {
    // Resume auto-follow after 8s of no interaction
    if (panTimer.current) clearTimeout(panTimer.current);
    panTimer.current = setTimeout(function() {
      isUserInteracting.current = false;
    }, 8000);
  }, []);

  var stale = isChildStale(data);
  var status = deriveStatus(data.speed || 0, data.risk || 'SAFE', stale);
  var riskClr = RISK_COLORS[data.risk] || colors.textMuted;
  // Only require MapView (Polyline is optional — fallback to no trail)
  var canRenderMap = MapView && !mapError;

  // Fix 4: Memoize trail coordinates (defensive: trail may be undefined)
  var trail = data.trail || [];
  var trailCoords = useMemo(function() {
    var coords = [];
    for (var i = 0; i < trail.length; i++) {
      coords.push({ latitude: trail[i].lat, longitude: trail[i].lng });
    }
    if (data.lat && data.lng) {
      coords.push({ latitude: data.lat, longitude: data.lng });
    }
    return coords;
  }, [trail.length, data.lat, data.lng]);

  return (
    <View style={[s.container, { height: height + 90 }]} testID="guardian-live-map">
      {/* Header */}
      <View style={s.header}>
        <View style={s.headerLeft}>
          <View style={[s.liveDot, { backgroundColor: status.color }]} />
          <Ionicons name={(ROLE_ICONS[(data as any).child_role] || 'person') as any} size={16} color={colors.primary} style={{ marginRight: 4 }} />
          <Text style={s.childName}>{data.child_name}</Text>
          {(data as any).child_role && (
            <Text style={{ fontSize: 10, color: colors.textMuted, marginLeft: 6 }}>
              {getRoleLabel((data as any).child_role)}
            </Text>
          )}
        </View>
        <View style={[s.statusChip, { backgroundColor: status.color + '20', borderColor: status.color }]}>
          <Ionicons name={status.icon as any} size={12} color={status.color} />
          <Text style={[s.statusText, { color: status.color }]}>{status.label}</Text>
        </View>
      </View>

      {/* Map */}
      {canRenderMap ? (
        <View style={[s.mapWrap, { height: height }]}>
          <MapView
            ref={mapRef}
            provider={PROVIDER_GOOGLE}
            style={StyleSheet.absoluteFillObject}
            initialRegion={{
              latitude: data.lat,
              longitude: data.lng,
              latitudeDelta: 0.004,
              longitudeDelta: 0.004,
            }}
            showsCompass
            onMapReady={function() { setMapReady(true); }}
            onError={function() { setMapError(true); }}
            onPanDrag={onPanStart}
            onRegionChangeComplete={onPanEnd}
            testID="live-map-view"
          >
            {sessionId ? (
              // Authoritative tri-color historical polyline from the
              // server. Supersedes the in-memory SSE trail when a
              // session is active.
              <JourneyPolyline sessionId={sessionId} />
            ) : (
              PolylineComp && trailCoords.length > 1 ? (
                <TrailLine coords={trailCoords} />
              ) : null
            )}
            <ChildMarker
              lat={data.lat}
              lng={data.lng}
              name={data.child_name}
              statusLabel={status.label}
              statusColor={status.color}
              zone={data.zone}
            />
          </MapView>
        </View>
      ) : (
        <View style={[s.fallback, { height: height }]}>
          <Ionicons name="location" size={32} color={colors.primary} />
          <Text style={s.fallbackCoords}>
            {data.lat.toFixed(6) + ', ' + data.lng.toFixed(6)}
          </Text>
          <Text style={s.fallbackNote}>Map unavailable - GPS active</Text>
        </View>
      )}

      {/* Info bar */}
      <View style={s.infoBar}>
        <View style={s.badgeRow}>
          <View style={s.badge}>
            <Ionicons name="speedometer-outline" size={11} color={colors.textSecondary} />
            <Text style={s.badgeText}>{formatSpeed(data.speed)}</Text>
          </View>
          <View style={s.badge}>
            <Ionicons name="map-outline" size={11} color={colors.textSecondary} />
            <Text style={s.badgeText} numberOfLines={1}>{data.zone.replace('Grid Zone ', '')}</Text>
          </View>
          <View style={[s.badge, { borderColor: riskClr + '40' }]}>
            <View style={[s.riskDot, { backgroundColor: riskClr }]} />
            <Text style={[s.badgeText, { color: riskClr }]}>{data.risk || 'SAFE'}</Text>
          </View>
        </View>
        <Text style={s.updated}>{timeAgoShort(data.ts)}</Text>
      </View>
    </View>
  );
}

export var GuardianLiveMap = memo(GuardianLiveMapInner);

var s = StyleSheet.create({
  container: {
    backgroundColor: colors.bgCard,
    borderRadius: radius.lg,
    overflow: 'hidden',
    marginBottom: spacing.md,
    borderWidth: 1,
    borderColor: colors.primary + '30',
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    backgroundColor: colors.bgElevated,
  },
  headerLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  liveDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  childName: {
    color: colors.textPrimary,
    fontSize: fontSize.sm,
    fontWeight: '700',
  },
  statusChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 12,
    borderWidth: 1,
  },
  statusText: {
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 0.5,
  },
  mapWrap: {
    position: 'relative',
    overflow: 'hidden',
  },
  fallback: {
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: colors.bg,
  },
  fallbackCoords: {
    color: colors.textPrimary,
    fontSize: fontSize.md,
    fontWeight: '600',
    marginTop: spacing.sm,
    fontVariant: ['tabular-nums'],
  },
  fallbackNote: {
    color: colors.textMuted,
    fontSize: fontSize.xs,
    marginTop: 4,
  },
  infoBar: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    backgroundColor: colors.bg,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  badgeRow: {
    flexDirection: 'row',
    gap: 6,
    flex: 1,
  },
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 3,
    backgroundColor: colors.bgCard,
    paddingHorizontal: 6,
    paddingVertical: 3,
    borderRadius: 6,
    borderWidth: 1,
    borderColor: colors.border,
  },
  badgeText: {
    color: colors.textSecondary,
    fontSize: 10,
    maxWidth: 80,
  },
  riskDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
  },
  updated: {
    color: colors.textMuted,
    fontSize: 10,
    marginLeft: 8,
  },
});
