// NISCH-007 Part B — Bottom sheet rendered when a marker is tapped.
//
// Lightweight Modal-based sheet. Uses RN's built-in Modal with a slide
// animation; no external bottom-sheet library needed.
import React from 'react';
import {
  Modal, View, Text, TouchableOpacity, StyleSheet, Pressable,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { colors } from '@/theme';
import { StateBadge } from './SeverityPrimitives';
import { FeedbackActionBar } from './FeedbackActionBar';
import type { FeedIncident } from './IncidentFeedRow';

interface Props {
  incident: FeedIncident | null;
  // Optional — when provided, the sheet renders a "🔴 LIVE — tap to
  // listen" affordance that routes to the listener screen. Pass the
  // current `stream_id` for this incident from the parent's SSE
  // handler. Null → no live stream affordance.
  liveStreamId?: string | null;
  onClose: () => void;
  onViewTimeline: (id: string) => void;
}

export function IncidentMarkerSheet({
  incident, liveStreamId, onClose, onViewTimeline,
}: Props) {
  if (!incident) return null;
  return (
    <Modal
      visible={incident !== null}
      transparent
      animationType="slide"
      onRequestClose={onClose}
    >
      <Pressable style={styles.backdrop} onPress={onClose} />
      <View style={styles.sheet} testID="incident-marker-sheet">
        <View style={styles.handle} />

        <Text style={styles.title} numberOfLines={2}>
          {incident.state_label}
        </Text>

        <View style={styles.metaRow}>
          <Meta label="Distance" value={`${incident.distance_metres}m away`} />
          {incident.zone_match && (
            <Meta label="Zone" value={cap(incident.zone_match)} />
          )}
          <Meta label="When" value={incident.elapsed_since_created} />
        </View>

        <View style={styles.badgeRow}>
          <StateBadge state={incident.state} label={incident.state_label} />
        </View>

        {incident.sla_degraded_at_dispatch && (
          <Text style={styles.slaText} testID="sla-degraded-text">
            ⚠  System experienced delays at dispatch
          </Text>
        )}

        <FeedbackActionBar
          incidentId={incident.id}
          compact
        />

        {liveStreamId && (
          <TouchableOpacity
            testID="live-stream-listen-btn"
            accessibilityLabel="Listen to the live audio stream"
            style={styles.liveCta}
            activeOpacity={0.85}
            onPress={() => {
              router.push({
                pathname: '/stream-listener',
                params: { stream_id: liveStreamId },
              });
              onClose();
            }}
          >
            <View style={styles.liveDot} />
            <Text style={styles.liveCtaText}>LIVE — tap to listen</Text>
            <Ionicons name="headset" size={16} color={colors.white} />
          </TouchableOpacity>
        )}

        <TouchableOpacity
          testID="view-timeline-btn"
          style={styles.cta}
          activeOpacity={0.85}
          onPress={() => onViewTimeline(incident.id)}
        >
          <Text style={styles.ctaText}>View Timeline</Text>
          <Ionicons name="arrow-forward" size={16} color={colors.white} />
        </TouchableOpacity>
      </View>
    </Modal>
  );
}

function cap(s: string) {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.metaCol}>
      <Text style={styles.metaLabel}>{label}</Text>
      <Text style={styles.metaValue}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.4)',
  },
  sheet: {
    position: 'absolute',
    left: 0, right: 0, bottom: 0,
    backgroundColor: colors.bgCard,
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    paddingTop: 8,
    paddingHorizontal: 20,
    paddingBottom: 32,
    gap: 12,
  },
  handle: {
    alignSelf: 'center',
    width: 40, height: 4,
    backgroundColor: colors.border,
    borderRadius: 2,
    marginBottom: 8,
  },
  title: {
    fontSize: 20,
    fontWeight: '700',
    color: colors.textPrimary,
  },
  metaRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 16,
    marginTop: 4,
  },
  metaCol: { gap: 2 },
  metaLabel: {
    fontSize: 11,
    color: colors.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    fontWeight: '600',
  },
  metaValue: {
    fontSize: 15,
    color: colors.textPrimary,
    fontWeight: '600',
  },
  badgeRow: { marginTop: 4 },
  slaText: {
    fontSize: 12,
    color: colors.warning,
    fontStyle: 'italic',
  },
  cta: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    backgroundColor: colors.primary,
    paddingVertical: 14,
    borderRadius: 12,
    marginTop: 8,
  },
  liveCta: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 10,
    backgroundColor: colors.error,
    paddingVertical: 14,
    borderRadius: 12,
    marginTop: 4,
  },
  liveCtaText: {
    color: colors.white,
    fontSize: 14,
    fontWeight: '800',
    letterSpacing: 0.6,
  },
  liveDot: {
    width: 10, height: 10, borderRadius: 5,
    backgroundColor: colors.white,
  },
  ctaText: {
    color: colors.white,
    fontSize: 15,
    fontWeight: '700',
  },
});
