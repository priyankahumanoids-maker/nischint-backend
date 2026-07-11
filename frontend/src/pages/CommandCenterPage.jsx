import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import api, { getToken } from '../api';
import { operatorApi } from '../api';
import { applyDelta, deltaMetrics, recordFrame } from '../utils/applyDelta';
import { WSFrameInspector } from '../components/command-center/WSFrameInspector';
import { WeatherChip } from '../components/command-center/WeatherChip';
import { LiveActivityChip } from '../components/command-center/LiveActivityChip';
import { DevScenarioPanel } from '../components/command-center/DevScenarioPanel';
import { FleetChangeIndicator } from '../components/command-center/FleetChangeIndicator';
import { LastCityUpdateChip } from '../components/command-center/LastCityUpdateChip';
import { SystemHealthCapsule } from '../components/command-center/SystemHealthCapsule';
import { LatencyHotspotsChip } from '../components/command-center/LatencyHotspotsChip';
import { LogTailCapsule } from '../components/command-center/LogTailCapsule';
import { LoopHealthCapsule } from '../components/command-center/LoopHealthCapsule';
import { V2ParityChip } from '../components/command-center/V2ParityChip';
import { ExternalSignalsCapsule } from '../components/command-center/ExternalSignalsCapsule';
import { DLQCapsule } from '../components/command-center/DLQCapsule';
import { TwinTrustTile } from '../components/command-center/TwinTrustTile';
import { ConsentHealthCapsule } from '../components/command-center/ConsentHealthCapsule';
import { DBIncidentsCapsule } from '../components/command-center/DBIncidentsCapsule';
import { SachetStatusCapsule } from '../components/command-center/SachetStatusCapsule';
import { NetworkHealthCapsule } from '../components/command-center/NetworkHealthCapsule';
import { CommandCenterHeader } from '../components/command-center/CommandCenterHeader';
import { LiveSafetyMap, getDisplayState } from '../components/command-center/LiveSafetyMap';
import { IncidentFeed } from '../components/command-center/IncidentFeed';
import { CityRiskRadar } from '../components/command-center/CityRiskRadar';
import { PredictiveAlertBar } from '../components/command-center/PredictiveAlertBar';
import { AIReasoningPanel } from '../components/command-center/AIReasoningPanel';
import { DigitalTwinPanel } from '../components/command-center/DigitalTwinPanel';
import { AITimeline } from '../components/command-center/AITimeline';
import { ThreatAssessment } from '../components/command-center/ThreatAssessment';
import { SOSAlertCard } from '../components/command-center/SOSAlertCard';
import { EscalationLiveFeed } from '../components/command-center/EscalationLiveFeed';
import RiskPanelTile from '../components/command-center/RiskPanelTile';
import TrustConfidenceChip from '../components/command-center/TrustConfidenceChip';
import { Shield, AlertTriangle, TrendingUp, Wifi, WifiOff } from 'lucide-react';
import { playAlertChime } from '../utils/emergencyChime';

const RISK_COLORS = { critical: 'text-red-400', high: 'text-orange-400', moderate: 'text-amber-400', low: 'text-emerald-400' };

// Same display-state language as the map. STALE rows are explicitly muted
// so operators never read a stale baseline pin as "live presence".
// DATA_GAP rows pop in amber so a broken pipeline never silently decays
// into a "looks like the user just stopped" interpretation.
const FRESHNESS_TONE = {
  live:     { dot: 'bg-emerald-500', ring: 'animate-ping bg-emerald-400 opacity-75', label: 'LIVE',     labelClass: 'text-emerald-300' },
  recent:   { dot: 'bg-amber-400',   ring: null,                                      label: 'RECENT',   labelClass: 'text-amber-300' },
  stale:    { dot: 'bg-slate-500',   ring: null,                                      label: 'STALE',    labelClass: 'text-slate-500' },
  data_gap: { dot: 'bg-orange-500',  ring: 'animate-ping bg-orange-400 opacity-75',   label: 'DATA GAP', labelClass: 'text-orange-300 font-bold' },
};

// Pick the more recent of two ISO strings; nullish-safe.
const maxIso = (a, b) => {
  if (!a) return b || null;
  if (!b) return a;
  return new Date(a).getTime() >= new Date(b).getTime() ? a : b;
};

