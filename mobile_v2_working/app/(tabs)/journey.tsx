// Journey Screen — Start Journey, Live Safety, Safe Routes
import { useState, useEffect, useRef, useCallback } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  TextInput, Alert, ActivityIndicator, AppState, AppStateStatus,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import * as Location from 'expo-location';
import { guardianService, guardianDashboardService, safeRouteService, checkInService, childHelpService } from '@/services/endpoints';
import { useAuthStore } from '@/stores/authStore';
import { colors, spacing, fontSize, radius, shadows, scoreColor } from '@/theme';
import { startAudioMonitoring, stopAudioMonitoring, isVoiceMonitoringActive } from '@/services/audioMonitorService';
import { useJourneyStore } from '@/stores/journeyStore';
import { useChildSSE } from '@/hooks/useChildSSE';

type Tab = 'start' | 'active' | 'routes';

export default function JourneyScreen() {
  const { profileMode } = useAuthStore();
  if (profileMode === 'women' || profileMode === 'senior') {
    return <WomanRoutesScreen />;
  }
  return <LegacyJourneyScreen />;
}

function LegacyJourneyScreen() {
  const { user, profileMode } = useAuthStore();
  const [tab, setTab] = useState<Tab>('start');
  const [loading, setLoading] = useState(false);
  const [helpSending, setHelpSending] = useState(false);

  // ── Persisted Session — Single source of truth: Zustand store ──
  const { session, isReady, setSession, clearSession, setLastLocation } = useJourneyStore();
  const [pendingCheckIn, setPendingCheckIn] = useState<any>(null);
  const [respondingCheckIn, setRespondingCheckIn] = useState(false);

  // Safety hatch: if Zustand rehydration never fires (e.g. AsyncStorage corrupted),
  // force-unlock the UI after 2s so we never render a perpetually blank screen.
  const [forceReady, setForceReady] = useState(false);
  useEffect(() => {
    if (isReady) return;
    const t = setTimeout(() => setForceReady(true), 2000);
    return () => clearTimeout(t);
  }, [isReady]);

  // ── Child SSE for real-time check-in events on Journey screen ──
  const handleJourneySSE = useCallback((eventType: string, payload: any) => {
    const inner = payload.data || payload;
    if (eventType === 'checkin_pending') {
      console.log('[JOURNEY_SSE] checkin_pending received');
      setPendingCheckIn({
        id: inner.check_in_id,
        alert_type: 'check_in_pending',
        user_name: inner.guardian_name || 'Your guardian',
        responded: false,
      });
    }
    if (eventType === 'checkin_safe' || eventType === 'checkin_help' || eventType === 'checkin_expired') {
      console.log('[JOURNEY_SSE] ' + eventType + ' — clearing banner');
      setPendingCheckIn(null);
    }
  }, []);
  const { lastEventTs: journeySSELastEvent } = useChildSSE(handleJourneySSE);

  // ── GPS State ──
  const [currentLat, setCurrentLat] = useState<number | null>(null);
  const [currentLng, setCurrentLng] = useState<number | null>(null);
  const [gpsStatus, setGpsStatus] = useState<'idle' | 'fetching' | 'ready' | 'denied'>('idle');
  const locationWatchRef = useRef<Location.LocationSubscription | null>(null);
  const locationSendingRef = useRef(false); // In-flight lock — prevents duplicate API calls
  const lastSentRef = useRef(0); // Time-based debounce — prevents rapid-fire sends

  // ── AppState Lifecycle Guards ──
  const isGPSTrackingRef = useRef(false);
  const isMicActiveRef = useRef(false);
  const appStateRef = useRef<AppStateStatus>(AppState.currentState);

  const [destLat, setDestLat] = useState('');
  const [destLng, setDestLng] = useState('');

  // Safe Routes state — auto-populated from GPS
  const [startLat, setStartLat] = useState('');
  const [startLng, setStartLng] = useState('');
  const [endLat, setEndLat] = useState('12.9352');
  const [endLng, setEndLng] = useState('77.6245');
  const [routes, setRoutes] = useState<any>(null);
  const [routeLoading, setRouteLoading] = useState(false);

  // ── Request GPS permission and get initial fix ──
  const requestLocationPermission = async (): Promise<{ lat: number; lng: number } | null> => {
    setGpsStatus('fetching');
    const { status } = await Location.requestForegroundPermissionsAsync();
    if (status !== 'granted') {
      setGpsStatus('denied');
      return null;
    }

    const enabled = await Location.hasServicesEnabledAsync();
    if (!enabled) {
      setGpsStatus('denied');
      Alert.alert('GPS Disabled', 'Please enable Location Services in your device settings.');
      return null;
    }

    try {
      const loc = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High });
      const { latitude, longitude } = loc.coords;
      console.log(`[Journey GPS] Initial fix: ${latitude.toFixed(4)}, ${longitude.toFixed(4)}`);
      setCurrentLat(latitude);
      setCurrentLng(longitude);
      setGpsStatus('ready');
      return { lat: latitude, lng: longitude };
    } catch {
      try {
        const loc = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
        const { latitude, longitude } = loc.coords;
        setCurrentLat(latitude);
        setCurrentLng(longitude);
        setGpsStatus('ready');
        return { lat: latitude, lng: longitude };
      } catch {
        setGpsStatus('idle');
        Alert.alert('Location Error', 'Could not get your location. Please try again in an open area.');
        return null;
      }
    }
  };

  // ── Start GPS tracking — called from startJourney and AppState resume ──
  const startGPSTracking = async (sessionId: string) => {
    // Guard: if already tracking, skip (prevents duplicate tracking)
    if (isGPSTrackingRef.current || locationWatchRef.current) {
      console.log('[GPS_TRACKING] Already active, skipping duplicate start');
      return;
    }

    isGPSTrackingRef.current = true;
    console.log('[GPS_TRACKING_STARTED]', sessionId);

    // Single mechanism — watchPositionAsync handles BOTH UI update AND backend sync
    // Double guard: in-flight lock + time-based debounce (race condition fix)
    try {
      const sub = await Location.watchPositionAsync(
        { accuracy: Location.Accuracy.High, timeInterval: 15000, distanceInterval: 10 },
        async (loc) => {
          const { latitude, longitude } = loc.coords;
          setCurrentLat(latitude);
          setCurrentLng(longitude);
          setLastLocation(latitude, longitude);

          // Guard 1: Time debounce — skip if last send was < 2s ago
          const now = Date.now();
          if (now - lastSentRef.current < 2000) return;

          // Guard 2: In-flight lock — skip if a send is already in progress
          if (locationSendingRef.current) return;

          locationSendingRef.current = true;
          lastSentRef.current = now;
          try {
            await guardianService.updateLocation(sessionId, latitude, longitude);
          } catch (e) {
            console.warn('[LOCATION_SEND_FAIL]', e);
          } finally {
            locationSendingRef.current = false;
          }
        }
      );
      locationWatchRef.current = sub;
    } catch (e) {
      console.warn('[Journey GPS] watchPosition failed:', e);
    }
  };

  // ── Stop GPS tracking — called from "End Journey" button and cleanup ──
  const stopGPSTracking = () => {
    if (locationWatchRef.current) {
      locationWatchRef.current.remove();
      locationWatchRef.current = null;
    }
    isGPSTrackingRef.current = false;
    locationSendingRef.current = false;
    lastSentRef.current = 0;
    console.log('[GPS_TRACKING_STOPPED]');
  };

  // ── Restart mic monitoring (AppState resume) ──
  // Only for child/woman roles — guardians receive alerts via SSE
  const restartMicMonitoring = useCallback(async () => {
    const role = (user?.role || '').toLowerCase().trim();
    const isGuardianRole = ['guardian', 'parent', 'parents', 'caregiver', 'family', 'operator', 'admin'].includes(role);
    if (isGuardianRole) {
      console.log('[MIC_RESTART] Skipped — guardian role:', role);
      return;
    }
    // Always stop existing monitoring first to prevent Recording overlap
    if (isMicActiveRef.current || isVoiceMonitoringActive()) {
      console.log('[MIC_RESTART] Stopping existing monitoring before restart');
      try {
        stopAudioMonitoring();
      } catch (_) {}
      isMicActiveRef.current = false;
      // Delay to let native recorder fully unload before re-creating
      await new Promise(resolve => setTimeout(resolve, 500));
    }
    try {
      isMicActiveRef.current = true;
      await startAudioMonitoring({
        onAlert: (alert) => {
          console.log('[VOICE] Distress alert (resumed):', alert.message);
          Alert.alert(
            'Distress Detected',
            `${alert.message}\n\n${alert.countdownSeconds}s until auto-SOS.`,
            [
              { text: "I'm OK", style: 'cancel' },
              { text: 'Send Help', style: 'destructive' },
            ],
            { cancelable: false }
          );
        },
        onCountdown: (alertId, remaining) => {
          console.log(`[VOICE] Countdown: ${remaining}s for ${alertId}`);
        },
        onAutoSOS: (alertId) => {
          console.log(`[VOICE] Auto-SOS triggered for ${alertId}`);
        },
      });
      console.log('[MIC_RESTART] Audio monitoring restarted successfully');
    } catch (e) {
      console.warn('[MIC_RESTART] Failed to restart audio monitoring:', e);
      isMicActiveRef.current = false;
    }
  }, []);

  // ── Session Restore + AppState Lifecycle ──
  // Reactive: re-runs when isReady or session changes (no getState needed)
  useEffect(() => {
    if (!isReady) {
      console.log('[APP_FOREGROUND] Waiting for hydration...');
      return;
    }

    console.log('[SESSION_STATE]',
      'id:', session?.session_id ?? 'none',
      'status:', session?.status ?? 'none'
    );

    // Restore services if session is active (handles mount + rehydrate)
    if (session?.session_id && session?.status === 'active') {
      if (!isGPSTrackingRef.current) {
        console.log('[GPS_RESTART] Restoring GPS for session:', session.session_id);
        startGPSTracking(session.session_id);
      }
      if (!isMicActiveRef.current && !isVoiceMonitoringActive()) {
        console.log('[MIC_RESTART] Restoring audio monitoring');
        restartMicMonitoring();
      }
    }

    // AppState handler — session from closure is always fresh
    // because effect re-runs on [isReady, session] changes
    const handleAppStateChange = (nextAppState: AppStateStatus) => {
      const prevState = appStateRef.current;
      appStateRef.current = nextAppState;

      if (nextAppState === 'background' || nextAppState === 'inactive') {
        console.log('[APP_BACKGROUND]');
        return;
      }

      if (nextAppState === 'active' && (prevState === 'background' || prevState === 'inactive')) {
        console.log('[APP_FOREGROUND]');
        console.log('[SESSION_STATE]',
          'id:', session?.session_id ?? 'none',
          'status:', session?.status ?? 'none'
        );

        if (session?.session_id && session?.status === 'active') {
          console.log('[APP_FOREGROUND] Restoring session:', session.session_id);

          if (!isGPSTrackingRef.current) {
            console.log('[GPS_RESTART]');
            startGPSTracking(session.session_id);
          }

          if (!isMicActiveRef.current && !isVoiceMonitoringActive()) {
            console.log('[MIC_RESTART]');
            restartMicMonitoring();
          }
        } else {
          console.log('[APP_FOREGROUND] No active session');
        }
      }
    };

    console.log('[APPSTATE_REGISTERED]');
    const subscription = AppState.addEventListener('change', handleAppStateChange);
    return () => subscription.remove();
  }, [isReady, session, restartMicMonitoring]);

  // Auto-populate Safe Routes origin from GPS
  useEffect(() => {
    if (currentLat && currentLng && !startLat) {
      setStartLat(currentLat.toFixed(6));
      setStartLng(currentLng!.toFixed(6));
    }
  }, [currentLat, currentLng]);

  // Passive GPS on mount (no alert if denied)
  useEffect(() => {
    (async () => {
      const { status } = await Location.requestForegroundPermissionsAsync();
      if (status === 'granted') {
        try {
          const loc = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
          setCurrentLat(loc.coords.latitude);
          setCurrentLng(loc.coords.longitude);
          setGpsStatus('ready');
        } catch {}
      }
    })();
  }, []);

  // Check server for active sessions on mount (canonical source of truth)
  useEffect(() => { checkActiveSession(); }, []);

  // Auto-switch to active tab when session is rehydrated from storage
  useEffect(() => {
    if (isReady && session?.session_id) {
      console.log('[SESSION_STATE] Rehydrated session detected — switching to active tab');
      setTab('active');
    }
  }, [isReady]);

  const checkActiveSession = async () => {
    try {
      if (user?.role === 'guardian') {
        const res = await guardianService.listActive();
        const sessions = res?.data?.sessions || res?.data || [];
        if (sessions.length > 0) {
          const s = sessions[0];
          setSession(s.session_id, s.status || 'active', s.start_time || null);
          console.log('[SESSION_STATE] Server session loaded — id:', s.session_id, 'status:', s.status);
          setTab('active');
        }
      }
    } catch (e) {
      console.log('[Journey] checkActiveSession failed:', e);
    }
  };

  // Fallback poll for check-in requests — FIX 4: ONLY if SSE dead or stale
  useEffect(() => {
    if (!profileMode) return;
    const POLL_INTERVAL = 30000;
    const STALE_MS = 60000;

    const interval = setInterval(async () => {
      try {
        if (profileMode === 'parents') return;

        const isStale = journeySSELastEvent === 0 || (Date.now() - journeySSELastEvent > STALE_MS);
        if (!isStale) {
          console.log('[JOURNEY_POLL_FALLBACK] Skipped — SSE alive');
          return;
        }
        console.log('[JOURNEY_POLL_FALLBACK] Polling check-ins (stale=' + isStale + ')');

        const res = await guardianDashboardService.getAlerts(5);
        const alertList = res.data?.alerts || [];

        const pending = alertList.find(
          (a: any) => (
            a.alert_type === 'check_in_pending' ||
            a.alert_type === 'check_in_request' ||
            a.type === 'check_in_pending' ||
            a.type === 'check_in_request'
          ) && !a.responded
        );

        setPendingCheckIn(pending || null);
      } catch (e: any) {
        console.log('[JOURNEY_POLL_FALLBACK] Failed:', e?.response?.status || e?.message);
      }
    }, POLL_INTERVAL);

    return () => clearInterval(interval);
  }, [profileMode, journeySSELastEvent]);

  const handleCheckInResponse = async (response: 'safe' | 'help') => {
    if (!pendingCheckIn) return;
    setRespondingCheckIn(true);
    try {
      await checkInService.respond(pendingCheckIn.id, response);
      setPendingCheckIn(null);
      Alert.alert(
        response === 'safe' ? 'Sent' : 'Alert Sent',
        response === 'safe'
          ? 'Your guardian has been notified that you are safe.'
          : 'Your guardian has been notified that you need help.'
      );
    } catch (e: any) {
      Alert.alert('Error', e?.response?.data?.detail || 'Failed to respond');
    }
    setRespondingCheckIn(false);
  };

  // ── Standalone "Need Help" — alerts all guardians immediately ──
  const handleNeedHelp = useCallback(() => {
    Alert.alert(
      'Send Help Request?',
      'Your guardians will be alerted immediately with your location.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'SEND HELP',
          style: 'destructive',
          onPress: async () => {
            setHelpSending(true);
            try {
              const loc = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High });
              const res = await childHelpService.requestHelp(
                loc.coords.latitude,
                loc.coords.longitude,
              );
              const notified = res.data?.guardians_notified || 0;
              console.log(`[HELP_REQUEST] Sent — ${notified} guardians notified`);
              Alert.alert('Help Sent', `${notified} guardian(s) have been alerted.`);
            } catch (e: any) {
              console.error('[HELP_REQUEST] Failed:', e);
              Alert.alert('Error', e?.response?.data?.detail || 'Failed to send help request');
            }
            setHelpSending(false);
          },
        },
      ],
      { cancelable: true },
    );
  }, []);

  const startJourney = async () => {
    if (!user?.id) {
      Alert.alert('Error', 'User ID not found');
      return;
    }

    setLoading(true);

    // Get real GPS location
    const location = await requestLocationPermission();
    if (!location) {
      // Permission denied or GPS failed — prompt retry
      setLoading(false);
      Alert.alert(
        'Location Required',
        'Location permission is required for safety tracking.',
        [
          { text: 'Cancel', style: 'cancel' },
          { text: 'Retry', onPress: () => startJourney() },
        ]
      );
      return;
    }

    try {
      console.log(`[Journey] Starting session with GPS: lat=${location.lat.toFixed(6)} lng=${location.lng.toFixed(6)}`);
      const res = await guardianService.startSession(user.id, location);
      const resData = res?.data;
      const sessionId = resData?.session_id;

      // Persist IMMEDIATELY before any async operations
      if (sessionId) {
        setSession(sessionId, resData?.status || 'active', resData?.start_time || null);
      }
      console.log('[SESSION_PERSIST] Saved:', sessionId);

      setTab('active');
      Alert.alert('Success', 'Journey Started — your location is being shared.');

      // Then start services
      if (sessionId) {
        startGPSTracking(sessionId);
      }
    } catch (e: any) {
      Alert.alert('Error', e?.response?.data?.detail || e?.message || 'Failed to start journey');
    } finally {
      setLoading(false);
    }
  };

  const stopJourney = async () => {
    if (!session?.session_id) return;
    setLoading(true);
    try {
      await guardianService.stopSession(session.session_id);
      stopGPSTracking();
      clearSession();
      setTab('start');
      Alert.alert('Journey Ended', 'You have arrived safely.');
    } catch (e: any) {
      Alert.alert('Error', e?.response?.data?.detail || 'Failed to stop journey');
    }
    setLoading(false);
  };

  const fetchRoutes = async () => {
    // Use current GPS if route origin fields are empty
    const originLat = startLat ? parseFloat(startLat) : currentLat;
    const originLng = startLng ? parseFloat(startLng) : currentLng;

    if (!originLat || !originLng) {
      Alert.alert('Location Needed', 'Please wait for GPS fix or enter coordinates manually.');
      return;
    }

    setRouteLoading(true);
    try {
      const res = await safeRouteService.generateRoutes(
        originLat, originLng,
        parseFloat(endLat), parseFloat(endLng),
      );
      setRoutes(res.data);
    } catch (e: any) {
      Alert.alert('Error', e?.response?.data?.detail || 'Failed to generate routes');
    }
    setRouteLoading(false);
  };

  // GPS status indicator text
  const gpsLabel = gpsStatus === 'fetching' ? 'Fetching location...'
    : gpsStatus === 'ready' && currentLat ? `GPS: ${currentLat.toFixed(4)}, ${currentLng?.toFixed(4)}`
    : gpsStatus === 'denied' ? 'Location denied'
    : 'Tap Start to enable GPS';

  // Loading gate — wait for store rehydration before rendering.
  // Falls through after 2s regardless (forceReady) so UI never stays blank.
  if (!isReady && !forceReady) {
    return (
      <SafeAreaView style={styles.safe}>
        <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center' }}>
          <ActivityIndicator size="large" color={colors.primary} />
          <Text style={{ color: colors.textMuted, marginTop: spacing.md, fontSize: fontSize.sm }}>
            Restoring session…
          </Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} testID="journey-screen">
      <ScrollView style={styles.scroll} contentContainerStyle={styles.content}>
        <Text style={styles.title}>Journey</Text>

        {/* Check-In Request Banner */}
        {pendingCheckIn && (
          <View style={styles.checkInBanner} testID="journey-checkin-banner">
            <View style={styles.checkInInfo}>
              <Ionicons name="shield-checkmark" size={24} color="#3B82F6" />
              <View style={{ flex: 1, marginLeft: 12 }}>
                <Text style={styles.checkInTitle}>Guardian is checking on you</Text>
                <Text style={styles.checkInSub}>Please respond to let them know you're OK</Text>
              </View>
            </View>
            <View style={styles.checkInButtons}>
              <TouchableOpacity
                style={[styles.safeBtn, respondingCheckIn && styles.btnDisabled]}
                onPress={() => handleCheckInResponse('safe')}
                disabled={respondingCheckIn}
                testID="journey-checkin-safe-btn"
              >
                <Ionicons name="checkmark-circle" size={20} color="#fff" />
                <Text style={styles.safeBtnText}>I'm Safe</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.helpBtn, respondingCheckIn && styles.btnDisabled]}
                onPress={() => handleCheckInResponse('help')}
                disabled={respondingCheckIn}
                testID="journey-checkin-help-btn"
              >
                <Ionicons name="alert-circle" size={20} color="#fff" />
                <Text style={styles.helpBtnText}>Need Help</Text>
              </TouchableOpacity>
            </View>
          </View>
        )}

        <View style={styles.tabs}>
          {(['start', 'active', 'routes'] as Tab[]).map((t) => (
            <TouchableOpacity
              key={t}
              style={[styles.tab, tab === t && styles.tabActive]}
              onPress={() => setTab(t)}
              testID={`journey-tab-${t}`}
            >
              <Text style={[styles.tabText, tab === t && styles.tabTextActive]}>
                {t === 'start' ? 'Start' : t === 'active' ? 'Live Status' : 'Safe Routes'}
              </Text>
            </TouchableOpacity>
          ))}
        </View>

        {tab === 'start' && (
          <View style={styles.section}>
            <View style={styles.card}>
              <Ionicons name="location" size={48} color={colors.primary} style={{ alignSelf: 'center', marginBottom: spacing.lg }} />
              <Text style={styles.cardTitle}>Start a Safety Journey</Text>
              <Text style={styles.cardDesc}>
                Your location will be shared with guardians in real-time.
                They'll receive alerts if anything seems unusual.
              </Text>

              {/* GPS Status Indicator */}
              <View style={styles.gpsBar} testID="gps-status-bar">
                <Ionicons
                  name={gpsStatus === 'ready' ? 'locate' : gpsStatus === 'fetching' ? 'sync' : 'locate-outline'}
                  size={16}
                  color={gpsStatus === 'ready' ? colors.safe : gpsStatus === 'denied' ? colors.critical : colors.textMuted}
                />
                <Text style={[styles.gpsText, gpsStatus === 'ready' && { color: colors.safe }]}>
                  {gpsLabel}
                </Text>
                {gpsStatus === 'fetching' && <ActivityIndicator size="small" color={colors.primary} />}
              </View>

              <Text style={styles.inputLabel}>Destination (optional)</Text>
              <View style={styles.coordRow}>
                <View style={styles.coordInput}>
                  <Text style={styles.coordLabel}>Lat</Text>
                  <TextInput style={styles.input} value={destLat} onChangeText={setDestLat}
                    placeholder="e.g. 12.9352" keyboardType="numeric" placeholderTextColor={colors.textMuted} testID="journey-dest-lat" />
                </View>
                <View style={styles.coordInput}>
                  <Text style={styles.coordLabel}>Lng</Text>
                  <TextInput style={styles.input} value={destLng} onChangeText={setDestLng}
                    placeholder="e.g. 77.6245" keyboardType="numeric" placeholderTextColor={colors.textMuted} testID="journey-dest-lng" />
                </View>
              </View>

              <TouchableOpacity
                style={[styles.startBtn, loading && styles.btnDisabled]}
                onPress={startJourney}
                disabled={loading}
                testID="start-journey-btn"
              >
                {loading ? (
                  <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
                    <ActivityIndicator color={colors.white} />
                    <Text style={styles.startBtnText}>
                      {gpsStatus === 'fetching' ? 'Getting Location...' : 'Starting...'}
                    </Text>
                  </View>
                ) : (
                  <>
                    <Ionicons name="play-circle" size={22} color={colors.white} />
                    <Text style={styles.startBtnText}>Start Journey</Text>
                  </>
                )}
              </TouchableOpacity>
            </View>
          </View>
        )}

        {tab === 'active' && (
          <View style={styles.section}>
            {session ? (
              <View style={styles.card}>
                <View style={styles.liveHeader}>
                  <View style={styles.liveDot} />
                  <Text style={styles.liveText}>LIVE</Text>
                </View>
                <Text style={styles.cardTitle}>Journey Active</Text>
                <Text style={styles.cardDesc}>
                  Session: {session.session_id?.slice(0, 12)}...
                </Text>

                <View style={styles.statusGrid}>
                  <StatusItem icon="time" label="Started" value={formatTime(session.start_time ?? null)} />
                  <StatusItem icon="shield-checkmark" label="Status" value={session.status || 'active'} />
                  <StatusItem
                    icon="locate"
                    label="GPS"
                    value={currentLat ? `${currentLat.toFixed(4)}, ${currentLng?.toFixed(4)}` : 'Acquiring...'}
                  />
                </View>

                <TouchableOpacity
                  style={[styles.needHelpBtn, helpSending && styles.btnDisabled]}
                  onPress={handleNeedHelp}
                  disabled={helpSending}
                  testID="need-help-btn"
                >
                  {helpSending ? (
                    <ActivityIndicator color={colors.white} />
                  ) : (
                    <>
                      <Ionicons name="alert-circle" size={24} color={colors.white} />
                      <Text style={styles.needHelpBtnText}>NEED HELP</Text>
                    </>
                  )}
                </TouchableOpacity>

                <TouchableOpacity
                  style={[styles.stopBtn, loading && styles.btnDisabled]}
                  onPress={stopJourney}
                  disabled={loading}
                  testID="stop-journey-btn"
                >
                  {loading ? (
                    <ActivityIndicator color={colors.white} />
                  ) : (
                    <>
                      <Ionicons name="stop-circle" size={22} color={colors.white} />
                      <Text style={styles.stopBtnText}>End Journey</Text>
                    </>
                  )}
                </TouchableOpacity>
              </View>
            ) : (
              <View style={styles.emptyCard}>
                <Ionicons name="navigate-outline" size={48} color={colors.textMuted} />
                <Text style={styles.emptyText}>No active journey</Text>
                <TouchableOpacity onPress={() => setTab('start')}>
                  <Text style={styles.emptyLink}>Start one now</Text>
                </TouchableOpacity>
              </View>
            )}
          </View>
        )}

        {tab === 'routes' && (
          <View style={styles.section}>
            <View style={styles.card}>
              <Text style={styles.cardTitle}>Safe Route Finder</Text>
              <Text style={styles.cardDesc}>Compare routes by safety score</Text>

              <Text style={styles.inputLabel}>Origin {currentLat ? '(GPS)' : ''}</Text>
              <View style={styles.coordRow}>
                <View style={styles.coordInput}>
                  <Text style={styles.coordLabel}>Lat</Text>
                  <TextInput style={styles.input} value={startLat} onChangeText={setStartLat}
                    placeholder={currentLat ? currentLat.toFixed(6) : 'Waiting for GPS...'}
                    keyboardType="numeric" placeholderTextColor={colors.textMuted} testID="route-start-lat" />
                </View>
                <View style={styles.coordInput}>
                  <Text style={styles.coordLabel}>Lng</Text>
                  <TextInput style={styles.input} value={startLng} onChangeText={setStartLng}
                    placeholder={currentLng ? currentLng.toFixed(6) : 'Waiting for GPS...'}
                    keyboardType="numeric" placeholderTextColor={colors.textMuted} testID="route-start-lng" />
                </View>
              </View>

              <Text style={styles.inputLabel}>Destination</Text>
              <View style={styles.coordRow}>
                <View style={styles.coordInput}>
                  <Text style={styles.coordLabel}>Lat</Text>
                  <TextInput style={styles.input} value={endLat} onChangeText={setEndLat}
                    keyboardType="numeric" placeholderTextColor={colors.textMuted} testID="route-end-lat" />
                </View>
                <View style={styles.coordInput}>
                  <Text style={styles.coordLabel}>Lng</Text>
                  <TextInput style={styles.input} value={endLng} onChangeText={setEndLng}
                    keyboardType="numeric" placeholderTextColor={colors.textMuted} testID="route-end-lng" />
                </View>
              </View>

              <TouchableOpacity
                style={[styles.startBtn, routeLoading && styles.btnDisabled]}
                onPress={fetchRoutes}
                disabled={routeLoading}
                testID="find-routes-btn"
              >
                {routeLoading ? (
                  <ActivityIndicator color={colors.white} />
                ) : (
                  <>
                    <Ionicons name="map" size={20} color={colors.white} />
                    <Text style={styles.startBtnText}>Find Safe Routes</Text>
                  </>
                )}
              </TouchableOpacity>
            </View>

            {routes?.routes && routes.routes.map((route: any, i: number) => (
              <RouteCard key={i} route={route} index={i} />
            ))}
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function StatusItem({ icon, label, value }: { icon: string; label: string; value: string }) {
  return (
    <View style={styles.statusItem}>
      <Ionicons name={icon as any} size={18} color={colors.textMuted} />
      <Text style={styles.statusLabel}>{label}</Text>
      <Text style={styles.statusValue} numberOfLines={1}>{value}</Text>
    </View>
  );
}

function RouteCard({ route, index }: { route: any; index: number }) {
  const typeColors: Record<string, string> = { safest: colors.safe, balanced: colors.primary, shortest: colors.warning };
  const color = typeColors[route.type] || colors.textMuted;
  return (
    <View style={[styles.routeCard, { borderLeftColor: color, borderLeftWidth: 3 }]} testID={`route-card-${index}`}>
      <View style={styles.routeHeader}>
        <Text style={[styles.routeType, { color }]}>{route.type?.toUpperCase()}</Text>
        <Text style={[styles.routeScore, { color: scoreColor(route.safety_score || 5) }]}>
          {(route.safety_score || 0).toFixed(1)}/10
        </Text>
      </View>
      <View style={styles.routeStats}>
        <Text style={styles.routeStat}>{((route.distance || 0) / 1000).toFixed(1)} km</Text>
        <Text style={styles.routeStat}>{Math.round((route.duration || 0) / 60)} min</Text>
        <Text style={styles.routeStat}>{route.danger_count || 0} risks</Text>
      </View>
    </View>
  );
}

function WomanRoutesScreen() {
  const { profileMode, user } = useAuthStore();
  const isSeniorMode = profileMode === 'senior';
  const [period, setPeriod] = useState<'Today' | 'This Week' | 'This Month'>('Today');
  const [expandedRoute, setExpandedRoute] = useState<string | null>(null);
  const displayName = user?.full_name?.trim() || (isSeniorMode ? 'sfdgfh' : 'fcwhgcj');
  const allRoutes = [
    { status: 'Safe', time: 'Today - 7:42 AM', from: 'Home, Sector 15', to: 'DPS School, Sector 19', duration: '18 min', distance: '3.2 km', tone: '#22C55E', timeline: [['navigate-outline', 'Departed Home', '7:42 AM'], ['trail-sign-outline', 'Crossed Sector 18 Roundabout', '7:51 AM'], ['flag-outline', 'Arrived at School', '8:00 AM']] },
    { status: 'Deviation', time: 'Today - 3:35 PM', from: 'DPS School, Sector 19', to: 'Aakash Tuition, Sector 10', duration: '24 min', distance: '4.8 km', tone: '#F59E0B', timeline: [['navigate-outline', 'Departed School', '3:35 PM'], ['warning-outline', 'Route deviation at Sector 12 crossing', '3:48 PM'], ['flag-outline', 'Reached Aakash Tuition', '3:59 PM']] },
    { status: 'Safe', time: 'Yesterday - 6:15 PM', from: 'Aakash Tuition, Sector 10', to: 'Home, Sector 15', duration: '21 min', distance: '3.9 km', tone: '#22C55E', timeline: [['navigate-outline', 'Departed Tuition', '6:15 PM'], ['shield-checkmark-outline', 'Guardian tracking active', '6:24 PM'], ['flag-outline', 'Arrived Home', '6:36 PM']] },
    { status: 'Safe', time: 'Sat - 8:30 AM', from: 'Home, Sector 15', to: 'Market Road', duration: '14 min', distance: '2.1 km', tone: '#22C55E', timeline: [['navigate-outline', 'Journey started', '8:30 AM'], ['flag-outline', 'Arrived safely', '8:44 AM']] },
    { status: 'Safe', time: 'Fri - 5:20 PM', from: 'Office Park', to: 'Home, Sector 15', duration: '31 min', distance: '6.4 km', tone: '#22C55E', timeline: [['navigate-outline', 'Journey started', '5:20 PM'], ['flag-outline', 'Arrived safely', '5:51 PM']] },
  ];
  const visibleRoutes = period === 'Today' ? allRoutes.slice(0, 2) : period === 'This Week' ? allRoutes : allRoutes;

  return (
    <SafeAreaView style={womanRoute.safe} edges={['top']}>
      <View style={womanRoute.header}>
        <TouchableOpacity activeOpacity={0.82} style={womanRoute.backBtn}>
          <Ionicons name="chevron-back" size={24} color="#0F172A" />
        </TouchableOpacity>
        <View style={womanRoute.headerCenter}>
          <Text style={womanRoute.userName}>{displayName}</Text>
          <View style={womanRoute.roleRow}>
            <View style={womanRoute.onlineDot} />
            <Text style={[womanRoute.roleText, isSeniorMode && womanRoute.seniorRoleText]}>{isSeniorMode ? 'Senior Citizen · Protected' : 'Woman · Protected'}</Text>
          </View>
        </View>
        <View style={[womanRoute.rolePill, isSeniorMode && womanRoute.seniorRolePill]}>
          <Text style={[womanRoute.rolePillText, isSeniorMode && womanRoute.seniorRolePillText]}>{isSeniorMode ? 'Senior' : 'Woman'}</Text>
        </View>
      </View>

      <View style={womanRoute.titleBlock}>
        <Text style={womanRoute.title}>My Routes</Text>
        <Text style={womanRoute.subtitle}>{visibleRoutes.length} routes recorded</Text>
        <View style={womanRoute.filterRow}>
          {(['Today', 'This Week', 'This Month'] as const).map((item) => (
            <TouchableOpacity
              key={item}
              activeOpacity={0.82}
              onPress={() => {
                setPeriod(item);
                setExpandedRoute(null);
              }}
              style={[womanRoute.filterPill, period === item && womanRoute.filterActive]}
            >
              <Text style={period === item ? womanRoute.filterActiveText : womanRoute.filterText}>{item}</Text>
            </TouchableOpacity>
          ))}
        </View>
      </View>

      <ScrollView style={womanRoute.scroll} contentContainerStyle={womanRoute.content} showsVerticalScrollIndicator={false}>
        {visibleRoutes.map((route) => {
          const routeKey = `${route.time}-${route.to}`;
          const expanded = expandedRoute === routeKey;
          return (
          <TouchableOpacity key={routeKey} activeOpacity={0.88} onPress={() => setExpandedRoute(expanded ? null : routeKey)} style={[womanRoute.routeCard, expanded && womanRoute.routeCardExpanded]}>
            <View style={womanRoute.routeSummary}>
              <View style={womanRoute.mapThumb}>
                <View style={[womanRoute.mapCurve, { borderColor: route.tone }]} />
                <View style={[womanRoute.mapDotStart, { borderColor: route.tone }]} />
                <View style={[womanRoute.mapDotEnd, { borderColor: route.tone }]} />
              </View>
              <View style={womanRoute.routeCopy}>
                <View style={womanRoute.routeTop}>
                  <View style={[womanRoute.statusPill, { backgroundColor: route.status === 'Safe' ? '#DCFCE7' : '#FEF3C7' }]}>
                    <Ionicons name={route.status === 'Safe' ? 'checkmark-circle-outline' : 'warning-outline'} size={14} color={route.tone} />
                    <Text style={[womanRoute.statusText, { color: route.tone }]}>{route.status}</Text>
                  </View>
                  <Text style={womanRoute.routeTime}>{route.time}</Text>
                  <Ionicons name={expanded ? 'chevron-up' : 'chevron-down'} size={16} color="#8EA0BB" />
                </View>
                <View style={womanRoute.placeRow}>
                  <View style={womanRoute.greenDot} />
                  <Text style={womanRoute.placeText}>{route.from}</Text>
                </View>
                <View style={womanRoute.placeRow}>
                  <Ionicons name="location-outline" size={12} color="#EF4444" />
                  <Text style={womanRoute.placeText}>{route.to}</Text>
                </View>
                <View style={womanRoute.metaRow}>
                  <Ionicons name="time-outline" size={14} color="#64748B" />
                  <Text style={womanRoute.metaText}>{route.duration}</Text>
                  <Ionicons name="git-branch-outline" size={14} color="#64748B" />
                  <Text style={womanRoute.metaText}>{route.distance}</Text>
                </View>
              </View>
            </View>
            {expanded ? (
              <View style={womanRoute.timelineBlock}>
                <Text style={womanRoute.timelineLabel}>JOURNEY TIMELINE</Text>
                {route.timeline.map(([icon, title, time], stepIndex) => (
                  <View key={`${title}-${time}`} style={womanRoute.timelineRow}>
                    <View style={womanRoute.timelineIcon}>
                      <Ionicons name={icon as keyof typeof Ionicons.glyphMap} size={19} color={route.status === 'Deviation' && stepIndex === 1 ? '#F59E0B' : '#0B8FF0'} />
                    </View>
                    <View style={womanRoute.timelineTextWrap}>
                      <Text style={womanRoute.timelineTitle}>{title}</Text>
                      <Text style={womanRoute.timelineTime}>{time}</Text>
                    </View>
                  </View>
                ))}
              </View>
            ) : null}
          </TouchableOpacity>
          );
        })}
        <Text style={womanRoute.footerText}>Route Monitoring by NISCHINT</Text>
      </ScrollView>
    </SafeAreaView>
  );
}

function formatTime(ts: string | null) {
  if (!ts) return '--';
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

const womanRoute = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#F3F7FB' },
  header: { height: 86, backgroundColor: '#FFFFFF', borderBottomWidth: 1, borderBottomColor: '#E2E8F0', flexDirection: 'row', alignItems: 'center', paddingHorizontal: 18 },
  backBtn: { width: 42, height: 42, borderRadius: 21, backgroundColor: '#F1F5F9', alignItems: 'center', justifyContent: 'center' },
  headerCenter: { flex: 1, alignItems: 'center' },
  userName: { color: '#020817', fontSize: 18, fontWeight: '900' },
  roleRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 3 },
  onlineDot: { width: 7, height: 7, borderRadius: 4, backgroundColor: '#4ADE80' },
  roleText: { color: '#7C3AED', fontSize: 12, fontWeight: '900' },
  seniorRoleText: { color: '#92400E' },
  rolePill: { borderRadius: 16, paddingHorizontal: 13, paddingVertical: 7, backgroundColor: '#F4ECFF' },
  seniorRolePill: { backgroundColor: '#FEF3C7' },
  rolePillText: { color: '#7C3AED', fontSize: 12, fontWeight: '900' },
  seniorRolePillText: { color: '#92400E' },
  titleBlock: { backgroundColor: '#FFFFFF', paddingHorizontal: 18, paddingTop: 62, paddingBottom: 20 },
  title: { color: '#020817', fontSize: 25, fontWeight: '900' },
  subtitle: { color: '#53657E', fontSize: 15, marginTop: 4 },
  filterRow: { flexDirection: 'row', gap: 10, marginTop: 16 },
  filterPill: { height: 38, borderRadius: 19, paddingHorizontal: 18, alignItems: 'center', justifyContent: 'center', backgroundColor: '#F8FAFC', borderWidth: 1, borderColor: '#D8E1EC' },
  filterActive: { backgroundColor: '#1299F5', borderColor: '#1299F5' },
  filterText: { color: '#53657E', fontSize: 14, fontWeight: '900' },
  filterActiveText: { color: '#FFFFFF', fontSize: 14, fontWeight: '900' },
  scroll: { flex: 1 },
  content: { padding: 18, paddingBottom: 100 },
  routeCard: { minHeight: 150, borderRadius: 18, backgroundColor: '#FFFFFF', borderWidth: 1, borderColor: '#DDE6F1', padding: 20, marginBottom: 16, shadowColor: '#0F172A', shadowOpacity: 0.04, shadowOffset: { width: 0, height: 5 }, shadowRadius: 12, elevation: 1 },
  routeCardExpanded: { paddingBottom: 22 },
  routeSummary: { flexDirection: 'row' },
  mapThumb: { width: 80, height: 60, borderRadius: 12, backgroundColor: '#EAF5FF', overflow: 'hidden', marginRight: 16, marginTop: 2 },
  mapCurve: { position: 'absolute', left: 10, top: 12, width: 56, height: 38, borderLeftWidth: 3, borderTopWidth: 3, borderRadius: 28, transform: [{ rotate: '-12deg' }] },
  mapDotStart: { position: 'absolute', left: 8, bottom: 7, width: 8, height: 8, borderRadius: 4, borderWidth: 2, backgroundColor: '#FFFFFF' },
  mapDotEnd: { position: 'absolute', right: 8, top: 8, width: 8, height: 8, borderRadius: 4, borderWidth: 2, backgroundColor: '#FFFFFF' },
  routeCopy: { flex: 1 },
  routeTop: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 11 },
  statusPill: { height: 24, borderRadius: 12, flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 8 },
  statusText: { fontSize: 13, fontWeight: '900' },
  routeTime: { flex: 1, color: '#8EA0BB', fontSize: 14, fontWeight: '800', textAlign: 'right' },
  placeRow: { flexDirection: 'row', alignItems: 'center', gap: 7, marginBottom: 6 },
  greenDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: '#22C55E' },
  placeText: { color: '#020817', fontSize: 15, fontWeight: '800' },
  metaRow: { flexDirection: 'row', alignItems: 'center', gap: 5, marginTop: 6 },
  metaText: { color: '#53657E', fontSize: 14, fontWeight: '700', marginRight: 12 },
  timelineBlock: { borderTopWidth: 1, borderTopColor: '#EEF2F7', marginTop: 18, paddingTop: 18 },
  timelineLabel: { color: '#60708A', fontSize: 13, fontWeight: '900', letterSpacing: 1.4, marginBottom: 14 },
  timelineRow: { flexDirection: 'row', alignItems: 'center', marginBottom: 14 },
  timelineIcon: { width: 36, height: 36, borderRadius: 18, backgroundColor: '#EAF5FF', alignItems: 'center', justifyContent: 'center', marginRight: 14 },
  timelineTextWrap: { flex: 1 },
  timelineTitle: { color: '#07111F', fontSize: 16, fontWeight: '900' },
  timelineTime: { color: '#8EA0BB', fontSize: 14, fontWeight: '700', marginTop: 4 },
  footerText: { color: '#94A3B8', fontSize: 14, fontWeight: '800', textAlign: 'center', marginTop: 130 },
});

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  scroll: { flex: 1 },
  content: { padding: spacing.xl, paddingBottom: spacing['5xl'] },
  title: { fontSize: fontSize['2xl'], fontWeight: '800', color: colors.textPrimary, marginBottom: spacing.lg },
  tabs: { flexDirection: 'row', gap: spacing.sm, marginBottom: spacing.xl },
  tab: { flex: 1, paddingVertical: spacing.md, borderRadius: radius.lg, backgroundColor: colors.bgCard, alignItems: 'center', borderWidth: 1, borderColor: colors.border },
  tabActive: { backgroundColor: colors.primary + '20', borderColor: colors.primary },
  tabText: { fontSize: fontSize.sm, fontWeight: '600', color: colors.textMuted },
  tabTextActive: { color: colors.primary },
  section: { gap: spacing.lg },
  card: { backgroundColor: colors.bgCard, borderRadius: radius.xl, padding: spacing.xl, borderWidth: 1, borderColor: colors.border, ...shadows.md },
  cardTitle: { fontSize: fontSize.xl, fontWeight: '700', color: colors.textPrimary, marginBottom: spacing.xs },
  cardDesc: { fontSize: fontSize.sm, color: colors.textSecondary, marginBottom: spacing.xl },
  inputLabel: { fontSize: fontSize.sm, fontWeight: '600', color: colors.textSecondary, marginBottom: spacing.sm, marginTop: spacing.md },
  coordRow: { flexDirection: 'row', gap: spacing.md },
  coordInput: { flex: 1 },
  coordLabel: { fontSize: fontSize.xs, color: colors.textMuted, marginBottom: 4 },
  input: { backgroundColor: colors.bgInput, borderRadius: radius.md, paddingHorizontal: spacing.md, height: 44, color: colors.textPrimary, fontSize: fontSize.md, borderWidth: 1, borderColor: colors.border },
  startBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: spacing.sm, backgroundColor: colors.primary, borderRadius: radius.lg, height: 52, marginTop: spacing.xl },
  startBtnText: { color: colors.white, fontSize: fontSize.lg, fontWeight: '700' },
  btnDisabled: { opacity: 0.6 },
  stopBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: spacing.sm, backgroundColor: colors.critical, borderRadius: radius.lg, height: 52, marginTop: spacing.md },
  stopBtnText: { color: colors.white, fontSize: fontSize.lg, fontWeight: '700' },
  needHelpBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: spacing.sm, backgroundColor: '#FF6600', borderRadius: radius.lg, height: 56, marginTop: spacing.xl, borderWidth: 2, borderColor: '#FF8800' },
  needHelpBtnText: { color: colors.white, fontSize: fontSize.xl, fontWeight: '900', letterSpacing: 2 },
  liveHeader: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.lg },
  liveDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: colors.safe },
  liveText: { fontSize: fontSize.sm, fontWeight: '800', color: colors.safe, letterSpacing: 2 },
  statusGrid: { flexDirection: 'row', gap: spacing.lg, marginTop: spacing.md },
  statusItem: { flex: 1, alignItems: 'center', gap: 4 },
  statusLabel: { fontSize: fontSize.xs, color: colors.textMuted },
  statusValue: { fontSize: fontSize.md, fontWeight: '700', color: colors.textPrimary, textTransform: 'capitalize' },
  emptyCard: { backgroundColor: colors.bgCard, borderRadius: radius.xl, padding: spacing['4xl'], alignItems: 'center', gap: spacing.md, borderWidth: 1, borderColor: colors.border },
  emptyText: { fontSize: fontSize.md, color: colors.textMuted },
  emptyLink: { fontSize: fontSize.md, color: colors.primary, fontWeight: '600' },
  routeCard: { backgroundColor: colors.bgCard, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, marginTop: spacing.md },
  routeHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: spacing.sm },
  routeType: { fontSize: fontSize.sm, fontWeight: '800', letterSpacing: 1 },
  routeScore: { fontSize: fontSize.lg, fontWeight: '800' },
  routeStats: { flexDirection: 'row', gap: spacing.xl },
  routeStat: { fontSize: fontSize.sm, color: colors.textSecondary },
  // GPS Status Bar
  gpsBar: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: colors.bg,
    borderRadius: radius.md,
    paddingHorizontal: 12,
    paddingVertical: 8,
    marginBottom: spacing.md,
  },
  gpsText: { fontSize: fontSize.xs, color: colors.textMuted, flex: 1 },
  // Check-In Banner
  checkInBanner: {
    backgroundColor: '#1E3A5F',
    borderRadius: 16,
    padding: 16,
    marginBottom: 16,
    borderWidth: 2,
    borderColor: '#3B82F6',
  },
  checkInInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 12,
  },
  checkInTitle: { fontSize: 15, fontWeight: '700', color: '#fff' },
  checkInSub: { fontSize: 12, color: '#94A3B8', marginTop: 2 },
  checkInButtons: {
    flexDirection: 'row',
    gap: 12,
  },
  safeBtn: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    backgroundColor: '#22C55E',
    borderRadius: 12,
    paddingVertical: 14,
  },
  safeBtnText: { fontSize: 15, fontWeight: '700', color: '#fff' },
  helpBtn: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    backgroundColor: '#EF4444',
    borderRadius: 12,
    paddingVertical: 14,
  },
  helpBtnText: { fontSize: 15, fontWeight: '700', color: '#fff' },
});
