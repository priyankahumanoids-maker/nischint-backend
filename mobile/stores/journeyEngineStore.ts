// Journey Engine Store — Zustand state for the mobile Journey Engine v5
// Separate from the existing journeyStore (which persists session info)
// This store holds RUNTIME state: isActive, risk, alerts, connection, escalation.
import { create } from 'zustand';

export type RiskLevel = 'safe' | 'caution' | 'high' | 'critical';
export type ConnectionStatus = 'online' | 'offline' | 'reconnecting';

export interface LastLocation {
  lat: number;
  lng: number;
  accuracy?: number;
  speed?: number | null;
  ts: number;
}

export interface ActiveAlert {
  id: string;              // sos_id or event id
  type: string;            // 'sos' | 'escalation' | 'risk' | 'voice_distress'
  state: string;           // 'delivered' | 'acknowledged' | 'authority_dispatched' | ...
  message: string;
  ts: number;
  meta?: Record<string, any>;
}

export interface EscalationState {
  sos_id: string | null;
  active_layer: 'guardian' | 'authority' | null;
  authority_pre_alerted: boolean;
  authority_verified: boolean;
  current_contact_name?: string | null;
  any_guardian_acked: boolean;
  elapsed_sec: number;
}

export type BrainAction =
  | 'TRIGGER_SOS'
  | 'NOTIFY_GUARDIAN'
  | 'INCREASE_MONITORING'
  | 'LOG_ONLY'
  | null;

export interface BrainDecision {
  risk_level: RiskLevel;
  risk_score: number;
  final_score: number;
  recommended_action: BrainAction;
  executed: boolean;          // true → backend already acted autonomously
  cooldown_applied: boolean;  // true → action was downgraded; suppress UI noise
  sos_id?: string | null;
  triggers_fired?: string[];
  ts: number;
}

interface JourneyEngineState {
  isActive: boolean;
  currentRiskLevel: RiskLevel;
  currentRiskScore: number;
  lastLocation: LastLocation | null;
  activeAlert: ActiveAlert | null;
  escalationState: EscalationState;
  connectionStatus: ConnectionStatus;
  pendingQueueSize: number;

  // AI Brain decision (latest)
  lastDecision: BrainDecision | null;
  advisoryActive: boolean;  // RED/YELLOW advisory cue on UI
  autonomousSOSActive: boolean;  // backend-triggered SOS in flight (silent UX)

  // Counters (for diagnostics / dashboard)
  locationsSentTotal: number;
  sseEventsReceivedTotal: number;
  lastSyncAt: number | null;

  // Actions
  setActive: (v: boolean) => void;
  setRisk: (score: number, level: RiskLevel) => void;
  setLastLocation: (loc: LastLocation) => void;
  setAlert: (a: ActiveAlert | null) => void;
  setEscalation: (e: Partial<EscalationState>) => void;
  setConnection: (s: ConnectionStatus) => void;
  setQueueSize: (n: number) => void;
  setDecision: (d: BrainDecision) => void;
  clearAdvisory: () => void;
  bumpLocationSent: () => void;
  bumpSseReceived: () => void;
  markSync: () => void;
  reset: () => void;
}

const EMPTY_ESCALATION: EscalationState = {
  sos_id: null,
  active_layer: null,
  authority_pre_alerted: false,
  authority_verified: false,
  current_contact_name: null,
  any_guardian_acked: false,
  elapsed_sec: 0,
};

export const useJourneyEngineStore = create<JourneyEngineState>((set) => ({
  isActive: false,
  currentRiskLevel: 'safe',
  currentRiskScore: 0,
  lastLocation: null,
  activeAlert: null,
  escalationState: EMPTY_ESCALATION,
  connectionStatus: 'offline',
  pendingQueueSize: 0,
  lastDecision: null,
  advisoryActive: false,
  autonomousSOSActive: false,
  locationsSentTotal: 0,
  sseEventsReceivedTotal: 0,
  lastSyncAt: null,

  setActive: (v) => set({ isActive: v }),
  setRisk: (score, level) => set({ currentRiskScore: score, currentRiskLevel: level }),
  setLastLocation: (loc) => set({ lastLocation: loc }),
  setAlert: (a) => set({ activeAlert: a }),
  setEscalation: (e) =>
    set((s) => ({ escalationState: { ...s.escalationState, ...e } })),
  setConnection: (s) => set({ connectionStatus: s }),
  setQueueSize: (n) => set({ pendingQueueSize: n }),
  setDecision: (d) =>
    set({
      lastDecision: d,
      // Advisory cue for RED/YELLOW (silent actions) — but NOT when in cooldown
      advisoryActive:
        !d.cooldown_applied &&
        (d.recommended_action === 'NOTIFY_GUARDIAN' ||
          d.recommended_action === 'INCREASE_MONITORING'),
      // Autonomous SOS state when backend already fired an SOS silently
      autonomousSOSActive:
        d.executed && d.recommended_action === 'TRIGGER_SOS' && !!d.sos_id,
      // Mirror risk into top-level fields for convenience
      currentRiskScore: d.risk_score,
      currentRiskLevel: d.risk_level,
    }),
  clearAdvisory: () => set({ advisoryActive: false }),
  bumpLocationSent: () =>
    set((s) => ({ locationsSentTotal: s.locationsSentTotal + 1 })),
  bumpSseReceived: () =>
    set((s) => ({ sseEventsReceivedTotal: s.sseEventsReceivedTotal + 1 })),
  markSync: () => set({ lastSyncAt: Date.now() }),
  reset: () =>
    set({
      isActive: false,
      currentRiskLevel: 'safe',
      currentRiskScore: 0,
      activeAlert: null,
      escalationState: EMPTY_ESCALATION,
      lastDecision: null,
      advisoryActive: false,
      autonomousSOSActive: false,
    }),
}));
