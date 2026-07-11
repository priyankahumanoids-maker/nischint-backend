// NISCH-008 — Child-side non-blocking banner that pops up when
// guardians can stream live audio.
//
// Design rule (locked by spec): "calm over alarm". This is a banner,
// NOT a modal — we never interrupt the SOS flow. Tap accept → we
// route to the live-stream caller screen which kicks off WebRTC.
// Auto-accept gate: when the source incident has confidence > 0.90
// the banner skips user tap and accepts immediately (the child is
// in distress; one less interaction is one more safety win).
import React, { useEffect, useState, useCallback } from 'react';
import { View, Text, TouchableOpacity, StyleSheet, Animated } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { colors } from '@/theme';
import api from '@/services/api';
import { useChildSSE } from '@/hooks/useChildSSE';

interface StreamOfferEvent {
  type: 'stream_offer';
  stream_id: string;
  incident_id: string;
  stream_type: 'audio' | 'video';
  ice_servers: any[];
  offer_timeout_seconds: number;
  ttl_seconds: number;
  timestamp: string;
}

interface OfferState {
  offer: StreamOfferEvent;
  // High-confidence incidents auto-accept after a 1s delay so the
  // child sees the banner flash but doesn't have to act. Manual
  // tap accept is also available.
  autoAccept: boolean;
  acceptedAt: number | null;
}

const AUTO_ACCEPT_CONFIDENCE_THRESHOLD = 0.90;

export function StreamBanner() {
  const [state, setState] = useState<OfferState | null>(null);
  const [busy, setBusy] = useState(false);
  const slide = React.useRef(new Animated.Value(-80)).current;

  const dismiss = useCallback(() => {
    Animated.timing(slide, {
      toValue: -80, duration: 220, useNativeDriver: true,
    }).start(() => setState(null));
  }, [slide]);

  const accept = useCallback(async (offer: StreamOfferEvent) => {
    if (busy) return;
    setBusy(true);
    try {
      // Don't await the accept POST — the caller screen will load
      // it in parallel (it needs the `connecting` state ASAP for
      // the WebRTC offer; this POST flips offered → connecting).
      api.post(`/stream/${offer.stream_id}/accept`).catch(() => {});
      router.push({
        pathname: '/stream-caller',
        params: { stream_id: offer.stream_id, incident_id: offer.incident_id },
      });
      dismiss();
    } finally {
      setBusy(false);
    }
  }, [busy, dismiss]);

  // SSE inbound — child receives stream_offer on their own incidents.
  useChildSSE((eventType, payload) => {
    if (eventType !== 'stream_offer' && eventType !== 'stream_state') return;

    if (eventType === 'stream_state' && state?.offer.stream_id === payload?.stream_id) {
      // Server-driven state change (e.g. auto-decline on offer
      // timeout, or the guardian ended the stream while the banner
      // is still showing). Drop the banner so we don't show stale
      // affordances.
      if (['ended', 'declined'].includes(payload?.state)) dismiss();
      return;
    }

    if (eventType === 'stream_offer' && payload?.stream_id) {
      const auto = (payload?.confidence ?? 0) > AUTO_ACCEPT_CONFIDENCE_THRESHOLD;
      setState({ offer: payload, autoAccept: auto, acceptedAt: null });
      Animated.timing(slide, {
        toValue: 0, duration: 240, useNativeDriver: true,
      }).start();
      if (auto) {
        // 1s eyelid — child sees the banner before media kicks on.
        setTimeout(() => accept(payload), 1000);
      }
    }
  });

  // Auto-decline timeout — match the server-side OFFER_TIMEOUT_S so
  // the banner never lingers after the offer is no longer actionable.
  useEffect(() => {
    if (!state?.offer) return;
    const t = setTimeout(() => dismiss(), state.offer.offer_timeout_seconds * 1000);
    return () => clearTimeout(t);
  }, [state?.offer, dismiss]);

  if (!state) return null;
  const { offer, autoAccept } = state;

  return (
    <Animated.View
      testID="stream-offer-banner"
      style={[styles.banner, { transform: [{ translateY: slide }] }]}
    >
      <View style={styles.iconWrap}>
        <Ionicons name="radio-outline" size={20} color={colors.white} />
      </View>
      <View style={styles.body}>
        <Text style={styles.title}>
          {autoAccept ? 'Connecting your guardians' : 'Your guardians can hear you'}
        </Text>
        <Text style={styles.sub}>
          {autoAccept
            ? 'Live audio starting in a moment…'
            : 'Tap to share live audio for help'}
        </Text>
      </View>
      <View style={styles.actions}>
        <TouchableOpacity
          testID="stream-banner-decline-btn"
          accessibilityLabel="Decline live audio"
          onPress={dismiss}
          style={styles.declineBtn}
        >
          <Ionicons name="close" size={18} color={colors.textPrimary} />
        </TouchableOpacity>
        {!autoAccept && (
          <TouchableOpacity
            testID="stream-banner-accept-btn"
            accessibilityLabel="Accept and start live audio"
            onPress={() => accept(offer)}
            disabled={busy}
            style={styles.acceptBtn}
          >
            <Ionicons name="mic" size={18} color={colors.white} />
            <Text style={styles.acceptText}>Stream</Text>
          </TouchableOpacity>
        )}
      </View>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  banner: {
    position: 'absolute',
    top: 50,
    left: 12,
    right: 12,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    padding: 14,
    backgroundColor: colors.bgCard,
    borderWidth: 1,
    borderColor: colors.error,
    borderRadius: 16,
    shadowColor: '#000',
    shadowOpacity: 0.4,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    elevation: 8,
    zIndex: 999,
  },
  iconWrap: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: colors.error,
    alignItems: 'center',
    justifyContent: 'center',
  },
  body: { flex: 1, gap: 2 },
  title: { fontSize: 14, fontWeight: '700', color: colors.textPrimary },
  sub: { fontSize: 12, color: colors.textSecondary },
  actions: { flexDirection: 'row', gap: 8, alignItems: 'center' },
  declineBtn: {
    width: 32, height: 32, borderRadius: 16,
    alignItems: 'center', justifyContent: 'center',
    backgroundColor: 'rgba(120,120,120,0.15)',
  },
  acceptBtn: {
    flexDirection: 'row', alignItems: 'center', gap: 6,
    backgroundColor: colors.error,
    paddingHorizontal: 12, paddingVertical: 8,
    borderRadius: 10,
  },
  acceptText: { color: colors.white, fontWeight: '700', fontSize: 13 },
});
