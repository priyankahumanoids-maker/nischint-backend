// Zustand store for real-time escalation tracking
// Receives escalation_update events via SSE and drives the EscalationTracker UI
//
// Hardened: Event ordering guard — status rank prevents UI regression
// (e.g., incoming "ringing" after "answered" is dropped)
import { create } from 'zustand';

export type EscalationStatus =
  | 'started'
  | 'calling'
  | 'no_answer'
  | 'voicemail'
  | 'answered'
  | 'failed'
  | 'sms_blast'
  | 'exhausted';

export interface EscalationGuardian {
  name: string;
  phone: string;
  priority: number;
  source: string;
}

export interface EscalationState {
  event_id: string;
  child_name: string;
  status: EscalationStatus;
  current_guardian: EscalationGuardian | null;
  sequence: number;
  total_guardians: number;
  resolved_by: string | null;
  timestamp: string;
}

// Monotonically increasing rank — higher = more final
// An incoming event is only applied if its rank >= current rank
var STATUS_RANK: Record<EscalationStatus, number> = {
  started: 0,
  calling: 1,
  no_answer: 2,
  voicemail: 2,
  failed: 2,
  answered: 10,
  sms_blast: 8,
  exhausted: 9,
};

function shouldApply(incoming: EscalationState, current: EscalationState | null): boolean {
  // Different event — always apply
  if (!current || incoming.event_id !== current.event_id) return true;

  var incomingRank = STATUS_RANK[incoming.status] ?? 0;
  var currentRank = STATUS_RANK[current.status] ?? 0;

  // Same status rank but higher sequence — allow (next guardian)
  if (incomingRank === currentRank && incoming.sequence > current.sequence) return true;

  // Higher rank — allow
  if (incomingRank >= currentRank) return true;

  // Lower rank — reject (prevents regression: "answered" → "calling")
  return false;
}

interface EscalationStoreState {
  escalation: EscalationState | null;
  history: EscalationState[];
  setEscalation: (data: EscalationState) => void;
  clearEscalation: () => void;
}

export const useEscalationStore = create<EscalationStoreState>(function (set, get) {
  return {
    escalation: null,
    history: [],

    setEscalation: function (data: EscalationState) {
      var current = get().escalation;

      // Event ordering guard
      if (!shouldApply(data, current)) {
        return; // Drop regressive event
      }

      set(function (state) {
        var newHistory = [data, ...state.history].slice(0, 50);
        return {
          escalation: data,
          history: newHistory,
        };
      });

      // Auto-clear after 30s on terminal states
      var isTerminal = data.status === 'answered' || data.status === 'exhausted';
      if (isTerminal) {
        setTimeout(function () {
          set(function (state) {
            if (state.escalation && state.escalation.event_id === data.event_id) {
              return { escalation: null };
            }
            return {};
          });
        }, 30000);
      }
    },

    clearEscalation: function () {
      set({ escalation: null });
    },
  };
});
