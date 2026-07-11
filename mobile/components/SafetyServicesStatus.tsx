// Safety Services Status — diagnostic widget showing live health of all background safety services.
// Gives users visibility into what's running: GPS, Push, Shake, Fall, Voice, Accelerometer, Network.
// Tapping a "denied" row requests the permission or opens Android Settings.

import React, { useEffect, useState, useCallback } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Linking, Platform, Alert } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import * as Location from 'expo-location';
import * as Notifications from 'expo-notifications';
import {
  getRecordingPermissionsAsync,
  requestRecordingPermissionsAsync,
} from 'expo-audio';
import { Accelerometer } from 'expo-sensors';
import NetInfo from '@react-native-community/netinfo';
import { colors, spacing, fontSize, radius } from '@/theme';

type Status = 'on' | 'off' | 'denied' | 'unknown' | 'journey-only';
type PermissionKey = 'location' | 'notifications' | 'microphone' | null;

interface Service {
  label: string;
  status: Status;
  detail?: string;
  icon: keyof typeof Ionicons.glyphMap;
  permissionKey?: PermissionKey; // which permission to request on tap
  canNeverAsk?: boolean; // if true and denied, skip request and go straight to Settings
}

const STATUS_COLOR: Record<Status, string> = {
  on: '#10B981',        // emerald green
  off: '#64748B',       // slate gray
  denied: '#EF4444',    // red
  unknown: '#F59E0B',   // amber
  'journey-only': '#3B82F6',  // blue
};

const STATUS_LABEL: Record<Status, string> = {
  on: 'Active',
  off: 'Off',
  denied: 'Denied',
  unknown: 'Checking…',
  'journey-only': 'On Journey',
};

