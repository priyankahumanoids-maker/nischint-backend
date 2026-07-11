// NISCH-009.1 — Guardian Impact Badge.
//
// "Saved by your network — N times" — surfaces meaningful contribution
// from community-driven safety resolution. Earned, never gamified spam.
//
// Visibility rules (locked by spec):
//   * count > 0      — REQUIRED (no zero badges)
//   * confidence_low — REQUIRED to be false (≥5 system-wide community
//                      resolutions before the badge surface activates)
//   * 403 from API   — silent hide
//
// Placement: profile/header surface. Compact one-line treatment so it
// reads as an earned credential, not a celebration.
import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Modal, Pressable } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { colors } from '@/theme';
import api from '@/services/api';

interface ImpactPayload {
  guardian_id: string;
  saved_by_network_count: number;
  system_resolutions: number;
  confidence_low: boolean;
  from_cache: boolean;
}

interface Props {
  // Optional — when omitted the component fetches /me. Admin/operator
  // surfaces can pass a target user id to display somebody else's count.
  userId?: string;
}

export function ImpactBadge({ userId }: Props) {
  const [data, setData]   = useState<ImpactPayload | null>(null);
  const [open, setOpen]   = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const url = userId
          ? `/guardian/impact/${userId}`
          : '/guardian/impact/me';
        const res = await api.get<ImpactPayload>(url);
        if (!cancelled) setData(res.data);
      } catch (e: any) {
        // 403 → silent hide. Any other error → also silent (this
        // surface is decorative; we never block UI on it).
        if (__DEV__ && e?.response?.status !== 403) {
          console.warn('[IMPACT] fetch failed:', e?.message);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [userId]);

  if (!data) return null;
  if (data.confidence_low) return null;          // < 5 system-wide
  if (data.saved_by_network_count <= 0) return null;

  const n = data.saved_by_network_count;
  const labelN = n === 1 ? '1 time' : `${n} times`;

  return (
    <>
      <TouchableOpacity
        testID="guardian-impact-badge"
        accessibilityRole="button"
        accessibilityLabel={`Saved by your network ${labelN}`}
        activeOpacity={0.85}
        onPress={() => setOpen(true)}
        style={styles.badge}
      >
        <View style={styles.iconWrap}>
          <Ionicons name="shield-checkmark" size={14} color={colors.success} />
        </View>
        <Text style={styles.text}>
          Saved by your network — <Text style={styles.count}>{labelN}</Text>
        </Text>
      </TouchableOpacity>

      <Modal
        visible={open}
        transparent
        animationType="fade"
        onRequestClose={() => setOpen(false)}
      >
        <Pressable style={styles.backdrop} onPress={() => setOpen(false)} />
        <View style={styles.tooltipCard} testID="guardian-impact-tooltip">
          <Ionicons name="shield-checkmark" size={28} color={colors.success} />
          <Text style={styles.tooltipTitle}>Saved by your network</Text>
          <Text style={styles.tooltipBody}>
            Incidents where your "Mark Safe" vote contributed to an
            automatic resolution by the community.
          </Text>
          <Text style={styles.tooltipFooter}>
            Each contribution counts once — only when your network
            agreed without dispute.
          </Text>
          <TouchableOpacity
            onPress={() => setOpen(false)}
            style={styles.tooltipBtn}
            testID="guardian-impact-tooltip-close"
          >
            <Text style={styles.tooltipBtnText}>Got it</Text>
          </TouchableOpacity>
        </View>
      </Modal>
    </>
  );
}

const styles = StyleSheet.create({
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    alignSelf: 'flex-start',
    paddingHorizontal: 12,
    paddingVertical: 7,
    borderRadius: 999,
    backgroundColor: 'rgba(34,197,94,0.10)',  // colors.success @ 10%
    borderWidth: 1,
    borderColor: 'rgba(34,197,94,0.35)',
    marginTop: 8,
  },
  iconWrap: {
    width: 20,
    height: 20,
    borderRadius: 10,
    backgroundColor: 'rgba(34,197,94,0.18)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  text: {
    fontSize: 12,
    fontWeight: '600',
    color: colors.textPrimary,
    letterSpacing: 0.2,
  },
  count: {
    color: colors.success,
    fontWeight: '800',
  },
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.5)',
  },
  tooltipCard: {
    position: 'absolute',
    left: 24,
    right: 24,
    top: '32%',
    backgroundColor: colors.bgCard,
    borderRadius: 16,
    padding: 24,
    alignItems: 'center',
    gap: 10,
  },
  tooltipTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.textPrimary,
  },
  tooltipBody: {
    fontSize: 14,
    color: colors.textSecondary,
    textAlign: 'center',
    lineHeight: 20,
  },
  tooltipFooter: {
    fontSize: 12,
    color: colors.textMuted,
    textAlign: 'center',
    fontStyle: 'italic',
    marginTop: 4,
  },
  tooltipBtn: {
    marginTop: 12,
    paddingVertical: 10,
    paddingHorizontal: 24,
    backgroundColor: colors.success,
    borderRadius: 10,
  },
  tooltipBtnText: {
    color: colors.white,
    fontWeight: '700',
    fontSize: 14,
  },
});
