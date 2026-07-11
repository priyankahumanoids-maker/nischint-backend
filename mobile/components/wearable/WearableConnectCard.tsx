/**
 * HC-01 Day 3 — Wearable connect onboarding card.
 *
 * Renders only when:
 *   • `hc_permissions_granted` is NOT 'true'  AND
 *   • `hc_permissions_denied_until` is absent or expired (7-day cool-off).
 *
 * On grant: persists permission + registers the background sync task.
 * On deny:  marks a 7-day suppression window.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Platform, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';

import { colors, fontSize, radius, spacing } from '@/theme';
import { requestHealthPermissions } from '@/services/healthConnectService';
import {
  isHealthConnectDenyActive,
  isHealthConnectGranted,
  markHealthConnectDenied,
  markHealthConnectGranted,
} from '@/services/healthConnectStorage';
import { registerWearableSync } from '@/tasks/wearableSyncTask';

export function WearableConnectCard() {
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);

  const recompute = useCallback(async () => {
    // Day 3 ships Android-only (Health Connect). iOS HealthKit is a
    // future drop — hide the card on iOS until then to avoid a CTA
    // that does nothing.
    if (Platform.OS !== 'android') {
      setVisible(false);
      return;
    }
    const [granted, denyActive] = await Promise.all([
      isHealthConnectGranted(),
      isHealthConnectDenyActive(),
    ]);
    setVisible(!granted && !denyActive);
  }, []);

  useEffect(() => {
    recompute();
  }, [recompute]);

  const handleConnect = useCallback(async () => {
    setBusy(true);
    try {
      const ok = await requestHealthPermissions();
      if (ok) {
        await markHealthConnectGranted();
        try {
          await registerWearableSync();
        } catch (e) {
          console.warn('[WearableConnectCard] registerWearableSync failed:', e);
        }
      } else {
        await markHealthConnectDenied();
      }
    } finally {
      setBusy(false);
      recompute();
    }
  }, [recompute]);

  const handleDismiss = useCallback(async () => {
    await markHealthConnectDenied();
    recompute();
  }, [recompute]);

  if (!visible) return null;

  return (
    <View style={styles.card} testID="wearable-connect-card">
      <View style={styles.iconWrap}>
        <Ionicons name="watch-outline" size={22} color={colors.primary} />
      </View>
      <View style={styles.body}>
        <Text style={styles.title} testID="wearable-connect-title">
          Connect your wearable
        </Text>
        <Text style={styles.subtitle}>
          Get health-based safety alerts. We read heart-rate, SpO₂ and steps from
          Health Connect — nothing else, and nothing is sold.
        </Text>
        <View style={styles.actions}>
          <TouchableOpacity
            style={[styles.connectBtn, busy && styles.connectBtnDisabled]}
            onPress={handleConnect}
            disabled={busy}
            testID="wearable-connect-btn"
          >
            {busy ? (
              <ActivityIndicator size="small" color={colors.white} />
            ) : (
              <Text style={styles.connectBtnText}>Connect</Text>
            )}
          </TouchableOpacity>
          <TouchableOpacity
            onPress={handleDismiss}
            style={styles.dismissBtn}
            disabled={busy}
            testID="wearable-connect-dismiss"
          >
            <Text style={styles.dismissText}>Not now</Text>
          </TouchableOpacity>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: 'row',
    gap: spacing.md,
    padding: spacing.lg,
    borderRadius: radius.lg ?? 14,
    backgroundColor: colors.bgCard,
    borderWidth: 1,
    borderColor: colors.borderActive + '55',
    marginBottom: spacing.lg,
  },
  iconWrap: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.primary + '22',
    alignItems: 'center',
    justifyContent: 'center',
  },
  body: { flex: 1 },
  title: {
    color: colors.textPrimary,
    fontSize: fontSize.md ?? 14,
    fontWeight: '700',
    marginBottom: spacing.xs,
  },
  subtitle: {
    color: colors.textSecondary,
    fontSize: fontSize.sm ?? 13,
    lineHeight: 18,
    marginBottom: spacing.md,
  },
  actions: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  connectBtn: {
    backgroundColor: colors.primary,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    borderRadius: radius.md ?? 10,
    minWidth: 96,
    alignItems: 'center',
  },
  connectBtnDisabled: { opacity: 0.6 },
  connectBtnText: {
    color: colors.white,
    fontSize: fontSize.sm ?? 13,
    fontWeight: '700',
  },
  dismissBtn: { paddingHorizontal: spacing.sm, paddingVertical: spacing.sm },
  dismissText: { color: colors.textMuted, fontSize: fontSize.sm ?? 13 },
});
