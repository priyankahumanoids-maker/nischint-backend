// Predictive Alerts Screen
import { useState, useEffect, useCallback } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  RefreshControl, ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import * as Location from 'expo-location';
import { predictiveAlertService } from '@/services/endpoints';
import { colors, spacing, fontSize, radius, shadows, riskColor } from '@/theme';

// Fallback check points (used only if GPS is denied / unavailable).
// Center of India so the map is reasonably centered regardless of region.
const FALLBACK_POINTS = [
  { name: 'Area (GPS unavailable)', lat: 20.5937, lng: 78.9629, speed: 0, heading: 0 },
];

type CheckPoint = { name: string; lat: number; lng: number; speed: number; heading: number };

// Build 4 monitored points around the user's current location:
//   1. Current Area   — exact GPS
//   2. 1 km North
//   3. 1 km East
//   4. 1 km South-West
// 0.009° ≈ 1 km in latitude. Longitude is scaled by cos(lat) for accuracy.
function buildCheckPointsAround(lat: number, lng: number): CheckPoint[] {
  const dLat = 0.009;
  const dLng = 0.009 / Math.max(0.2, Math.cos((lat * Math.PI) / 180));
  return [
    { name: 'Current Area',    lat,               lng,               speed: 0,  heading: 0 },
    { name: '1 km North',      lat: lat + dLat,   lng,               speed: 0,  heading: 0 },
    { name: '1 km East',       lat,               lng: lng + dLng,   speed: 0,  heading: 90 },
    { name: '1 km South-West', lat: lat - dLat,   lng: lng - dLng,   speed: 0,  heading: 225 },
  ];
}

