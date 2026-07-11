// SafetyAlertBanner — Unified alert UI for fall / voice / wandering events
//
// Slide-in banner at top of screen with:
//  - Color-coded header (red = fall/voice, yellow = wandering)
//  - Countdown timer ring
//  - "I'm OK" dismiss button
//  - Optional extra action buttons (wandering: "Need help")

import React, { useEffect, useRef, useState } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, Animated,
  Vibration, Dimensions,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { colors, spacing, fontSize, radius } from '@/theme';
import type { SafetyAlert } from '@/services/sensorService';

const SCREEN_WIDTH = Dimensions.get('window').width;

const ALERT_CONFIG: Record<string, { color: string; icon: string; bg: string }> = {
  fall:      { color: '#EF4444', icon: 'body-outline',         bg: 'rgba(239,68,68,0.12)' },
  voice:     { color: '#EF4444', icon: 'mic-outline',          bg: 'rgba(239,68,68,0.12)' },
  wandering: { color: '#EAB308', icon: 'navigate-outline',     bg: 'rgba(234,179,8,0.12)' },
};

interface Props {
  alert: SafetyAlert | null;
  secondsRemaining: number;
  onDismiss: (alertId: string) => void;
  /** For wandering: "detour" or "help" */
  onAction?: (alertId: string, actionKey: string) => void;
}

export default function SafetyAlertBanner({ alert, secondsRemaining, onDismiss, onAction }: Props) {
  const slideAnim = useRef(new Animated.Value(-200)).current;
  const pulseAnim = useRef(new Animated.Value(1)).current;
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (alert) {
      setVisible(true);
      Vibration.vibrate([0, 300, 150, 300]);

      Animated.spring(slideAnim, {
        toValue: 0,
        tension: 60,
        friction: 10,
        useNativeDriver: true,
      }).start();

      // Pulse animation
      const pulse = Animated.loop(
        Animated.sequence([
          Animated.timing(pulseAnim, { toValue: 0.5, duration: 600, useNativeDriver: true }),
          Animated.timing(pulseAnim, { toValue: 1, duration: 600, useNativeDriver: true }),
        ]),
      );
      pulse.start();
      return () => pulse.stop();
    } else {
      Animated.timing(slideAnim, {
        toValue: -200,
        duration: 250,
        useNativeDriver: true,
      }).start(() => setVisible(false));
    }
  }, [alert]);

  if (!visible || !alert) return null;

  const cfg = ALERT_CONFIG[alert.type] || ALERT_CONFIG.fall;
  const progress = alert.countdownSeconds > 0
    ? secondsRemaining / alert.countdownSeconds
    : 0;

  return (
    <Animated.View
      style={[styles.container, { transform: [{ translateY: slideAnim }], borderColor: cfg.color + '40' }]}
      testID="safety-alert-banner"
    >
      {/* Top accent stripe */}
      <View style={[styles.stripe, { backgroundColor: cfg.color }]} />

      <View style={styles.body}>
        {/* Left: icon + countdown ring */}
        <View style={styles.iconCol}>
          <Animated.View style={[styles.iconCircle, { backgroundColor: cfg.bg, opacity: pulseAnim }]}>
            <Ionicons name={cfg.icon as any} size={28} color={cfg.color} />
          </Animated.View>
          {alert.countdownSeconds > 0 && (
            <View style={styles.countdownBadge}>
              <Text style={[styles.countdownText, { color: cfg.color }]}>{secondsRemaining}s</Text>
            </View>
          )}
        </View>

        {/* Center: message */}
        <View style={styles.textCol}>
          <Text style={styles.alertLabel}>
            {alert.type === 'fall' ? 'FALL DETECTED' : alert.type === 'voice' ? 'DISTRESS DETECTED' : 'OFF ROUTE'}
          </Text>
          <Text style={styles.alertMessage} numberOfLines={2}>{alert.message}</Text>

          {/* Progress bar for countdown */}
          {alert.countdownSeconds > 0 && (
            <View style={styles.progressTrack}>
              <View style={[styles.progressFill, { width: `${progress * 100}%`, backgroundColor: cfg.color }]} />
            </View>
          )}
        </View>
      </View>

      {/* Buttons */}
      <View style={styles.buttons}>
        {alert.actions && alert.actions.length > 0 ? (
          alert.actions.map((action) => (
            <TouchableOpacity
              key={action.key}
              style={[
                styles.actionBtn,
                action.key === 'help' ? styles.helpBtn : styles.okBtn,
              ]}
              onPress={() => onAction?.(alert.id, action.key)}
              testID={`safety-alert-action-${action.key}`}
            >
              <Text style={[
                styles.actionBtnText,
                action.key === 'help' ? styles.helpBtnText : styles.okBtnText,
              ]}>
                {action.label}
              </Text>
            </TouchableOpacity>
          ))
        ) : (
          <TouchableOpacity
            style={styles.okBtn}
            onPress={() => onDismiss(alert.id)}
            testID="safety-alert-dismiss"
          >
            <Ionicons name="checkmark-circle" size={18} color={colors.safe} />
            <Text style={styles.okBtnText}>I'm OK</Text>
          </TouchableOpacity>
        )}
      </View>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  container: {
    position: 'absolute',
    top: 50,
    left: spacing.md,
    right: spacing.md,
    zIndex: 9999,
    backgroundColor: colors.bgElevated,
    borderRadius: radius.xl,
    borderWidth: 1,
    overflow: 'hidden',
    elevation: 20,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.5,
    shadowRadius: 16,
  },
  stripe: {
    height: 3,
    width: '100%',
  },
  body: {
    flexDirection: 'row',
    padding: spacing.lg,
    gap: spacing.md,
  },
  iconCol: {
    alignItems: 'center',
    gap: spacing.xs,
  },
  iconCircle: {
    width: 52,
    height: 52,
    borderRadius: 26,
    alignItems: 'center',
    justifyContent: 'center',
  },
  countdownBadge: {
    backgroundColor: colors.bg,
    borderRadius: radius.full,
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
  },
  countdownText: {
    fontSize: fontSize.xs,
    fontWeight: '800',
    fontVariant: ['tabular-nums'],
  },
  textCol: {
    flex: 1,
    justifyContent: 'center',
  },
  alertLabel: {
    fontSize: fontSize.xs,
    fontWeight: '800',
    color: colors.textMuted,
    letterSpacing: 1.5,
    marginBottom: 2,
  },
  alertMessage: {
    fontSize: fontSize.md,
    fontWeight: '600',
    color: colors.textPrimary,
    lineHeight: 20,
  },
  progressTrack: {
    height: 3,
    backgroundColor: colors.border,
    borderRadius: 2,
    marginTop: spacing.sm,
    overflow: 'hidden',
  },
  progressFill: {
    height: '100%',
    borderRadius: 2,
  },
  buttons: {
    flexDirection: 'row',
    gap: spacing.sm,
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.lg,
  },
  okBtn: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
    backgroundColor: colors.safe + '18',
    borderColor: colors.safe + '40',
    borderWidth: 1,
    borderRadius: radius.lg,
    paddingVertical: spacing.md,
  },
  okBtnText: {
    fontSize: fontSize.sm,
    fontWeight: '700',
    color: colors.safe,
  },
  actionBtn: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: radius.lg,
    paddingVertical: spacing.md,
    borderWidth: 1,
  },
  actionBtnText: {
    fontSize: fontSize.sm,
    fontWeight: '700',
  },
  helpBtn: {
    backgroundColor: colors.critical + '18',
    borderColor: colors.critical + '40',
  },
  helpBtnText: {
    color: colors.critical,
  },
});
