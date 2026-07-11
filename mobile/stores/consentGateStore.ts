// DPDP-04-MOB — Global consent gate store.
//
// Holds the single in-flight consent request (if any) plus the
// Promise resolver wired up by `consentService.requireConsent()`.
// The `<ConsentSheet />` component subscribes here and renders the
// bottom-sheet whenever `pending != null`.
//
// Only one request is shown at a time. If two services race for
// consent simultaneously, the second is queued and shown right
// after the first resolves.

import { create } from 'zustand';

export type ConsentCategory =
  | 'location_tracking'
  | 'audio_recording'
  | 'health_vitals'
  | 'push_notifications'
  | 'biometric_sensors';

export interface ConsentPrompt {
  category: ConsentCategory;
  resolve: (granted: boolean) => void;
}

interface ConsentGateState {
  /** Currently displayed prompt, if any. */
  pending: ConsentPrompt | null;
  /** FIFO queue of prompts waiting to be shown after `pending` clears. */
  queue: ConsentPrompt[];

  /** Push a new prompt onto the queue (or render it immediately if idle). */
  enqueue: (p: ConsentPrompt) => void;
  /** Resolve the current prompt and shift the queue. */
  resolveCurrent: (granted: boolean) => void;
}

export const useConsentGateStore = create<ConsentGateState>((set, get) => ({
  pending: null,
  queue: [],
  enqueue: (p) => {
    const { pending, queue } = get();
    if (pending === null) {
      set({ pending: p });
    } else {
      set({ queue: [...queue, p] });
    }
  },
  resolveCurrent: (granted) => {
    const { pending, queue } = get();
    if (pending) {
      try { pending.resolve(granted); } catch { /* resolver errors must not crash UI */ }
    }
    const [next, ...rest] = queue;
    set({ pending: next ?? null, queue: rest });
  },
}));