export default function AlertsScreen() {
  const [alerts, setAlerts] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [checkPoints, setCheckPoints] = useState<CheckPoint[]>(FALLBACK_POINTS);
  const [gpsReady, setGpsReady] = useState(false);

  // Fetch user's real GPS once on mount and build dynamic monitored points.
  const initLocation = useCallback(async () => {
    try {
      const { status } = await Location.requestForegroundPermissionsAsync();
      if (status !== 'granted') {
        setCheckPoints(FALLBACK_POINTS);
        setGpsReady(false);
        return;
      }
      const loc = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
      const pts = buildCheckPointsAround(loc.coords.latitude, loc.coords.longitude);
      setCheckPoints(pts);
      setGpsReady(true);
    } catch (e) {
      console.warn('[ALERTS] GPS init failed, using fallback:', (e as any)?.message || e);
      setCheckPoints(FALLBACK_POINTS);
      setGpsReady(false);
    }
  }, []);

  const fetchAlerts = useCallback(async (points: CheckPoint[]) => {
    setScanning(true);
    const newAlerts: any[] = [];
    for (const point of points) {
      try {
        const res = await predictiveAlertService.evaluateWithAlternative(
          point.lat, point.lng, point.speed, point.heading,
        );
        if (res.data?.alerts?.length > 0) {
          newAlerts.push(...res.data.alerts.map((a: any) => ({ ...a, checkpoint: point.name })));
        }
      } catch {}
    }
    setAlerts(newAlerts);
    setLoading(false);
    setScanning(false);
  }, []);

  // On mount: GPS first, then scan
  useEffect(() => {
    (async () => {
      await initLocation();
    })();
  }, [initLocation]);

  // Once checkPoints are ready, run a scan
  useEffect(() => {
    if (checkPoints.length > 0) {
      fetchAlerts(checkPoints);
    }
  }, [checkPoints, fetchAlerts]);

  const onRefresh = async () => {
    setRefreshing(true);
    await initLocation();
    await fetchAlerts(checkPoints);
    setRefreshing(false);
  };

  const handleScanPress = () => fetchAlerts(checkPoints);

  return (
    <SafeAreaView style={styles.safe} testID="alerts-screen">
      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />}
      >
        <Text style={styles.title}>Predictive Alerts</Text>
        <Text style={styles.subtitle}>
          AI-powered risk predictions for nearby areas
        </Text>

        {/* Scan Button */}
        <TouchableOpacity
          style={[styles.scanBtn, scanning && styles.btnDisabled]}
          onPress={handleScanPress}
          disabled={scanning}
          testID="scan-alerts-btn"
        >
          {scanning ? (
            <ActivityIndicator color={colors.white} />
          ) : (
            <>
              <Ionicons name="radio" size={20} color={colors.white} />
              <Text style={styles.scanBtnText}>Scan Area</Text>
            </>
          )}
        </TouchableOpacity>

        {/* Summary */}
        <View style={styles.summaryRow}>
          <View style={styles.summaryItem}>
            <Text style={styles.summaryNum}>{alerts.length}</Text>
            <Text style={styles.summaryLabel}>Active Alerts</Text>
          </View>
          <View style={styles.summaryItem}>
            <Text style={[styles.summaryNum, { color: colors.critical }]}>
              {alerts.filter(a => a.severity === 'high' || a.severity === 'critical').length}
            </Text>
            <Text style={styles.summaryLabel}>High Risk</Text>
          </View>
          <View style={styles.summaryItem}>
            <Text style={styles.summaryNum}>{checkPoints.length}</Text>
            <Text style={styles.summaryLabel}>Areas Checked</Text>
          </View>
        </View>

        {!gpsReady && (
          <View style={styles.gpsBanner}>
            <Ionicons name="location-outline" size={16} color={colors.warning} />
            <Text style={styles.gpsBannerText}>
              Location unavailable — enable location to scan your area.
            </Text>
          </View>
        )}

        {/* Alert Cards */}
        {loading ? (
          <View style={styles.loadingBox}>
            <ActivityIndicator size="large" color={colors.primary} />
            <Text style={styles.loadingText}>Scanning nearby areas...</Text>
          </View>
        ) : alerts.length === 0 ? (
          <View style={styles.emptyCard}>
            <Ionicons name="shield-checkmark" size={48} color={colors.safe} />
            <Text style={styles.emptyTitle}>All Clear</Text>
            <Text style={styles.emptyDesc}>No safety alerts in your area right now</Text>
          </View>
        ) : (
          alerts.map((alert, i) => <AlertCard key={i} alert={alert} index={i} />)
        )}

        {/* Check Points */}
        <Text style={styles.sectionTitle}>Monitored Areas</Text>
        {checkPoints.map((p, i) => (
          <View key={i} style={styles.checkpointCard}>
            <Ionicons name="location" size={18} color={colors.primary} />
            <View style={styles.checkpointInfo}>
              <Text style={styles.checkpointName}>{p.name}</Text>
              <Text style={styles.checkpointCoords}>{p.lat.toFixed(4)}, {p.lng.toFixed(4)}</Text>
            </View>
            <Ionicons name="checkmark-circle" size={18} color={colors.safe} />
          </View>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

function AlertCard({ alert, index }: { alert: any; index: number }) {
  const severityColor = riskColor(alert.severity || 'moderate');
  return (
    <View style={[styles.alertCard, { borderLeftColor: severityColor, borderLeftWidth: 3 }]} testID={`alert-card-${index}`}>
      <View style={styles.alertHeader}>
        <View style={[styles.severityBadge, { backgroundColor: severityColor + '20' }]}>
          <Text style={[styles.severityText, { color: severityColor }]}>
            {(alert.severity || 'unknown').toUpperCase()}
          </Text>
        </View>
        {alert.checkpoint && (
          <Text style={styles.alertCheckpoint}>{alert.checkpoint}</Text>
        )}
      </View>
      <Text style={styles.alertType}>{alert.type || alert.alert_type || 'Risk Alert'}</Text>
      {alert.message && <Text style={styles.alertMsg}>{alert.message}</Text>}
      {alert.distance_meters != null && (
        <Text style={styles.alertDist}>{Math.round(alert.distance_meters)}m ahead</Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  scroll: { flex: 1 },
  content: { padding: spacing.xl, paddingBottom: spacing['5xl'] },
  title: { fontSize: fontSize['2xl'], fontWeight: '800', color: colors.textPrimary },
  subtitle: { fontSize: fontSize.sm, color: colors.textSecondary, marginBottom: spacing.xl },
  scanBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: spacing.sm, backgroundColor: colors.primary, borderRadius: radius.lg, height: 48, marginBottom: spacing.xl },
  scanBtnText: { color: colors.white, fontSize: fontSize.md, fontWeight: '700' },
  btnDisabled: { opacity: 0.6 },
  summaryRow: { flexDirection: 'row', gap: spacing.md, marginBottom: spacing.xl },
  summaryItem: { flex: 1, backgroundColor: colors.bgCard, borderRadius: radius.lg, padding: spacing.lg, alignItems: 'center', borderWidth: 1, borderColor: colors.border },
  summaryNum: { fontSize: fontSize['2xl'], fontWeight: '800', color: colors.textPrimary },
  summaryLabel: { fontSize: fontSize.xs, color: colors.textMuted, marginTop: 2 },
  loadingBox: { backgroundColor: colors.bgCard, borderRadius: radius.xl, padding: spacing['4xl'], alignItems: 'center', gap: spacing.md },
  loadingText: { fontSize: fontSize.md, color: colors.textSecondary },
  emptyCard: { backgroundColor: colors.bgCard, borderRadius: radius.xl, padding: spacing['4xl'], alignItems: 'center', gap: spacing.md, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.xl },
  emptyTitle: { fontSize: fontSize.xl, fontWeight: '700', color: colors.safe },
  emptyDesc: { fontSize: fontSize.sm, color: colors.textSecondary },
  alertCard: { backgroundColor: colors.bgCard, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md },
  alertHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: spacing.sm },
  severityBadge: { paddingHorizontal: spacing.md, paddingVertical: 2, borderRadius: radius.full },
  severityText: { fontSize: fontSize.xs, fontWeight: '800', letterSpacing: 1 },
  alertCheckpoint: { fontSize: fontSize.xs, color: colors.textMuted },
  alertType: { fontSize: fontSize.md, fontWeight: '700', color: colors.textPrimary, marginBottom: 4, textTransform: 'capitalize' },
  alertMsg: { fontSize: fontSize.sm, color: colors.textSecondary },
  alertDist: { fontSize: fontSize.xs, color: colors.textMuted, marginTop: spacing.xs },
  sectionTitle: { fontSize: fontSize.lg, fontWeight: '700', color: colors.textPrimary, marginTop: spacing.xl, marginBottom: spacing.md },
  checkpointCard: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, backgroundColor: colors.bgCard, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm },
  checkpointInfo: { flex: 1 },
  checkpointName: { fontSize: fontSize.sm, fontWeight: '600', color: colors.textPrimary },
  checkpointCoords: { fontSize: fontSize.xs, color: colors.textMuted },
  gpsBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    backgroundColor: colors.warning + '15',
    borderColor: colors.warning + '40',
    borderWidth: 1,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    marginBottom: spacing.lg,
  },
  gpsBannerText: {
    flex: 1,
    fontSize: fontSize.xs,
    color: colors.warning,
  },
});
