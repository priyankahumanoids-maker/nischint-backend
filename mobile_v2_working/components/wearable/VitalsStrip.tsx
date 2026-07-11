/**
 * HC-01 Day 3 — Vitals strip on the homescreen.
 *
 * Only renders when Health Connect permissions are granted. Reads the
 * latest HR / SpO₂ / sync timestamp from AsyncStorage (populated by
 * the background `WEARABLE_SYNC` task after each successful upload).
 *
 * Tap → navigates to /health-history (stub screen — Day 4 work).
 */
import React, { useCallback, useEffect, useState } from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useFocusEffect, useRouter } from 'expo-router';

import { colors, fontSize, radius, spacing } from '@/theme';
import { HC_KEYS, isHealthConnectGranted } from '@/services/healthConnectStorage';

const relativeAgo = (iso: string | null): string => {
  if (!iso) return 'syncing…';
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return 'syncing…';
  const sec = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const d = Math.floor(hr / 24);
  return `${d}d ago`;
};

export function VitalsStrip() {
  const router = useRouter();
  const [granted, setGranted] = useState<boolean | null>(null);
  const [hr, setHr] = useState<string | null>(null);
  const [spo2, setSpo2] = useState<string | null>(null);
  const [lastSync, setLastSync] = useState<string | null>(null);
  const [, force] = useState(0);

  const load = useCallback(async () => {
    const ok = await isHealthConnectGranted();
    setGranted(ok);
    if (!ok) return;
    const [h, s, ts] = await Promise.all([
      AsyncStorage.getItem(HC_KEYS.lastHr),
      AsyncStorage.getItem(HC_KEYS.lastSpo2),
      AsyncStorage.getItem(HC_KEYS.lastSync),
    ]);
    setHr(h);
    setSpo2(s);
    setLastSync(ts);
  }, []);

  // Refresh on every screen focus + tick "X ago" every 30s.
  useFocusEffect(
    useCallback(() => {
      load();
      const iv = setInterval(() => force((n) => n + 1), 30_000);
      return () => clearInterval(iv);
    }, [load]),
  );

  useEffect(() => {
    load();
  }, [load]);

  if (!granted) return null;

  const hasData = hr || spo2;

  return (
    <TouchableOpacity
      onPress={() => router.push('/health-history')}
      activeOpacity={0.85}
      style={styles.strip}
      testID="vitals-strip"
    >
      {hasData ? (
        <>
          <View style={styles.metric}>
            <Ionicons name="heart" size={14} color={colors.critical} />
            <Text style={styles.metricValue} testID="vitals-hr">
              {hr ? `${Math.round(Number(hr))}` : '—'}
            </Text>
            <Text style={styles.metricUnit}>bpm</Text>
          </View>
          <View style={styles.divider} />
          <View style={styles.metric}>
            <Ionicons name="leaf" size={14} color={colors.primaryLight} />
            <Text style={styles.metricValue} testID="vitals-spo2">
              {spo2 ? `${Math.round(Number(spo2))}` : '—'}
            </Text>
            <Text style={styles.metricUnit}>%</Text>
          </View>
          <View style={styles.divider} />
          <View style={styles.metric}>
            <Ionicons name="sync" size={12} color={colors.textMuted} />
            <Text style={styles.syncLabel} testID="vitals-sync-ago">
              {relativeAgo(lastSync)}
            </Text>
          </View>
          <Ionicons
            name="chevron-forward"
            size={14}
            color={colors.textMuted}
            style={{ marginLeft: 'auto' }}
          />
        </>
      ) : (
        <>
          <Ionicons name="watch-outline" size={16} color={colors.primary} />
          <Text style={styles.emptyLabel}>Wearable connected — syncing…</Text>
        </>
      )}
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  strip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderRadius: radius.md ?? 10,
    backgroundColor: colors.bgElevated,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: spacing.lg,
  },
  metric: { flexDirection: 'row', alignItems: 'baseline', gap: 4 },
  metricValue: {
    color: colors.textPrimary,
    fontSize: fontSize.md ?? 14,
    fontWeight: '700',
  },
  metricUnit: {
    color: colors.textMuted,
    fontSize: fontSize.xs ?? 11,
  },
  syncLabel: {
    color: colors.textMuted,
    fontSize: fontSize.xs ?? 11,
  },
  divider: { width: 1, height: 14, backgroundColor: colors.border },
  emptyLabel: {
    color: colors.textSecondary,
    fontSize: fontSize.sm ?? 13,
  },
});
