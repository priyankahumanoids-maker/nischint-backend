// NISCH-008 — RTCPeerConnection lifecycle hook for live emergency
// audio streams. Caller-side (child) sends a getUserMedia audio track,
// guardian-side receives + plays through the device speaker.
//
// Hook exposes:
//   * `pc`         — the RTCPeerConnection instance (for advanced ops)
//   * `start()`    — caller path: createOffer + setLocalDescription
//   * `acceptOffer(sdp)` — callee path: setRemoteDescription + answer
//   * `acceptAnswer(sdp)` — caller path: setRemoteDescription
//   * `addRemoteIce(c)`  — both: addIceCandidate
//   * `localDescription` / `remoteAudioStream` for UI consumption
//
// Lifecycle: pc is created on first start/acceptOffer; close() tears
// it all down (including the local mic track).
//
// Privacy: this hook NEVER calls getUserMedia for video. Camera
// permission is requested by the config plugin's `cameraPermission`
// flag at install time, but we never trigger it at runtime — audio
// only for v1.
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  RTCPeerConnection,
  RTCSessionDescription,
  RTCIceCandidate,
  mediaDevices,
  MediaStream,
} from 'react-native-webrtc';

export type Role = 'caller' | 'callee';

interface UseWebRTCOptions {
  role: Role;
  iceServers: RTCIceServer[];
  onLocalDescription: (sdp: { type: string; sdp: string }) => void;
  onIceCandidate: (c: any) => void;
  onConnectionStateChange?: (state: string) => void;
  enabled: boolean;
}

export function useWebRTC({
  role, iceServers, onLocalDescription, onIceCandidate,
  onConnectionStateChange, enabled,
}: UseWebRTCOptions) {
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const localStreamRef = useRef<MediaStream | null>(null);
  const [remoteStream, setRemoteStream] = useState<MediaStream | null>(null);
  const [pcState, setPcState] = useState<string>('new');

  // Stable refs — callers may pass new closures every render but we
  // only want to subscribe once.
  const onLocalRef = useRef(onLocalDescription);
  onLocalRef.current = onLocalDescription;
  const onIceRef = useRef(onIceCandidate);
  onIceRef.current = onIceCandidate;
  const onStateRef = useRef(onConnectionStateChange);
  onStateRef.current = onConnectionStateChange;

  const buildPc = useCallback((): RTCPeerConnection => {
    const pc = new RTCPeerConnection({ iceServers });
    pcRef.current = pc;

    (pc as any).addEventListener('icecandidate', (event: any) => {
      if (event?.candidate) {
        onIceRef.current(event.candidate);
      }
    });

    (pc as any).addEventListener('connectionstatechange', () => {
      const s = (pc as any).connectionState || 'unknown';
      setPcState(s);
      onStateRef.current?.(s);
    });

    (pc as any).addEventListener('track', (event: any) => {
      // First inbound media stream → render via RTCView in the listener.
      if (event?.streams && event.streams[0]) {
        setRemoteStream(event.streams[0]);
      }
    });

    return pc;
  }, [iceServers]);

  const attachLocalAudio = useCallback(async (pc: RTCPeerConnection) => {
    if (localStreamRef.current) return;
    try {
      const stream = await mediaDevices.getUserMedia({ audio: true, video: false });
      localStreamRef.current = stream;
      stream.getTracks().forEach((t) => {
        try { pc.addTrack(t, stream); } catch {}
      });
    } catch (e) {
      if (__DEV__) console.warn('[WebRTC] mic access denied:', e);
      throw e;
    }
  }, []);

  const start = useCallback(async () => {
    if (role !== 'caller') return;
    const pc = pcRef.current || buildPc();
    await attachLocalAudio(pc);
    const offer = await (pc as any).createOffer({ offerToReceiveAudio: true });
    await (pc as any).setLocalDescription(offer);
    onLocalRef.current({ type: offer.type, sdp: offer.sdp });
  }, [role, buildPc, attachLocalAudio]);

  const acceptOffer = useCallback(async (sdp: { type: string; sdp: string }) => {
    if (role !== 'callee') return;
    const pc = pcRef.current || buildPc();
    await (pc as any).setRemoteDescription(new RTCSessionDescription(sdp));
    const answer = await (pc as any).createAnswer();
    await (pc as any).setLocalDescription(answer);
    onLocalRef.current({ type: answer.type, sdp: answer.sdp });
  }, [role, buildPc]);

  const acceptAnswer = useCallback(async (sdp: { type: string; sdp: string }) => {
    const pc = pcRef.current;
    if (!pc) return;
    await (pc as any).setRemoteDescription(new RTCSessionDescription(sdp));
  }, []);

  const addRemoteIce = useCallback(async (candidate: any) => {
    const pc = pcRef.current;
    if (!pc || !candidate) return;
    try {
      await (pc as any).addIceCandidate(new RTCIceCandidate(candidate));
    } catch (e) {
      if (__DEV__) console.warn('[WebRTC] addIceCandidate failed:', e);
    }
  }, []);

  const close = useCallback(() => {
    const pc = pcRef.current;
    pcRef.current = null;
    if (localStreamRef.current) {
      try { localStreamRef.current.getTracks().forEach((t) => t.stop()); } catch {}
      localStreamRef.current = null;
    }
    if (pc) {
      try { (pc as any).close(); } catch {}
    }
    setRemoteStream(null);
    setPcState('closed');
  }, []);

  useEffect(() => {
    if (!enabled) {
      close();
    }
    return () => close();
  }, [enabled, close]);

  return {
    start,
    acceptOffer,
    acceptAnswer,
    addRemoteIce,
    close,
    remoteStream,
    pcState,
    localStream: localStreamRef.current,
  };
}
