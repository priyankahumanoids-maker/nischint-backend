/**
 * NISCHINT Wearable Store — Zustand store for BLE device state.
 * Tracks paired device, connection status, battery, and events.
 */
import { create } from 'zustand';

export interface WearableDevice {
  deviceId: string;     // Backend UUID
  deviceUid: string;    // BLE peripheral ID
  name: string;
  battery: number | null;
  connected: boolean;
  lastSeen: string | null;
}

export interface WearableEvent {
  eventType: string;
  alertCategory: string;
  timestamp: string;
  guardiansNotified: number;
  escalationTriggered: boolean;
}

interface WearableState {
  device: WearableDevice | null;
  scanning: boolean;
  pairing: boolean;
  lastEvent: WearableEvent | null;
  eventHistory: WearableEvent[];

  setDevice: (device: WearableDevice | null) => void;
  setScanning: (scanning: boolean) => void;
  setPairing: (pairing: boolean) => void;
  updateBattery: (battery: number) => void;
  updateConnection: (connected: boolean) => void;
  addEvent: (event: WearableEvent) => void;
  clear: () => void;
}

export const useWearableStore = create<WearableState>((set) => ({
  device: null,
  scanning: false,
  pairing: false,
  lastEvent: null,
  eventHistory: [],

  setDevice: (device) => set({ device }),
  setScanning: (scanning) => set({ scanning }),
  setPairing: (pairing) => set({ pairing }),

  updateBattery: (battery) =>
    set((state) => ({
      device: state.device ? { ...state.device, battery } : null,
    })),

  updateConnection: (connected) =>
    set((state) => ({
      device: state.device ? { ...state.device, connected } : null,
    })),

  addEvent: (event) =>
    set((state) => ({
      lastEvent: event,
      eventHistory: [event, ...state.eventHistory].slice(0, 50),
    })),

  clear: () =>
    set({
      device: null,
      scanning: false,
      pairing: false,
      lastEvent: null,
      eventHistory: [],
    }),
}));
