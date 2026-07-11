// useJourneyLifecycle (native) — master hook that orchestrates all
// mobile-side Journey Engine services: location, audio, SSE, queue.
//
// Usage:
//   const { startJourney, stopJourney, triggerSOS, isActive } = useJourneyLifecycle();
//
// On mount, this hook wires AppState listeners. Sensors start on startJourney()
// and stop on stopJourney(). Background continuation for location is handled
// by the existing backgroundLocation.ts TaskManager task (opt-in).
import { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, AppStateStatus } from 'react-native';
import NetInfo from '@react-native-community/netinfo';

import {
  initJourneyService,
  shutdownJourneyService,
  sendEvent,
  sendSOS,
  requestRiskScore,
  isOnline,
} from '../services/journeyService';
import {
  startLocationTracking,
  stopLocationTracking,
  setLowBatteryMode,
  setSessionId as setLocSession,
} from '../services/locationService';
import {
  startAudioMonitoring,
  stopAudioMonitoring,
  setAudioSessionId,
} from '../services/audioService';
import {
  connectSOSStream,
  disconnectSOSStream,
  setSseAuthToken,
} from '../services/sseService';
import { useJourneyEngineStore } from '../stores/journeyEngineStore';

interface JourneyConfig {
  sessionId: string;
  authToken?: string | null;
  enableAudio?: boolean;
  userType?: 'child' | 'woman' | 'adult' | 'elderly';
}

const RISK_EVAL_INTERVAL_MS = 60_000;

