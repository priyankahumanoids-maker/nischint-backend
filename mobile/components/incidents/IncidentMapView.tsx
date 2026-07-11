// NISCH-007 Part B — Map view with severity-colored markers and
// optional saved-zone overlay rings.
//
// Native maps only — there's a `react-native-maps` web shim but we keep
// this component native-only because the brief targets the mobile app.
//
// Marker coordinate rule (privacy-locked):
//   1. Prefer API-provided `marker_lat`/`marker_lng` — already rounded
//      to 3 decimal places (~111m) by the backend (`round_marker_coord`).
//   2. Fall back to a stable per-id bearing ray-cast from the guardian's
//      centre when the API omits the marker (child has no location fix).
//   3. Use `!= null` (not falsy) so a valid `0.000` coordinate doesn't
//      incorrectly trigger the bearing fallback.
import React, { useRef } from 'react';
import { View, TouchableOpacity, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import MapView, { Marker, Circle, PROVIDER_GOOGLE } from 'react-native-maps';
import { colors } from '@/theme';
import { PulsingMarker } from './PulsingMarker';
import type { FeedIncident } from './IncidentFeedRow';

// MapIncident is now just FeedIncident — the map computes its own
// coordinate from the privacy-rounded API fields (or the bearing
// fallback) at render time. No upstream coercion required.
export type MapIncident = FeedIncident;

export interface SavedZone {
  id: string;
  lat: number;
  lng: number;
  radius_m: number;
  zone_type: string;
}

interface Props {
  centre:       { lat: number; lng: number };
  incidents:    MapIncident[];
  savedZones:   SavedZone[];
  onMarkerPress: (id: string) => void;
  onRecentre:    () => void;
}

// Stable bearing derived from the incident id — same incident always
// places at the same compass direction so successive renders don't
// jump the marker around. Used ONLY when the API has no marker_lat/lng
// (child has no location fix yet).
function bearingFromId(id: string): number {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) | 0;
  return ((h % 360) + 360) % 360;
}

function deriveMarkerCoord(
  id: string,
  guardianLat: number,
  guardianLng: number,
  distanceM: number,
): { lat: number; lng: number } {
  const bearingRad = (bearingFromId(id) * Math.PI) / 180;
  // 1 deg lat ≈ 111_320 m; 1 deg lng ≈ 111_320 * cos(lat)
  const dLat = (distanceM * Math.cos(bearingRad)) / 111_320;
  const dLng = (distanceM * Math.sin(bearingRad)) /
               (111_320 * Math.cos((guardianLat * Math.PI) / 180));
  return { lat: guardianLat + dLat, lng: guardianLng + dLng };
}

export function IncidentMapView({
  centre, incidents, savedZones, onMarkerPress, onRecentre,
}: Props) {
  const mapRef = useRef<MapView>(null);

  const handleRecentre = () => {
    mapRef.current?.animateToRegion(
      { latitude: centre.lat, longitude: centre.lng,
        latitudeDelta: 0.01, longitudeDelta: 0.01 },
      400
    );
    onRecentre();
  };

  return (
    <View style={styles.container} testID="incident-map-view">
      <MapView
        ref={mapRef}
        provider={PROVIDER_GOOGLE}
        style={StyleSheet.absoluteFill}
        initialRegion={{
          latitude:  centre.lat,
          longitude: centre.lng,
          latitudeDelta:  0.01,
          longitudeDelta: 0.01,
        }}
        showsUserLocation
        showsMyLocationButton={false}
      >
        {/* Subtle saved-zone overlays */}
        {savedZones.map((z) => (
          <Circle
            key={z.id}
            center={{ latitude: z.lat, longitude: z.lng }}
            radius={z.radius_m}
            fillColor="rgba(14, 165, 233, 0.06)"   // colors.primary @ 6%
            strokeColor="rgba(14, 165, 233, 0.5)"
            strokeWidth={1}
          />
        ))}

        {incidents.map((inc) => {
          // Privacy-locked coordinate selection. `!= null` (not `!`)
          // so a valid `0.000` coord won't fall through to bearing.
          const coordinate = inc.marker_lat != null && inc.marker_lng != null
            ? { latitude: inc.marker_lat, longitude: inc.marker_lng }
            : (() => {
                const f = deriveMarkerCoord(
                  inc.id, centre.lat, centre.lng, inc.distance_metres,
                );
                return { latitude: f.lat, longitude: f.lng };
              })();

          return (
            <Marker
              key={inc.id}
              testID={`map-marker-${inc.id}`}
              coordinate={coordinate}
              onPress={() => onMarkerPress(inc.id)}
              anchor={{ x: 0.5, y: 0.5 }}
              tracksViewChanges={false /* perf — re-render only on data */}
            >
              <PulsingMarker severity={inc.severity} state={inc.state} />
            </Marker>
          );
        })}
      </MapView>

      <TouchableOpacity
        testID="recentre-btn"
        style={styles.recentre}
        activeOpacity={0.85}
        onPress={handleRecentre}
        accessibilityLabel="Recentre map on my location"
      >
        <Ionicons name="locate" size={20} color={colors.white} />
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  recentre: {
    position: 'absolute',
    bottom: 24,
    right: 16,
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: '#000',
    shadowOpacity: 0.3,
    shadowRadius: 6,
    shadowOffset: { width: 0, height: 2 },
    elevation: 4,
  },
});
