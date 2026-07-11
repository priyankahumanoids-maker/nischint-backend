// Safety Score Screen
import { useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  TextInput, ActivityIndicator, Alert, Share,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { safetyScoreService } from '@/services/endpoints';
import { colors, spacing, fontSize, radius, shadows, scoreColor, scoreLabel } from '@/theme';

type ScoreTab = 'location' | 'route' | 'journey';

const SIGNALS: Record<string, { label: string; icon: string }> = {
  zone_risk: { label: 'Zone Risk', icon: 'location' },
  dynamic_risk: { label: 'Dynamic Risk', icon: 'pulse' },
  incident_density: { label: 'Incident Density', icon: 'warning' },
  route_exposure: { label: 'Route Exposure', icon: 'navigate' },
  time_risk: { label: 'Time Risk', icon: 'time' },
};

export default function SafetyScoreScreen() {
  const [tab, setTab] = useState<ScoreTab>('location');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any>(null);

  // Location inputs
  const [lat, setLat] = useState('12.9716');
  const [lng, setLng] = useState('77.5946');

  // Route inputs
  const [oLat, setOLat] = useState('12.9716');
  const [oLng, setOLng] = useState('77.5946');
  const [dLat, setDLat] = useState('12.9352');
  const [dLng, setDLng] = useState('77.6245');

  // Journey input
  const [sessionId, setSessionId] = useState('');

  const calculateLocation = async () => {
    setLoading(true);
    try {
      const res = await safetyScoreService.getLocationScore(parseFloat(lat), parseFloat(lng));
      setResult({ type: 'location', data: res.data });
    } catch (e: any) {
      Alert.alert('Error', e.response?.data?.detail || 'Failed to calculate');
    }
    setLoading(false);
  };

  const calculateRoute = async () => {
    setLoading(true);
    try {
      const res = await safetyScoreService.getRouteScore(
        { lat: parseFloat(oLat), lng: parseFloat(oLng) },
        { lat: parseFloat(dLat), lng: parseFloat(dLng) },
      );
      setResult({ type: 'route', data: res.data });
    } catch (e: any) {
      Alert.alert('Error', e.response?.data?.detail || 'Failed to calculate');
    }
    setLoading(false);
  };

  const calculateJourney = async () => {
    if (!sessionId.trim()) { Alert.alert('Error', 'Enter a session ID'); return; }
    setLoading(true);
    try {
      const res = await safetyScoreService.getJourneyScore(sessionId.trim());
      setResult({ type: 'journey', data: res.data });
    } catch (e: any) {
      Alert.alert('Error', e.response?.data?.detail || 'Failed to calculate');
    }
    setLoading(false);
  };

  const shareScore = async () => {
    if (!result?.data?.score) return;
    const score = result.data.score.toFixed(1);
    const label = scoreLabel(result.data.score);
    try {
      await Share.share({
        message: `My NISCHINT Safety Score: ${score}/10 (${label}). Check your area's safety at nischint.care`,
      });
    } catch {}
  };

  const switchTab = (t: ScoreTab) => {
    setTab(t);
    setResult(null);
  };

  return (
    <SafeAreaView style={styles.safe} testID="safety-score-screen">
      <ScrollView style={styles.scroll} contentContainerStyle={styles.content}>
        <Text style={styles.title}>Safety Score</Text>
        <Text style={styles.subtitle}>Check safety ratings for any location, route, or journey</Text>

        {/* Tabs */}
        <View style={styles.tabs}>
          {(['location', 'route', 'journey'] as ScoreTab[]).map((t) => (
            <TouchableOpacity
              key={t}
              style={[styles.tab, tab === t && styles.tabActive]}
              onPress={() => switchTab(t)}
              testID={`score-tab-${t}`}
            >
              <Text style={[styles.tabText, tab === t && styles.tabTextActive]}>
                {t.charAt(0).toUpperCase() + t.slice(1)}
              </Text>
            </TouchableOpacity>
          ))}
        </View>

        {/* Input Forms */}
        {tab === 'location' && (
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Location Score</Text>
            <View style={styles.coordRow}>
              <CoordInput label="Latitude" value={lat} onChange={setLat} testID="loc-lat" />
              <CoordInput label="Longitude" value={lng} onChange={setLng} testID="loc-lng" />
            </View>
            <CalcButton loading={loading} onPress={calculateLocation} testID="calc-location-btn" />
          </View>
        )}

        {tab === 'route' && (
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Route Score</Text>
            <Text style={styles.inputLabel}>Origin</Text>
            <View style={styles.coordRow}>
              <CoordInput label="Lat" value={oLat} onChange={setOLat} testID="route-olat" />
              <CoordInput label="Lng" value={oLng} onChange={setOLng} testID="route-olng" />
            </View>
            <Text style={styles.inputLabel}>Destination</Text>
            <View style={styles.coordRow}>
              <CoordInput label="Lat" value={dLat} onChange={setDLat} testID="route-dlat" />
              <CoordInput label="Lng" value={dLng} onChange={setDLng} testID="route-dlng" />
            </View>
            <CalcButton loading={loading} onPress={calculateRoute} testID="calc-route-btn" />
          </View>
        )}

        {tab === 'journey' && (
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Journey Score</Text>
            <TextInput
              style={styles.fullInput}
              placeholder="Enter Session ID"
              placeholderTextColor={colors.textMuted}
              value={sessionId}
              onChangeText={setSessionId}
              testID="journey-session-input"
            />
            <CalcButton loading={loading} onPress={calculateJourney} testID="calc-journey-btn" />
          </View>
        )}

        {/* Results */}
        {result && <ScoreResult data={result} onShare={shareScore} />}
      </ScrollView>
    </SafeAreaView>
  );
}

function CoordInput({ label, value, onChange, testID }: any) {
  return (
    <View style={{ flex: 1 }}>
      <Text style={styles.coordLabel}>{label}</Text>
      <TextInput
        style={styles.input}
        value={value}
        onChangeText={onChange}
        keyboardType="numeric"
        placeholderTextColor={colors.textMuted}
        testID={testID}
      />
    </View>
  );
}

function CalcButton({ loading, onPress, testID }: any) {
  return (
    <TouchableOpacity
      style={[styles.calcBtn, loading && styles.btnDisabled]}
      onPress={onPress}
      disabled={loading}
      testID={testID}
    >
      {loading ? <ActivityIndicator color={colors.white} /> : (
        <>
          <Ionicons name="calculator" size={18} color={colors.white} />
          <Text style={styles.calcBtnText}>Calculate</Text>
        </>
      )}
    </TouchableOpacity>
  );
}

function ScoreResult({ data, onShare }: { data: any; onShare: () => void }) {
  const score = data.data?.score ?? 0;
  const color = scoreColor(score);
  const label = scoreLabel(score);

  return (
    <View style={styles.resultCard} testID="score-result">
      {/* Score Gauge */}
      <View style={[styles.gaugeCircle, { borderColor: color }]}>
        <Text style={[styles.gaugeScore, { color }]}>{score.toFixed(1)}</Text>
        <Text style={styles.gaugeOf}>/10</Text>
      </View>
      <Text style={[styles.gaugeLabel, { color }]}>{label}</Text>

      {/* Metadata */}
      {data.data?.percentile && (
        <Text style={styles.percentile}>
          Safer than {data.data.percentile}% of nearby areas
        </Text>
      )}

      {data.data?.trend && (
        <View style={styles.metaRow}>
          <Ionicons
            name={data.data.trend === 'rising' ? 'trending-up' : data.data.trend === 'falling' ? 'trending-down' : 'remove'}
            size={16}
            color={data.data.trend === 'rising' ? colors.safe : data.data.trend === 'falling' ? colors.critical : colors.textMuted}
          />
          <Text style={styles.metaText}>Trend: {data.data.trend}</Text>
        </View>
      )}

      {data.data?.night_score != null && (
        <View style={styles.metaRow}>
          <Ionicons name="moon" size={16} color={colors.accent} />
          <Text style={styles.metaText}>Night Score: {data.data.night_score.toFixed(1)}/10</Text>
        </View>
      )}

      {/* Signal Breakdown */}
      {data.data?.signals && (
        <View style={styles.signalSection}>
          <Text style={styles.signalTitle}>Signal Breakdown</Text>
          {Object.entries(data.data.signals).map(([key, val]: any) => {
            const sig = SIGNALS[key];
            if (!sig) return null;
            return (
              <View key={key} style={styles.signalRow}>
                <Ionicons name={sig.icon as any} size={14} color={colors.textMuted} />
                <Text style={styles.signalLabel}>{sig.label}</Text>
                <View style={styles.signalBar}>
                  <View style={[styles.signalFill, { width: `${(val.normalized || 0) * 100}%`, backgroundColor: scoreColor(10 - (val.normalized || 0) * 10) }]} />
                </View>
                <Text style={styles.signalVal}>{((val.normalized || 0) * 100).toFixed(0)}%</Text>
              </View>
            );
          })}
        </View>
      )}

      {/* Route-specific */}
      {data.type === 'route' && data.data?.risk_zones_crossed != null && (
        <View style={styles.routeMeta}>
          <MetaPill label="Risk Zones" value={data.data.risk_zones_crossed} />
          <MetaPill label="Max Risk" value={data.data.max_risk} />
          <MetaPill label="Samples" value={data.data.sample_points} />
        </View>
      )}

      {/* Journey-specific */}
      {data.type === 'journey' && (
        <View style={styles.routeMeta}>
          <MetaPill label="Base Score" value={data.data.base_score?.toFixed(1)} />
          <MetaPill label="Penalty" value={data.data.total_penalty?.toFixed(1)} />
          <MetaPill label="Alerts" value={data.data.alert_count} />
        </View>
      )}

      {/* Share */}
      <TouchableOpacity style={styles.shareBtn} onPress={onShare} testID="share-score-btn">
        <Ionicons name="share-social" size={18} color={colors.primary} />
        <Text style={styles.shareBtnText}>Share My Score</Text>
      </TouchableOpacity>
    </View>
  );
}

function MetaPill({ label, value }: { label: string; value: any }) {
  return (
    <View style={styles.metaPill}>
      <Text style={styles.metaPillLabel}>{label}</Text>
      <Text style={styles.metaPillValue}>{String(value)}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  scroll: { flex: 1 },
  content: { padding: spacing.xl, paddingBottom: spacing['5xl'] },
  title: { fontSize: fontSize['2xl'], fontWeight: '800', color: colors.textPrimary },
  subtitle: { fontSize: fontSize.sm, color: colors.textSecondary, marginBottom: spacing.xl },
  tabs: { flexDirection: 'row', gap: spacing.sm, marginBottom: spacing.xl },
  tab: { flex: 1, paddingVertical: spacing.md, borderRadius: radius.lg, backgroundColor: colors.bgCard, alignItems: 'center', borderWidth: 1, borderColor: colors.border },
  tabActive: { backgroundColor: colors.primary + '20', borderColor: colors.primary },
  tabText: { fontSize: fontSize.sm, fontWeight: '600', color: colors.textMuted },
  tabTextActive: { color: colors.primary },
  card: { backgroundColor: colors.bgCard, borderRadius: radius.xl, padding: spacing.xl, borderWidth: 1, borderColor: colors.border, ...shadows.md },
  cardTitle: { fontSize: fontSize.lg, fontWeight: '700', color: colors.textPrimary, marginBottom: spacing.lg },
  inputLabel: { fontSize: fontSize.sm, fontWeight: '600', color: colors.textSecondary, marginTop: spacing.lg, marginBottom: spacing.sm },
  coordRow: { flexDirection: 'row', gap: spacing.md },
  coordLabel: { fontSize: fontSize.xs, color: colors.textMuted, marginBottom: 4 },
  input: { backgroundColor: colors.bgInput, borderRadius: radius.md, paddingHorizontal: spacing.md, height: 44, color: colors.textPrimary, fontSize: fontSize.md, borderWidth: 1, borderColor: colors.border },
  fullInput: { backgroundColor: colors.bgInput, borderRadius: radius.md, paddingHorizontal: spacing.md, height: 44, color: colors.textPrimary, fontSize: fontSize.md, borderWidth: 1, borderColor: colors.border },
  calcBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: spacing.sm, backgroundColor: colors.primary, borderRadius: radius.lg, height: 48, marginTop: spacing.xl },
  calcBtnText: { color: colors.white, fontSize: fontSize.md, fontWeight: '700' },
  btnDisabled: { opacity: 0.6 },
  resultCard: { backgroundColor: colors.bgCard, borderRadius: radius.xl, padding: spacing.xl, borderWidth: 1, borderColor: colors.border, marginTop: spacing.xl, alignItems: 'center', ...shadows.lg },
  gaugeCircle: { width: 120, height: 120, borderRadius: 60, borderWidth: 5, justifyContent: 'center', alignItems: 'center', backgroundColor: colors.bgElevated, marginBottom: spacing.md },
  gaugeScore: { fontSize: fontSize['3xl'], fontWeight: '900' },
  gaugeOf: { fontSize: fontSize.sm, color: colors.textMuted, marginTop: -4 },
  gaugeLabel: { fontSize: fontSize.xl, fontWeight: '700', marginBottom: spacing.sm },
  percentile: { fontSize: fontSize.sm, color: colors.textSecondary, marginBottom: spacing.md },
  metaRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.xs },
  metaText: { fontSize: fontSize.sm, color: colors.textSecondary, textTransform: 'capitalize' },
  signalSection: { width: '100%', marginTop: spacing.xl, borderTopWidth: 1, borderTopColor: colors.border, paddingTop: spacing.lg },
  signalTitle: { fontSize: fontSize.md, fontWeight: '700', color: colors.textPrimary, marginBottom: spacing.md },
  signalRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.md },
  signalLabel: { fontSize: fontSize.sm, color: colors.textSecondary, width: 100 },
  signalBar: { flex: 1, height: 6, borderRadius: 3, backgroundColor: colors.bgInput, overflow: 'hidden' },
  signalFill: { height: '100%', borderRadius: 3 },
  signalVal: { fontSize: fontSize.xs, color: colors.textMuted, width: 36, textAlign: 'right' },
  routeMeta: { flexDirection: 'row', gap: spacing.md, marginTop: spacing.lg, width: '100%' },
  metaPill: { flex: 1, backgroundColor: colors.bgElevated, borderRadius: radius.md, padding: spacing.md, alignItems: 'center' },
  metaPillLabel: { fontSize: fontSize.xs, color: colors.textMuted },
  metaPillValue: { fontSize: fontSize.md, fontWeight: '700', color: colors.textPrimary, marginTop: 2, textTransform: 'capitalize' },
  shareBtn: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginTop: spacing.xl, paddingVertical: spacing.md, paddingHorizontal: spacing.xl, borderRadius: radius.full, borderWidth: 1, borderColor: colors.primary },
  shareBtnText: { fontSize: fontSize.md, fontWeight: '600', color: colors.primary },
});
