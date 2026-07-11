// NISCH-007 — Incident timeline detail screen.
//
// Consumes `GET /api/incidents/{id}/timeline` (Day 3 endpoint) and
// renders a chronological replay of state transitions.
//
// Reachable from `IncidentFeedRow` row tap and `IncidentMarkerSheet`
// "View Timeline" CTA.
import React, { useEffect, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, ActivityIndicator,
  TouchableOpacity,
} from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';

import { colors } from '@/theme';
import api from '@/services/api';
import { StateBadge } from '@/components/incidents/SeverityPrimitives';
import { FeedbackActionBar } from '@/components/incidents/FeedbackActionBar';
import { StreamRecordingChip } from '@/components/incidents/StreamRecordingChip';

const STATE_LABELS: Record<string, string> = {
  detected:     'Distress detected',
  validating:   'Alert sent to network',
  escalated:    'Guardian network alerted',
  acknowledged: 'Acknowledged',
  resolved:     'Marked safe',
  archived:     'Archived',
};

interface TimelineEvent {
  id: string;
  from_state: string | null;
  to_state: string;
  actor_type: string | null;
  ttfa_tag: string | null;
  sla_degraded: boolean;
  metadata: Record<string, any>;
  created_at: string;
  elapsed_ms: number;
}

interface StreamBlock {
  stream_id: string;
  state: 'ended';
  stream_type: 'audio' | 'video';
  duration_seconds: number | null;
  recording_url: string | null;
  started_at: string | null;
  ended_at: string | null;
  guardian_join_count: number;
}

interface TimelineResponse {
  incident_id: string;
  child_id: string;
  incident_type: string;
  severity: string;
  current_state: string;
  sla_degraded_at_dispatch: boolean;
  created_at: string;
  resolved_at: string | null;
  archived_at: string | null;
  timeline: TimelineEvent[];
  // NISCH-008 — most recent ENDED stream session for this incident,
  // surfaced for the 🎙 Listen chip. `null` when no stream existed
  // or the stream is still in flight (we only expose ended streams
  // since their recording_url is stable).
  stream: StreamBlock | null;
}

function formatElapsed(ms: number): string {
  if (ms === 0) return 'just now';
  if (ms < 1000)        return `${ms}ms later`;
  if (ms < 60_000)      return `${(ms / 1000).toFixed(1)}s later`;
  if (ms < 3_600_000)   return `${Math.round(ms / 60_000)}m later`;
  return `${Math.round(ms / 3_600_000)}h later`;
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString([], {
      hour: '2-digit', minute: '2-digit',
    });
  } catch {
    return '';
  }
}

export default function IncidentTimelineScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [data, setData] = useState<TimelineResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await api.get(`/incidents/${id}/timeline`);
        if (!cancelled) setData(res.data);
      } catch (e: any) {
        if (!cancelled) {
          setError(e?.response?.status === 403
            ? "You don't have access to this incident"
            : 'Could not load timeline');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [id]);

  return (
    <SafeAreaView style={styles.root} edges={['top']}>
      <View style={styles.header}>
        <TouchableOpacity
          onPress={() => router.back()}
          accessibilityLabel="Go back"
          style={styles.backBtn}
        >
          <Ionicons name="chevron-back" size={26} color={colors.textPrimary} />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Incident Timeline</Text>
        <View style={{ width: 26 }} />
      </View>

      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator color={colors.primary} />
        </View>
      ) : error ? (
        <View style={styles.center}>
          <Text style={styles.errorText}>{error}</Text>
        </View>
      ) : data ? (
        <ScrollView contentContainerStyle={styles.body}>
          <View style={styles.summary}>
            <Text style={styles.title}>
              {STATE_LABELS[data.current_state] || data.current_state}
            </Text>
            <Text style={styles.subtitle}>
              {data.incident_type} · {data.severity}
            </Text>
            {data.sla_degraded_at_dispatch && (
              <Text style={styles.slaText}>
                ⚠  System experienced delays at dispatch
              </Text>
            )}
          </View>

          <FeedbackActionBar
            incidentId={data.incident_id}
            onChange={({ state }) => {
              // Auto-resolve from community feedback flips state →
              // refetch in place so the timeline reflects the new
              // resolved row + label without leaving the screen.
              if (state !== data.current_state) {
                setData((d) => d ? { ...d, current_state: state } : d);
                api.get(`/incidents/${id}/timeline`).then((res) => {
                  setData(res.data);
                }).catch(() => {});
              }
            }}
          />

          {data.timeline.map((evt, idx) => {
            const stateLabel = STATE_LABELS[evt.to_state] || evt.to_state;
            const isFirst = idx === 0;
            return (
              <View key={evt.id} style={styles.event} testID={`timeline-event-${idx}`}>
                <View style={styles.timeCol}>
                  <Text style={styles.eventTime}>{formatTime(evt.created_at)}</Text>
                  {!isFirst && (
                    <Text style={styles.eventElapsed}>
                      {formatElapsed(evt.elapsed_ms)}
                    </Text>
                  )}
                </View>
                <View style={styles.dotCol}>
                  <View style={styles.dot} />
                  {idx < data.timeline.length - 1 && <View style={styles.line} />}
                </View>
                <View style={styles.eventBody}>
                  <StateBadge state={evt.to_state} label={stateLabel} />
                  {evt.actor_type && (
                    <Text style={styles.actor}>
                      by {evt.actor_type}
                    </Text>
                  )}
                </View>
              </View>
            );
          })}

          {/* NISCH-008 — Forensic stream replay. Only renders when an
              ENDED stream session exists for this incident. */}
          {data.stream && data.stream.state === 'ended' && (
            <StreamRecordingChip
              durationSeconds={data.stream.duration_seconds}
              recordingUrl={data.stream.recording_url}
              startedAt={data.stream.started_at}
            />
          )}
        </ScrollView>
      ) : null}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: colors.bg,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  backBtn: { padding: 4 },
  headerTitle: {
    fontSize: 17,
    fontWeight: '700',
    color: colors.textPrimary,
  },
  center: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 32,
  },
  errorText: {
    color: colors.textSecondary,
    fontSize: 14,
    textAlign: 'center',
  },
  body: { padding: 16, gap: 4 },
  summary: {
    paddingBottom: 16,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    marginBottom: 16,
    gap: 6,
  },
  title: {
    fontSize: 22,
    fontWeight: '700',
    color: colors.textPrimary,
  },
  subtitle: {
    fontSize: 13,
    color: colors.textSecondary,
    textTransform: 'capitalize',
  },
  slaText: {
    fontSize: 12,
    color: colors.warning,
    fontStyle: 'italic',
    marginTop: 4,
  },
  event: {
    flexDirection: 'row',
    minHeight: 64,
  },
  timeCol: {
    width: 64,
    alignItems: 'flex-end',
    paddingRight: 8,
    paddingTop: 2,
    gap: 2,
  },
  eventTime: {
    fontSize: 12,
    color: colors.textPrimary,
    fontWeight: '600',
  },
  eventElapsed: {
    fontSize: 10,
    color: colors.textMuted,
  },
  dotCol: {
    width: 16,
    alignItems: 'center',
    paddingTop: 6,
  },
  dot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    backgroundColor: colors.primary,
    borderWidth: 2,
    borderColor: colors.bg,
  },
  line: {
    flex: 1,
    width: 2,
    backgroundColor: colors.border,
    marginTop: 4,
  },
  eventBody: {
    flex: 1,
    paddingLeft: 12,
    paddingTop: 2,
    gap: 6,
  },
  actor: {
    fontSize: 11,
    color: colors.textMuted,
    fontStyle: 'italic',
  },
});
