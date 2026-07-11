/**
 * HC-01 Day 4 — Per-dependent vitals card for the guardian dashboard.
 *
 * Polls `GET /api/health-signals/dependent/:id/latest` every 60s
 * (and on screen-focus). Renders an amber border when HR > 120 bpm
 * and a red border when SpO₂ < 94 % — same thresholds the backend
 * brain hook uses, so what the guardian sees on this card is
 * semantically identical to what fires a SafetyEvent.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect } from 'expo-router';

import { colors, fontSize, radius, spacing } from '@/theme';
import api from '@/services/api';

interface DependentVitals {
  dependent_id: string;
  hr: number | null;
  spo2: number | null;
  last_sync: string | null;
}

interface Props {
  dependentId: string;
  dependentName: string;
  testID?: string;
}

const POLL_MS = 60_000;

const HR_THRESHOLD = 120;
const SPO2_THRESHOLD = 94;

const relativeAgo = (iso: string | null): string => {
  if (!iso) return 'no data yet';
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return 'no data yet';
  const sec = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  return `${Math.floor(hr / 24)}d ago`;
};

export function DependentVitalsCard({ dependentId, dependentName, testID }: Props) {
  const [data, setData] = useState<DependentVitals | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [, force] = useState(0);

  const fetchOnce = useCallback(async () => {
    try {
      const res = await api.get<DependentVitals>(`/health-signals/dependent/${dependentId}/latest`);
      setData(res.data);
      setError(null);
    } catch (e: any) {
      // 403 is expected when the relationship isn't yet established;
      // surface it gently instead of as an error state.
      const status = e?.response?.status;
      if (status === 403 || status === 404) {
        setData(null);
        setError(null);
      } else {
        setError('Could not load vitals');
      }
    } finally {
      setLoading(false);
    }
  }, [dependentId]);

  useFocusEffect(
    useCallback(() => {
      fetchOnce();
      pollRef.current = setInterval(fetchOnce, POLL_MS);
      const tickIv = setInterval(() => force((n) => n + 1), 30_000);
      return () => {
        if (pollRef.current) clearInterval(pollRef.current);
        clearInterval(tickIv);
      };
    }, [fetchOnce]),
  );

  // Mount-time fetch even before focus (e.g., when rendered inside a
  // not-yet-focused tab on first render).
  useEffect(() => {
    fetchOnce();
  }, [fetchOnce]);

  const hr = data?.hr;
  const spo2 = data?.spo2;
  const hrBreach = typeof hr === 'number' && hr > HR_THRESHOLD;
  const spo2Breach = typeof spo2 === 'number' && spo2 < SPO2_THRESHOLD;

  const borderColor = spo2Breach
    ? colors.critical
    : hrBreach
    ? colors.warning
    : colors.border;

  if (loading && !data) {
    return (
      <View style={[styles.card, { borderColor: colors.border }]} testID={testID ?? `dependent-vitals-${dependentId}`}>
        <ActivityIndicator size="small" color={colors.primary} />
      </View>
    );
  }

  const hasAnyData = typeof hr === 'number' || typeof spo2 === 'number';

  // HC-02 — tap card → guardian's view of dependent's 7-day history.
  // Lazy require to avoid pulling expo-router into all DependentVitalsCard
  // consumers' test fixtures.
  const navigateToHistory = useCallback(() => {
    try {
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const { router } = require('expo-router') as { router: { push: (s: string) => void } };
      router.push(`/health-history?userId=${dependentId}`);
    } catch { /* noop in test env */ }
  }, [dependentId]);

  return (
    <TouchableOpacity
      onPress={navigateToHistory}
      style={[styles.card, { borderColor }]}
      testID={testID ?? `dependent-vitals-${dependentId}`}
      accessibilityLabel={`Vitals for ${dependentName}`}
    >
      <View style={styles.header}>
        <View style={styles.iconWrap}>
          <Ionicons name="watch-outline" size={16} color={colors.primary} />
        </View>
        <Text style={styles.name} numberOfLines={1} testID={`dependent-name-${dependentId}`}>
          {dependentName}
        </Text>
        {(hrBreach || spo2Breach) && (
          <View style={[styles.breachBadge, { backgroundColor: spo2Breach ? colors.critical : colors.warning }]}>
            <Text style={styles.breachText}>{spo2Breach ? 'SpO₂ LOW' : 'HR HIGH'}</Text>
          </View>
        )}
      </View>

      {hasAnyData ? (
        <View style={styles.metrics}>
          <View style={styles.metric}>
            <Ionicons name="heart" size={14} color={hrBreach ? colors.warning : colors.critical} />
            <Text style={[styles.value, hrBreach && { color: colors.warning }]} testID={`dependent-hr-${dependentId}`}>
              {typeof hr === 'number' ? Math.round(hr) : '—'}
            </Text>
            <Text style={styles.unit}>bpm</Text>
          </View>
          <View style={styles.divider} />
          <View style={styles.metric}>
            <Ionicons name="leaf" size={14} color={spo2Breach ? colors.critical : colors.primaryLight} />
            <Text style={[styles.value, spo2Breach && { color: colors.critical }]} testID={`dependent-spo2-${dependentId}`}>
              {typeof spo2 === 'number' ? Math.round(spo2) : '—'}
            </Text>
            <Text style={styles.unit}>%</Text>
          </View>
          <View style={styles.divider} />
          <Text style={styles.sync} testID={`dependent-sync-${dependentId}`}>
            {relativeAgo(data?.last_sync ?? null)}
          </Text>
        </View>
      ) : (
        <Text style={styles.empty} testID={`dependent-empty-${dependentId}`}>
          {error ?? 'No wearable data yet'}
        </Text>
      )}
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  card: {
    padding: spacing.md,
    borderRadius: radius.md ?? 10,
    backgroundColor: colors.bgElevated,
    borderWidth: 1,
    marginBottom: spacing.sm,
    minHeight: 56,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  iconWrap: {
    width: 26,
    height: 26,
    borderRadius: 13,
    backgroundColor: colors.primary + '22',
    alignItems: 'center',
    justifyContent: 'center',
  },
  name: {
    flex: 1,
    color: colors.textPrimary,
    fontSize: fontSize.sm ?? 13,
    fontWeight: '600',
  },
  breachBadge: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: 999,
  },
  breachText: {
    color: colors.white,
    fontSize: 10,
    fontWeight: '800',
    letterSpacing: 0.4,
  },
  metrics: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  metric: { flexDirection: 'row', alignItems: 'baseline', gap: 4 },
  value: { color: colors.textPrimary, fontSize: fontSize.md ?? 14, fontWeight: '700' },
  unit: { color: colors.textMuted, fontSize: fontSize.xs ?? 11 },
  divider: { width: 1, height: 14, backgroundColor: colors.border },
  sync: { color: colors.textMuted, fontSize: fontSize.xs ?? 11, marginLeft: 'auto' },
  empty: { color: colors.textMuted, fontSize: fontSize.xs ?? 11, fontStyle: 'italic' },
});
