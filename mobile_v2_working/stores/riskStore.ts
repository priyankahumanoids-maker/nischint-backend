// Risk Store — Zustand store for real-time per-child risk data (SSE-driven)
import { create } from 'zustand';

export interface RiskEntry {
  child_id: string;
  child_name: string;
  lat: number;
  lng: number;
  risk: 'CRITICAL' | 'RED' | 'YELLOW' | 'GREEN';
  score: number;
  factors: string[];
  speed_kmh: number;
  last_updated: string;
  /** Monotonic version stamped by the backend `risk_emitter`.
   * Used by SSE consumers to ignore out-of-order updates. */
  version?: number;
}

interface RiskStore {
  entries: Record<string, RiskEntry>;
  updateRisk: (entry: RiskEntry) => void;
  clearAll: () => void;
}

export const useRiskStore = create<RiskStore>(function(set) {
  return {
    entries: {},

    updateRisk: function(entry: RiskEntry) {
      set(function(state) {
        return {
          entries: { ...state.entries, [entry.child_id]: entry },
        };
      });
    },

    clearAll: function() {
      set({ entries: {} });
    },
  };
});
