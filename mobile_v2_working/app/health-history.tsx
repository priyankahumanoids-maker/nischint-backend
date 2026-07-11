// HC-02 — Health history screen.
// Replaces the Day-3 stub. Renders a 7-day or 24-hour HR + SpO₂
// timeline from `GET /api/health-signals/history/{userId}` with
// inline anomaly dots (HR > 120, SpO₂ < 94).
//
// Chart engine: bare `react-native-svg`. We don't pull victory-native
// or recharts — both add ~600 KB to the bundle for a two-line chart.
// A tiny inline `<LineChart>` (~70 lines) does exactly what we need.
//
// RBAC happens server-side: the endpoint enforces self-or-guardian.
// This screen just hands `userId` to the URL.

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator, ScrollView, StyleSheet,
  Text, TouchableOpacity, View, Dimensions,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Svg, { Circle, Line, Path, Text as SvgText } from 'react-native-svg';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import api from '@/services/api';
import { useAuthStore } from '@/stores/authStore';
import { colors, fontSize, radius, spacing } from '@/theme';

// ── Types ────────────────────────────────────────────────────────────
interface Sample { timestamp: string; value: number }
interface Anomaly { timestamp: string; type: 'hr_high' | 'spo2_low'; value: number }
export interface HistoryResponse {
  user_id: string;
  hr: Sample[];
  spo2: Sample[];
  anomalies: Anomaly[];
}
type Window = '24h' | '7d';
const WINDOW_MS: Record<Window, number> = { '24h': 86_400_000, '7d': 7 * 86_400_000 };

// ── Test seam ───────────────────────────────────────────────────────
let _fetchOverride: ((userId: string) => Promise<HistoryResponse>) | null = null;
export function __setHistoryFetch(fn: ((u: string) => Promise<HistoryResponse>) | null): void {
  _fetchOverride = fn;
}
async function defaultFetchHistory(userId: string): Promise<HistoryResponse> {
  const res = await api.get<HistoryResponse>(`/health-signals/history/${userId}`);
  return res.data;
}

// ── Inline line chart ───────────────────────────────────────────────
interface LineChartProps {
  data: Sample[];
  anomalies: Sample[];
  cutoffMs: number;
  color: string;
  thresholdValue: number;
  thresholdLabel: string;
  thresholdAbove: boolean;          // true = anomaly when value > threshold
  yMin: number;
  yMax: number;
  yLabel: string;
  width: number;
  height: number;
  testID?: string;
}

function LineChart(props: LineChartProps): React.ReactElement {
  const { data, anomalies, cutoffMs, color, thresholdValue, thresholdLabel,
          thresholdAbove, yMin, yMax, yLabel, width, height, testID } = props;
  const padL = 36;
  const padR = 8;
  const padT = 12;
  const padB = 24;
  const plotW = Math.max(1, width  - padL - padR);
  const plotH = Math.max(1, height - padT - padB);

  const now = Date.now();
  const xMin = now - cutoffMs;
  const xMax = now;
  const xScale = (tsMs: number) => padL + ((tsMs - xMin) / (xMax - xMin)) * plotW;
  const yScale = (v: number) => padT + (1 - (v - yMin) / (yMax - yMin)) * plotH;

  // Build a polyline path with explicit M/L so a single missing point
  // doesn't blow up the chart geometry.
  let path = '';
  data.forEach((s, i) => {
    const t = Date.parse(s.timestamp);
    if (Number.isNaN(t) || t < xMin) return;
    const cmd = i === 0 ? 'M' : 'L';
    path += `${cmd}${xScale(t).toFixed(1)},${yScale(s.value).toFixed(1)} `;
  });

  const thresholdY = yScale(thresholdValue);

  return (
    <View testID={testID}>
      <Svg width={width} height={height}>
        {/* Axes */}
        <Line x1={padL} y1={padT} x2={padL} y2={padT + plotH} stroke="#cbd5e1" strokeWidth={1} />
        <Line x1={padL} y1={padT + plotH} x2={padL + plotW} y2={padT + plotH} stroke="#cbd5e1" strokeWidth={1} />
        {/* Threshold (dashed) */}
        <Line
          x1={padL} y1={thresholdY} x2={padL + plotW} y2={thresholdY}
          stroke={color} strokeWidth={1} strokeDasharray="4,4" opacity={0.55}
        />
        <SvgText x={padL + 4} y={thresholdY - 4} fontSize={10} fill={color}>
          {thresholdLabel}
        </SvgText>
        {/* Y-axis label */}
        <SvgText x={4} y={padT + 8} fontSize={10} fill="#6b7280">{yLabel}</SvgText>
        {/* Polyline */}
        {path.length > 0 && (
          <Path d={path} stroke={color} strokeWidth={2} fill="none" />
        )}
        {/* Anomaly dots */}
        {anomalies.map((a, i) => {
          const t = Date.parse(a.timestamp);
          if (Number.isNaN(t) || t < xMin) return null;
          const fits = thresholdAbove ? a.value > thresholdValue : a.value < thresholdValue;
          if (!fits) return null;
          return (
            <Circle
              key={`anom-${i}`}
              cx={xScale(t)} cy={yScale(a.value)} r={4.5}
              fill={color} stroke="#fff" strokeWidth={1.5}
            />
          );
        })}
        {/* X-axis labels: leftmost + rightmost timestamp */}
        <SvgText x={padL} y={padT + plotH + 14} fontSize={9} fill="#6b7280">
          {new Date(xMin).toLocaleString([], { month: 'short', day: 'numeric' })}
        </SvgText>
        <SvgText x={padL + plotW - 40} y={padT + plotH + 14} fontSize={9} fill="#6b7280">
          now
        </SvgText>
      </Svg>
    </View>
  );
}

