// NISCH-008 — Guardian-side listener screen.
//
// Reached when a guardian taps the "🔴 LIVE — tap to listen" affordance
// on the incident feed. Owns:
//   * WebRTC PeerConnection (audio receiver, role='callee')
//   * Signalling WebSocket
//   * RTCView mounted invisibly (just to keep the audio track alive
//     in the React tree — the actual playback is automatic on iOS/Android)
//   * Mark Safe shortcut wired into the existing NISCH-009 feedback API
//     so a listening guardian can resolve the incident without leaving.
import React, { useEffect, useRef, useState, useCallback } from 'react';
import {
  View, Text, TouchableOpacity, StyleSheet, ActivityIndicator,
  Alert,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { router, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { RTCView } from 'react-native-webrtc';
import { colors } from '@/theme';
import api from '@/services/api';
import { useStreamSignaling, SignalMessage } from '@/hooks/useStreamSignaling';
import { useWebRTC } from '@/hooks/useWebRTC';

interface JoinEnvelope {
  stream_id: string;
  incident_id: string;
  child_id: string;
  state: string;
  stream_type: string;
  ice_servers: any[];
  ttl_seconds: number;
}

export default function StreamListenerScreen() {
  const { stream_id } = useLocalSearchParams<{ stream_id?: string }>();
  const [join, setJoin] = useState<JoinEnvelope | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [elapsedS, setElapsedS] = useState(0);
  const startedAtRef = useRef<number | null>(null);
  const endedRef = useRef(false);

  // ── 1. Cold load: hit /join to mint fresh ICE + record the
  //      `guardian_join_count` bump.
  useEffect(() => {
    if (!stream_id) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await api.get(`/stream/${stream_id}/join`);
        if (cancelled) return;
        setJoin(res.data);
      } catch (e: any) {
        if (cancelled) return;
        setError(
          e?.response?.status === 409
            ? 'This stream has ended.'
            : 'Could not join the stream.'
        );
      }
    })();
    return () => { cancelled = true; };
  }, [stream_id]);

  // ── 2. WebRTC + signalling.
  const sigRef = useRef<{ send: (m: SignalMessage) => void } | null>(null);
  const sendSignal = useCallback((msg: SignalMessage) => {
    sigRef.current?.send(msg);
  }, []);

  const {
    acceptOffer, addRemoteIce, close: closePc, remoteStream, pcState,
  } = useWebRTC({
    role: 'callee',
    iceServers: join?.ice_servers || [],
    enabled: !!join,
    onLocalDescription: (sdp) => sendSignal({ type: 'answer', sdp: sdp.sdp, sdpType: sdp.type }),
    onIceCandidate: (c) => sendSignal({ type: 'ice_candidate', candidate: c }),
    onConnectionStateChange: (s) => {
      if (s === 'connected' && startedAtRef.current === null) {
        startedAtRef.current = Date.now();
      }
    },
  });

  const sig = useStreamSignaling({
    streamId: join ? stream_id! : null,
    enabled: !!join,
    onMessage: (msg) => {
      if (msg.type === 'offer') {
        acceptOffer({ type: 'offer', sdp: msg.sdp || msg.offer?.sdp || '' }).catch(() => {});
      } else if (msg.type === 'ice_candidate' && msg.candidate) {
        addRemoteIce(msg.candidate).catch(() => {});
      } else if (msg.type === 'end_stream') {
        // Caller ended → notify and pop.
        endedRef.current = true;
        Alert.alert('Stream ended', 'The child has ended the stream.', [
          { text: 'OK', onPress: () => router.back() },
        ]);
        closePc();
      }
    },
  });
  sigRef.current = { send: sig.send };

  // ── 3. Duration HUD.
  useEffect(() => {
    if (!join) return;
    const t = setInterval(() => {
      if (startedAtRef.current) {
        setElapsedS(Math.floor((Date.now() - startedAtRef.current) / 1000));
      }
    }, 500);
    return () => clearInterval(t);
  }, [join]);

  // ── 4. Mark Safe shortcut — wires into existing NISCH-009 endpoint.
  const markSafe = useCallback(async () => {
    if (!join) return;
    try {
      await api.post(`/incidents/${join.incident_id}/feedback`, {
        verdict: 'mark_safe',
      });
      Alert.alert(
        'Marked safe',
        'Your verdict has been recorded. Thank you.',
        [{ text: 'OK', onPress: () => leaveStream() }],
      );
    } catch {
      Alert.alert('Could not mark safe', 'Please try again.');
    }
  }, [join]);

  const leaveStream = useCallback(() => {
    if (endedRef.current) return;
    endedRef.current = true;
    sendSignal({ type: 'end_stream' });
    closePc();
    router.back();
  }, [sendSignal, closePc]);

  if (error) {
    return (
      <SafeAreaView style={styles.root}>
        <View style={styles.errorBlock}>
          <Ionicons name="alert-circle" size={44} color={colors.error} />
          <Text style={styles.errorTitle}>Stream unavailable</Text>
          <Text style={styles.errorBody}>{error}</Text>
          <TouchableOpacity onPress={() => router.back()} style={styles.leaveBtn}>
            <Text style={styles.leaveText}>Close</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  const live = pcState === 'connected';

  return (
    <SafeAreaView style={styles.root} testID="stream-listener-screen">
      {/* RTCView is invisible — its purpose is to keep the audio
          track in the render tree so playback continues. We never
          set video here. */}
      {remoteStream ? (
        <RTCView
          streamURL={(remoteStream as any).toURL?.() || ''}
          style={styles.hiddenAudio}
          objectFit="cover"
        />
      ) : null}

      <View style={styles.body}>
        <View style={styles.iconHero}>
          <Ionicons
            name={live ? 'mic' : 'cellular-outline'}
            size={32}
            color={live ? colors.error : colors.textMuted}
          />
        </View>
        <Text style={styles.title}>
          {live ? 'Listening live' : 'Connecting to the stream…'}
        </Text>
        <Text style={styles.duration}>{fmtMmSs(elapsedS)}</Text>
        {!live && (
          <ActivityIndicator color={colors.primary} style={{ marginTop: 12 }} />
        )}
        <Text style={styles.sub}>
          {live
            ? 'You can hear what\u2019s happening. Mark safe when the situation is OK.'
            : 'Hold tight — we\u2019re joining the stream.'}
        </Text>
      </View>

      <View style={styles.footer}>
        <TouchableOpacity
          testID="stream-listener-mark-safe-btn"
          accessibilityLabel="Mark this incident safe"
          onPress={markSafe}
          style={styles.markSafeBtn}
          activeOpacity={0.85}
        >
          <Ionicons name="shield-checkmark" size={20} color={colors.white} />
          <Text style={styles.markSafeText}>Mark Safe</Text>
        </TouchableOpacity>
        <TouchableOpacity
          testID="stream-listener-leave-btn"
          accessibilityLabel="End and leave the stream"
          onPress={leaveStream}
          style={styles.leaveBtn}
          activeOpacity={0.85}
        >
          <Ionicons name="exit-outline" size={20} color={colors.textPrimary} />
          <Text style={styles.leaveText}>Leave</Text>
        </TouchableOpacity>
      </View>
    </SafeAreaView>
  );
}

function fmtMmSs(s: number) {
  const mm = Math.floor(s / 60);
  const ss = (s % 60).toString().padStart(2, '0');
  return `${mm}:${ss}`;
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg },
  body: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24, gap: 12 },
  iconHero: {
    width: 84, height: 84, borderRadius: 42,
    backgroundColor: 'rgba(239,68,68,0.10)',
    alignItems: 'center', justifyContent: 'center',
    borderWidth: 1, borderColor: 'rgba(239,68,68,0.35)',
    marginBottom: 8,
  },
  title: { fontSize: 20, fontWeight: '700', color: colors.textPrimary, textAlign: 'center' },
  duration: { fontSize: 32, fontWeight: '800', color: colors.error, fontVariant: ['tabular-nums'] },
  sub: { fontSize: 13, color: colors.textSecondary, textAlign: 'center', marginTop: 8, lineHeight: 18 },
  footer: {
    flexDirection: 'row', gap: 10,
    marginHorizontal: 16, marginBottom: 24,
  },
  markSafeBtn: {
    flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    gap: 8, paddingVertical: 14, borderRadius: 14,
    backgroundColor: colors.success || '#10b981',
  },
  markSafeText: { color: colors.white, fontWeight: '700', fontSize: 15 },
  leaveBtn: {
    flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    gap: 8, paddingVertical: 14, borderRadius: 14,
    backgroundColor: 'transparent',
    borderWidth: 1, borderColor: colors.border,
  },
  leaveText: { color: colors.textPrimary, fontWeight: '600', fontSize: 15 },
  hiddenAudio: { width: 1, height: 1, opacity: 0, position: 'absolute' },
  errorBlock: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32, gap: 12 },
  errorTitle: { fontSize: 18, fontWeight: '700', color: colors.textPrimary },
  errorBody: { fontSize: 13, color: colors.textSecondary, textAlign: 'center' },
});
