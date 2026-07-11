// Journey Session Store — persisted via Zustand persist + AsyncStorage
// Stores: session_id, status, last_location, last_update_time
import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import AsyncStorage from '@react-native-async-storage/async-storage';

console.log('[JourneyStore] Initialized');

interface LastLocation {
  lat: number;
  lng: number;
  ts: string;
}

interface JourneySession {
  session_id: string;
  status: string;
  start_time: string | null;
}

interface JourneyState {
  session: JourneySession | null;
  last_location: LastLocation | null;
  isReady: boolean;

  setSession: (session_id: string, status: string, start_time?: string | null) => void;
  updateStatus: (status: string) => void;
  setLastLocation: (lat: number, lng: number) => void;
  clearSession: () => void;
  setIsReady: (ready: boolean) => void;
}

export var useJourneyStore = create<JourneyState>()(
  persist(
    function(set, get) {
      return {
        session: null,
        last_location: null,
        isReady: false,

        setSession: function(session_id: string, status: string, start_time?: string | null) {
          console.log('[SESSION_PERSIST] Saved:', session_id);
          set({ session: { session_id: session_id, status: status, start_time: start_time || null } });
        },

        updateStatus: function(status: string) {
          var current = get().session;
          if (current) {
            set({ session: { session_id: current.session_id, status: status, start_time: current.start_time } });
          }
        },

        setLastLocation: function(lat: number, lng: number) {
          set({ last_location: { lat: lat, lng: lng, ts: new Date().toISOString() } });
        },

        clearSession: function() {
          console.log('[SESSION_CLEARED]');
          set({ session: null, last_location: null });
        },

        setIsReady: function(ready: boolean) { set({ isReady: ready }); },
      };
    },
    {
      name: 'nischint-journey-session',
      storage: createJSONStorage(function() { return AsyncStorage; }),
      partialize: function(state) {
        return { session: state.session, last_location: state.last_location };
      },

      onRehydrateStorage: function() {
        return function(state: any, error: any) {
          if (error) {
            console.log('[JourneyStore] Rehydrate error (continuing anyway):', error);
          }
          console.log('[JourneyStore] Rehydrated:', state && state.session);
          // Always mark ready — even if rehydration failed or state is null —
          // so the Journey screen does not stay stuck on a loading gate.
          // Use setTimeout so zustand has committed before we flip the flag.
          setTimeout(function() {
            try {
              useJourneyStore.setState({ isReady: true });
            } catch (e) {
              console.log('[JourneyStore] isReady set failed:', e);
            }
          }, 0);
        };
      },
    }
  )
);
