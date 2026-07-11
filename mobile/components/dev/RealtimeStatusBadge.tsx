// RealtimeStatusBadge — DEV-ONLY floating overlay for QA verification of
// the realtime singleton behaviour shipped in the May-7 audit.
//
// Renders nothing in production builds (`!__DEV__` short-circuits before
// any state is read). In dev builds it surfaces, at a glance:
//
//   • SSE connection status (per role)
//   • Seconds since the last SSE event (heartbeat freshness)
//   • Subscriber count — the singleton-correctness signal. If this ever
//     reads > 1 with a single screen mounted, the ref-counting is wrong.
//   • Retry attempt + next-backoff state during reconnects
//   • Polling state (Active / Idle) — should be Idle whenever SSE is alive
//
// Tap the badge to expand/collapse. Long-press to dismiss for the rest
// of the session (state held in memory only — re-appears on next launch).
//
// Mounted exactly ONCE at the root layout (`app/_layout.tsx`).
import React, { useEffect, useState } from 'react';
import {
  View, Text, TouchableOpacity, StyleSheet, Platform,
} from 'react-native';

import {
  isGuardianSSEAlive,
  getGuardianSSELastEvent,
  getGuardianSSESubscriberCount,
  getGuardianSSERetryAttempt,
} from '@/hooks/useGuardianSSE';
import {
  isChildSSEAlive,
  getChildSSELastEvent,
  getChildSSESubscriberCount,
} from '@/hooks/useChildSSE';

type Role = 'guardian' | 'child' | 'idle';

interface Snapshot {
  guardianAlive:    boolean;
  guardianAge:      number;        // seconds since last event, -1 if no event
  guardianSubs:     number;
  guardianRetry:    number;
  childAlive:       boolean;
  childAge:         number;
  childSubs:        number;
}

function readSnapshot(): Snapshot {
  const now = Date.now();
  const gLast = getGuardianSSELastEvent();
  const cLast = getChildSSELastEvent();
  return {
    guardianAlive: isGuardianSSEAlive(),
    guardianAge:   gLast > 0 ? Math.round((now - gLast) / 1000) : -1,
    guardianSubs:  getGuardianSSESubscriberCount(),
    guardianRetry: getGuardianSSERetryAttempt(),
    childAlive:    isChildSSEAlive(),
    childAge:      cLast > 0 ? Math.round((now - cLast) / 1000) : -1,
    childSubs:     getChildSSESubscriberCount(),
  };
}

function inferRole(snap: Snapshot): Role {
  if (snap.guardianSubs > 0) return 'guardian';
  if (snap.childSubs > 0) return 'child';
  return 'idle';
}

function statusColor(alive: boolean, retry: number): string {
  if (alive) return '#10b981';            // green
  if (retry > 0) return '#f59e0b';         // amber — backoff in progress
  return '#ef4444';                        // red — disconnected
}

function statusLabel(alive: boolean, retry: number, ageS: number): string {
  if (alive) return 'CONNECTED';
  if (retry > 0) return `RECONNECTING (#${retry})`;
  if (ageS < 0) return 'IDLE';
  return ageS > 60 ? 'STALE' : 'DISCONNECTED';
}