export function SafetyServicesStatus() {
  const [expanded, setExpanded] = useState(false);
  const [requesting, setRequesting] = useState<string | null>(null);
  const [services, setServices] = useState<Service[]>([
    { label: 'GPS (Location)', status: 'unknown', icon: 'location', permissionKey: 'location' },
    { label: 'Push Notifications', status: 'unknown', icon: 'notifications', permissionKey: 'notifications' },
    { label: 'Shake Detection', status: 'unknown', icon: 'phone-portrait' },
    { label: 'Fall Detection', status: 'unknown', icon: 'warning' },
    { label: 'Voice Distress', status: 'journey-only', detail: 'Starts when you begin a journey', icon: 'mic', permissionKey: 'microphone' },
    { label: 'Network', status: 'unknown', icon: 'wifi' },
  ]);

  const refresh = useCallback(async () => {
    const next: Service[] = [];

    // 1) GPS
    try {
      const loc = await Location.getForegroundPermissionsAsync();
      next.push({
        label: 'GPS (Location)',
        status: loc.granted ? 'on' : 'denied',
        detail: loc.granted ? 'Foreground + background ready' : 'Tap to grant location',
        icon: 'location',
        permissionKey: 'location',
        canNeverAsk: !loc.granted && !loc.canAskAgain,
      });
    } catch {
      next.push({ label: 'GPS (Location)', status: 'unknown', icon: 'location', permissionKey: 'location' });
    }

    // 2) Push notifications
    try {
      const notif = await Notifications.getPermissionsAsync();
      next.push({
        label: 'Push Notifications',
        status: notif.granted ? 'on' : 'denied',
        detail: notif.granted ? 'FCM / APNs token registered' : 'Tap to grant notifications',
        icon: 'notifications',
        permissionKey: 'notifications',
        canNeverAsk: !notif.granted && !notif.canAskAgain,
      });
    } catch {
      next.push({ label: 'Push Notifications', status: 'unknown', icon: 'notifications', permissionKey: 'notifications' });
    }

    // 3) Shake detection (uses accelerometer)
    try {
      const accel = await Accelerometer.isAvailableAsync();
      next.push({
        label: 'Shake Detection',
        status: accel ? 'on' : 'off',
        detail: accel ? 'Accelerometer running · shake 3x for instant SOS' : 'Accelerometer unavailable',
        icon: 'phone-portrait',
      });
    } catch {
      next.push({ label: 'Shake Detection', status: 'unknown', icon: 'phone-portrait' });
    }

    // 4) Fall detection (uses accelerometer + gyroscope)
    try {
      const accel = await Accelerometer.isAvailableAsync();
      next.push({
        label: 'Fall Detection',
        status: accel ? 'on' : 'off',
        detail: accel ? 'Monitoring for high-impact + immobility' : 'Sensors unavailable',
        icon: 'warning',
      });
    } catch {
      next.push({ label: 'Fall Detection', status: 'unknown', icon: 'warning' });
    }

    // 5) Voice distress — explicitly NOT started at boot (by design, to avoid permission prompt abuse)
    try {
      const audio = await getRecordingPermissionsAsync();
      next.push({
        label: 'Voice Distress',
        status: audio.granted ? 'journey-only' : 'denied',
        detail: audio.granted
          ? 'Permission granted. Activates when you Start Journey.'
          : 'Tap to grant microphone for scream/whisper detection',
        icon: 'mic',
        permissionKey: 'microphone',
        canNeverAsk: !audio.granted && !audio.canAskAgain,
      });
    } catch {
      next.push({ label: 'Voice Distress', status: 'unknown', icon: 'mic', permissionKey: 'microphone' });
    }

    // 6) Network
    try {
      const nw = await NetInfo.fetch();
      next.push({
        label: 'Network',
        status: nw.isConnected && nw.isInternetReachable ? 'on' : 'denied',
        detail: nw.isConnected
          ? `${nw.type === 'wifi' ? 'Wi-Fi' : 'Mobile data'} · ${nw.isInternetReachable ? 'reachable' : 'no internet'}`
          : 'Offline — SOS will queue and send when reconnected',
        icon: 'wifi',
      });
    } catch {
      next.push({ label: 'Network', status: 'unknown', icon: 'wifi' });
    }

    setServices(next);
  }, []);

  // Request permission inline, or open Settings if system has locked it
  const handleRowTap = async (svc: Service) => {
    if (!svc.permissionKey || svc.status === 'on' || svc.status === 'journey-only') return;
    if (requesting) return;

    setRequesting(svc.label);
    try {
      if (svc.canNeverAsk) {
        // System has locked the permission — only Android Settings can fix it
        Alert.alert(
          'Permission locked',
          `${svc.label} was denied permanently. Please enable it in App Settings.`,
          [
            { text: 'Cancel', style: 'cancel' },
            { text: 'Open Settings', onPress: () => Linking.openSettings() },
          ],
        );
        return;
      }

      let result: { granted: boolean; canAskAgain?: boolean } = { granted: false };
      if (svc.permissionKey === 'location') {
        const r = await Location.requestForegroundPermissionsAsync();
        result = { granted: r.granted, canAskAgain: r.canAskAgain };
        // Also request background if foreground granted (optional, best-effort)
        if (r.granted && Platform.OS === 'android') {
          try { await Location.requestBackgroundPermissionsAsync(); } catch {}
        }
      } else if (svc.permissionKey === 'notifications') {
        const r = await Notifications.requestPermissionsAsync();
        result = { granted: r.granted, canAskAgain: r.canAskAgain };
      } else if (svc.permissionKey === 'microphone') {
        const r = await requestRecordingPermissionsAsync();
        result = { granted: r.granted, canAskAgain: r.canAskAgain };
      }

      if (!result.granted && !result.canAskAgain) {
        Alert.alert(
          'Permission denied',
          `${svc.label} is blocked. Please enable it in App Settings.`,
          [
            { text: 'Cancel', style: 'cancel' },
            { text: 'Open Settings', onPress: () => Linking.openSettings() },
          ],
        );
      }
    } catch (e: any) {
      Alert.alert('Permission error', e?.message || 'Unable to request permission');
    } finally {
      setRequesting(null);
      // Re-read status to update UI
      setTimeout(refresh, 400);
    }
  };

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 20000); // re-check every 20s
    return () => clearInterval(t);
  }, []);

  const activeCount = services.filter((s) => s.status === 'on' || s.status === 'journey-only').length;
  const deniedCount = services.filter((s) => s.status === 'denied' && s.permissionKey).length;
  const summary =
    deniedCount > 0
      ? `${activeCount}/${services.length} active · ${deniedCount} need permission`
      : `${activeCount}/${services.length} active`;
  const summaryColor = deniedCount > 0 ? '#EF4444' : '#10B981';

  // Grant all missing permissions in sequence (one Android prompt at a time)
  const grantAll = async () => {
    const denied = services.filter((s) => s.status === 'denied' && s.permissionKey);
    for (const svc of denied) {
      await handleRowTap(svc);
      // wait briefly between prompts
      await new Promise((r) => setTimeout(r, 500));
    }
    await refresh();
  };

  return (
    <View style={styles.container} testID="safety-services-status">
      <TouchableOpacity style={styles.header} onPress={() => setExpanded(!expanded)} activeOpacity={0.7}>
        <View style={styles.headerLeft}>
          <View style={[styles.statusDot, { backgroundColor: summaryColor }]} />
          <Text style={styles.title}>Safety Services</Text>
          <Text style={[styles.summary, { color: summaryColor }]}>{summary}</Text>
        </View>
        <Ionicons name={expanded ? 'chevron-up' : 'chevron-down'} size={18} color={colors.textMuted} />
      </TouchableOpacity>

      {/* Visible "Grant" CTA when NOT expanded AND there are missing permissions */}
      {!expanded && deniedCount > 0 && (
        <TouchableOpacity style={styles.grantAllBtnCompact} onPress={grantAll} testID="grant-all-permissions-compact">
          <Ionicons name="shield-checkmark" size={14} color="#fff" />
          <Text style={styles.grantAllText}>Enable {deniedCount} Missing Permission{deniedCount > 1 ? 's' : ''}</Text>
        </TouchableOpacity>
      )}

      {expanded && (
        <View style={styles.list}>
          {deniedCount > 0 && (
            <TouchableOpacity style={styles.grantAllBtn} onPress={grantAll} testID="grant-all-permissions">
              <Ionicons name="shield-checkmark" size={16} color="#fff" />
              <Text style={styles.grantAllText}>Enable All {deniedCount} Missing Permission{deniedCount > 1 ? 's' : ''}</Text>
            </TouchableOpacity>
          )}
          {services.map((s) => {
            const isRequesting = requesting === s.label;
            const canTap = s.permissionKey && s.status === 'denied';
            const RowComponent: any = canTap ? TouchableOpacity : View;
            return (
              <RowComponent
                key={s.label}
                style={[styles.row, canTap && styles.rowTappable]}
                onPress={canTap ? () => handleRowTap(s) : undefined}
                activeOpacity={0.7}
                testID={`svc-${s.label.replace(/\s+/g, '-').toLowerCase()}`}
              >
                <View style={styles.rowLeft}>
                  <Ionicons name={s.icon} size={16} color={STATUS_COLOR[s.status]} />
                  <View style={{ flex: 1, marginLeft: spacing.sm }}>
                    <Text style={styles.rowLabel}>{s.label}</Text>
                    {s.detail && <Text style={styles.rowDetail}>{s.detail}</Text>}
                  </View>
                </View>
                {canTap ? (
                  <View style={[styles.badge, styles.grantBadge]}>
                    {isRequesting ? (
                      <Text style={styles.grantBadgeText}>…</Text>
                    ) : (
                      <>
                        <Ionicons name="shield-checkmark" size={10} color="#fff" />
                        <Text style={styles.grantBadgeText}>{s.canNeverAsk ? 'Open Settings' : 'Grant'}</Text>
                      </>
                    )}
                  </View>
                ) : (
                  <View style={[styles.badge, { backgroundColor: STATUS_COLOR[s.status] + '20', borderColor: STATUS_COLOR[s.status] + '80' }]}>
                    <Text style={[styles.badgeText, { color: STATUS_COLOR[s.status] }]}>{STATUS_LABEL[s.status]}</Text>
                  </View>
                )}
              </RowComponent>
            );
          })}
          <TouchableOpacity style={styles.refreshBtn} onPress={refresh} testID="svc-refresh">
            <Ionicons name="refresh" size={14} color={colors.primary} />
            <Text style={styles.refreshText}>Refresh</Text>
          </TouchableOpacity>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    backgroundColor: colors.bgCard || 'rgba(30,41,59,0.6)',
    borderRadius: radius.lg || 12,
    borderWidth: 1,
    borderColor: 'rgba(148,163,184,0.15)',
    marginBottom: spacing.md || 12,
    overflow: 'hidden',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: spacing.md || 12,
    paddingHorizontal: spacing.md || 12,
  },
  headerLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    flex: 1,
  },
  statusDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginRight: 8,
  },
  title: {
    fontSize: fontSize.sm || 14,
    fontWeight: '700',
    color: colors.textPrimary,
  },
  summary: {
    fontSize: fontSize.xs || 12,
    marginLeft: 6,
  },
  list: {
    paddingHorizontal: spacing.md || 12,
    paddingBottom: spacing.md || 12,
    gap: 8,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 8,
    borderTopWidth: 1,
    borderTopColor: 'rgba(148,163,184,0.1)',
  },
  rowLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    flex: 1,
  },
  rowLabel: {
    fontSize: fontSize.sm || 13,
    fontWeight: '600',
    color: colors.textPrimary,
  },
  rowDetail: {
    fontSize: 10,
    color: colors.textMuted,
    marginTop: 1,
  },
  badge: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 6,
    borderWidth: 1,
  },
  badgeText: {
    fontSize: 10,
    fontWeight: '700',
  },
  refreshBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 4,
    paddingVertical: 8,
    marginTop: 4,
    borderRadius: 6,
    backgroundColor: 'rgba(14,165,233,0.1)',
  },
  refreshText: {
    fontSize: 11,
    fontWeight: '600',
    color: colors.primary,
    marginLeft: 4,
  },
  grantAllBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    paddingVertical: 10,
    paddingHorizontal: 12,
    marginTop: 4,
    marginBottom: 4,
    borderRadius: 8,
    backgroundColor: '#EF4444',
  },
  grantAllBtnCompact: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    paddingVertical: 8,
    marginHorizontal: spacing.md || 12,
    marginBottom: spacing.md || 12,
    borderRadius: 8,
    backgroundColor: '#EF4444',
  },
  grantAllText: {
    fontSize: 12,
    fontWeight: '700',
    color: '#fff',
    marginLeft: 4,
  },
  rowTappable: {
    backgroundColor: 'rgba(239,68,68,0.05)',
  },
  grantBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: '#EF4444',
    borderColor: '#DC2626',
    paddingHorizontal: 10,
  },
  grantBadgeText: {
    fontSize: 10,
    fontWeight: '700',
    color: '#fff',
    marginLeft: 2,
  },
});
