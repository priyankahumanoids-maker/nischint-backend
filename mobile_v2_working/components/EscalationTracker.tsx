// EscalationTracker — Live escalation call chain visibility
// Shows which guardian is being called, call status, and resolution
import React, { useEffect, useRef } from 'react';
import { View, Text, StyleSheet, Animated, Vibration } from 'react-native';
import { useEscalationStore } from '@/stores/escalationStore';

// Vibration patterns mimic haptic feedback (no native module required)
const HAPTIC_IMPACT_MEDIUM = [0, 40];
const HAPTIC_SUCCESS = [0, 40, 60, 40];
const HAPTIC_WARNING = [0, 80, 100, 80];
const HAPTIC_ERROR = [0, 120, 80, 120, 80, 120];

function safeVibrate(pattern: number[]) {
  try { Vibration.vibrate(pattern); } catch {}
}

var STATUS_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  started: { label: 'ESCALATION STARTED', color: '#FF6B35', bg: 'rgba(255,107,53,0.15)' },
  calling: { label: 'CALLING', color: '#FFB800', bg: 'rgba(255,184,0,0.15)' },
  no_answer: { label: 'NO ANSWER', color: '#FF4444', bg: 'rgba(255,68,68,0.15)' },
  voicemail: { label: 'VOICEMAIL', color: '#FF6B35', bg: 'rgba(255,107,53,0.15)' },
  answered: { label: 'ANSWERED', color: '#00E676', bg: 'rgba(0,230,118,0.15)' },
  failed: { label: 'CALL FAILED', color: '#FF4444', bg: 'rgba(255,68,68,0.15)' },
  sms_blast: { label: 'SMS BLAST SENT', color: '#FF6B35', bg: 'rgba(255,107,53,0.15)' },
  exhausted: { label: 'ALL CONTACTS EXHAUSTED', color: '#FF4444', bg: 'rgba(255,68,68,0.15)' },
};

export default function EscalationTracker() {
  var escalation = useEscalationStore(function (s) { return s.escalation; });
  var pulseAnim = useRef(new Animated.Value(1)).current;
  var prevStatusRef = useRef<string | null>(null);

  // Pulse animation for active states
  useEffect(function () {
    if (!escalation) return;

    var isActive = escalation.status === 'calling' || escalation.status === 'started';
    if (isActive) {
      var loop = Animated.loop(
        Animated.sequence([
          Animated.timing(pulseAnim, { toValue: 0.6, duration: 800, useNativeDriver: true }),
          Animated.timing(pulseAnim, { toValue: 1, duration: 800, useNativeDriver: true }),
        ])
      );
      loop.start();
      return function () { loop.stop(); };
    } else {
      pulseAnim.setValue(1);
    }
  }, [escalation?.status]);

  // Haptic feedback on status changes
  useEffect(function () {
    if (!escalation) return;
    if (prevStatusRef.current === escalation.status) return;
    prevStatusRef.current = escalation.status;

    if (escalation.status === 'calling') {
      safeVibrate(HAPTIC_IMPACT_MEDIUM);
    } else if (escalation.status === 'answered') {
      safeVibrate(HAPTIC_SUCCESS);
    } else if (escalation.status === 'no_answer' || escalation.status === 'failed') {
      safeVibrate(HAPTIC_WARNING);
    } else if (escalation.status === 'exhausted') {
      safeVibrate(HAPTIC_ERROR);
    }
  }, [escalation?.status, escalation?.sequence]);

  if (!escalation) return null;

  var config = STATUS_CONFIG[escalation.status] || STATUS_CONFIG.started;
  var isResolved = escalation.status === 'answered';
  var isCalling = escalation.status === 'calling';

  // Progress bar
  var progress = escalation.total_guardians > 0
    ? escalation.sequence / escalation.total_guardians
    : 0;

  return (
    <Animated.View style={[styles.container, { backgroundColor: config.bg, opacity: isCalling ? pulseAnim : 1 }]}>
      {/* Header */}
      <View style={styles.header}>
        <Text style={[styles.badge, { backgroundColor: config.color }]}>
          EMERGENCY ESCALATION
        </Text>
        <Text style={[styles.statusText, { color: config.color }]}>
          {config.label}
        </Text>
      </View>

      {/* Child info */}
      <Text style={styles.childName}>
        {escalation.child_name}
      </Text>

      {/* Current guardian being called */}
      {escalation.current_guardian && (
        <View style={styles.guardianRow}>
          <Text style={styles.guardianLabel}>
            {isCalling ? 'Calling: ' : escalation.status === 'answered' ? 'Answered by: ' : 'Tried: '}
          </Text>
          <Text style={[styles.guardianName, { color: config.color }]}>
            {escalation.current_guardian.name}
          </Text>
          {isCalling && (
            <Text style={styles.callingDots}>...</Text>
          )}
        </View>
      )}

      {/* Resolved by */}
      {isResolved && escalation.resolved_by && (
        <View style={styles.resolvedRow}>
          <Text style={styles.resolvedLabel}>Resolved by: </Text>
          <Text style={styles.resolvedName}>{escalation.resolved_by}</Text>
        </View>
      )}

      {/* Progress bar */}
      {escalation.total_guardians > 0 && (
        <View style={styles.progressContainer}>
          <View style={styles.progressBar}>
            <View
              style={[
                styles.progressFill,
                {
                  width: `${Math.min(progress * 100, 100)}%`,
                  backgroundColor: config.color,
                },
              ]}
            />
          </View>
          <Text style={styles.progressText}>
            Step {escalation.sequence} of {escalation.total_guardians}
          </Text>
        </View>
      )}

      {/* SMS blast indicator */}
      {escalation.status === 'sms_blast' && (
        <Text style={styles.smsBlast}>
          Sending SMS to all contacts...
        </Text>
      )}

      {/* Exhausted warning */}
      {escalation.status === 'exhausted' && (
        <Text style={styles.exhaustedText}>
          No guardian responded. SMS alerts sent. Contact emergency services.
        </Text>
      )}

      {/* Timestamp */}
      <Text style={styles.timestamp}>
        {new Date(escalation.timestamp).toLocaleTimeString()}
      </Text>
    </Animated.View>
  );
}