export function RealtimeStatusBadge() {
  // Compile-time stripped in production via Metro's __DEV__ replacement.
  if (!__DEV__) return null;

  const [snap, setSnap] = useState<Snapshot>(() => readSnapshot());
  const [expanded, setExpanded] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    if (dismissed) return;
    const t = setInterval(() => setSnap(readSnapshot()), 1000);
    return () => clearInterval(t);
  }, [dismissed]);

  if (dismissed) return null;

  const role = inferRole(snap);
  // Until a real subscriber attaches we render a translucent placeholder
  // so QA still knows the badge is mounted (rather than wondering if the
  // file is even imported).
  const alive  = role === 'guardian' ? snap.guardianAlive  : role === 'child' ? snap.childAlive  : false;
  const ageS   = role === 'guardian' ? snap.guardianAge    : role === 'child' ? snap.childAge    : -1;
  const subs   = role === 'guardian' ? snap.guardianSubs   : role === 'child' ? snap.childSubs   : 0;
  const retry  = role === 'guardian' ? snap.guardianRetry  : 0;
  const color  = statusColor(alive, retry);
  const label  = statusLabel(alive, retry, ageS);
  // Polling-coordination heuristic: we don't have a direct hook into the
  // poller, but the contract from the audit is "polling runs iff SSE is
  // not alive." Show that derived state.
  const polling = !alive && (role === 'guardian' || role === 'child');

  return (
    <View
      pointerEvents="box-none"
      style={styles.wrapper}
      testID="realtime-status-badge"
    >
      <TouchableOpacity
        accessibilityRole="button"
        onPress={() => setExpanded((e) => !e)}
        onLongPress={() => setDismissed(true)}
        delayLongPress={800}
        activeOpacity={0.85}
        style={[styles.badge, { borderLeftColor: color }]}
      >
        <View style={[styles.dot, { backgroundColor: color }]} />
        <Text style={styles.title}>
          RT · {role.toUpperCase()} · {label}
        </Text>
        {expanded && (
          <View style={styles.body}>
            <Row label="role"        value={role} />
            <Row label="sse"         value={`${alive ? 'alive' : 'down'}  age=${ageS < 0 ? '—' : `${ageS}s`}`} />
            <Row label="subs"        value={`${subs}${subs > 1 ? '  ⚠ check singleton' : ''}`}
                 warn={subs > 1 && role !== 'idle'} />
            <Row label="retry"       value={retry > 0 ? `#${retry}` : '—'} />
            <Row label="polling"     value={polling ? 'ACTIVE (fallback)' : 'IDLE (sse healthy)'} />
            <Text style={styles.hint}>tap to collapse · long-press to dismiss</Text>
          </View>
        )}
      </TouchableOpacity>
    </View>
  );
}

function Row({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <View style={styles.row}>
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={[styles.rowValue, warn ? styles.warnValue : null]}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: {
    position: 'absolute',
    bottom: Platform.OS === 'ios' ? 92 : 64, // sit above the tab bar
    right: 8,
    zIndex: 9999,
    elevation: 9999,
  },
  badge: {
    flexDirection: 'column',
    backgroundColor: 'rgba(15, 23, 42, 0.92)',
    borderLeftWidth: 3,
    borderRadius: 6,
    paddingVertical: 6,
    paddingHorizontal: 10,
    minWidth: 140,
    maxWidth: 240,
    shadowColor: '#000',
    shadowOpacity: 0.35,
    shadowRadius: 6,
    shadowOffset: { width: 0, height: 2 },
  },
  dot: {
    position: 'absolute',
    top: 9,
    left: -6,
    width: 6,
    height: 6,
    borderRadius: 3,
  },
  title: {
    color: '#f1f5f9',
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 0.4,
    fontFamily: Platform.select({ ios: 'Menlo', android: 'monospace' }),
  },
  body: {
    marginTop: 6,
    paddingTop: 6,
    borderTopWidth: 1,
    borderTopColor: 'rgba(148, 163, 184, 0.3)',
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 1,
  },
  rowLabel: {
    color: '#94a3b8',
    fontSize: 9,
    fontFamily: Platform.select({ ios: 'Menlo', android: 'monospace' }),
  },
  rowValue: {
    color: '#e2e8f0',
    fontSize: 9,
    fontFamily: Platform.select({ ios: 'Menlo', android: 'monospace' }),
  },
  warnValue: {
    color: '#fbbf24',
    fontWeight: '700',
  },
  hint: {
    color: '#64748b',
    fontSize: 8,
    marginTop: 4,
    fontStyle: 'italic',
  },
});
