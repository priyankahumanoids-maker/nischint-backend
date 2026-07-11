// Alert Store — persisted via Zustand + AsyncStorage
// Stores SSE/push alerts so they survive app reload
import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import AsyncStorage from '@react-native-async-storage/async-storage';
import type { UnifiedAlert } from '@/services/alertResolver';

const ALERT_TTL_MS = 2 * 60 * 1000; // 2 minutes auto-expiry
const MAX_ALERTS = 50;

// Critical alert types that NEVER auto-expire
const CRITICAL_TYPES = new Set(['emergency_triggered', 'auto_escalated']);

interface AlertStore {
  alerts: UnifiedAlert[];
  seenIds: string[];
  pushAlert: (alert: UnifiedAlert) => void;
  removeAlert: (id: string) => void;
  acknowledgeAlert: (id: string) => void;
  pruneExpired: () => void;
  isDuplicate: (id: string) => boolean;
  clearAll: () => void;
}

export const useAlertStore = create<AlertStore>()(
  persist(
    function(set, get) {
      return {
        alerts: [],
        seenIds: [],

        pushAlert: function(alert: UnifiedAlert) {
          set(function(state) {
            // Dedup: skip if already seen
            if (state.seenIds.includes(alert.id)) {
              return state;
            }
            // Add to seen IDs (cap at 200)
            var newSeenIds = [alert.id, ...state.seenIds].slice(0, 200);
            // Add alert, dedup by ID, cap at MAX
            var filtered = state.alerts.filter(function(a) { return a.id !== alert.id; });
            return {
              alerts: [alert, ...filtered].slice(0, MAX_ALERTS),
              seenIds: newSeenIds,
            };
          });
        },

        removeAlert: function(id: string) {
          set(function(state) {
            return {
              alerts: state.alerts.filter(function(a) { return a.id !== id; }),
            };
          });
        },

        acknowledgeAlert: function(id: string) {
          set(function(state) {
            return {
              alerts: state.alerts.map(function(a) {
                if (a.id === id) {
                  return { ...a, acknowledged: true };
                }
                return a;
              }),
            };
          });
        },

        pruneExpired: function() {
          var now = Date.now();
          set(function(state) {
            return {
              alerts: state.alerts.filter(function(a) {
                // CRITICAL LOCK: never auto-expire EMERGENCY/ESCALATION
                if (CRITICAL_TYPES.has(a.alert_type)) return true;
                var age = now - new Date(a.created_at).getTime();
                return age < ALERT_TTL_MS;
              }),
            };
          });
        },

        isDuplicate: function(id: string) {
          return get().seenIds.includes(id);
        },

        clearAll: function() {
          set({ alerts: [], seenIds: [] });
        },
      };
    },
    {
      name: 'nischint-alerts',
      storage: createJSONStorage(function() { return AsyncStorage; }),
      partialize: function(state) {
        return { alerts: state.alerts, seenIds: state.seenIds };
      },
    }
  )
);
