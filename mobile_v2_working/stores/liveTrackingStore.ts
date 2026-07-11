// Live tracking Zustand store — SSE data layer, separate from UI
// Features: dedup, trail cap, stale detection (>30s)
import { create } from 'zustand';

export interface TrailPoint {
  lat: number;
  lng: number;
}

export interface ChildLocation {
  lat: number;
  lng: number;
  speed: number;
  zone: string;
  risk: string;
  ts: string;
  child_id: string;
  child_name: string;
  child_role: string;
  trail: TrailPoint[];
}

interface LiveTrackingState {
  children: Record<string, ChildLocation>;
  updateChild: (childId: string, data: Omit<ChildLocation, 'trail' | 'child_id'> & { child_id: string }) => void;
  clearChild: (childId: string) => void;
  clearAll: () => void;
}

var MAX_TRAIL = 40;
var STALE_THRESHOLD_S = 30;

// Helper: check if a child location is stale (>30s since last update)
export function isChildStale(loc: ChildLocation): boolean {
  if (!loc || !loc.ts) return true;
  var sec = (Date.now() - new Date(loc.ts).getTime()) / 1000;
  return sec > STALE_THRESHOLD_S;
}

export var useLiveTrackingStore = create<LiveTrackingState>(function(set) {
  return {
    children: {},

    updateChild: function(childId, data) {
      set(function(state) {
        var existing = state.children[childId];

        // Deduplicate: skip trail if same lat/lng
        if (existing && existing.lat === data.lat && existing.lng === data.lng) {
          var updated: Record<string, ChildLocation> = {};
          for (var k in state.children) { updated[k] = state.children[k]; }
          updated[childId] = {
            lat: data.lat,
            lng: data.lng,
            speed: data.speed,
            zone: data.zone,
            risk: data.risk,
            ts: data.ts,
            child_id: data.child_id,
            child_name: data.child_name,
            child_role: data.child_role || 'child',
            trail: existing.trail,
          };
          return { children: updated };
        }

        // Build trail: append old position, cap at MAX_TRAIL
        var oldTrail = existing ? existing.trail : [];
        var newTrail = existing
          ? oldTrail.concat([{ lat: existing.lat, lng: existing.lng }])
          : oldTrail;
        if (newTrail.length > MAX_TRAIL) {
          newTrail = newTrail.slice(newTrail.length - MAX_TRAIL);
        }

        var result: Record<string, ChildLocation> = {};
        for (var j in state.children) { result[j] = state.children[j]; }
        result[childId] = {
          lat: data.lat,
          lng: data.lng,
          speed: data.speed,
          zone: data.zone,
          risk: data.risk,
          ts: data.ts,
          child_id: data.child_id,
          child_name: data.child_name,
          child_role: data.child_role || 'child',
          trail: newTrail,
        };
        return { children: result };
      });
    },

    clearChild: function(childId) {
      set(function(state) {
        var result: Record<string, ChildLocation> = {};
        for (var k in state.children) {
          if (k !== childId) result[k] = state.children[k];
        }
        return { children: result };
      });
    },

    clearAll: function() {
      set({ children: {} });
    },
  };
});