var styles = StyleSheet.create({
  container: {
    margin: 12,
    padding: 14,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: 'rgba(255,68,68,0.3)',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 8,
  },
  badge: {
    color: '#000',
    fontSize: 9,
    fontWeight: '800',
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
    overflow: 'hidden',
    letterSpacing: 0.5,
  },
  statusText: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 0.5,
  },
  childName: {
    color: '#FFF',
    fontSize: 16,
    fontWeight: '700',
    marginBottom: 6,
  },
  guardianRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 4,
  },
  guardianLabel: {
    color: 'rgba(255,255,255,0.6)',
    fontSize: 13,
  },
  guardianName: {
    fontSize: 14,
    fontWeight: '600',
  },
  callingDots: {
    color: '#FFB800',
    fontSize: 18,
    fontWeight: '700',
    marginLeft: 2,
  },
  resolvedRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 4,
    marginBottom: 4,
  },
  resolvedLabel: {
    color: 'rgba(255,255,255,0.5)',
    fontSize: 12,
  },
  resolvedName: {
    color: '#00E676',
    fontSize: 14,
    fontWeight: '700',
  },
  progressContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 8,
    gap: 8,
  },
  progressBar: {
    flex: 1,
    height: 4,
    backgroundColor: 'rgba(255,255,255,0.1)',
    borderRadius: 2,
    overflow: 'hidden',
  },
  progressFill: {
    height: '100%',
    borderRadius: 2,
  },
  progressText: {
    color: 'rgba(255,255,255,0.5)',
    fontSize: 10,
    fontWeight: '600',
  },
  smsBlast: {
    color: '#FF6B35',
    fontSize: 12,
    fontWeight: '600',
    marginTop: 6,
  },
  exhaustedText: {
    color: '#FF4444',
    fontSize: 12,
    fontWeight: '600',
    marginTop: 6,
  },
  timestamp: {
    color: 'rgba(255,255,255,0.3)',
    fontSize: 9,
    textAlign: 'right',
    marginTop: 6,
  },
});