// ── Screen ───────────────────────────────────────────────────────────
export default function HealthHistoryScreen(): React.ReactElement {
  const router = useRouter();
  const params = useLocalSearchParams<{ userId?: string }>();
  const { user } = useAuthStore();
  const targetUserId = (params.userId && params.userId.length > 0)
    ? params.userId : (user?.id ?? '');

  const [window, setWindow] = useState<Window>('7d');
  const [data, setData] = useState<HistoryResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  // HC-02 cache: keyed by `userId`. The 24h view is a strict subset
  // of 7d data we already fetched, so toggling 24h ↔ 7d after the
  // first load is a free client-side filter. The map survives
  // background tab returns; explicit pull-to-retry busts the cache
  // for the current user.
  const cacheRef = React.useRef<Map<string, HistoryResponse>>(new Map());

  const load = useCallback(async (opts: { force?: boolean } = {}) => {
    if (!targetUserId) {
      setError('No user selected'); setLoading(false); return;
    }
    const cached = cacheRef.current.get(targetUserId);
    if (cached && !opts.force) {
      setData(cached); setLoading(false); setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const fn = _fetchOverride ?? defaultFetchHistory;
      const fresh = await fn(targetUserId);
      cacheRef.current.set(targetUserId, fresh);
      setData(fresh);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load history');
    } finally {
      setLoading(false);
    }
  }, [targetUserId]);

  useEffect(() => { void load(); }, [load]);

  const cutoffMs = WINDOW_MS[window];
  const screenWidth = Dimensions.get('window').width - 32;

  // Client-side window filter — the underlying 7-day payload is the
  // source of truth, the chart just narrows its x-axis.
  const filtered = useMemo<HistoryResponse | null>(() => {
    if (!data) return null;
    const cutoff = Date.now() - cutoffMs;
    const inRange = (s: Sample): boolean => Date.parse(s.timestamp) >= cutoff;
    return {
      user_id:   data.user_id,
      hr:        data.hr.filter(inRange),
      spo2:      data.spo2.filter(inRange),
      anomalies: data.anomalies.filter((a) => Date.parse(a.timestamp) >= cutoff),
    };
  }, [data, cutoffMs]);

  // Anomalies are produced server-side, but `LineChart` expects them
  // alongside the data — fold them in by metric.
  const hrAnomalies = useMemo<Sample[]>(
    () => (filtered?.anomalies ?? [])
      .filter((a) => a.type === 'hr_high')
      .map((a) => ({ timestamp: a.timestamp, value: a.value })),
    [filtered],
  );
  const spo2Anomalies = useMemo<Sample[]>(
    () => (filtered?.anomalies ?? [])
      .filter((a) => a.type === 'spo2_low')
      .map((a) => ({ timestamp: a.timestamp, value: a.value })),
    [filtered],
  );

  const hasData = (filtered?.hr.length ?? 0) + (filtered?.spo2.length ?? 0) > 0;

  return (
    <SafeAreaView style={styles.safe} edges={['top']} testID="health-history">
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} testID="health-history-back">
          <Ionicons name="chevron-back" size={24} color={colors.textPrimary} />
        </TouchableOpacity>
        <Text style={styles.title}>Health history</Text>
        <View style={{ width: 24 }} />
      </View>

      {/* Window toggle */}
      <View style={styles.toggleRow}>
        {(['24h', '7d'] as const).map((w) => (
          <TouchableOpacity
            key={w}
            onPress={() => setWindow(w)}
            style={[styles.toggleBtn, window === w && styles.toggleBtnActive]}
            testID={`history-toggle-${w}`}
          >
            <Text style={[styles.toggleText, window === w && styles.toggleTextActive]}>
              {w === '24h' ? 'Last 24h' : 'Last 7 days'}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      <ScrollView contentContainerStyle={{ padding: spacing.lg, gap: spacing.lg }}>
        {loading && (
          <View style={styles.center} testID="history-loading">
            <ActivityIndicator size="large" color={colors.primary} />
            <Text style={styles.muted}>Loading history…</Text>
          </View>
        )}

        {!loading && error && (
          <View style={styles.center} testID="history-error">
            <Text style={styles.errorText}>{error}</Text>
            <TouchableOpacity style={styles.retryBtn}
                              onPress={() => void load({ force: true })}
                              testID="history-retry">
              <Text style={styles.retryText}>Retry</Text>
            </TouchableOpacity>
          </View>
        )}

        {!loading && !error && !hasData && (
          <View style={styles.center} testID="history-empty">
            <View style={styles.iconCircle}>
              <Ionicons name="pulse" size={32} color={colors.primary} />
            </View>
            <Text style={styles.h1}>No wearable data yet</Text>
            <Text style={styles.p}>Connect your device to start seeing trends here.</Text>
          </View>
        )}

        {!loading && !error && hasData && filtered && (
          <>
            <View style={styles.card}>
              <View style={styles.cardHeader}>
                <Text style={styles.cardTitle}>Heart rate</Text>
                <Text style={styles.cardSubtitle}>{filtered.hr.length} readings</Text>
              </View>
              <LineChart
                data={filtered.hr}
                anomalies={hrAnomalies}
                cutoffMs={cutoffMs}
                color="#dc2626"
                thresholdValue={120}
                thresholdLabel="120 bpm threshold"
                thresholdAbove
                yMin={40}
                yMax={160}
                yLabel="bpm"
                width={screenWidth}
                height={180}
                testID="chart-hr"
              />
            </View>

            <View style={styles.card}>
              <View style={styles.cardHeader}>
                <Text style={styles.cardTitle}>SpO₂</Text>
                <Text style={styles.cardSubtitle}>{filtered.spo2.length} readings</Text>
              </View>
              <LineChart
                data={filtered.spo2}
                anomalies={spo2Anomalies}
                cutoffMs={cutoffMs}
                color="#2563eb"
                thresholdValue={94}
                thresholdLabel="94% threshold"
                thresholdAbove={false}
                yMin={85}
                yMax={100}
                yLabel="%"
                width={screenWidth}
                height={180}
                testID="chart-spo2"
              />
            </View>

            {filtered.anomalies.length > 0 && (
              <View style={styles.card}>
                <Text style={styles.cardTitle}>Anomalies flagged</Text>
                {filtered.anomalies.slice(0, 10).map((a, i) => (
                  <View key={`anom-${i}`} style={styles.anomalyRow}>
                    <Ionicons
                      name="alert-circle"
                      size={16}
                      color={a.type === 'hr_high' ? '#dc2626' : '#2563eb'}
                    />
                    <Text style={styles.anomalyText}>
                      {a.type === 'hr_high'
                        ? `HR ${a.value.toFixed(0)} bpm`
                        : `SpO₂ ${a.value.toFixed(0)}%`}
                    </Text>
                    <Text style={styles.anomalyTime}>
                      {new Date(a.timestamp).toLocaleString()}
                    </Text>
                  </View>
                ))}
              </View>
            )}
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe:   { flex: 1, backgroundColor: colors.bg },
  header: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  title:        { color: colors.textPrimary, fontSize: fontSize.lg ?? 17, fontWeight: '700' },
  toggleRow:    { flexDirection: 'row', padding: spacing.md, gap: spacing.sm },
  toggleBtn:    { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 999,
                  backgroundColor: colors.bgElevated, borderWidth: 1, borderColor: colors.border },
  toggleBtnActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  toggleText:   { color: colors.textPrimary, fontSize: 13, fontWeight: '600' },
  toggleTextActive: { color: '#fff' },
  card:         { backgroundColor: colors.bgElevated, borderRadius: radius.md ?? 12,
                  padding: spacing.md, borderWidth: 1, borderColor: colors.border },
  cardHeader:   { flexDirection: 'row', justifyContent: 'space-between',
                  alignItems: 'baseline', marginBottom: 8 },
  cardTitle:    { color: colors.textPrimary, fontSize: 15, fontWeight: '700' },
  cardSubtitle: { color: colors.textSecondary, fontSize: 12 },
  center:       { alignItems: 'center', padding: spacing.xl },
  muted:        { color: colors.textSecondary, marginTop: 12 },
  errorText:    { color: '#b91c1c', marginBottom: 12, textAlign: 'center' },
  retryBtn:     { backgroundColor: colors.primary, paddingHorizontal: 16, paddingVertical: 10, borderRadius: 8 },
  retryText:    { color: '#fff', fontWeight: '700' },
  iconCircle:   { width: 64, height: 64, borderRadius: 32, marginBottom: spacing.md,
                  backgroundColor: colors.primary + '22',
                  alignItems: 'center', justifyContent: 'center' },
  h1:           { color: colors.textPrimary, fontSize: fontSize['2xl'] ?? 20, fontWeight: '700' },
  p:            { color: colors.textSecondary, fontSize: 13, marginTop: 8, textAlign: 'center' },
  anomalyRow:   { flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
                  paddingVertical: 6, borderTopWidth: 1, borderTopColor: colors.border },
  anomalyText:  { color: colors.textPrimary, fontSize: 13, fontWeight: '600' },
  anomalyTime:  { color: colors.textSecondary, fontSize: 11, marginLeft: 'auto' },
});
