// NISCH-007 Part B — Single feed row.
//
// Pure presentation — the parent owns the data and the navigation
// handler. Stable shape means FlatList can recycle it efficiently.
import React from 'react';
import { TouchableOpacity, View, Text, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { colors } from '@/theme';
import { SeverityDot, StateBadge } from './SeverityPrimitives';

export interface FeedIncident {
  id: string;
  state: string;
  state_label: string;
  severity: string;
  distance_metres: number;
  zone_match: string | null;
  elapsed_since_created: string;
  sla_degraded_at_dispatch: boolean;
  // Privacy-rounded marker coordinates from the /nearby endpoint.
  // Rounded server-side to 3 decimal places (~111m) — never precise
  // child location. `null` when the child has no location fix; the
  // map view falls back to per-id bearing ray-cast in that case.
  marker_lat: number | null;
  marker_lng: number | null;
  // SSE flash window — set by the parent for ~200ms when a new
  // incident arrives. Never displayed; controls the row tint.
  _flash?: boolean;
}

interface Props {
  incident: FeedIncident;
  onPress: (id: string) => void;
}

export function IncidentFeedRow({ incident, onPress }: Props) {
  const subDistance = `${incident.distance_metres}m away`;
  const subLine = incident.zone_match
    ? `${subDistance} · ${capitalise(incident.zone_match)} zone`
    : subDistance;

  return (
    <TouchableOpacity
      testID={`incident-row-${incident.id}`}
      accessibilityRole="button"
      activeOpacity={0.7}
      onPress={() => onPress(incident.id)}
      style={[styles.row, incident._flash && styles.rowFlash]}
    >
      <View style={styles.dotCol}>
        <SeverityDot severity={incident.severity} size={10} />
      </View>

      <View style={styles.body}>
        <View style={styles.titleRow}>
          <Text style={styles.title} numberOfLines={1}>
            {incident.state_label}
          </Text>
          <View style={styles.timeBlock}>
            {incident.sla_degraded_at_dispatch && (
              <View
                style={styles.slaDot}
                accessibilityLabel="Alert dispatched while system was experiencing delays"
              />
            )}
            <Text style={styles.timestamp}>{incident.elapsed_since_created}</Text>
          </View>
        </View>

        <Text style={styles.subtitle} numberOfLines={1}>
          {subLine}
        </Text>

        <View style={styles.badgeRow}>
          <StateBadge state={incident.state} label={incident.state_label} />
        </View>
      </View>

      <Ionicons name="chevron-forward" size={18} color={colors.textMuted} />
    </TouchableOpacity>
  );
}

function capitalise(s: string) {
  if (!s) return s;
  return s.charAt(0).toUpperCase() + s.slice(1);
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    minHeight: 72,                 // brief: 48px+ tap target — we go to 72
    paddingHorizontal: 16,
    paddingVertical: 12,
    backgroundColor: colors.bgCard,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    gap: 12,
  },
  rowFlash: {
    backgroundColor: '#0F2530',    // teal-tinted dark — fades back to bgCard
  },
  dotCol: {
    width: 10,
    alignItems: 'center',
    justifyContent: 'center',
    paddingTop: 6,
    alignSelf: 'flex-start',
  },
  body: {
    flex: 1,
    gap: 4,
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 8,
  },
  title: {
    flex: 1,
    fontSize: 16,                  // brief minimum
    fontWeight: '600',
    color: colors.textPrimary,
  },
  subtitle: {
    fontSize: 13,
    color: colors.textSecondary,
  },
  badgeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 2,
  },
  timeBlock: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  timestamp: {
    fontSize: 12,
    color: colors.textMuted,
  },
  slaDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: colors.warning,
  },
});
