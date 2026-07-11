// NISCH-008 — Child-side caller screen.
//
// Reached when the child accepts a stream_offer banner. Owns:
//   * WebRTC PeerConnection (audio sender, role='caller')
//   * Signalling WebSocket
//   * Optional on-device recording for forensic upload (gated by
//     STREAM_RECORDING_BUCKET env on the backend — if presign 503s
//     we silently skip and the recording_url stays null)
//   * Foreground UI: red recording dot + duration + End Stream
//
// Privacy: the live mic stream is sent to guardians via WebRTC
// (peer-to-peer when possible, TURN-relayed via Twilio NTS when NAT
// blocks direct). The local recording is uploaded ONLY after the
// child ends the stream — no continuous server-side capture.
import React, { useEffect, useRef, useState, useCallback } from 'react';
import {
  View, Text, TouchableOpacity, StyleSheet, ActivityIndicator,
  Alert, BackHandler,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { router, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { colors } from '@/theme';
import api from '@/services/api';
import { useStreamSignaling, SignalMessage } from '@/hooks/useStreamSignaling';
import { useWebRTC } from '@/hooks/useWebRTC';
import {
  AudioModule,
  RecordingPresets,
} from 'expo-audio';

interface StreamSnapshot {
  stream_id: string;
  state: string;
  ice_servers: any[];
  ttl_seconds: number;
}

export default function StreamCallerScreen() {
  const { stream_id, incident_id } = useLocalSearchParams<{
    stream_id?: string; incident_id?: string;
  }>();
  const [snapshot, setSnapshot] = useState<StreamSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [elapsedS, setElapsedS] = useState(0);
  const startedAtRef = useRef<number | null>(null);
  const recorderRef = useRef<any>(null);
  const recordingUriRef = useRef<string | null>(null);
  const endedRef = useRef(false);

  // ── 1. Cold load: fetch the full envelope (we only had the id from
  //      the banner) so we can see ICE servers + state.
  useEffect(() => {
    if (!stream_id) return;
    let cancelled = false;
    (async () => {
      try {
        const init = await api.post(`/stream/${stream_id}/accept`);
        // /accept doesn't return ICE — fetch the join envelope (which
        // mints fresh ICE) for the actual handshake.
        const join = await api.get(`/stream/${stream_id}/join`);
        if (cancelled) return;
        setSnapshot({
          stream_id: stream_id,
          state: join.data?.state || 'connecting',
          ice_servers: join.data?.ice_servers || [],
          ttl_seconds: join.data?.ttl_seconds || 30,
        });
      } catch (e: any) {
        if (cancelled) return;
        setError(
          e?.response?.status === 409
            ? 'This stream already ended.'
            : 'Could not start the stream. Please try again.'
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
    start, acceptAnswer, addRemoteIce, close: closePc, pcState,
  } = useWebRTC({
    role: 'caller',
    iceServers: snapshot?.ice_servers || [],
    enabled: !!snapshot,
    onLocalDescription: (sdp) => sendSignal({ type: 'offer', sdp: sdp.sdp, sdpType: sdp.type }),
    onIceCandidate: (c) => sendSignal({ type: 'ice_candidate', candidate: c }),
    onConnectionStateChange: (s) => {
      if (s === 'connected' && startedAtRef.current === null) {
        startedAtRef.current = Date.now();
      }
    },
  });

  const sig = useStreamSignaling({
    streamId: snapshot ? stream_id! : null,
    enabled: !!snapshot,
    onMessage: (msg) => {
      if (msg.type === 'connected') {
        // Caller initiates the offer immediately on signalling open.
        start().catch((e) => setError('Microphone permission denied.'));
      } else if (msg.type === 'answer') {
        acceptAnswer({ type: 'answer', sdp: msg.sdp || msg.answer?.sdp || '' }).catch(() => {});
      } else if (msg.type === 'ice_candidate' && msg.candidate) {
        addRemoteIce(msg.candidate).catch(() => {});
      } else if (msg.type === 'end_stream') {
        teardown();
      }
    },
  });
  // Wire the ref so onLocal/onIce closures can reach send() without
  // closure-on-stale-value bugs.
  sigRef.current = { send: sig.send };

  // ── 3. On-device forensic recording. Best-effort — backend may
  //      return 503 if the bucket isn't configured; in that case we
  //      simply don't record.
  useEffect(() => {
    if (!snapshot) return;
    let cancelled = false;
    (async () => {
      try {
        const perm = await AudioModule.requestRecordingPermissionsAsync();
        if (!perm.granted || cancelled) return;
        const recorder = new AudioModule.AudioRecorder(
          RecordingPresets.HIGH_QUALITY,
        );
        recorderRef.current = recorder;
        await recorder.prepareToRecordAsync();
        await recorder.record();
      } catch (e) {
        if (__DEV__) console.warn('[STREAM_CALLER] local recording skipped:', e);
      }
    })();
    return () => { cancelled = true; };
  }, [snapshot]);

  // ── 4. Tick for the duration HUD.
  useEffect(() => {
    if (!snapshot) return;
    const t = setInterval(() => {
      if (startedAtRef.current) {
        setElapsedS(Math.floor((Date.now() - startedAtRef.current) / 1000));
      }
    }, 500);
    return () => clearInterval(t);
  }, [snapshot]);

  // ── 5. End-stream + recording upload.
  const teardown = useCallback(async () => {
    if (endedRef.current) return;
    endedRef.current = true;

    // 1. Stop recorder + capture URI for upload.
    let uri: string | null = null;
    try {
      const r = recorderRef.current;
      if (r) {
        await r.stop();
        uri = r.uri || null;
      }
    } catch {}
    recordingUriRef.current = uri;

    // 2. Tear down WebRTC + signalling.
    sendSignal({ type: 'end_stream' });
    closePc();

    // 3. Persist recording (best-effort).
    if (uri && stream_id) {
      try {
        const presign = await api.post(`/stream/${stream_id}/recording/presign`, {
          content_type: 'audio/m4a',
        });
        const putUrl = presign.data?.put_url;
        if (putUrl) {
          // Stream the file as binary PUT.
          const blob = await fetch(uri).then((r) => r.blob());
          await fetch(putUrl, {
            method: 'PUT',
            headers: { 'Content-Type': 'audio/m4a' },
            body: blob,
          });
          await api.post(`/stream/${stream_id}/recording/finalize`, {
            bucket: presign.data.bucket,
            key:    presign.data.key,
            duration_seconds: elapsedS,
          });
        }
      } catch (e) {
        if (__DEV__) console.warn('[STREAM_CALLER] recording upload skipped:', e);
      }
    }

    // 4. Final state transition + back nav.
    try {
      await api.post(`/stream/${stream_id}/end`, {
        duration_seconds: elapsedS,
      });
    } catch {}
    router.back();
  }, [stream_id, elapsedS, sendSignal, closePc]);

  // Hardware back / swipe-to-dismiss — always treat as End Stream
  // so we never leave a dangling LIVE row in the DB.
  useEffect(() => {
    const sub = BackHandler.addEventListener('hardwareBackPress', () => {
      teardown();
      return true;
    });
    return () => sub.remove();
  }, [teardown]);

  if (error) {
    return (
      <SafeAreaView style={styles.root}>
        <View style={styles.errorBlock}>
          <Ionicons name="alert-circle" size={44} color={colors.error} />
          <Text style={styles.errorTitle}>Stream not available</Text>
          <Text style={styles.errorBody}>{error}</Text>
          <TouchableOpacity onPress={() => router.back()} style={styles.endBtn}>
            <Text style={styles.endText}>Close</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  const live = pcState === 'connected';

  return (
    <SafeAreaView style={styles.root} testID="stream-caller-screen">
      <View style={styles.body}>
        <View style={[styles.recDot, !live && styles.recDotIdle]} />
        <Text style={styles.title}>
          {live ? 'Live with your guardians' : 'Connecting to your network…'}
        </Text>
        <Text style={styles.duration}>{fmtMmSs(elapsedS)}</Text>
        {!live && (
          <ActivityIndicator color={colors.error} style={{ marginTop: 12 }} />
        )}
        <Text style={styles.sub}>
          {live
            ? 'Your microphone is on. Guardians can hear you in real time.'
            : 'Hold tight — we\u2019re connecting you now.'}
        </Text>
      </View>
      <TouchableOpacity
        testID="stream-caller-end-btn"
        accessibilityLabel="End live stream"
        onPress={teardown}
        style={styles.endBtn}
        activeOpacity={0.85}
      >
        <Ionicons name="stop-circle" size={22} color={colors.white} />
        <Text style={styles.endText}>End Stream</Text>
      </TouchableOpacity>
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
  recDot: {
    width: 24, height: 24, borderRadius: 12,
    backgroundColor: colors.error, marginBottom: 8,
  },
  recDotIdle: { backgroundColor: colors.textMuted, opacity: 0.5 },
  title: { fontSize: 20, fontWeight: '700', color: colors.textPrimary, textAlign: 'center' },
  duration: { fontSize: 36, fontWeight: '800', color: colors.error, fontVariant: ['tabular-nums'] },
  sub: { fontSize: 13, color: colors.textSecondary, textAlign: 'center', marginTop: 8 },
  endBtn: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    gap: 8, marginHorizontal: 24, marginBottom: 24,
    backgroundColor: colors.error,
    paddingVertical: 14, borderRadius: 14,
  },
  endText: { color: colors.white, fontSize: 15, fontWeight: '700' },
  errorBlock: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32, gap: 12 },
  errorTitle: { fontSize: 18, fontWeight: '700', color: colors.textPrimary },
  errorBody: { fontSize: 13, color: colors.textSecondary, textAlign: 'center' },
});
