// DPDP-04-MOB — Global pre-permission consent half-modal.
//
// Subscribes to `useConsentGateStore`. When a `pending` prompt is
// present, slides up a bottom-sheet that explains:
//   • why Nischint needs this category of data,
//   • what specifically is collected,
//   • the DPDP §6.3 compliance statement (explicit, granular, revocable
//     consent).
// Provides Accept / Decline buttons. The store's `resolveCurrent`
// passes the boolean back to the `requireConsent()` promise.
//
// Rendered inside the root layout so it overlays every screen.

import React from 'react';
import {
  Modal,
  Pressable,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { colors, fontSize, radius, spacing } from '../theme';
import {
  useConsentGateStore,
  type ConsentCategory,
} from '../stores/consentGateStore';

interface CategoryCopy {
  title: string;
  purpose: string;
  collected: string[];
  icon: string;
}

const COPY: Record<ConsentCategory, CategoryCopy> = {
  location_tracking: {
    title: 'Location access',
    purpose:
      'So your guardians can see you on the live map during an SOS and we can detect when you leave a safe zone.',
    collected: [
      'Live GPS coordinates while a journey is active',
      'Background location for geofence breach alerts',
      'Movement & speed for route deviation detection',
    ],
    icon: '📍',
  },
  audio_recording: {
    title: 'Microphone access',
    purpose:
      'To detect cries for help or distress sounds during an emergency. Audio is analysed on-device only — only the severity score is uploaded.',
    collected: [
      'Short ambient audio samples (analysed on-device)',
      'Voice features (pitch, amplitude, keywords)',
      'Distress confidence score — NOT the raw audio',
    ],
    icon: '🎙️',
  },
  health_vitals: {
    title: 'Health & wearable data',
    purpose:
      'To detect medical anomalies — abnormal heart-rate, low SpO₂, sudden falls — and trigger silent SOS when needed.',
    collected: [
      'Heart-rate readings from your wearable',
      'Blood-oxygen (SpO₂) samples',
      'Step count & activity for baseline modelling',
    ],
    icon: '❤️',
  },
  push_notifications: {
    title: 'Emergency notifications',
    purpose:
      'To deliver SOS alerts, geofence breach warnings, and health anomalies to your phone — even when the app is closed.',
    collected: [
      'A push token from Apple / Google to deliver alerts',
      'Notification interaction (read / tapped) for delivery audit',
    ],
    icon: '🔔',
  },
  biometric_sensors: {
    title: 'Motion sensors',
    purpose:
      'To detect falls and shake-to-SOS gestures using the device accelerometer and gyroscope. Raw motion data stays on-device.',
    collected: [
      'Accelerometer & gyroscope readings (on-device only)',
      'Fall confidence scores',
    ],
    icon: '🌀',
  },
};

export function ConsentSheet(): React.ReactElement | null {
  const pending = useConsentGateStore((s) => s.pending);
  const resolveCurrent = useConsentGateStore((s) => s.resolveCurrent);

  if (!pending) return null;

  const copy = COPY[pending.category];

  return (
    <Modal
      animationType="slide"
      transparent
      visible={pending !== null}
      onRequestClose={() => resolveCurrent(false)}
      testID={`consent-sheet-${pending.category}`}
    >
      <View style={styles.backdrop}>
        {/* Tap-outside dismisses as a Decline — DPDP §6.4 treats
            absence of affirmative action as no-consent. */}
        <Pressable
          style={styles.backdropTap}
          onPress={() => resolveCurrent(false)}
          testID="consent-sheet-backdrop"
        />
        <View style={styles.sheet}>
          <View style={styles.handle} />

          <Text style={styles.icon}>{copy.icon}</Text>
          <Text style={styles.title} testID="consent-sheet-title">
            {copy.title}
          </Text>
          <Text style={styles.purpose}>{copy.purpose}</Text>

          <View style={styles.collectedBlock}>
            <Text style={styles.collectedLabel}>What we collect</Text>
            {copy.collected.map((item) => (
              <Text key={item} style={styles.bullet}>
                • {item}
              </Text>
            ))}
          </View>

          <View style={styles.complianceBlock}>
            <Text style={styles.complianceTitle}>
              Your right (DPDP Act, §6)
            </Text>
            <Text style={styles.complianceText}>
              Your consent is explicit and granular. You can revoke it any
              time from <Text style={styles.bold}>Settings → Privacy</Text>{' '}
              — Nischint stops processing this data within 7 days and
              keeps no shadow copies.
            </Text>
          </View>

          <TouchableOpacity
            style={styles.acceptBtn}
            onPress={() => resolveCurrent(true)}
            testID="consent-sheet-accept"
          >
            <Text style={styles.acceptText}>Allow {copy.title}</Text>
          </TouchableOpacity>

          <TouchableOpacity
            style={styles.declineBtn}
            onPress={() => resolveCurrent(false)}
            testID="consent-sheet-decline"
          >
            <Text style={styles.declineText}>Not now</Text>
          </TouchableOpacity>

          <Text style={styles.footer}>
            After you allow, your phone will show its own permission
            prompt — that one is from Android/iOS, not Nischint.
          </Text>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.55)',
    justifyContent: 'flex-end',
  },
  backdropTap: {
    flex: 1,
  },
  sheet: {
    backgroundColor: colors.bgCard,
    borderTopLeftRadius: radius.xl,
    borderTopRightRadius: radius.xl,
    padding: spacing['2xl'],
    paddingBottom: spacing['3xl'],
    borderTopWidth: 1,
    borderColor: colors.border,
  },
  handle: {
    alignSelf: 'center',
    width: 44,
    height: 4,
    borderRadius: 2,
    backgroundColor: colors.textMuted,
    marginBottom: spacing.lg,
    opacity: 0.5,
  },
  icon: {
    fontSize: 36,
    textAlign: 'center',
    marginBottom: spacing.sm,
  },
  title: {
    fontSize: fontSize.xl,
    fontWeight: '700',
    color: colors.textPrimary,
    textAlign: 'center',
    marginBottom: spacing.md,
  },
  purpose: {
    fontSize: fontSize.md,
    color: colors.textSecondary,
    textAlign: 'center',
    lineHeight: 22,
    marginBottom: spacing.lg,
  },
  collectedBlock: {
    backgroundColor: colors.bgElevated,
    borderRadius: radius.md,
    padding: spacing.lg,
    marginBottom: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  collectedLabel: {
    fontSize: fontSize.xs,
    fontWeight: '700',
    color: colors.primary,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginBottom: spacing.sm,
  },
  bullet: {
    fontSize: fontSize.sm,
    color: colors.textPrimary,
    marginVertical: 3,
    lineHeight: 20,
  },
  complianceBlock: {
    backgroundColor: 'rgba(14, 165, 233, 0.08)',
    borderRadius: radius.md,
    padding: spacing.lg,
    marginBottom: spacing.xl,
    borderLeftWidth: 3,
    borderLeftColor: colors.primary,
  },
  complianceTitle: {
    fontSize: fontSize.xs,
    fontWeight: '700',
    color: colors.primaryLight,
    marginBottom: 4,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  complianceText: {
    fontSize: fontSize.sm,
    color: colors.textSecondary,
    lineHeight: 19,
  },
  bold: {
    fontWeight: '700',
    color: colors.textPrimary,
  },
  acceptBtn: {
    backgroundColor: colors.primary,
    paddingVertical: spacing.lg,
    borderRadius: radius.md,
    alignItems: 'center',
    marginBottom: spacing.sm,
  },
  acceptText: {
    color: colors.white,
    fontSize: fontSize.md,
    fontWeight: '700',
  },
  declineBtn: {
    paddingVertical: spacing.md,
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  declineText: {
    color: colors.textSecondary,
    fontSize: fontSize.md,
    fontWeight: '600',
  },
  footer: {
    fontSize: fontSize.xs,
    color: colors.textMuted,
    textAlign: 'center',
    lineHeight: 16,
  },
});