export function useJourneyLifecycle() {
  const [ready, setReady] = useState(false);
  const activeRef = useRef(false);
  const configRef = useRef<JourneyConfig | null>(null);
  const riskTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const appStateRef = useRef<AppStateStatus>(AppState.currentState);

  const isActive = useJourneyEngineStore((s) => s.isActive);

  // Init service layer once
  useEffect(() => {
    initJourneyService();
    setReady(true);
    return () => {
      shutdownJourneyService();
    };
  }, []);

  // AppState transitions — restart sensors on foreground if journey is active
  useEffect(() => {
    const sub = AppState.addEventListener('change', (next) => {
      const prev = appStateRef.current;
      appStateRef.current = next;
      if (!activeRef.current) return;

      if (prev.match(/inactive|background/) && next === 'active') {
        // Foreground restart — refresh sensors in case OS killed them
        console.log('[LIFECYCLE] foreground → ensure sensors running');
        void ensureSensorsRunning();
        void sendEvent('state_change', {
          state: 'foreground',
          sessionId: configRef.current?.sessionId || 'default',
          timestamp: Date.now(),
        });
      } else if (next.match(/inactive|background/)) {
        console.log('[LIFECYCLE] background — sensors continue via OS scheduling');
        void sendEvent('state_change', {
          state: 'background',
          sessionId: configRef.current?.sessionId || 'default',
          timestamp: Date.now(),
        });
      }
    });
    return () => sub.remove();
  }, []);

  const ensureSensorsRunning = useCallback(async () => {
    const cfg = configRef.current;
    if (!cfg) return;
    await startLocationTracking(cfg.sessionId);
    if (cfg.enableAudio !== false) {
      await startAudioMonitoring(cfg.sessionId);
    }
  }, []);

  const startJourney = useCallback(
    async (config: JourneyConfig): Promise<boolean> => {
      if (activeRef.current) return true;
      console.log('[LIFECYCLE] startJourney', config.sessionId);
      configRef.current = config;

      setLocSession(config.sessionId);
      setAudioSessionId(config.sessionId);
      setSseAuthToken(config.authToken || null);

      const locOk = await startLocationTracking(config.sessionId);
      if (!locOk) {
        console.warn('[LIFECYCLE] location permission missing — aborting');
        return false;
      }
      if (config.enableAudio !== false) {
        await startAudioMonitoring(config.sessionId);
      }

      activeRef.current = true;
      useJourneyEngineStore.getState().setActive(true);

      // Announce start
      await sendEvent('journey_start', {
        sessionId: config.sessionId,
        timestamp: Date.now(),
      });

      // Periodic risk eval
      if (riskTimerRef.current) clearInterval(riskTimerRef.current);
      riskTimerRef.current = setInterval(() => {
        void doRiskEval();
      }, RISK_EVAL_INTERVAL_MS);

      return true;
    },
    []
  );

  const stopJourney = useCallback(async (): Promise<void> => {
    if (!activeRef.current) return;
    console.log('[LIFECYCLE] stopJourney');
    activeRef.current = false;

    if (riskTimerRef.current) {
      clearInterval(riskTimerRef.current);
      riskTimerRef.current = null;
    }

    stopLocationTracking();
    await stopAudioMonitoring();
    disconnectSOSStream();

    await sendEvent('journey_stop', {
      sessionId: configRef.current?.sessionId || 'default',
      timestamp: Date.now(),
    });

    useJourneyEngineStore.getState().reset();
    configRef.current = null;
  }, []);

  const triggerSOS = useCallback(
    async (opts?: { riskLevel?: 'high' | 'critical'; meta?: Record<string, any> }) => {
      const cfg = configRef.current;
      const sessionId = cfg?.sessionId || 'manual';
      const loc = useJourneyEngineStore.getState().lastLocation;
      const net = await NetInfo.fetch();
      const net_state: 'online' | 'offline' =
        net.isConnected && net.isInternetReachable !== false ? 'online' : 'offline';

      const res = await sendSOS({
        sessionId,
        riskLevel: opts?.riskLevel || 'critical',
        riskScore: 95,
        location: loc ? { lat: loc.lat, lng: loc.lng } : null,
        network: net_state,
        meta: opts?.meta,
      });
      if (res.sos_id) {
        connectSOSStream(res.sos_id, cfg?.authToken || null);
        useJourneyEngineStore.getState().setEscalation({
          sos_id: res.sos_id,
          active_layer: 'guardian',
        });
      }
      return res;
    },
    []
  );

  const doRiskEval = useCallback(async () => {
    const cfg = configRef.current;
    if (!cfg) return;
    const net = await NetInfo.fetch();
    const online = !!net.isConnected && net.isInternetReachable !== false;
    const loc = useJourneyEngineStore.getState().lastLocation;
    const lastLocTs = loc?.ts || Date.now();
    const idleSec = Math.max(0, Math.round((Date.now() - lastLocTs) / 1000));

    const decision = await requestRiskScore({
      sessionId: cfg.sessionId,
      userType: cfg.userType,
      idleSec,
      network: online ? 'online' : 'offline',
      location: loc ? { lat: loc.lat, lng: loc.lng } : null,
      hour: new Date().getHours(),
    });
    if (!decision) return;

    // Persist full decision into store so any subscriber UI can react
    const store = useJourneyEngineStore.getState();
    const levelMap: Record<string, 'safe' | 'caution' | 'high' | 'critical'> = {
      GREEN: 'safe', YELLOW: 'caution', RED: 'high', CRITICAL: 'critical',
    };
    store.setDecision({
      risk_level: levelMap[decision.risk_level as string] || (decision.level as any) || 'safe',
      risk_score: decision.risk_score ?? 0,
      final_score: decision.final_score ?? decision.effective_score ?? 0,
      recommended_action: (decision.recommended_action as any) || null,
      executed: !!decision.executed,
      cooldown_applied: !!decision.cooldown_applied,
      sos_id: decision.sos_id || null,
      triggers_fired: decision.triggers_fired || decision.factors || [],
      ts: Date.now(),
    });

    // ── Signal → Brain → Action → Human → Feedback ──

    // 1. Cooldown: suppress UI noise entirely (brain already decided not to re-act)
    if (decision.cooldown_applied) {
      console.log('[LIFECYCLE] decision in cooldown — suppressing UI escalation noise');
      return;
    }

    // 2. Autonomous trigger: backend already fired SOS. No user confirmation needed.
    //    Silently wire SSE so mobile UI tracks escalation in real time.
    if (decision.executed && decision.recommended_action === 'TRIGGER_SOS' && decision.sos_id) {
      console.warn('[LIFECYCLE] autonomous SOS triggered by AI Brain', decision.sos_id);
      connectSOSStream(decision.sos_id, cfg.authToken || null);
      store.setEscalation({
        sos_id: decision.sos_id,
        active_layer: 'guardian',
      });
      return;
    }

    // 3. Advisory (RED/YELLOW): store.advisoryActive is already true via setDecision.
    //    UI should subscribe and render a subtle (non-panic) banner — NOT a popup.
    if (
      decision.recommended_action === 'NOTIFY_GUARDIAN' ||
      decision.recommended_action === 'INCREASE_MONITORING'
    ) {
      console.log(
        `[LIFECYCLE] advisory cue: ${decision.recommended_action} ` +
        `(risk=${decision.risk_level}) executed=${decision.executed}`
      );
      return;
    }

    // 4. GREEN / LOG_ONLY: nothing to do.
  }, []);

  return {
    ready,
    isActive,
    startJourney,
    stopJourney,
    triggerSOS,
    forceRiskEval: doRiskEval,
    isOnline,
    setLowBatteryMode,
  };
}