/* AI Risk Intelligence — with click-to-select */
const AIRiskIntelligence = ({ highRiskUsers = [], liveUsers = [], selectedUserId, flashUserId = null, onSelectUser }) => {
  const liveById = new Map(liveUsers.map(u => [u.user_id, u]));
  return (
  <div className="rounded-xl bg-slate-900 border border-slate-800 flex flex-col h-full" data-testid="ai-risk-intelligence">
    <div className="px-3 py-2 border-b border-slate-700/50 flex items-center justify-between shrink-0">
      <div className="flex items-center gap-1.5">
        <Shield className="w-3.5 h-3.5 text-purple-400" />
        <h3 className="text-[11px] font-semibold text-white">AI Risk Intelligence</h3>
      </div>
      <span className="text-[7px] text-slate-600">Powered by Guardian AI Engine</span>
    </div>
    <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
      {highRiskUsers.length === 0 ? (
        <p className="text-[10px] text-slate-500 text-center py-4">No risk assessments yet</p>
      ) : highRiskUsers.map((u, i) => {
        const isSelected = u.user_id === selectedUserId;
        // SF-01 v2 Day 5 — row flash on dev scenario fire. The
        // flash overlays the selection style so an operator can fire
        // a scenario, see the result chip, and watch the target row
        // glow amber for 3s — without losing the "selected purple"
        // visual context.
        const isFlashing = u.user_id === flashUserId;
        const liveRow = liveById.get(u.user_id);
        const display = getDisplayState(liveRow?.last_seen_at, liveRow?.last_ping_at, liveRow?.location_source);
        const tone = FRESHNESS_TONE[display];
        return (
          <div
            key={i}
            className={`p-2 rounded-lg cursor-pointer transition-all ${
              isFlashing
                ? 'bg-amber-500/20 border border-amber-400/60 ring-2 ring-amber-400/40 shadow-[0_0_18px_rgba(251,191,36,0.35)] animate-pulse'
                : isSelected
                  ? 'bg-purple-500/15 border border-purple-500/40 ring-1 ring-purple-500/20'
                  : 'bg-slate-700/20 border border-slate-700/40 hover:bg-slate-700/30'
            }`}
            onClick={() => onSelectUser(u.user_id)}
            data-testid={`high-risk-user-${i}`}
            data-flashing={isFlashing ? 'true' : 'false'}
          >
            <div className="flex items-center justify-between mb-1 gap-2">
              <div className="flex items-center gap-1.5 min-w-0">
                <span className="relative inline-flex w-2 h-2 shrink-0" title={`Location data: ${tone.label}`}>
                  {tone.ring && <span className={`absolute inline-flex w-full h-full rounded-full ${tone.ring}`} />}
                  <span className={`relative inline-flex w-2 h-2 rounded-full ${tone.dot}`} />
                </span>
                <span className="text-[10px] text-slate-300 truncate">{u.user_name}</span>
                <span className={`text-[8px] font-mono font-bold tracking-wider ${tone.labelClass}`} data-testid={`hr-tier-${i}`}>{tone.label}</span>
              </div>
              <div className="flex items-center gap-1.5 shrink-0">
                <span className={`text-sm font-bold font-mono ${RISK_COLORS[u.risk_level] || RISK_COLORS.low}`}>{(u.final_score * 10).toFixed(1)}</span>
                <span className={`text-[8px] uppercase font-medium ${RISK_COLORS[u.risk_level] || RISK_COLORS.low}`}>{u.risk_level}</span>
              </div>
            </div>
            {u.top_factors?.slice(0, 2).map((f, j) => (
              <div key={j} className="flex items-start gap-1 mt-0.5">
                <AlertTriangle className={`w-2.5 h-2.5 mt-0.5 shrink-0 ${RISK_COLORS[u.risk_level] || 'text-slate-500'}`} />
                <span className="text-[9px] text-slate-400 truncate">{f.description}</span>
              </div>
            ))}
            <div className="mt-1 flex items-center gap-1">
              <TrendingUp className="w-2.5 h-2.5 text-amber-500" />
              <span className="text-[9px] text-amber-400 truncate">{u.action_detail || u.recommended_action}</span>
            </div>
            {/* SB-01 Day 3 — Operator Confidence Engine.
                Render an "Adaptive Intelligence" chip only when Hermes
                is actually doing something: a multiplier < 1.0 means
                a softened weight; verdicts >= 5 confirms the data is
                trusted. New users (source === "no feedback yet")
                render nothing — clean UI. */}
            {(() => {
              const att = u.attenuation;
              if (!att || !att.source || att.source === "no feedback yet") return null;
              const mults = att.multipliers || {};
              const softened = Object.entries(mults)
                .filter(([, m]) => Number(m) < 1.0)
                .sort((a, b) => Number(a[1]) - Number(b[1])); // most-softened first
              if (softened.length === 0) return null;
              const [signalKey, mult] = softened[0];
              const dropPct = Math.round((1.0 - Number(mult)) * 100);
              return (
                <div
                  className="mt-1 flex items-center gap-1 px-1.5 py-0.5 rounded bg-cyan-500/10 border border-cyan-500/20"
                  data-testid={`adaptive-intel-${u.user_id}`}
                  title={`Hermes learning loop: ${att.source}`}
                >
                  <span className="text-[9px] text-cyan-300 font-medium">⚙️ Adaptive</span>
                  <span className="text-[9px] text-slate-300 capitalize">{signalKey}</span>
                  <span className="text-[9px] text-cyan-400 font-mono">-{dropPct}%</span>
                  <span className="text-[8px] text-slate-500 ml-auto">{att.verdicts}v</span>
                </div>
              );
            })()}
          </div>
        );
      })}
    </div>
  </div>
  );
};

