// NISCH-009 — Guardian feedback action bar.
//
// Three primary verdicts:
//   * Mark Safe       — green, friendly
//   * Confirm Risk    — red, urgent
//   * Report Anomaly  — amber, ambiguous, opens optional 200-char note
//
// Mounts on both the timeline screen and the marker bottom sheet. The
// component owns its own fetch + submit lifecycle so the parent only
// has to pass an `incidentId`. Caller may also pass `onChange` to be
// notified when the verdict mutates (e.g. parent wants to refetch the
// incident state because auto-resolve fired).
import React, { useCallback, useEffect, useState } from 'react';
import {
  View, Text, TouchableOpacity, StyleSheet, ActivityIndicator,
  Modal, TextInput, Pressable, Alert,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { colors } from '@/theme';
import api from '@/services/api';

export type Verdict = 'mark_safe' | 'confirm_risk' | 'report_anomaly';

interface OwnVerdict {
  verdict: Verdict;
  note: string | null;
  updated_at: string;
}

interface FeedbackResponse {
  incident_id: string;
  current_state: string;
  counts: Record<Verdict, number>;
  total: number;
  own_verdict: OwnVerdict | null;
}

interface SubmitResponse {
  feedback: { verdict: Verdict; is_update: boolean };
  aggregate: {
    counts: Record<Verdict, number>;
    classification: 'risk' | 'safe' | null;
    confidence_before: number;
    confidence_after: number;
    auto_resolved: boolean;
    current_state: string;
  };
}

interface Props {
  incidentId: string;
  onChange?: (next: { state: string; auto_resolved: boolean }) => void;
  // When `compact` is true, the layout shrinks to fit the marker sheet.
  compact?: boolean;
}

const NOTE_MAX = 200;

export function FeedbackActionBar({ incidentId, onChange, compact }: Props) {
  const [loading,    setLoading]    = useState(true);
  const [submitting, setSubmitting] = useState<Verdict | null>(null);
  const [data,       setData]       = useState<FeedbackResponse | null>(null);
  const [noteOpen,   setNoteOpen]   = useState(false);
  const [noteText,   setNoteText]   = useState('');

  // ── Initial fetch ────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await api.get(`/incidents/${incidentId}/feedback`);
        if (!cancelled) setData(res.data);
      } catch (e: any) {
        // 403 is a real possibility — child or unrelated user. Hide
        // the bar entirely in that case rather than rendering errors.
        if (!cancelled && e?.response?.status !== 403) {
          if (__DEV__) console.warn('[FEEDBACK] fetch failed:', e?.message);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [incidentId]);

  const submit = useCallback(async (verdict: Verdict, note?: string) => {
    setSubmitting(verdict);
    try {
      const res = await api.post<SubmitResponse>(
        `/incidents/${incidentId}/feedback`,
        { verdict, note: note || null },
      );
      const agg = res.data.aggregate;
      setData((prev) => prev ? {
        ...prev,
        current_state: agg.current_state,
        counts: agg.counts,
        total: Object.values(agg.counts).reduce((a, b) => a + b, 0),
        own_verdict: {
          verdict,
          note: note || null,
          updated_at: new Date().toISOString(),
        },
      } : prev);
      onChange?.({
        state: agg.current_state,
        auto_resolved: agg.auto_resolved,
      });
      if (agg.auto_resolved) {
        Alert.alert(
          'Marked safe',
          'Your network agreed this is safe. The incident has been resolved.',
        );
      }
    } catch (e: any) {
      const status = e?.response?.status;
      if (status === 403) {
        Alert.alert(
          'Not authorized',
          'Only guardians in this child\u2019s network can submit feedback.',
        );
      } else if (status === 409) {
        Alert.alert('Closed', 'This incident is archived; feedback is closed.');
      } else {
        Alert.alert('Could not submit', 'Please try again in a moment.');
      }
    } finally {
      setSubmitting(null);
    }
  }, [incidentId, onChange]);

  const onAnomalyPress = useCallback(() => {
    setNoteText(data?.own_verdict?.verdict === 'report_anomaly'
      ? (data.own_verdict.note || '')
      : '');
    setNoteOpen(true);
  }, [data]);

  const onAnomalyConfirm = useCallback(() => {
    setNoteOpen(false);
    submit('report_anomaly', noteText.trim() || undefined);
  }, [noteText, submit]);

  if (loading) {
    return (
      <View style={[styles.bar, compact && styles.barCompact]}>
        <ActivityIndicator color={colors.primary} size="small" />
      </View>
    );
  }
  if (!data) {
    // 403 path — guardian isn't in the closed network. Show nothing.
    return null;
  }

  // Disable everything once the incident is archived (server enforces
  // 409 too — this is just to avoid the UX flicker).
  const closed = data.current_state === 'archived';
  const own = data.own_verdict?.verdict;

  return (
    <View
      style={[styles.container, compact && styles.containerCompact]}
      testID="feedback-action-bar"
    >
      {!compact && (
        <Text style={styles.heading}>How does this look?</Text>
      )}

      <View style={styles.bar}>
        <ActionBtn
          label="Mark Safe"
          icon="shield-checkmark"
          tint={colors.success || '#10b981'}
          active={own === 'mark_safe'}
          loading={submitting === 'mark_safe'}
          disabled={closed || submitting !== null}
          count={data.counts.mark_safe}
          onPress={() => submit('mark_safe')}
          testID="feedback-mark-safe-btn"
        />
        <ActionBtn
          label="Confirm Risk"
          icon="alert-circle"
          tint={colors.error || '#ef4444'}
          active={own === 'confirm_risk'}
          loading={submitting === 'confirm_risk'}
          disabled={closed || submitting !== null}
          count={data.counts.confirm_risk}
          onPress={() => submit('confirm_risk')}
          testID="feedback-confirm-risk-btn"
        />
        <ActionBtn
          label="Report Anomaly"
          icon="warning"
          tint={colors.warning || '#f59e0b'}
          active={own === 'report_anomaly'}
          loading={submitting === 'report_anomaly'}
          disabled={closed || submitting !== null}
          count={data.counts.report_anomaly}
          onPress={onAnomalyPress}
          testID="feedback-report-anomaly-btn"
        />
      </View>

      {own && !compact && (
        <Text style={styles.ownVerdictText} testID="feedback-own-verdict">
          You voted: {labelFor(own)} — tap again to change.
        </Text>
      )}

      {/* Anomaly note dialog */}
      <Modal
        visible={noteOpen}
        transparent
        animationType="fade"
        onRequestClose={() => setNoteOpen(false)}
      >
        <Pressable style={styles.backdrop} onPress={() => setNoteOpen(false)} />
        <View style={styles.noteCard} testID="feedback-anomaly-dialog">
          <Text style={styles.noteTitle}>Report Anomaly</Text>
          <Text style={styles.noteSub}>
            Optional — describe what felt off (max {NOTE_MAX} chars).
          </Text>
          <TextInput
            value={noteText}
            onChangeText={(t) => setNoteText(t.slice(0, NOTE_MAX))}
            multiline
            placeholder="Heard background noise, child sounded unusual…"
            placeholderTextColor={colors.textMuted}
            style={styles.noteInput}
            testID="feedback-anomaly-input"
          />
          <Text style={styles.noteCount}>
            {noteText.length}/{NOTE_MAX}
          </Text>
          <View style={styles.noteActions}>
            <TouchableOpacity
              onPress={() => setNoteOpen(false)}
              style={[styles.noteBtn, styles.noteBtnGhost]}
              testID="feedback-anomaly-cancel"
            >
              <Text style={styles.noteBtnGhostText}>Cancel</Text>
            </TouchableOpacity>
            <TouchableOpacity
              onPress={onAnomalyConfirm}
              style={[styles.noteBtn, styles.noteBtnPrimary]}
              testID="feedback-anomaly-submit"
            >
              <Text style={styles.noteBtnPrimaryText}>Submit Report</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>
    </View>
  );
}

interface BtnProps {
  label: string;
  icon: keyof typeof Ionicons.glyphMap;
  tint: string;
  active: boolean;
  loading: boolean;
  disabled: boolean;
  count: number;
  onPress: () => void;
  testID: string;
}

function ActionBtn({
  label, icon, tint, active, loading, disabled, count, onPress, testID,
}: BtnProps) {
  return (
    <TouchableOpacity
      testID={testID}
      onPress={onPress}
      disabled={disabled}
      activeOpacity={0.85}
      style={[
        styles.btn,
        active && { borderColor: tint, backgroundColor: hexAlpha(tint, 0.10) },
        disabled && styles.btnDisabled,
      ]}
    >
      {loading ? (
        <ActivityIndicator color={tint} size="small" />
      ) : (
        <Ionicons name={icon} size={20} color={tint} />
      )}
      <Text style={[styles.btnLabel, active && { color: tint }]} numberOfLines={1}>
        {label}
      </Text>
      {count > 0 && (
        <View style={[styles.countPill, { backgroundColor: hexAlpha(tint, 0.18) }]}>
          <Text style={[styles.countText, { color: tint }]}>{count}</Text>
        </View>
      )}
    </TouchableOpacity>
  );
}

function labelFor(v: Verdict): string {
  return v === 'mark_safe' ? 'Mark Safe'
       : v === 'confirm_risk' ? 'Confirm Risk'
       : 'Report Anomaly';
}

function hexAlpha(hex: string, alpha: number): string {
  // Tolerate non-hex inputs (CSS named colours leak through occasionally).
  if (!hex.startsWith('#') || (hex.length !== 7 && hex.length !== 4)) {
    return hex;
  }
  const h = hex.length === 4
    ? `#${hex[1]}${hex[1]}${hex[2]}${hex[2]}${hex[3]}${hex[3]}`
    : hex;
  const r = parseInt(h.slice(1, 3), 16);
  const g = parseInt(h.slice(3, 5), 16);
  const b = parseInt(h.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

const styles = StyleSheet.create({
  container: {
    paddingHorizontal: 16,
    paddingTop: 12,
    paddingBottom: 8,
    gap: 8,
  },
  containerCompact: {
    paddingHorizontal: 0,
    paddingTop: 4,
  },
  heading: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.textSecondary,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  bar: {
    flexDirection: 'row',
    gap: 8,
  },
  barCompact: {
    paddingVertical: 4,
  },
  btn: {
    flex: 1,
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 4,
    paddingVertical: 12,
    paddingHorizontal: 6,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    backgroundColor: colors.bgCard,
    minHeight: 64,
  },
  btnDisabled: {
    opacity: 0.5,
  },
  btnLabel: {
    fontSize: 12,
    fontWeight: '600',
    color: colors.textPrimary,
    textAlign: 'center',
  },
  countPill: {
    paddingHorizontal: 6,
    paddingVertical: 1,
    borderRadius: 10,
    minWidth: 20,
    alignItems: 'center',
  },
  countText: {
    fontSize: 11,
    fontWeight: '700',
  },
  ownVerdictText: {
    fontSize: 12,
    color: colors.textMuted,
    fontStyle: 'italic',
  },
  // Anomaly dialog
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.5)',
  },
  noteCard: {
    position: 'absolute',
    left: 20,
    right: 20,
    top: '25%',
    backgroundColor: colors.bgCard,
    borderRadius: 16,
    padding: 20,
    gap: 10,
  },
  noteTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.textPrimary,
  },
  noteSub: {
    fontSize: 13,
    color: colors.textSecondary,
  },
  noteInput: {
    minHeight: 90,
    maxHeight: 180,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 8,
    padding: 10,
    color: colors.textPrimary,
    backgroundColor: colors.bg,
    textAlignVertical: 'top',
  },
  noteCount: {
    fontSize: 11,
    color: colors.textMuted,
    textAlign: 'right',
  },
  noteActions: {
    flexDirection: 'row',
    gap: 10,
    marginTop: 4,
  },
  noteBtn: {
    flex: 1,
    paddingVertical: 12,
    borderRadius: 10,
    alignItems: 'center',
  },
  noteBtnGhost: {
    backgroundColor: 'transparent',
    borderWidth: 1,
    borderColor: colors.border,
  },
  noteBtnGhostText: {
    color: colors.textPrimary,
    fontWeight: '600',
  },
  noteBtnPrimary: {
    backgroundColor: colors.primary,
  },
  noteBtnPrimaryText: {
    color: colors.white,
    fontWeight: '700',
  },
});
