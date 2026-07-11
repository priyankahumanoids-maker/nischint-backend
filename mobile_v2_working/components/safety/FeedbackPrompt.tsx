/**
 * SB-01 Day 3 — Guardian feedback prompt.
 *
 * Surface contract:
 *   • Show 30 s after the guardian acknowledges a SafetyEvent alert.
 *   • Bottom sheet: "Was this alert accurate?"
 *   • Three buttons → POST /api/safety-events/:id/feedback.
 *   • Auto-dismiss after 10 s of no-tap (silence ≠ a verdict).
 *   • Never show twice for the same event_id (AsyncStorage dedupe).
 *
 * The dedupe key (`sb01_feedback_<eventId>`) is set BEFORE the 30 s
 * delay fires, so even a fast subsequent alert for the same event
 * can't queue a second prompt.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Animated, Easing, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { Ionicons } from '@expo/vector-icons';

import { colors, fontSize, radius, spacing } from '@/theme';
import api from '@/services/api';

const STORAGE_PREFIX = 'sb01_feedback_';
const SHOW_DELAY_MS = 30_000;       // 30 s after ack
const AUTO_DISMISS_MS = 10_000;     // 10 s of no tap → fade out

type Verdict = 'confirmed' | 'false_positive' | 'unsure';

export interface FeedbackPromptHandle {
  scheduleFor: (eventId: string) => void;
  /** Cancel any pending prompt (e.g. on screen unmount or new alert). */
  cancel: () => void;
}

interface Props {
  /** Optional callback after a verdict is submitted. */
  onSubmit?: (eventId: string, verdict: Verdict) => void;
}

export const FeedbackPrompt = React.forwardRef<FeedbackPromptHandle, Props>(
  function FeedbackPrompt({ onSubmit }, ref) {
    const [visibleEventId, setVisibleEventId] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const fadeIn = useRef(new Animated.Value(0)).current;
    const showTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
    const dismissTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

    const cancel = useCallback(() => {
      if (showTimer.current) {
        clearTimeout(showTimer.current);
        showTimer.current = null;
      }
      if (dismissTimer.current) {
        clearTimeout(dismissTimer.current);
        dismissTimer.current = null;
      }
    }, []);

    const hide = useCallback(() => {
      Animated.timing(fadeIn, {
        toValue: 0,
        duration: 200,
        useNativeDriver: true,
      }).start(() => {
        setVisibleEventId(null);
      });
    }, [fadeIn]);

    const show = useCallback(
      (eventId: string) => {
        setVisibleEventId(eventId);
        Animated.timing(fadeIn, {
          toValue: 1,
          duration: 220,
          easing: Easing.out(Easing.cubic),
          useNativeDriver: true,
        }).start();
        // Auto-dismiss countdown.
        if (dismissTimer.current) clearTimeout(dismissTimer.current);
        dismissTimer.current = setTimeout(hide, AUTO_DISMISS_MS);
      },
      [fadeIn, hide],
    );

    const scheduleFor = useCallback(
      async (eventId: string) => {
        if (!eventId) return;
        // Idempotency: once dedupe key is written, no prompt EVER fires
        // for this event again. Read+write happens before the delay so
        // dup acks within the 30 s window can't double-queue.
        const key = STORAGE_PREFIX + eventId;
        const already = await AsyncStorage.getItem(key);
        if (already) return;
        await AsyncStorage.setItem(key, String(Date.now()));

        cancel();
        showTimer.current = setTimeout(() => show(eventId), SHOW_DELAY_MS);
      },
      [cancel, show],
    );

    React.useImperativeHandle(ref, () => ({ scheduleFor, cancel }), [scheduleFor, cancel]);

    useEffect(() => {
      return () => cancel();
    }, [cancel]);

    const submit = useCallback(
      async (verdict: Verdict) => {
        if (!visibleEventId || busy) return;
        setBusy(true);
        try {
          await api.post(`/safety-events/${visibleEventId}/feedback`, { verdict });
          onSubmit?.(visibleEventId, verdict);
        } catch (e) {
          // Failure mode is silent — guardian shouldn't see API errors
          // in a transient bottom sheet. Log only.
          console.warn('[SB-01 feedback] submit failed:', e);
        } finally {
          setBusy(false);
          hide();
        }
      },
      [visibleEventId, busy, hide, onSubmit],
    );

    if (!visibleEventId) return null;

    return (
      <Animated.View
        style={[styles.sheet, { opacity: fadeIn, transform: [{ translateY: fadeIn.interpolate({ inputRange: [0, 1], outputRange: [40, 0] }) }] }]}
        testID="sb01-feedback-sheet"
      >
        <View style={styles.handle} />
        <Text style={styles.title} testID="sb01-feedback-title">
          Was this alert accurate?
        </Text>
        <Text style={styles.subtitle}>
          Your answer trains the safety brain. Takes 1 second.
        </Text>
        <View style={styles.row}>
          <Btn
            label="Yes, real"
            icon="checkmark-circle"
            tint={colors.success}
            onPress={() => submit('confirmed')}
            disabled={busy}
            testID="sb01-feedback-confirmed"
          />
          <Btn
            label="False alarm"
            icon="close-circle"
            tint={colors.critical}
            onPress={() => submit('false_positive')}
            disabled={busy}
            testID="sb01-feedback-false-positive"
          />
          <Btn
            label="Not sure"
            icon="help-circle"
            tint={colors.textMuted}
            onPress={() => submit('unsure')}
            disabled={busy}
            testID="sb01-feedback-unsure"
          />
        </View>
      </Animated.View>
    );
  },
);

function Btn({
  label, icon, tint, onPress, disabled, testID,
}: { label: string; icon: any; tint: string; onPress: () => void; disabled: boolean; testID: string }) {
  return (
    <TouchableOpacity
      style={[styles.btn, { borderColor: tint + '55' }, disabled && { opacity: 0.5 }]}
      onPress={onPress}
      disabled={disabled}
      testID={testID}
    >
      <Ionicons name={icon} size={16} color={tint} />
      <Text style={[styles.btnLabel, { color: tint }]}>{label}</Text>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  sheet: {
    position: 'absolute',
    left: 0, right: 0, bottom: 0,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    paddingBottom: spacing.xl,
    borderTopLeftRadius: radius.xl ?? 20,
    borderTopRightRadius: radius.xl ?? 20,
    backgroundColor: colors.bgCard,
    borderTopWidth: 1,
    borderColor: colors.border,
    zIndex: 50,
    shadowColor: '#000', shadowOpacity: 0.3, shadowRadius: 12, shadowOffset: { width: 0, height: -4 }, elevation: 12,
  },
  handle: {
    width: 36, height: 4, borderRadius: 2,
    backgroundColor: colors.textMuted, opacity: 0.4,
    alignSelf: 'center', marginBottom: spacing.md,
  },
  title: {
    color: colors.textPrimary,
    fontSize: fontSize.md ?? 14,
    fontWeight: '700',
    textAlign: 'center',
  },
  subtitle: {
    color: colors.textSecondary,
    fontSize: fontSize.xs ?? 11,
    textAlign: 'center',
    marginTop: 4,
    marginBottom: spacing.md,
  },
  row: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  btn: {
    flex: 1,
    flexDirection: 'column',
    alignItems: 'center',
    gap: 4,
    paddingVertical: spacing.md,
    borderRadius: radius.md ?? 10,
    borderWidth: 1,
    backgroundColor: colors.bgElevated,
  },
  btnLabel: {
    fontSize: fontSize.xs ?? 11,
    fontWeight: '700',
  },
});
