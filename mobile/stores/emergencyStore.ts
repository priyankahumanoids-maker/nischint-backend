// Emergency State Store — reactive UI state for Silent SOS
import { create } from 'zustand';
import AsyncStorage from '@react-native-async-storage/async-storage';

const STORAGE_KEY = 'nischint:active_emergency';

interface EmergencyState {
  isActive: boolean;
  eventId: string | null;
  triggerSource: string | null;
  startedAt: string | null;
  isTriggering: boolean;

  activate: (eventId: string, trigger: string) => Promise<void>;
  deactivate: () => Promise<void>;
  setTriggering: (v: boolean) => void;
  restore: () => Promise<boolean>;
}

export const useEmergencyStore = create<EmergencyState>((set) => ({
  isActive: false,
  eventId: null,
  triggerSource: null,
  startedAt: null,
  isTriggering: false,

  activate: async (eventId: string, trigger: string) => {
    const startedAt = new Date().toISOString();
    set({ isActive: true, eventId, triggerSource: trigger, startedAt, isTriggering: false });
    await AsyncStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ event_id: eventId, started_at: startedAt, trigger }),
    );
  },

  deactivate: async () => {
    set({ isActive: false, eventId: null, triggerSource: null, startedAt: null, isTriggering: false });
    await AsyncStorage.removeItem(STORAGE_KEY);
  },

  setTriggering: (v: boolean) => set({ isTriggering: v }),

  restore: async () => {
    try {
      const stored = await AsyncStorage.getItem(STORAGE_KEY);
      if (!stored) return false;
      const data = JSON.parse(stored);
      set({
        isActive: true,
        eventId: data.event_id,
        triggerSource: data.trigger,
        startedAt: data.started_at,
      });
      return true;
    } catch {
      return false;
    }
  },
}));
