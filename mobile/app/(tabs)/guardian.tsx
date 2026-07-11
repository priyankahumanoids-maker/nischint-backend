// Guardian / Share Tab — Guardian Family Dashboard for guardians, Share Safety for users
import { useState, useEffect, useCallback } from 'react';
import React from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  RefreshControl, Alert, Share, ActivityIndicator, TextInput,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect } from '@react-navigation/native';
import { useAuthStore } from '@/stores/authStore';
import { guardianDashboardService, guardianService, safetyScoreService, locationShareService, guardianLinkService } from '@/services/endpoints';
import { colors, spacing, fontSize, radius, shadows, riskColor, scoreColor, scoreLabel } from '@/theme';
import { ImpactBadge } from '@/components/guardian/ImpactBadge';

export default function GuardianScreen() {
  const { user, logout } = useAuthStore();
  const isGuardian = user?.role === 'guardian';

  return isGuardian ? <GuardianDashboard /> : <ShareSafety />;
}

// ===== GUARDIAN DASHBOARD =====
function GuardianDashboard() {
  const { user, logout } = useAuthStore();
  const [lovedOnes, setLovedOnes] = useState<any[]>([]);
  const [alerts, setAlerts] = useState<any[]>([]);
  const [sessions, setSessions] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [tab, setTab] = useState<'overview' | 'alerts' | 'history' | 'settings'>('overview');
  const [showLinkModal, setShowLinkModal] = useState(false);
  const [linkCode, setLinkCode] = useState('');
  const [linkLoading, setLinkLoading] = useState(false);
  const [linkError, setLinkError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const [loRes, alRes, sesRes] = await Promise.all([
        guardianDashboardService.getLovedOnes().catch((err: any) => { console.log("LO ERROR:", err?.message, err?.response?.status); return { data: {} }; }),
        guardianDashboardService.getAlerts(20).catch(() => ({ data: [] })),
        guardianDashboardService.getSessions().catch(() => ({ data: [] })),
      ]);

      const loData = loRes.data || {};
      const monitored = loData.monitored_users || loData.loved_ones || [];
      setLovedOnes(Array.isArray(monitored) ? monitored : []);
      setAlerts(Array.isArray(alRes.data) ? alRes.data : alRes.data?.alerts || []);
      setSessions(Array.isArray(sesRes.data) ? sesRes.data : sesRes.data?.sessions || []);
    } catch (e: any) {
      console.log("FETCH_ERROR:", e?.message);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    const role = user?.role;
    if (role === 'guardian') {
      fetchData();
    }
  }, [user?.role]);

  useFocusEffect(
    React.useCallback(() => {
      if (user?.role === 'guardian') {
        fetchData();
      }
    }, [user?.role])
  );

  const onRefresh = async () => { setRefreshing(true); await fetchData(); setRefreshing(false); };

  const requestCheck = async (userId: string) => {
    try {
      await guardianDashboardService.requestCheck(userId);
      Alert.alert('Check Requested', 'A safety check has been sent to your loved one.');
    } catch (e: any) {
      Alert.alert('Error', e.response?.data?.detail || 'Failed to request check');
    }
  };

  const handleLinkChild = async () => {
    if (linkCode.length !== 6) { setLinkError('Enter a 6-digit code'); return; }
    setLinkLoading(true);
    setLinkError(null);
    try {
      await guardianLinkService.linkChild(linkCode);
      setShowLinkModal(false);
      setLinkCode('');
      setLinkError(null);
      fetchData();
    } catch (e: any) {
      const status = e.response?.status;
      if (status === 400) setLinkError('Code expired or invalid — try again');
      else if (status === 409) setLinkError('Child already linked');
      else if (status === 403) setLinkError('Cannot link from a child account');
      else setLinkError(e.response?.data?.detail || 'Something went wrong — try again');
    }
    setLinkLoading(false);
  };

  return (
    <SafeAreaView style={styles.safe} testID="guardian-dashboard">
      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />}
      >
        <View style={styles.headerRow}>
          <View>
            <Text style={styles.title}>Family Safety</Text>
            <Text style={styles.subtitle}>Monitor your loved ones</Text>
            <ImpactBadge />
          </View>
          <TouchableOpacity onPress={logout} style={styles.logoutBtn} testID="logout-btn">
            <Ionicons name="log-out-outline" size={22} color={colors.textMuted} />
          </TouchableOpacity>
        </View>

        {/* Tabs */}
        <View style={styles.tabs}>
          {(['overview', 'alerts', 'history', 'settings'] as const).map((t) => (
            <TouchableOpacity
              key={t} style={[styles.tab, tab === t && styles.tabActive]}
              onPress={() => setTab(t)} testID={`guardian-tab-${t}`}
            >
              <Text style={[styles.tabText, tab === t && styles.tabTextActive]}>
                {t.charAt(0).toUpperCase() + t.slice(1)}
              </Text>
            </TouchableOpacity>
          ))}
        </View>

        {loading ? (
          <ActivityIndicator size="large" color={colors.primary} style={{ marginTop: spacing['4xl'] }} />
        ) : (
          <>
            {tab === 'overview' && (
              <>
                {/* Active Sessions */}
                {sessions.length > 0 && (
                  <>
                    <Text style={styles.sectionTitle}>Active Journeys</Text>
                    {sessions.map((s: any, i: number) => (
                      <View key={i} style={styles.sessionCard} testID={`session-card-${i}`}>
                        <View style={styles.liveRow}>
                          <View style={styles.liveDot} />
                          <Text style={styles.liveText}>LIVE</Text>
                        </View>
                        <Text style={styles.sessionId}>Session: {s.session_id?.slice(0, 12)}...</Text>
                        <Text style={styles.sessionTime}>Started: {formatTime(s.start_time)}</Text>
                      </View>
                    ))}
                  </>
                )}

                {/* Loved Ones */}
                <Text style={styles.sectionTitle}>Loved Ones</Text>
                {lovedOnes.length === 0 && (
                  <View style={styles.emptyCard} testID="empty-loved-ones">
                    <Ionicons name="people-outline" size={40} color={colors.textMuted} />
                    <Text style={styles.emptyText}>No linked loved ones yet</Text>
                    {!showLinkModal ? (
                      <TouchableOpacity
                        style={styles.linkButton}
                        onPress={() => setShowLinkModal(true)}
                        testID="link-child-btn"
                      >
                        <Ionicons name="link" size={18} color={colors.white} />
                        <Text style={styles.linkButtonText}>Link a Child</Text>
                      </TouchableOpacity>
                    ) : (
                      <View style={styles.linkInputWrap} testID="link-input-section">
                        <TextInput
                          style={styles.linkInput}
                          value={linkCode}
                          onChangeText={(t) => { setLinkCode(t.replace(/\D/g, '').slice(0, 6)); setLinkError(null); }}
                          placeholder="Enter 6-digit code"
                          placeholderTextColor={colors.textMuted}
                          keyboardType="numeric"
                          maxLength={6}
                          testID="link-code-input"
                        />
                        <View style={styles.linkBtnRow}>
                          <TouchableOpacity style={styles.linkCancelBtn} onPress={() => { setShowLinkModal(false); setLinkCode(''); setLinkError(null); }}>
                            <Text style={styles.linkCancelText}>Cancel</Text>
                          </TouchableOpacity>
                          <TouchableOpacity
                            style={[styles.linkSubmitBtn, linkLoading && { opacity: 0.5 }]}
                            onPress={handleLinkChild}
                            disabled={linkLoading}
                            testID="link-submit-btn"
                          >
                            <Text style={styles.linkSubmitText}>{linkLoading ? 'Linking...' : 'Link'}</Text>
                          </TouchableOpacity>
                        </View>
                        {linkError && <Text style={styles.linkError} testID="link-error-text">{linkError}</Text>}
                      </View>
                    )}
                  </View>
                )}

                {lovedOnes.length > 0 && (
                  <>
                    {/* Secondary link action when list is populated */}
                    {!showLinkModal ? (
                      <TouchableOpacity
                        style={styles.linkSecondaryBtn}
                        onPress={() => { setShowLinkModal(true); setLinkError(null); }}
                        testID="link-child-secondary-btn"
                      >
                        <Ionicons name="add-circle-outline" size={16} color={colors.primary} />
                        <Text style={styles.linkSecondaryText}>Link a Child</Text>
                      </TouchableOpacity>
                    ) : (
                      <View style={[styles.linkInputWrap, { marginBottom: spacing.md }]} testID="link-input-section-secondary">
                        <TextInput
                          style={styles.linkInput}
                          value={linkCode}
                          onChangeText={(t) => { setLinkCode(t.replace(/\D/g, '').slice(0, 6)); setLinkError(null); }}
                          placeholder="Enter 6-digit code"
                          placeholderTextColor={colors.textMuted}
                          keyboardType="numeric"
                          maxLength={6}
                          testID="link-code-input-secondary"
                        />
                        <View style={styles.linkBtnRow}>
                          <TouchableOpacity style={styles.linkCancelBtn} onPress={() => { setShowLinkModal(false); setLinkCode(''); setLinkError(null); }}>
                            <Text style={styles.linkCancelText}>Cancel</Text>
                          </TouchableOpacity>
                          <TouchableOpacity
                            style={[styles.linkSubmitBtn, linkLoading && { opacity: 0.5 }]}
                            onPress={handleLinkChild}
                            disabled={linkLoading}
                            testID="link-submit-btn-secondary"
                          >
                            <Text style={styles.linkSubmitText}>{linkLoading ? 'Linking...' : 'Link'}</Text>
                          </TouchableOpacity>
                        </View>
                        {linkError && <Text style={styles.linkError}>{linkError}</Text>}
                      </View>
                    )}

                    {lovedOnes.map((person: any, i: number) => {
                      const statusCfg = getStatusBadge(person.status);
                      return (
                        <View key={i} style={[styles.personCard, person.status === 'EMERGENCY' && styles.personCardEmergency]} testID={`loved-one-${i}`}>
                          <View style={[styles.personAvatar, { backgroundColor: statusCfg.color + '20' }]}>
                            <Ionicons name="person" size={24} color={statusCfg.color} />
                          </View>
                          <View style={styles.personInfo}>
                            <Text style={styles.personName}>{person.name || person.full_name || 'User'}</Text>
                            <View style={[styles.statusPill, { backgroundColor: statusCfg.bg }]} testID={`status-badge-${i}`}>
                              <View style={[styles.statusDot, { backgroundColor: statusCfg.color }]} />
                              <Text style={[styles.statusLabel, { color: statusCfg.color }]}>{statusCfg.label}</Text>
                            </View>
                            <LocationIndicator locationType={person.location_type} lastUpdated={person.last_updated} testID={`location-${i}`} />
                          </View>
                          <TouchableOpacity
                            style={styles.checkBtn}
                            onPress={() => requestCheck(person.user_id || person.id)}
                            testID={`check-btn-${i}`}
                          >
                            <Text style={styles.checkBtnText}>Check In</Text>
                          </TouchableOpacity>
                        </View>
                      );
                    })}
                  </>
                )}
              </>
            )}

            {tab === 'alerts' && (
              <>
                <Text style={styles.sectionTitle}>Recent Alerts</Text>
                {alerts.length === 0 ? (
                  <View style={styles.emptyCard}>
                    <Ionicons name="shield-checkmark" size={40} color={colors.safe} />
                    <Text style={styles.emptyText}>No alerts</Text>
                  </View>
                ) : (
                  alerts.map((alert: any, i: number) => (
                    <View key={i} style={styles.alertCard} testID={`alert-item-${i}`}>
                      <View style={[styles.alertDot, { backgroundColor: riskColor(alert.severity || 'moderate') }]} />
                      <View style={styles.alertInfo}>
                        <Text style={styles.alertType}>{alert.type || 'Alert'}</Text>
                        <Text style={styles.alertTime}>{formatTime(alert.created_at || alert.timestamp)}</Text>
                      </View>
                    </View>
                  ))
                )}
              </>
            )}

            {tab === 'history' && (
              <>
                <Text style={styles.sectionTitle}>Journey History</Text>
                <HistorySection />
              </>
            )}

            {tab === 'settings' && (
              <View style={styles.settingsSection}>
                <Text style={styles.sectionTitle}>Account</Text>
                <View style={styles.settingCard}>
                  <Ionicons name="person" size={20} color={colors.primary} />
                  <Text style={styles.settingLabel}>{user?.full_name || 'User'}</Text>
                </View>
                <View style={styles.settingCard}>
                  <Ionicons name="mail" size={20} color={colors.primary} />
                  <Text style={styles.settingLabel}>{user?.email || ''}</Text>
                </View>
                <View style={styles.settingCard}>
                  <Ionicons name="shield" size={20} color={colors.primary} />
                  <Text style={styles.settingLabel}>Role: {user?.role}</Text>
                </View>
                <TouchableOpacity
                  style={styles.logoutFullBtn}
                  onPress={logout}
                  testID="settings-logout-btn"
                >
                  <Ionicons name="log-out" size={20} color={colors.critical} />
                  <Text style={styles.logoutFullText}>Sign Out</Text>
                </TouchableOpacity>
              </View>
            )}
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function HistorySection() {
  const [history, setHistory] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    guardianDashboardService.getHistory()
      .then((res) => setHistory(Array.isArray(res.data) ? res.data : res.data?.sessions || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <ActivityIndicator color={colors.primary} />;
  if (history.length === 0) {
    return (
      <View style={styles.emptyCard}>
        <Ionicons name="time-outline" size={40} color={colors.textMuted} />
        <Text style={styles.emptyText}>No journey history</Text>
      </View>
    );
  }

  return (
    <>
      {history.map((h: any, i: number) => (
        <View key={i} style={styles.historyCard} testID={`history-item-${i}`}>
          <Ionicons name="navigate-circle" size={20} color={colors.primary} />
          <View style={styles.historyInfo}>
            <Text style={styles.historyId}>{h.session_id?.slice(0, 12)}...</Text>
            <Text style={styles.historyTime}>
              {formatTime(h.start_time)} — {h.end_time ? formatTime(h.end_time) : 'ongoing'}
            </Text>
          </View>
          <Text style={[styles.historyStatus, { color: h.status === 'completed' ? colors.safe : colors.warning }]}>
            {h.status || 'unknown'}
          </Text>
        </View>
      ))}
    </>
  );
}

// ===== SHARE SAFETY =====
function ShareSafety() {
  const { user, logout } = useAuthStore();
  const [score, setScore] = useState<any>(null);

  useEffect(() => {
    safetyScoreService.getLocationScore(12.9716, 77.5946)
      .then(res => setScore(res.data))
      .catch(() => {});
  }, []);

  const shareMyStatus = async () => {
    try {
      const res = await locationShareService.createShare(4);
      const trackingUrl = `https://nischint.care${res.data.tracking_url}`;
      const s = score?.score?.toFixed(1) || '?';
      await Share.share({
        message: `Track my live location on NISCHINT:\n${trackingUrl}\n\nArea safety score: ${s}/10 (${scoreLabel(score?.score || 0)})`,
      });
    } catch {
      const s = score?.score?.toFixed(1) || '?';
      await Share.share({
        message: `I'm using NISCHINT for safety monitoring. My current area safety score: ${s}/10 (${scoreLabel(score?.score || 0)}). Stay safe! nischint.care`,
      });
    }
  };

  return (
    <SafeAreaView style={styles.safe} testID="share-safety-screen">
      <ScrollView style={styles.scroll} contentContainerStyle={styles.content}>
        <View style={styles.headerRow}>
          <View>
            <Text style={styles.title}>Share Safety</Text>
            <Text style={styles.subtitle}>Let your network know you're safe</Text>
          </View>
          <TouchableOpacity onPress={logout} style={styles.logoutBtn} testID="logout-btn">
            <Ionicons name="log-out-outline" size={22} color={colors.textMuted} />
          </TouchableOpacity>
        </View>

        {/* Share Card */}
        <View style={styles.shareCard} testID="share-card">
          <View style={styles.shareLogo}>
            <Ionicons name="shield-checkmark" size={32} color={colors.primary} />
          </View>
          <Text style={styles.shareTitle}>NISCHINT</Text>
          {score && (
            <>
              <View style={[styles.shareScoreCircle, { borderColor: scoreColor(score.score) }]}>
                <Text style={[styles.shareScoreNum, { color: scoreColor(score.score) }]}>
                  {score.score.toFixed(1)}
                </Text>
                <Text style={styles.shareScoreOf}>/10</Text>
              </View>
              <Text style={[styles.shareLabel, { color: scoreColor(score.score) }]}>
                {scoreLabel(score.score)}
              </Text>
            </>
          )}
          <TouchableOpacity style={styles.shareSendBtn} onPress={shareMyStatus} testID="share-send-btn">
            <Ionicons name="share-social" size={20} color={colors.white} />
            <Text style={styles.shareSendText}>Share My Safety Status</Text>
          </TouchableOpacity>
        </View>

        {/* Guardian Management */}
        <Text style={styles.sectionTitle}>Your Guardians</Text>
        <View style={styles.emptyCard}>
          <Ionicons name="people-outline" size={40} color={colors.textMuted} />
          <Text style={styles.emptyText}>Guardian management coming soon</Text>
          <Text style={styles.emptyDesc}>Add trusted contacts who will receive your safety updates</Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

// ===== HELPERS =====
function relativeTime(isoStr: string | null): string {
  if (!isoStr) return '';
  const diff = Date.now() - new Date(isoStr).getTime();
  const sec = Math.floor(diff / 1000);
  if (sec < 60) return 'just now';
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  return `${Math.floor(hr / 24)}d ago`;
}

function getStatusBadge(status: string | null): { label: string; color: string; bg: string } {
  const s = (status || '').toUpperCase();
  if (s === 'EMERGENCY') return { label: 'EMERGENCY', color: '#EF4444', bg: '#EF444420' };
  if (s === 'LIVE_JOURNEY') return { label: 'Live Journey', color: '#3B82F6', bg: '#3B82F620' };
  if (s === 'CHECK_IN_PENDING') return { label: 'Check-in Pending', color: '#F59E0B', bg: '#F59E0B20' };
  if (s === 'HELP') return { label: 'Needs Help', color: '#EF4444', bg: '#EF444420' };
  return { label: 'Safe', color: '#22C55E', bg: '#22C55E20' };
}

function LocationIndicator({ locationType, lastUpdated, testID }: { locationType: string | null; lastUpdated: string | null; testID?: string }) {
  let dotColor = '#9CA3AF';
  let label = 'Location unavailable';
  if (locationType === 'live') { dotColor = '#22C55E'; label = 'Live'; }
  else if (locationType === 'emergency') { dotColor = '#EF4444'; label = 'Emergency location'; }
  else if (locationType === 'recent') { dotColor = '#F59E0B'; label = `Last seen · ${relativeTime(lastUpdated)}`; }
  else if (locationType === 'historical') { dotColor = '#9CA3AF'; label = `Last known · ${relativeTime(lastUpdated)}`; }
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 5, marginTop: 3 }} testID={testID}>
      {locationType && <View style={{ width: 7, height: 7, borderRadius: 3.5, backgroundColor: dotColor }} />}
      <Text style={{ fontSize: 11, color: colors.textSecondary }}>{label}</Text>
    </View>
  );
}

function formatTime(ts: string | null) {
  if (!ts) return '--';
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  scroll: { flex: 1 },
  content: { padding: spacing.xl, paddingBottom: spacing['5xl'] },
  headerRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: spacing.lg },
  title: { fontSize: fontSize['2xl'], fontWeight: '800', color: colors.textPrimary },
  subtitle: { fontSize: fontSize.sm, color: colors.textSecondary },
  logoutBtn: { padding: spacing.sm },
  tabs: { flexDirection: 'row', gap: spacing.xs, marginBottom: spacing.xl },
  tab: { flex: 1, paddingVertical: spacing.sm, borderRadius: radius.lg, backgroundColor: colors.bgCard, alignItems: 'center', borderWidth: 1, borderColor: colors.border },
  tabActive: { backgroundColor: colors.primary + '20', borderColor: colors.primary },
  tabText: { fontSize: fontSize.xs, fontWeight: '600', color: colors.textMuted },
  tabTextActive: { color: colors.primary },
  sectionTitle: { fontSize: fontSize.lg, fontWeight: '700', color: colors.textPrimary, marginBottom: spacing.md, marginTop: spacing.lg },
  sessionCard: { backgroundColor: colors.bgCard, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.safe + '30', marginBottom: spacing.md },
  liveRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.sm },
  liveDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.safe },
  liveText: { fontSize: fontSize.xs, fontWeight: '800', color: colors.safe, letterSpacing: 2 },
  sessionId: { fontSize: fontSize.sm, fontWeight: '600', color: colors.textPrimary },
  sessionTime: { fontSize: fontSize.xs, color: colors.textMuted, marginTop: 2 },
  personCard: { flexDirection: 'row', alignItems: 'center', backgroundColor: colors.bgCard, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md },
  personAvatar: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.primary + '20', justifyContent: 'center', alignItems: 'center', marginRight: spacing.md },
  personInfo: { flex: 1 },
  personName: { fontSize: fontSize.md, fontWeight: '700', color: colors.textPrimary },
  personStatus: { fontSize: fontSize.sm, color: colors.safe, marginTop: 2 },
  checkBtn: { backgroundColor: colors.primary + '20', paddingHorizontal: spacing.lg, paddingVertical: spacing.sm, borderRadius: radius.full },
  checkBtnText: { fontSize: fontSize.sm, fontWeight: '600', color: colors.primary },
  emptyCard: { backgroundColor: colors.bgCard, borderRadius: radius.xl, padding: spacing['3xl'], alignItems: 'center', gap: spacing.sm, borderWidth: 1, borderColor: colors.border },
  emptyText: { fontSize: fontSize.md, color: colors.textMuted },
  emptyDesc: { fontSize: fontSize.sm, color: colors.textMuted, textAlign: 'center' },
  alertCard: { flexDirection: 'row', alignItems: 'center', backgroundColor: colors.bgCard, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm },
  alertDot: { width: 8, height: 8, borderRadius: 4, marginRight: spacing.md },
  alertInfo: { flex: 1 },
  alertType: { fontSize: fontSize.sm, fontWeight: '600', color: colors.textPrimary, textTransform: 'capitalize' },
  alertTime: { fontSize: fontSize.xs, color: colors.textMuted },
  historyCard: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, backgroundColor: colors.bgCard, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm },
  historyInfo: { flex: 1 },
  historyId: { fontSize: fontSize.sm, fontWeight: '600', color: colors.textPrimary },
  historyTime: { fontSize: fontSize.xs, color: colors.textMuted },
  historyStatus: { fontSize: fontSize.xs, fontWeight: '700', textTransform: 'capitalize' },
  settingsSection: { gap: spacing.md },
  settingCard: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, backgroundColor: colors.bgCard, borderRadius: radius.md, padding: spacing.lg, borderWidth: 1, borderColor: colors.border },
  settingLabel: { fontSize: fontSize.md, color: colors.textPrimary },
  logoutFullBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: spacing.sm, backgroundColor: colors.critical + '15', borderRadius: radius.lg, padding: spacing.lg, marginTop: spacing.xl, borderWidth: 1, borderColor: colors.critical + '30' },
  logoutFullText: { fontSize: fontSize.md, fontWeight: '700', color: colors.critical },
  shareCard: { backgroundColor: colors.bgCard, borderRadius: radius.xl, padding: spacing['3xl'], alignItems: 'center', borderWidth: 1, borderColor: colors.border, ...shadows.lg, marginTop: spacing.lg },
  shareLogo: { marginBottom: spacing.md },
  shareTitle: { fontSize: fontSize.xl, fontWeight: '800', color: colors.textPrimary, letterSpacing: 3, marginBottom: spacing.xl },
  shareScoreCircle: { width: 100, height: 100, borderRadius: 50, borderWidth: 4, justifyContent: 'center', alignItems: 'center', backgroundColor: colors.bgElevated, marginBottom: spacing.md },
  shareScoreNum: { fontSize: fontSize['3xl'], fontWeight: '900' },
  shareScoreOf: { fontSize: fontSize.xs, color: colors.textMuted, marginTop: -4 },
  shareLabel: { fontSize: fontSize.lg, fontWeight: '700', marginBottom: spacing.xl },
  shareSendBtn: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, backgroundColor: colors.primary, borderRadius: radius.full, paddingHorizontal: spacing['2xl'], paddingVertical: spacing.md },
  shareSendText: { color: colors.white, fontSize: fontSize.md, fontWeight: '700' },
  linkButton: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, backgroundColor: colors.primary, paddingHorizontal: spacing.xl, paddingVertical: spacing.md, borderRadius: radius.lg, marginTop: spacing.md },
  linkButtonText: { fontSize: fontSize.md, fontWeight: '700', color: colors.white },
  linkSecondaryBtn: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs, alignSelf: 'flex-end', paddingVertical: spacing.xs, marginBottom: spacing.sm },
  linkSecondaryText: { fontSize: fontSize.sm, fontWeight: '600', color: colors.primary },
  linkInputWrap: { width: '100%', backgroundColor: colors.bgCard, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, gap: spacing.sm, marginTop: spacing.sm },
  linkInput: { backgroundColor: colors.bgElevated, borderRadius: radius.lg, paddingHorizontal: spacing.lg, paddingVertical: spacing.md, fontSize: 24, fontWeight: '700', color: colors.textPrimary, textAlign: 'center', letterSpacing: 8, borderWidth: 1, borderColor: colors.border },
  linkBtnRow: { flexDirection: 'row', gap: spacing.md },
  linkCancelBtn: { flex: 1, paddingVertical: spacing.md, alignItems: 'center', borderRadius: radius.lg, backgroundColor: colors.bgElevated, borderWidth: 1, borderColor: colors.border },
  linkCancelText: { fontSize: fontSize.md, fontWeight: '600', color: colors.textMuted },
  linkSubmitBtn: { flex: 1, paddingVertical: spacing.md, alignItems: 'center', borderRadius: radius.lg, backgroundColor: colors.primary },
  linkSubmitText: { fontSize: fontSize.md, fontWeight: '700', color: colors.white },
  linkError: { fontSize: fontSize.sm, color: '#EF4444', textAlign: 'center' },
  statusPill: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 8, paddingVertical: 2, borderRadius: 20, alignSelf: 'flex-start', marginTop: 3 },
  statusDot: { width: 6, height: 6, borderRadius: 3 },
  statusLabel: { fontSize: 11, fontWeight: '700' },
  personCardEmergency: { borderColor: '#EF444460', borderWidth: 2, backgroundColor: '#EF444410' },
});