export default function CommandCenterPage() {
  const { user } = useAuth();
  const navigate = useNavigate();

  const [metrics, setMetrics] = useState(null);
  const [commandData, setCommandData] = useState(null);
  const [journeys, setJourneys] = useState([]);
  const [queueHealth, setQueueHealth] = useState({});
  const [sseEvents, setSseEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [heatmapData, setHeatmapData] = useState([]);
  const [showHeatmap, setShowHeatmap] = useState(true);
  const [highRiskUsers, setHighRiskUsers] = useState([]);
  // Live monitored-users layer for the map. Hydrated from highRiskUsers
  // (now carrying lat/lng/last_seen_at/location_source) and patched in
  // place by WS `live_location.*` deltas — never refetched on its own.
  const [liveUsers, setLiveUsers] = useState([]);

  // Selected user state (drives AI Reasoning, Digital Twin, Timeline)
  const [selectedUserId, setSelectedUserId] = useState(null);
  const [userRiskData, setUserRiskData] = useState(null);
  const [userBaseline, setUserBaseline] = useState(null);
  const [userDigitalTwin, setUserDigitalTwin] = useState(null);
  const [userEnvironment, setUserEnvironment] = useState(null);
  const [userMotionTelemetry, setUserMotionTelemetry] = useState(null);
  // SF-01 v2 Day 5 — row flash on dev scenario fire. 3s decay, then
  // null. Listens for the `nischint:scenario-fired` CustomEvent
  // dispatched by DevScenarioPanel — keeps the visual storyline of
  // "button click → result chip → user row glows" intact without
  // coupling the two components directly.
  const [flashUserId, setFlashUserId] = useState(null);
  useEffect(() => {
    const handler = (e) => {
      const uid = e?.detail?.target_user_id;
      if (!uid) return;
      setFlashUserId(uid);
      const t = setTimeout(() => setFlashUserId(null), 3000);
      return () => clearTimeout(t);
    };
    window.addEventListener('nischint:scenario-fired', handler);
    return () => window.removeEventListener('nischint:scenario-fired', handler);
  }, []);
  const [userPredictions, setUserPredictions] = useState([]);
  const [userRiskHistory, setUserRiskHistory] = useState([]);
  const [userDataLoading, setUserDataLoading] = useState(false);

  // Phase 7 — Fleet change summary (perception layer). Set by WS handler
  // when a `FLEET_CHANGE_SUMMARY` event arrives. The indicator pulses for
  // ~9s then auto-fades.
  const [fleetChange, setFleetChange] = useState(null);

  // Phase 2 — refs so the WS handler (captured at connect time) can read
  // the latest selectedUserId / refetch fn without re-establishing the WS
  // on every selection change.
  const selectedUserIdRef = useRef(null);
  const fetchSelectedUserRef = useRef(null);
  useEffect(() => { selectedUserIdRef.current = selectedUserId; }, [selectedUserId]);


  // Alert system state
  const [headerFlashing, setHeaderFlashing] = useState(false);
  const [newCriticalCount, setNewCriticalCount] = useState(0);
  const [alertsMuted, setAlertsMuted] = useState(false);
  const [mapFocusTarget, setMapFocusTarget] = useState(null);
  const [newIncidentIds, setNewIncidentIds] = useState(new Set());
  const previousIdsRef = useRef(new Set());
  const isFirstLoadRef = useRef(true);

  // Demo mode state
  const [demoMode, setDemoMode] = useState(false);
  const [demoStatus, setDemoStatus] = useState(null);
  const demoPollingRef = useRef(null);

  // WebSocket state for real-time streaming
  const [wsConnected, setWsConnected] = useState(false);
  const wsRef = useRef(null);
  const wsReconnectRef = useRef(null);

  // Real-time SOS alert state
  const [activeAlert, setActiveAlert] = useState(null);
  const [aiSuggestions, setAiSuggestions] = useState(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [realtimeSOS, setRealtimeSOS] = useState([]);

  // Escalation live feed state
  const [escalationEvents, setEscalationEvents] = useState([]);

  const isAuthorized = user?.role === 'admin' || user?.role === 'operator' ||
    user?.roles?.includes('admin') || user?.roles?.includes('operator');

  // Init notification permission
  useEffect(() => {
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission();
    }
  }, []);

  const triggerAlert = useCallback((newCriticals) => {
    if (!alertsMuted) {
      const top = newCriticals[0];
      const sev = (top?.severity === 'critical' || top?.incident_type === 'sos') ? 'critical'
        : top?.severity === 'high' ? 'medium' : 'low';
      playAlertChime(sev);
    }
    // Reset then re-apply flash so the CSS animation replays
    setHeaderFlashing(false);
    requestAnimationFrame(() => setHeaderFlashing(true));
    setTimeout(() => setHeaderFlashing(false), 1200);
    setNewCriticalCount(newCriticals.length);
    const ids = new Set(newCriticals.map(i => i.id));
    setNewIncidentIds(ids);
    if (newCriticals[0]) {
      const loc = { lat: 19.076 + (Math.random() - 0.5) * 0.04, lng: 72.877 + (Math.random() - 0.5) * 0.04 };
      setMapFocusTarget(loc);
      if ('Notification' in window && Notification.permission === 'granted') {
        new Notification('COMMAND CENTER — CRITICAL INCIDENT', {
          body: `${newCriticals[0].senior_name || newCriticals[0].user_id || 'Unknown'} — ${newCriticals[0].incident_type || 'Critical'}`,
          icon: '/favicon.ico',
          tag: `cc-${newCriticals[0].id}`,
          requireInteraction: true,
        });
      }
    }
    setTimeout(() => { setNewCriticalCount(0); setNewIncidentIds(new Set()); }, 10000);
  }, [alertsMuted]);

  // ── WebSocket Connection for Real-Time Incident Streaming ──
  const connectWebSocket = useCallback(() => {
    const token = getToken();
    if (!token) return;

    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const wsUrl = `${protocol}://${window.location.host}/api/ws/command-center?token=${encodeURIComponent(token)}`;

    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log('[CC-WS] Connected');
        setWsConnected(true);
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          const msgType = msg.type;

          if (msgType === 'ping') {
            ws.send(JSON.stringify({ type: 'pong' }));
            return;
          }

          if (msgType === 'connected') {
            console.log('[CC-WS] Authenticated:', msg.data);
            return;
          }

          // Real-time system_health_delta — emitted ONLY on threshold
          // crossings, never on every metric tick (golden rule).
          if (msgType === 'system_health_delta') {
            try {
              window.dispatchEvent(new CustomEvent('cc:system_health_delta', { detail: msg.data || msg }));
            } catch (_) { /* ignore */ }
            return;
          }

          // Handle SOS alerts from WebSocket
          if (msgType === 'SOS_ALERT' || msgType === 'sos_triggered') {
            const alertData = msg.data || msg;
            const sosEvent = {
              id: alertData.incident_id || alertData.sos_id || `ws-${Date.now()}`,
              incident_type: 'sos',
              severity: 'critical',
              user_name: alertData.user_name,
              user_id: alertData.user_id,
              lat: alertData.lat,
              lng: alertData.lng,
              risk_score: alertData.risk_score || 7.6,
              trigger_type: alertData.trigger_type,
              created_at: msg.timestamp || new Date().toISOString(),
              status: 'active',
              type: 'sos_triggered',
            };

            // Show alert popup
            setActiveAlert(sosEvent);
            setAiSuggestions(null);
            setAiLoading(true);

            // Add to real-time SOS list for map display
            setRealtimeSOS(prev => [sosEvent, ...prev].slice(0, 20));

            // Add to SSE events for incident feed
            setSseEvents(prev => [sosEvent, ...prev].slice(0, 50));

            // Trigger visual/audio alerts
            triggerAlert([sosEvent]);

            // Focus map on incident location
            if (alertData.lat && alertData.lng) {
              setMapFocusTarget({ lat: alertData.lat, lng: alertData.lng });
            }

            // Request AI suggestions via WebSocket
            if (ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify({
                type: 'request_ai_response',
                incident_id: sosEvent.id,
                data: alertData,
              }));
            }
          }

          // Handle AI response
          if (msgType === 'ai_response') {
            setAiSuggestions(msg.data);
            setAiLoading(false);
          }

          // Handle incident updates
          if (['incident_created', 'incident_updated', 'emergency_triggered'].includes(msgType)) {
            const eventData = msg.data || msg;
            const event = { ...eventData, type: msgType, timestamp: msg.timestamp || new Date().toISOString() };
            setSseEvents(prev => [event, ...prev].slice(0, 50));
          }

          // Handle escalation_update events — live call chain feed
          if (msgType === 'escalation_update') {
            const escalationData = msg.data || msg;
            setEscalationEvents(prev => [escalationData, ...prev].slice(0, 50));

            // Play alert sound for active escalations
            if (escalationData.status === 'started' || escalationData.status === 'exhausted') {
              if (!alertsMuted) playAlertChime('critical');
            }
          }

          // Handle live tracking events (UPGRADE 3)
          if (msgType === 'live_tracking_started' || msgType === 'live_tracking_ended') {
            const eventData = msg.data || msg;
            const event = {
              id: `tracking-${Date.now()}`,
              type: msgType,
              incident_type: 'live_tracking',
              severity: 'low',
              senior_name: eventData.user_name || 'Unknown',
              user_name: eventData.user_name,
              user_id: eventData.user_id,
              status: msgType === 'live_tracking_started' ? 'active' : 'ended',
              tracking_url: eventData.tracking_url,
              token: eventData.token,
              created_at: msg.timestamp || new Date().toISOString(),
            };
            setSseEvents(prev => [event, ...prev].slice(0, 50));
          }

          // Handle tracking stop + deviation events
          if (msgType === 'tracking_stop_detected' || msgType === 'tracking_deviation') {
            const eventData = msg.data || msg;
            const event = {
              id: `trail-${Date.now()}`,
              type: msgType,
              incident_type: msgType === 'tracking_stop_detected' ? 'tracking_stop' : 'tracking_deviation',
              severity: msgType === 'tracking_deviation' ? 'medium' : 'low',
              senior_name: eventData.user_name || 'Unknown',
              user_name: eventData.user_name,
              detail: eventData.detail || '',
              status: 'active',
              created_at: msg.timestamp || new Date().toISOString(),
            };
            setSseEvents(prev => [event, ...prev].slice(0, 50));
          }

          // Handle geofence zone events
          if (['safe_zone_exit', 'unknown_area_entry', 'safe_zone_arrival', 'danger_zone_entry'].includes(msgType)) {
            const eventData = msg.data || msg;
            const event = {
              id: `zone-${Date.now()}`,
              type: msgType,
              incident_type: msgType,
              severity: eventData.severity || 'info',
              senior_name: eventData.user_name || 'Unknown',
              user_name: eventData.user_name,
              detail: eventData.detail || '',
              status: 'active',
              created_at: msg.timestamp || new Date().toISOString(),
            };
            setSseEvents(prev => [event, ...prev].slice(0, 50));
          }

          // Phase 2 — events previously routed via SSE only
          if (['safety_risk_alert', 'fake_call_incoming'].includes(msgType)) {
            const eventData = msg.data || msg;
            const event = {
              ...eventData,
              type: msgType,
              timestamp: msg.timestamp || new Date().toISOString(),
            };
            setSseEvents(prev => [event, ...prev].slice(0, 50));
            if (msgType === 'safety_risk_alert' && eventData.severity === 'critical') {
              triggerAlert([event]);
            }
          }

          // Phase 2 — risk score change for the currently selected user
          // refetches the unified per-user payload (single round-trip).
          if (msgType === 'risk_score_change') {
            const eventData = msg.data || msg;
            const eventUserId = eventData.user_id || eventData.userId;
            if (eventUserId && eventUserId === selectedUserIdRef.current) {
              fetchSelectedUserRef.current?.(eventUserId);
            }
          }

          // Phase 3 — live Digital Twin deviation delta. Patches the selected
          // user's `digital_twin.live_deviation` in place — no refetch.
          if (msgType === 'twin_delta') {
            const eventData = msg.data || msg;
            const eventUserId = eventData.user_id;
            const newDeviation = eventData.live_deviation;
            if (eventUserId === selectedUserIdRef.current && newDeviation) {
              setUserDigitalTwin(prev => ({
                ...(prev || {}),
                live_deviation: newDeviation,
              }));
            }
          }

          // Phase 7 — Fleet change summary (perception layer). Separate
          // event from COMMAND_CENTER_DELTA: gives the operator a tiny,
          // glanceable badge ("3 zones updated · 1 ↑ HIGH risk") instead
          // of forcing them to parse dotted-path deltas.
          if (msgType === 'FLEET_CHANGE_SUMMARY') {
            const eventData = msg.data || msg;
            setFleetChange({
              timestamp: eventData.timestamp || msg.timestamp || new Date().toISOString(),
              summary: eventData.summary || {},
              breakdown: Array.isArray(eventData.breakdown) ? eventData.breakdown : [],
            });
            // Dev-mode log
            try {
              const debug = (typeof window !== 'undefined') && (
                new URL(window.location.href).searchParams.get('debug_ws') === 'true' ||
                window.localStorage?.getItem('debug_ws') === 'true'
              );
              if (debug) {
                const s = eventData.summary || {};
                console.log(`[FLEET_CHANGE] updated=${s.cells_updated || 0} escalated=${s.cells_escalated || 0} deescalated=${s.cells_deescalated || 0}`);
              }
            } catch (_) { /* ignore */ }
          }


          // Phase 5 — canonical structured delta envelope. Single source of
          // truth for risk / live_deviation / live_location / environment /
          // active_event patches. Per-namespace dispatch + stale-timestamp
          // rejection via applyDelta utility.
          if (msgType === 'COMMAND_CENTER_DELTA') {
            const envelope = msg.data || msg;
            // Hardening: record every frame for the WS Inspector regardless
            // of whether it matches the selected user — gives developers
            // full visibility into the live stream.
            try { recordFrame(envelope); } catch (_) { /* ignore */ }

            const eventUserId = envelope.user_id;
            const changes = envelope.changes || {};
            // Group dotted-path changes by their top-level namespace
            const byNs = {};
            for (const path of Object.keys(changes)) {
              const dot = path.indexOf('.');
              const ns = dot > 0 ? path.slice(0, dot) : path;
              if (!byNs[ns]) byNs[ns] = {};
              byNs[ns][path] = changes[path];
            }

            // Live location patches MUST run for ALL users (not just the
            // selected one) so the Live Safety Map reflects every active
            // device in real time.
            if (byNs.live_location) {
              const lat = byNs.live_location['live_location.lat'];
              const lng = byNs.live_location['live_location.lng'];
              const riskLevel = byNs.live_location['live_location.risk_level'];
              setLiveUsers(prev => {
                const idx = prev.findIndex(u => u.user_id === eventUserId);
                const ts = envelope.timestamp || new Date().toISOString();
                if (idx >= 0) {
                  const next = prev.slice();
                  next[idx] = {
                    ...next[idx],
                    ...(lat != null ? { lat: Number(lat) } : {}),
                    ...(lng != null ? { lng: Number(lng) } : {}),
                    ...(riskLevel ? { risk_level: String(riskLevel).toLowerCase() } : {}),
                    last_seen_at: ts,
                    // Any inbound live_location delta proves the data
                    // pipeline is alive, so we bump last_ping_at too.
                    last_ping_at: ts,
                    location_source: 'session',
                  };
                  return next;
                }
                if (lat != null && lng != null) {
                  return [...prev, {
                    user_id: eventUserId,
                    user_name: 'Active user',
                    risk_level: riskLevel ? String(riskLevel).toLowerCase() : 'low',
                    final_score: 0,
                    lat: Number(lat),
                    lng: Number(lng),
                    last_seen_at: ts,
                    last_ping_at: ts,
                    location_source: 'session',
                  }];
                }
                return prev;
              });
            }

            if (eventUserId !== selectedUserIdRef.current) return;

            const wrapped = (nsChanges) => ({
              version: envelope.version,
              timestamp: envelope.timestamp,
              user_id: eventUserId,
              changes: nsChanges,
            });

            // Risk
            if (byNs.risk) {
              const stripped = Object.fromEntries(
                Object.entries(byNs.risk).map(([k, v]) => [k.replace(/^risk\./, ''), v])
              );
              setUserRiskData(prev => {
                const result = applyDelta(prev || {}, wrapped(stripped), 'risk');
                deltaMetrics.recordApply(result.reason);
                if (!result.applied && result.reason !== 'stale_timestamp' && process.env.NODE_ENV !== 'production') {
                  console.warn('[CC-DELTA] risk rejected:', result.reason);
                }
                return result.state;
              });
            }
            // Live deviation → patches into digitalTwin.live_deviation
            if (byNs.live_deviation) {
              setUserDigitalTwin(prev => {
                const result = applyDelta(prev || {}, wrapped(byNs.live_deviation), 'live_deviation');
                deltaMetrics.recordApply(result.reason);
                if (!result.applied && result.reason !== 'stale_timestamp' && process.env.NODE_ENV !== 'production') {
                  console.warn('[CC-DELTA] live_deviation rejected:', result.reason);
                }
                return result.state;
              });
            }
            // Live location → fleet-level patch already applied above for
            // ALL users. Trigger a per-user unified refetch only when the
            // risk band actually flips on the *currently selected* user.
            if (byNs.live_location && Object.keys(byNs.live_location).some(k => k.endsWith('.risk_level'))) {
              fetchSelectedUserRef.current?.(eventUserId);
            }
          }

        } catch (e) {
          console.error('[CC-WS] Parse error:', e);
        }
      };

      ws.onclose = (e) => {
        console.log('[CC-WS] Disconnected:', e.code, e.reason);
        setWsConnected(false);
        wsRef.current = null;
        // Auto-reconnect after 3s
        if (!e.wasClean || e.code !== 1000) {
          wsReconnectRef.current = setTimeout(connectWebSocket, 3000);
        }
      };

      ws.onerror = () => {
        setWsConnected(false);
      };
    } catch (e) {
      console.error('[CC-WS] Connection error:', e);
    }
  }, [triggerAlert]);

  // Connect WebSocket on mount
  useEffect(() => {
    if (!isAuthorized) return;
    connectWebSocket();
    return () => {
      if (wsRef.current) {
        wsRef.current.close(1000, 'unmount');
      }
      clearTimeout(wsReconnectRef.current);
    };
  }, [isAuthorized, connectWebSocket]);

  // Alert card handlers
  const handleTrackLive = useCallback(() => {
    if (activeAlert?.lat && activeAlert?.lng) {
      setMapFocusTarget({ lat: activeAlert.lat, lng: activeAlert.lng });
    }
  }, [activeAlert]);

  const handleCallGuardian = useCallback(() => {
    console.log('Call guardian for:', activeAlert?.user_id);
  }, [activeAlert]);

  const handleAcknowledge = useCallback(async () => {
    if (activeAlert?.id && wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'ack_incident',
        incident_id: activeAlert.id,
      }));
    }
    try {
      if (activeAlert?.id && !activeAlert.id.startsWith('ws-')) {
        await api.patch(`/incidents/${activeAlert.id}/acknowledge?channel=command-center`);
      }
    } catch { /* silent */ }
    setActiveAlert(null);
    setAiSuggestions(null);
  }, [activeAlert]);

  const handleDismissAlert = useCallback(() => {
    setActiveAlert(null);
    setAiSuggestions(null);
    setAiLoading(false);
  }, []);

  // Fetch all data in parallel
  const fetchData = useCallback(async () => {
    try {
      const requests = [
        api.get('/admin/monitoring/metrics').catch(() => null),
        api.get('/operator/command-center').catch(() => null),
        api.get('/night-guardian/sessions').catch(() => null),
        api.get('/admin/monitoring/queue-health').catch(() => null),
        api.get('/operator/city-heatmap/live').catch(() => null),
        api.get('/guardian-ai/insights/high-risk?limit=6').catch(() => null),
      ];
      const [metricsRes, cmdRes, journeyRes, queueRes, heatmapRes, hrRes] = await Promise.all(requests);

      if (metricsRes?.data) setMetrics(metricsRes.data);
      if (cmdRes?.data) {
        const incoming = cmdRes.data.active_incidents || [];
        const prevIds = previousIdsRef.current;
        if (!isFirstLoadRef.current && prevIds.size > 0) {
          const newCriticals = incoming.filter(
            i => (i.severity === 'critical' || i.incident_type === 'sos') && !prevIds.has(i.id)
          );
          if (newCriticals.length > 0) triggerAlert(newCriticals);
        }
        isFirstLoadRef.current = false;
        previousIdsRef.current = new Set(incoming.map(i => i.id));
        setCommandData(cmdRes.data);
      }
      if (journeyRes?.data?.sessions) setJourneys(journeyRes.data.sessions);
      if (queueRes?.data) setQueueHealth(queueRes.data);
      if (heatmapRes?.data?.cells) {
        setHeatmapData(heatmapRes.data.cells.map(c => ({
          lat: c.lat, lng: c.lng,
          risk_score: c.composite_score,
          risk_level: c.risk_level?.toUpperCase(),
          grid_id: c.grid_id,
          hotspot: c.hotspot,
          activity: c.activity,
        })));
      }
      if (hrRes?.data?.high_risk_users) {
        setHighRiskUsers(hrRes.data.high_risk_users);
        // Hydrate the live-users layer with everyone who has a known location.
        // Preserves any in-flight WS patches (lat/lng/last_seen_at) by merging
        // by user_id rather than replacing wholesale.
        setLiveUsers(prev => {
          const byId = new Map(prev.map(u => [u.user_id, u]));
          for (const u of hrRes.data.high_risk_users) {
            if (u.lat == null || u.lng == null) continue;
            const existing = byId.get(u.user_id);
            // If we have a live-fresh patch (source=session) within 60s, keep it.
            const existingTs = existing?.last_seen_at ? new Date(existing.last_seen_at).getTime() : 0;
            const incomingTs = u.last_seen_at ? new Date(u.last_seen_at).getTime() : 0;
            if (existing && existing.location_source === 'session' && Date.now() - existingTs < 60000 && existingTs >= incomingTs) {
              byId.set(u.user_id, {
                ...existing, ...u,
                lat: existing.lat, lng: existing.lng,
                last_seen_at: existing.last_seen_at,
                location_source: existing.location_source,
                // Preserve the freshest pipeline ping we know about.
                last_ping_at: maxIso(existing.last_ping_at, u.last_ping_at),
              });
            } else {
              byId.set(u.user_id, {
                ...existing, ...u,
                last_ping_at: maxIso(existing?.last_ping_at, u.last_ping_at),
              });
            }
          }
          return Array.from(byId.values());
        });
        // Auto-select first user if none selected
        if (!selectedUserId && hrRes.data.high_risk_users.length > 0) {
          setSelectedUserId(hrRes.data.high_risk_users[0].user_id);
        }
      }
    } catch { /* silent */ }
    setLoading(false);
  }, []);

  useEffect(() => {
    if (!isAuthorized) { navigate('/family'); return; }
    fetchData();
  }, [isAuthorized, navigate, fetchData]);

  // Phase 2 + Hardening — 10s polling removed. Initial mount triggers ONE
  // cold-start fetch (above), then the WebSocket pushes deltas. When the WS
  // reconnects after a disconnect, we fire ONE refetch to resync slow-moving
  // fleet data AND the per-user unified payload (so we never apply deltas
  // on top of stale state). The refresh button still works for manual
  // resync.
  const wasConnectedRef = useRef(false);
  useEffect(() => {
    if (wsConnected && !wasConnectedRef.current) {
      // Skip the very first connect — the mount-triggered fetchData() already ran
      if (!isFirstLoadRef.current) {
        deltaMetrics.recordReconnect();
        fetchData();
        // Hardening: also resync the per-user unified payload so any
        // missed deltas during the disconnect window don't leave the UI
        // showing stale per-user state.
        if (selectedUserIdRef.current) {
          fetchSelectedUserRef.current?.(selectedUserIdRef.current);
        }
      }
    }
    wasConnectedRef.current = wsConnected;
  }, [wsConnected, fetchData]);

  // Demo mode toggle handler
  const toggleDemo = useCallback(async () => {
    try {
      if (demoMode) {
        await api.post('/demo/stop');
        setDemoMode(false);
        setDemoStatus(null);
        clearInterval(demoPollingRef.current);
      } else {
        const res = await api.post('/demo/start');
        if (res.data?.status === 'started' || res.data?.status === 'already_running') {
          setDemoMode(true);
          // Poll demo status every 2s during demo
          demoPollingRef.current = setInterval(async () => {
            try {
              const s = await api.get('/demo/status');
              setDemoStatus(s.data);
              if (!s.data?.running) {
                setDemoMode(false);
                clearInterval(demoPollingRef.current);
                fetchData(); // Refresh command center data
              }
            } catch {}
          }, 2000);
        }
      }
    } catch (err) {
      console.warn('Demo toggle error:', err.message);
    }
  }, [demoMode, fetchData]);

  // Cleanup demo polling on unmount
  useEffect(() => {
    return () => clearInterval(demoPollingRef.current);
  }, []);

  // Per-user Command Center data — Phase 1 unified endpoint.
  // Single fetch replaces the prior 4 parallel calls
  // (risk-score, baseline, predictions, risk-history).
  const fetchSelectedUser = useCallback(async (uid) => {
    if (!uid) return;
    setUserDataLoading(true);
    try {
      const r = await operatorApi.getCommandCenterUser(uid);
      const payload = r?.data || {};
      // Versioned envelope sanity check — reject stale or unknown shapes
      if (payload.version && payload.version !== 'v1') {
        console.warn('[CC] Unknown command-center payload version:', payload.version);
      }
      setUserRiskData(payload.risk || null);
      setUserBaseline(payload.baseline || null);
      setUserDigitalTwin(payload.digital_twin || null);
      setUserEnvironment(payload.environment || null);
      setUserMotionTelemetry(payload.motion_telemetry || null);
      setUserPredictions(payload.predictions || []);
      setUserRiskHistory(payload.risk_history || []);
    } catch (e) {
      console.warn('[CC] Per-user fetch failed:', e?.message);
    } finally {
      setUserDataLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!selectedUserId) {
      setUserRiskData(null);
      setUserBaseline(null);
      setUserDigitalTwin(null);
      setUserEnvironment(null);
      setUserMotionTelemetry(null);
      setUserPredictions([]);
      setUserRiskHistory([]);
      return;
    }
    fetchSelectedUser(selectedUserId);
  }, [selectedUserId, fetchSelectedUser]);

  // Keep the latest fetcher accessible to the WS handler
  useEffect(() => { fetchSelectedUserRef.current = fetchSelectedUser; }, [fetchSelectedUser]);

  // Phase 2 — SSE removed. All real-time events now flow through the
  // Command Center WebSocket (`/api/ws/command-center`), backed by Redis
  // pub/sub. See connectWebSocket() above for the unified handler.

  if (!isAuthorized) return null;

  const incidents = commandData?.active_incidents || [];

  // Build map data — include real-time SOS events
  const realtimeIds = new Set(realtimeSOS.map(s => s.id));
  const allNewIncidentIds = new Set([...newIncidentIds, ...realtimeIds]);
  const sosMapEvents = [
    ...realtimeSOS.filter(s => s.lat && s.lng),
    ...incidents
      .filter(i => i.severity === 'critical' || i.incident_type === 'sos')
      .map(i => ({ ...i, lat: i.lat || (19.076 + (Math.random() - 0.5) * 0.05), lng: i.lng || (72.877 + (Math.random() - 0.5) * 0.05) })),
  ];

  const journeyMapData = journeys.map(j => ({
    ...j,
    location: j.location || { lat: 19.076 + (Math.random() - 0.5) * 0.08, lng: 72.877 + (Math.random() - 0.5) * 0.08 },
  }));

  if (loading) {
    return (
      <div className="h-screen bg-slate-900 text-white flex flex-col overflow-hidden" data-testid="command-center-skeleton">
        {/* Skeleton header */}
        <div className="h-[68px] shrink-0 bg-slate-800/60 border-b border-slate-700/50 px-6 flex items-center gap-4">
          <div className="w-32 h-6 bg-slate-700/50 rounded animate-pulse" />
          <div className="flex-1" />
          <div className="flex gap-3">
            {[1,2,3,4].map(i => (
              <div key={i} className="w-20 h-10 bg-slate-700/40 rounded-xl animate-pulse" />
            ))}
          </div>
        </div>
        {/* Skeleton grid */}
        <div className="flex-1 grid grid-cols-12 gap-3 p-3 min-h-0">
          <div className="col-span-12 lg:col-span-3 flex flex-col gap-3">
            <div className="flex-1 bg-slate-800/30 rounded-xl animate-pulse" />
            <div className="flex-1 bg-slate-800/30 rounded-xl animate-pulse" />
          </div>
          <div className="col-span-12 lg:col-span-6 bg-slate-800/30 rounded-xl animate-pulse" />
          <div className="col-span-12 lg:col-span-3 flex flex-col gap-3">
            <div className="flex-1 bg-slate-800/30 rounded-xl animate-pulse" />
            <div className="h-[180px] bg-slate-800/30 rounded-xl animate-pulse" />
          </div>
        </div>
        {/* Skeleton bottom panels */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 px-3 pb-3 h-[240px] shrink-0">
          {[1,2,3].map(i => (
            <div key={i} className="bg-slate-800/30 rounded-xl animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen bg-slate-900 text-white flex flex-col overflow-hidden" data-testid="command-center-page">
      {/* Row 1: Header */}
      <div className="shrink-0">
        <CommandCenterHeader
          metrics={metrics}
          incidents={incidents}
          guardianSessions={metrics?.guardian_sessions?.active || journeys.length}
          flashing={headerFlashing}
          newCriticalCount={newCriticalCount}
          alertsMuted={alertsMuted}
          onToggleMute={() => setAlertsMuted(m => !m)}
          demoMode={demoMode}
          onToggleDemo={toggleDemo}
          wsConnected={wsConnected}
        />
        {/* Phase 8 — Persistent fleet weather freshness chip */}
        <div className="px-3 py-1 flex items-center gap-2 border-b border-slate-800 bg-slate-900/40" data-testid="cc-status-strip">
          <LastCityUpdateChip wsConnected={wsConnected} fleetChange={fleetChange} />
          <div className="ml-auto flex items-center gap-2">
            <NetworkHealthCapsule />
            <V2ParityChip />
            <ExternalSignalsCapsule />
            <DLQCapsule />
            <DBIncidentsCapsule />
            <SachetStatusCapsule />
            <ConsentHealthCapsule />
            <TwinTrustTile />
            <SystemHealthCapsule />
            <LatencyHotspotsChip />
            <LoopHealthCapsule />
            <LogTailCapsule />
          </div>
        </div>
        {/* Live Risk Panel — docked, persistent. Single decision
            surface ("act now or ignore safely"). Polls every 5s. */}
        <div className="px-3 pt-2 pb-1 border-b border-slate-800 bg-slate-900/40">
          <RiskPanelTile
            limit={10}
            onIncidentClick={(inc) => {
              if (inc.user_id) setSelectedUserId(inc.user_id);
            }}
          />
          {/* OCE-01 — Trust Confidence Chip. Renders only when an
              incident/user has been selected so the panel doesn't
              reserve empty space pre-selection. */}
          {selectedUserId && (
            <div className="mt-2">
              <TrustConfidenceChip userId={selectedUserId} />
            </div>
          )}
        </div>
      </div>

      {/* SOS Alert Popup Card */}
      <SOSAlertCard
        alert={activeAlert}
        aiSuggestions={aiSuggestions}
        aiLoading={aiLoading}
        onTrackLive={handleTrackLive}
        onCallGuardian={handleCallGuardian}
        onAcknowledge={handleAcknowledge}
        onDismiss={handleDismissAlert}
      />

      {/* Demo Mode Status Bar */}
      {demoMode && demoStatus && (
        <div className="shrink-0 bg-amber-500/10 border-b border-amber-500/30 px-6 py-1.5 flex items-center gap-4" data-testid="demo-status-bar">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
            <span className="text-[10px] font-bold text-amber-400 uppercase tracking-wider">Demo Mode Active</span>
          </div>
          <span className="text-[10px] text-amber-300">
            {demoStatus.scenario_user && `Simulating: ${demoStatus.scenario_user}`}
          </span>
          <div className="flex-1" />
          <span className="text-[10px] text-amber-400 font-mono">
            Step {demoStatus.current_step}/{demoStatus.total_steps} · {demoStatus.elapsed_seconds}s
          </span>
          <div className="w-32 h-1.5 bg-slate-800 rounded-full overflow-hidden">
            <div
              className="h-full bg-amber-400 rounded-full transition-all duration-500"
              style={{ width: `${(demoStatus.current_step / demoStatus.total_steps) * 100}%` }}
            />
          </div>
        </div>
      )}

      {/* Row 2: Main 3-column grid — Left panels | Map | Right panels */}
      <div className="flex-1 grid grid-cols-1 md:grid-cols-6 lg:grid-cols-12 gap-3 p-3 min-h-0 overflow-hidden">
        {/* Left column: City Risk Radar + Predictive Intelligence + Threat Assessment */}
        <div className="col-span-1 md:col-span-2 lg:col-span-3 flex flex-col gap-3 min-h-0 overflow-y-auto">
          <CityRiskRadar heatmapData={heatmapData} />
          <PredictiveAlertBar predictions={userPredictions} riskScores={userRiskData} />
          <ThreatAssessment />
          <EscalationLiveFeed events={escalationEvents} />
        </div>

        {/* Center: Map */}
        <div className="col-span-1 md:col-span-2 lg:col-span-6 min-h-0 h-[420px] lg:h-auto relative" data-testid="cc-map-container">
          <LiveSafetyMap
            sosEvents={sosMapEvents}
            journeys={journeyMapData}
            heatmapData={showHeatmap ? heatmapData : []}
            liveUsers={liveUsers}
            selectedUserId={selectedUserId}
            onSelectUser={setSelectedUserId}
            focusTarget={mapFocusTarget}
            newIncidentIds={allNewIncidentIds}
            showHeatmap={showHeatmap}
            onToggleHeatmap={() => setShowHeatmap(h => !h)}
          />
          {/* Phase 7 — Fleet Change Indicator pulses for ~9s on each refresh */}
          <FleetChangeIndicator change={fleetChange} />
        </div>

        {/* Right column: Incident Feed + AI Timeline */}
        <div className="col-span-1 md:col-span-2 lg:col-span-3 flex flex-col gap-3 min-h-0">
          <div className="flex-1 min-h-0">
            <IncidentFeed
              incidents={incidents}
              sseEvents={sseEvents}
              onSelectIncident={(inc) => console.log('Selected:', inc)}
            />
          </div>
          <div className="h-[200px] shrink-0">
            <AITimeline
              riskHistory={userRiskHistory}
              incidents={incidents}
              loading={userDataLoading}
            />
          </div>
        </div>
      </div>

      {/* Row 3: Bottom intelligence panels */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 px-3 pb-3 h-[240px] shrink-0">
        <AIRiskIntelligence
          highRiskUsers={highRiskUsers}
          liveUsers={liveUsers}
          selectedUserId={selectedUserId}
          flashUserId={flashUserId}
          onSelectUser={setSelectedUserId}
        />
        <div className="flex flex-col gap-2">
          {/* Phase 6 — Weather chip + NISCH-012 Live Activity Class chip for the selected user.
              Both render only when their respective data slices are present in the unified payload. */}
          {(userEnvironment || userMotionTelemetry || userDataLoading) && (
            <div className="flex items-center gap-2 px-1 flex-wrap" data-testid="user-context-bar">
              {userEnvironment && <WeatherChip environment={userEnvironment} />}
              {(userMotionTelemetry || userDataLoading) && (
                <LiveActivityChip motion={userMotionTelemetry} loading={userDataLoading} />
              )}
            </div>
          )}

          {/* SF-01 v2 Day 4 — investor demo button row. Self-hides when
              the backend env flag is off OR the caller isn't an
              operator. Pure dev-environment affordance — never affects
              real telemetry, dispatch, or trust. */}
          {selectedUserId && (
            <DevScenarioPanel targetUserId={selectedUserId} />
          )}
          <div className="flex-1 min-h-0">
            <AIReasoningPanel riskData={userRiskData} loading={userDataLoading} />
          </div>
        </div>
        <DigitalTwinPanel baseline={userBaseline} riskData={userRiskData} digitalTwin={userDigitalTwin} loading={userDataLoading} />
      </div>

      {/* Hardening — Dev WS Frame Inspector (toggle via ?debug_ws=true) */}
      <WSFrameInspector />
    </div>
  );
}
