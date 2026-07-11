// LocationMap — GPS-first map component with automatic fallback
// GPS coordinates are ALWAYS visible. Map is a non-blocking visual layer.
import { useState, useEffect, useRef } from 'react';
import { View, Text, StyleSheet, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { colors, spacing, fontSize, radius } from '@/theme';

// Lazy-load MapView to avoid crash if native module is missing
let MapView: any = null;
let Marker: any = null;
let PROVIDER_GOOGLE: any = undefined;
try {
  const Maps = require('react-native-maps');
  MapView = Maps.default;
  Marker = Maps.Marker;
  PROVIDER_GOOGLE = Maps.PROVIDER_GOOGLE;
} catch (e) {
  console.warn('[MAP] react-native-maps not available:', e);
}

interface LocationMapProps {
  latitude: number | null;
  longitude: number | null;
  accuracy: number | null;
  timestamp: number | null;
  secondsAgo: number | null;
  isLoading: boolean;
  error: string | null;
  permissionStatus: string;
  height?: number;
}

export function LocationMap({
  latitude, longitude, accuracy, timestamp,
  secondsAgo, isLoading, error, permissionStatus,
  height = 220,
}: LocationMapProps) {
  const [mapError, setMapError] = useState(false);
  const [mapReady, setMapReady] = useState(false);
  const mapRef = useRef<any>(null);

  const hasCoords = latitude !== null && longitude !== null;

  // Animate map to new coords when they change
  useEffect(() => {
    if (hasCoords && mapReady && mapRef.current) {
      mapRef.current.animateToRegion({
        latitude, longitude,
        latitudeDelta: 0.005, longitudeDelta: 0.005,
      }, 500);
    }
  }, [latitude, longitude, mapReady]);

  // GPS info bar — ALWAYS visible
  const GPSInfoBar = () => (
    <View style={s.gpsBar} testID="gps-info-bar">
      <View style={s.gpsRow}>
        <Ionicons
          name={hasCoords ? 'location' : 'location-outline'}
          size={16}
          color={hasCoords ? colors.safe : colors.textMuted}
        />
        {isLoading ? (
          <Text style={s.gpsText}>Acquiring GPS fix...</Text>
        ) : error ? (
          <Text style={[s.gpsText, { color: colors.critical }]}>{error}</Text>
        ) : hasCoords ? (
          <Text style={s.gpsText}>
            {latitude!.toFixed(6)}, {longitude!.toFixed(6)}
          </Text>
        ) : (
          <Text style={s.gpsText}>No location</Text>
        )}
      </View>
      <View style={s.gpsRow}>
        {hasCoords && accuracy != null && (
          <Text style={s.gpsMeta}>{accuracy.toFixed(0)}m</Text>
        )}
        {secondsAgo != null && (
          <Text style={s.gpsMeta}>
            {secondsAgo < 5 ? 'Just now' : `${secondsAgo}s ago`}
          </Text>
        )}
      </View>
    </View>
  );

  // Loading state
  if (isLoading) {
    return (
      <View style={[s.container, { height }]}>
        <View style={[s.fallback, { height: height - 40 }]}>
          <ActivityIndicator size="large" color={colors.primary} />
          <Text style={s.fallbackText}>Acquiring GPS signal...</Text>
        </View>
        <GPSInfoBar />
      </View>
    );
  }

  // Permission denied
  if (permissionStatus === 'denied') {
    return (
      <View style={[s.container, { height }]}>
        <View style={[s.fallback, { height: height - 40 }]}>
          <Ionicons name="warning" size={36} color={colors.warning} />
          <Text style={s.fallbackText}>Location permission denied</Text>
          <Text style={s.fallbackSub}>Enable location in device Settings</Text>
        </View>
        <GPSInfoBar />
      </View>
    );
  }

  // No coords yet
  if (!hasCoords) {
    return (
      <View style={[s.container, { height }]}>
        <View style={[s.fallback, { height: height - 40 }]}>
          <Ionicons name="navigate-outline" size={36} color={colors.textMuted} />
          <Text style={s.fallbackText}>{error || 'Waiting for GPS fix...'}</Text>
        </View>
        <GPSInfoBar />
      </View>
    );
  }

  // Map available + has coords → render map with fallback
  const canRenderMap = MapView && !mapError;

  return (
    <View style={[s.container, { height }]} testID="location-map-container">
      {canRenderMap ? (
        <View style={[s.mapWrap, { height: height - 40 }]}>
          <MapView
            ref={mapRef}
            provider={PROVIDER_GOOGLE}
            style={StyleSheet.absoluteFillObject}
            initialRegion={{
              latitude, longitude,
              latitudeDelta: 0.005, longitudeDelta: 0.005,
            }}
            showsUserLocation
            showsMyLocationButton
            showsCompass
            onMapReady={() => {
              console.log('[MAP] Map rendered successfully');
              setMapReady(true);
            }}
            onError={(e: any) => {
              console.warn('[MAP] Map render error — switching to fallback:', e.nativeEvent?.error);
              setMapError(true);
            }}
            testID="location-map-view"
          >
            <Marker
              coordinate={{ latitude, longitude }}
              title="Current Location"
              pinColor={colors.primary}
              testID="location-marker"
            />
          </MapView>
          {!mapReady && (
            <View style={[StyleSheet.absoluteFillObject, s.mapLoading]}>
              <ActivityIndicator size="small" color={colors.primary} />
              <Text style={s.mapLoadingText}>Loading map...</Text>
            </View>
          )}
        </View>
      ) : (
        <View style={[s.fallback, { height: height - 40 }]}>
          <Ionicons name="location" size={36} color={colors.primary} />
          <Text style={s.fallbackCoords}>
            {latitude!.toFixed(6)}, {longitude!.toFixed(6)}
          </Text>
          {accuracy != null && (
            <Text style={s.fallbackSub}>Accuracy: {accuracy.toFixed(0)}m</Text>
          )}
          <Text style={s.fallbackNote}>Map unavailable — GPS active</Text>
        </View>
      )}
      <GPSInfoBar />
    </View>
  );
}

const s = StyleSheet.create({
  container: {
    borderRadius: radius.lg,
    overflow: 'hidden',
    backgroundColor: colors.bgCard,
    marginBottom: spacing.md,
  },
  mapWrap: {
    position: 'relative',
    overflow: 'hidden',
  },
  mapLoading: {
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: colors.bgCard,
  },
  mapLoadingText: {
    color: colors.textMuted,
    fontSize: fontSize.xs,
    marginTop: 4,
  },
  fallback: {
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: colors.bgCard,
    paddingHorizontal: spacing.lg,
  },
  fallbackText: {
    color: colors.textSecondary,
    fontSize: fontSize.sm,
    marginTop: spacing.sm,
    textAlign: 'center',
  },
  fallbackSub: {
    color: colors.textMuted,
    fontSize: fontSize.xs,
    marginTop: 4,
    textAlign: 'center',
  },
  fallbackCoords: {
    color: colors.textPrimary,
    fontSize: fontSize.lg,
    fontWeight: '600',
    marginTop: spacing.sm,
    fontVariant: ['tabular-nums'],
  },
  fallbackNote: {
    color: colors.warning,
    fontSize: fontSize.xs,
    marginTop: spacing.sm,
  },
  gpsBar: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: spacing.md,
    paddingVertical: 8,
    backgroundColor: colors.bg,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    height: 40,
  },
  gpsRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  gpsText: {
    color: colors.textSecondary,
    fontSize: fontSize.xs,
    fontVariant: ['tabular-nums'],
  },
  gpsMeta: {
    color: colors.textMuted,
    fontSize: 10,
    backgroundColor: colors.bgCard,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
    overflow: 'hidden',
    marginLeft: 4,
  },
});
